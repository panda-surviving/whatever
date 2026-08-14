from flask import Flask, jsonify, render_template, request, Response
from pathlib import Path
from datetime import datetime, timedelta, date
import sqlite3
import requests
import threading
import re
import json
import time
import io
import csv
import uuid
import datetime as dt
from bs4 import BeautifulSoup

# numpy/pandas power the intraday RSI-divergence technical scanners
# (Crypto Technicals / Forex Technicals) ported over from the PSX
# Toolkit project. They are optional at import time so that the rest of
# the app still runs even on a minimal install; the scan routes below
# give a clear error if they are genuinely missing.
try:
    import numpy as np
    import pandas as pd
    import psx_screener as core  # RSI / divergence / trend-structure math, shared with the scanners below
    _TECHNICALS_AVAILABLE = True
except Exception:  # pragma: no cover - defensive, see requirements.txt
    _TECHNICALS_AVAILABLE = False

BASE = Path(__file__).resolve().parent
DB = BASE / "portfolio.db"

app = Flask(__name__)

PSX_SYMBOLS_URL = "https://dps.psx.com.pk/symbols"
PSX_COMPANY_URL = "https://dps.psx.com.pk/company/{symbol}"
PSX_INTRADAY_URL = "https://dps.psx.com.pk/timeseries/int/{symbol}"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120 Safari/537.36"
    )
}

SYMBOL_CACHE_MINUTES = 60
QUOTE_CACHE_SECONDS = 120

_symbol_cache = {"items": [], "time": None}
_symbol_lock = threading.Lock()

_quote_cache = {}
_quote_lock = threading.Lock()

# Bulk "all PSX stocks, live" cache. Populated by a background thread
# (see start_bulk_refresh_thread) plus refreshable on demand via
# POST /api/stocks/live/refresh. Concurrency-limited so we are not
# hammering PSX's site with 500 simultaneous requests.
_bulk_quote_cache = {"items": [], "time": None, "in_progress": False}
_technicals_cache = {}
_technicals_cache_lock = threading.Lock()
_bulk_quote_lock = threading.Lock()
_screener_result_cache = {}
_screener_cache_lock = threading.Lock()
SCREENER_CACHE_SECONDS = 10
BULK_REFRESH_MINUTES = 10
BULK_FETCH_WORKERS = 12

# MUFAP mutual fund NAV cache.
_mufap_cache = {"items": [], "time": None, "source": None}
_mufap_lock = threading.Lock()
MUFAP_CACHE_MINUTES = 30
MUFAP_NAV_URL = "https://www.mufap.com.pk/nav-all.php"

# Crypto: CoinGecko's public markets endpoint needs no API key for
# reasonable personal-use call volumes. Cached briefly since crypto
# prices move fast.
_crypto_cache = {"items": [], "time": None, "source": None}
_crypto_lock = threading.Lock()
CRYPTO_CACHE_SECONDS = 90
COINGECKO_MARKETS_URL = "https://api.coingecko.com/api/v3/coins/markets"
CRYPTO_PAGES = 2          # 2 x 250 = top 500 coins by market cap
CRYPTO_PER_PAGE = 250     # CoinGecko's max page size

# Crypto Fear & Greed Index: alternative.me's free public API, no key
# required, updated daily.
_crypto_sentiment_cache = {"data": None, "time": None}
_crypto_sentiment_lock = threading.Lock()
CRYPTO_SENTIMENT_CACHE_MINUTES = 30
ALTERNATIVE_ME_FNG_URL = "https://api.alternative.me/fng/"

# Forex: Frankfurter (ECB reference rates) needs no API key. These are
# daily ECB reference rates, not tick-by-tick, so a longer cache is fine.
_forex_cache = {"rates": {}, "time": None, "source": None, "date": None}
_forex_lock = threading.Lock()
FOREX_CACHE_MINUTES = 60
FRANKFURTER_URL = "https://api.frankfurter.dev/v1/latest"

# Live world-index / forex / commodity data, via a generic vendor
# adapter. Set MARKET_DATA_API_KEY (and optionally MARKET_DATA_PROVIDER,
# default "twelvedata") as environment variables to enable; without a
# key everything gracefully falls back to the MULTI_MARKET development
# data already used elsewhere in this file.
import os
MARKET_DATA_API_KEY = os.environ.get("MARKET_DATA_API_KEY", "").strip()
MARKET_DATA_PROVIDER = os.environ.get("MARKET_DATA_PROVIDER", "twelvedata").strip().lower()
_live_index_cache = {}
_live_index_lock = threading.Lock()
LIVE_INDEX_CACHE_SECONDS = 60

# Development values used only if a quote cannot be fetched.
FALLBACK_QUOTES = {
    "FFC": {"company": "Fauji Fertilizer Company", "sector": "Fertilizer", "price": 425.80, "change": 2.14, "volume": 8543210},
    "UBL": {"company": "United Bank Limited", "sector": "Commercial Banks", "price": 385.20, "change": 1.20, "volume": 3214560},
    "OGDC": {"company": "Oil & Gas Development Company", "sector": "Oil & Gas Exploration Companies", "price": 218.40, "change": -0.42, "volume": 12456890},
    "MARI": {"company": "Mari Energies", "sector": "Oil & Gas Exploration Companies", "price": 665.10, "change": 1.63, "volume": 4567890},
    "HBL": {"company": "Habib Bank Limited", "sector": "Commercial Banks", "price": 178.60, "change": 0.91, "volume": 6784320},
    "EFERT": {"company": "Engro Fertilizers", "sector": "Fertilizer", "price": 196.30, "change": 1.48, "volume": 7432150},
    "LUCK": {"company": "Lucky Cement", "sector": "Cement", "price": 822.40, "change": 1.74, "volume": 1987650},
    "SYS": {"company": "Systems Limited", "sector": "Technology & Communication", "price": 151.90, "change": -0.82, "volume": 5432180},
    "PPL": {"company": "Pakistan Petroleum", "sector": "Oil & Gas Exploration Companies", "price": 221.55, "change": -0.42, "volume": 2856468},
    "MCB": {"company": "MCB Bank", "sector": "Commercial Banks", "price": 302.50, "change": -0.35, "volume": 2876540},
}

KSE100 = {
    "price": 181430.02,
    "change": -346.57,
    "change_pct": -0.19,
}

SECTOR_PERFORMANCE = [
    {"sector": "Fertilizer", "change": 1.82},
    {"sector": "Cement", "change": 1.16},
    {"sector": "Commercial Banks", "change": 0.62},
    {"sector": "Technology & Communication", "change": -0.44},
    {"sector": "Oil & Gas Exploration Companies", "change": -0.18},
    {"sector": "Oil & Gas Marketing Companies", "change": 0.94},
    {"sector": "Power Generation & Distribution", "change": 1.35},
    {"sector": "Textile Composite", "change": -1.05},
    {"sector": "Textile Spinning", "change": -0.72},
    {"sector": "Textile Weaving", "change": 0.28},
    {"sector": "Sugar & Allied Industries", "change": 3.12},
    {"sector": "Pharmaceuticals", "change": 0.51},
    {"sector": "Automobile Assembler", "change": -0.85},
    {"sector": "Automobile Parts & Accessories", "change": 0.18},
    {"sector": "Insurance", "change": 0.44},
    {"sector": "Inv. Banks / Inv. Cos. / Securities Cos.", "change": -0.62},
    {"sector": "Leasing Companies", "change": 0.12},
    {"sector": "Modarabas", "change": -0.35},
    {"sector": "Chemical", "change": 0.78},
    {"sector": "Engineering", "change": 1.24},
    {"sector": "Refinery", "change": 2.15},
    {"sector": "Food & Personal Care Products", "change": -0.28},
    {"sector": "Glass & Ceramics", "change": 0.65},
    {"sector": "Paper & Board", "change": -0.18},
    {"sector": "Cable & Electrical Goods", "change": 0.92},
    {"sector": "Woollen", "change": -1.42},
    {"sector": "Synthetic & Rayon", "change": -2.05},
    {"sector": "Miscellaneous", "change": 0.36},
    {"sector": "Real Estate Investment Trust", "change": 0.58},
    {"sector": "Tobacco", "change": -0.22},
]

MACRO = [
    {"name": "Policy Rate", "value": "11.0%", "note": "Development value", "direction": "steady", "supportive": None},
    {"name": "CPI Inflation", "value": "4.1%", "note": "Development value", "direction": "falling", "supportive": True},
    {"name": "USD / PKR", "value": "279.2", "note": "Development value", "direction": "rising", "supportive": False},
    {"name": "FX Reserves", "value": "$14.3B", "note": "Development value", "direction": "rising", "supportive": True},
]


def compute_macro_signal(macro_items):
    """Small heuristic synthesis of the macro cards into a single
    headwind/tailwind read, in the same spirit as the rest of the
    development data above. Replace with a real model once macro
    trend data comes from a licensed source."""
    score = 50
    drivers_support = []
    drivers_drag = []

    for item in macro_items:
        supportive = item.get("supportive")
        if supportive is True:
            score += 12
            drivers_support.append(item["name"])
        elif supportive is False:
            score -= 12
            drivers_drag.append(item["name"])

    score = max(0, min(100, score))

    if score >= 65:
        label = "Tailwind"
    elif score <= 35:
        label = "Headwind"
    else:
        label = "Neutral"

    return {
        "score": score,
        "label": label,
        "supportive": drivers_support,
        "drag": drivers_drag,
    }

ANNOUNCEMENTS = [
    {"symbol": "PPL", "title": "Corporate / company update", "time": "Recent"},
    {"symbol": "FFC", "title": "Board / payout related update", "time": "Recent"},
    {"symbol": "OGDC", "title": "Operational / exploration update", "time": "Recent"},
]



# Portfolio360-inspired research modules.
MARKET_BREADTH = {
    "advancers": 52,
    "decliners": 41,
    "unchanged": 9,
    "new_highs": 7,
    "new_lows": 3,
}

FEAR_GREED = {
    "score": 58,
    "label": "Neutral to Greedy",
    "components": [
        {"name": "Breadth", "score": 62},
        {"name": "Momentum", "score": 57},
        {"name": "Volume", "score": 54},
        {"name": "Volatility", "score": 48},
        {"name": "52-Week Highs/Lows", "score": 59},
        {"name": "Macro", "score": 61},
    ]
}

# Sentiment across every major asset class / region, for the "Global &
# Composite Sentiment" section. Development values, same spirit as
# FEAR_GREED above — swap in real per-market sentiment feeds later.
GLOBAL_SENTIMENT = [
    {"key": "psx", "name": "PSX (Pakistan)", "score": 58, "label": "Neutral to Greedy"},
    {"key": "us", "name": "US Markets", "score": 64, "label": "Greed"},
    {"key": "crypto", "name": "Crypto", "score": 31, "label": "Fear"},
    {"key": "forex", "name": "Forex", "score": 50, "label": "Neutral"},
    {"key": "commodities", "name": "Commodities", "score": 74, "label": "Greed"},
    {"key": "uk", "name": "UK (FTSE)", "score": 55, "label": "Neutral"},
    {"key": "europe", "name": "Europe (DAX)", "score": 52, "label": "Neutral"},
    {"key": "japan", "name": "Japan (Nikkei)", "score": 60, "label": "Greed"},
    {"key": "china_hk", "name": "China / Hong Kong", "score": 41, "label": "Fear"},
    {"key": "india", "name": "India (Nifty)", "score": 66, "label": "Greed"},
    {"key": "saudi", "name": "Saudi Arabia (Tadawul)", "score": 53, "label": "Neutral"},
]

INDEX_CARDS = [
    {"symbol": "KSE100", "name": "KSE-100", "price": 181430.02, "change_pct": -0.19},
    {"symbol": "KSE30", "name": "KSE-30", "price": 54263.25, "change_pct": -0.24},
    {"symbol": "ALLSHR", "name": "All Share", "price": 109168.66, "change_pct": -0.13},
    {"symbol": "KMI30", "name": "KMI-30", "price": 255651.73, "change_pct": -0.19},
]


# ---------------------------------------------------------
# Portfolio360-homepage-style development data
#
# Everything below is clearly-labeled placeholder/development
# data, in the same spirit as KSE100 / SECTOR_PERFORMANCE / MACRO
# above. It powers the expanded Markets page (multi-market cards,
# cross-asset signals, fund flows, insider trades, seasonality,
# etc). Replace each block with a licensed feed before any public
# or commercial deployment.
# ---------------------------------------------------------

RISK_SENTIMENT = {
    "label": "Mild Risk-Off",
    "composite": -35,
    "note": "Risk assets -0.6\u03c3 across 5 tracked instruments, havens +1.0\u03c3 across 2.",
}

MULTI_MARKET = [
    {"key": "kse100", "name": "KSE 100", "price": 181430.02, "change_pct": -0.19, "change_abs": -346.57, "tone": "down"},
    {"key": "spx", "name": "S&P 500", "price": 7757.64, "change_pct": 0.62, "change_abs": 47.68, "tone": "up"},
    {"key": "dow", "name": "Dow Jones", "price": 44320.15, "change_pct": 0.38, "change_abs": 168.4, "tone": "up"},
    {"key": "nasdaq", "name": "Nasdaq", "price": 19680.22, "change_pct": 0.85, "change_abs": 166.2, "tone": "up"},
    {"key": "ftse", "name": "FTSE 100", "price": 8320.55, "change_pct": -0.22, "change_abs": -18.3, "tone": "down"},
    {"key": "dax", "name": "DAX", "price": 19540.80, "change_pct": 0.41, "change_abs": 80.1, "tone": "up"},
    {"key": "nikkei", "name": "Nikkei 225", "price": 39810.40, "change_pct": 0.95, "change_abs": 375.6, "tone": "up"},
    {"key": "hangseng", "name": "Hang Seng", "price": 18240.10, "change_pct": -0.68, "change_abs": -124.9, "tone": "down"},
    {"key": "nifty", "name": "Nifty 50", "price": 24680.35, "change_pct": 0.52, "change_abs": 128.0, "tone": "up"},
    {"key": "tadawul", "name": "Tadawul", "price": 10817.01, "change_pct": 0.05, "change_abs": 5.41, "tone": "up"},
    {"key": "btc", "name": "Bitcoin", "price": 64888, "change_pct": 0.20, "change_abs": 130, "tone": "up"},
    {"key": "gold", "name": "Gold", "price": 4399.70, "change_pct": -0.04, "change_abs": -1.60, "tone": "down"},
    {"key": "wti", "name": "WTI Crude", "price": 78.18, "change_pct": 1.43, "change_abs": 1.10, "tone": "up"},
    {"key": "usd", "name": "Forex \u00b7 USD Strength", "price": None, "label_value": "USD", "change_pct": -0.30, "tone": "down"},
    {"key": "cad", "name": "Forex \u00b7 Strongest Today", "price": None, "label_value": "CAD", "change_pct": 0.30, "tone": "up"},
]

# Extra detail shown when a Complete Market Detail card is clicked.
# Development values (52-week range, note) alongside the live/dev price
# already in MULTI_MARKET above.
MULTI_MARKET_DETAIL = {
    "kse100": {"range52w": [95000, 195000], "note": "Pakistan's benchmark index of the 100 largest KSE-listed companies by market cap."},
    "spx": {"range52w": [6800, 8100], "note": "Capitalization-weighted index of 500 large US companies."},
    "dow": {"range52w": [40200, 45500], "note": "Price-weighted index of 30 large US industrial/blue-chip companies."},
    "nasdaq": {"range52w": [17200, 20200], "note": "Tech-heavy US index, capitalization-weighted."},
    "ftse": {"range52w": [7600, 8600], "note": "UK's benchmark index of the 100 largest LSE-listed companies."},
    "dax": {"range52w": [17800, 20100], "note": "Germany's benchmark index of 40 major companies."},
    "nikkei": {"range52w": [35500, 41200], "note": "Japan's benchmark price-weighted index of 225 companies."},
    "hangseng": {"range52w": [16200, 20800], "note": "Hong Kong's benchmark index of the largest HKEX-listed companies."},
    "nifty": {"range52w": [21500, 26200], "note": "India's benchmark index of 50 large NSE-listed companies."},
    "tadawul": {"range52w": [9800, 12400], "note": "Saudi Arabia's benchmark index (Tadawul All Share)."},
    "btc": {"range52w": [38000, 82000], "note": "Bitcoin, priced in USD."},
    "gold": {"range52w": [3200, 4600], "note": "Spot gold, USD per troy ounce."},
    "wti": {"range52w": [62, 92], "note": "West Texas Intermediate crude oil, USD per barrel."},
    "usd": {"range52w": None, "note": "US Dollar Index strength read across major crosses."},
    "cad": {"range52w": None, "note": "Today's strongest-performing major currency vs USD."},
}

CROSS_ASSET_SIGNALS = [
    {"title": "Gold vs USD", "read": "Gold +3.72% / USD -0.30%", "tone": "up", "note": "Gold bid as the dollar eases, safe-haven tilt."},
    {"title": "Bitcoin vs US Equities", "read": "BTC +0.27% / S&P +0.62%", "tone": "up", "note": "Moving together, correlated risk-on."},
    {"title": "Gold vs US Risk", "read": "Gold +3.72% / S&P + BTC +0.45%", "tone": "up", "note": "Gold leading, mild rotation to safety."},
    {"title": "Commodity Leadership", "read": "Grains +2.36%", "tone": "up", "note": "Grains leading the commodity complex."},
]

CROSS_ASSET_HIGHLIGHTS = {
    "stocks": {"kse100": 181430.02, "kse100_change": -0.19, "spx": 7757.64, "spx_change": 0.62, "breadth_up": 34, "breadth_down": 65, "top_symbol": "TICL", "top_change": 28.26},
    "crypto": {"total_market_cap": "$2.31T", "market_cap_change": 0.16, "fear_greed": 31, "fear_greed_label": "Fear", "btc_dominance": "56.7%", "breadth_up": 39, "breadth_down": 36, "top_symbol": "BEAT", "top_change": 30.30},
    "forex": {"strongest": "CAD", "strongest_change": 0.30, "weakest": "PKR", "weakest_change": -0.37, "usd_pkr": 277.43, "usd_pkr_change": 0.46, "breadth_up": 22, "breadth_down": 22, "top_symbol": "CAD/PKR", "top_change": 1.01},
    "commodities": {"best_sector": "Grains", "best_change": 2.36, "worst_sector": "Livestock", "worst_change": -5.76, "gold": "$4.4K", "gold_change": 3.72, "breadth_up": 20, "breadth_down": 7, "top_symbol": "Oats", "top_change": 6.86},
}


TRENDING_STOCKS_BASE = {
    "gainers": [
        {"symbol": "TICL", "sector": "Sugar & Allied Industries", "change": 28.26, "streak": "5/5 up", "steady": True},
        {"symbol": "POWER", "sector": "Cement", "change": 16.25, "streak": "5/5 up", "steady": True},
        {"symbol": "FCEPL", "sector": "Food & Personal Care Products", "change": 16.20, "streak": "4/5 up", "steady": True},
        {"symbol": "NCPL", "sector": "Power Generation & Distribution", "change": 12.89, "streak": "4/5 up", "steady": False},
        {"symbol": "CNERGY", "sector": "Refinery", "change": 11.17, "streak": "4/5 up", "steady": True},
        {"symbol": "NPL", "sector": "Power Generation & Distribution", "change": 9.69, "streak": "3/5 up", "steady": False},
    ],
    "losers": [
        {"symbol": "IBFL", "sector": "Synthetic & Rayon", "change": -13.42, "streak": "1/5 up", "steady": False},
        {"symbol": "IMS", "sector": "Inv. Banks / Inv. Cos. / Securities Cos.", "change": -12.94, "streak": "2/5 up", "steady": False},
        {"symbol": "TSML", "sector": "Sugar & Allied Industries", "change": -12.25, "streak": "1/5 up", "steady": False},
        {"symbol": "NESTLE", "sector": "Food & Personal Care Products", "change": -3.96, "streak": "2/5 up", "steady": False},
        {"symbol": "KTML", "sector": "Textile Composite", "change": -2.69, "streak": "1/5 up", "steady": False},
        {"symbol": "SHFA", "sector": "Miscellaneous", "change": -2.44, "streak": "1/5 up", "steady": False},
    ],
}

# Trending Stocks, recalculated per selectable period. Development data:
# each period scales the 1-week base by a period-appropriate multiplier
# (longer windows compound further), so choosing a period actually
# changes the ranking shown rather than just relabeling it. Swap in a
# real per-period ranking query once historical OHLCV is available.
TRENDING_PERIOD_MULTIPLIERS = {
    "1D": 0.22, "1W": 1.0, "2W": 1.55, "3W": 1.95, "1M": 2.4,
    "3M": 4.1, "6M": 6.3, "1Y": 9.8,
}
TRENDING_PERIOD_LABELS = {
    "1D": "Daily", "1W": "1 Week", "2W": "2 Weeks", "3W": "3 Weeks", "1M": "1 Month",
    "3M": "3 Months", "6M": "6 Months", "1Y": "1 Year",
}


def get_trending_stocks(period="1W"):
    mult = TRENDING_PERIOD_MULTIPLIERS.get(period, 1.0)
    label = TRENDING_PERIOD_LABELS.get(period, "1 Week")

    def scale(rows):
        return [{**r, "change": round(r["change"] * mult, 2)} for r in rows]

    return {
        "gainers": sorted(scale(TRENDING_STOCKS_BASE["gainers"]), key=lambda r: -r["change"]),
        "losers": sorted(scale(TRENDING_STOCKS_BASE["losers"]), key=lambda r: r["change"]),
        "window": label,
        "period": period,
    }


TRENDING_STOCKS = get_trending_stocks("1W")

WEEK52 = {
    "highs": [
        {"symbol": "CNERGY", "company": "Cnergyico PK Limited", "price": 11.94, "change_pct": 6.13},
        {"symbol": "ATRL", "company": "Attock Refinery Limited", "price": 987.87, "change_pct": 0.91},
        {"symbol": "GHNI", "company": "Ghandhara Industries Limited", "price": 1239.20, "change_pct": 0.42},
    ],
    "lows": [],
}

FUND_FLOWS = {
    "foreign_mn": -3.87,
    "local_mn": 3.87,
    "session": "Fri, Aug 7 Session",
    "note": "Foreigners sold a second straight session (-$7.43mn over the run), heaviest in Oil & Gas Marketing, with Individuals and Brokers on the other side.",
    "sectors": [
        {"sector": "Everyone \u00b7 All Sectors", "foreign": -3.9, "individuals": 7.7, "mutual_funds": -0.8, "banks": -2.1, "companies": 1.0, "brokers": -0.9, "insurance": -0.8, "other": -0.2},
        {"sector": "Cement", "foreign": -0.9, "individuals": 1.3, "mutual_funds": -2.4, "banks": -0.3, "companies": 0.3, "brokers": 2.1, "insurance": -0.1, "other": 0},
        {"sector": "Commercial Banks", "foreign": -0.9, "individuals": 1.0, "mutual_funds": 1.8, "banks": -0.3, "companies": 0.8, "brokers": -2.3, "insurance": -0.1, "other": 0},
        {"sector": "Oil & Gas Marketing", "foreign": -1.6, "individuals": 1.7, "mutual_funds": -1.3, "banks": 0, "companies": -0.5, "brokers": 1.5, "insurance": 0.2, "other": 0},
        {"sector": "All Other Sectors", "foreign": 0.5, "individuals": 1.1, "mutual_funds": 0.8, "banks": -0.5, "companies": 0, "brokers": -1.4, "insurance": -0.4, "other": -0.1},
    ],
    "net_flow_30d": [-1.1, -2.3, 0.6, 1.8, 0.3, -0.4, -0.2, 0.4, 0.9, 1.1, 3.6, 0.5, 0.3, 3.4, 3.1, 1.6, 0.4, -0.3, 1.2, -0.6, 0.4, 2.0, 1.4, -0.5, -0.3, 1.3, 1.7, -0.9, -1.1, -0.7],
}

INSIDER_ACTIVITY = {
    "buys": 119,
    "sells": 75,
    "net_bn": 1.11,
    "note": "Insiders filed 119 buys against 75 sells over the last month, Rs. 1.11bn of net buying. PKGS saw the heaviest accumulation while BAPL led the selling.",
    "top_buying": [
        {"symbol": "PKGS", "company": "Packages Limited", "value": "Rs 4.09 bn", "filings": 14},
        {"symbol": "ASL", "company": "Aisha Steel Mills Limited", "value": "Rs 366.3 mn", "filings": 2},
        {"symbol": "SHFA", "company": "Shifa International Hospitals Limited", "value": "Rs 174.3 mn", "filings": 3},
        {"symbol": "MEBL", "company": "Meezan Bank Limited", "value": "Rs 162.5 mn", "filings": 1},
        {"symbol": "PACE", "company": "Pace (Pakistan) Limited", "value": "Rs 78.2 mn", "filings": 6},
    ],
    "top_selling": [
        {"symbol": "BAPL", "company": "Bawany Air Products Limited", "value": "Rs 1.88 bn", "filings": 1},
        {"symbol": "STYLERS", "company": "Stylers International Limited", "value": "Rs 388.1 mn", "filings": 9},
        {"symbol": "GCIL", "company": "Ghani Chemical Industries Limited", "value": "Rs 387.5 mn", "filings": 1},
        {"symbol": "SKRS", "company": "Sakrand Sugar Mills Limited", "value": "Rs 223.1 mn", "filings": 1},
        {"symbol": "WAVESAPP", "company": "Waves Home Appliances Limited", "value": "Rs 207.9 mn", "filings": 6},
    ],
    "monthly": [
        {"month": "Sep", "bought": 78, "sold": 34}, {"month": "Oct", "bought": 82, "sold": 40},
        {"month": "Nov", "bought": 46, "sold": 24}, {"month": "Dec", "bought": 38, "sold": 26},
        {"month": "Jan", "bought": 32, "sold": 22}, {"month": "Feb", "bought": 58, "sold": 20},
        {"month": "Mar", "bought": 52, "sold": 26}, {"month": "Apr", "bought": 46, "sold": 28},
        {"month": "May", "bought": 40, "sold": 22}, {"month": "Jun", "bought": 60, "sold": 34},
        {"month": "Jul", "bought": 30, "sold": 12}, {"month": "Aug", "bought": 10, "sold": 8},
    ],
}

SENTIMENT_HISTORY = {
    "previous_close": 61, "previous_close_label": "Greed",
    "week_ago": 63, "week_ago_label": "Greed",
    "month_ago": 28, "month_ago_label": "Fear",
    "year_ago": None, "year_ago_label": "Building",
    "advancing": 34, "flat": 1, "declining": 65,
    "read": "The KSE-100 internals read greed today, scoring 61 out of 100. Of the 5 gauges, 3 lean greed, 0 neutral, and 2 lean fear.",
}

NON_EQUITY_SENTIMENT = {
    "crypto": {"score": 31, "label": "Fear"},
    "forex": {"score": 50, "label": "Neutral"},
    "commodities": {"score": 74, "label": "Greed"},
}

BREADTH_PULSE = {
    "crypto": 39,
    "forex": 48,
    "commodities": 71,
}

TOP_STOCKS_THREE_WAYS = {
    "investor_favorites": [
        {"symbol": "FFC", "company": "Fauji Fertilizer Company Limited", "rank": 1, "marks": "2/3"},
        {"symbol": "HUBC", "company": "The Hub Power Company Limited", "rank": 2, "marks": "2/3"},
        {"symbol": "LUCK", "company": "Lucky Cement Limited", "rank": 3, "marks": "3/3"},
        {"symbol": "MEBL", "company": "Meezan Bank Limited", "rank": 4, "marks": "3/3"},
        {"symbol": "SYS", "company": "Systems Limited", "rank": 5, "marks": "2/3"},
    ],
    "fundamentals_top": [
        {"symbol": "CHCC", "company": "Cherat Cement Company Limited", "score": 75},
        {"symbol": "KTML", "company": "Kohinoor Textile Mills Limited", "score": 74},
        {"symbol": "COLG", "company": "Colgate-Palmolive (Pakistan) Limited", "score": 73},
        {"symbol": "SCBPL", "company": "Standard Chartered Bank (Pak) Ltd", "score": 73},
        {"symbol": "TGL", "company": "Tariq Glass Industries Limited", "score": 73},
    ],
    "fund_holdings": [
        {"symbol": "OGDC", "company": "Oil and Gas Development Co. Ltd.", "funds": 55},
        {"symbol": "PPL", "company": "Petroleum Company Limited", "funds": 54},
        {"symbol": "LUCK", "company": "Lucky Cement Limited", "funds": 50},
        {"symbol": "MEBL", "company": "Meezan Bank Limited", "funds": 47},
        {"symbol": "FFC", "company": "Fauji Fertilizer Company Limited", "funds": 41},
    ],
}

LEVELS_TO_PLAY = {
    "summary": {"strong_bearish": 3, "bearish": 9, "neutral": 37, "bullish": 32, "strong_bullish": 19},
    "stocks": [
        {"symbol": "POL", "conviction": "Low Conviction", "setup": "Bullish Setup", "level": 687.99, "note": "Held 683.13 through 7 tests, closed 0.71% above it."},
        {"symbol": "GAL", "conviction": "Low Conviction", "setup": "Bullish Setup", "level": 610.90, "note": "Held 604.25 through 6 tests, closed 1.09% above it."},
        {"symbol": "APL", "conviction": "Low Conviction", "setup": "Bullish Setup", "level": 549.02, "note": "Held 542.5 through 8 tests, closed 1.19% above it."},
    ],
}

SEASONALITY = {
    "months": ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
    "median": [2.0, -1.1, -0.8, 2.4, 2.6, 0.3, -0.6, 0.8, 2.3, 1.0, 3.0, 3.4],
    "hit_rate": ["8 of 11", "2 of 11", "5 of 11", "7 of 11", "6 of 11", "6 of 11", "5 of 11", "6 of 10", "6 of 10", "6 of 10", "8 of 10", "7 of 10"],
    "top_seasonal_stocks": [
        {"symbol": "NATF", "record": "Up 8 of 10 Years", "median": 7.0, "worst": "-23.3% (2020)"},
        {"symbol": "TGL", "record": "Up 7 of 10 Years", "median": 9.3, "worst": "-10.5% (2017)"},
        {"symbol": "APL", "record": "Up 7 of 10 Years", "median": 4.1, "worst": "-10.1% (2023)"},
        {"symbol": "FCCL", "record": "Up 7 of 10 Years", "median": 2.5, "worst": "-15.1% (2023)"},
        {"symbol": "CNERGY", "record": "Up 6 of 10 Years", "median": 4.5, "worst": "-18.4% (2023)"},
    ],
}

