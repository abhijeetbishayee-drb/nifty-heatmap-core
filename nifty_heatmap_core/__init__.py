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


# ── NSE F&O universe, grouped by sector ──────────────────────────────────────
# Source: the user's Kite marketwatch "NSE F&O Stocks (Grouped by sector)".
# NOTE: that export declared 210 names (Financial Services 55) but only 209 rows
# survived the copy out of Kite — Financial Services here holds 54. Adding the
# missing symbol is a one-line change below.

FNO_SECTORS = {
    "Automobile and Auto Components": [
        "MARUTI.NS", "M&M.NS", "BAJAJ-AUTO.NS", "EICHERMOT.NS", "TVSMOTOR.NS", "HYUNDAI.NS",
        "MOTHERSON.NS", "BOSCHLTD.NS", "TMPV.NS", "HEROMOTOCO.NS", "BHARATFORG.NS",
        "UNOMINDA.NS", "ATHERENERG.NS", "TIINDIA.NS", "SONACOMS.NS", "FORCEMOT.NS",
    ],
    "Capital Goods": [
        "HAL.NS", "BEL.NS", "ABB.NS", "BHEL.NS", "CGPOWER.NS", "CUMMINSIND.NS", "SIEMENS.NS",
        "POWERINDIA.NS", "POLYCAB.NS", "GVT&D.NS", "ASHOKLEY.NS", "MAZDOCK.NS", "WAAREEENER.NS",
        "SUZLON.NS", "APLAPOLLO.NS", "SUPREMEIND.NS", "KEI.NS", "PREMIERENE.NS", "BDL.NS",
        "COCHINSHIP.NS", "ASTRAL.NS", "KAYNES.NS", "INOXWIND.NS",
    ],
    "Chemicals": [
        "SOLARINDS.NS", "PIDILITIND.NS", "SRF.NS", "UPL.NS", "PIIND.NS",
    ],
    "Construction": [
        "LT.NS", "RVNL.NS", "NBCC.NS",
    ],
    "Construction Materials": [
        "ULTRACEMCO.NS", "GRASIM.NS", "AMBUJACEM.NS", "SHREECEM.NS",
    ],
    "Consumer Durables": [
        "TITAN.NS", "ASIANPAINT.NS", "DIXON.NS", "HAVELLS.NS", "KALYANKJIL.NS", "VOLTAS.NS",
        "BLUESTARCO.NS", "AMBER.NS", "PGEL.NS", "CROMPTON.NS",
    ],
    "Consumer Services": [
        "ETERNAL.NS", "DMART.NS", "TRENT.NS", "INDHOTEL.NS", "NYKAA.NS", "NAUKRI.NS",
        "SWIGGY.NS", "VMM.NS", "JUBLFOOD.NS",
    ],
    "Fast Moving Consumer Goods": [
        "HINDUNILVR.NS", "ITC.NS", "NESTLEIND.NS", "VBL.NS", "BRITANNIA.NS", "MARICO.NS",
        "UNITDSPR.NS", "TATACONSUM.NS", "GODREJCP.NS", "DABUR.NS", "RADICO.NS", "COLPAL.NS",
        "PATANJALI.NS", "GODFRYPHLP.NS",
    ],
    "Financial Services": [
        "HDFCBANK.NS", "ICICIBANK.NS", "SBIN.NS", "BAJFINANCE.NS", "LICI.NS", "KOTAKBANK.NS",
        "AXISBANK.NS", "BAJAJFINSV.NS", "SHRIRAMFIN.NS", "SBILIFE.NS", "CHOLAFIN.NS",
        "JIOFIN.NS", "UNIONBANK.NS", "PNB.NS", "BANKBARODA.NS", "BAJAJHLDNG.NS", "PFC.NS",
        "INDIANB.NS", "HDFCLIFE.NS", "MUTHOOTFIN.NS", "CANBK.NS", "PAYTM.NS", "ABCAPITAL.NS",
        "IRFC.NS", "HDFCAMC.NS", "FEDERALBNK.NS", "MCX.NS", "POLICYBZR.NS", "RECLTD.NS",
        "AUBANK.NS", "LTF.NS", "INDUSINDBK.NS", "NAM-INDIA.NS", "IDFCFIRSTB.NS", "ICICIGI.NS",
        "YESBANK.NS", "ICICIPRULI.NS", "MAHABANK.NS", "BANKINDIA.NS", "RBLBANK.NS",
        "SBICARD.NS", "MOTILALOFS.NS", "MFSL.NS", "IREDA.NS", "MANAPPURAM.NS", "PNBHOUSING.NS",
        "LICHSGFIN.NS", "BANDHANBNK.NS", "ANGELONE.NS", "CAMS.NS", "KFINTECH.NS", "IEX.NS",
        "BSE.NS", "CDSL.NS",
    ],
    "Healthcare": [
        "SUNPHARMA.NS", "DIVISLAB.NS", "TORNTPHARM.NS", "APOLLOHOSP.NS", "ZYDUSLIFE.NS",
        "CIPLA.NS", "LAURUSLABS.NS", "MAXHEALTH.NS", "AUROPHARMA.NS", "DRREDDY.NS", "LUPIN.NS",
        "MANKIND.NS", "GLENMARK.NS", "FORTIS.NS", "BIOCON.NS", "ALKEM.NS",
    ],
    "Information Technology": [
        "TCS.NS", "INFY.NS", "HCLTECH.NS", "WIPRO.NS", "TECHM.NS", "LTM.NS", "OFSS.NS",
        "PERSISTENT.NS", "COFORGE.NS", "MPHASIS.NS", "TATAELXSI.NS", "SAGILITY.NS",
        "KPITTECH.NS",
    ],
    "Metals & Mining": [
        "ADANIENT.NS", "JSWSTEEL.NS", "HINDZINC.NS", "TATASTEEL.NS", "HINDALCO.NS",
        "JINDALSTEL.NS", "VEDL.NS", "SAIL.NS", "NMDC.NS", "NATIONALUM.NS",
    ],
    "Oil Gas & Consumable Fuels": [
        "RELIANCE.NS", "ONGC.NS", "COALINDIA.NS", "IOC.NS", "BPCL.NS", "GAIL.NS", "OIL.NS",
        "HINDPETRO.NS", "PETRONET.NS",
    ],
    "Power": [
        "ADANIPOWER.NS", "NTPC.NS", "POWERGRID.NS", "ADANIGREEN.NS", "ADANIENSOL.NS",
        "TATAPOWER.NS", "JSWENERGY.NS", "NHPC.NS",
    ],
    "Realty": [
        "DLF.NS", "LODHA.NS", "PHOENIXLTD.NS", "PRESTIGE.NS", "OBEROIRLTY.NS", "GODREJPROP.NS",
    ],
    "Services": [
        "ADANIPORTS.NS", "INDIGO.NS", "GMRAIRPORT.NS", "CONCOR.NS", "DELHIVERY.NS",
    ],
    "Telecommunication": [
        "BHARTIARTL.NS", "IDEA.NS", "INDUSTOWER.NS",
    ],
    "Textiles": [
        "PAGEIND.NS",
    ],
}


