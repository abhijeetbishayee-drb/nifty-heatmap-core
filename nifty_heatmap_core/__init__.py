"""Shared Yahoo Finance fetch + gainers/losers logic for the Nifty Heatmap web and Android apps."""

from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

NIFTY50 = [
    "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "INFY.NS", "ICICIBANK.NS",
    "HINDUNILVR.NS", "ITC.NS", "SBIN.NS", "BHARTIARTL.NS", "KOTAKBANK.NS",
    "LT.NS", "AXISBANK.NS", "ASIANPAINT.NS", "MARUTI.NS", "HCLTECH.NS",
    "SUNPHARMA.NS", "TITAN.NS", "ULTRACEMCO.NS", "BAJFINANCE.NS", "WIPRO.NS",
    "ONGC.NS", "NTPC.NS", "POWERGRID.NS", "NESTLEIND.NS", "TECHM.NS",
    "M&M.NS", "ADANIENT.NS", "ADANIPORTS.NS", "COALINDIA.NS", "JSWSTEEL.NS",
    "TVSMOTOR.NS", "TATASTEEL.NS", "BAJAJFINSV.NS", "BPCL.NS", "DRREDDY.NS",
    "CIPLA.NS", "EICHERMOT.NS", "HEROMOTOCO.NS", "INDUSINDBK.NS", "GRASIM.NS",
    "APOLLOHOSP.NS", "BRITANNIA.NS", "DIVISLAB.NS", "TATACONSUM.NS", "SBILIFE.NS",
    "HDFCLIFE.NS", "BAJAJ-AUTO.NS", "UPL.NS", "LTM.NS", "HINDALCO.NS",
]

INDICES = {
    "^NSEI": "nifty",
    "^NSEBANK": "banknifty",
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
}


def short_name(ticker):
    return ticker.replace(".NS", "").replace("-", "")[:10]


def nse_url(ticker):
    symbol = ticker.replace(".NS", "")
    return f"https://www.nseindia.com/get-quotes/equity?symbol={symbol}"


def fetch_one(ticker, timeout=10, on_error=None):
    try:
        sym = ticker.replace("^", "%5E")
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?interval=1d&range=5d"
        resp = requests.get(url, headers=HEADERS, timeout=timeout)
        data = resp.json()
        meta = data["chart"]["result"][0]["meta"]
        price = meta.get("regularMarketPrice")
        pct = meta.get("regularMarketChangePercent")
        pts = meta.get("fulldayChange")
        day_high = meta.get("regularMarketDayHigh")
        day_low = meta.get("regularMarketDayLow")
        return ticker, (price, pct, pts, day_high, day_low)
    except Exception as e:
        if on_error is not None:
            on_error(ticker, e)
        return ticker, (None, None, None, None, None)


def fetch_all(tickers, indices_map=None, timeout=10, on_error=None, max_workers=20):
    """Fetch `tickers` plus the keys of `indices_map` concurrently.

    Returns (stocks, indices):
      stocks: {ticker: (price, pct, pts, day_high, day_low)} for every entry in `tickers`
      indices: {indices_map[ticker]: {price, pct, pts, dayHigh, dayLow}} for successful index fetches
    """
    indices_map = indices_map or {}
    stocks = {}
    indices = {}
    all_tickers = list(indices_map.keys()) + list(tickers)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(fetch_one, t, timeout, on_error): t for t in all_tickers
        }
        for future in as_completed(futures):
            ticker, (price, pct, pts, day_high, day_low) = future.result()
            if ticker in indices_map:
                if price is not None:
                    indices[indices_map[ticker]] = {
                        "price": price, "pct": pct, "pts": pts,
                        "dayHigh": day_high, "dayLow": day_low,
                    }
            else:
                stocks[ticker] = (price, pct, pts, day_high, day_low)

    return stocks, indices


def build_rows(tickers, stocks):
    """Turn a {ticker: (price, pct, pts, day_high, day_low)} map into the row
    shape both apps compute gainers/losers from."""
    rows = []
    for ticker in tickers:
        price, pct, pts, day_high, day_low = stocks.get(
            ticker, (None, None, None, None, None))
        off_low = (price - day_low) / day_low * 100 if price is not None and day_low else None
        off_high = (price - day_high) / day_high * 100 if price is not None and day_high else None
        rows.append({
            "ticker": ticker,
            "name": short_name(ticker),
            "price": price,
            "pct": pct,
            "pts": pts,
            "offLow": off_low,
            "offHigh": off_high,
            "dayHigh": day_high,
            "dayLow": day_low,
        })
    return rows


def compute_movers(rows, n=5):
    """Top gainers = biggest % bounce off the day's low. Top losers = biggest
    % drop off the day's high. Returns (gainers, losers)."""
    valid_low = [r for r in rows if r.get("offLow") is not None]
    valid_high = [r for r in rows if r.get("offHigh") is not None]
    gainers = sorted(valid_low, key=lambda r: r["offLow"], reverse=True)[:n]
    losers = sorted(valid_high, key=lambda r: r["offHigh"])[:n]
    return gainers, losers