PAKISTAN_PROFILE = [
    {"key": "brent", "name": "Brent Crude Oil", "value": "90.12 USD", "trend": "up", "note": "Rising vs last month", "category": "Energy"},
    {"key": "cpi", "name": "CPI Inflation", "value": "11.10% YoY", "trend": "down", "note": "Falling vs last month", "category": "Prices"},
    {"key": "policy_rate", "name": "SBP Policy Rate", "value": "11.50%", "trend": "flat", "note": "Little changed", "category": "Monetary"},
    {"key": "current_account", "name": "Current Account", "value": "-649.00M USD", "trend": "down", "note": "Falling vs last month", "category": "External"},
    {"key": "fx_reserves", "name": "FX Reserves", "value": "22,442.00M USD", "trend": "down", "note": "Falling vs last month", "category": "External"},
    {"key": "usd_pkr", "name": "USD / PKR", "value": "277.85", "trend": "flat", "note": "Little changed", "category": "Currency"},
    {"key": "petrol", "name": "Petrol (PKR/litre)", "value": "272.50 PKR", "trend": "up", "note": "Development value — OGRA notifies actual price fortnightly", "category": "Energy"},
    {"key": "diesel", "name": "Diesel (PKR/litre)", "value": "278.90 PKR", "trend": "up", "note": "Development value — OGRA notifies actual price fortnightly", "category": "Energy"},
    {"key": "kibor_1m", "name": "KIBOR (1-Month)", "value": "11.35%", "trend": "flat", "note": "Little changed vs last week", "category": "Monetary"},
    {"key": "kibor_6m", "name": "KIBOR (6-Month)", "value": "11.62%", "trend": "down", "note": "Easing vs last month", "category": "Monetary"},
    {"key": "tbill_3m", "name": "T-Bill Yield (3-Month)", "value": "11.20%", "trend": "down", "note": "Falling at recent auctions", "category": "Monetary"},
    {"key": "tbill_12m", "name": "T-Bill Yield (12-Month)", "value": "11.05%", "trend": "down", "note": "Falling at recent auctions", "category": "Monetary"},
    {"key": "remittances", "name": "Worker Remittances", "value": "3,120M USD/mo", "trend": "up", "note": "Rising vs last month", "category": "External"},
    {"key": "exports", "name": "Exports", "value": "2,680M USD/mo", "trend": "up", "note": "Rising vs last month", "category": "Trade"},
    {"key": "imports", "name": "Imports", "value": "4,850M USD/mo", "trend": "up", "note": "Rising vs last month", "category": "Trade"},
    {"key": "trade_balance", "name": "Trade Balance", "value": "-2,170M USD/mo", "trend": "down", "note": "Deficit widening vs last month", "category": "Trade"},
    {"key": "gdp_growth", "name": "GDP Growth", "value": "2.85% YoY", "trend": "up", "note": "Improving vs last quarter", "category": "Growth"},
    {"key": "gold_pkr", "name": "Gold (per tola, PKR)", "value": "352,400 PKR", "trend": "up", "note": "Tracking global gold higher", "category": "Energy"},
]

UPCOMING_PAYOUTS = [
    {"symbol": "FFC", "ex_date": "2026-08-10", "amount": "14.50 PKR"},
    {"symbol": "EFERT", "ex_date": "2026-08-10", "amount": "1.75 PKR"},
    {"symbol": "EPQL", "ex_date": "2026-08-11", "amount": "1.00 PKR"},
    {"symbol": "BAFL", "ex_date": "2026-08-12", "amount": "1.50 PKR"},
    {"symbol": "AKBL", "ex_date": "2026-08-12", "amount": "2.00 PKR"},
]

CALENDAR_EVENTS = [
    {"date": "Fri, Aug 14", "title": "Independence Day, PSX Closed", "tag": "Market Holiday"},
    {"date": "Mon, Aug 17", "title": "Results Season Peaks", "tag": "Results Season"},
    {"date": "Tue, Aug 25", "title": "Eid Milad-un-Nabi, PSX Closed", "tag": "Market Holiday"},
    {"date": "Tue, Sep 1", "title": "Pakistan CPI Inflation Release", "tag": "Inflation Data"},
]

JOURNAL_ARTICLES = [
    {"title": "Reading A Bank Quarter Like An Investor", "category": "Markets", "blurb": "A plain-language walkthrough of what actually moves a Pakistani bank's earnings quarter to quarter, and which line items are noise."},
    {"title": "When A Sell-Off Is Just A Sell-Off", "category": "Markets", "blurb": "A framework for telling a healthy pullback apart from the start of a real down-trend, using breadth and volume together."},
    {"title": "Building A Starter PSX Watchlist", "category": "Education", "blurb": "How to narrow 500+ listed names down to a first watchlist you can actually keep up with."},
    {"title": "What Zakat On Shares Actually Covers", "category": "Personal Finance", "blurb": "The basics of how zakat is typically calculated on a brokerage portfolio, and why purification is a separate step."},
    {"title": "Dividend Yield Traps To Watch For", "category": "Education", "blurb": "A high trailing yield can be a warning sign as often as it's an opportunity. Here's how to tell the difference."},
]

JOURNAL_PODCASTS = [
    {"title": "Decoding Top-Down vs Bottoms-Up Investment Strategy", "guest": "Investor & Shareholder Activist", "episode": "Ep 12"},
    {"title": "Pakistan's Economic Outlook And Investment Strategies", "guest": "Portfolio Manager", "episode": "Ep 11"},
    {"title": "Pakistan's Stock Market & The Digital Tailwinds", "guest": "Market Strategist", "episode": "Ep 10"},
    {"title": "Buy, Hold Or Sell? A Framework For Deciding", "guest": "Independent Analyst", "episode": "Ep 9"},
]

TOOL_CATALOG = [
    {"key": "market-calc", "name": "Stock Market Calculator", "blurb": "Profit/Loss, break-even, position sizing, target price, average cost and CGT — all in one tool."},
    {"key": "zakat", "name": "Zakat Calculator", "blurb": "Assets, liabilities, nisab and zakat due summary."},
    {"key": "purification", "name": "Dividend Purification", "blurb": "Charity due from PSX dividends using a published purification rate."},
    {"key": "fire", "name": "FIRE Calculator", "blurb": "Financial Independence / Retire Early planner with a timeline projection."},
    {"key": "goal", "name": "Goal Planner", "blurb": "Target-based savings and contribution planning."},
    {"key": "sip", "name": "SIP Calculator", "blurb": "Monthly investment growth projections."},
    {"key": "compare-stocks", "name": "Compare Stocks", "blurb": "Compare symbols side by side using live market and detail data."},
    {"key": "dcf", "name": "DCF Calculator", "blurb": "Discounted cash flow valuation workspace."},
    {"key": "compare-funds", "name": "Compare Funds", "blurb": "NAV, returns and AUM comparison across funds."},
]

