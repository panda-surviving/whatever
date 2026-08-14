"""
PSX Screener: 52-Week Low + RSI Bullish Divergence
====================================================

What this does
---------------
1. Downloads the list of all stocks listed on the Pakistan Stock Exchange (PSX).
2. Pulls ~1 year of daily price history for each stock (free, public data via
   the `psxdata` library).
3. Flags stocks currently trading at or very near their 52-week low.
4. Among those, checks for a classic "bullish RSI divergence":
      -> price makes a LOWER low
      -> but RSI(14) makes a HIGHER low at the same time
   This pattern often signals weakening downside momentum.
5. Writes the results to:
      - results.html   (open this in your browser - just double-click it)
      - results.csv     (open in Excel if you prefer)

How to run it (see README.md for full step-by-step instructions)
------------------------------------------------------------------
    pip install -r requirements.txt
    python psx_screener.py

You can tweak the settings in the CONFIG section below without touching any
other code.

IMPORTANT DISCLAIMER
---------------------
This is a technical screening tool, not investment advice. 52-week-low +
RSI-divergence is a starting point for further research, not a buy signal.
Always do your own due diligence before trading. PSX market data terms
restrict commercial redistribution of this data - this tool is intended for
your own personal, non-commercial research use only.
"""

import sys
import time
import warnings
from datetime import date, timedelta

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

# ============================== CONFIG ==================================

# How many calendar days of history to pull (52 weeks + a buffer for
# indicator "warm-up" and swing detection).
HISTORY_DAYS = 420

# Which price to use for the "52-week low" and swing-low calculations:
#   "close" -> uses daily closing prices (matches simple "closing price
#              near its 52-week-low-close" screens - broader, catches more
#              stocks, but ignores intraday wicks/spikes)
#   "low"   -> uses the actual intraday low (the candle wick) - matches how
#              most charting platforms (e.g. TradingView) define "52-week
#              low," but is stricter and will flag fewer stocks
PRICE_BASIS = "close"

# A stock is considered "near its 52-week low" if the latest close is within
# this percentage of the 52-week low (as defined by PRICE_BASIS above).
# 0 = only flag stocks making a brand-new 52-week low today.
NEAR_LOW_PCT = 3.0

# RSI settings
RSI_PERIOD = 14

# How many bars on either side a point needs to be the smallest/largest
# in order to count as a "swing low" / "swing high" (for divergence
# detection). Higher = fewer, more significant swings.
SWING_ORDER = 8

# Only look for divergence using swing lows that occurred within the last
# N trading days (keeps it focused on the recent price action).
DIVERGENCE_LOOKBACK_DAYS = 90

# --- Significance filters (avoid flagging noisy, meaningless "divergences") ---
# The 2nd low must be at least this % BELOW the 1st low to count as a real
# "lower low" (not just a fraction of a percent of noise).
MIN_PRICE_DROP_PCT = 1.5

# RSI at the 2nd low must be at least this many points HIGHER than at the
# 1st low to count as a real "higher low".
MIN_RSI_RISE_POINTS = 5.0

# --- Bearish divergence significance filters (mirror image of above) ---
# The 2nd high must be at least this % ABOVE the 1st high to count as a
# real "higher high".
MIN_PRICE_RISE_PCT = 1.5

# RSI at the 2nd high must be at least this many points LOWER than at the
# 1st high to count as a real "lower high".
MIN_RSI_DROP_POINTS = 5.0

# --- Trend structure classification (higher-high/higher-low vs
# lower-high/lower-low) ---
# How many trading days back to look when classifying a stock's overall
# structure as an uptrend or downtrend.
STRUCTURE_LOOKBACK_DAYS = 150

# Swing significance for structure classification (separate from the
# divergence swing detection above, since structure is usually judged
# over a longer window with bigger swings).
STRUCTURE_SWING_ORDER = 8

# Skip stocks with fewer than this many closing prices with real trading
# (avoids illiquid / recently-listed / suspended scrips producing noise).
MIN_TRADING_DAYS = 100

# Skip stocks whose latest close is below this price (optional penny-stock
# filter). Set to 0 to disable.
MIN_PRICE = 0

# Pause between requests to be polite to PSX's servers (seconds).
REQUEST_DELAY = 0.15

