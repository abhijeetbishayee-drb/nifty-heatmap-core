"""Corporate-action handling, shared by the heatmap boards and the RRG.

Used from two very different places, and the difference matters:

  HISTORY (the RRG) repairs retrospectively. An event can be added to the table
  long after the fact and the whole series is fixed on the next rebuild.

  LIVE SNAPSHOT (the heatmap boards) gets exactly one chance. A stock's
  ex-date print is wrong for that session only - the next session is right
  again with no intervention - so an entry added the following day buys
  nothing. Entries have to be in the table BEFORE the ex-date to be worth
  anything.
"""

import statistics as st  # noqa: F401  (kept for callers importing from here)
from datetime import date, datetime, timezone


# ── Corporate actions ────────────────────────────────────────────────────
# A demerger or bonus leaves a cliff in the RAW close series that is neither
# risk nor a return. Vedanta printed -64.9% on 2026-04-30 (773.6 -> 271.5)
# because the company became smaller; nobody lost 65% that day. Left raw it
# inflated VEDL's weekly volatility to 96.7% against 29.1% daily, purely
# because the 26-week window still spanned the gap while the 60-day one did
# not. It also distorts relative strength and any basket the name sits in.
#
# These CANNOT be detected automatically. Every obvious rule was tried and
# fails (all measured 2026-09-27):
#   - A size threshold does not work. NSE removes the daily price band for
#     stocks in F&O, so a >25% day is legal and real: ADANIENT -28.2%
#     (Hindenburg, 2023-02-01), INDUSINDBK -27.2% (accounting disclosure,
#     2025-03-11), IEX -29.6% (market-coupling ruling, 2025-07-24) must NOT be
#     smoothed away.
#   - Yahoo's adjclose does not work: it gaps by exactly the same amount as
#     close on every one of these, corporate action or not.
#   - Yahoo's split records do not work: they exist for some, but the DATE is
#     wrong. Yahoo puts all three bonus/split gaps below on 1 January of some
#     year, months from the real record date.
#
# So the events are listed explicitly, checked against company announcements,
# and matched into the series by RATIO rather than by date - the ratio is the
# one thing both sources agree on. CORP_ACTION_JUMP is only a safety net that
# reports unclassified gaps so this stays maintainable instead of going stale.
CORP_ACTION_JUMP = 0.25
RATIO_TOL = 0.03          # the stock also trades on the event day

# COSMETIC vs ECONOMIC decides whether adjusting is enough:
#   cosmetic (split, bonus) - the share count changed and nothing else. Same
#     business, same economics, exact ratio. Back-adjusted history is
#     genuinely what the stock would have printed and stays comparable to its
#     peers. Adjust and carry on.
#   economic (demerger, spin-off) - the COMPANY changed. Post-demerger VEDL is
#     a smaller, different business from pre-demerger Vedanta, so no amount of
#     arithmetic makes its pre-event history describe the thing now being
#     plotted. A continuous series would just be a confident wrong number, and
#     an RRG exists to compare securities to each other - the same objection as
#     the normalisation trap above. So usable history STARTS at the event, and
#     the name is excluded until it has enough of its own, exactly as any other
#     short-history symbol is. That clears itself as the window rolls forward.
#
# Verified against company announcements on 2026-09-27; `date` is the real
# record/ex date, which is NOT where Yahoo puts the gap for the cosmetic ones.
CORPORATE_ACTIONS = {
    "VEDL.NS":       {"what": "Vedanta 5-way demerger", "kind": "economic",
                      "date": "30 Apr 2026", "exDate": "2026-04-30",
                      "ratio": 0.351},
    "TMPV.NS":       {"what": "Tata Motors demerger", "kind": "economic",
                      "date": "14 Oct 2025", "exDate": "2025-10-14",
                      "ratio": 0.599},
    "MOTILALOFS.NS": {"what": "3:1 bonus", "kind": "cosmetic",
                      "date": "10 Jun 2024", "exDate": "2024-06-10",
                      "ratio": 0.25},
    "PARAS.NS":      {"what": "1:2 split", "kind": "cosmetic",
                      "date": "4 Jul 2025", "exDate": "2025-07-04",
                      "ratio": 0.50},
    "TRENT.NS":      {"what": "1:2 bonus", "kind": "cosmetic",
                      "date": "4 Jun 2026", "exDate": "2026-06-04",
                      "ratio": 2.0 / 3.0},
}


def _iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d")