# Real Pakistan mutual fund directory, sourced from the person's
# uploaded MUFAP "Asset Allocation" export (July 2026 AUM figures,
# in PKR millions). Used as the fallback whenever the live MUFAP NAV
# scrape (fetch_mufap_funds) fails or is unreachable, so the Mutual
# Funds page always has the full real fund list even without a live
# connection - NAV/YTD stay None here since this export only has AUM;
# a live scrape or NAV feed fills those in when reachable.
MUFAP_FUND_DIRECTORY = [
    {'name': "786 Islamic Money Market Fund", 'amc': "786 Investments Limited", 'category': "Shariah Compliant Money Market", 'inception': "Oct 22, 2024", 'aum_mn': 705.77, 'nav': None, 'ytd': None},
    {'name': "786 Smart Fund", 'amc': "786 Investments Limited", 'category': "Shariah Compliant Income", 'inception': "May 20, 2003", 'aum_mn': 1286.25, 'nav': None, 'ytd': None},
    {'name': "ABL Cash Fund", 'amc': "ABL Asset Management Company Limited", 'category': "Money Market", 'inception': "Jul 31, 2010", 'aum_mn': 70549.0, 'nav': None, 'ytd': None},
    {'name': "ABL Financial Sector Fund Plan I", 'amc': "ABL Asset Management Company Limited", 'category': "Income", 'inception': "Aug 01, 2023", 'aum_mn': 39320.0, 'nav': None, 'ytd': None},
    {'name': "ABL Fixed Rate Plan XXVII", 'amc': "ABL Asset Management Company Limited", 'category': "Fixed Rate / Return", 'inception': "Jun 29, 2026", 'aum_mn': 29945.0, 'nav': None, 'ytd': None},
    {'name': "ABL Fixed Rate Plan XXVIII", 'amc': "ABL Asset Management Company Limited", 'category': "Fixed Rate / Return", 'inception': "Jul 15, 2026", 'aum_mn': 7779.0, 'nav': None, 'ytd': None},
    {'name': "ABL Government Securities Fund", 'amc': "ABL Asset Management Company Limited", 'category': "Income", 'inception': "Nov 29, 2011", 'aum_mn': 5420.0, 'nav': None, 'ytd': None},
    {'name': "ABL Income Fund", 'amc': "ABL Asset Management Company Limited", 'category': "Income", 'inception': "Sep 19, 2008", 'aum_mn': 4286.0, 'nav': None, 'ytd': None},
    {'name': "ABL Islamic Asset Allocation Fund", 'amc': "ABL Asset Management Company Limited", 'category': "Shariah Compliant Asset Allocation", 'inception': "May 31, 2018", 'aum_mn': 691.0, 'nav': None, 'ytd': None},
    {'name': "ABL Islamic Cash Fund", 'amc': "ABL Asset Management Company Limited", 'category': "Shariah Compliant Money Market", 'inception': "Feb 13, 2020", 'aum_mn': 10263.0, 'nav': None, 'ytd': None},
    {'name': "ABL Islamic Financial Planning Fund (Active Allocation Plan)", 'amc': "ABL Asset Management Company Limited", 'category': "Shariah Compliant Fund of Funds", 'inception': "Dec 22, 2015", 'aum_mn': 91.0, 'nav': None, 'ytd': None},
    {'name': "ABL Islamic Financial Planning Fund (Capital Preservation Plan I)", 'amc': "ABL Asset Management Company Limited", 'category': "Shariah Compliant Fund of Funds - CPPI", 'inception': "Mar 29, 2019", 'aum_mn': 54.0, 'nav': None, 'ytd': None},
    {'name': "ABL Islamic Financial Planning Fund (Conservative Allocation Plan)", 'amc': "ABL Asset Management Company Limited", 'category': "Shariah Compliant Fund of Funds", 'inception': "Dec 22, 2015", 'aum_mn': 123.0, 'nav': None, 'ytd': None},
    {'name': "ABL Islamic Income Fund", 'amc': "ABL Asset Management Company Limited", 'category': "Shariah Compliant Income", 'inception': "Jul 31, 2010", 'aum_mn': 1709.0, 'nav': None, 'ytd': None},
    {'name': "ABL Islamic Money Market Plan I", 'amc': "ABL Asset Management Company Limited", 'category': "Shariah Compliant Money Market", 'inception': "Dec 22, 2023", 'aum_mn': 48685.0, 'nav': None, 'ytd': None},
    {'name': "ABL Islamic Sovereign Plan I", 'amc': "ABL Asset Management Company Limited", 'category': "Shariah Compliant Income", 'inception': "Jul 22, 2024", 'aum_mn': 117.0, 'nav': None, 'ytd': None},
    {'name': "ABL Islamic Stock Fund", 'amc': "ABL Asset Management Company Limited", 'category': "Shariah Compliant Equity", 'inception': "Jun 11, 2013", 'aum_mn': 3935.0, 'nav': None, 'ytd': None},
    {'name': "ABL Money Market Plan I", 'amc': "ABL Asset Management Company Limited", 'category': "Money Market", 'inception': "Nov 15, 2023", 'aum_mn': 10271.0, 'nav': None, 'ytd': None},
    {'name': "ABL Optimal Asset Allocation Fund", 'amc': "ABL Asset Management Company Limited", 'category': "Asset Allocation", 'inception': "Sep 03, 2025", 'aum_mn': 424.0, 'nav': None, 'ytd': None},
    {'name': "ABL Special Saving Fund (ABL Special Saving Plan I)", 'amc': "ABL Asset Management Company Limited", 'category': "Capital Protected", 'inception': "Sep 19, 2019", 'aum_mn': 47327.0, 'nav': None, 'ytd': None},
    {'name': "ABL Special Saving Fund (ABL Special Saving Plan II)", 'amc': "ABL Asset Management Company Limited", 'category': "Capital Protected", 'inception': "Sep 20, 2019", 'aum_mn': 9344.0, 'nav': None, 'ytd': None},
    {'name': "ABL Special Saving Fund (ABL Special Saving Plan III)", 'amc': "ABL Asset Management Company Limited", 'category': "Capital Protected", 'inception': "Oct 11, 2019", 'aum_mn': 3112.0, 'nav': None, 'ytd': None},
    {'name': "ABL Special Saving Fund (ABL Special Saving Plan IV)", 'amc': "ABL Asset Management Company Limited", 'category': "Capital Protected", 'inception': "Dec 06, 2019", 'aum_mn': 4814.0, 'nav': None, 'ytd': None},
    {'name': "ABL Special Saving Fund (ABL Special Saving Plan V)", 'amc': "ABL Asset Management Company Limited", 'category': "Capital Protected", 'inception': "Feb 26, 2021", 'aum_mn': 731.0, 'nav': None, 'ytd': None},
    {'name': "ABL Special Saving Fund (ABL Special Saving Plan VI)", 'amc': "ABL Asset Management Company Limited", 'category': "Capital Protected", 'inception': "Aug 05, 2022", 'aum_mn': 3046.0, 'nav': None, 'ytd': None},
    {'name': "ABL Stock Fund", 'amc': "ABL Asset Management Company Limited", 'category': "Equity", 'inception': "Jun 28, 2009", 'aum_mn': 10514.0, 'nav': None, 'ytd': None},
    {'name': "Allied Finergy Fund", 'amc': "ABL Asset Management Company Limited", 'category': "Asset Allocation", 'inception': "Nov 23, 2018", 'aum_mn': 334.0, 'nav': None, 'ytd': None},
    {'name': "AKD Aggressive Income Fund", 'amc': "AKD Investment Management Limited", 'category': "Aggressive Fixed Income", 'inception': "Mar 22, 2007", 'aum_mn': 1288.82, 'nav': None, 'ytd': None},
    {'name': "AKD Alpha Income Fund", 'amc': "AKD Investment Management Limited", 'category': "Aggressive Fixed Income", 'inception': "Apr 10, 2026", 'aum_mn': 301.26, 'nav': None, 'ytd': None},
    {'name': "AKD Cash Fund", 'amc': "AKD Investment Management Limited", 'category': "Money Market", 'inception': "Jan 20, 2012", 'aum_mn': 2814.61, 'nav': None, 'ytd': None},
    {'name': "AKD Index Tracker Fund", 'amc': "AKD Investment Management Limited", 'category': "Index Tracker", 'inception': "Oct 11, 2005", 'aum_mn': 2038.52, 'nav': None, 'ytd': None},
    {'name': "AKD Islamic Cash Fund", 'amc': "AKD Investment Management Limited", 'category': "Shariah Compliant Money Market", 'inception': "Feb 17, 2023", 'aum_mn': 836.74, 'nav': None, 'ytd': None},
    {'name': "AKD Islamic Income Fund", 'amc': "AKD Investment Management Limited", 'category': "Shariah Compliant Income", 'inception': "Feb 20, 2018", 'aum_mn': 1904.53, 'nav': None, 'ytd': None},
    {'name': "AKD Islamic Stock Fund", 'amc': "AKD Investment Management Limited", 'category': "Shariah Compliant Equity", 'inception': "Feb 20, 2018", 'aum_mn': 408.6, 'nav': None, 'ytd': None},
    {'name': "AKD Opportunity Fund", 'amc': "AKD Investment Management Limited", 'category': "Equity", 'inception': "Mar 31, 2006", 'aum_mn': 893.35, 'nav': None, 'ytd': None},
    {'name': "Golden Arrow Stock Fund", 'amc': "AKD Investment Management Limited", 'category': "Equity", 'inception': "May 09, 1983", 'aum_mn': 3499.61, 'nav': None, 'ytd': None},
    {'name': "AL Habib Asset Allocation Fund", 'amc': "AL Habib Asset Management Limited", 'category': "Asset Allocation", 'inception': "Nov 08, 2017", 'aum_mn': None, 'nav': None, 'ytd': None},
    {'name': "AL Habib Cash Fund", 'amc': "AL Habib Asset Management Limited", 'category': "Money Market", 'inception': "Mar 10, 2011", 'aum_mn': None, 'nav': None, 'ytd': None},
    {'name': "AL Habib Fixed Return Fund Plan 19", 'amc': "AL Habib Asset Management Limited", 'category': "Fixed Rate / Return", 'inception': "Mar 06, 2025", 'aum_mn': None, 'nav': None, 'ytd': None},
    {'name': "AL Habib Fixed Return Fund Plan 23", 'amc': "AL Habib Asset Management Limited", 'category': "Fixed Rate / Return", 'inception': "Aug 22, 2025", 'aum_mn': None, 'nav': None, 'ytd': None},
    {'name': "AL Habib Fixed Return Fund Plan 28", 'amc': "AL Habib Asset Management Limited", 'category': "Fixed Rate / Return", 'inception': "Mar 06, 2026", 'aum_mn': None, 'nav': None, 'ytd': None},
    {'name': "AL Habib Fixed Return Fund Plan 31", 'amc': "AL Habib Asset Management Limited", 'category': "Fixed Rate / Return", 'inception': "Jun 22, 2026", 'aum_mn': None, 'nav': None, 'ytd': None},
    {'name': "AL Habib Fixed Return Fund Plan 32", 'amc': "AL Habib Asset Management Limited", 'category': "Fixed Rate / Return", 'inception': "Jun 16, 2026", 'aum_mn': None, 'nav': None, 'ytd': None},
    {'name': "AL Habib Fixed Return Fund Plan 33", 'amc': "AL Habib Asset Management Limited", 'category': "Fixed Rate / Return", 'inception': "Jul 17, 2026", 'aum_mn': None, 'nav': None, 'ytd': None},
    {'name': "AL Habib Government Securities Fund", 'amc': "AL Habib Asset Management Limited", 'category': "Income", 'inception': "Jul 13, 2023", 'aum_mn': None, 'nav': None, 'ytd': None},
    {'name': "AL Habib Income Fund", 'amc': "AL Habib Asset Management Limited", 'category': "Income", 'inception': "May 29, 2007", 'aum_mn': None, 'nav': None, 'ytd': None},
    {'name': "AL Habib Islamic Cash Fund", 'amc': "AL Habib Asset Management Limited", 'category': "Shariah Compliant Money Market", 'inception': "Dec 20, 2021", 'aum_mn': None, 'nav': None, 'ytd': None},
    {'name': "AL Habib Islamic Income Fund", 'amc': "AL Habib Asset Management Limited", 'category': "Shariah Compliant Income", 'inception': "Jan 23, 2017", 'aum_mn': None, 'nav': None, 'ytd': None},
    {'name': "AL Habib Islamic Money Market Fund", 'amc': "AL Habib Asset Management Limited", 'category': "Shariah Compliant Money Market", 'inception': "Mar 05, 2026", 'aum_mn': None, 'nav': None, 'ytd': None},
    {'name': "AL Habib Islamic Munafa Fund Plan 8", 'amc': "AL Habib Asset Management Limited", 'category': "Shariah Compliant Fixed Rate / Return", 'inception': "Jun 19, 2026", 'aum_mn': None, 'nav': None, 'ytd': None},
    {'name': "AL Habib Islamic Munafa Fund Plan 9", 'amc': "AL Habib Asset Management Limited", 'category': "Shariah Compliant Fixed Rate / Return", 'inception': "Jul 28, 2026", 'aum_mn': None, 'nav': None, 'ytd': None},
    {'name': "AL Habib Islamic Savings Fund", 'amc': "AL Habib Asset Management Limited", 'category': "Shariah Compliant Income", 'inception': "Dec 20, 2021", 'aum_mn': None, 'nav': None, 'ytd': None},
    {'name': "AL Habib Islamic Stock Fund", 'amc': "AL Habib Asset Management Limited", 'category': "Shariah Compliant Equity", 'inception': "Nov 09, 2012", 'aum_mn': None, 'nav': None, 'ytd': None},
    {'name': "AL Habib Money Market Fund", 'amc': "AL Habib Asset Management Limited", 'category': "Money Market", 'inception': "Dec 20, 2021", 'aum_mn': None, 'nav': None, 'ytd': None},
    {'name': "AL Habib Sovereign Income Fund Plan 1", 'amc': "AL Habib Asset Management Limited", 'category': "Income", 'inception': "Jun 03, 2025", 'aum_mn': None, 'nav': None, 'ytd': None},
    {'name': "AL Habib Sovereign Income Fund Plan 2", 'amc': "AL Habib Asset Management Limited", 'category': "Income", 'inception': "Jun 19, 2025", 'aum_mn': None, 'nav': None, 'ytd': None},
    {'name': "AL Habib Sovereign Income Fund Plan 3", 'amc': "AL Habib Asset Management Limited", 'category': "Income", 'inception': "Jun 19, 2025", 'aum_mn': None, 'nav': None, 'ytd': None},
    {'name': "AL Habib Stock Fund", 'amc': "AL Habib Asset Management Limited", 'category': "Equity", 'inception': "Oct 08, 2009", 'aum_mn': None, 'nav': None, 'ytd': None},
    {'name': "Al Meezan Mutual Fund", 'amc': "Al Meezan Investment Management Limited", 'category': "Shariah Compliant Equity", 'inception': "Jul 13, 1995", 'aum_mn': 24781.69, 'nav': None, 'ytd': None},
    {'name': "KSE Meezan Index Fund", 'amc': "Al Meezan Investment Management Limited", 'category': "Shariah Compliant Index Tracker", 'inception': "May 28, 2012", 'aum_mn': 8054.15, 'nav': None, 'ytd': None},
    {'name': "Meezan Asset Allocation Fund", 'amc': "Al Meezan Investment Management Limited", 'category': "Shariah Compliant Asset Allocation", 'inception': "Apr 18, 2016", 'aum_mn': 1428.83, 'nav': None, 'ytd': None},
    {'name': "Meezan Balanced Fund", 'amc': "Al Meezan Investment Management Limited", 'category': "Shariah Compliant Balanced", 'inception': "Dec 20, 2004", 'aum_mn': 5723.1, 'nav': None, 'ytd': None},
    {'name': "Meezan Capital Protected Fund III (Meezan Capital Secure Plan I)", 'amc': "Al Meezan Investment Management Limited", 'category': "Shariah Compliant Capital Protected", 'inception': "Mar 12, 2026", 'aum_mn': 1124.21, 'nav': None, 'ytd': None},
    {'name': "Meezan Cash Fund", 'amc': "Al Meezan Investment Management Limited", 'category': "Shariah Compliant Money Market", 'inception': "Jun 15, 2009", 'aum_mn': 170676.12, 'nav': None, 'ytd': None},
    {'name': "Meezan Daily Income Fund (MDIP I)", 'amc': "Al Meezan Investment Management Limited", 'category': "Shariah Compliant Income", 'inception': "Sep 13, 2021", 'aum_mn': 24836.94, 'nav': None, 'ytd': None},
    {'name': "Meezan Daily Income Fund (Meezan Mahana Munafa Plan)", 'amc': "Al Meezan Investment Management Limited", 'category': "Shariah Compliant Income", 'inception': "Oct 29, 2022", 'aum_mn': 1859.29, 'nav': None, 'ytd': None},
    {'name': "Meezan Daily Income Fund (Meezan Munafa Plan I)", 'amc': "Al Meezan Investment Management Limited", 'category': "Shariah Compliant Income", 'inception': "Aug 29, 2023", 'aum_mn': 79829.26, 'nav': None, 'ytd': None},
    {'name': "Meezan Daily Income Fund (Meezan Sehl Account Plan) (MSHP)", 'amc': "Al Meezan Investment Management Limited", 'category': "Shariah Compliant Income", 'inception': "Jun 19, 2023", 'aum_mn': 258.14, 'nav': None, 'ytd': None},
    {'name': "Meezan Daily Income Fund (Meezan Super Saver Plan) (MSSP)", 'amc': "Al Meezan Investment Management Limited", 'category': "Shariah Compliant Income", 'inception': "Apr 22, 2024", 'aum_mn': 1151.22, 'nav': None, 'ytd': None},
    {'name': "Meezan Dynamic Asset Allocation Fund (Meezan Dividend Yield Plan)", 'amc': "Al Meezan Investment Management Limited", 'category': "Shariah Compliant Asset Allocation", 'inception': "Aug 28, 2024", 'aum_mn': 1342.36, 'nav': None, 'ytd': None},
    {'name': "Meezan Energy Fund", 'amc': "Al Meezan Investment Management Limited", 'category': "Shariah Compliant Equity", 'inception': "Nov 30, 2016", 'aum_mn': 5176.01, 'nav': None, 'ytd': None},
    {'name': "Meezan Financial Planning Fund of Funds (Aggressive)", 'amc': "Al Meezan Investment Management Limited", 'category': "Shariah Compliant Fund of Funds", 'inception': "Apr 12, 2013", 'aum_mn': 331.69, 'nav': None, 'ytd': None},
    {'name': "Meezan Financial Planning Fund of Funds (Conservative)", 'amc': "Al Meezan Investment Management Limited", 'category': "Shariah Compliant Fund of Funds", 'inception': "Apr 12, 2013", 'aum_mn': 274.8, 'nav': None, 'ytd': None},
    {'name': "Meezan Financial Planning Fund of Funds (MAAP I)", 'amc': "Al Meezan Investment Management Limited", 'category': "Shariah Compliant Fund of Funds", 'inception': "Jul 09, 2015", 'aum_mn': 159.52, 'nav': None, 'ytd': None},
    {'name': "Meezan Financial Planning Fund of Funds (Moderate)", 'amc': "Al Meezan Investment Management Limited", 'category': "Shariah Compliant Fund of Funds", 'inception': "Apr 12, 2013", 'aum_mn': 230.88, 'nav': None, 'ytd': None},
    {'name': "Meezan Financial Planning Fund of Funds (Very Conservative Allocation Plan)", 'amc': "Al Meezan Investment Management Limited", 'category': "Shariah Compliant Fund of Funds", 'inception': "Aug 18, 2023", 'aum_mn': 44.36, 'nav': None, 'ytd': None},
    {'name': "Meezan Gold Fund", 'amc': "Al Meezan Investment Management Limited", 'category': "Shariah Compliant Commodities", 'inception': "Aug 13, 2015", 'aum_mn': 9685.75, 'nav': None, 'ytd': None},
    {'name': "Meezan Government Securities Fund Plan I", 'amc': "Al Meezan Investment Management Limited", 'category': "Shariah Compliant Income", 'inception': "Jul 03, 2026", 'aum_mn': 5868.55, 'nav': None, 'ytd': None},
    {'name': "Meezan Islamic Asaan Cash Fund", 'amc': "Al Meezan Investment Management Limited", 'category': "Shariah Compliant Money Market", 'inception': "Jan 28, 2026", 'aum_mn': 79376.56, 'nav': None, 'ytd': None},
    {'name': "Meezan Islamic Fund", 'amc': "Al Meezan Investment Management Limited", 'category': "Shariah Compliant Equity", 'inception': "Aug 08, 2003", 'aum_mn': 65514.26, 'nav': None, 'ytd': None},
    {'name': "Meezan Islamic Income Fund", 'amc': "Al Meezan Investment Management Limited", 'category': "Shariah Compliant Income", 'inception': "Jan 15, 2007", 'aum_mn': 16000.35, 'nav': None, 'ytd': None},
    {'name': "Meezan Paidaar Munafa Plan 34", 'amc': "Al Meezan Investment Management Limited", 'category': "Shariah Compliant Fixed Rate / Return", 'inception': "Feb 26, 2026", 'aum_mn': 10.39, 'nav': None, 'ytd': None},
    {'name': "Meezan Paidaar Munafa Plan 39", 'amc': "Al Meezan Investment Management Limited", 'category': "Shariah Compliant Fixed Rate / Return", 'inception': "Feb 26, 2026", 'aum_mn': 175.67, 'nav': None, 'ytd': None},
    {'name': "Meezan Paidaar Munafa Plan 43", 'amc': "Al Meezan Investment Management Limited", 'category': "Shariah Compliant Fixed Rate / Return", 'inception': "Mar 31, 2026", 'aum_mn': 130.34, 'nav': None, 'ytd': None},
    {'name': "Meezan Paidaar Munafa Plan 45", 'amc': "Al Meezan Investment Management Limited", 'category': "Shariah Compliant Fixed Rate / Return", 'inception': "Jun 22, 2026", 'aum_mn': 35121.36, 'nav': None, 'ytd': None},
    {'name': "Meezan Paidaar Munafa Plan 47", 'amc': "Al Meezan Investment Management Limited", 'category': "Shariah Compliant Fixed Rate / Return", 'inception': "May 21, 2026", 'aum_mn': 168.34, 'nav': None, 'ytd': None},
    {'name': "Meezan Paidaar Munafa Plan 48", 'amc': "Al Meezan Investment Management Limited", 'category': "Shariah Compliant Fixed Rate / Return", 'inception': "Jun 12, 2026", 'aum_mn': 421.19, 'nav': None, 'ytd': None},
    {'name': "Meezan Paidaar Munafa Plan 49", 'amc': "Al Meezan Investment Management Limited", 'category': "Shariah Compliant Fixed Rate / Return", 'inception': "Jun 16, 2026", 'aum_mn': 74065.44, 'nav': None, 'ytd': None},
    {'name': "Meezan Paidaar Munafa Plan 50", 'amc': "Al Meezan Investment Management Limited", 'category': "Shariah Compliant Fixed Rate / Return", 'inception': "Jul 29, 2026", 'aum_mn': 5205.32, 'nav': None, 'ytd': None},
    {'name': "Meezan Rozana Amdani Fund", 'amc': "Al Meezan Investment Management Limited", 'category': "Shariah Compliant Money Market", 'inception': "Dec 28, 2018", 'aum_mn': 32878.66, 'nav': None, 'ytd': None},
    {'name': "Meezan Sovereign Fund", 'amc': "Al Meezan Investment Management Limited", 'category': "Shariah Compliant Income", 'inception': "Feb 10, 2010", 'aum_mn': 9720.0, 'nav': None, 'ytd': None},
    {'name': "Meezan Strategic Allocation Fund (MSAP I)", 'amc': "Al Meezan Investment Management Limited", 'category': "Shariah Compliant Fund of Funds", 'inception': "Oct 19, 2016", 'aum_mn': 114.65, 'nav': None, 'ytd': None},
    {'name': "Meezan Strategic Allocation Fund (MSAP II)", 'amc': "Al Meezan Investment Management Limited", 'category': "Shariah Compliant Fund of Funds", 'inception': "Dec 22, 2016", 'aum_mn': 51.06, 'nav': None, 'ytd': None},
    {'name': "Meezan Strategic Allocation Fund (MSAP III)", 'amc': "Al Meezan Investment Management Limited", 'category': "Shariah Compliant Fund of Funds", 'inception': "Feb 20, 2017", 'aum_mn': 135.98, 'nav': None, 'ytd': None},
    {'name': "Meezan Strategic Allocation Fund (MSAP IV)", 'amc': "Al Meezan Investment Management Limited", 'category': "Shariah Compliant Fund of Funds", 'inception': "Apr 24, 2017", 'aum_mn': 78.98, 'nav': None, 'ytd': None},
    {'name': "Meezan Strategic Allocation Fund (MSAP V)", 'amc': "Al Meezan Investment Management Limited", 'category': "Shariah Compliant Fund of Funds", 'inception': "Aug 17, 2017", 'aum_mn': 25.19, 'nav': None, 'ytd': None},
    {'name': "Alfalah Asset Allocation Fund", 'amc': "Alfalah Asset Management Limited", 'category': "Asset Allocation", 'inception': "Jul 24, 2006", 'aum_mn': None, 'nav': None, 'ytd': None},
    {'name': "Alfalah Cash Fund - II", 'amc': "Alfalah Asset Management Limited", 'category': "Money Market", 'inception': "Dec 22, 2020", 'aum_mn': None, 'nav': None, 'ytd': None},
    {'name': "Alfalah Financial Sector Income Fund", 'amc': "Alfalah Asset Management Limited", 'category': "Income", 'inception': "Aug 02, 2023", 'aum_mn': 22164.85, 'nav': None, 'ytd': None},
    {'name': "Alfalah Financial Sector Opportunity Fund", 'amc': "Alfalah Asset Management Limited", 'category': "Income", 'inception': "Jul 05, 2013", 'aum_mn': 25216.98, 'nav': None, 'ytd': None},
    {'name': "Alfalah Financial Value Fund (Alfalah Financial Value Plan I)", 'amc': "Alfalah Asset Management Limited", 'category': "Asset Allocation", 'inception': "Oct 19, 2023", 'aum_mn': 3174.47, 'nav': None, 'ytd': None},
    {'name': "Alfalah Financial Value Fund - II", 'amc': "Alfalah Asset Management Limited", 'category': "Asset Allocation", 'inception': "Feb 10, 2025", 'aum_mn': 977.01, 'nav': None, 'ytd': None},
    {'name': "Alfalah GHP Alpha Fund", 'amc': "Alfalah Asset Management Limited", 'category': "Equity", 'inception': "Sep 09, 2008", 'aum_mn': 7947.49, 'nav': None, 'ytd': None},
    {'name': "Alfalah GHP Cash Fund", 'amc': "Alfalah Asset Management Limited", 'category': "Money Market", 'inception': "Mar 13, 2010", 'aum_mn': 14042.31, 'nav': None, 'ytd': None},
    {'name': "Alfalah GHP Income Fund", 'amc': "Alfalah Asset Management Limited", 'category': "Income", 'inception': "Apr 14, 2007", 'aum_mn': 2392.41, 'nav': None, 'ytd': None},
    {'name': "Alfalah GHP Income Multiplier Fund", 'amc': "Alfalah Asset Management Limited", 'category': "Aggressive Fixed Income", 'inception': "Jun 15, 2007", 'aum_mn': 3920.28, 'nav': None, 'ytd': None},
    {'name': "Alfalah GHP Islamic Income Fund", 'amc': "Alfalah Asset Management Limited", 'category': "Shariah Compliant Income", 'inception': "Dec 03, 2009", 'aum_mn': 1893.0, 'nav': None, 'ytd': None},
    {'name': "Alfalah GHP Islamic Prosperity Planning Fund (Alfalah GHP Islamic Active Allocation Plan II)", 'amc': "Alfalah Asset Management Limited", 'category': "Shariah Compliant Fund of Funds", 'inception': "Nov 01, 2016", 'aum_mn': 32.46, 'nav': None, 'ytd': None},
    {'name': "Alfalah GHP Islamic Prosperity Planning Fund (Alfalah GHP Islamic Balance Allocation Plan)", 'amc': "Alfalah Asset Management Limited", 'category': "Shariah Compliant Fund of Funds", 'inception': "Jun 11, 2016", 'aum_mn': 167.94, 'nav': None, 'ytd': None},
    {'name': "Alfalah GHP Islamic Prosperity Planning Fund (Alfalah GHP Islamic Moderate Allocation Plan)", 'amc': "Alfalah Asset Management Limited", 'category': "Shariah Compliant Fund of Funds", 'inception': "Jun 11, 2016", 'aum_mn': 92.34, 'nav': None, 'ytd': None},
    {'name': "Alfalah GHP Islamic Stock Fund", 'amc': "Alfalah Asset Management Limited", 'category': "Shariah Compliant Equity", 'inception': "Sep 03, 2007", 'aum_mn': 8683.15, 'nav': None, 'ytd': None},
    {'name': "Alfalah GHP Islamic Value Fund", 'amc': "Alfalah Asset Management Limited", 'category': "Shariah Compliant Asset Allocation", 'inception': "Oct 12, 2017", 'aum_mn': 842.28, 'nav': None, 'ytd': None},
    {'name': "Alfalah GHP Money Market Fund", 'amc': "Alfalah Asset Management Limited", 'category': "Money Market", 'inception': "May 27, 2010", 'aum_mn': 81689.47, 'nav': None, 'ytd': None},
    {'name': "Alfalah GHP Prosperity Planning Fund (Alfalah GHP Active Allocation Plan)", 'amc': "Alfalah Asset Management Limited", 'category': "Fund of Funds", 'inception': "Sep 12, 2015", 'aum_mn': 154.61, 'nav': None, 'ytd': None},
    {'name': "Alfalah GHP Prosperity Planning Fund (Alfalah GHP Conservative Allocation Plan)", 'amc': "Alfalah Asset Management Limited", 'category': "Fund of Funds", 'inception': "Sep 12, 2015", 'aum_mn': 410.87, 'nav': None, 'ytd': None},
    {'name': "Alfalah GHP Prosperity Planning Fund (Alfalah GHP Moderate Allocation Plan)", 'amc': "Alfalah Asset Management Limited", 'category': "Fund of Funds", 'inception': "Sep 12, 2015", 'aum_mn': 66.6, 'nav': None, 'ytd': None},
    {'name': "Alfalah GHP Sovereign Fund", 'amc': "Alfalah Asset Management Limited", 'category': "Income", 'inception': "May 10, 2014", 'aum_mn': 12826.95, 'nav': None, 'ytd': None},
    {'name': "Alfalah GHP Stock Fund", 'amc': "Alfalah Asset Management Limited", 'category': "Equity", 'inception': "Jul 15, 2008", 'aum_mn': 14422.89, 'nav': None, 'ytd': None},
    {'name': "Alfalah GHP Value Fund", 'amc': "Alfalah Asset Management Limited", 'category': "Asset Allocation", 'inception': "Oct 28, 2005", 'aum_mn': 370.01, 'nav': None, 'ytd': None},
    {'name': "Alfalah Government Securities Fund - II", 'amc': "Alfalah Asset Management Limited", 'category': "Income", 'inception': "Mar 16, 2020", 'aum_mn': 2546.31, 'nav': None, 'ytd': None},
    {'name': "Alfalah Government Securities Fund Plan I", 'amc': "Alfalah Asset Management Limited", 'category': "Income", 'inception': "Sep 10, 2024", 'aum_mn': 5049.15, 'nav': None, 'ytd': None},
    {'name': "Alfalah Government Securities Fund Plan II", 'amc': "Alfalah Asset Management Limited", 'category': "Income", 'inception': "Nov 12, 2024", 'aum_mn': 214.93, 'nav': None, 'ytd': None},
    {'name': "Alfalah Income & Growth Fund", 'amc': "Alfalah Asset Management Limited", 'category': "Aggressive Fixed Income", 'inception': "Oct 10, 2005", 'aum_mn': 1356.28, 'nav': None, 'ytd': None},
    {'name': "Alfalah Islamic Amdani Fund", 'amc': "Alfalah Asset Management Limited", 'category': "Shariah Compliant Money Market", 'inception': "Sep 21, 2020", 'aum_mn': 30953.17, 'nav': None, 'ytd': None},
    {'name': "Alfalah Islamic Asset Allocation Fund Plan I", 'amc': "Alfalah Asset Management Limited", 'category': "Shariah Compliant Asset Allocation", 'inception': "Jun 10, 2026", 'aum_mn': 162.54, 'nav': None, 'ytd': None},
    {'name': "Alfalah Islamic Income Growth Fund", 'amc': "Alfalah Asset Management Limited", 'category': "Shariah Compliant Aggressive Fixed Income", 'inception': "Apr 19, 2026", 'aum_mn': 3822.38, 'nav': None, 'ytd': None},
    {'name': "Alfalah Islamic Money Market Fund", 'amc': "Alfalah Asset Management Limited", 'category': "Shariah Compliant Money Market", 'inception': "Apr 13, 2023", 'aum_mn': 58446.51, 'nav': None, 'ytd': None},
    {'name': "Alfalah Islamic Sovereign Fund (Alfalah Islamic Sovereign Plan I)", 'amc': "Alfalah Asset Management Limited", 'category': "Shariah Compliant Income", 'inception': "Sep 26, 2023", 'aum_mn': 1595.54, 'nav': None, 'ytd': None},
    {'name': "Alfalah Islamic Sovereign Fund (Alfalah Islamic Sovereign Plan II)", 'amc': "Alfalah Asset Management Limited", 'category': "Shariah Compliant Income", 'inception': "Dec 13, 2023", 'aum_mn': 163.46, 'nav': None, 'ytd': None},
    {'name': "Alfalah Islamic Sovereign Fund (Alfalah Islamic Sovereign Plan III)", 'amc': "Alfalah Asset Management Limited", 'category': "Shariah Compliant Income", 'inception': "Aug 22, 2024", 'aum_mn': 251.94, 'nav': None, 'ytd': None},
    {'name': "Alfalah Islamic Stable Return Fund Plan XIX", 'amc': "Alfalah Asset Management Limited", 'category': "Shariah Compliant Fixed Rate / Return", 'inception': "Jul 21, 2026", 'aum_mn': 5505.6, 'nav': None, 'ytd': None},
    {'name': "Alfalah KTrade Islamic Plan VII", 'amc': "Alfalah Asset Management Limited", 'category': "Shariah Compliant Fund of Funds", 'inception': "Aug 21, 2023", 'aum_mn': None, 'nav': None, 'ytd': None},
    {'name': "Alfalah Money Market Fund - II", 'amc': "Alfalah Asset Management Limited", 'category': "Money Market", 'inception': "Dec 13, 2010", 'aum_mn': 22476.98, 'nav': None, 'ytd': None},
    {'name': "Alfalah MTS Fund", 'amc': "Alfalah Asset Management Limited", 'category': "Income", 'inception': "Apr 11, 2016", 'aum_mn': 1162.19, 'nav': None, 'ytd': None},
    {'name': "Alfalah Savings Growth Fund", 'amc': "Alfalah Asset Management Limited", 'category': "Income", 'inception': "May 11, 2007", 'aum_mn': 1998.97, 'nav': None, 'ytd': None},
    {'name': "Alfalah Special Savings Fund - I", 'amc': "Alfalah Asset Management Limited", 'category': "Capital Protected", 'inception': "Oct 01, 2021", 'aum_mn': None, 'nav': None, 'ytd': None},
    {'name': "Alfalah Special Savings Fund - II", 'amc': "Alfalah Asset Management Limited", 'category': "Capital Protected", 'inception': "Jul 26, 2022", 'aum_mn': None, 'nav': None, 'ytd': None},
    {'name': "Alfalah Stable Return Fund Plan XX", 'amc': "Alfalah Asset Management Limited", 'category': "Fixed Rate / Return", 'inception': "May 15, 2025", 'aum_mn': 1011.14, 'nav': None, 'ytd': None},
    {'name': "Alfalah Stable Return Fund Plan XXII", 'amc': "Alfalah Asset Management Limited", 'category': "Fixed Rate / Return", 'inception': "Sep 09, 2025", 'aum_mn': 1539.19, 'nav': None, 'ytd': None},
    {'name': "Alfalah Stable Return Fund Plan XXVI", 'amc': "Alfalah Asset Management Limited", 'category': "Fixed Rate / Return", 'inception': "Nov 18, 2025", 'aum_mn': 1074.35, 'nav': None, 'ytd': None},
    {'name': "Alfalah Stable Return Fund Plan XXVII", 'amc': "Alfalah Asset Management Limited", 'category': "Fixed Rate / Return", 'inception': "Mar 05, 2026", 'aum_mn': 0.0, 'nav': None, 'ytd': None},
    {'name': "Alfalah Stable Return Fund Plan XXVIII", 'amc': "Alfalah Asset Management Limited", 'category': "Fixed Rate / Return", 'inception': "May 19, 2026", 'aum_mn': 5377.02, 'nav': None, 'ytd': None},
    {'name': "Alfalah Stable Return Fund Plan XXX", 'amc': "Alfalah Asset Management Limited", 'category': "Fixed Rate / Return", 'inception': "Jun 22, 2026", 'aum_mn': 4854.6, 'nav': None, 'ytd': None},
    {'name': "Alfalah Stock Fund - II", 'amc': "Alfalah Asset Management Limited", 'category': "Equity", 'inception': "Apr 19, 2004", 'aum_mn': 1177.02, 'nav': None, 'ytd': None},
    {'name': "Alfalah Strategic Allocation Capital Preservation Plan II", 'amc': "Alfalah Asset Management Limited", 'category': "Fund of Funds", 'inception': "Apr 21, 2026", 'aum_mn': 1990.01, 'nav': None, 'ytd': None},
    {'name': "Alfalah Strategic Allocation Fund Plan - I", 'amc': "Alfalah Asset Management Limited", 'category': "Fund of Funds", 'inception': "Nov 21, 2024", 'aum_mn': 11719.12, 'nav': None, 'ytd': None},
    {'name': "Atlas Dividend Yield Fund", 'amc': "Atlas Asset Management Limited", 'category': "Equity", 'inception': "Feb 10, 2026", 'aum_mn': 1411.0, 'nav': None, 'ytd': None},
    {'name': "Atlas Financial Sector Fund", 'amc': "Atlas Asset Management Limited", 'category': "Equity", 'inception': "Feb 10, 2026", 'aum_mn': 847.0, 'nav': None, 'ytd': None},
    {'name': "Atlas Income Fund", 'amc': "Atlas Asset Management Limited", 'category': "Income", 'inception': "Mar 22, 2004", 'aum_mn': 7708.0, 'nav': None, 'ytd': None},
    {'name': "Atlas Islamic Building Materials Fund", 'amc': "Atlas Asset Management Limited", 'category': "Shariah Compliant Equity", 'inception': "Apr 01, 2026", 'aum_mn': 274.0, 'nav': None, 'ytd': None},
    {'name': "Atlas Islamic Cash Fund", 'amc': "Atlas Asset Management Limited", 'category': "Shariah Compliant Money Market", 'inception': "Jul 03, 2024", 'aum_mn': 1237.0, 'nav': None, 'ytd': None},
    {'name': "Atlas Islamic Energy Fund", 'amc': "Atlas Asset Management Limited", 'category': "Shariah Compliant Equity", 'inception': "Apr 01, 2026", 'aum_mn': 294.0, 'nav': None, 'ytd': None},
    {'name': "Atlas Islamic Fund of Funds (Atlas Aggressive Allocation Islamic Plan)", 'amc': "Atlas Asset Management Limited", 'category': "Shariah Compliant Fund of Funds", 'inception': "Jan 07, 2019", 'aum_mn': 473.0, 'nav': None, 'ytd': None},
    {'name': "Atlas Islamic Fund of Funds (Atlas Conservative Allocation Islamic Plan)", 'amc': "Atlas Asset Management Limited", 'category': "Shariah Compliant Fund of Funds", 'inception': "Jan 07, 2019", 'aum_mn': 402.0, 'nav': None, 'ytd': None},
    {'name': "Atlas Islamic Fund of Funds (Atlas Moderate Allocation Islamic Plan)", 'amc': "Atlas Asset Management Limited", 'category': "Shariah Compliant Fund of Funds", 'inception': "Jan 07, 2019", 'aum_mn': 436.0, 'nav': None, 'ytd': None},
    {'name': "Atlas Islamic Income Fund", 'amc': "Atlas Asset Management Limited", 'category': "Shariah Compliant Income", 'inception': "Oct 14, 2008", 'aum_mn': 3334.0, 'nav': None, 'ytd': None},
    {'name': "Atlas Islamic Money Market Fund", 'amc': "Atlas Asset Management Limited", 'category': "Shariah Compliant Money Market", 'inception': "Jan 07, 2021", 'aum_mn': 16153.0, 'nav': None, 'ytd': None},
    {'name': "Atlas Islamic Stock Fund", 'amc': "Atlas Asset Management Limited", 'category': "Shariah Compliant Equity", 'inception': "Jan 15, 2007", 'aum_mn': 13408.0, 'nav': None, 'ytd': None},
    {'name': "Atlas Liquid Fund", 'amc': "Atlas Asset Management Limited", 'category': "Money Market", 'inception': "Nov 23, 2021", 'aum_mn': 11154.0, 'nav': None, 'ytd': None},
    {'name': "Atlas Money Market Fund", 'amc': "Atlas Asset Management Limited", 'category': "Money Market", 'inception': "Jan 21, 2010", 'aum_mn': 56243.0, 'nav': None, 'ytd': None},
    {'name': "Atlas Sovereign Fund", 'amc': "Atlas Asset Management Limited", 'category': "Income", 'inception': "Dec 01, 2014", 'aum_mn': 2031.0, 'nav': None, 'ytd': None},
    {'name': "Atlas Stock Market Fund", 'amc': "Atlas Asset Management Limited", 'category': "Equity", 'inception': "Nov 23, 2004", 'aum_mn': 41872.0, 'nav': None, 'ytd': None},
    {'name': "AWT Islamic Asset Allocation Fund", 'amc': "AWT Investments Limited", 'category': "Shariah Compliant Asset Allocation", 'inception': "Sep 22, 2025", 'aum_mn': 155.12, 'nav': None, 'ytd': None},
    {'name': "AWT Islamic Income Fund", 'amc': "AWT Investments Limited", 'category': "Shariah Compliant Income", 'inception': "Mar 04, 2014", 'aum_mn': 60066.76, 'nav': None, 'ytd': None},
    {'name': "AWT Islamic Money Market Fund", 'amc': "AWT Investments Limited", 'category': "Shariah Compliant Money Market", 'inception': "Feb 26, 2025", 'aum_mn': 7718.96, 'nav': None, 'ytd': None},
    {'name': "AWT Islamic Stock Fund", 'amc': "AWT Investments Limited", 'category': "Shariah Compliant Equity", 'inception': "Mar 04, 2014", 'aum_mn': 3697.51, 'nav': None, 'ytd': None},
    {'name': "BMA Islamic Noor Cash Fund", 'amc': "BMA Investment Advisors Limited", 'category': "Shariah Compliant Money Market", 'inception': "May 08, 2026", 'aum_mn': 9418.59, 'nav': None, 'ytd': None},
    {'name': "BMA Money Market Fund", 'amc': "BMA Investment Advisors Limited", 'category': "Money Market", 'inception': "May 08, 2026", 'aum_mn': 2935.73, 'nav': None, 'ytd': None},
    {'name': "BMA Stock Fund", 'amc': "BMA Investment Advisors Limited", 'category': "Equity", 'inception': "May 08, 2026", 'aum_mn': 255.63, 'nav': None, 'ytd': None},
    {'name': "Faysal Halal Amdani Fund", 'amc': "Faysal Asset Management Limited", 'category': "Shariah Compliant Money Market", 'inception': "Oct 10, 2019", 'aum_mn': 43042.31, 'nav': None, 'ytd': None},
    {'name': "Faysal Halal Amdani Fund II", 'amc': "Faysal Asset Management Limited", 'category': "Shariah Compliant Income", 'inception': "Jul 02, 2025", 'aum_mn': 34372.29, 'nav': None, 'ytd': None},
    {'name': "Faysal Halal Amdani Fund III", 'amc': "Faysal Asset Management Limited", 'category': "Shariah Compliant Income", 'inception': "Dec 10, 2025", 'aum_mn': 2005.77, 'nav': None, 'ytd': None},
    {'name': "Faysal Islamic Asset Allocation Fund", 'amc': "Faysal Asset Management Limited", 'category': "Shariah Compliant Asset Allocation", 'inception': "Sep 09, 2015", 'aum_mn': 684.76, 'nav': None, 'ytd': None},
    {'name': "Faysal Islamic Asset Allocation Fund II", 'amc': "Faysal Asset Management Limited", 'category': "Shariah Compliant Asset Allocation", 'inception': "Aug 12, 2024", 'aum_mn': 3106.82, 'nav': None, 'ytd': None},
    {'name': "Faysal Islamic Asset Allocation Fund III (Faysal Shariah Flex Plan I)", 'amc': "Faysal Asset Management Limited", 'category': "Shariah Compliant Asset Allocation", 'inception': "Sep 17, 2025", 'aum_mn': 1057.89, 'nav': None, 'ytd': None},
    {'name': "Faysal Islamic Asset Allocation Fund III (Faysal Shariah Flex Plan II)", 'amc': "Faysal Asset Management Limited", 'category': "Shariah Compliant Asset Allocation", 'inception': "Nov 25, 2025", 'aum_mn': 1822.62, 'nav': None, 'ytd': None},
    {'name': "Faysal Islamic Asset Allocation Fund III (Faysal Shariah Flex Plan III)", 'amc': "Faysal Asset Management Limited", 'category': "Shariah Compliant Asset Allocation", 'inception': "Jan 19, 2026", 'aum_mn': 4407.54, 'nav': None, 'ytd': None},
    {'name': "Faysal Islamic Asset Allocation Fund IV (Faysal Shariah Flex Plan IV)", 'amc': "Faysal Asset Management Limited", 'category': "Shariah Compliant Asset Allocation", 'inception': "May 11, 2026", 'aum_mn': 2730.1, 'nav': None, 'ytd': None},
    {'name': "Faysal Islamic Asset Allocation Fund IV (Faysal Shariah Flex Plan V)", 'amc': "Faysal Asset Management Limited", 'category': "Shariah Compliant Asset Allocation", 'inception': "May 14, 2026", 'aum_mn': 7024.8, 'nav': None, 'ytd': None},
    {'name': "Faysal Islamic Asset Allocation Fund IV (Faysal Shariah Flex Plan VI)", 'amc': "Faysal Asset Management Limited", 'category': "Shariah Compliant Asset Allocation", 'inception': "May 15, 2026", 'aum_mn': 3878.12, 'nav': None, 'ytd': None},
    {'name': "Faysal Islamic Cash Fund", 'amc': "Faysal Asset Management Limited", 'category': "Shariah Compliant Money Market", 'inception': "Aug 11, 2020", 'aum_mn': 34141.45, 'nav': None, 'ytd': None},
    {'name': "Faysal Islamic Financial Growth Fund (Faysal Islamic Financial Growth Plan I)", 'amc': "Faysal Asset Management Limited", 'category': "Shariah Compliant Aggressive Fixed Income", 'inception': "Jul 25, 2023", 'aum_mn': 6779.05, 'nav': None, 'ytd': None},
    {'name': "Faysal Islamic Financial Growth Fund (Faysal Islamic Financial Growth Plan II)", 'amc': "Faysal Asset Management Limited", 'category': "Shariah Compliant Aggressive Fixed Income", 'inception': "Aug 06, 2024", 'aum_mn': 15804.0, 'nav': None, 'ytd': None},
    {'name': "Faysal Islamic Financial Growth Fund II", 'amc': "Faysal Asset Management Limited", 'category': "Shariah Compliant Aggressive Fixed Income", 'inception': "Dec 10, 2025", 'aum_mn': 9478.26, 'nav': None, 'ytd': None},
    {'name': "Faysal Islamic Financial Planning Fund II (Faysal Priority Ascend Plan I)", 'amc': "Faysal Asset Management Limited", 'category': "Shariah Compliant Fund of Funds", 'inception': "Jul 18, 2025", 'aum_mn': 179.87, 'nav': None, 'ytd': None},
    {'name': "Faysal Islamic Financial Planning Fund II (Faysal Priority Ascend Plan II)", 'amc': "Faysal Asset Management Limited", 'category': "Shariah Compliant Fund of Funds", 'inception': "Aug 11, 2025", 'aum_mn': 200.6, 'nav': None, 'ytd': None},
    {'name': "Faysal Islamic Financial Planning Fund II (Faysal Priority Ascend Plan III)", 'amc': "Faysal Asset Management Limited", 'category': "Shariah Compliant Fund of Funds", 'inception': "May 29, 2025", 'aum_mn': 6226.16, 'nav': None, 'ytd': None},
    {'name': "Faysal Islamic Mustakil Munafa Fund (Faysal Islamic Mehdood Muddat Plan XXI)", 'amc': "Faysal Asset Management Limited", 'category': "Shariah Compliant Fixed Rate / Return", 'inception': "May 21, 2026", 'aum_mn': 9209.64, 'nav': None, 'ytd': None},
    {'name': "Faysal Islamic Mustakil Munafa Fund (Faysal Islamic Mehdood Muddat Plan XXV)", 'amc': "Faysal Asset Management Limited", 'category': "Shariah Compliant Fixed Rate / Return", 'inception': "Jul 09, 2026", 'aum_mn': 7059.17, 'nav': None, 'ytd': None},
    {'name': "Faysal Islamic Mustakil Munafa Fund (Faysal Islamic Mehdood Muddat Plan XXVI)", 'amc': "Faysal Asset Management Limited", 'category': "Shariah Compliant Fixed Rate / Return", 'inception': "Jul 15, 2026", 'aum_mn': 14421.77, 'nav': None, 'ytd': None},
    {'name': "Faysal Islamic Mustakil Munafa Fund (Faysal Islamic Mehdood Muddat Plan XXVII)", 'amc': "Faysal Asset Management Limited", 'category': "Shariah Compliant Fixed Rate / Return", 'inception': "Jul 16, 2026", 'aum_mn': 22997.09, 'nav': None, 'ytd': None},
    {'name': "Faysal Islamic Mustakil Munafa Fund (Faysal Islamic Mehdood Muddat Plan XXVIII)", 'amc': "Faysal Asset Management Limited", 'category': "Shariah Compliant Fixed Rate / Return", 'inception': "Jul 29, 2026", 'aum_mn': 30077.58, 'nav': None, 'ytd': None},
    {'name': "Faysal Islamic Savings Growth Fund", 'amc': "Faysal Asset Management Limited", 'category': "Shariah Compliant Income", 'inception': "Jun 16, 2010", 'aum_mn': 3498.38, 'nav': None, 'ytd': None},
    {'name': "Faysal Islamic Sovereign Fund (Faysal Islamic Sovereign Plan I)", 'amc': "Faysal Asset Management Limited", 'category': "Shariah Compliant Income", 'inception': "Feb 01, 2023", 'aum_mn': 1069.42, 'nav': None, 'ytd': None},
    {'name': "Faysal Islamic Sovereign Fund (Faysal Islamic Sovereign Plan II)", 'amc': "Faysal Asset Management Limited", 'category': "Shariah Compliant Income", 'inception': "Jan 08, 2024", 'aum_mn': 959.65, 'nav': None, 'ytd': None},
    {'name': "Faysal Islamic Special Income Plan I", 'amc': "Faysal Asset Management Limited", 'category': "Shariah Compliant Income", 'inception': "Jun 20, 2022", 'aum_mn': 197.24, 'nav': None, 'ytd': None},
    {'name': "Faysal Islamic Stock Fund", 'amc': "Faysal Asset Management Limited", 'category': "Shariah Compliant Equity", 'inception': "Jul 24, 2020", 'aum_mn': 2431.74, 'nav': None, 'ytd': None},
    {'name': "Faysal Islamic Stock Fund II", 'amc': "Faysal Asset Management Limited", 'category': "Shariah Compliant Equity", 'inception': "Mar 10, 2025", 'aum_mn': 1016.0, 'nav': None, 'ytd': None},
    {'name': "Faysal Khushal Mustaqbil Fund (Faysal Barak’ah Women Savers Plan)", 'amc': "Faysal Asset Management Limited", 'category': "Shariah Compliant Fund of Funds", 'inception': "Jan 10, 2025", 'aum_mn': 51.99, 'nav': None, 'ytd': None},
    {'name': "Faysal Khushal Mustaqbil Fund (Faysal Nu’umah Women Savers Plan)", 'amc': "Faysal Asset Management Limited", 'category': "Shariah Compliant Fund of Funds", 'inception': "Jan 10, 2025", 'aum_mn': 75.61, 'nav': None, 'ytd': None},
    {'name': "First Capital Mutual Fund", 'amc': "First Capital Investments Limited", 'category': "Equity", 'inception': "May 24, 1995", 'aum_mn': 234.99, 'nav': None, 'ytd': None},
    {'name': "HBL Cash Fund", 'amc': "HBL Asset Management Limited", 'category': "Money Market", 'inception': "Dec 13, 2010", 'aum_mn': None, 'nav': None, 'ytd': None},
    {'name': "HBL Energy Fund", 'amc': "HBL Asset Management Limited", 'category': "Equity", 'inception': "Jan 20, 2006", 'aum_mn': None, 'nav': None, 'ytd': None},
    {'name': "HBL Equity Fund", 'amc': "HBL Asset Management Limited", 'category': "Equity", 'inception': "Sep 26, 2011", 'aum_mn': 1436.0, 'nav': None, 'ytd': None},
    {'name': "HBL Financial Sector Income Fund Plan I", 'amc': "HBL Asset Management Limited", 'category': "Income", 'inception': "Jan 18, 2022", 'aum_mn': 20214.0, 'nav': None, 'ytd': None},
    {'name': "HBL Financial Sector Income Fund Plan II", 'amc': "HBL Asset Management Limited", 'category': "Income", 'inception': "Feb 19, 2024", 'aum_mn': 10332.0, 'nav': None, 'ytd': None},
    {'name': "HBL Government Securities Fund", 'amc': "HBL Asset Management Limited", 'category': "Income", 'inception': "Jul 24, 2010", 'aum_mn': None, 'nav': None, 'ytd': None},
    {'name': "HBL Growth Fund-Class A", 'amc': "HBL Asset Management Limited", 'category': "Equity", 'inception': "Jul 02, 2018", 'aum_mn': None, 'nav': None, 'ytd': None},
    {'name': "HBL Growth Fund-Class B", 'amc': "HBL Asset Management Limited", 'category': "Equity", 'inception': "Jul 02, 2018", 'aum_mn': None, 'nav': None, 'ytd': None},
    {'name': "HBL Income Fund", 'amc': "HBL Asset Management Limited", 'category': "Income", 'inception': "Feb 19, 2007", 'aum_mn': None, 'nav': None, 'ytd': None},
    {'name': "HBL Investment Fund-Class A", 'amc': "HBL Asset Management Limited", 'category': "Equity", 'inception': "Jul 02, 2018", 'aum_mn': None, 'nav': None, 'ytd': None},
    {'name': "HBL Investment Fund-Class B", 'amc': "HBL Asset Management Limited", 'category': "Equity", 'inception': "Jul 02, 2018", 'aum_mn': None, 'nav': None, 'ytd': None},
    {'name': "HBL Islamic Asset Allocation Fund", 'amc': "HBL Asset Management Limited", 'category': "Shariah Compliant Asset Allocation", 'inception': "Jan 11, 2016", 'aum_mn': None, 'nav': None, 'ytd': None},
    {'name': "HBL Islamic Equity Fund", 'amc': "HBL Asset Management Limited", 'category': "Shariah Compliant Equity", 'inception': "May 29, 2014", 'aum_mn': 1225.0, 'nav': None, 'ytd': None},
    {'name': "HBL Islamic Fixed Term Fund Plan IV", 'amc': "HBL Asset Management Limited", 'category': "Shariah Compliant Fixed Rate / Return", 'inception': "Feb 24, 2026", 'aum_mn': None, 'nav': None, 'ytd': None},
    {'name': "HBL Islamic Fixed Term Fund Plan VII", 'amc': "HBL Asset Management Limited", 'category': "Shariah Compliant Fixed Rate / Return", 'inception': "Apr 02, 2026", 'aum_mn': None, 'nav': None, 'ytd': None},
    {'name': "HBL Islamic Fixed Term Fund Plan VIII", 'amc': "HBL Asset Management Limited", 'category': "Shariah Compliant Fixed Rate / Return", 'inception': "May 14, 2026", 'aum_mn': None, 'nav': None, 'ytd': None},
    {'name': "HBL Islamic Fixed Term Fund Plan X", 'amc': "HBL Asset Management Limited", 'category': "Shariah Compliant Fixed Rate / Return", 'inception': "Jun 29, 2026", 'aum_mn': 8861.39, 'nav': None, 'ytd': None},
    {'name': "HBL Islamic Income Fund", 'amc': "HBL Asset Management Limited", 'category': "Shariah Compliant Income", 'inception': "May 29, 2014", 'aum_mn': 11731.0, 'nav': None, 'ytd': None},
    {'name': "HBL Islamic Money Market Fund", 'amc': "HBL Asset Management Limited", 'category': "Shariah Compliant Money Market", 'inception': "May 09, 2011", 'aum_mn': None, 'nav': None, 'ytd': None},
    {'name': "HBL Islamic Regualar Income Fund", 'amc': "HBL Asset Management Limited", 'category': "Shariah Compliant Income", 'inception': "May 08, 2026", 'aum_mn': None, 'nav': None, 'ytd': None},
    {'name': "HBL Islamic Savings Plan I", 'amc': "HBL Asset Management Limited", 'category': "Shariah Compliant Money Market", 'inception': "Mar 13, 2024", 'aum_mn': None, 'nav': None, 'ytd': None},
    {'name': "HBL Islamic Stock Fund", 'amc': "HBL Asset Management Limited", 'category': "Shariah Compliant Equity", 'inception': "May 09, 2011", 'aum_mn': 1124.93, 'nav': None, 'ytd': None},
    {'name': "HBL Mehfooz Munafa Fund Plan XI", 'amc': "HBL Asset Management Limited", 'category': "Fixed Rate / Return", 'inception': "Oct 24, 2025", 'aum_mn': None, 'nav': None, 'ytd': None},
    {'name': "HBL Mehfooz Munafa Fund Plan XIV", 'amc': "HBL Asset Management Limited", 'category': "Fixed Rate / Return", 'inception': "Jun 08, 2026", 'aum_mn': None, 'nav': None, 'ytd': None},
    {'name': "HBL Mehfooz Munafa Fund Plan XVIII", 'amc': "HBL Asset Management Limited", 'category': "Fixed Rate / Return", 'inception': "Jun 30, 2026", 'aum_mn': None, 'nav': None, 'ytd': None},
    {'name': "HBL Mehfooz Munafa Fund Plan XXI", 'amc': "HBL Asset Management Limited", 'category': "Fixed Rate / Return", 'inception': "Jul 17, 2026", 'aum_mn': None, 'nav': None, 'ytd': None},
    {'name': "HBL Money Market Fund", 'amc': "HBL Asset Management Limited", 'category': "Money Market", 'inception': "Jul 15, 2010", 'aum_mn': None, 'nav': None, 'ytd': None},
    {'name': "HBL Multi Asset Fund", 'amc': "HBL Asset Management Limited", 'category': "Balanced", 'inception': "Nov 08, 2007", 'aum_mn': None, 'nav': None, 'ytd': None},
    {'name': "HBL Regular Income Fund", 'amc': "HBL Asset Management Limited", 'category': "Income", 'inception': "May 08, 2026", 'aum_mn': None, 'nav': None, 'ytd': None},
    {'name': "HBL Stock Fund", 'amc': "HBL Asset Management Limited", 'category': "Equity", 'inception': "Aug 23, 2007", 'aum_mn': None, 'nav': None, 'ytd': None},
    {'name': "JS Cash Fund", 'amc': "JS Investments Limited", 'category': "Money Market", 'inception': "Mar 29, 2010", 'aum_mn': 4655.06, 'nav': None, 'ytd': None},
    {'name': "JS Fixed Term Munafa Fund (JS Fixed Term Munafa Plan I)", 'amc': "JS Investments Limited", 'category': "Fixed Rate / Return", 'inception': "Jan 08, 2024", 'aum_mn': 2308.27, 'nav': None, 'ytd': None},
    {'name': "JS Fixed Term Munafa Fund (JS Fixed Term Munafa Plan XX)", 'amc': "JS Investments Limited", 'category': "Fixed Rate / Return", 'inception': "Jan 22, 2026", 'aum_mn': 3026.8, 'nav': None, 'ytd': None},
    {'name': "JS Fixed Term Munafa Fund (JS Fixed Term Munafa Plan XXI)", 'amc': "JS Investments Limited", 'category': "Fixed Rate / Return", 'inception': "Feb 02, 2026", 'aum_mn': 501.98, 'nav': None, 'ytd': None},
    {'name': "JS Fixed Term Munafa Fund (JS Fixed Term Munafa Plan XXII)", 'amc': "JS Investments Limited", 'category': "Fixed Rate / Return", 'inception': "Apr 27, 2026", 'aum_mn': 888.14, 'nav': None, 'ytd': None},
    {'name': "JS Fixed Term Munafa Fund II (JS Fixed Term Munafa Plan IX)", 'amc': "JS Investments Limited", 'category': "Fixed Rate / Return", 'inception': "May 06, 2026", 'aum_mn': 28.11, 'nav': None, 'ytd': None},
    {'name': "JS Fixed Term Munafa Fund II (JS Fixed Term Munafa Plan VI)", 'amc': "JS Investments Limited", 'category': "Fixed Rate / Return", 'inception': "Nov 10, 2025", 'aum_mn': 1481.23, 'nav': None, 'ytd': None},
    {'name': "JS Fixed Term Munafa Fund II (JS Fixed Term Munafa Plan VII)", 'amc': "JS Investments Limited", 'category': "Fixed Rate / Return", 'inception': "Mar 02, 2026", 'aum_mn': 147.64, 'nav': None, 'ytd': None},
    {'name': "JS Fund of Funds", 'amc': "JS Investments Limited", 'category': "Fund of Funds", 'inception': "Oct 31, 2005", 'aum_mn': 2089.81, 'nav': None, 'ytd': None},
    {'name': "JS Government Securities Fund", 'amc': "JS Investments Limited", 'category': "Income", 'inception': "Jul 15, 2022", 'aum_mn': 8034.59, 'nav': None, 'ytd': None},
    {'name': "JS Growth Fund", 'amc': "JS Investments Limited", 'category': "Equity", 'inception': "Jun 06, 2006", 'aum_mn': 4122.5, 'nav': None, 'ytd': None},
    {'name': "JS Income Fund", 'amc': "JS Investments Limited", 'category': "Income", 'inception': "Aug 26, 2002", 'aum_mn': 3020.13, 'nav': None, 'ytd': None},
    {'name': "JS Islamic Fixed Term Munafa Fund Plan 1", 'amc': "JS Investments Limited", 'category': "Shariah Compliant Fixed Rate / Return", 'inception': "Apr 28, 2026", 'aum_mn': None, 'nav': None, 'ytd': None},
    {'name': "JS Islamic Fund", 'amc': "JS Investments Limited", 'category': "Shariah Compliant Equity", 'inception': "Dec 27, 2002", 'aum_mn': 554.05, 'nav': None, 'ytd': None},
    {'name': "JS Islamic Income Fund", 'amc': "JS Investments Limited", 'category': "Shariah Compliant Income", 'inception': "Jun 05, 2013", 'aum_mn': 1010.41, 'nav': None, 'ytd': None},
    {'name': "JS Islamic Money Market Fund", 'amc': "JS Investments Limited", 'category': "Shariah Compliant Money Market", 'inception': "Sep 03, 2020", 'aum_mn': 10919.28, 'nav': None, 'ytd': None},
    {'name': "JS Islamic Sarmaya Mehfooz Fund (JS Islamic Sarmaya Mehfooz Plan 1)", 'amc': "JS Investments Limited", 'category': "Shariah Compliant Capital Protected", 'inception': "Jul 26, 2025", 'aum_mn': 1775.21, 'nav': None, 'ytd': None},
    {'name': "JS Islamic Sarmaya Mehfooz Fund Plan 2 2020", 'amc': "JS Investments Limited", 'category': "Shariah Compliant Capital Protected", 'inception': "Dec 11, 2025", 'aum_mn': 314.48, 'nav': None, 'ytd': None},
    {'name': "JS Large Cap Fund", 'amc': "JS Investments Limited", 'category': "Equity", 'inception': "May 15, 2004", 'aum_mn': 2556.76, 'nav': None, 'ytd': None},
    {'name': "JS Microfinance Sector Fund", 'amc': "JS Investments Limited", 'category': "Income", 'inception': "May 11, 2022", 'aum_mn': 33093.35, 'nav': None, 'ytd': None},
    {'name': "JS Money Market Fund", 'amc': "JS Investments Limited", 'category': "Money Market", 'inception': "Feb 28, 2023", 'aum_mn': 6034.99, 'nav': None, 'ytd': None},
    {'name': "Unit Trust of Pakistan", 'amc': "JS Investments Limited", 'category': "Balanced", 'inception': "Oct 27, 1997", 'aum_mn': 2331.22, 'nav': None, 'ytd': None},
    {'name': "Lakson Asset Allocation Developed Markets Fund", 'amc': "Lakson Investments Limited", 'category': "Asset Allocation", 'inception': "Oct 10, 2011", 'aum_mn': 1690.0, 'nav': None, 'ytd': None},
    {'name': "Lakson Equity Fund", 'amc': "Lakson Investments Limited", 'category': "Equity", 'inception': "Nov 13, 2009", 'aum_mn': 6740.0, 'nav': None, 'ytd': None},
    {'name': "Lakson Fixed Return Fund Plan II", 'amc': "Lakson Investments Limited", 'category': "Fixed Rate / Return", 'inception': "Apr 27, 2026", 'aum_mn': None, 'nav': None, 'ytd': None},
    {'name': "Lakson Income Fund", 'amc': "Lakson Investments Limited", 'category': "Income", 'inception': "Nov 13, 2009", 'aum_mn': 12311.0, 'nav': None, 'ytd': None},
    {'name': "Lakson Islamic Fixed Term Fund Plan I", 'amc': "Lakson Investments Limited", 'category': "Shariah Compliant Fixed Rate / Return", 'inception': "May 22, 2026", 'aum_mn': None, 'nav': None, 'ytd': None},
    {'name': "Lakson Islamic Money Market Fund", 'amc': "Lakson Investments Limited", 'category': "Shariah Compliant Money Market", 'inception': "Sep 29, 2022", 'aum_mn': 5974.0, 'nav': None, 'ytd': None},
    {'name': "Lakson Islamic Tactical Fund", 'amc': "Lakson Investments Limited", 'category': "Shariah Compliant Asset Allocation", 'inception': "Oct 10, 2011", 'aum_mn': 623.0, 'nav': None, 'ytd': None},
    {'name': "Lakson Money Market Fund", 'amc': "Lakson Investments Limited", 'category': "Money Market", 'inception': "Nov 13, 2009", 'aum_mn': 29834.0, 'nav': None, 'ytd': None},
    {'name': "Lakson Tactical Fund", 'amc': "Lakson Investments Limited", 'category': "Asset Allocation", 'inception': "Oct 10, 2011", 'aum_mn': 1798.0, 'nav': None, 'ytd': None},
    {'name': "Lucky Islamic Cash Fund", 'amc': "Lucky Investments Limited", 'category': "Shariah Compliant Money Market", 'inception': "Jan 20, 2026", 'aum_mn': 18293.8, 'nav': None, 'ytd': None},
    {'name': "Lucky Islamic Dividend Yield Fund", 'amc': "Lucky Investments Limited", 'category': "Shariah Compliant Equity", 'inception': "Jul 01, 2026", 'aum_mn': 152.43, 'nav': None, 'ytd': None},
    {'name': "Lucky Islamic Energy Fund", 'amc': "Lucky Investments Limited", 'category': "Shariah Compliant Equity", 'inception': "Jan 01, 2026", 'aum_mn': 2698.43, 'nav': None, 'ytd': None},
    {'name': "Lucky Islamic Fixed Term Fund Plan 20", 'amc': "Lucky Investments Limited", 'category': "Shariah Compliant Fixed Rate / Return", 'inception': "Jun 15, 2026", 'aum_mn': None, 'nav': None, 'ytd': None},
    {'name': "Lucky Islamic Fixed Term Fund Plan 22", 'amc': "Lucky Investments Limited", 'category': "Shariah Compliant Fixed Rate / Return", 'inception': "Jun 23, 2026", 'aum_mn': 30.14, 'nav': None, 'ytd': None},
    {'name': "Lucky Islamic Fixed Term Fund Plan 23", 'amc': "Lucky Investments Limited", 'category': "Shariah Compliant Fixed Rate / Return", 'inception': "Jul 20, 2026", 'aum_mn': 11694.66, 'nav': None, 'ytd': None},
    {'name': "Lucky Islamic Income Fund", 'amc': "Lucky Investments Limited", 'category': "Shariah Compliant Income", 'inception': "Apr 25, 2025", 'aum_mn': 13472.34, 'nav': None, 'ytd': None},
    {'name': "Lucky Islamic Money Market Fund", 'amc': "Lucky Investments Limited", 'category': "Shariah Compliant Money Market", 'inception': "Apr 09, 2025", 'aum_mn': 57087.39, 'nav': None, 'ytd': None},
    {'name': "Lucky Islamic Stock Fund", 'amc': "Lucky Investments Limited", 'category': "Shariah Compliant Equity", 'inception': "Apr 25, 2025", 'aum_mn': 14960.55, 'nav': None, 'ytd': None},
    {'name': "Mahaana Islamic Cash Fund", 'amc': "Mahaana Wealth Limited", 'category': "Shariah Compliant Money Market", 'inception': "Mar 29, 2023", 'aum_mn': 3698.41, 'nav': None, 'ytd': None},
    {'name': "Alhamra Cash Management Optimizer", 'amc': "MCB Investment Management Limited", 'category': "Shariah Compliant Money Market", 'inception': "May 23, 2023", 'aum_mn': 73872.7, 'nav': None, 'ytd': None},
    {'name': "Alhamra Daily Dividend Fund", 'amc': "MCB Investment Management Limited", 'category': "Shariah Compliant Income", 'inception': "Apr 10, 2018", 'aum_mn': 2911.9, 'nav': None, 'ytd': None},
    {'name': "Alhamra Government Securities Plan I", 'amc': "MCB Investment Management Limited", 'category': "Shariah Compliant Income", 'inception': "Jun 24, 2024", 'aum_mn': 1249.0, 'nav': None, 'ytd': None},
    {'name': "Alhamra Islamic Asset Allocation Fund", 'amc': "MCB Investment Management Limited", 'category': "Shariah Compliant Asset Allocation", 'inception': "Apr 22, 2006", 'aum_mn': 2081.93, 'nav': None, 'ytd': None},
    {'name': "Alhamra Islamic Energy Fund", 'amc': "MCB Investment Management Limited", 'category': "Shariah Compliant Equity", 'inception': "Jul 02, 2026", 'aum_mn': 378.45, 'nav': None, 'ytd': None},
    {'name': "Alhamra Islamic Income Fund", 'amc': "MCB Investment Management Limited", 'category': "Shariah Compliant Income", 'inception': "Jun 19, 2011", 'aum_mn': 16423.57, 'nav': None, 'ytd': None},
    {'name': "Alhamra Islamic Investment Savings Fund", 'amc': "MCB Investment Management Limited", 'category': "Shariah Compliant Income", 'inception': "Jun 05, 2026", 'aum_mn': 18774.76, 'nav': None, 'ytd': None},
    {'name': "Alhamra Islamic Money Market Fund", 'amc': "MCB Investment Management Limited", 'category': "Shariah Compliant Money Market", 'inception': "Aug 20, 2020", 'aum_mn': 2385.67, 'nav': None, 'ytd': None},
    {'name': "Alhamra Islamic Stock Fund", 'amc': "MCB Investment Management Limited", 'category': "Shariah Compliant Equity", 'inception': "Aug 25, 2004", 'aum_mn': 11580.0, 'nav': None, 'ytd': None},
    {'name': "Alhamra Opportunity Fund (Dividend Strategy Plan)", 'amc': "MCB Investment Management Limited", 'category': "Shariah Compliant Equity", 'inception': "Feb 27, 2024", 'aum_mn': 2177.83, 'nav': None, 'ytd': None},
    {'name': "Alhamra Smart Portfolio", 'amc': "MCB Investment Management Limited", 'category': "Shariah Compliant Fund of Funds", 'inception': "Jun 11, 2021", 'aum_mn': 256.01, 'nav': None, 'ytd': None},
    {'name': "MCB Cash Management Optimizer", 'amc': "MCB Investment Management Limited", 'category': "Money Market", 'inception': "Oct 01, 2009", 'aum_mn': 78618.42, 'nav': None, 'ytd': None},
    {'name': "MCB DCF Fixed Return III (Plan IV)", 'amc': "MCB Investment Management Limited", 'category': "Fixed Rate / Return", 'inception': "Oct 10, 2024", 'aum_mn': 587.91, 'nav': None, 'ytd': None},
    {'name': "MCB DCF Fixed Return Plan XI", 'amc': "MCB Investment Management Limited", 'category': "Fixed Rate / Return", 'inception': "Jul 06, 2026", 'aum_mn': 1733.15, 'nav': None, 'ytd': None},
    {'name': "MCB DCF Fixed Return Plan XII", 'amc': "MCB Investment Management Limited", 'category': "Fixed Rate / Return", 'inception': "Jul 07, 2026", 'aum_mn': 1020.85, 'nav': None, 'ytd': None},
    {'name': "MCB DCF Income Fund", 'amc': "MCB Investment Management Limited", 'category': "Income", 'inception': "Jan 03, 2007", 'aum_mn': 15773.75, 'nav': None, 'ytd': None},
    {'name': "MCB Financial Sector Fund", 'amc': "MCB Investment Management Limited", 'category': "Equity", 'inception': "Jul 02, 2026", 'aum_mn': 538.73, 'nav': None, 'ytd': None},
    {'name': "MCB Government Securities Plan I", 'amc': "MCB Investment Management Limited", 'category': "Income", 'inception': "Nov 05, 2024", 'aum_mn': 13220.27, 'nav': None, 'ytd': None},
    {'name': "MCB Investment Savings Plan I", 'amc': "MCB Investment Management Limited", 'category': "Aggressive Fixed Income", 'inception': "Aug 05, 2024", 'aum_mn': 75344.54, 'nav': None, 'ytd': None},
    {'name': "MCB Money Market Fund", 'amc': "MCB Investment Management Limited", 'category': "Money Market", 'inception': "Jul 08, 2026", 'aum_mn': 1988.48, 'nav': None, 'ytd': None},
    {'name': "MCB Pakistan Asset Allocation Fund", 'amc': "MCB Investment Management Limited", 'category': "Asset Allocation", 'inception': "Mar 17, 2008", 'aum_mn': 1389.0, 'nav': None, 'ytd': None},
    {'name': "MCB Pakistan Opportunity Fund (MCB Pakistan  Dividend Yield Plan)", 'amc': "MCB Investment Management Limited", 'category': "Asset Allocation", 'inception': "Jun 29, 2022", 'aum_mn': 2548.29, 'nav': None, 'ytd': None},
    {'name': "MCB Pakistan Sovereign Fund", 'amc': "MCB Investment Management Limited", 'category': "Income", 'inception': "Mar 01, 2003", 'aum_mn': 13175.15, 'nav': None, 'ytd': None},
    {'name': "MCB Pakistan Stock Market Fund", 'amc': "MCB Investment Management Limited", 'category': "Equity", 'inception': "Mar 11, 2002", 'aum_mn': 37984.01, 'nav': None, 'ytd': None},
    {'name': "Pakistan Capital Market Fund", 'amc': "MCB Investment Management Limited", 'category': "Balanced", 'inception': "Jan 24, 2004", 'aum_mn': 956.99, 'nav': None, 'ytd': None},
    {'name': "Pakistan Cash Management Fund", 'amc': "MCB Investment Management Limited", 'category': "Money Market", 'inception': "Mar 19, 2008", 'aum_mn': 930.48, 'nav': None, 'ytd': None},
    {'name': "Pakistan Income Enhancement Fund", 'amc': "MCB Investment Management Limited", 'category': "Aggressive Fixed Income", 'inception': "Aug 28, 2008", 'aum_mn': 3990.0, 'nav': None, 'ytd': None},
    {'name': "Pakistan Income Fund", 'amc': "MCB Investment Management Limited", 'category': "Income", 'inception': "Mar 11, 2002", 'aum_mn': 3461.96, 'nav': None, 'ytd': None},
    {'name': "National Investment Unit Trust", 'amc': "National Investment Trust Limited", 'category': "Equity", 'inception': "Nov 12, 1962", 'aum_mn': 87289.58, 'nav': None, 'ytd': None},
    {'name': "NIT - Government Bond Fund", 'amc': "National Investment Trust Limited", 'category': "Income", 'inception': "Nov 18, 2009", 'aum_mn': 2410.07, 'nav': None, 'ytd': None},
    {'name': "NIT - Income Fund", 'amc': "National Investment Trust Limited", 'category': "Income", 'inception': "Feb 19, 2010", 'aum_mn': 2596.03, 'nav': None, 'ytd': None},
    {'name': "NIT Asset Allocation Fund", 'amc': "National Investment Trust Limited", 'category': "Asset Allocation", 'inception': "Apr 09, 2020", 'aum_mn': 979.44, 'nav': None, 'ytd': None},
    {'name': "NIT Islamic Equity Fund", 'amc': "National Investment Trust Limited", 'category': "Shariah Compliant Equity", 'inception': "May 18, 2015", 'aum_mn': 4827.04, 'nav': None, 'ytd': None},
    {'name': "NIT Islamic Income Fund", 'amc': "National Investment Trust Limited", 'category': "Shariah Compliant Income", 'inception': "Jul 04, 2016", 'aum_mn': 1937.34, 'nav': None, 'ytd': None},
    {'name': "NIT Islamic Money Market Fund", 'amc': "National Investment Trust Limited", 'category': "Shariah Compliant Money Market", 'inception': "Sep 21, 2021", 'aum_mn': 11068.98, 'nav': None, 'ytd': None},
    {'name': "NIT Money Market Fund", 'amc': "National Investment Trust Limited", 'category': "Money Market", 'inception': "Jan 22, 2016", 'aum_mn': 53813.82, 'nav': None, 'ytd': None},
    {'name': "NIT Social Impact Fund", 'amc': "National Investment Trust Limited", 'category': "Income", 'inception': "May 16, 2022", 'aum_mn': 7167.64, 'nav': None, 'ytd': None},
    {'name': "NBP Balanced Fund", 'amc': "NBP Fund Management Limited", 'category': "Balanced", 'inception': "Jan 22, 2007", 'aum_mn': 2053.0, 'nav': None, 'ytd': None},
    {'name': "NBP Cash Plan I", 'amc': "NBP Fund Management Limited", 'category': "Money Market", 'inception': "Jan 10, 2023", 'aum_mn': None, 'nav': None, 'ytd': None},
    {'name': "NBP Cash Plan II", 'amc': "NBP Fund Management Limited", 'category': "Money Market", 'inception': "Jan 10, 2023", 'aum_mn': 1023.0, 'nav': None, 'ytd': None},
    {'name': "NBP Financial Sector Fund", 'amc': "NBP Fund Management Limited", 'category': "Equity", 'inception': "Feb 14, 2018", 'aum_mn': 3046.0, 'nav': None, 'ytd': None},
    {'name': "NBP Financial Sector Income Fund", 'amc': "NBP Fund Management Limited", 'category': "Income", 'inception': "Oct 28, 2011", 'aum_mn': 49821.0, 'nav': None, 'ytd': None},
    {'name': "NBP Financial Sector Income Plus Fund", 'amc': "NBP Fund Management Limited", 'category': "Income", 'inception': "Apr 20, 2026", 'aum_mn': 78201.0, 'nav': None, 'ytd': None},
    {'name': "NBP Fixed Term Munafa Plan VIB (NBP Mustahkam Fund I)", 'amc': "NBP Fund Management Limited", 'category': "Fixed Rate / Return", 'inception': "Jun 29, 2026", 'aum_mn': 2239.0, 'nav': None, 'ytd': None},
    {'name': "NBP Fixed Term Munafa Plan VIIB (NBP Mustahkam Fund I)", 'amc': "NBP Fund Management Limited", 'category': "Fixed Rate / Return", 'inception': "Jul 08, 2026", 'aum_mn': 2383.0, 'nav': None, 'ytd': None},
    {'name': "NBP Fixed Term Munafa Plan XIIB (NBP Mustahkam Fund II)", 'amc': "NBP Fund Management Limited", 'category': "Fixed Rate / Return", 'inception': "Jun 18, 2026", 'aum_mn': 15363.0, 'nav': None, 'ytd': None},
    {'name': "NBP Fixed Term Munafa Plan XIII (NBP Mustahkam Fund II)", 'amc': "NBP Fund Management Limited", 'category': "Fixed Rate / Return", 'inception': "Oct 06, 2025", 'aum_mn': None, 'nav': None, 'ytd': None},
    {'name': "NBP Fixed Term Munafa Plan XIIIB (NBP Mustahkam Fund II)", 'amc': "NBP Fund Management Limited", 'category': "Fixed Rate / Return", 'inception': "Jun 29, 2026", 'aum_mn': 853.0, 'nav': None, 'ytd': None},
    {'name': "NBP Fixed Term Munafa Plan XIVB", 'amc': "NBP Fund Management Limited", 'category': "Fixed Rate / Return", 'inception': "Jun 22, 2026", 'aum_mn': 10157.0, 'nav': None, 'ytd': None},
    {'name': "NBP Fixed Term Munafa Plan XXA (NBP Mustahkam Fund II)", 'amc': "NBP Fund Management Limited", 'category': "Fixed Rate / Return", 'inception': "Mar 03, 2026", 'aum_mn': 2074.0, 'nav': None, 'ytd': None},
    {'name': "NBP Government Securities Liquid Fund", 'amc': "NBP Fund Management Limited", 'category': "Money Market", 'inception': "May 16, 2009", 'aum_mn': 5260.0, 'nav': None, 'ytd': None},
    {'name': "NBP Government Securities Plan IV", 'amc': "NBP Fund Management Limited", 'category': "Income", 'inception': "May 10, 2023", 'aum_mn': 2878.0, 'nav': None, 'ytd': None},
    {'name': "NBP Government Securities Plan VIII", 'amc': "NBP Fund Management Limited", 'category': "Income", 'inception': "Aug 19, 2025", 'aum_mn': 4.0, 'nav': None, 'ytd': None},
    {'name': "NBP Government Securities Savings Fund", 'amc': "NBP Fund Management Limited", 'category': "Income", 'inception': "Jul 03, 2014", 'aum_mn': 3038.0, 'nav': None, 'ytd': None},
    {'name': "NBP Income Opportunity Fund", 'amc': "NBP Fund Management Limited", 'category': "Income", 'inception': "Apr 22, 2006", 'aum_mn': 9226.0, 'nav': None, 'ytd': None},
    {'name': "NBP Income Plan I", 'amc': "NBP Fund Management Limited", 'category': "Income", 'inception': "Jan 10, 2023", 'aum_mn': 116.0, 'nav': None, 'ytd': None},
    {'name': "NBP Islamic Daily Dividend Fund", 'amc': "NBP Fund Management Limited", 'category': "Shariah Compliant Money Market", 'inception': "Nov 01, 2019", 'aum_mn': 9760.0, 'nav': None, 'ytd': None},
    {'name': "NBP Islamic Energy Fund", 'amc': "NBP Fund Management Limited", 'category': "Shariah Compliant Equity", 'inception': "Apr 21, 2016", 'aum_mn': 4266.0, 'nav': None, 'ytd': None},
    {'name': "NBP Islamic Fixed Term Munafa Plan IIB (NBP Islamic Mustahkam Fund)", 'amc': "NBP Fund Management Limited", 'category': "Shariah Compliant Fixed Rate / Return", 'inception': "Jul 13, 2026", 'aum_mn': 16256.0, 'nav': None, 'ytd': None},
    {'name': "NBP Islamic Fixed Term Munafa Plan-IVB ( NBP Islamic Mustahkam Fund )", 'amc': "NBP Fund Management Limited", 'category': "Shariah Compliant Fixed Rate / Return", 'inception': "Jul 23, 2026", 'aum_mn': None, 'nav': None, 'ytd': None},
    {'name': "NBP Islamic Gold Fund", 'amc': "NBP Fund Management Limited", 'category': "Shariah Compliant Commodities", 'inception': "May 04, 2026", 'aum_mn': None, 'nav': None, 'ytd': None},
    {'name': "NBP Islamic Government Securities Plan III", 'amc': "NBP Fund Management Limited", 'category': "Shariah Compliant Income", 'inception': "Jan 19, 2024", 'aum_mn': 897.0, 'nav': None, 'ytd': None},
    {'name': "NBP Islamic Income Fund", 'amc': "NBP Fund Management Limited", 'category': "Shariah Compliant Income", 'inception': "Aug 14, 2020", 'aum_mn': None, 'nav': None, 'ytd': None},
    {'name': "NBP Islamic Mahana Amdani Fund", 'amc': "NBP Fund Management Limited", 'category': "Shariah Compliant Income", 'inception': "Oct 08, 2018", 'aum_mn': 15393.0, 'nav': None, 'ytd': None},
    {'name': "NBP Islamic Money Market Fund", 'amc': "NBP Fund Management Limited", 'category': "Shariah Compliant Money Market", 'inception': "Feb 28, 2018", 'aum_mn': 74897.0, 'nav': None, 'ytd': None},
    {'name': "NBP Islamic Principal Protection Fund I (NBP Islamic Principal Protection Plan I)", 'amc': "NBP Fund Management Limited", 'category': "Shariah Compliant Capital Protected", 'inception': "Sep 25, 2025", 'aum_mn': 930.0, 'nav': None, 'ytd': None},
    {'name': "NBP Islamic Principal Protection Fund I (NBP Islamic Principal Protection Plan II)", 'amc': "NBP Fund Management Limited", 'category': "Shariah Compliant Capital Protected", 'inception': "Dec 19, 2025", 'aum_mn': 910.0, 'nav': None, 'ytd': None},
    {'name': "NBP Islamic Principal Protection Fund I (NBP Islamic Principal Protection Plan III)", 'amc': "NBP Fund Management Limited", 'category': "Shariah Compliant Capital Protected", 'inception': "Jan 26, 2026", 'aum_mn': 1727.0, 'nav': None, 'ytd': None},
    {'name': "NBP Islamic Principal Protection Fund I (NBP Islamic Principal Protection Plan IV)", 'amc': "NBP Fund Management Limited", 'category': "Shariah Compliant Capital Protected", 'inception': "Feb 23, 2026", 'aum_mn': 453.0, 'nav': None, 'ytd': None},
    {'name': "NBP Islamic Principal Protection Fund I (NBP Islamic Principal Protection Plan V)", 'amc': "NBP Fund Management Limited", 'category': "Shariah Compliant Capital Protected", 'inception': "Jun 12, 2026", 'aum_mn': 604.0, 'nav': None, 'ytd': None},
    {'name': "NBP Islamic Sarmaya Izafa Fund", 'amc': "NBP Fund Management Limited", 'category': "Shariah Compliant Asset Allocation", 'inception': "Oct 29, 2007", 'aum_mn': None, 'nav': None, 'ytd': None},
    {'name': "NBP Islamic Savings Fund", 'amc': "NBP Fund Management Limited", 'category': "Shariah Compliant Income", 'inception': "Oct 29, 2007", 'aum_mn': 7559.0, 'nav': None, 'ytd': None},
    {'name': "NBP Islamic Stock Fund", 'amc': "NBP Fund Management Limited", 'category': "Shariah Compliant Equity", 'inception': "Jan 12, 2015", 'aum_mn': 13822.0, 'nav': None, 'ytd': None},
    {'name': "NBP Mahana Amdani Fund", 'amc': "NBP Fund Management Limited", 'category': "Income", 'inception': "Nov 21, 2009", 'aum_mn': 28556.0, 'nav': None, 'ytd': None},
    {'name': "NBP Money Market Fund", 'amc': "NBP Fund Management Limited", 'category': "Money Market", 'inception': "Feb 24, 2012", 'aum_mn': 92808.0, 'nav': None, 'ytd': None},
    {'name': "NBP Money Market Liquid Fund", 'amc': "NBP Fund Management Limited", 'category': "Money Market", 'inception': "Jul 03, 2026", 'aum_mn': None, 'nav': None, 'ytd': None},
    {'name': "NBP Riba Free Savings Fund", 'amc': "NBP Fund Management Limited", 'category': "Shariah Compliant Income", 'inception': "Aug 20, 2010", 'aum_mn': 21213.0, 'nav': None, 'ytd': None},
    {'name': "NBP Sarmaya Izafa Fund", 'amc': "NBP Fund Management Limited", 'category': "Asset Allocation", 'inception': "Aug 20, 2010", 'aum_mn': 1079.0, 'nav': None, 'ytd': None},
    {'name': "NBP Savings Fund", 'amc': "NBP Fund Management Limited", 'category': "Income", 'inception': "Mar 29, 2008", 'aum_mn': 7122.0, 'nav': None, 'ytd': None},
    {'name': "NBP Stock Fund", 'amc': "NBP Fund Management Limited", 'category': "Equity", 'inception': "Jan 22, 2007", 'aum_mn': 58584.0, 'nav': None, 'ytd': None},
    {'name': "Askari Cash Fund", 'amc': "Pak Oman Asset Management Company Limited", 'category': "Money Market", 'inception': "Sep 30, 2009", 'aum_mn': None, 'nav': None, 'ytd': None},
    {'name': "Askari High Yield Scheme", 'amc': "Pak Oman Asset Management Company Limited", 'category': "Aggressive Fixed Income", 'inception': "Mar 16, 2006", 'aum_mn': None, 'nav': None, 'ytd': None},
    {'name': "Askari Sovereign Yield Enhancer", 'amc': "Pak Oman Asset Management Company Limited", 'category': "Income", 'inception': "May 07, 2012", 'aum_mn': None, 'nav': None, 'ytd': None},
    {'name': "Pak Oman Advantage Asset Allocation Fund", 'amc': "Pak Oman Asset Management Company Limited", 'category': "Asset Allocation", 'inception': "Oct 30, 2008", 'aum_mn': None, 'nav': None, 'ytd': None},
    {'name': "Pak Oman Advantage Islamic Income Fund", 'amc': "Pak Oman Asset Management Company Limited", 'category': "Shariah Compliant Income", 'inception': "Oct 28, 2008", 'aum_mn': None, 'nav': None, 'ytd': None},
    {'name': "Pak Oman Daily Dividend Fund", 'amc': "Pak Oman Asset Management Company Limited", 'category': "Shariah Compliant Money Market", 'inception': "Dec 07, 2021", 'aum_mn': None, 'nav': None, 'ytd': None},
    {'name': "Pak Oman Income Fund", 'amc': "Pak Oman Asset Management Company Limited", 'category': "Income", 'inception': "Jul 28, 2011", 'aum_mn': None, 'nav': None, 'ytd': None},
    {'name': "Pak Oman Islamic Asset Allocation Fund", 'amc': "Pak Oman Asset Management Company Limited", 'category': "Shariah Compliant Asset Allocation", 'inception': "Oct 28, 2008", 'aum_mn': None, 'nav': None, 'ytd': None},
    {'name': "Pak Oman Micro Finance Fund", 'amc': "Pak Oman Asset Management Company Limited", 'category': "Income", 'inception': "May 14, 2024", 'aum_mn': None, 'nav': None, 'ytd': None},
    {'name': "Pak Qatar Asset Allocation Plan I (PQAAP  IA)", 'amc': "Pak-Qatar Asset Management Company Limited", 'category': "Shariah Compliant Asset Allocation", 'inception': "Aug 18, 2023", 'aum_mn': None, 'nav': None, 'ytd': None},
    {'name': "Pak Qatar Asset Allocation Plan II (PQAAP  IIA)", 'amc': "Pak-Qatar Asset Management Company Limited", 'category': "Shariah Compliant Asset Allocation", 'inception': "Aug 18, 2023", 'aum_mn': None, 'nav': None, 'ytd': None},
    {'name': "Pak Qatar Cash Plan", 'amc': "Pak-Qatar Asset Management Company Limited", 'category': "Shariah Compliant Money Market", 'inception': "Oct 03, 2022", 'aum_mn': 21381.36, 'nav': None, 'ytd': None},
    {'name': "Pak Qatar Daily Dividend Plan", 'amc': "Pak-Qatar Asset Management Company Limited", 'category': "Shariah Compliant Money Market", 'inception': "Oct 03, 2022", 'aum_mn': 898.62, 'nav': None, 'ytd': None},
    {'name': "Pak Qatar Income Plan", 'amc': "Pak-Qatar Asset Management Company Limited", 'category': "Shariah Compliant Income", 'inception': "Oct 03, 2022", 'aum_mn': 10584.81, 'nav': None, 'ytd': None},
    {'name': "Pak Qatar Islamic Stock Fund", 'amc': "Pak-Qatar Asset Management Company Limited", 'category': "Shariah Compliant Equity", 'inception': "Sep 22, 2022", 'aum_mn': 1242.07, 'nav': None, 'ytd': None},
    {'name': "Pak-Qatar Asset Allocation Plan III (PQAAP  IIIA)", 'amc': "Pak-Qatar Asset Management Company Limited", 'category': "Shariah Compliant Asset Allocation", 'inception': "Sep 24, 2024", 'aum_mn': None, 'nav': None, 'ytd': None},
    {'name': "Al Ameen Islamic Aggressive Income Fund", 'amc': "UBL Fund Managers Limited", 'category': "Shariah Compliant Aggressive Fixed Income", 'inception': "Oct 20, 2007", 'aum_mn': 766.52, 'nav': None, 'ytd': None},
    {'name': "Al Ameen Islamic Aggressive Income Plan I", 'amc': "UBL Fund Managers Limited", 'category': "Shariah Compliant Aggressive Fixed Income", 'inception': "Apr 16, 2020", 'aum_mn': 53.81, 'nav': None, 'ytd': None},
    {'name': "Al Ameen Islamic Asset Allocation Fund", 'amc': "UBL Fund Managers Limited", 'category': "Shariah Compliant Asset Allocation", 'inception': "Dec 11, 2013", 'aum_mn': 5375.55, 'nav': None, 'ytd': None},
    {'name': "Al Ameen Islamic Cash Fund", 'amc': "UBL Fund Managers Limited", 'category': "Shariah Compliant Money Market", 'inception': "Sep 19, 2012", 'aum_mn': 28826.21, 'nav': None, 'ytd': None},
    {'name': "Al Ameen Islamic Cash Plan I", 'amc': "UBL Fund Managers Limited", 'category': "Shariah Compliant Money Market", 'inception': "May 29, 2020", 'aum_mn': 44676.87, 'nav': None, 'ytd': None},
    {'name': "Al Ameen Islamic Energy Fund", 'amc': "UBL Fund Managers Limited", 'category': "Shariah Compliant Equity", 'inception': "Dec 13, 2019", 'aum_mn': 4439.67, 'nav': None, 'ytd': None},
    {'name': "Al Ameen Islamic Income Fund", 'amc': "UBL Fund Managers Limited", 'category': "Shariah Compliant Income", 'inception': "May 29, 2023", 'aum_mn': 53204.17, 'nav': None, 'ytd': None},
    {'name': "Al Ameen Islamic Sovereign Fund", 'amc': "UBL Fund Managers Limited", 'category': "Shariah Compliant Income", 'inception': "Nov 07, 2010", 'aum_mn': 7935.53, 'nav': None, 'ytd': None},
    {'name': "Al Ameen Shariah Stock Fund", 'amc': "UBL Fund Managers Limited", 'category': "Shariah Compliant Equity", 'inception': "Dec 24, 2006", 'aum_mn': 33133.39, 'nav': None, 'ytd': None},
    {'name': "UBL Asset Allocation Fund", 'amc': "UBL Fund Managers Limited", 'category': "Asset Allocation", 'inception': "Aug 20, 2013", 'aum_mn': 3070.86, 'nav': None, 'ytd': None},
    {'name': "UBL Cash Fund", 'amc': "UBL Fund Managers Limited", 'category': "Money Market", 'inception': "Sep 23, 2019", 'aum_mn': 81067.48, 'nav': None, 'ytd': None},
    {'name': "UBL Financial Sector Fund", 'amc': "UBL Fund Managers Limited", 'category': "Equity", 'inception': "Apr 06, 2018", 'aum_mn': 9494.31, 'nav': None, 'ytd': None},
    {'name': "UBL Fixed Return Plan II (AB)", 'amc': "UBL Fund Managers Limited", 'category': "Fixed Rate / Return", 'inception': "Jun 25, 2025", 'aum_mn': 5.58, 'nav': None, 'ytd': None},
    {'name': "UBL Fixed Return Plan II (M)", 'amc': "UBL Fund Managers Limited", 'category': "Fixed Rate / Return", 'inception': "Jun 03, 2024", 'aum_mn': None, 'nav': None, 'ytd': None},
    {'name': "UBL Fixed Return Plan III (Y)", 'amc': "UBL Fund Managers Limited", 'category': "Fixed Rate / Return", 'inception': "Jun 26, 2025", 'aum_mn': 0.23, 'nav': None, 'ytd': None},
    {'name': "UBL Fixed Return Plan III (Z)", 'amc': "UBL Fund Managers Limited", 'category': "Fixed Rate / Return", 'inception': "Jul 21, 2025", 'aum_mn': 238.54, 'nav': None, 'ytd': None},
    {'name': "UBL Government Securities Fund", 'amc': "UBL Fund Managers Limited", 'category': "Income", 'inception': "Jul 27, 2011", 'aum_mn': 3487.47, 'nav': None, 'ytd': None},
    {'name': "UBL Growth & Income Fund", 'amc': "UBL Fund Managers Limited", 'category': "Aggressive Fixed Income", 'inception': "Mar 02, 2006", 'aum_mn': 5366.26, 'nav': None, 'ytd': None},
    {'name': "UBL Income Opportunity Fund", 'amc': "UBL Fund Managers Limited", 'category': "Income", 'inception': "Mar 29, 2013", 'aum_mn': 2501.24, 'nav': None, 'ytd': None},
    {'name': "UBL Liquidity Fund", 'amc': "UBL Fund Managers Limited", 'category': "Money Market", 'inception': "Sep 05, 2025", 'aum_mn': 16661.27, 'nav': None, 'ytd': None},
    {'name': "UBL Liquidity Plus Fund", 'amc': "UBL Fund Managers Limited", 'category': "Money Market", 'inception': "Jun 21, 2009", 'aum_mn': 6885.52, 'nav': None, 'ytd': None},
    {'name': "UBL Money Market Fund", 'amc': "UBL Fund Managers Limited", 'category': "Money Market", 'inception': "Oct 13, 2010", 'aum_mn': 46310.29, 'nav': None, 'ytd': None},
    {'name': "UBL Special Savings Plan X", 'amc': "UBL Fund Managers Limited", 'category': "Capital Protected - Income", 'inception': "Mar 29, 2023", 'aum_mn': 934.0, 'nav': None, 'ytd': None},
    {'name': "UBL Stock Advantage Fund", 'amc': "UBL Fund Managers Limited", 'category': "Equity", 'inception': "Aug 04, 2006", 'aum_mn': 37442.57, 'nav': None, 'ytd': None},
]