# Limit for testing - set to None to scan the FULL market (~700+ symbols,
# takes a while on first run but is cached afterwards). Set to e.g. 30 to
# do a quick test run first.
LIMIT_SYMBOLS = None

# ==========================================================================


def compute_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Standard Wilder RSI."""
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    rsi = rsi.fillna(50)  # neutral where undefined (e.g. no losses yet)
    return rsi


def compute_macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    """Standard MACD: MACD line = EMA(fast) - EMA(slow); Signal = EMA(signal)
    of the MACD line; Histogram = MACD - Signal. Returns three Series."""
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def compute_sma(close: pd.Series, period: int) -> pd.Series:
    return close.rolling(window=period, min_periods=period).mean()


def compute_ema(close: pd.Series, period: int) -> pd.Series:
    return close.ewm(span=period, adjust=False).mean()


def compute_classic_pivots(high: float, low: float, close: float) -> dict:
    """Classic floor-trader pivot points, based on the most recent
    completed session's High/Low/Close."""
    p = (high + low + close) / 3
    r1 = 2 * p - low
    s1 = 2 * p - high
    r2 = p + (high - low)
    s2 = p - (high - low)
    r3 = high + 2 * (p - low)
    s3 = low - 2 * (high - p)
    return {"P": p, "R1": r1, "R2": r2, "R3": r3, "S1": s1, "S2": s2, "S3": s3}


def compute_fibonacci_pivots(high: float, low: float, close: float) -> dict:
    """Fibonacci-ratio pivot points (0.382/0.618/1.0 of the day's range),
    based on the most recent completed session's High/Low/Close."""
    p = (high + low + close) / 3
    rng = high - low
    r1 = p + 0.382 * rng
    s1 = p - 0.382 * rng
    r2 = p + 0.618 * rng
    s2 = p - 0.618 * rng
    r3 = p + 1.000 * rng
    s3 = p - 1.000 * rng
    return {"P": p, "R1": r1, "R2": r2, "R3": r3, "S1": s1, "S2": s2, "S3": s3}


def compute_technical_verdict(df: pd.DataFrame) -> dict:
    """
    Combines RSI(14), MACD(12,26,9), SMA 20/50/200, and EMA 20/50/200 into
    a single weighted 0-100 score and a Strong Sell -> Strong Buy verdict.

    Each of the 8 indicators casts one vote: Bullish (+1), Neutral (0), or
    Bearish (-1). The score is the average vote rescaled to 0-100
    (50 = perfectly neutral). This is a transparent, evenly-weighted
    combination - not a proprietary or "official" formula - and the full
    per-indicator breakdown is returned so exactly how the score was
    reached is visible, not just the final number.

    Requires df with a 'close' column (and enough history - 200+ bars
    ideally, for the 200-period moving averages to be meaningful).
    """
    close = df["close"]
    latest_close = float(close.iloc[-1])

    breakdown = []

    # --- RSI ---
    rsi = compute_rsi(close, 14)
    latest_rsi = float(rsi.iloc[-1])
    if latest_rsi < 30:
        rsi_signal = "bullish"   # oversold - potential bounce
    elif latest_rsi > 70:
        rsi_signal = "bearish"   # overbought - potential pullback
    else:
        rsi_signal = "neutral"
    breakdown.append({"indicator": "RSI (14)", "value": round(latest_rsi, 2), "signal": rsi_signal})

    # --- MACD ---
    macd_line, signal_line, _ = compute_macd(close)
    latest_macd, latest_signal = float(macd_line.iloc[-1]), float(signal_line.iloc[-1])
    if latest_macd > latest_signal:
        macd_signal = "bullish"
    elif latest_macd < latest_signal:
        macd_signal = "bearish"
    else:
        macd_signal = "neutral"
    breakdown.append({
        "indicator": "MACD (12,26,9)",
        "value": f"MACD {latest_macd:.2f} vs Signal {latest_signal:.2f}",
        "signal": macd_signal,
    })

    # --- SMA & EMA at 20/50/200 ---
    for period in (20, 50, 200):
        sma = compute_sma(close, period)
        latest_sma = sma.iloc[-1]
        if pd.notna(latest_sma):
            sig = "bullish" if latest_close > latest_sma else ("bearish" if latest_close < latest_sma else "neutral")
            breakdown.append({"indicator": f"SMA {period}", "value": round(float(latest_sma), 2), "signal": sig})
        else:
            breakdown.append({"indicator": f"SMA {period}", "value": None,
                               "signal": "neutral", "note": f"Not enough history for a {period}-period SMA yet."})

        ema = compute_ema(close, period)
        latest_ema = float(ema.iloc[-1])
        sig = "bullish" if latest_close > latest_ema else ("bearish" if latest_close < latest_ema else "neutral")
        breakdown.append({"indicator": f"EMA {period}", "value": round(latest_ema, 2), "signal": sig})

    vote_value = {"bullish": 1, "neutral": 0, "bearish": -1}
    total_vote = sum(vote_value[b["signal"]] for b in breakdown)
    score = round(50 + (total_vote / len(breakdown)) * 50, 1)

    if score < 20:
        verdict = "Strong Sell"
    elif score < 40:
        verdict = "Sell"
    elif score < 60:
        verdict = "Neutral"
    elif score < 80:
        verdict = "Buy"
    else:
        verdict = "Strong Buy"

    return {"score": score, "verdict": verdict, "latest_close": round(latest_close, 2), "breakdown": breakdown}