def apply_corporate_actions(dates, values, spec):
    """Repair a close series for one ticker's listed corporate action.

    Returns (values, start_offset, note, unreviewed):
      cosmetic - everything before the event is rebased onto the post-event
                 basis by the gap ratio; start_offset stays 0.
      economic - the series is TRUNCATED to begin at the event, because the
                 pre-event bars belong to a different company. start_offset is
                 where it now begins, and the ordinary minimum-history rule
                 then excludes the name until it has enough of its own bars.
      unreviewed - gaps over the threshold that match no listed action, so the
                 build can report them rather than silently guessing.
    """
    unreviewed, hits = [], []
    for i in range(1, len(values)):
        prev, cur = values[i - 1], values[i]
        if not prev or not cur or abs(cur / prev - 1) < CORP_ACTION_JUMP:
            continue
        ratio = cur / prev
        if spec and abs(ratio - spec["ratio"]) <= RATIO_TOL * spec["ratio"]:
            hits.append((i, ratio))
        else:
            unreviewed.append((_iso(dates[i]), round(100 * (ratio - 1), 1)))
    if not hits:
        return list(values), 0, None, unreviewed

    note = {"what": spec["what"], "kind": spec["kind"], "date": spec["date"]}
    if spec["kind"] == "economic":
        idx = hits[-1][0]
        note["since"] = len(values) - idx
        return list(values[idx:]), idx, note, unreviewed

    out = list(values)
    for i, ratio in hits:
        for j in range(i):
            out[j] *= ratio
    note["since"] = len(values) - hits[-1][0]
    return out, 0, note, unreviewed


# ── Live snapshot ────────────────────────────────────────────────────────
# A snapshot carries no history, so the test is different: the print must be
# too large to be a day's trading AND must collapse to a plausible day's move
# once the listed ratio is divided out.
#
# Both halves are needed. Without the first, a ratio near 1 would fire on an
# ordinary session; without the second, any large move would be treated as a
# corporate action - which is exactly the mistake that would erase a real
# crash. Note the consequence: an action too small to clear MIN_LIVE_GAP
# cannot be detected live at all. Every action in the table today gaps at
# least 33%, so this is a limit on what may be ADDED, not on what is handled.
MIN_LIVE_GAP = 0.15    # the raw print must be impossible as a day's trading
MAX_DAY_MOVE = 0.25    # what the name may genuinely have done on the ex-date
EX_DATE_SLACK = 3      # days, to absorb record-date vs ex-date drift


def live_adjustment(ticker, price, prev, today=None):
    """Return the corrected reading for a name trading ex a corporate action.

    `prev` is the previous close implied by the snapshot, which on an ex-date
    is the UNADJUSTED prior close - verified 2026-09-27 that Yahoo does not
    adjust it, so VEDL's snapshot on 2026-04-30 prints -64.9%.

    Returns None unless every guard passes, because a false positive here is
    worse than the problem: it would quietly rewrite a genuine crash, and a
    crash is the single most important thing these boards show. Guards are the
    listed ex-date (within EX_DATE_SLACK days), a raw print too large to trade,
    and a residual move that is plausible for one session.
    """
    spec = CORPORATE_ACTIONS.get(ticker)
    if not spec or not price or not prev or price <= 0 or prev <= 0:
        return None

    ex = spec.get("exDate")
    if ex:
        today = today or datetime.now(timezone.utc).date()
        if abs((today - date.fromisoformat(ex)).days) > EX_DATE_SLACK:
            return None

    raw = price / prev
    if abs(raw - 1) < MIN_LIVE_GAP:
        return None
    ratio = spec["ratio"]
    if abs(raw / ratio - 1) > MAX_DAY_MOVE:
        return None

    out = {"what": spec["what"], "kind": spec["kind"], "date": spec["date"],
           "rawPct": 100 * (raw - 1), "pct": None, "pts": None}

    # Only a COSMETIC action has an adjusted price that means anything. Its
    # ratio comes from the announced terms - 3:1 bonus is exactly 1/4, a 1:2
    # bonus exactly 2/3 - so dividing it out leaves the move the stock really
    # made: Trent +0.43% on a day the raw print said -33.0%. That is
    # independent evidence and worth showing.
    #
    # A demerger has no such ratio. What the parent is "worth" ex-event is
    # discovered by the market across all the resulting entities, which is why
    # exchanges run a special price-discovery session for it. The only ratio
    # available is the one read off the gap itself, so an adjusted percentage
    # would be ~0 by construction - the input echoed back, not a measurement.
    # It stays None, and the boards show NA, exactly as the RRG excludes the
    # name for the same underlying reason: the company changed.
    if spec["kind"] == "cosmetic":
        adj_prev = prev * ratio
        out["pct"] = 100 * (price / adj_prev - 1)
        out["pts"] = price - adj_prev
    return out