# Flat list of every F&O ticker, sector order preserved.
FNO_ALL = [t for syms in FNO_SECTORS.values() for t in syms]

SECTOR_OF = {t: sector for sector, syms in FNO_SECTORS.items() for t in syms}



def _prev_close(r):
    """Previous close implied by the snapshot: price - fulldayChange, falling
    back to price / (1 + pct/100)."""
    price = r.get("price")
    if price is None:
        return None
    pts = r.get("pts")
    if pts is not None:
        prev = price - pts
        return prev if prev > 0 else None
    pct = r.get("pct")
    if pct is None or pct <= -100:
        return None
    prev = price / (1 + pct / 100)
    return prev if prev > 0 else None


def constituent_range(rows):
    """Equal-weighted day range built from the sector's own constituents, for
    groups with no matching NSE sectoral index.

    Each stock's day low and high are expressed as a % move from that stock's
    own previous close, then averaged with equal weight - the same weighting as
    avgPct, so avgPct is always inside [lowPct, highPct] by construction.

    This is an ENVELOPE of the constituents' individual day ranges, not the
    range a real equal-weighted index would have printed: it treats every
    stock's low as simultaneous (and every high likewise), which no index does.
    Read it as "how far the average name in this sector travelled today", and
    label it as such in any UI - never present it as an index.

    A one-constituent sector (Textiles holds only PAGEIND) returns that stock's
    own day range, which is correct - `basis` reports the sample size so the UI
    can say so.
    """
    lows, highs, curs = [], [], []
    for r in rows:
        prev = _prev_close(r)
        if prev is None:
            continue
        lo, hi, pct = r.get("dayLow"), r.get("dayHigh"), r.get("pct")
        if lo is None or hi is None or pct is None:
            continue
        lows.append((lo - prev) / prev * 100)
        highs.append((hi - prev) / prev * 100)
        curs.append(pct)

    if not curs:
        return None
    low_pct = sum(lows) / len(lows)
    high_pct = sum(highs) / len(highs)
    cur_pct = sum(curs) / len(curs)
    if high_pct <= low_pct:
        return None
    return {
        "lowPct": low_pct,
        "highPct": high_pct,
        "curPct": cur_pct,
        "basis": len(curs),
    }