# World Clock — major exchanges. IANA timezone names let the browser
# compute local time (incl. DST) correctly on the client; open/close
# are in that market's own local 24h time. "days" uses JS getDay()
# convention: 0=Sun ... 6=Sat.
WORLD_MARKETS = [
    {"key": "psx", "name": "Pakistan Stock Exchange", "city": "Karachi", "tz": "Asia/Karachi", "open": "09:15", "close": "15:30", "days": [1, 2, 3, 4, 5]},
    {"key": "lse", "name": "London Stock Exchange", "city": "London", "tz": "Europe/London", "open": "08:00", "close": "16:30", "days": [1, 2, 3, 4, 5]},
    {"key": "nyse", "name": "New York Stock Exchange", "city": "New York", "tz": "America/New_York", "open": "09:30", "close": "16:00", "days": [1, 2, 3, 4, 5]},
    {"key": "nasdaq", "name": "NASDAQ", "city": "New York", "tz": "America/New_York", "open": "09:30", "close": "16:00", "days": [1, 2, 3, 4, 5]},
    {"key": "tse", "name": "Tokyo Stock Exchange", "city": "Tokyo", "tz": "Asia/Tokyo", "open": "09:00", "close": "15:00", "days": [1, 2, 3, 4, 5]},
    {"key": "hkex", "name": "Hong Kong Stock Exchange", "city": "Hong Kong", "tz": "Asia/Hong_Kong", "open": "09:30", "close": "16:00", "days": [1, 2, 3, 4, 5]},
    {"key": "sse", "name": "Shanghai Stock Exchange", "city": "Shanghai", "tz": "Asia/Shanghai", "open": "09:30", "close": "15:00", "days": [1, 2, 3, 4, 5]},
    {"key": "asx", "name": "Australian Securities Exchange", "city": "Sydney", "tz": "Australia/Sydney", "open": "10:00", "close": "16:00", "days": [1, 2, 3, 4, 5]},
    {"key": "tadawul", "name": "Saudi Exchange (Tadawul)", "city": "Riyadh", "tz": "Asia/Riyadh", "open": "10:00", "close": "15:00", "days": [0, 1, 2, 3, 4]},
    {"key": "dfm", "name": "Dubai Financial Market", "city": "Dubai", "tz": "Asia/Dubai", "open": "10:00", "close": "14:00", "days": [0, 1, 2, 3, 4]},
]

