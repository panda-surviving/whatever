# PSX Hub — merged PSX research, portfolio & screener app

This is a single Flask web app that merges **PSX Toolkit** and **PSX 360**
into one site. It keeps PSX 360's full front-end (it was the more complete
of the two) and adds the two capabilities PSX Toolkit had that PSX 360
didn't: **Crypto Technicals** and **Forex Technicals** — RSI-divergence /
trend-structure screeners on live intraday data — plus **portfolio CSV
import/export**. Overlapping features (PSX screener, fundamentals, mutual
funds, crypto/forex prices, portfolio tracking) were kept in their PSX 360
form since that implementation was more complete and already had a
matching database and UI.

## What's inside

**Overview:** Dashboard, Portfolio (holdings, day-by-day P/L, CSV
import/export), Watchlist, Transactions, Stock Screener, **PSX Divergence
Screener** (new).

**Markets:** Market overview, full PSX stock directory, Mutual Funds
(MUFAP), Crypto prices, Forex rates, Commodities, Fear & Greed sentiment,
Sector rotation, **Forex Technicals** (new), **Crypto Technicals** (new).

**Research:** Pakistan macro indicators, News/announcements, Journal,
Tools (calculators), World Clock, Stock comparison.

**Top ticker bar:** A scrolling strip on the dashboard now refreshes
itself every 60 seconds instead of loading once — so the "PSX LIVE" line
in particular reliably shows up once the server's bulk quote cache
finishes warming up (which can take a little while right after a cold
start on a free host), instead of staying blank until you manually
reload the page.

**Under the hood:** Background bulk quote refresh so the screener doesn't
wait on PSX for every click, cached technical indicators, a service
worker for repeat-visit speed, and a `/healthz` endpoint for uptime
monitors.

### New: PSX Divergence Screener

This is PSX Toolkit's own original screen, kept as its own separate tab
from PSX 360's filter-based Screener. It walks every PSX-listed stock's
roughly one year of daily price history (via the free `psxdata` library)
and reports, market-wide:
- Stocks sitting near their 52-week low
- Bullish RSI divergence (price makes a lower low, RSI makes a higher low)
  combined with being near a 52-week low
- Every bullish RSI divergence market-wide
- Every bearish RSI divergence market-wide
- Divergences occurring inside an uptrend (higher-high/higher-low) structure
- Divergences occurring inside a downtrend (lower-high/lower-low) structure

Scanning 700+ symbols one at a time with a polite delay takes several
minutes on a full run, so — like the Technicals scanners — it runs as a
background job with progress polling, and the last completed scan is
cached so reopening the tab shows results instantly.

### New: Forex & Crypto Technicals

Ported over from PSX Toolkit. Scans major forex pairs (plus gold and
silver) and the top ~15 cryptocurrencies by market cap for:
- RSI(14)
- Bullish / bearish RSI divergence
- Trend-structure classification (higher highs/lows, lower highs/lows, etc.)

on 30-minute and 1-hour bars (forex) or 30m/1h/4h bars (crypto), using
free data from Yahoo Finance (`yfinance`, no API key needed). A scan
takes a minute or two, so it runs in the background — the page polls for
progress, and the last completed scan is cached so reopening the tab
shows results instantly.

This is a technical screen, not investment advice.

### New: Interactive Charts (stock page)

Real candlestick + volume charts (via [Lightweight Charts](https://www.tradingview.com/lightweight-charts/), TradingView's free MIT-licensed charting library), built entirely from actual PSX price history — no placeholder/demo data:

- Candlesticks with a synced volume pane underneath
- Selectable timeframes: 1M / 3M / 6M / 1Y / 3Y / 5Y / ALL (3Y+ auto-resamples to weekly/monthly bars so old, long-listed stocks stay readable)
- Toggleable SMA(20/50/200) and EMA(20/50/200) overlays on the price pane
- Separate RSI(14) and MACD(12/26/9) panels below, synced to the same time scale
- Support/resistance lines drawn directly on the price chart from the same classic pivot-point math used in the Technical Verdict card

Switching timeframes or toggling indicators never re-hits PSX — everything is computed client-request-time from the same cached full-history fetch described below.

### Performance & reliability fixes (this round)

A few real production issues were found and fixed:

- **Shared, retry-hardened HTTP session** — every PSX/MUFAP request now goes through one connection-pooled `requests.Session()` with automatic retries on connection resets and 5xx/429 responses, instead of a fresh, unprotected connection per call. This was the direct cause of the `RemoteDisconnected`/"Connection aborted" errors under load.
- **`/api/symbols` no longer blocks** — it used to make a live, synchronous PSX request on every cold start, so the first visitor after a Render free-tier wake-up could get stuck waiting (and failing) on it. It now serves cached (or a small built-in fallback) data instantly and always refreshes in the background, matching the pattern already used for live quotes.
- **Divergence Screener runs 6 symbols concurrently** instead of one at a time — cuts a full ~700-symbol market scan from many minutes down to a fraction of that.
- **Mutual Funds NaN/Infinity bug** — a malformed scraped number could silently become `NaN`/`Infinity`, which isn't valid JSON and crashes `response.json()` in the browser. Fixed at the source and backstopped everywhere with a blanket JSON-safety wrapper.

### New: Consolidated Technical Verdict & Support/Resistance (stock page)

Opening any stock's profile page (from All PSX Stocks, Watchlist,
Portfolio, etc.) now also shows two new cards:

- **Consolidated Technical Verdict** — RSI(14), MACD, and SMA/EMA at
  20/50/200 are each scored bullish/neutral/bearish, weighted, and
  combined into a single 0–100 score mapped to **Strong Buy / Buy /
  Neutral / Sell / Strong Sell**. A breakdown table shows exactly which
  indicators pushed the score up or down and by how much.
- **Support & Resistance** — Classic floor-trader pivot points (P,
  S1–S3, R1–R3) and Fibonacci pivot points, computed from the most
  recent completed trading day.

Both pull full price history directly from PSX (rather than this app's
own slowly-self-accumulating price-history table), so they work
immediately for any symbol instead of needing weeks/months of the app
running first.

### New: Portfolio CSV import/export

On the Portfolio page, **Export CSV** downloads your current holdings
(symbol, quantity, avg_cost, acquired_date). **Import CSV** accepts a
file in the same format — matching symbols are updated, new ones are
added, and any malformed rows are reported back rather than silently
skipped.

## Run it locally

```bash
pip install -r requirements.txt
python app.py
```

Then open `http://127.0.0.1:5000` in your browser. To reach it from your
phone on the same WiFi, use your computer's local IP instead of
`127.0.0.1` (e.g. `http://192.168.1.23:5000`) — check your OS's network
settings for that IP, or run `ipconfig` (Windows) / `ifconfig` (Mac) in a
terminal. Add it to your phone's home screen ("Add to Home Screen" in
Safari, or the ⋮ menu → "Install app" in Chrome) for an app-like icon.