def find_swing_extrema(series: pd.Series, order: int = 5, kind: str = "low"):
    """Return integer positions where `series` is a local minimum ("low")
    or local maximum ("high") - i.e. more extreme than `order` bars on
    either side. Pure pandas/numpy, no scipy dependency needed."""
    vals = series.values
    n = len(vals)
    positions = []
    for i in range(order, n - order):
        window = vals[i - order : i + order + 1]
        if kind == "low":
            if vals[i] == window.min() and np.sum(window == vals[i]) == 1:
                positions.append(i)
        else:
            if vals[i] == window.max() and np.sum(window == vals[i]) == 1:
                positions.append(i)
    return positions


def find_swing_lows(series: pd.Series, order: int = 5):
    return find_swing_extrema(series, order=order, kind="low")


def check_bullish_divergence(df: pd.DataFrame, lookback_days: int, swing_order: int,
                              min_price_drop_pct: float = MIN_PRICE_DROP_PCT,
                              min_rsi_rise_points: float = MIN_RSI_RISE_POINTS):
    """
    Look at the most recent two swing lows in price within `lookback_days`.
    Bullish divergence = price's 2nd low < 1st low (by at least
    `min_price_drop_pct`), AND RSI's 2nd low > 1st low (by at least
    `min_rsi_rise_points`). The minimums filter out noisy, meaningless
    "divergences" where the two lows are basically the same value.

    Returns a dict with divergence details if found, else None.
    """
    recent = df.iloc[-lookback_days:].reset_index(drop=True)
    if len(recent) < swing_order * 2 + 2:
        return None

    price_col = "low" if (PRICE_BASIS == "low" and "low" in recent.columns) else "close"
    swing_positions = find_swing_lows(recent[price_col], order=swing_order)
    if len(swing_positions) < 2:
        return None

    # Take the two most recent swing lows
    p2_idx, p1_idx = swing_positions[-1], swing_positions[-2]
    # p1 = earlier low, p2 = later (more recent) low
    # Price comparison uses the actual intraday low (the candle wick) -
    # matching what you'd see and draw a trendline through on a chart.
    p1_price = recent[price_col].iloc[p1_idx]
    p2_price = recent[price_col].iloc[p2_idx]
    p1_rsi = recent["rsi"].iloc[p1_idx]
    p2_rsi = recent["rsi"].iloc[p2_idx]
    p1_date = recent["date"].iloc[p1_idx]
    p2_date = recent["date"].iloc[p2_idx]

    price_drop_pct = (p1_price - p2_price) / p1_price * 100
    rsi_rise_points = p2_rsi - p1_rsi

    is_real_lower_low = price_drop_pct >= min_price_drop_pct
    is_real_higher_low = rsi_rise_points >= min_rsi_rise_points

    if is_real_lower_low and is_real_higher_low:
        return {
            "pivot1_date": p1_date.date(),
            "pivot1_price": round(float(p1_price), 2),
            "pivot1_rsi": round(float(p1_rsi), 1),
            "pivot2_date": p2_date.date(),
            "pivot2_price": round(float(p2_price), 2),
            "pivot2_rsi": round(float(p2_rsi), 1),
            "price_change_pct": round(float(-price_drop_pct), 2),
            "rsi_change_points": round(float(rsi_rise_points), 1),
        }
    return None