FOREX_SESSIONS = [
    {"key": "sydney", "name": "Sydney", "tz": "Australia/Sydney", "open": "07:00", "close": "16:00"},
    {"key": "tokyo", "name": "Tokyo", "tz": "Asia/Tokyo", "open": "09:00", "close": "18:00"},
    {"key": "london", "name": "London", "tz": "Europe/London", "open": "08:00", "close": "16:30"},
    {"key": "newyork", "name": "New York", "tz": "America/New_York", "open": "08:00", "close": "17:00"},
]


# ---------------------------------------------------------
# Stock Screener — full checklist from the user's master checklist
# PDF, grouped by section. Each item is marked available=True only
# if we have a genuine, real data source for it today (PSX's public
# company page). Everything else is listed (so the full requested
# checklist is visible and filterable-in-principle) but marked
# available=False with a plain-language reason - these need either
# multi-year historical OHLCV data (for technicals/smart-money/price
# patterns) or a financial-statements data vendor (for deep
# fundamentals/ownership/risk), neither of which PSX's public pages
# expose. Flip "available" to True and wire in stock_matches_filters()
# once a real source is connected.
# ---------------------------------------------------------

NEEDS_HISTORY = "Needs multi-year historical price data (not available from PSX's public pages)"
NEEDS_FINANCIALS = "Needs a financial-statements data vendor (not available from PSX's public pages)"
NEEDS_OWNERSHIP = "Needs an ownership/institutional-holdings data vendor"
NEEDS_PATTERN_ENGINE = "Needs historical OHLCV data plus a pattern-detection engine"

def _catalog_item(key, label, available=False, reason=None, filter_key=None):
    item = {"key": key, "label": label, "available": available}
    if not available:
        item["reason"] = reason
    if available and filter_key:
        item["filter_key"] = filter_key
    return item


FILTER_CATALOG = [
    {
        "section": "Valuation Metrics",
        "items": [
            _catalog_item("pe_ratio", "P/E Ratio", True, filter_key="pe"),
            _catalog_item("forward_pe", "Forward P/E Ratio", False, NEEDS_FINANCIALS),
            _catalog_item("peg", "PEG Ratio", False, NEEDS_FINANCIALS),
            _catalog_item("pb", "Price-to-Book Ratio (P/B)", False, NEEDS_FINANCIALS),
            _catalog_item("bvps", "Book Value Per Share (BVPS)", False, NEEDS_FINANCIALS),
            _catalog_item("ps", "Price-to-Sales Ratio (P/S)", False, NEEDS_FINANCIALS),
            _catalog_item("pcf", "Price-to-Cash Flow Ratio", False, NEEDS_FINANCIALS),
            _catalog_item("ev", "Enterprise Value (EV)", False, NEEDS_FINANCIALS),
            _catalog_item("ev_ebitda", "EV/EBITDA", False, NEEDS_FINANCIALS),
            _catalog_item("ev_sales", "EV/Sales", False, NEEDS_FINANCIALS),
            _catalog_item("dcf_value", "Discounted Cash Flow (DCF) Fair Value", False, NEEDS_FINANCIALS),
            _catalog_item("intrinsic_value", "Intrinsic Value Estimate", False, NEEDS_FINANCIALS),
            _catalog_item("margin_of_safety", "Margin of Safety", False, NEEDS_FINANCIALS),
            _catalog_item("sector_relative_valuation", "Sector Relative Valuation", False, NEEDS_FINANCIALS),
        ],
    },
    {
        "section": "Growth Metrics",
        "items": [
            _catalog_item("revenue_growth", "Revenue Growth", False, NEEDS_FINANCIALS),
            _catalog_item("revenue_cagr", "Revenue CAGR", False, NEEDS_FINANCIALS),
            _catalog_item("eps_growth", "EPS Growth", False, NEEDS_FINANCIALS),
            _catalog_item("eps_cagr", "EPS CAGR", False, NEEDS_FINANCIALS),
            _catalog_item("earnings_surprise", "Earnings Surprise History", False, NEEDS_FINANCIALS),
            _catalog_item("q_revenue_growth", "Quarterly Revenue Growth", False, NEEDS_FINANCIALS),
            _catalog_item("q_eps_growth", "Quarterly EPS Growth", False, NEEDS_FINANCIALS),
            _catalog_item("future_earnings_growth", "Future Earnings Growth Forecast", False, NEEDS_FINANCIALS),
            _catalog_item("analyst_revision", "Analyst Earnings Revision", False, NEEDS_FINANCIALS),
            _catalog_item("profit_growth_consistency", "Profit Growth Consistency", False, NEEDS_FINANCIALS),
        ],
    },
    {
        "section": "Profitability & Quality",
        "items": [
            _catalog_item("gross_margin", "Gross Profit Margin", False, NEEDS_FINANCIALS),
            _catalog_item("operating_margin", "Operating Profit Margin", False, NEEDS_FINANCIALS),
            _catalog_item("net_margin", "Net Profit Margin", False, NEEDS_FINANCIALS),
            _catalog_item("ebitda_margin", "EBITDA Margin", False, NEEDS_FINANCIALS),
            _catalog_item("ebit_margin", "EBIT Margin", False, NEEDS_FINANCIALS),
            _catalog_item("roe", "Return on Equity (ROE)", False, NEEDS_FINANCIALS),
            _catalog_item("roa", "Return on Assets (ROA)", False, NEEDS_FINANCIALS),
            _catalog_item("roic", "Return on Invested Capital (ROIC)", False, NEEDS_FINANCIALS),
            _catalog_item("roce", "Return on Capital Employed (ROCE)", False, NEEDS_FINANCIALS),
            _catalog_item("profit_stability", "Profit Stability", False, NEEDS_FINANCIALS),
        ],
    },
    {
        "section": "Financial Health",
        "items": [
            _catalog_item("total_debt", "Total Debt", False, NEEDS_FINANCIALS),
            _catalog_item("debt_equity", "Debt-to-Equity Ratio", False, NEEDS_FINANCIALS),
            _catalog_item("debt_assets", "Debt-to-Assets Ratio", False, NEEDS_FINANCIALS),
            _catalog_item("interest_coverage", "Interest Coverage Ratio", False, NEEDS_FINANCIALS),
            _catalog_item("current_ratio", "Current Ratio", False, NEEDS_FINANCIALS),
            _catalog_item("quick_ratio", "Quick Ratio", False, NEEDS_FINANCIALS),
            _catalog_item("cash_ratio", "Cash Ratio", False, NEEDS_FINANCIALS),
            _catalog_item("working_capital", "Working Capital", False, NEEDS_FINANCIALS),
            _catalog_item("net_cash", "Net Cash Position", False, NEEDS_FINANCIALS),
            _catalog_item("fcf", "Free Cash Flow", False, NEEDS_FINANCIALS),
            _catalog_item("fcf_margin", "Free Cash Flow Margin", False, NEEDS_FINANCIALS),
            _catalog_item("operating_cash_flow", "Operating Cash Flow", False, NEEDS_FINANCIALS),
        ],
    },
    {
        "section": "Balance Sheet",
        "items": [
            _catalog_item(k, label, False, NEEDS_FINANCIALS) for k, label in [
                ("total_assets", "Total Assets"), ("total_liabilities", "Total Liabilities"),
                ("shareholder_equity", "Shareholder Equity"), ("book_value", "Book Value"),
                ("tangible_book_value", "Tangible Book Value"), ("goodwill", "Goodwill"),
                ("inventory", "Inventory Levels"), ("receivables", "Accounts Receivable"),
                ("payables", "Accounts Payable"),
            ]
        ],
    },
    {
        "section": "Dividends",
        "items": [
            _catalog_item(k, label, False, NEEDS_FINANCIALS) for k, label in [
                ("dividend_yield", "Dividend Yield"), ("dividend_growth", "Dividend Growth Rate"),
                ("payout_ratio", "Dividend Payout Ratio"), ("dividend_history", "Dividend History"),
                ("dividend_safety", "Dividend Safety Score"),
            ]
        ],
    },
    {
        "section": "Ownership & Institutional Data",
        "items": [
            _catalog_item(k, label, False, NEEDS_OWNERSHIP) for k, label in [
                ("institutional_ownership", "Institutional Ownership"), ("insider_ownership", "Insider Ownership"),
                ("insider_buying", "Insider Buying"), ("insider_selling", "Insider Selling"),
                ("fund_holdings", "Mutual Fund Holdings"), ("short_interest", "Short Interest"),
                ("shares_outstanding", "Shares Outstanding"), ("float_shares", "Float Shares"),
                ("buybacks", "Share Buybacks"), ("dilution_history", "Dilution History"),
            ]
        ],
    },
    {
        "section": "Market Performance",
        "items": [
            _catalog_item("market_cap", "Market Capitalization", False, NEEDS_FINANCIALS),
            _catalog_item("ev2", "Enterprise Value", False, NEEDS_FINANCIALS),
            _catalog_item("week52_high", "52-Week High", True, filter_key="week52_high"),
            _catalog_item("week52_low", "52-Week Low", True, filter_key="week52_low"),
            _catalog_item("relative_strength", "Relative Strength Rating", False, NEEDS_HISTORY),
            _catalog_item("beta", "Beta", False, NEEDS_HISTORY),
            _catalog_item("alpha", "Alpha", False, NEEDS_HISTORY),
            _catalog_item("volatility", "Volatility", False, NEEDS_HISTORY),
            _catalog_item("atr", "ATR", False, NEEDS_HISTORY),
            _catalog_item("volume", "Trading Volume", True, filter_key="volume"),
        ],
    },
    {
        "section": "Technical Analysis",
        "items": [
            _catalog_item("ema20", "20 EMA", True, filter_key="ema20"),
            _catalog_item("sma50", "50 SMA", True, filter_key="sma50"),
            _catalog_item("sma100", "100 SMA", True, filter_key="sma100"),
            _catalog_item("sma200", "200 SMA", True, filter_key="sma200"),
            _catalog_item("golden_cross", "Golden Cross", True, filter_key="golden_cross"),
            _catalog_item("death_cross", "Death Cross", True, filter_key="death_cross"),
            _catalog_item("rsi", "RSI", True, filter_key="rsi"),
            _catalog_item("rsi_bull_div", "Bullish RSI Divergence", False, NEEDS_PATTERN_ENGINE),
            _catalog_item("macd", "MACD", True, filter_key="macd"),
            _catalog_item("macd_div", "MACD Divergence", False, NEEDS_PATTERN_ENGINE),
            _catalog_item("bollinger", "Bollinger Bands", False, NEEDS_HISTORY),
            _catalog_item("vwap", "VWAP", False, "Needs intraday tick data (not just daily closes)"),
            _catalog_item("adx", "ADX", False, NEEDS_HISTORY),
            _catalog_item("obv", "OBV", True, filter_key="obv"),
            _catalog_item("support", "Support Levels", False, NEEDS_PATTERN_ENGINE),
            _catalog_item("resistance", "Resistance Levels", False, NEEDS_PATTERN_ENGINE),
            _catalog_item("breakout", "Breakout Detection", False, NEEDS_PATTERN_ENGINE),
            _catalog_item("volume_confirmation", "Volume Confirmation", True, filter_key="high_volume"),
        ],
    },
    {
        "section": "Smart Money Concepts",
        "items": [
            _catalog_item(k, label, False, NEEDS_PATTERN_ENGINE) for k, label in [
                ("order_blocks", "Order Blocks"), ("demand_zones", "Demand Zones"), ("supply_zones", "Supply Zones"),
                ("liquidity_zones", "Liquidity Zones"), ("liquidity_sweep", "Liquidity Sweep"),
                ("fvg", "Fair Value Gap (FVG)"), ("bos", "Break of Structure (BOS)"),
                ("choch", "Change of Character (CHoCH)"), ("institutional_accumulation", "Institutional Accumulation"),
                ("wyckoff", "Wyckoff Accumulation"), ("volume_profile", "Volume Profile"),
                ("poc", "Point of Control"),
            ]
        ],
    },
    {
        "section": "Price Action & Patterns",
        "items": [
            _catalog_item(k, label, False, NEEDS_PATTERN_ENGINE) for k, label in [
                ("higher_highs", "Higher Highs"), ("higher_lows", "Higher Lows"), ("trend_reversal", "Trend Reversal"),
                ("breakout_retest", "Breakout Retest"), ("cup_handle", "Cup and Handle"),
                ("double_bottom", "Double Bottom"), ("inv_head_shoulders", "Inverse Head and Shoulders"),
                ("bull_flag", "Bull Flag"), ("ascending_triangle", "Ascending Triangle"), ("base_formation", "Base Formation"),
            ]
        ],
    },
    {
        "section": "Risk Management",
        "items": [
            _catalog_item(k, label, False, NEEDS_HISTORY) for k, label in [
                ("sharpe", "Sharpe Ratio"), ("sortino", "Sortino Ratio"), ("max_drawdown", "Maximum Drawdown"),
                ("var", "Value at Risk"), ("risk_reward", "Risk/Reward Ratio"), ("position_sizing", "Position Sizing"),
                ("stop_loss", "Stop Loss Placement"),
            ]
        ],
    },
    {
        "section": "Today's Trading (available now)",
        "items": [
            _catalog_item("price", "Price", True, filter_key="price"),
            _catalog_item("change_pct", "Change % Today", True, filter_key="change_pct"),
            _catalog_item("one_year_change", "1-Year Change %", True, filter_key="one_year_change"),
            _catalog_item("ytd_change", "YTD Change %", True, filter_key="ytd_change"),
            _catalog_item("sector", "Sector", True, filter_key="sector"),
            _catalog_item("above_ldcp", "Trading Above Yesterday's Close (LDCP)", True, filter_key="above_ldcp"),
        ],
    },
]


def stock_matches_filters(quote, criteria):
    def in_range(value, min_key, max_key):
        if value is None:
            return not (criteria.get(min_key) is not None or criteria.get(max_key) is not None)
        if criteria.get(min_key) is not None and value < criteria[min_key]:
            return False
        if criteria.get(max_key) is not None and value > criteria[max_key]:
            return False
        return True

    if not in_range(quote.get("price"), "price_min", "price_max"):
        return False
    if not in_range(quote.get("change_pct"), "change_pct_min", "change_pct_max"):
        return False
    if not in_range(quote.get("pe_ratio"), "pe_min", "pe_max"):
        return False
    if not in_range(quote.get("one_year_change"), "one_year_change_min", "one_year_change_max"):
        return False
    if not in_range(quote.get("ytd_change"), "ytd_change_min", "ytd_change_max"):
        return False

    if criteria.get("volume_min") is not None:
        if quote.get("volume") is None or quote["volume"] < criteria["volume_min"]:
            return False

    if criteria.get("sectors"):
        if quote.get("sector") not in criteria["sectors"]:
            return False

    if criteria.get("above_ldcp"):
        price, ldcp = quote.get("price"), quote.get("ldcp")
        if price is None or ldcp is None or price <= ldcp:
            return False

    if criteria.get("week52_position"):
        low, high, price = quote.get("low52"), quote.get("high52"), quote.get("price")
        if low is None or high is None or price is None or high <= low:
            return False
        pct = (price - low) / (high - low) * 100
        pos = criteria["week52_position"]
        if pos == "near_high" and pct < 90:
            return False
        if pos == "near_low" and pct > 10:
            return False
        if pos == "mid" and not (25 <= pct <= 75):
            return False

    # Technical indicators (computed from stock_price_history — see
    # compute_technicals). Any of these return None until enough
    # trading-day history has been recorded, and in_range/boolean
    # checks below correctly treat "not enough history yet" as a
    # non-match rather than fabricating a pass.
    if not in_range(quote.get("rsi14"), "rsi_min", "rsi_max"):
        return False

    if criteria.get("above_sma20") and quote.get("above_sma20") is not True:
        return False
    if criteria.get("above_sma50") and quote.get("above_sma50") is not True:
        return False
    if criteria.get("above_sma200") and quote.get("above_sma200") is not True:
        return False
    if criteria.get("golden_cross") and quote.get("golden_death_cross") != "golden_cross":
        return False
    if criteria.get("death_cross") and quote.get("golden_death_cross") != "death_cross":
        return False
    if criteria.get("macd_bullish") and quote.get("macd_bullish") is not True:
        return False
    if criteria.get("rsi_oversold") and quote.get("rsi_oversold") is not True:
        return False
    if criteria.get("rsi_overbought") and quote.get("rsi_overbought") is not True:
        return False

    return True


def compute_premarket_signal():
    """Pre-market read: flags when more of the tracked global
    markets/commodities are trading down than up, ahead of PSX's own
    open. Uses live vendor data when MARKET_DATA_API_KEY is set
    (get_multi_market_live), and falls back to the MULTI_MARKET
    development snapshot otherwise."""
    markets = get_multi_market_live()
    global_markets = [m for m in markets if m["key"] != "kse100"]
    down = [m for m in global_markets if m.get("tone") == "down"]
    up = [m for m in global_markets if m.get("tone") == "up"]

    return {
        "alert": len(down) > len(up),
        "down_count": len(down),
        "up_count": len(up),
        "down_markets": [m["name"] for m in down],
        "live": bool(MARKET_DATA_API_KEY),
        "note": (
            "Live vendor data." if MARKET_DATA_API_KEY else
            "Development signal from the Markets snapshot data. Set MARKET_DATA_API_KEY for a live pre-open feed."
        ),
    }


def db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row

    return conn


