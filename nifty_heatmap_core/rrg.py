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
DAILY = {"n_short": 10, "n_long": 30, "norm": 250, "tail": 12}
WEEKLY = {"n_short": 10, "n_long": 30, "norm": 100, "tail": 12}


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