def build_sectors(rows):
    """Group `rows` (from build_rows) by sector and compute per-sector aggregates.

    Aggregates are EQUAL-WEIGHTED across constituents that have data - this is a
    breadth measure of the sector's F&O names, not the official sector index.

    Returns a list of dicts, each: {sector, count, avgPct, up, down, flat, rows}.
    """
    by_sector = {sector: [] for sector in FNO_SECTORS}
    for r in rows:
        sector = SECTOR_OF.get(r["ticker"])
        if sector is not None:
            by_sector[sector].append(r)

    out = []
    for sector, srows in by_sector.items():
        vals = [r["pct"] for r in srows if r.get("pct") is not None]
        avg = sum(vals) / len(vals) if vals else None
        out.append({
            "sector": sector,
            "count": len(srows),
            "avgPct": avg,
            "constituentRange": constituent_range(srows),
            "up": sum(1 for v in vals if v > 0),
            "down": sum(1 for v in vals if v < 0),
            "flat": sum(1 for v in vals if v == 0),
            "rows": sorted(
                srows,
                key=lambda r: (r["pct"] if r.get("pct") is not None else -999),
                reverse=True,
            ),
        })
    return out


# ── Real NSE sectoral indices, mapped onto the watchlist's sector groups ─────
# Only mappings where the index's composition genuinely matches the group are
# listed. Every ticker below was verified to return a live name plus a real
# regularMarketDayHigh/Low. Deliberately NOT mapped, because no NSE index
# matches the group's actual constituents:
#   Capital Goods, Construction, Consumer Services, Power, Services,
#   Telecommunication, Textiles
# Near-misses rejected on composition: Nifty Energy (oil+gas+power blend) for
# Power, Nifty Services Sector (financials/IT/telecom) for Services, Nifty
# Consumption (broad) for Consumer Services, Nifty Infra (broad) for
# Construction. Also rejected as DEAD tickers - they resolve but return no
# shortName and a frozen high==low==price: NIFTY_ENERGY.NS, NIFTY_INFRA.NS,
# NIFTY_CONSUMPTION.NS.
SECTOR_INDICES = {
    "Automobile and Auto Components": {"ticker": "^CNXAUTO", "label": "NIFTY AUTO"},
    "Chemicals": {"ticker": "NIFTY_CHEMICALS.NS", "label": "NIFTY CHEMICALS"},
    "Construction Materials": {"ticker": "NIFTY_CEMENT.NS", "label": "NIFTY CEMENT"},
    "Consumer Durables": {"ticker": "NIFTY_CONSR_DURBL.NS", "label": "NIFTY CONSR DURBL"},
    "Fast Moving Consumer Goods": {"ticker": "^CNXFMCG", "label": "NIFTY FMCG"},
    "Financial Services": {"ticker": "NIFTY_FIN_SERVICE.NS", "label": "NIFTY FIN SERVICE"},
    "Healthcare": {"ticker": "NIFTY_HEALTHCARE.NS", "label": "NIFTY HEALTHCARE"},
    "Information Technology": {"ticker": "^CNXIT", "label": "NIFTY IT"},
    "Metals & Mining": {"ticker": "^CNXMETAL", "label": "NIFTY METAL"},
    "Oil Gas & Consumable Fuels": {"ticker": "NIFTY_OIL_AND_GAS.NS", "label": "NIFTY OIL & GAS"},
    "Realty": {"ticker": "^CNXREALTY", "label": "NIFTY REALTY"},
}

SECTOR_INDEX_TICKERS = {v["ticker"]: s for s, v in SECTOR_INDICES.items()}


def attach_sector_indices(sectors, fetched):
    """Attach the matching sectoral index snapshot to each sector dict.

    `fetched` is {sector_name: {price, pct, pts, dayHigh, dayLow}} as returned by
    fetch_all when given SECTOR_INDEX_TICKERS as its indices_map. Sectors with no
    matching NSE index get index=None, which the UI renders as "no NSE index".
    """
    for s in sectors:
        meta = SECTOR_INDICES.get(s["sector"])
        snap = fetched.get(s["sector"]) if meta else None
        if meta and snap and snap.get("price") is not None:
            s["index"] = dict(snap, label=meta["label"], ticker=meta["ticker"])
        else:
            s["index"] = None
    return sectors