# ── Build-time warnings ──────────────────────────────────────────────────
# The live path only works if an event is in the table BEFORE its ex-date, so
# the table going stale is the one failure mode that silently disables it.
# These emit nothing on an ordinary day - the price build runs every minute
# and a standing message would be scrolled past and stop being read.
UPCOMING_HORIZON = 10          # calendar days of notice


def upcoming(today=None, horizon=UPCOMING_HORIZON):
    """(ticker, spec, days_away) for listed actions due within `horizon`."""
    today = today or datetime.now(timezone.utc).date()
    out = []
    for ticker, spec in CORPORATE_ACTIONS.items():
        ex = spec.get("exDate")
        if not ex:
            continue
        days = (date.fromisoformat(ex) - today).days
        if 0 <= days <= horizon:
            out.append((ticker, spec, days))
    return sorted(out, key=lambda x: x[2])


def armed(today=None):
    """Listed actions still in the future - what the table actually protects
    against. An all-historical table protects against nothing."""
    today = today or datetime.now(timezone.utc).date()
    return [(t, s) for t, s in CORPORATE_ACTIONS.items()
            if s.get("exDate") and date.fromisoformat(s["exDate"]) > today]


def live_warnings(rows, today=None, horizon=UPCOMING_HORIZON):
    """Lines a live build should print. Empty when nothing needs attention.

    Three things are worth saying, and nothing else:
      UPCOMING - an ex-date is near, so the entry can still be checked while
                 there is time to correct it
      APPLIED  - an adjustment fired, so the change on the board is explained
      MISSED   - an ex-date is TODAY and nothing fired, which means the entry
                 is wrong (ratio or date) and the board is showing the raw
                 cliff right now. The observed move is included so the ratio
                 can be corrected from the log alone.
    """
    today = today or datetime.now(timezone.utc).date()
    by_ticker = {r.get("ticker"): r for r in rows or []}
    lines = []

    for ticker, spec, days in upcoming(today, horizon):
        if days == 0:
            continue
        lines.append(
            f"  UPCOMING: {ticker} goes ex {spec['what']} in {days} day(s) "
            f"({spec['exDate']}, ratio {spec['ratio']:.4f}, {spec['kind']}). "
            + ("An adjusted % will be shown." if spec["kind"] == "cosmetic"
               else "It will read NA and leave its sector average."))

    for ticker, spec in CORPORATE_ACTIONS.items():
        row = by_ticker.get(ticker)
        if row is None:
            continue
        ca = row.get("ca")
        ex = spec.get("exDate")
        if ca:
            shown = (f"adjusted to {row['pct']:+.2f}%" if ca.get("adjusted")
                     else "NA")
            note = "" if ex == str(today) else f" (listed ex-date {ex})"
            lines.append(f"  APPLIED: {ticker} ex {spec['what']} — raw "
                         f"{ca['rawPct']:+.2f}% shown as {shown}{note}")
        elif ex == str(today):
            pct = row.get("pct")
            seen = f"{pct:+.2f}%" if pct is not None else "no quote"
            lines.append(
                f"  MISSED: {ticker} is listed ex {spec['what']} TODAY "
                f"({ex}) but no adjustment fired — the board is showing the "
                f"raw print. Observed {seen} against an expected ratio of "
                f"{spec['ratio']:.4f}; check the date and the ratio.")
    return lines


def table_status(today=None):
    """One-line summary for a daily build: is anything actually armed?"""
    today = today or datetime.now(timezone.utc).date()
    live = armed(today)
    if live:
        nxt = min(live, key=lambda x: x[1]["exDate"])
        return (f"corporate-action table: {len(CORPORATE_ACTIONS)} entries, "
                f"{len(live)} still ahead; next {nxt[0]} on {nxt[1]['exDate']}")
    return (f"corporate-action table: {len(CORPORATE_ACTIONS)} entries, all "
            "historical — history is repaired, but nothing is armed for a "
            "future ex-date, so a new action would print raw on the day. "
            "Entries must be added BEFORE the ex-date to have any effect.")