## Deploy for free (Render)

Render's free tier can run this Flask app at no cost, from any device,
without keeping your own computer on.

1. Put this folder in a GitHub repository (GitHub Desktop or
   `git init && git add . && git commit -m "init" && git push` all work).
2. In Render, choose **New → Web Service** and connect that repository.
3. Render will pick up the included `render.yaml` automatically —
   otherwise set:
   - **Build command:** `pip install -r requirements.txt`
   - **Start command:** `gunicorn app:app --workers 1 --threads 8 --timeout 120 --keep-alive 5`
   - **Health check path:** `/healthz`
4. Deploy. Render gives you a public `https://your-app.onrender.com` URL
   you can open from any device — phone, tablet, laptop.

Full official docs: https://render.com/docs/deploy-flask

**Free-tier notes:**
- Free services spin down after 15 minutes of inactivity and take ~30–60
  seconds to wake back up on the next visit — normal for a free host.
- The filesystem is ephemeral, so the SQLite portfolio database
  (`portfolio.db`) can be reset on redeploy/restart. For data that must
  never disappear, point the app at an external database — this is
  beyond what's included here, but Render's docs cover free Postgres
  add-ons.
- Use **Export CSV** on the Portfolio page from time to time as a manual
  backup regardless of hosting.

## Optional live market-data key

The app already uses public/fallback sources for everything (PSX's own
site, CoinGecko, Frankfurter, MUFAP, Yahoo Finance). For live world
indices/commodities beyond those free sources, you can optionally set:

- `MARKET_DATA_API_KEY`
- `MARKET_DATA_PROVIDER` (defaults to `twelvedata`)

as environment variables. Never put API keys directly in source code —
set them as environment variables in Render's dashboard (or a local
`.env` you don't commit) instead.

## What was merged from where

| Feature | Source | Notes |
|---|---|---|
| Dashboard, Portfolio, Watchlist, Transactions | PSX 360 | Kept as-is — SQLite-backed, includes P/L history |
| Stock Screener, Fundamentals | PSX 360 | Kept as-is — has its own in-house technical-indicator engine with real progress tracking |
| Mutual Funds, Crypto, Forex, Commodities, Sentiment, Macro, News, Journal, Tools, World Clock | PSX 360 | Kept as-is |
| **Forex Technicals, Crypto Technicals** | **PSX Toolkit** | Newly wired into PSX 360's UI/routing; RSI-divergence math reused from `psx_screener.py` |
| **PSX Divergence Screener** | **PSX Toolkit** | Its own separate tab now, reusing `psx_screener.py`'s original 52-week-low + divergence logic against the live `psxdata` library, run as a background job |
| **Portfolio CSV import/export** | **PSX Toolkit** (concept) | Rebuilt against PSX 360's SQLite schema |

PSX Toolkit's own portfolio system and fundamentals lookup were **not**
duplicated — PSX 360 already covers that ground with a more capable,
database-backed implementation. Its 52-week-low/divergence screener *is*
now included as its own tab (Divergence Screener), separate from PSX
360's filter-based Screener.

## Notes

- PSX / MUFAP / Yahoo Finance data availability can change independently
  of this app. Some fields are deliberately shown as unavailable rather
  than guessed.
- This is a personal research tool, not investment advice or a brokerage
  connection — nothing here places trades.
- Your data (portfolio, watchlist, transactions) lives in this app's own
  SQLite database; nothing is sent to a third party except requests to
  public data sources for prices.