def check_bearish_divergence(df: pd.DataFrame, lookback_days: int, swing_order: int,
                              min_price_rise_pct: float = MIN_PRICE_RISE_PCT,
                              min_rsi_drop_points: float = MIN_RSI_DROP_POINTS):
    """
    Mirror image of check_bullish_divergence: looks at the two most recent
    swing HIGHS. Bearish divergence = price's 2nd high > 1st high (by at
    least `min_price_rise_pct`), AND RSI's 2nd high < 1st high (by at least
    `min_rsi_drop_points`). This pattern often signals weakening upside
    momentum - a possible warning sign in an uptrend.

    Returns a dict with divergence details if found, else None.
    """
    recent = df.iloc[-lookback_days:].reset_index(drop=True)
    if len(recent) < swing_order * 2 + 2:
        return None

    price_col = "high" if (PRICE_BASIS == "low" and "high" in recent.columns) else "close"
    swing_positions = find_swing_extrema(recent[price_col], order=swing_order, kind="high")
    if len(swing_positions) < 2:
        return None

    p2_idx, p1_idx = swing_positions[-1], swing_positions[-2]
    p1_price = recent[price_col].iloc[p1_idx]
    p2_price = recent[price_col].iloc[p2_idx]
    p1_rsi = recent["rsi"].iloc[p1_idx]
    p2_rsi = recent["rsi"].iloc[p2_idx]
    p1_date = recent["date"].iloc[p1_idx]
    p2_date = recent["date"].iloc[p2_idx]

    price_rise_pct = (p2_price - p1_price) / p1_price * 100
    rsi_drop_points = p1_rsi - p2_rsi

    is_real_higher_high = price_rise_pct >= min_price_rise_pct
    is_real_lower_high = rsi_drop_points >= min_rsi_drop_points

    if is_real_higher_high and is_real_lower_high:
        return {
            "pivot1_date": p1_date.date(),
            "pivot1_price": round(float(p1_price), 2),
            "pivot1_rsi": round(float(p1_rsi), 1),
            "pivot2_date": p2_date.date(),
            "pivot2_price": round(float(p2_price), 2),
            "pivot2_rsi": round(float(p2_rsi), 1),
            "price_change_pct": round(float(price_rise_pct), 2),
            "rsi_change_points": round(float(-rsi_drop_points), 1),
        }
    return None


def classify_structure(df: pd.DataFrame, lookback_days: int, swing_order: int):
    """
    Classify a stock's recent price structure using its last two swing
    highs and last two swing lows:
      - "uptrend"   -> higher high AND higher low (HH + HL)
      - "downtrend" -> lower high AND lower low (LH + LL)
      - "mixed"     -> anything else (e.g. HH + LL - a widening range)
      - None        -> not enough swing points to tell
    """
    recent = df.iloc[-lookback_days:].reset_index(drop=True)
    if len(recent) < swing_order * 2 + 2:
        return None

    low_col = "low" if (PRICE_BASIS == "low" and "low" in recent.columns) else "close"
    high_col = "high" if (PRICE_BASIS == "low" and "high" in recent.columns) else "close"

    swing_low_pos = find_swing_extrema(recent[low_col], order=swing_order, kind="low")
    swing_high_pos = find_swing_extrema(recent[high_col], order=swing_order, kind="high")

    if len(swing_low_pos) < 2 or len(swing_high_pos) < 2:
        return None

    low2, low1 = recent[low_col].iloc[swing_low_pos[-1]], recent[low_col].iloc[swing_low_pos[-2]]
    high2, high1 = recent[high_col].iloc[swing_high_pos[-1]], recent[high_col].iloc[swing_high_pos[-2]]

    higher_high, higher_low = high2 > high1, low2 > low1
    lower_high, lower_low = high2 < high1, low2 < low1

    if higher_high and higher_low:
        return "uptrend"
    if lower_high and lower_low:
        return "downtrend"
    return "mixed"


