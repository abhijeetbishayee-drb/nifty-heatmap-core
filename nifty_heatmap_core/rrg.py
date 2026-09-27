"""Relative Rotation Graph maths for the heatmap universe.

Plots each security against a benchmark on two axes:
  X = RS-Ratio     relative strength vs the benchmark
  Y = RS-Momentum  rate of change of that relative strength
both centred on 100, giving the four quadrants
Leading (RS>100, Mom>100) / Weakening (RS>100, Mom<100) /
Lagging (RS<100, Mom<100) / Improving (RS<100, Mom>100).

IMPORTANT - this is NOT the licensed JdK RS-Ratio/RS-Momentum. Those are
proprietary to RRG Research. What follows is the commonly published
approximation: relative strength, smoothed with a short and a long SMA, then
z-scored onto a 100-centred scale. Quadrants and rotation behave correctly, but
the numbers will not tie out against a Bloomberg/Optuma RRG.

THE NORMALISATION TRAP, and why every symbol uses the same window:
a z-score depends on the window it is taken over, so the SAME stock on the SAME
day lands in a different spot if you normalise it over a different amount of
history. Measured on 2026-09-26: TCS printed RS-Ratio 99.53 normalised over
~490 bars but 98.70 over 75; ITC 101.37 vs 102.52. Both kept their quadrant,
but a name sitting near the crosshair would not have. An RRG exists to compare
securities against each other on one chart, so comparing points normalised over
different windows is meaningless. Hence: one fixed window for everybody, and
any symbol without that much history is EXCLUDED rather than plotted on a
shorter window.
"""

import statistics as st
from datetime import datetime, timezone

# n_short / n_long smooth the relative-strength line; norm is the common
# z-score window; tail is how many trailing points the chart draws.
# vol_win / ann drive the Z axis of the 3D view: trailing realised volatility
# over vol_win bars, annualised by sqrt(ann).
DAILY = {"n_short": 10, "n_long": 30, "norm": 250, "tail": 12,
         "vol_win": 60, "ann": 252, "ret_win": 12}
WEEKLY = {"n_short": 10, "n_long": 30, "norm": 100, "tail": 12,
          "vol_win": 26, "ann": 52, "ret_win": 12}


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
                      "date": "30 Apr 2026", "ratio": 0.351},
    "TMPV.NS":       {"what": "Tata Motors demerger", "kind": "economic",
                      "date": "14 Oct 2025", "ratio": 0.599},
    "MOTILALOFS.NS": {"what": "3:1 bonus", "kind": "cosmetic",
                      "date": "10 Jun 2024", "ratio": 0.25},
    "PARAS.NS":      {"what": "1:2 split", "kind": "cosmetic",
                      "date": "4 Jul 2025", "ratio": 0.50},
    "TRENT.NS":      {"what": "1:2 bonus", "kind": "cosmetic",
                      "date": "4 Jun 2026", "ratio": 2.0 / 3.0},
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


def min_bars(cfg):
    """Bars a symbol must have before it can be placed on a common scale."""
    return cfg["n_long"] + cfg["norm"] + cfg["tail"]


def to_weekly(dates, closes):
    """Last close of each ISO week."""
    out_d, out_c, cur = [], [], None
    for d, c in zip(dates, closes):
        key = datetime.fromtimestamp(d, timezone.utc).isocalendar()[:2]
        if key != cur:
            out_d.append(d)
            out_c.append(c)
            cur = key
        else:
            out_d[-1], out_c[-1] = d, c
    return out_d, out_c


def _sma(seq, n, i):
    return sum(seq[i - n + 1:i + 1]) / n