def init_db():
    conn = db()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS holdings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol TEXT NOT NULL UNIQUE,
        quantity REAL NOT NULL,
        avg_cost REAL NOT NULL,
        acquired_date TEXT
    );

    CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT NOT NULL,
        symbol TEXT NOT NULL,
        type TEXT NOT NULL,
        quantity REAL NOT NULL,
        price REAL NOT NULL
    );

    CREATE TABLE IF NOT EXISTS watchlist (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol TEXT NOT NULL UNIQUE
    );

    CREATE TABLE IF NOT EXISTS portfolio_daily (
        day TEXT PRIMARY KEY,
        invested REAL NOT NULL,
        value REAL NOT NULL,
        pnl REAL NOT NULL,
        pnl_pct REAL NOT NULL
    );

    CREATE TABLE IF NOT EXISTS holding_daily (
        day TEXT NOT NULL,
        symbol TEXT NOT NULL,
        price REAL NOT NULL,
        quantity REAL NOT NULL,
        avg_cost REAL NOT NULL,
        invested REAL NOT NULL,
        value REAL NOT NULL,
        pnl REAL NOT NULL,
        pnl_pct REAL NOT NULL,
        PRIMARY KEY(day, symbol)
    );

    CREATE TABLE IF NOT EXISTS stock_price_history (
        day TEXT NOT NULL,
        symbol TEXT NOT NULL,
        close REAL,
        high REAL,
        low REAL,
        volume REAL,
        PRIMARY KEY(day, symbol)
    );

    CREATE TABLE IF NOT EXISTS fund_nav_history (
        day TEXT NOT NULL,
        fund_name TEXT NOT NULL,
        nav REAL,
        PRIMARY KEY(day, fund_name)
    );
    """)

    # Upgrade older database: add sort_order to holdings/watchlist if missing.
    holdings_columns = {
        row["name"] for row in conn.execute("PRAGMA table_info(holdings)").fetchall()
    }
    if "sort_order" not in holdings_columns:
        conn.execute("ALTER TABLE holdings ADD COLUMN sort_order INTEGER DEFAULT 0")
        conn.execute(
            "UPDATE holdings SET sort_order = id WHERE sort_order IS NULL OR sort_order = 0"
        )

    watchlist_columns = {
        row["name"] for row in conn.execute("PRAGMA table_info(watchlist)").fetchall()
    }
    if "sort_order" not in watchlist_columns:
        conn.execute("ALTER TABLE watchlist ADD COLUMN sort_order INTEGER DEFAULT 0")
        conn.execute(
            "UPDATE watchlist SET sort_order = id WHERE sort_order IS NULL OR sort_order = 0"
        )
    if "asset_type" not in watchlist_columns:
        # asset_type: 'stock' (default, uses live get_quote), 'crypto',
        # 'forex', or 'fund'. For non-stock types we can't call
        # get_quote (that's PSX-specific), so we store a display name
        # and a last-seen price/change snapshot at the time it was
        # added, refreshed opportunistically from the live endpoints.
        conn.execute("ALTER TABLE watchlist ADD COLUMN asset_type TEXT DEFAULT 'stock'")
        conn.execute("ALTER TABLE watchlist ADD COLUMN display_name TEXT")
        conn.execute("ALTER TABLE watchlist ADD COLUMN last_price REAL")
        conn.execute("ALTER TABLE watchlist ADD COLUMN last_change_pct REAL")

    # Upgrade older database if acquired_date does not exist.
    columns = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(holdings)").fetchall()
    }
    if "acquired_date" not in columns:
        conn.execute("ALTER TABLE holdings ADD COLUMN acquired_date TEXT")

    if conn.execute("SELECT COUNT(*) FROM holdings").fetchone()[0] == 0:
        today = date.today().isoformat()
        conn.executemany(
            """
            INSERT INTO holdings(symbol,quantity,avg_cost,acquired_date)
            VALUES(?,?,?,?)
            """,
            [
                ("FFC", 700, 350, today),
                ("UBL", 450, 310, today),
                ("OGDC", 800, 190, today),
                ("MARI", 250, 590, today),
                ("HBL", 500, 155, today),
                ("EFERT", 350, 170, today),
            ]
        )

    if conn.execute("SELECT COUNT(*) FROM watchlist").fetchone()[0] == 0:
        conn.executemany(
            "INSERT INTO watchlist(symbol) VALUES(?)",
            [("LUCK",), ("SYS",), ("PPL",), ("MCB",)]
        )

    conn.commit()
    conn.close()


# ---------------------------------------------------------
# PSX symbol directory
# ---------------------------------------------------------

def fetch_psx_symbols(force=False):
    now = datetime.now()

    with _symbol_lock:
        if (
            not force
            and _symbol_cache["items"]
            and _symbol_cache["time"]
            and now - _symbol_cache["time"] < timedelta(minutes=SYMBOL_CACHE_MINUTES)
        ):
            return _symbol_cache["items"]

    response = requests.get(
        PSX_SYMBOLS_URL,
        headers=HEADERS,
        timeout=20
    )
    response.raise_for_status()
    raw = response.json()

    items = []
    seen = set()

    for row in raw:
        if row.get("isDebt") or row.get("isETF"):
            continue

        symbol = str(row.get("symbol", "")).strip().upper()
        company = str(row.get("name", "")).strip()
        sector = str(row.get("sectorName", "")).strip()

        if not symbol or symbol in seen:
            continue

        seen.add(symbol)
        items.append({
            "symbol": symbol,
            "company": company,
            "sector": sector,
        })

    items.sort(key=lambda x: x["symbol"])

    with _symbol_lock:
        _symbol_cache["items"] = items
        _symbol_cache["time"] = now

    return items


def symbol_metadata(symbol):
    symbol = symbol.upper()

    try:
        for row in fetch_psx_symbols():
            if row["symbol"] == symbol:
                return row
    except requests.RequestException:
        pass

    fallback = FALLBACK_QUOTES.get(symbol, {})

    return {
        "symbol": symbol,
        "company": fallback.get("company", symbol),
        "sector": fallback.get("sector", ""),
    }


# ---------------------------------------------------------
# PSX company-page quote parser
# ---------------------------------------------------------

def _number(value):
    if value is None:
        return None
    try:
        return float(str(value).replace(",", "").strip())
    except (ValueError, TypeError):
        return None


def _downsample(values, target_len):
    """Reduce a long series (e.g. CoinGecko's ~168 hourly 7d points) to
    roughly target_len evenly-spaced points, for a lightweight sparkline
    without shipping hundreds of points to the browser."""
    values = [v for v in (values or []) if v is not None]
    if len(values) <= target_len:
        return values

    step = len(values) / target_len
    return [values[int(i * step)] for i in range(target_len)]


def _integer(value):
    if value is None:
        return None
    try:
        return int(float(str(value).replace(",", "").strip()))
    except (ValueError, TypeError):
        return None


def _search(text, pattern, flags=re.I):
    match = re.search(pattern, text, flags)
    return match.group(1).strip() if match else None


def parse_company_page(symbol, html):
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ", strip=True)
    meta = symbol_metadata(symbol)

    price_match = re.search(r'data-current="([\d,.]+)"', html, re.I)
    price = _number(price_match.group(1)) if price_match else None

    # Header commonly contains: Rs.221.55 -0.93 (-0.42%)
    header = re.search(
        r'Rs\.\s*([\d,.]+)\s+([+-]?\d[\d,.]*)\s+\(\s*([+-]?\d+(?:\.\d+)?)%\s*\)',
        text,
        re.I
    )

    change = None
    change_pct = None
    if header:
        price = price or _number(header.group(1))
        change = _number(header.group(2))
        change_pct = _number(header.group(3))

    quote = {
        **meta,
        "price": price,
        "change": change,
        "change_pct": change_pct,
        "open": _number(_search(text, r'\bOpen\s*([\d,.]+)')),
        "high": _number(_search(text, r'\bHigh\s*([\d,.]+)')),
        "low": _number(_search(text, r'\bLow\s*([\d,.]+)')),
        "volume": _integer(_search(text, r'\bVolume\s*([\d,]+)')),
        "ldcp": _number(_search(text, r'\bLDCP\s*([\d,.]+)')),
        "ask_price": _number(_search(text, r'\bAsk Price\s*([\d,.]+)')),
        "ask_volume": _integer(_search(text, r'\bAsk Volume\s*([\d,]+)')),
        "bid_price": _number(_search(text, r'\bBid Price\s*([\d,.]+)')),
        "bid_volume": _integer(_search(text, r'\bBid Volume\s*([\d,]+)')),
        "pe_ratio": _number(_search(text, r'P/E Ratio\s*\(TTM\)\s*([\d,.]+)')),
        "one_year_change": _number(_search(text, r'1-Year Change[^0-9+\-]*([+\-]?\d+(?:\.\d+)?)%')),
        "ytd_change": _number(_search(text, r'YTD Change[^0-9+\-]*([+\-]?\d+(?:\.\d+)?)%')),
        "last_update": _search(text, r'Last update:\s*([^*]+?)(?=\s+Open\b|\s+Company Profile\b|$)'),
    }

    day_range = re.search(
        r'DAY RANGE\s*([\d,.]+)\s*[—-]\s*([\d,.]+)',
        text,
        re.I
    )
    if day_range:
        quote["day_low"] = _number(day_range.group(1))
        quote["day_high"] = _number(day_range.group(2))
    else:
        quote["day_low"] = quote["low"]
        quote["day_high"] = quote["high"]

    range52 = re.search(
        r'52-WEEK RANGE[^\d]*([\d,.]+)\s*[—-]\s*([\d,.]+)',
        text,
        re.I
    )
    if range52:
        quote["low52"] = _number(range52.group(1))
        quote["high52"] = _number(range52.group(2))
    else:
        quote["low52"] = None
        quote["high52"] = None

    circuit = re.search(
        r'CIRCUIT BREAKER\s*([\d,.]+)\s*[—-]\s*([\d,.]+)',
        text,
        re.I
    )
    if circuit:
        quote["circuit_low"] = _number(circuit.group(1))
        quote["circuit_high"] = _number(circuit.group(2))
    else:
        quote["circuit_low"] = None
        quote["circuit_high"] = None

    return quote


def get_quote(symbol, force=False):
    symbol = symbol.upper()
    now = datetime.now()

    with _quote_lock:
        cached = _quote_cache.get(symbol)
        if (
            not force
            and cached
            and now - cached["time"] < timedelta(seconds=QUOTE_CACHE_SECONDS)
        ):
            return cached["quote"]

    url = PSX_COMPANY_URL.format(symbol=symbol)

    try:
        response = requests.get(url, headers=HEADERS, timeout=15)
        response.raise_for_status()
        quote = parse_company_page(symbol, response.text)

        if quote.get("price") is None:
            fallback = FALLBACK_QUOTES.get(symbol, {})
            quote["price"] = fallback.get("price")
            quote["change_pct"] = quote.get("change_pct") if quote.get("change_pct") is not None else fallback.get("change")
            quote["volume"] = quote.get("volume") if quote.get("volume") is not None else fallback.get("volume")

        quote["source"] = "PSX company page"
        quote["fetched_at"] = now.isoformat(timespec="seconds")

        with _quote_lock:
            _quote_cache[symbol] = {
                "time": now,
                "quote": quote
            }

        return quote

    except requests.RequestException as exc:
        fallback = FALLBACK_QUOTES.get(symbol)
        if fallback:
            return {
                "symbol": symbol,
                **fallback,
                "change_pct": fallback.get("change"),
                "source": "Development fallback",
                "error": str(exc),
                "fetched_at": now.isoformat(timespec="seconds"),
            }

        return {
            **symbol_metadata(symbol),
            "price": None,
            "volume": None,
            "source": "Unavailable",
            "error": str(exc),
            "fetched_at": now.isoformat(timespec="seconds"),
        }


def record_daily_prices(quotes):
    """Persist today's close/high/low/volume for every symbol in a bulk
    fetch, so technical indicators (SMA, EMA, RSI, MACD, OBV) become
    computable over time. This is the mechanism that "activates" those
    screener filters — they start returning real matches once enough
    trading days have been recorded (see compute_technicals below)."""
    today = date.today().isoformat()
    conn = db()

    rows = [
        (
            today,
            q.get("symbol"),
            q.get("price"),
            q.get("high"),
            q.get("low"),
            q.get("volume"),
        )
        for q in quotes
        if q.get("symbol") and q.get("price") is not None
    ]

    conn.executemany(
        """
        INSERT INTO stock_price_history(day,symbol,close,high,low,volume)
        VALUES(?,?,?,?,?,?)
        ON CONFLICT(day,symbol) DO UPDATE SET
            close=excluded.close,
            high=excluded.high,
            low=excluded.low,
            volume=excluded.volume
        """,
        rows
    )

    conn.commit()
    conn.close()


def get_price_history(symbol, limit=260):
    conn = db()
    rows = conn.execute(
        """
        SELECT day, close, high, low, volume
        FROM stock_price_history
        WHERE symbol = ?
        ORDER BY day DESC
        LIMIT ?
        """,
        (symbol.upper(), limit)
    ).fetchall()
    conn.close()

    rows = [dict(r) for r in rows]
    rows.reverse()  # oldest -> newest
    return rows


# Trading-day thresholds each indicator needs before it's "activated".
TECHNICAL_REQUIREMENTS = {
    "sma20": 20, "sma50": 50, "sma100": 100, "sma200": 200,
    "ema20": 20, "rsi": 15, "macd": 35, "obv": 2,
    "golden_cross": 201, "death_cross": 201,
}

RECORDING_START_NOTE = (
    "Yalvon360 started recording each PSX stock's daily close on the day "
    "this feature was turned on. This indicator needs {needed} trading "
    "days of history; {have} recorded so far ({pct}% there)."
)


def _sma(values, n):
    if len(values) < n:
        return None
    return sum(values[-n:]) / n


def _ema_series(values, n):
    if len(values) < n:
        return []
    k = 2 / (n + 1)
    ema = [sum(values[:n]) / n]
    for price in values[n:]:
        ema.append(price * k + ema[-1] * (1 - k))
    return ema


def _rsi(values, n=14):
    if len(values) < n + 1:
        return None

    gains, losses = [], []
    for i in range(1, len(values)):
        change = values[i] - values[i - 1]
        gains.append(max(0.0, change))
        losses.append(max(0.0, -change))

    avg_gain = sum(gains[:n]) / n
    avg_loss = sum(losses[:n]) / n

    for i in range(n, len(gains)):
        avg_gain = (avg_gain * (n - 1) + gains[i]) / n
        avg_loss = (avg_loss * (n - 1) + losses[i]) / n

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def _macd(values):
    if len(values) < 35:
        return None, None, None

    ema12 = _ema_series(values, 12)
    ema26 = _ema_series(values, 26)
    offset = len(ema12) - len(ema26)
    macd_line = [a - b for a, b in zip(ema12[offset:], ema26)]

    if len(macd_line) < 9:
        return None, None, None

    signal_line = _ema_series(macd_line, 9)
    macd_val = macd_line[-1]
    signal_val = signal_line[-1]
    return macd_val, signal_val, macd_val - signal_val


def _obv(closes, volumes):
    if len(closes) < 2 or any(v is None for v in volumes):
        return None
    obv = 0
    for i in range(1, len(closes)):
        if closes[i] > closes[i - 1]:
            obv += volumes[i] or 0
        elif closes[i] < closes[i - 1]:
            obv -= volumes[i] or 0
    return obv


def compute_technicals(symbol):
    """Real technical indicators computed from stock_price_history.
    Returns None for any indicator that doesn't have enough recorded
    trading days yet, plus a 'progress' dict so the UI can show exactly
    how close each one is to activating — never a fabricated value."""
    history = get_price_history(symbol)
    closes = [h["close"] for h in history if h["close"] is not None]
    volumes = [h["volume"] for h in history]
    have = len(closes)

    sma20 = _sma(closes, 20)
    sma50 = _sma(closes, 50)
    sma100 = _sma(closes, 100)
    sma200 = _sma(closes, 200)
    ema20_series = _ema_series(closes, 20)
    ema20 = ema20_series[-1] if ema20_series else None
    rsi14 = _rsi(closes, 14)
    macd_val, macd_signal, macd_hist = _macd(closes)
    obv = _obv(closes, volumes)

    golden_death = None
    if sma50 is not None and sma200 is not None and have >= 201:
        prev_closes = closes[:-1]
        prev_sma50 = _sma(prev_closes, 50)
        prev_sma200 = _sma(prev_closes, 200)
        if prev_sma50 is not None and prev_sma200 is not None:
            if prev_sma50 <= prev_sma200 and sma50 > sma200:
                golden_death = "golden_cross"
            elif prev_sma50 >= prev_sma200 and sma50 < sma200:
                golden_death = "death_cross"
            elif sma50 > sma200:
                golden_death = "bullish_alignment"
            else:
                golden_death = "bearish_alignment"

    def progress(key):
        needed = TECHNICAL_REQUIREMENTS[key]
        pct = min(100, round(have / needed * 100)) if needed else 100
        return {
            "have": have, "needed": needed, "pct": pct,
            "note": RECORDING_START_NOTE.format(needed=needed, have=have, pct=pct),
        }

    return {
        "symbol": symbol.upper(),
        "data_days": have,
        "price": closes[-1] if closes else None,
        "sma20": sma20, "sma50": sma50, "sma100": sma100, "sma200": sma200,
        "ema20": ema20, "rsi14": rsi14,
        "macd": macd_val, "macd_signal": macd_signal, "macd_histogram": macd_hist,
        "obv": obv,
        "golden_death_cross": golden_death,
        "above_sma20": (closes[-1] > sma20) if (closes and sma20) else None,
        "above_sma50": (closes[-1] > sma50) if (closes and sma50) else None,
        "above_sma200": (closes[-1] > sma200) if (closes and sma200) else None,
        "rsi_overbought": (rsi14 >= 70) if rsi14 is not None else None,
        "rsi_oversold": (rsi14 <= 30) if rsi14 is not None else None,
        "macd_bullish": (macd_hist > 0) if macd_hist is not None else None,
        "progress": {key: progress(key) for key in TECHNICAL_REQUIREMENTS},
    }


def refresh_technicals_cache(symbols):
    """Precompute technicals in parallel during the background refresh."""
    import concurrent.futures
    symbols = [s for s in symbols if s]
    fresh = {}

    def one(symbol):
        try:
            return symbol, compute_technicals(symbol)
        except Exception:
            return symbol, None

    with concurrent.futures.ThreadPoolExecutor(max_workers=min(12, max(1, len(symbols)))) as pool:
        for symbol, value in pool.map(one, symbols):
            if value:
                fresh[symbol] = value

    with _technicals_cache_lock:
        _technicals_cache.clear()
        _technicals_cache.update(fresh)

    with _screener_cache_lock:
        _screener_result_cache.clear()


def get_cached_technicals(symbol):
    with _technicals_cache_lock:
        cached = _technicals_cache.get(symbol.upper())
    return cached if cached else compute_technicals(symbol)


# ---------------------------------------------------------
# Bulk "all PSX stocks, live" fetch
# ---------------------------------------------------------

def _fetch_one_for_bulk(symbol):
    try:
        return get_quote(symbol)
    except Exception as exc:  # keep the bulk pass alive even if one symbol errors
        return {"symbol": symbol, "price": None, "source": "Unavailable", "error": str(exc)}


def refresh_bulk_quotes():
    """Fetch a live-ish price for every symbol in the PSX directory,
    with limited concurrency, and store the result in _bulk_quote_cache.
    Safe to call from a background thread or an on-demand route. Falls
    back to the known FALLBACK_QUOTES symbols if the live directory
    itself can't be reached, so the page still has something to show.
    Also persists today's close/high/low/volume per symbol so technical
    indicators accumulate real history over time (record_daily_prices)."""
    import concurrent.futures

    with _bulk_quote_lock:
        if _bulk_quote_cache["in_progress"]:
            return
        _bulk_quote_cache["in_progress"] = True

    try:
        try:
            symbols = [row["symbol"] for row in fetch_psx_symbols()]
        except requests.RequestException:
            symbols = list(FALLBACK_QUOTES.keys())

        results = []

        with concurrent.futures.ThreadPoolExecutor(max_workers=BULK_FETCH_WORKERS) as pool:
            for quote in pool.map(_fetch_one_for_bulk, symbols):
                results.append(quote)

        with _bulk_quote_lock:
            _bulk_quote_cache["items"] = results
            _bulk_quote_cache["time"] = datetime.now()

        try:
            record_daily_prices(results)
            refresh_technicals_cache([q.get("symbol") for q in results if q.get("symbol")])
        except Exception:
            pass  # never let history recording break the live-quotes flow
    finally:
        with _bulk_quote_lock:
            _bulk_quote_cache["in_progress"] = False



def get_bulk_quotes(force=False):
    with _bulk_quote_lock:
        stale = (
            _bulk_quote_cache["time"] is None
            or datetime.now() - _bulk_quote_cache["time"] > timedelta(minutes=BULK_REFRESH_MINUTES)
        )
        has_items = bool(_bulk_quote_cache["items"])

    if force:
        refresh_bulk_quotes()
    elif stale and not has_items:
        # Do not make the first browser request wait for hundreds of upstream
        # requests. Serve a tiny built-in snapshot while the full universe
        # warms in the background.
        fallback = [
            {"symbol": symbol, **quote, "change_pct": quote.get("change")}
            for symbol, quote in FALLBACK_QUOTES.items()
        ]
        with _bulk_quote_lock:
            _bulk_quote_cache["items"] = fallback
            _bulk_quote_cache["time"] = datetime.now()
        threading.Thread(target=refresh_bulk_quotes, daemon=True).start()
    elif stale:
        # Cache is stale but we already have something to show — refresh
        # in the background and serve the slightly-old data immediately.
        threading.Thread(target=refresh_bulk_quotes, daemon=True).start()

    with _bulk_quote_lock:
        return {
            "items": list(_bulk_quote_cache["items"]),
            "updated_at": _bulk_quote_cache["time"].isoformat(timespec="seconds") if _bulk_quote_cache["time"] else None,
        }


def start_bulk_refresh_thread():
    def loop():
        while True:
            try:
                refresh_bulk_quotes()
            except Exception:
                pass
            threading.Event().wait(BULK_REFRESH_MINUTES * 60)

    threading.Thread(target=loop, daemon=True).start()


# ---------------------------------------------------------
# Fundamentals (best-effort, from the same PSX company page)
# ---------------------------------------------------------

def get_fundamentals(symbol):
    """Whatever fundamental-ish fields we can pull from PSX's public
    company page, plus clearly-labeled placeholders for the fields PSX
    does not expose publicly (book value, dividend yield/history,
    full financial statements). Those need a licensed data vendor —
    the fields are kept here, set to None, so the UI has a stable
    shape to render against once a real source is wired in."""
    quote = get_quote(symbol)

    return {
        "symbol": symbol.upper(),
        "company": quote.get("company"),
        "sector": quote.get("sector"),
        "price": quote.get("price"),
        "pe_ratio_ttm": quote.get("pe_ratio"),
        "one_year_change_pct": quote.get("one_year_change"),
        "ytd_change_pct": quote.get("ytd_change"),
        "ldcp": quote.get("ldcp"),
        "day_range": [quote.get("day_low"), quote.get("day_high")],
        "week52_range": [quote.get("low52"), quote.get("high52")],
        "volume": quote.get("volume"),
        # Not available from PSX's public pages — needs a licensed vendor.
        "eps_ttm": None,
        "book_value_per_share": None,
        "dividend_yield_pct": None,
        "dividend_history": [],
        "source": quote.get("source"),
        "note": (
            "PE ratio, YTD/1-year change and price range come from PSX's "
            "public company page. EPS, book value, dividend yield and "
            "dividend history are not exposed there and need a licensed "
            "fundamentals data vendor to populate."
        ),
    }


# ---------------------------------------------------------
# Pakistan mutual funds (MUFAP)
# ---------------------------------------------------------

def fetch_mufap_funds(force=False):
    """Best-effort live scrape of MUFAP's public NAV listing, enriched
    with AMC/category/AUM from the person's uploaded MUFAP "Asset
    Allocation" export (MUFAP_FUND_DIRECTORY) where names match. If the
    live scrape fails entirely, falls back to serving the full uploaded
    directory directly (392 real funds, AUM-based, no live NAV) rather
    than a tiny placeholder list — the page always says which source
    it's showing via the returned label."""
    now = datetime.now()

    with _mufap_lock:
        cached = _mufap_cache
        if (
            not force
            and cached["time"]
            and now - cached["time"] < timedelta(minutes=MUFAP_CACHE_MINUTES)
        ):
            return cached["items"], cached["source"]

    directory_by_name = {f["name"].strip().lower(): f for f in MUFAP_FUND_DIRECTORY}

    try:
        response = requests.get(MUFAP_NAV_URL, headers=HEADERS, timeout=20)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        funds = []
        for row in soup.select("table tr"):
            cells = [c.get_text(" ", strip=True) for c in row.find_all(["td", "th"])]
            if len(cells) < 3:
                continue

            name = cells[0]
            nav = _number(cells[1]) if len(cells) > 1 else None

            if not name or nav is None or name.lower() in ("fund name", "fund"):
                continue

            match = directory_by_name.get(name.strip().lower())

            funds.append({
                "name": name,
                "amc": match["amc"] if match else None,
                "category": cells[2] if len(cells) > 2 else (match["category"] if match else "—"),
                "inception": match["inception"] if match else None,
                "nav": nav,
                "ytd": _number(cells[3]) if len(cells) > 3 else None,
                "aum_mn": match["aum_mn"] if match else None,
            })

        if not funds:
            raise ValueError("No fund rows parsed from MUFAP page")

        with _mufap_lock:
            _mufap_cache["items"] = funds
            _mufap_cache["time"] = now
            _mufap_cache["source"] = "MUFAP live"

        try:
            record_fund_nav_history(funds)
        except Exception:
            pass  # never let history recording break the live-NAV flow

        return funds, "MUFAP live"

    except (requests.RequestException, ValueError) as exc:
        with _mufap_lock:
            _mufap_cache["items"] = MUFAP_FUND_DIRECTORY
            _mufap_cache["time"] = now
            _mufap_cache["source"] = "MUFAP directory (uploaded export, AUM-based)"

        return MUFAP_FUND_DIRECTORY, f"MUFAP directory (uploaded export, AUM-based) — live NAV scrape failed: {exc}"


def record_fund_nav_history(funds):
    """Persist today's NAV for every fund we got a real value for, so
    the Mutual Funds page can show a real trend sparkline over time —
    same recording-builds-up-over-time approach as stock_price_history
    for technical indicators."""
    today = date.today().isoformat()
    rows = [(today, f["name"], f["nav"]) for f in funds if f.get("nav") is not None]

    if not rows:
        return

    conn = db()
    conn.executemany(
        """
        INSERT INTO fund_nav_history(day, fund_name, nav)
        VALUES(?,?,?)
        ON CONFLICT(day, fund_name) DO UPDATE SET nav=excluded.nav
        """,
        rows
    )
    conn.commit()
    conn.close()


def get_fund_trends(fund_names, limit=14):
    """Bulk-fetch recent NAV history for many funds in one query
    (rather than one query per fund), keyed by fund name."""
    if not fund_names:
        return {}

    conn = db()
    placeholders = ",".join("?" * len(fund_names))
    rows = conn.execute(
        f"""
        SELECT fund_name, day, nav FROM fund_nav_history
        WHERE fund_name IN ({placeholders})
        ORDER BY fund_name, day DESC
        """,
        list(fund_names)
    ).fetchall()
    conn.close()

    trends = {}
    for row in rows:
        trends.setdefault(row["fund_name"], [])
        if len(trends[row["fund_name"]]) < limit:
            trends[row["fund_name"]].append(row["nav"])

    for name in trends:
        trends[name].reverse()

    return trends


# ---------------------------------------------------------
# Live crypto prices (CoinGecko public markets API — no key needed)
# ---------------------------------------------------------

CRYPTO_DEV_FALLBACK = [
    {"id": "bitcoin", "symbol": "BTC", "name": "Bitcoin", "current_price": 64888, "price_change_percentage_24h": 0.20, "market_cap": 1280000000000, "total_volume": 28000000000, "market_cap_rank": 1, "sparkline_7d": []},
    {"id": "ethereum", "symbol": "ETH", "name": "Ethereum", "current_price": 3450, "price_change_percentage_24h": 0.55, "market_cap": 415000000000, "total_volume": 14000000000, "market_cap_rank": 2, "sparkline_7d": []},
    {"id": "tether", "symbol": "USDT", "name": "Tether", "current_price": 1.00, "price_change_percentage_24h": 0.01, "market_cap": 118000000000, "total_volume": 55000000000, "market_cap_rank": 3, "sparkline_7d": []},
    {"id": "binancecoin", "symbol": "BNB", "name": "BNB", "current_price": 590, "price_change_percentage_24h": -0.30, "market_cap": 86000000000, "total_volume": 1800000000, "market_cap_rank": 4, "sparkline_7d": []},
    {"id": "solana", "symbol": "SOL", "name": "Solana", "current_price": 148, "price_change_percentage_24h": 1.10, "market_cap": 70000000000, "total_volume": 3200000000, "market_cap_rank": 5, "sparkline_7d": []},
]


def fetch_crypto_live(force=False):
    """Top cryptocurrencies by market cap, live from CoinGecko's free
    public markets endpoint (no API key required). Falls back to a
    small labeled development list on any failure — same defensive
    pattern as fetch_mufap_funds above."""
    now = datetime.now()

    with _crypto_lock:
        cached = _crypto_cache
        if (
            not force
            and cached["time"]
            and now - cached["time"] < timedelta(seconds=CRYPTO_CACHE_SECONDS)
            and cached["items"]
        ):
            return cached["items"], cached["source"]

    try:
        all_coins = []
        for page in range(1, CRYPTO_PAGES + 1):
            response = requests.get(
                COINGECKO_MARKETS_URL,
                params={
                    "vs_currency": "usd",
                    "order": "market_cap_desc",
                    "per_page": CRYPTO_PER_PAGE,
                    "page": page,
                    "sparkline": "true",
                    "price_change_percentage": "24h",
                },
                headers=HEADERS,
                timeout=20,
            )
            response.raise_for_status()
            batch = response.json()
            if not isinstance(batch, list) or not batch:
                break
            all_coins.extend(batch)

        if not all_coins:
            raise ValueError("CoinGecko returned no coins")

        coins = [
            {
                "id": c.get("id"),
                "symbol": (c.get("symbol") or "").upper(),
                "name": c.get("name"),
                "current_price": c.get("current_price"),
                "price_change_percentage_24h": c.get("price_change_percentage_24h"),
                "market_cap": c.get("market_cap"),
                "total_volume": c.get("total_volume"),
                "market_cap_rank": c.get("market_cap_rank"),
                "sparkline_7d": _downsample(
                    (c.get("sparkline_in_7d") or {}).get("price") or [], 24
                ),
            }
            for c in all_coins
        ]

        with _crypto_lock:
            _crypto_cache["items"] = coins
            _crypto_cache["time"] = now
            _crypto_cache["source"] = "CoinGecko live"

        return coins, "CoinGecko live"

    except (requests.RequestException, ValueError) as exc:
        with _crypto_lock:
            _crypto_cache["items"] = CRYPTO_DEV_FALLBACK
            _crypto_cache["time"] = now
            _crypto_cache["source"] = "Development fallback"

        return CRYPTO_DEV_FALLBACK, f"Development fallback ({exc})"


def fetch_crypto_sentiment(force=False):
    """Live Crypto Fear & Greed Index from alternative.me's free public
    API (no key required, updates roughly once a day). Falls back to a
    labeled neutral development value on any failure."""
    now = datetime.now()

    with _crypto_sentiment_lock:
        cached = _crypto_sentiment_cache
        if (
            not force
            and cached["data"]
            and cached["time"]
            and now - cached["time"] < timedelta(minutes=CRYPTO_SENTIMENT_CACHE_MINUTES)
        ):
            return cached["data"]

    try:
        response = requests.get(ALTERNATIVE_ME_FNG_URL, params={"limit": 1}, headers=HEADERS, timeout=15)
        response.raise_for_status()
        payload = response.json()
        entry = (payload.get("data") or [None])[0]

        if not entry:
            raise ValueError("alternative.me returned no data")

        result = {
            "score": int(entry["value"]),
            "label": entry["value_classification"],
            "source": "alternative.me (live)",
        }

    except (requests.RequestException, ValueError, KeyError) as exc:
        result = {"score": 50, "label": "Neutral", "source": f"Development fallback ({exc})"}

    with _crypto_sentiment_lock:
        _crypto_sentiment_cache["data"] = result
        _crypto_sentiment_cache["time"] = now

    return result


# ---------------------------------------------------------
# Live forex rates (Frankfurter / ECB reference rates — no key needed)
# ---------------------------------------------------------

FOREX_DEV_FALLBACK = {
    "EUR": 0.912, "GBP": 0.786, "JPY": 149.20, "AUD": 1.534, "CAD": 1.368,
    "CHF": 0.879, "CNY": 7.145, "PKR": 277.85, "AED": 3.673, "SAR": 3.750,
    "INR": 83.40, "SGD": 1.345,
}


def fetch_forex_live(force=False, base="USD"):
    """Latest ECB reference exchange rates, live from Frankfurter's
    free public API (no API key required, no rate limit for personal
    use). Covers the ~30 currencies the ECB publishes rates for —
    which includes essentially all major and minor forex pairs;
    exotic/regional currencies beyond that need a different, usually
    paid, provider. Falls back to a small labeled development list on
    any failure."""
    now = datetime.now()

    with _forex_lock:
        cached = _forex_cache
        if (
            not force
            and cached["time"]
            and now - cached["time"] < timedelta(minutes=FOREX_CACHE_MINUTES)
            and cached["rates"]
        ):
            return cached["rates"], cached["source"], cached["date"]

    try:
        response = requests.get(
            FRANKFURTER_URL,
            params={"base": base},
            headers=HEADERS,
            timeout=15,
        )
        response.raise_for_status()
        payload = response.json()
        rates = payload.get("rates")

        if not rates:
            raise ValueError("Frankfurter returned no rates")

        # PKR isn't an ECB-tracked currency, so Frankfurter never
        # includes it. Layer in our own dev PKR rate so the Pakistan
        # angle of this page still shows something, clearly labeled.
        if "PKR" not in rates:
            rates = {**rates, "PKR": FOREX_DEV_FALLBACK["PKR"]}

        with _forex_lock:
            _forex_cache["rates"] = rates
            _forex_cache["time"] = now
            _forex_cache["source"] = "Frankfurter / ECB live"
            _forex_cache["date"] = payload.get("date")

        return rates, "Frankfurter / ECB live", payload.get("date")

    except (requests.RequestException, ValueError) as exc:
        with _forex_lock:
            _forex_cache["rates"] = FOREX_DEV_FALLBACK
            _forex_cache["time"] = now
            _forex_cache["source"] = f"Development fallback ({exc})"
            _forex_cache["date"] = None

        return FOREX_DEV_FALLBACK, f"Development fallback ({exc})", None


# ---------------------------------------------------------
# Live world indices / forex / commodities (optional vendor API)
# ---------------------------------------------------------

# Maps our internal MULTI_MARKET keys to a vendor's own symbol.
# Twelve Data uses e.g. "SPX" for S&P 500, "XAU/USD" for gold spot,
# "BTC/USD" for Bitcoin, "USD/CAD" for forex pairs, "CL" for WTI crude.
TWELVEDATA_SYMBOLS = {
    "kse100": None,  # PSX itself stays on the existing scraped source
    "spx": "SPX",
    "tadawul": "TASI",
    "btc": "BTC/USD",
    "gold": "XAU/USD",
    "wti": "CL",
    "usd": "DXY",
    "cad": "USD/CAD",
}


def fetch_live_index(key, symbol_map=None):
    """Fetch one live index/forex/commodity value from the configured
    vendor. Returns None (never raises) if no API key is set or the
    request fails, so callers can cleanly fall back to development
    data. symbol_map defaults to TWELVEDATA_SYMBOLS (world indices);
    pass COMMODITY_TWELVEDATA_SYMBOLS for commodities."""
    if not MARKET_DATA_API_KEY:
        return None

    symbol_map = symbol_map if symbol_map is not None else TWELVEDATA_SYMBOLS
    cache_key = f"{id(symbol_map)}:{key}"

    now = datetime.now()
    with _live_index_lock:
        cached = _live_index_cache.get(cache_key)
        if cached and now - cached["time"] < timedelta(seconds=LIVE_INDEX_CACHE_SECONDS):
            return cached["data"]

    if MARKET_DATA_PROVIDER == "twelvedata":
        vendor_symbol = symbol_map.get(key)
        if not vendor_symbol:
            return None

        try:
            response = requests.get(
                "https://api.twelvedata.com/quote",
                params={"symbol": vendor_symbol, "apikey": MARKET_DATA_API_KEY},
                timeout=10,
            )
            response.raise_for_status()
            payload = response.json()

            if "close" not in payload:
                return None

            data = {
                "price": _number(payload.get("close")),
                "change_pct": _number(payload.get("percent_change")),
                "change_abs": _number(payload.get("change")),
                "source": "Twelve Data (live)",
            }

            with _live_index_lock:
                _live_index_cache[cache_key] = {"time": now, "data": data}

            return data

        except (requests.RequestException, ValueError):
            return None

    # Other providers (Alpha Vantage, Finnhub, ...) can be added here
    # following the same pattern: fetch, normalize to
    # {price, change_pct, change_abs, source}, cache, return.
    return None


def get_multi_market_live():
    """MULTI_MARKET, with any items we have live data for overlaid on
    top of the development values. Falls back entirely to development
    data when MARKET_DATA_API_KEY is not set."""
    result = []

    for item in MULTI_MARKET:
        live = fetch_live_index(item["key"]) if item["key"] != "kse100" else None

        if live and live.get("price") is not None:
            tone = "up" if (live.get("change_pct") or 0) >= 0 else "down"
            result.append({
                **item,
                "price": live["price"],
                "change_pct": live["change_pct"],
                "change_abs": live["change_abs"],
                "tone": tone,
                "source": live["source"],
            })
        else:
            result.append({**item, "source": "Development value"})

    return result


COMMODITIES_DEV = [
    {"key": "gold", "name": "Gold", "price": 4399.70, "change_pct": -0.04, "unit": "USD/oz"},
    {"key": "silver", "name": "Silver", "price": 29.85, "change_pct": 0.62, "unit": "USD/oz"},
    {"key": "platinum", "name": "Platinum", "price": 985.50, "change_pct": -0.15, "unit": "USD/oz"},
    {"key": "wti", "name": "WTI Crude Oil", "price": 78.18, "change_pct": 1.43, "unit": "USD/bbl"},
    {"key": "brent", "name": "Brent Crude Oil", "price": 90.12, "change_pct": 1.10, "unit": "USD/bbl"},
    {"key": "natgas", "name": "Natural Gas", "price": 2.85, "change_pct": -0.75, "unit": "USD/MMBtu"},
    {"key": "copper", "name": "Copper", "price": 4.32, "change_pct": 0.28, "unit": "USD/lb"},
    {"key": "wheat", "name": "Wheat", "price": 612.25, "change_pct": 0.95, "unit": "USd/bu"},
    {"key": "corn", "name": "Corn", "price": 445.75, "change_pct": -0.32, "unit": "USd/bu"},
    {"key": "cotton", "name": "Cotton", "price": 71.40, "change_pct": 0.48, "unit": "USd/lb"},
]

# Maps our commodity keys to Twelve Data's own symbols. Grains
# (wheat/corn/cotton) aren't reliably available on Twelve Data's free
# tier, so those stay on development data even with an API key set.
COMMODITY_TWELVEDATA_SYMBOLS = {
    "gold": "XAU/USD", "silver": "XAG/USD", "platinum": "XPT/USD",
    "wti": "CL", "brent": "BZ", "natgas": "NG", "copper": "HG",
}


def get_commodities_live():
    """COMMODITIES_DEV, with any items we have live data for (via
    MARKET_DATA_API_KEY) overlaid on top — same pattern as
    get_multi_market_live()."""
    result = []

    for item in COMMODITIES_DEV:
        live = fetch_live_index(item["key"], COMMODITY_TWELVEDATA_SYMBOLS)

        if live and live.get("price") is not None:
            tone = "up" if (live.get("change_pct") or 0) >= 0 else "down"
            result.append({
                **item,
                "price": live["price"],
                "change_pct": live["change_pct"],
                "change_abs": live["change_abs"],
                "tone": tone,
                "source": live["source"],
            })
        else:
            result.append({**item, "tone": "up" if item["change_pct"] >= 0 else "down", "source": "Development value"})

    return result


# ---------------------------------------------------------
# Intraday series
# ---------------------------------------------------------

def normalize_timeseries(payload):
    """
    PSX can change response shape. This function accepts common
    list/dict variants and extracts numeric x/y points conservatively.
    """
    points = []

    def walk(obj):
        if isinstance(obj, list):
            # Direct numeric pair/triple
            if len(obj) >= 2 and all(isinstance(x, (int, float)) for x in obj[:2]):
                x = obj[0]
                y = obj[1]
                if y is not None:
                    points.append({"x": x, "y": y})
                return
            for child in obj:
                walk(child)

        elif isinstance(obj, dict):
            lower = {str(k).lower(): v for k, v in obj.items()}

            x = (
                lower.get("time")
                or lower.get("timestamp")
                or lower.get("date")
                or lower.get("x")
            )
            y = (
                lower.get("price")
                or lower.get("close")
                or lower.get("value")
                or lower.get("y")
            )

            if x is not None and y is not None and _number(y) is not None:
                points.append({"x": x, "y": _number(y)})
                return

            for child in obj.values():
                walk(child)

    walk(payload)

    # Deduplicate while retaining order.
    result = []
    seen = set()
    for point in points:
        key = (str(point["x"]), float(point["y"]))
        if key not in seen:
            seen.add(key)
            result.append(point)

    return result[-300:]


def get_intraday(symbol):
    url = PSX_INTRADAY_URL.format(symbol=symbol.upper())

    try:
        response = requests.get(url, headers=HEADERS, timeout=15)
        response.raise_for_status()
        payload = response.json()
        return normalize_timeseries(payload)
    except (requests.RequestException, ValueError):
        return []


# ---------------------------------------------------------
# Portfolio calculations + daily history
# ---------------------------------------------------------

def get_holding_recent_trend(symbol, limit=14):
    """Last N recorded closing values for a holding, for the small
    inline trend sparkline on the Portfolio table. Empty until at
    least 2 days have been recorded (same recording mechanism as
    holding_daily used by the per-holding calendar)."""
    conn = db()
    rows = conn.execute(
        """
        SELECT price FROM holding_daily
        WHERE symbol = ?
        ORDER BY day DESC
        LIMIT ?
        """,
        (symbol.upper(), limit)
    ).fetchall()
    conn.close()
    values = [r["price"] for r in rows]
    values.reverse()
    return values


def current_portfolio():
    conn = db()
    rows = conn.execute("SELECT * FROM holdings ORDER BY sort_order, symbol").fetchall()
    conn.close()

    holdings = []
    invested = 0.0
    value = 0.0

    for row in rows:
        quote = get_quote(row["symbol"])
        current = quote.get("price")

        if current is None:
            current = float(row["avg_cost"])

        inv = float(row["quantity"]) * float(row["avg_cost"])
        val = float(row["quantity"]) * float(current)
        pl = val - inv

        invested += inv
        value += val

        holdings.append({
            "symbol": row["symbol"],
            "company": quote.get("company", row["symbol"]),
            "sector": quote.get("sector", ""),
            "price": current,
            "quantity": row["quantity"],
            "avg_cost": row["avg_cost"],
            "invested": inv,
            "value": val,
            "pl": pl,
            "pl_pct": (pl / inv * 100) if inv else 0,
            "change_pct": quote.get("change_pct"),
            "acquired_date": row["acquired_date"],
            "recent_trend": get_holding_recent_trend(row["symbol"]),
        })

    pnl = value - invested
    pnl_pct = (pnl / invested * 100) if invested else 0

    return {
        "holdings": holdings,
        "invested": invested,
        "value": value,
        "pl": pnl,
        "pl_pct": pnl_pct,
    }


def save_today_snapshot(portfolio_data):
    today = date.today().isoformat()
    conn = db()

    conn.execute(
        """
        INSERT INTO portfolio_daily(day,invested,value,pnl,pnl_pct)
        VALUES(?,?,?,?,?)
        ON CONFLICT(day) DO UPDATE SET
            invested=excluded.invested,
            value=excluded.value,
            pnl=excluded.pnl,
            pnl_pct=excluded.pnl_pct
        """,
        (
            today,
            portfolio_data["invested"],
            portfolio_data["value"],
            portfolio_data["pl"],
            portfolio_data["pl_pct"],
        )
    )

    for h in portfolio_data["holdings"]:
        conn.execute(
            """
            INSERT INTO holding_daily(day,symbol,price,quantity,avg_cost,invested,value,pnl,pnl_pct)
            VALUES(?,?,?,?,?,?,?,?,?)
            ON CONFLICT(day,symbol) DO UPDATE SET
                price=excluded.price,
                quantity=excluded.quantity,
                avg_cost=excluded.avg_cost,
                invested=excluded.invested,
                value=excluded.value,
                pnl=excluded.pnl,
                pnl_pct=excluded.pnl_pct
            """,
            (
                today,
                h["symbol"],
                h["price"],
                h["quantity"],
                h["avg_cost"],
                h["invested"],
                h["value"],
                h["pl"],
                h["pl_pct"],
            )
        )

    conn.commit()
    conn.close()


def portfolio_history():
    conn = db()
    rows = conn.execute(
        """
        SELECT day,invested,value,pnl,pnl_pct
        FROM portfolio_daily
        ORDER BY day
        """
    ).fetchall()
    conn.close()

    history = []
    previous_pnl = None

    for row in rows:
        pnl = float(row["pnl"])
        daily_change = 0.0 if previous_pnl is None else pnl - previous_pnl

        history.append({
            "day": row["day"],
            "invested": row["invested"],
            "value": row["value"],
            "pnl": pnl,
            "pnl_pct": row["pnl_pct"],
            "daily_pnl_change": daily_change,
        })

        previous_pnl = pnl

    return history


def holding_history(symbol, acquired_date, avg_cost, quantity):
    """Day-by-day value/P&L for a single holding, from its acquisition
    date up to today.

    Real numbers come from holding_daily, recorded automatically each
    day the app is opened (same mechanism as the whole-portfolio
    calendar). Any gap between the acquisition date and the first real
    snapshot (e.g. if you add this feature after already owning the
    stock for a while) is filled with a straight-line ESTIMATE between
    the purchase price and the first real recorded price - it is
    clearly marked "estimated" and is not a real historical close.
    Wire in a licensed PSX historical-price feed to replace the
    estimate with exact numbers.
    """
    symbol = symbol.upper()
    conn = db()
    rows = conn.execute(
        """
        SELECT day, price, quantity, avg_cost, invested, value, pnl, pnl_pct
        FROM holding_daily
        WHERE symbol = ?
        ORDER BY day
        """,
        (symbol,)
    ).fetchall()
    conn.close()

    real = [dict(r) for r in rows]

    if not acquired_date:
        acquired_date = real[0]["day"] if real else date.today().isoformat()

    try:
        start = date.fromisoformat(acquired_date)
    except ValueError:
        start = date.today()

    today = date.today()

    if real:
        first_real_day = date.fromisoformat(real[0]["day"])
        first_real_value = float(real[0]["value"])
    else:
        first_real_day = today
        first_real_value = float(quantity) * float(avg_cost)

    start_value = float(quantity) * float(avg_cost)

    estimated = []
    gap_days = (first_real_day - start).days

    if gap_days > 0:
        for i in range(gap_days):
            day = start + timedelta(days=i)
            if day.weekday() >= 5:  # skip weekends (PSX closed)
                continue
            t = i / gap_days
            value = start_value + (first_real_value - start_value) * t
            invested = float(quantity) * float(avg_cost)
            pnl = value - invested

            estimated.append({
                "day": day.isoformat(),
                "price": (value / float(quantity)) if quantity else avg_cost,
                "quantity": quantity,
                "avg_cost": avg_cost,
                "invested": invested,
                "value": value,
                "pnl": pnl,
                "pnl_pct": (pnl / invested * 100) if invested else 0,
                "estimated": True,
            })

    combined = estimated + [dict(r, estimated=False) for r in real]
    combined.sort(key=lambda r: r["day"])

    history = []
    previous_pnl = None

    for row in combined:
        pnl = float(row["pnl"])
        daily_change = 0.0 if previous_pnl is None else pnl - previous_pnl

        history.append({
            **row,
            "daily_pnl_change": daily_change,
        })

        previous_pnl = pnl

    return history


# ---------------------------------------------------------
# Routes
# ---------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


@app.get("/api/symbols")
def symbols():
    try:
        items = fetch_psx_symbols()
        return jsonify({
            "count": len(items),
            "symbols": items,
            "updated_at": (
                _symbol_cache["time"].isoformat(timespec="seconds")
                if _symbol_cache["time"] else None
            )
        })
    except requests.RequestException as exc:
        return jsonify({"error": str(exc)}), 502


@app.post("/api/symbols/refresh")
def refresh_symbols():
    try:
        items = fetch_psx_symbols(force=True)
        return jsonify({"ok": True, "count": len(items)})
    except requests.RequestException as exc:
        return jsonify({"error": str(exc)}), 502


@app.get("/api/stock/<symbol>")
def stock_detail(symbol):
    quote = get_quote(symbol)
    quote["series"] = get_intraday(symbol)
    return jsonify(quote)


@app.get("/api/market")
def market():
    symbols = list(FALLBACK_QUOTES.keys())
    stocks = [get_quote(symbol) for symbol in symbols]

    return jsonify({
        "kse100": KSE100,
        "stocks": stocks,
        "advancers": sum(
            1 for stock in stocks
            if (stock.get("change_pct") or 0) > 0
        ),
        "decliners": sum(
            1 for stock in stocks
            if (stock.get("change_pct") or 0) < 0
        ),
    })


@app.get("/api/extras")
def extras():
    return jsonify({
        "sectors": SECTOR_PERFORMANCE,
        "macro": MACRO,
        "macro_signal": compute_macro_signal(MACRO),
        "announcements": ANNOUNCEMENTS,
        "breadth": MARKET_BREADTH,
        "fear_greed": FEAR_GREED,
        "indices": INDEX_CARDS,
        "global_sentiment": GLOBAL_SENTIMENT,
    })


@app.get("/api/market-detail/<key>")
def market_detail(key):
    item = next((m for m in MULTI_MARKET if m["key"] == key), None)
    if not item:
        return jsonify({"error": "Unknown market"}), 404
    detail = MULTI_MARKET_DETAIL.get(key, {})
    return jsonify({**item, **detail})


@app.get("/api/macro-detail/<key>")
def macro_detail(key):
    item = next((m for m in PAKISTAN_PROFILE if m["key"] == key), None)
    if not item:
        return jsonify({"error": "Unknown indicator"}), 404
    return jsonify(item)


@app.get("/api/fund-holders/<symbol>")
def fund_holders(symbol):
    match = next((r for r in TOP_STOCKS_THREE_WAYS["fund_holdings"] if r["symbol"] == symbol.upper()), None)
    if not match:
        return jsonify({
            "symbol": symbol.upper(),
            "available": False,
            "note": "Fund-holder detail is only tracked for the handful of stocks in Top Stocks, Three Ways — a full per-stock fund-holder list needs a licensed holdings feed.",
        })
    # Development: which specific funds, since MUFAP's holdings reports
    # don't expose a public per-stock breakdown — approximate with the
    # largest funds by AUM from the real MUFAP_FUND_DIRECTORY.
    top_funds = sorted(
        [f for f in MUFAP_FUND_DIRECTORY if f.get("aum_mn")],
        key=lambda f: f["aum_mn"], reverse=True
    )[:match["funds"]]
    return jsonify({
        "symbol": match["symbol"],
        "company": match["company"],
        "fund_count": match["funds"],
        "available": True,
        "funds": [{"name": f["name"], "amc": f["amc"], "category": f["category"]} for f in top_funds],
        "note": "Fund list is illustrative (largest real MUFAP funds by AUM) — exact per-stock holdings need a licensed data feed.",
    })


@app.get("/api/market360")
def market360():
    """Everything the expanded Markets page needs, beyond what
    /api/market and /api/extras already cover. See the development-data
    block near the top of this file for the underlying values."""
    trending_period = request.args.get("trending_period", "1W")
    return jsonify({
        "risk_sentiment": RISK_SENTIMENT,
        "multi_market": get_multi_market_live(),
        "cross_asset_signals": CROSS_ASSET_SIGNALS,
        "cross_asset_highlights": CROSS_ASSET_HIGHLIGHTS,
        "trending_stocks": get_trending_stocks(trending_period),
        "trending_periods": list(TRENDING_PERIOD_LABELS.keys()),
        "week52": WEEK52,
        "fund_flows": FUND_FLOWS,
        "insider_activity": INSIDER_ACTIVITY,
        "sentiment_history": SENTIMENT_HISTORY,
        "non_equity_sentiment": NON_EQUITY_SENTIMENT,
        "breadth_pulse": BREADTH_PULSE,
        "top_stocks_three_ways": TOP_STOCKS_THREE_WAYS,
        "levels_to_play": LEVELS_TO_PLAY,
        "seasonality": SEASONALITY,
        "pakistan_profile": PAKISTAN_PROFILE,
        "upcoming_payouts": UPCOMING_PAYOUTS,
        "calendar_events": CALENDAR_EVENTS,
        "live_data_enabled": bool(MARKET_DATA_API_KEY),
    })


@app.get("/api/stocks/live")
def stocks_live():
    try:
        bulk = get_bulk_quotes()
        progress = get_recording_progress()

        with _technicals_cache_lock:
            cache_snapshot = dict(_technicals_cache)

        fund_holders = {
            row["symbol"]: row["funds"] for row in TOP_STOCKS_THREE_WAYS["fund_holdings"]
        }

        items = []
        for q in bulk["items"]:
            t = cache_snapshot.get(q.get("symbol"))
            items.append({
                **q,
                "rsi14": t.get("rsi14") if t else None,
                "above_sma50": t.get("above_sma50") if t else None,
                "above_sma200": t.get("above_sma200") if t else None,
                "golden_death_cross": t.get("golden_death_cross") if t else None,
                "data_days": t.get("data_days") if t else 0,
                "funds_holding": fund_holders.get(q.get("symbol")),
            })

        return jsonify({
            "items": items,
            "updated_at": bulk["updated_at"],
            "recording_progress": progress,
            "fund_holdings_note": (
                "Fund-holder counts are only tracked for a handful of top stocks "
                "(from the Markets page's 'Top Stocks, Three Ways' — see "
                "TOP_STOCKS_THREE_WAYS in app.py). A full per-stock fund-holder "
                "list for the whole PSX directory needs a licensed holdings feed."
            ),
        })
    except Exception as exc:
        return jsonify({"items": [], "updated_at": None, "error": str(exc)}), 200


@app.post("/api/stocks/live/refresh")
def stocks_live_refresh():
    threading.Thread(target=refresh_bulk_quotes, daemon=True).start()
    return jsonify({"ok": True, "message": "Refresh started in the background."})


@app.get("/api/stock/<symbol>/fundamentals")
def stock_fundamentals(symbol):
    return jsonify(get_fundamentals(symbol))


def get_recording_progress():
    """How many distinct trading days of stock_price_history exist so
    far, since the day this feature was turned on. Used to show real
    progress toward each technical indicator's activation threshold —
    never a fabricated 'it's ready' claim."""
    conn = db()
    row = conn.execute("SELECT COUNT(DISTINCT day) AS n FROM stock_price_history").fetchone()
    first = conn.execute("SELECT MIN(day) AS d FROM stock_price_history").fetchone()
    conn.close()
    return {"days_recorded": row["n"] if row else 0, "started_on": first["d"] if first else None}


def catalog_with_progress():
    """FILTER_CATALOG, with each history-backed technical item's
    'reason' replaced by live progress once it's still short of its
    activation threshold — e.g. '12/50 trading days recorded (24%)'.
    Items with enough history stay simply marked available."""
    progress = get_recording_progress()
    days = progress["days_recorded"]

    sections = []
    for section in FILTER_CATALOG:
        items = []
        for item in section["items"]:
            item = dict(item)
            key = item.get("filter_key")
            if item["available"] and key in TECHNICAL_REQUIREMENTS:
                needed = TECHNICAL_REQUIREMENTS[key]
                if days < needed:
                    pct = round(days / needed * 100) if needed else 100
                    item["activating"] = True
                    item["reason"] = (
                        f"Activating: {days}/{needed} trading days recorded ({pct}%). "
                        f"Recording started {progress['started_on'] or 'today'}."
                    )
            items.append(item)
        sections.append({**section, "items": items})

    return sections, progress


@app.get("/api/screener/catalog")
def screener_catalog():
    sections, progress = catalog_with_progress()
    return jsonify({"sections": sections, "recording_progress": progress})


TECHNICAL_CRITERIA_KEYS = {
    "rsi_min", "rsi_max", "above_sma20", "above_sma50", "above_sma200",
    "golden_cross", "death_cross", "macd_bullish", "rsi_oversold", "rsi_overbought",
}


@app.post("/api/screener/run")
def screener_run():
    """Fast, cache-first screener.

    Simple filters run against the in-memory bulk quote snapshot. Technical
    filters use the background technical cache; missing symbols are computed
    in parallel. Repeated identical runs are cached briefly.
    """
    import concurrent.futures

    criteria = request.get_json(silent=True) or {}
    cache_key = json.dumps(criteria, sort_keys=True, separators=(",", ":"))
    now = time.time()

    with _screener_cache_lock:
        hit = _screener_result_cache.get(cache_key)
        if hit and now - hit["time"] < SCREENER_CACHE_SECONDS:
            return jsonify(hit["data"])

    bulk = get_bulk_quotes()
    items = bulk["items"]

    if TECHNICAL_CRITERIA_KEYS & set(criteria.keys()):
        symbols = [q.get("symbol") for q in items if q.get("symbol")]
        with _technicals_cache_lock:
            missing = [s for s in symbols if s.upper() not in _technicals_cache]

        if missing:
            def one(symbol):
                try:
                    return symbol.upper(), compute_technicals(symbol)
                except Exception:
                    return symbol.upper(), None

            with concurrent.futures.ThreadPoolExecutor(max_workers=min(12, max(1, len(missing)))) as pool:
                computed = [pair for pair in pool.map(one, missing) if pair[1] is not None]

            with _technicals_cache_lock:
                for symbol, value in computed:
                    _technicals_cache[symbol] = value

        with _technicals_cache_lock:
            snapshot = dict(_technicals_cache)

        items = [
            {**q, **{k: v for k, v in snapshot.get(q.get("symbol", "").upper(), {}).items()
                     if k != "symbol"}}
            for q in items
        ]

    results = [q for q in items if stock_matches_filters(q, criteria)]

    sort_key = criteria.get("sort", "change_pct")
    reverse = criteria.get("sort_dir", "desc") != "asc"
    results.sort(key=lambda q: (q.get(sort_key) is None, q.get(sort_key) or 0), reverse=reverse)

    data = {
        "count": len(results),
        "scanned": len(items),
        "updated_at": bulk["updated_at"],
        "warming_up": bulk["updated_at"] is None,
        "results": results[:200],
    }

    with _screener_cache_lock:
        _screener_result_cache[cache_key] = {"time": now, "data": data}

    return jsonify(data)


@app.get("/api/mutual-funds")
def mutual_funds():
    funds, source = fetch_mufap_funds()
    trends = get_fund_trends([f["name"] for f in funds])
    funds = [{**f, "trend": trends.get(f["name"], [])} for f in funds]
    return jsonify({"funds": funds, "source": source})


@app.post("/api/mutual-funds/refresh")
def mutual_funds_refresh():
    funds, source = fetch_mufap_funds(force=True)
    trends = get_fund_trends([f["name"] for f in funds])
    funds = [{**f, "trend": trends.get(f["name"], [])} for f in funds]
    return jsonify({"funds": funds, "source": source})


@app.get("/api/crypto/live")
def crypto_live():
    coins, source = fetch_crypto_live()
    return jsonify({"coins": coins, "source": source, "count": len(coins)})


@app.get("/api/crypto/sentiment")
def crypto_sentiment():
    return jsonify(fetch_crypto_sentiment())


@app.post("/api/crypto/live/refresh")
def crypto_live_refresh():
    coins, source = fetch_crypto_live(force=True)
    return jsonify({"coins": coins, "source": source, "count": len(coins)})


@app.get("/api/forex/live")
def forex_live():
    rates, source, rate_date = fetch_forex_live()
    return jsonify({"rates": rates, "source": source, "date": rate_date, "base": "USD"})


@app.post("/api/forex/live/refresh")
def forex_live_refresh():
    rates, source, rate_date = fetch_forex_live(force=True)
    return jsonify({"rates": rates, "source": source, "date": rate_date, "base": "USD"})


@app.get("/api/commodities/live")
def commodities_live():
    return jsonify({
        "commodities": get_commodities_live(),
        "live_data_enabled": bool(MARKET_DATA_API_KEY),
    })


MAJOR_FOREX_PAIRS = ["EUR", "GBP", "JPY", "AUD", "PKR"]


@app.get("/api/dashboard-highlights")
def dashboard_highlights():
    """Compact bundle for the Dashboard's Major Forex / Top Mutual
    Funds / Commodities strip, so the frontend can fetch it in one
    call instead of three."""
    rates, forex_source, forex_date = fetch_forex_live()
    major_forex = [
        {"code": code, "rate": rates.get(code)}
        for code in MAJOR_FOREX_PAIRS
        if rates.get(code) is not None
    ]

    funds, funds_source = fetch_mufap_funds()
    top_funds = sorted(
        [f for f in funds if f.get("aum_mn") is not None],
        key=lambda f: f["aum_mn"],
        reverse=True,
    )[:5]

    commodities = get_commodities_live()[:6]

    return jsonify({
        "major_forex": major_forex,
        "forex_source": forex_source,
        "forex_date": forex_date,
        "top_funds": top_funds,
        "funds_source": funds_source,
        "commodities": commodities,
    })


@app.get("/api/journal")
def journal():
    return jsonify({
        "articles": JOURNAL_ARTICLES,
        "podcasts": JOURNAL_PODCASTS,
    })


@app.get("/api/tools")
def tools():
    funds, _source = fetch_mufap_funds()
    return jsonify({
        "catalog": TOOL_CATALOG,
        "funds": funds,
    })


@app.get("/api/compare")
def compare():
    symbols = [s.strip().upper() for s in request.args.get("symbols", "").split(",") if s.strip()]
    return jsonify([get_quote(sym) for sym in symbols[:4]])


@app.get("/api/portfolio")
def portfolio():
    data = current_portfolio()
    save_today_snapshot(data)
    data["history"] = portfolio_history()
    return jsonify(data)


@app.get("/api/portfolio/history")
def portfolio_history_route():
    period = request.args.get("period", "all")
    history = portfolio_history()

    days_map = {"1W": 7, "2W": 14, "3W": 21, "1M": 30, "3M": 90, "6M": 180, "1Y": 365, "1D": 1}
    if period in days_map:
        cutoff = date.today() - timedelta(days=days_map[period])
        history = [h for h in history if date.fromisoformat(h["day"]) >= cutoff]

    return jsonify({
        "history": history,
        "period": period,
    })


@app.post("/api/portfolio/snapshot")
def portfolio_snapshot():
    data = current_portfolio()
    save_today_snapshot(data)
    return jsonify({
        "ok": True,
        "history": portfolio_history()
    })


@app.get("/api/portfolio/holding/<symbol>")
def portfolio_holding(symbol):
    conn = db()
    row = conn.execute(
        "SELECT * FROM holdings WHERE symbol = ?", (symbol.upper(),)
    ).fetchone()
    conn.close()

    if not row:
        return jsonify({"error": "Holding not found"}), 404

    quote = get_quote(symbol)

    return jsonify({
        "symbol": row["symbol"],
        "company": quote.get("company", row["symbol"]),
        "acquired_date": row["acquired_date"],
        "avg_cost": row["avg_cost"],
        "quantity": row["quantity"],
        "current_price": quote.get("price"),
        "history": holding_history(
            row["symbol"], row["acquired_date"], row["avg_cost"], row["quantity"]
        ),
    })


@app.get("/api/world-clock")
def world_clock():
    return jsonify({
        "markets": WORLD_MARKETS,
        "forex_sessions": FOREX_SESSIONS,
    })


@app.get("/api/premarket-signal")
def premarket_signal_route():
    return jsonify(compute_premarket_signal())


@app.get("/api/search-all")
def search_all():
    """Universal search across every asset class Yalvon360 tracks —
    stocks, crypto, forex, mutual funds — for the Watchlist page's
    type-ahead. Reuses the same cached data each asset page already
    uses, so this stays fast and doesn't trigger fresh scrapes."""
    q = request.args.get("q", "").strip().upper()
    if not q or len(q) < 1:
        return jsonify({"results": []})

    results = []

    try:
        live_quotes = get_bulk_quotes()["items"]
        live_by_symbol = {x["symbol"]: x for x in live_quotes}
        try:
            symbol_rows = fetch_psx_symbols()
        except requests.RequestException:
            symbol_rows = [
                {"symbol": sym, "company": data["company"], "sector": data.get("sector", "")}
                for sym, data in FALLBACK_QUOTES.items()
            ]
        for row in symbol_rows:
            if q in row["symbol"].upper() or q in row["company"].upper():
                match = live_by_symbol.get(row["symbol"])
                results.append({
                    "symbol": row["symbol"], "name": row["company"], "asset_type": "stock",
                    "price": match.get("price") if match else None,
                    "change_pct": match.get("change_pct") if match else None,
                })
    except Exception:
        pass

    try:
        coins, _ = fetch_crypto_live()
        for c in coins:
            if q in c["symbol"].upper() or q in c["name"].upper():
                results.append({
                    "symbol": c["symbol"], "name": c["name"], "asset_type": "crypto",
                    "price": c["current_price"], "change_pct": c["price_change_percentage_24h"],
                })
    except Exception:
        pass

    try:
        rates, _, _ = fetch_forex_live()
        for code, rate in rates.items():
            if q in code.upper():
                results.append({
                    "symbol": code, "name": f"USD/{code}", "asset_type": "forex",
                    "price": rate, "change_pct": None,
                })
    except Exception:
        pass

    try:
        funds, _ = fetch_mufap_funds()
        for f in funds:
            if q in f["name"].upper():
                results.append({
                    "symbol": f["name"], "name": f["name"], "asset_type": "fund",
                    "price": f.get("nav"), "change_pct": f.get("ytd"),
                })
    except Exception:
        pass

    # Cap each asset class so one huge category doesn't crowd out others.
    by_type = {}
    capped = []
    for r in results:
        by_type.setdefault(r["asset_type"], 0)
        if by_type[r["asset_type"]] < 8:
            capped.append(r)
            by_type[r["asset_type"]] += 1

    return jsonify({"results": capped[:30], "query": q})


@app.get("/api/watchlist")
def watchlist():
    conn = db()
    rows = conn.execute("SELECT * FROM watchlist ORDER BY sort_order, symbol").fetchall()
    conn.close()

    # Build live lookup maps once, instead of one live call per row.
    crypto_coins, _ = fetch_crypto_live()
    crypto_by_symbol = {c["symbol"]: c for c in crypto_coins}
    forex_rates, _, _ = fetch_forex_live()
    fund_list, _ = fetch_mufap_funds()
    funds_by_name = {f["name"]: f for f in fund_list}

    results = []
    for row in rows:
        asset_type = row["asset_type"] or "stock"
        symbol = row["symbol"]

        if asset_type == "crypto" and symbol in crypto_by_symbol:
            c = crypto_by_symbol[symbol]
            results.append({
                "symbol": symbol, "asset_type": "crypto", "name": c["name"],
                "price": c["current_price"], "change_pct": c["price_change_percentage_24h"],
            })
        elif asset_type == "forex" and symbol in forex_rates:
            results.append({
                "symbol": symbol, "asset_type": "forex", "name": f"USD/{symbol}",
                "price": forex_rates[symbol], "change_pct": None,
            })
        elif asset_type == "fund" and symbol in funds_by_name:
            f = funds_by_name[symbol]
            results.append({
                "symbol": symbol, "asset_type": "fund", "name": f["name"],
                "price": f.get("nav"), "change_pct": f.get("ytd"),
            })
        elif asset_type == "stock":
            q = get_quote(symbol)
            results.append({
                "symbol": symbol, "asset_type": "stock", "name": q.get("company", symbol),
                "price": q.get("price"), "change_pct": q.get("change_pct"),
            })
        else:
            # Live source didn't have it this time (e.g. crypto cache
            # miss) — fall back to the snapshot taken when it was added.
            results.append({
                "symbol": symbol, "asset_type": asset_type,
                "name": row["display_name"] or symbol,
                "price": row["last_price"], "change_pct": row["last_change_pct"],
            })

    return jsonify(results)


@app.post("/api/watchlist")
def watchlist_add():
    data = request.get_json(silent=True) or {}
    raw_symbol = (data.get("symbol") or "").strip()
    asset_type = (data.get("asset_type") or "stock").strip().lower()
    if asset_type not in ("stock", "crypto", "forex", "fund"):
        asset_type = "stock"

    # Fund names are case-sensitive free text (matched against
    # MUFAP_FUND_DIRECTORY / live NAV data by exact name) — only
    # tickers (stock/crypto/forex) get uppercased.
    symbol = raw_symbol if asset_type == "fund" else raw_symbol.upper()
    display_name = data.get("display_name")
    last_price = data.get("price")
    last_change_pct = data.get("change_pct")

    if not symbol:
        return jsonify({"error": "Symbol is required"}), 400

    conn = db()
    exists = conn.execute("SELECT id FROM watchlist WHERE symbol = ? COLLATE NOCASE", (symbol,)).fetchone()

    if not exists:
        max_order = conn.execute("SELECT MAX(sort_order) AS m FROM watchlist").fetchone()["m"] or 0
        conn.execute(
            """
            INSERT INTO watchlist(symbol, sort_order, asset_type, display_name, last_price, last_change_pct)
            VALUES(?,?,?,?,?,?)
            """,
            (symbol, max_order + 1, asset_type, display_name, last_price, last_change_pct)
        )
        conn.commit()

    conn.close()
    return jsonify({"ok": True, "symbol": symbol})


@app.delete("/api/watchlist/<symbol>")
def watchlist_remove(symbol):
    conn = db()
    # COLLATE NOCASE: fund names are mixed-case free text while
    # stock/crypto/forex symbols are conventionally uppercase — a
    # case-insensitive match handles both without guessing.
    conn.execute("DELETE FROM watchlist WHERE symbol = ? COLLATE NOCASE", (symbol,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.post("/api/watchlist/reorder")
def watchlist_reorder():
    data = request.get_json(silent=True) or {}
    symbols = data.get("symbols") or []

    conn = db()
    for i, symbol in enumerate(symbols):
        conn.execute(
            "UPDATE watchlist SET sort_order=? WHERE symbol = ? COLLATE NOCASE",
            (i, symbol)
        )
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.post("/api/portfolio/reorder")
def portfolio_reorder():
    data = request.get_json(silent=True) or {}
    symbols = data.get("symbols") or []

    conn = db()
    for i, symbol in enumerate(symbols):
        conn.execute(
            "UPDATE holdings SET sort_order=? WHERE symbol=?",
            (i, symbol.upper())
        )
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.get("/api/transactions")
def transactions():
    conn = db()
    rows = conn.execute(
        "SELECT * FROM transactions ORDER BY id DESC LIMIT 100"
    ).fetchall()
    conn.close()

    return jsonify([dict(row) for row in rows])


@app.post("/api/transactions")
def add_transaction():
    data = request.get_json(force=True)

    symbol = data.get("symbol", "").upper().strip()
    tx_type = data.get("type", "BUY").upper()
    quantity = float(data.get("quantity", 0))
    price = float(data.get("price", 0))
    tx_date = data.get("date") or date.today().isoformat()

    try:
        valid = {item["symbol"] for item in fetch_psx_symbols()}
    except requests.RequestException:
        valid = set(FALLBACK_QUOTES.keys())

    if symbol not in valid:
        return jsonify({"error": "Symbol not found in PSX directory"}), 400

    if tx_type not in {"BUY", "SELL"}:
        return jsonify({"error": "Type must be BUY or SELL"}), 400

    if quantity <= 0 or price <= 0:
        return jsonify({"error": "Quantity and price must be positive"}), 400

    conn = db()

    now_stamp = datetime.now().strftime("%Y-%m-%d %H:%M")

    conn.execute(
        """
        INSERT INTO transactions(date,symbol,type,quantity,price)
        VALUES(?,?,?,?,?)
        """,
        (now_stamp, symbol, tx_type, quantity, price)
    )

    existing = conn.execute(
        """
        SELECT quantity,avg_cost,acquired_date
        FROM holdings
        WHERE symbol=?
        """,
        (symbol,)
    ).fetchone()

    if tx_type == "BUY":
        if existing:
            old_q = float(existing["quantity"])
            old_avg = float(existing["avg_cost"])
            new_q = old_q + quantity
            new_avg = ((old_q * old_avg) + (quantity * price)) / new_q
            acquired = existing["acquired_date"] or tx_date
            acquired = min(acquired, tx_date)

            conn.execute(
                """
                UPDATE holdings
                SET quantity=?,avg_cost=?,acquired_date=?
                WHERE symbol=?
                """,
                (new_q, new_avg, acquired, symbol)
            )
        else:
            conn.execute(
                """
                INSERT INTO holdings(symbol,quantity,avg_cost,acquired_date)
                VALUES(?,?,?,?)
                """,
                (symbol, quantity, price, tx_date)
            )

    elif existing:
        new_q = float(existing["quantity"]) - quantity

        if new_q <= 0:
            conn.execute("DELETE FROM holdings WHERE symbol=?", (symbol,))
        else:
            conn.execute(
                "UPDATE holdings SET quantity=? WHERE symbol=?",
                (new_q, symbol)
            )

    conn.commit()
    conn.close()

    return jsonify({"ok": True})


@app.delete("/api/portfolio/holding/<symbol>")
def delete_holding(symbol):
    """Remove a holding entirely from the portfolio: the position
    itself, its transaction history, and any recorded daily snapshots
    for it. This is a destructive, irreversible action - the frontend
    confirms with the person before calling this."""
    symbol = symbol.upper().strip()
    conn = db()

    existing = conn.execute(
        "SELECT symbol FROM holdings WHERE symbol=?", (symbol,)
    ).fetchone()

    if not existing:
        conn.close()
        return jsonify({"error": "Holding not found"}), 404

    conn.execute("DELETE FROM holdings WHERE symbol=?", (symbol,))
    conn.execute("DELETE FROM transactions WHERE symbol=?", (symbol,))
    conn.execute("DELETE FROM holding_daily WHERE symbol=?", (symbol,))
    conn.commit()
    conn.close()

    data = current_portfolio()
    save_today_snapshot(data)

    return jsonify({"ok": True, "portfolio": data})


@app.get("/healthz")
def healthz():
    with _bulk_quote_lock:
        count = len(_bulk_quote_cache["items"])
        updated = _bulk_quote_cache["time"].isoformat(timespec="seconds") if _bulk_quote_cache["time"] else None
        warming = _bulk_quote_cache["in_progress"]
    return jsonify({"ok": True, "stocks_cached": count, "updated_at": updated, "warming_up": warming})


@app.get("/sw.js")
def service_worker():
    return app.send_static_file("sw.js")


# =====================================================================
# INTRADAY TECHNICALS — Crypto & Forex (merged in from the PSX Toolkit)
# =====================================================================
# These two scanners are the one genuinely new capability the PSX
# Toolkit project had that this app didn't: RSI(14) + bullish/bearish
# divergence + trend-structure classification on live intraday bars for
# major forex pairs (plus gold/silver) and the top ~15 cryptocurrencies,
# at 30m / 1h / 4h. It reuses the exact same math (core.compute_rsi,
# core.check_bullish_divergence, core.check_bearish_divergence,
# core.classify_structure) that already existed in psx_screener.py.
#
# Data source: yfinance (free, no API key). A full scan loops over every
# symbol x timeframe combination, which is too slow for a single HTTP
# request, so it runs in a background thread; the browser polls a job id
# for progress and then the final result, then that result is cached in
# memory so re-opening the tab shows the last scan instantly.

FOREX_TECH_SYMBOLS = [
    {"yf": "EURUSD=X", "display": "EUR/USD"},
    {"yf": "GBPUSD=X", "display": "GBP/USD"},
    {"yf": "USDJPY=X", "display": "USD/JPY"},
    {"yf": "USDCHF=X", "display": "USD/CHF"},
    {"yf": "AUDUSD=X", "display": "AUD/USD"},
    {"yf": "USDCAD=X", "display": "USD/CAD"},
    {"yf": "NZDUSD=X", "display": "NZD/USD"},
    {"yf": "EURGBP=X", "display": "EUR/GBP"},
    {"yf": "EURJPY=X", "display": "EUR/JPY"},
    {"yf": "GBPJPY=X", "display": "GBP/JPY"},
    {"yf": "GC=F", "display": "Gold (Futures)"},
    {"yf": "SI=F", "display": "Silver (Futures)"},
]

CRYPTO_TECH_SYMBOLS = [
    {"yf": "BTC-USD", "display": "Bitcoin (BTC)"},
    {"yf": "ETH-USD", "display": "Ethereum (ETH)"},
    {"yf": "BNB-USD", "display": "BNB"},
    {"yf": "SOL-USD", "display": "Solana (SOL)"},
    {"yf": "XRP-USD", "display": "XRP"},
    {"yf": "ADA-USD", "display": "Cardano (ADA)"},
    {"yf": "DOGE-USD", "display": "Dogecoin (DOGE)"},
    {"yf": "AVAX-USD", "display": "Avalanche (AVAX)"},
    {"yf": "DOT-USD", "display": "Polkadot (DOT)"},
    {"yf": "LINK-USD", "display": "Chainlink (LINK)"},
    {"yf": "LTC-USD", "display": "Litecoin (LTC)"},
    {"yf": "TRX-USD", "display": "TRON (TRX)"},
    {"yf": "SHIB-USD", "display": "Shiba Inu (SHIB)"},
    {"yf": "UNI-USD", "display": "Uniswap (UNI)"},
    {"yf": "ATOM-USD", "display": "Cosmos (ATOM)"},
]

INTRADAY_DIVERGENCE_LOOKBACK = 60
INTRADAY_STRUCTURE_LOOKBACK = 80
INTRADAY_SWING_ORDER = 4


def _clean_for_json(obj):
    """Recursively converts numpy/pandas scalar & date types into plain
    JSON-safe Python values, and turns NaN/Infinity into null (a bare
    NaN is not valid JSON and browsers reject it)."""
    if isinstance(obj, dict):
        return {k: _clean_for_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean_for_json(v) for v in obj]
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.floating):
        f = float(obj)
        return None if (np.isnan(f) or np.isinf(f)) else f
    if isinstance(obj, float) and (np.isnan(obj) or np.isinf(obj)):
        return None
    if isinstance(obj, (pd.Timestamp, np.datetime64)):
        return pd.Timestamp(obj).isoformat()
    if isinstance(obj, (dt.date, dt.datetime)):
        return obj.isoformat()
    if hasattr(obj, "item") and not isinstance(obj, (str, bytes)):
        try:
            return _clean_for_json(obj.item())
        except Exception:
            return obj
    return obj


def safe_jsonify(data):
    return jsonify(_clean_for_json(data))


def fetch_yf_ohlc(symbol, interval="30m", period="60d", max_retries=3):
    """Fetches OHLC bars via yfinance and normalizes the result to a
    DataFrame with columns: date, open, high, low, close."""
    import yfinance as yf

    last_exc = None
    for attempt in range(max_retries):
        try:
            df = yf.download(symbol, interval=interval, period=period,
                              progress=False, auto_adjust=True)
            break
        except Exception as e:
            last_exc = e
            if attempt < max_retries - 1:
                time.sleep(1.5 * (2 ** attempt))
                continue
            raise
    else:
        raise last_exc

    if df is None or df.empty:
        raise RuntimeError(f"No data returned for {symbol} at interval={interval}.")

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]

    df = df.reset_index()
    first_col = df.columns[0]
    df = df.rename(columns={
        first_col: "date", "Open": "open", "High": "high", "Low": "low", "Close": "close",
    })

    missing = [c for c in ("date", "open", "high", "low", "close") if c not in df.columns]
    if missing:
        raise RuntimeError(f"Unexpected data shape from yfinance for {symbol} - missing columns {missing}.")

    return df[["date", "open", "high", "low", "close"]]


def resample_ohlc(df, rule):
    d = df.set_index("date")
    out = d.resample(rule).agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    return out.reset_index()


def analyze_intraday_symbol(df):
    if df is None or len(df) < INTRADAY_STRUCTURE_LOOKBACK:
        return {"error": f"Not enough bars ({0 if df is None else len(df)}) for analysis."}

    df = df.sort_values("date").reset_index(drop=True)
    df["rsi"] = core.compute_rsi(df["close"], core.RSI_PERIOD)

    bullish = core.check_bullish_divergence(df, INTRADAY_DIVERGENCE_LOOKBACK, INTRADAY_SWING_ORDER)
    bearish = core.check_bearish_divergence(df, INTRADAY_DIVERGENCE_LOOKBACK, INTRADAY_SWING_ORDER)
    structure = core.classify_structure(df, INTRADAY_STRUCTURE_LOOKBACK, INTRADAY_SWING_ORDER)

    return {
        "error": None,
        "latest_close": round(float(df["close"].iloc[-1]), 5),
        "latest_rsi": round(float(df["rsi"].iloc[-1]), 1),
        "latest_bar_time": df["date"].iloc[-1].isoformat() if hasattr(df["date"].iloc[-1], "isoformat") else str(df["date"].iloc[-1]),
        "structure": structure,
        "bullish_divergence": bullish,
        "bearish_divergence": bearish,
    }


def run_intraday_technical_scan(symbol_list, timeframes, progress_cb=None):
    """timeframes: list of (label, yf_interval, yf_period, resample_rule_or_None)."""
    results = {label: [] for label, *_ in timeframes}
    total = len(symbol_list) * len(timeframes)
    done = 0

    for sym in symbol_list:
        for label, interval, period, resample_rule in timeframes:
            try:
                df = fetch_yf_ohlc(sym["yf"], interval=interval, period=period)
                if resample_rule:
                    df = resample_ohlc(df, resample_rule)
                analysis = analyze_intraday_symbol(df)
            except Exception as e:
                analysis = {"error": str(e)}

            row = {"symbol": sym["yf"], "display": sym["display"]}
            row.update(analysis)
            results[label].append(row)

            done += 1
            if progress_cb:
                progress_cb(done, total, f"{sym['display']} ({label})")

    return results


_tech_jobs = {}
_tech_jobs_lock = threading.Lock()
_tech_scan_cache = {}  # name -> {"data": ..., "saved_at": iso string}
_tech_scan_cache_lock = threading.Lock()


def _new_tech_job():
    job_id = str(uuid.uuid4())
    with _tech_jobs_lock:
        _tech_jobs[job_id] = {"status": "running", "progress": {"done": 0, "total": 0, "symbol": ""},
                               "result": None, "error": None}
    return job_id


def _update_tech_job(job_id, **fields):
    with _tech_jobs_lock:
        if job_id in _tech_jobs:
            _tech_jobs[job_id].update(fields)


def _get_tech_job(job_id):
    with _tech_jobs_lock:
        job = _tech_jobs.get(job_id)
        return dict(job) if job else None


def _save_tech_cache(name, data):
    with _tech_scan_cache_lock:
        _tech_scan_cache[name] = {"data": data, "saved_at": datetime.utcnow().isoformat() + "Z"}


def _load_tech_cache(name):
    with _tech_scan_cache_lock:
        return _tech_scan_cache.get(name)


def _run_tech_job_in_background(job_id, cache_name, symbols, timeframes):
    def worker():
        try:
            def progress_cb(d, t, label):
                _update_tech_job(job_id, progress={"done": d, "total": t, "symbol": label})
            result = run_intraday_technical_scan(symbols, timeframes, progress_cb=progress_cb)
            _save_tech_cache(cache_name, result)
            _update_tech_job(job_id, status="done", result=result)
        except Exception as e:
            _update_tech_job(job_id, status="error", error=str(e))
    threading.Thread(target=worker, daemon=True).start()


def _technicals_guard():
    if not _TECHNICALS_AVAILABLE:
        return safe_jsonify({"ok": False, "error": "numpy/pandas/yfinance are not installed on the server. "
                                                     "Run: pip install -r requirements.txt"}), 500
    return None


@app.get("/api/forextech/scan/start")
def api_forextech_scan_start():
    guard = _technicals_guard()
    if guard:
        return guard
    job_id = _new_tech_job()
    timeframes = [("30m", "30m", "60d", None), ("1h", "60m", "60d", None)]
    _run_tech_job_in_background(job_id, "forextech", FOREX_TECH_SYMBOLS, timeframes)
    return safe_jsonify({"ok": True, "job_id": job_id})


@app.get("/api/forextech/scan/status/<job_id>")
def api_forextech_scan_status(job_id):
    job = _get_tech_job(job_id)
    if job is None:
        return safe_jsonify({"ok": False, "error": "Unknown job id (server may have restarted)."}), 404
    return safe_jsonify({"ok": True, **job})


@app.get("/api/forextech/scan/cached")
def api_forextech_scan_cached():
    cached = _load_tech_cache("forextech")
    if cached is None:
        return safe_jsonify({"ok": True, "found": False})
    return safe_jsonify({"ok": True, "found": True, "result": cached["data"], "saved_at": cached["saved_at"]})


@app.get("/api/cryptotech/scan/start")
def api_cryptotech_scan_start():
    guard = _technicals_guard()
    if guard:
        return guard
    job_id = _new_tech_job()
    timeframes = [
        ("30m", "30m", "60d", None),
        ("1h", "60m", "60d", None),
        ("4h", "60m", "60d", "4h"),
    ]
    _run_tech_job_in_background(job_id, "cryptotech", CRYPTO_TECH_SYMBOLS, timeframes)
    return safe_jsonify({"ok": True, "job_id": job_id})


@app.get("/api/cryptotech/scan/status/<job_id>")
def api_cryptotech_scan_status(job_id):
    job = _get_tech_job(job_id)
    if job is None:
        return safe_jsonify({"ok": False, "error": "Unknown job id (server may have restarted)."}), 404
    return safe_jsonify({"ok": True, **job})


@app.get("/api/cryptotech/scan/cached")
def api_cryptotech_scan_cached():
    cached = _load_tech_cache("cryptotech")
    if cached is None:
        return safe_jsonify({"ok": True, "found": False})
    return safe_jsonify({"ok": True, "found": True, "result": cached["data"], "saved_at": cached["saved_at"]})


# =====================================================================
# PSX DIVERGENCE SCREENER — 52-week low + RSI divergence, market-wide
# (merged in from the PSX Toolkit's original psx_screener.py / main())
# =====================================================================
# This is PSX Toolkit's own signature screen, distinct from the
# filter-based "Screener" tab above: it walks every PSX-listed symbol's
# ~1 year of daily price history (via the free `psxdata` library),
# flags stocks near their 52-week low, and checks every stock market-wide
# for bullish/bearish RSI divergence and trend structure. ~700+ symbols
# with a polite delay between requests takes several minutes, so it runs
# as a background job exactly like the Forex/Crypto Technicals scanners,
# with progress polling and a cached "last run" result.

PSX_DIVERGENCE_NEAR_LOW_PCT = getattr(core, "NEAR_LOW_PCT", 3.0)
PSX_DIVERGENCE_LOOKBACK_DAYS = getattr(core, "DIVERGENCE_LOOKBACK_DAYS", 90)
PSX_DIVERGENCE_SWING_ORDER = getattr(core, "SWING_ORDER", 8)
PSX_STRUCTURE_LOOKBACK_DAYS = getattr(core, "STRUCTURE_LOOKBACK_DAYS", 150)
PSX_STRUCTURE_SWING_ORDER = getattr(core, "STRUCTURE_SWING_ORDER", 8)
PSX_DIVERGENCE_HISTORY_DAYS = getattr(core, "HISTORY_DAYS", 420)
PSX_DIVERGENCE_MIN_TRADING_DAYS = getattr(core, "MIN_TRADING_DAYS", 100)
PSX_DIVERGENCE_PRICE_BASIS = getattr(core, "PRICE_BASIS", "close")
PSX_DIVERGENCE_REQUEST_DELAY = getattr(core, "REQUEST_DELAY", 0.15)


def run_psx_divergence_scan(progress_cb=None):
    """Market-wide PSX scan: near-52-week-low, bullish/bearish RSI
    divergence, and trend structure, for every listed symbol. Returns a
    dict of named result lists rather than writing CSV/HTML files (this
    is the same math as PSX Toolkit's main(), reshaped for an API)."""
    import psxdata

    tickers = psxdata.tickers()
    if not tickers:
        raise RuntimeError("PSX did not return a symbol list (site may be unreachable right now).")

    start_date = date.today() - timedelta(days=PSX_DIVERGENCE_HISTORY_DAYS)

    near_low_hits, divergence_hits = [], []
    bullish_all_hits, bearish_all_hits = [], []
    uptrend_hits, downtrend_hits = [], []
    errors = []

    total = len(tickers)
    for i, symbol in enumerate(tickers, 1):
        try:
            df = psxdata.stocks(symbol, start=start_date)
        except Exception as e:
            errors.append({"symbol": symbol, "error": str(e)})
            if progress_cb:
                progress_cb(i, total, symbol)
            time.sleep(PSX_DIVERGENCE_REQUEST_DELAY)
            continue

        if df is None or df.empty:
            if progress_cb:
                progress_cb(i, total, symbol)
            time.sleep(PSX_DIVERGENCE_REQUEST_DELAY)
            continue

        if "is_anomaly" in df.columns:
            df = df[~df["is_anomaly"].astype(bool)].copy()

        if len(df) < PSX_DIVERGENCE_MIN_TRADING_DAYS:
            if progress_cb:
                progress_cb(i, total, symbol)
            time.sleep(PSX_DIVERGENCE_REQUEST_DELAY)
            continue

        df = df.sort_values("date").reset_index(drop=True)
        df["date"] = pd.to_datetime(df["date"])

        latest_close = df["close"].iloc[-1]

        one_year_ago = df["date"].iloc[-1] - pd.Timedelta(days=365)
        last_year = df[df["date"] >= one_year_ago]
        if last_year.empty:
            if progress_cb:
                progress_cb(i, total, symbol)
            time.sleep(PSX_DIVERGENCE_REQUEST_DELAY)
            continue

        low_col = "low" if (PSX_DIVERGENCE_PRICE_BASIS == "low" and "low" in df.columns) else "close"
        low_52w = last_year[low_col].min()
        pct_above_low = (latest_close - low_52w) / low_52w * 100
        is_near_low = pct_above_low <= PSX_DIVERGENCE_NEAR_LOW_PCT

        df["rsi"] = core.compute_rsi(df["close"], core.RSI_PERIOD)

        base_info = {
            "symbol": symbol,
            "latest_close": round(float(latest_close), 2),
            "week52_low": round(float(low_52w), 2),
            "pct_above_52w_low": round(float(pct_above_low), 2),
            "latest_rsi": round(float(df["rsi"].iloc[-1]), 1),
        }

        if is_near_low:
            near_low_hits.append(dict(base_info))

        bullish = core.check_bullish_divergence(df, PSX_DIVERGENCE_LOOKBACK_DAYS, PSX_DIVERGENCE_SWING_ORDER)
        bearish = core.check_bearish_divergence(df, PSX_DIVERGENCE_LOOKBACK_DAYS, PSX_DIVERGENCE_SWING_ORDER)
        structure = core.classify_structure(df, PSX_STRUCTURE_LOOKBACK_DAYS, PSX_STRUCTURE_SWING_ORDER)

        if is_near_low and bullish:
            hit = dict(base_info); hit.update(bullish)
            divergence_hits.append(hit)
        if bullish:
            hit = dict(base_info); hit.update(bullish)
            bullish_all_hits.append(hit)
        if bearish:
            hit = dict(base_info); hit.update(bearish)
            bearish_all_hits.append(hit)
        if bullish and structure == "uptrend":
            hit = dict(base_info); hit["divergence_type"] = "bullish"; hit.update(bullish)
            uptrend_hits.append(hit)
        if bearish and structure == "uptrend":
            hit = dict(base_info); hit["divergence_type"] = "bearish"; hit.update(bearish)
            uptrend_hits.append(hit)
        if bullish and structure == "downtrend":
            hit = dict(base_info); hit["divergence_type"] = "bullish"; hit.update(bullish)
            downtrend_hits.append(hit)
        if bearish and structure == "downtrend":
            hit = dict(base_info); hit["divergence_type"] = "bearish"; hit.update(bearish)
            downtrend_hits.append(hit)

        if progress_cb:
            progress_cb(i, total, symbol)
        time.sleep(PSX_DIVERGENCE_REQUEST_DELAY)

    def sort_hits(hits, key="pct_above_52w_low"):
        return sorted(hits, key=lambda h: h.get(key, 0))

    return {
        "near_low": sort_hits(near_low_hits),
        "near_low_bullish_divergence": sort_hits(divergence_hits),
        "bullish_divergence_all": sort_hits(bullish_all_hits, "symbol"),
        "bearish_divergence_all": sort_hits(bearish_all_hits, "symbol"),
        "uptrend_divergence": sort_hits(uptrend_hits, "symbol"),
        "downtrend_divergence": sort_hits(downtrend_hits, "symbol"),
        "errors": errors,
        "symbols_scanned": total,
    }


def _run_psx_divergence_job_in_background(job_id):
    def worker():
        try:
            def progress_cb(done, tot, sym):
                _update_tech_job(job_id, progress={"done": done, "total": tot, "symbol": sym})
            result = run_psx_divergence_scan(progress_cb=progress_cb)
            _save_tech_cache("psxdivergence", result)
            _update_tech_job(job_id, status="done", result=result)
        except Exception as e:
            _update_tech_job(job_id, status="error", error=str(e))
    threading.Thread(target=worker, daemon=True).start()


@app.get("/api/psxdivergence/scan/start")
def api_psx_divergence_scan_start():
    guard = _technicals_guard()
    if guard:
        return guard
    job_id = _new_tech_job()
    _run_psx_divergence_job_in_background(job_id)
    return safe_jsonify({"ok": True, "job_id": job_id})


@app.get("/api/psxdivergence/scan/status/<job_id>")
def api_psx_divergence_scan_status(job_id):
    job = _get_tech_job(job_id)
    if job is None:
        return safe_jsonify({"ok": False, "error": "Unknown job id (server may have restarted)."}), 404
    return safe_jsonify({"ok": True, **job})


@app.get("/api/psxdivergence/scan/cached")
def api_psx_divergence_scan_cached():
    cached = _load_tech_cache("psxdivergence")
    if cached is None:
        return safe_jsonify({"ok": True, "found": False})
    return safe_jsonify({"ok": True, "found": True, "result": cached["data"], "saved_at": cached["saved_at"]})


# =====================================================================
# PORTFOLIO CSV IMPORT / EXPORT (merged in from the PSX Toolkit)
# =====================================================================

@app.get("/api/portfolio/export")
def portfolio_export_csv():
    conn = db()
    rows = conn.execute("SELECT symbol, quantity, avg_cost, acquired_date FROM holdings ORDER BY sort_order, symbol").fetchall()
    conn.close()

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["symbol", "quantity", "avg_cost", "acquired_date"])
    for r in rows:
        writer.writerow([r["symbol"], r["quantity"], r["avg_cost"], r["acquired_date"] or ""])

    return Response(
        buf.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=portfolio_export.csv"},
    )