def main():
    try:
        import psxdata
    except ImportError:
        print("ERROR: psxdata is not installed.")
        print("Run:  pip install -r requirements.txt")
        sys.exit(1)

    print("Fetching list of all PSX-listed symbols...")
    try:
        tickers = psxdata.tickers()
    except Exception as e:
        print(f"Could not fetch ticker list: {e}")
        sys.exit(1)

    if not tickers:
        print("No tickers returned - PSX site may be unreachable right now. Try again later.")
        sys.exit(1)

    if LIMIT_SYMBOLS:
        tickers = tickers[:LIMIT_SYMBOLS]

    print(f"Found {len(tickers)} symbols. Downloading price history "
          f"(this can take a while the first time - it's cached after that)...\n")

    start_date = date.today() - timedelta(days=HISTORY_DAYS)

    near_low_hits = []
    divergence_hits = []          # bullish divergence AND near 52w low (original combo list)
    bullish_all_hits = []         # every bullish divergence, market-wide
    bearish_all_hits = []         # every bearish divergence, market-wide
    uptrend_divergence_hits = []  # divergence (either type) within an HH+HL structure
    downtrend_divergence_hits = []  # divergence (either type) within an LH+LL structure
    errors = []

    for i, symbol in enumerate(tickers, 1):
        progress = f"[{i}/{len(tickers)}]"
        try:
            df = psxdata.stocks(symbol, start=start_date)
        except Exception as e:
            errors.append((symbol, str(e)))
            time.sleep(REQUEST_DELAY)
            continue

        if df is None or df.empty:
            time.sleep(REQUEST_DELAY)
            continue

        # Drop rows PSX itself flags as bad/glitched ticks - these can create
        # a fake "52-week low" or throw off RSI/divergence that never
        # actually happened on the real chart.
        if "is_anomaly" in df.columns:
            df = df[~df["is_anomaly"].astype(bool)].copy()

        if len(df) < MIN_TRADING_DAYS:
            time.sleep(REQUEST_DELAY)
            continue

        df = df.sort_values("date").reset_index(drop=True)
        df["date"] = pd.to_datetime(df["date"])

        latest_close = df["close"].iloc[-1]
        if MIN_PRICE and latest_close < MIN_PRICE:
            time.sleep(REQUEST_DELAY)
            continue

        # 52-week (365 day) low, based on the last year of INTRADAY lows
        # (the candle wicks) - not closing prices. This is how "52-week low"
        # is conventionally defined and how charting platforms like
        # TradingView compute it, so our numbers should now line up with
        # what you see on the chart.
        one_year_ago = df["date"].iloc[-1] - pd.Timedelta(days=365)
        last_year = df[df["date"] >= one_year_ago]
        if last_year.empty:
            time.sleep(REQUEST_DELAY)
            continue

        low_col = "low" if (PRICE_BASIS == "low" and "low" in df.columns) else "close"
        low_52w = last_year[low_col].min()
        pct_above_low = (latest_close - low_52w) / low_52w * 100

        is_near_low = pct_above_low <= NEAR_LOW_PCT

        print(f"{progress} {symbol:<8} close={latest_close:<10.2f} "
              f"52w_low={low_52w:<10.2f} (+{pct_above_low:.1f}%)"
              f"{'  <-- NEAR 52W LOW' if is_near_low else ''}")

        # RSI + divergence checks now run for EVERY stock, not just ones
        # near their 52-week low, so we can build market-wide divergence
        # and trend-structure lists.
        df["rsi"] = compute_rsi(df["close"], RSI_PERIOD)

        base_info = {
            "symbol": symbol,
            "latest_close": round(float(latest_close), 2),
            "52w_low": round(float(low_52w), 2),
            "pct_above_52w_low": round(float(pct_above_low), 2),
            "latest_rsi": round(float(df["rsi"].iloc[-1]), 1),
        }

        if is_near_low:
            near_low_hits.append(dict(base_info))

        bullish = check_bullish_divergence(df, DIVERGENCE_LOOKBACK_DAYS, SWING_ORDER)
        bearish = check_bearish_divergence(df, DIVERGENCE_LOOKBACK_DAYS, SWING_ORDER)
        structure = classify_structure(df, STRUCTURE_LOOKBACK_DAYS, STRUCTURE_SWING_ORDER)

        if is_near_low and bullish:
            hit = dict(base_info)
            hit.update(bullish)
            divergence_hits.append(hit)

        if bullish:
            hit = dict(base_info)
            hit.update(bullish)
            bullish_all_hits.append(hit)

        if bearish:
            hit = dict(base_info)
            hit.update(bearish)
            bearish_all_hits.append(hit)

        if bullish and structure == "uptrend":
            hit = dict(base_info)
            hit["divergence_type"] = "bullish"
            hit.update(bullish)
            uptrend_divergence_hits.append(hit)
        if bearish and structure == "uptrend":
            hit = dict(base_info)
            hit["divergence_type"] = "bearish"
            hit.update(bearish)
            uptrend_divergence_hits.append(hit)

        if bullish and structure == "downtrend":
            hit = dict(base_info)
            hit["divergence_type"] = "bullish"
            hit.update(bullish)
            downtrend_divergence_hits.append(hit)
        if bearish and structure == "downtrend":
            hit = dict(base_info)
            hit["divergence_type"] = "bearish"
            hit.update(bearish)
            downtrend_divergence_hits.append(hit)

        time.sleep(REQUEST_DELAY)

    print("\n" + "=" * 70)
    print(f"Done. {len(near_low_hits)} stocks near their 52-week low.")
    print(f"{len(divergence_hits)} of those show bullish RSI divergence.")
    print(f"{len(bullish_all_hits)} stocks show bullish RSI divergence market-wide.")
    print(f"{len(bearish_all_hits)} stocks show bearish RSI divergence market-wide.")
    print(f"{len(uptrend_divergence_hits)} divergences found within an uptrend (HH+HL) structure.")
    print(f"{len(downtrend_divergence_hits)} divergences found within a downtrend (LH+LL) structure.")
    if errors:
        print(f"({len(errors)} symbols failed to download and were skipped.)")
    print("=" * 70)

    def symbol_first(df):
        """Explicitly force 'symbol' to be the first column, regardless of
        dict-insertion order or any pandas-version-specific column-ordering
        behavior - guarantees consistent, readable table output."""
        if df.empty or "symbol" not in df.columns:
            return df
        cols = ["symbol"] + [c for c in df.columns if c != "symbol"]
        return df[cols]

    def to_df(hits, sort_col="pct_above_52w_low"):
        df = pd.DataFrame(hits).sort_values(sort_col) if hits else pd.DataFrame()
        return symbol_first(df)

    near_low_df = to_df(near_low_hits)
    divergence_df = to_df(divergence_hits)
    bullish_all_df = to_df(bullish_all_hits, sort_col="symbol")
    bearish_all_df = to_df(bearish_all_hits, sort_col="symbol")
    uptrend_df = to_df(uptrend_divergence_hits, sort_col="symbol")
    downtrend_df = to_df(downtrend_divergence_hits, sort_col="symbol")

    divergence_df.to_csv("results.csv", index=False)
    bullish_all_df.to_csv("bullish_divergence_all.csv", index=False)
    bearish_all_df.to_csv("bearish_divergence_all.csv", index=False)
    uptrend_df.to_csv("uptrend_divergence.csv", index=False)
    downtrend_df.to_csv("downtrend_divergence.csv", index=False)

    write_html_report(near_low_df, divergence_df, bullish_all_df, bearish_all_df,
                       uptrend_df, downtrend_df, errors)

    print("\nResults written to:")
    print("  - results.html                  (open this in your browser - everything's in here)")
    print("  - results.csv                   (near-low + bullish divergence combo, for Excel)")
    print("  - bullish_divergence_all.csv     (all bullish divergences, market-wide)")
    print("  - bearish_divergence_all.csv     (all bearish divergences, market-wide)")
    print("  - uptrend_divergence.csv         (divergences within an HH+HL uptrend structure)")
    print("  - downtrend_divergence.csv       (divergences within an LH+LL downtrend structure)")