def rrg_tail(values, bench, cfg):
    """Return the last `tail` (rs_ratio, rs_momentum) points, or None if the
    series is too short to normalise on the common window.

    `values` and `bench` must already be aligned on the same dates.
    """
    n_s, n_l, norm, tail = cfg["n_short"], cfg["n_long"], cfg["norm"], cfg["tail"]
    if len(values) < min_bars(cfg) or len(values) != len(bench):
        return None

    rs = [100.0 * v / b for v, b in zip(values, bench) if b]
    if len(rs) < min_bars(cfg):
        return None

    # relative strength, smoothed short vs long
    raw = [100 * ((_sma(rs, n_s, i) - _sma(rs, n_l, i)) / _sma(rs, n_l, i) + 1)
           for i in range(n_l - 1, len(rs))]

    # One z-score transform per symbol, taken over the SAME number of most
    # recent observations for every symbol, then applied to the whole tail so
    # the trail stays internally consistent.
    win = raw[-norm:]
    m, sd = st.mean(win), st.pstdev(win) or 1e-9
    ratio = [100 + (v - m) / sd for v in raw]

    mom_raw = [ratio[i] / ratio[i - 1] * 100 for i in range(1, len(ratio))]
    win_m = mom_raw[-norm:]
    m2, sd2 = st.mean(win_m), st.pstdev(win_m) or 1e-9
    mom = [100 + (v - m2) / sd2 for v in mom_raw]

    n = min(tail, len(ratio) - 1, len(mom))
    if n < 2:
        return None
    return [(round(r, 3), round(q, 3)) for r, q in zip(ratio[-n:], mom[-n:])]


def vol_tail(values, cfg, n):
    """Trailing annualised realised volatility, as a % , for the last `n` bars.

    One value per RRG tail point rather than a single headline number, so a 3D
    trail moves on the volatility axis too instead of implying that volatility
    was constant across the tail.

    Returns None if there is not enough history for a full window at every
    point - a partial window would make the earliest tail points noisier than
    the latest ones, which is the same window-comparability problem the module
    docstring describes for the z-score.
    """
    win, ann = cfg["vol_win"], cfg["ann"]
    rets = [values[i] / values[i - 1] - 1
            for i in range(1, len(values)) if values[i - 1]]
    if len(rets) < win + n - 1:
        return None
    out = []
    for end in range(len(rets) - n + 1, len(rets) + 1):
        w = rets[end - win:end]
        out.append(round(100 * st.pstdev(w) * (ann ** 0.5), 2))
    return out


def ret_tail(values, cfg, n):
    """Trailing absolute (not relative) return over ret_win bars, as a %, for
    the last `n` bars.

    This is the one thing an RRG structurally cannot show. RS-Ratio and
    RS-Momentum are both RELATIVE to the benchmark, so a security can sit deep
    in the Leading quadrant while losing money - it is simply falling more
    slowly than the index. Plotting absolute return on the third axis puts that
    back on the chart: the sign says whether the relative strength was worth
    holding.

    Window matches cfg["ret_win"] so the number covers the same stretch the
    RRG tail is drawn over.
    """
    win = cfg["ret_win"]
    if len(values) < win + n:
        return None
    out = []
    for end in range(len(values) - n, len(values)):
        base = values[end - win]
        if not base:
            return None
        out.append(round(100 * (values[end] / base - 1), 2))
    return out


def equal_weight_series(series_list):
    """Synthetic equal-weighted index from constituent close series that are
    already aligned on identical dates. Each constituent is rebased to 100 at
    the start so a high-priced stock does not dominate, then averaged.

    Used for sector groups that have no real NSE sectoral index - the same
    reasoning as the heatmap's constituent-derived range, and it must be
    labelled as synthetic wherever it is drawn.
    """
    series_list = [s for s in series_list if s and s[0]]
    if not series_list:
        return None
    n = min(len(s) for s in series_list)
    series_list = [s[-n:] for s in series_list]
    out = []
    for i in range(n):
        vals = [100.0 * s[i] / s[0] for s in series_list if s[0]]
        out.append(sum(vals) / len(vals))
    return out


def quadrant(ratio, mom):
    if ratio >= 100:
        return "Leading" if mom >= 100 else "Weakening"
    return "Improving" if mom >= 100 else "Lagging"