@app.post("/api/portfolio/import")
def portfolio_import_csv():
    """Accepts a CSV file (multipart form field 'file') with columns
    symbol, quantity, avg_cost, acquired_date (acquired_date optional).
    Existing holdings for the same symbol are updated; new symbols are
    added. Malformed rows are skipped and reported back, not silently
    dropped."""
    if "file" not in request.files:
        return jsonify({"ok": False, "error": "No file uploaded."}), 400

    file = request.files["file"]
    try:
        text = file.read().decode("utf-8-sig")
    except Exception as e:
        return jsonify({"ok": False, "error": f"Could not read file: {e}"}), 400

    reader = csv.DictReader(io.StringIO(text))
    added, updated, skipped = 0, 0, []

    conn = db()
    for i, row in enumerate(reader, start=2):
        try:
            symbol = (row.get("symbol") or "").strip().upper()
            quantity = float(row.get("quantity"))
            avg_cost = float(row.get("avg_cost"))
            acquired_date = (row.get("acquired_date") or date.today().isoformat()).strip()
            if not symbol or quantity <= 0 or avg_cost <= 0:
                raise ValueError("symbol/quantity/avg_cost missing or invalid")

            existing = conn.execute("SELECT id FROM holdings WHERE symbol=?", (symbol,)).fetchone()
            if existing:
                conn.execute(
                    "UPDATE holdings SET quantity=?, avg_cost=?, acquired_date=? WHERE symbol=?",
                    (quantity, avg_cost, acquired_date, symbol),
                )
                updated += 1
            else:
                conn.execute(
                    "INSERT INTO holdings(symbol, quantity, avg_cost, acquired_date) VALUES (?,?,?,?)",
                    (symbol, quantity, avg_cost, acquired_date),
                )
                added += 1
        except Exception as e:
            skipped.append({"row": i, "error": str(e)})

    conn.commit()
    conn.close()

    data = current_portfolio()
    save_today_snapshot(data)

    return jsonify({"ok": True, "added": added, "updated": updated, "skipped": skipped})


if __name__ == "__main__":
    # use_reloader=False: on Windows, Flask's auto-reloader spawns a
    # second watcher process and re-runs this whole file. Combined with
    # our background bulk-price-refresh thread (start_bulk_refresh_thread),
    # that reliably triggers a Windows-only crash on shutdown/restart:
    #   OSError: [WinError 10038] An operation was attempted on
    #   something that is not a socket
    # in werkzeug's serve_forever/select.select(). Turning the reloader
    # off avoids the whole class of bug. You'll need to manually restart
    # `python app.py` after editing the code, but the server no longer
    # crashes on its own.
    init_db()
    start_bulk_refresh_thread()
    app.run(debug=False, use_reloader=False, host="0.0.0.0", port=int(os.environ.get("PORT", "5000")))