def write_html_report(near_low_df, divergence_df, bullish_all_df, bearish_all_df,
                      uptrend_df, downtrend_df, errors):
    def df_to_html_table(df, empty_msg):
        if df is None or df.empty:
            return f"<p class='empty'>{empty_msg}</p>"
        return df.to_html(index=False, classes="tbl", border=0)

    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>PSX Screener Results</title>
<style>
  body {{ font-family: -apple-system, Segoe UI, Roboto, Arial, sans-serif;
          background: #0f1115; color: #e6e6e6; padding: 32px; max-width: 1100px; margin: auto; }}
  h1 {{ color: #4fd1c5; margin-bottom: 4px; }}
  h2 {{ color: #f6ad55; margin-top: 40px; border-bottom: 1px solid #333; padding-bottom: 8px; }}
  p.sub {{ color: #999; margin-top: 0; }}
  p.empty {{ color: #777; font-style: italic; }}
  table.tbl {{ border-collapse: collapse; width: 100%; margin-top: 12px; font-size: 0.92em; }}
  table.tbl th {{ background: #1c2129; text-align: left; padding: 8px 10px; color: #4fd1c5; white-space: nowrap; }}
  table.tbl td {{ padding: 8px 10px; border-top: 1px solid #262b33; white-space: nowrap; }}
  table.tbl tr:hover {{ background: #171b22; }}
  .disclaimer {{ margin-top: 48px; font-size: 0.85em; color: #888; border-top: 1px solid #333; padding-top: 16px; }}
  .badge {{ background: #234; color: #4fd1c5; padding: 2px 8px; border-radius: 10px; font-size: 0.8em; margin-right: 4px;}}
  .badge.bear {{ background: #402; color: #f56565; }}
</style>
</head>
<body>
  <h1>PSX Screener</h1>
  <p class="sub">Generated {date.today().isoformat()} &middot;
     <span class="badge">{len(divergence_df)} near-low + bullish divergence</span>
     <span class="badge">{len(near_low_df)} near 52-week low</span>
     <span class="badge">{len(bullish_all_df)} bullish divergence (all)</span>
     <span class="badge bear">{len(bearish_all_df)} bearish divergence (all)</span>
     <span class="badge">{len(uptrend_df)} in uptrend structure</span>
     <span class="badge bear">{len(downtrend_df)} in downtrend structure</span>
  </p>

  <h2>Bullish RSI Divergence + Near 52-Week Low</h2>
  <p class="sub">Price made a lower low while RSI made a higher low, in a stock also sitting near its 52-week low - a possible sign of fading downside momentum right where it matters most.</p>
  {df_to_html_table(divergence_df, "No stocks matched both conditions today.")}

  <h2>All Stocks Near Their 52-Week Low</h2>
  <p class="sub">Every screened stock within {NEAR_LOW_PCT}% of its 52-week low (not all of these show divergence).</p>
  {df_to_html_table(near_low_df, "No stocks currently near their 52-week low.")}

  <h2>All Bullish RSI Divergence (market-wide)</h2>
  <p class="sub">Every stock showing a bullish divergence anywhere in the market - regardless of where it sits relative to its 52-week low.</p>
  {df_to_html_table(bullish_all_df, "No bullish divergences found today.")}

  <h2>All Bearish RSI Divergence (market-wide)</h2>
  <p class="sub">The mirror image: price made a higher high while RSI made a lower high - a possible sign of fading upside momentum.</p>
  {df_to_html_table(bearish_all_df, "No bearish divergences found today.")}

  <h2>Divergence Within an Uptrend Structure (Higher-High + Higher-Low)</h2>
  <p class="sub">Stocks whose recent swing structure is a series of higher highs and higher lows, that are also showing an RSI divergence (bullish or bearish) - see the "divergence_type" column.</p>
  {df_to_html_table(uptrend_df, "No divergences found within an uptrend structure today.")}

  <h2>Divergence Within a Downtrend Structure (Lower-High + Lower-Low)</h2>
  <p class="sub">Stocks whose recent swing structure is a series of lower highs and lower lows, that are also showing an RSI divergence (bullish or bearish) - see the "divergence_type" column.</p>
  {df_to_html_table(downtrend_df, "No divergences found within a downtrend structure today.")}

  <div class="disclaimer">
    This is a technical screening tool, not investment advice. Do your own research
    before making any trading decisions. Data sourced from the public PSX website via
    the open-source <code>psxdata</code> library; for personal research use only -
    PSX restricts commercial redistribution of its market data.
    {f"<br>{len(errors)} symbols failed to download and were skipped." if errors else ""}
  </div>
</body>
</html>"""

    with open("results.html", "w", encoding="utf-8") as f:
        f.write(html)


if __name__ == "__main__":
    main()
