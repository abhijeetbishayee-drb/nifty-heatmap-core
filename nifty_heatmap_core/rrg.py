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
# THE COMMON WINDOW IS SET BY THE SHORTEST HISTORY WE CHOOSE TO ADMIT, and
# that is a real trade, not a free parameter. Every symbol shares one window
# (see THE NORMALISATION TRAP below), so admitting a recent listing shortens
# the window for EVERYBODY.
#
# daily norm was 250 and is 150, taken deliberately on 2026-09-27 to admit
# MEESHO (201 bars, listed 2025-12-10) and LENSKART (223, 2025-11-10):
#   min_bars = n_long 30 + norm + tail 12, so norm 150 needs 192 bars.
# Measured cost of the change across the 222 names on both boards: 27 changed
# quadrant, but ALL 27 sat within 0.50 of an axis and 25 within 0.30 - median
# distance to the nearest axis 0.069 for the flippers against 0.358 for
# everyone else. So the reshuffle is confined to names hovering on the
# crosshair, whose quadrant was never a firm claim; nothing deep in a quadrant
# moved. Median |RS-Ratio| shift 0.198, p90 0.472.
#
# The floor this sets: admitting anything shorter than ~192 bars means cutting
# norm again for all 227 names. VAML (75 bars) and post-demerger VEDL (103)
# are below it and stay out by design.
DAILY = {"n_short": 10, "n_long": 30, "norm": 150, "tail": 12,
         "vol_win": 60, "ann": 252, "ret_win": 12}
# WEEKLY is unchanged, and no window would help a 2025 listing here: n_long
# is 30 WEEKS, so a symbol needs n_long + tail = 42 weekly bars before any
# normalisation window at all. MEESHO has ~40 and LENSKART ~44. Even norm=0
# would not admit MEESHO, so the recent listings are a daily-only affair and
# the weekly board honestly says so rather than drawing them on a stub.
WEEKLY = {"n_short": 10, "n_long": 30, "norm": 100, "tail": 12,
          "vol_win": 26, "ann": 52, "ret_win": 12}


# Corporate actions live in their own module: they are shared with the
# heatmap boards, which need the LIVE path rather than the history one.
from .corporate_actions import (  # noqa: F401  (re-exported)
    CORP_ACTION_JUMP, CORPORATE_ACTIONS, RATIO_TOL,
    apply_corporate_actions, live_adjustment,
)


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


# ── Outlier constituents ─────────────────────────────────────────────────
# An equal-weighted basket is one name away from being a story about that one
# name: POLICYBZR fell 36% on the IRDAI commission paper (2026-09-24) and
# dragged a 7-member New Age basket from -2.1% to -5.3% by itself. The
# ex-outlier variant answers the other question - what the REST of the sector
# is doing - without hiding anything: the outlier keeps its own point on the
# stocks view either way.
#
# TWO tests, and each one exists because the other fails alone. Measured
# across all 23 sectors on 2026-09-27:
#
#  1. SECTOR test, 3 MAD from the sector median. Alone it flagged 22 names in
#     13 sectors, including HDFCBANK, RELIANCE, ULTRACEMCO, HCLTECH and
#     TECHM. MAD collapses in a tightly clustered sector (Information
#     Technology 1.18, Construction Materials 0.44), so "3 MAD" becomes a
#     couple of percent and perfectly ordinary names fall outside it.
#
#  2. BOARD test, 4 robust sigma from the median of every constituent on the
#     board for that timeframe. This is the scale check, and it must be
#     CALIBRATED FROM THE DATA rather than hard-coded. A fixed 15-point floor
#     worked on daily and then flagged 8 of 23 sectors on weekly, because a
#     12-week return is spread about 2.3x wider than a 12-day one - the same
#     class of mistake as normalising two symbols over different windows.
#     Deriving the floor from the board's own dispersion fixes that: it comes
#     out at 16.0 points on daily and 36.2 on weekly, automatically.
#
# Together they leave 2 names of 225 on daily (POLICYBZR -36.1% against a
# -2.1% sector median, next nearest -3.9%; PATANJALI +18.1% against +0.5%,
# next nearest +7.2%) and 2 of 215 on weekly (CYIENTDLM +82.8%, KALYANKJIL
# +50.0%). The choice of 4 sigma is not delicate - 3.0 to 4.5 all give the
# same answer on daily. The rule is symmetric, so it catches the upside
# outliers too, and the variant is IDENTICAL to the ordinary basket in 21 of
# 23 sectors, which is what makes it worth showing: it differs only where
# there is genuinely something to see.
OUTLIER_SECTOR_MAD = 3.0
OUTLIER_BOARD_SIGMA = 4.0
MAD_TO_SIGMA = 1.4826       # normal-consistent estimator


def _mad(vals):
    m = st.median(vals)
    return st.median([abs(v - m) for v in vals])


def outlier_indices(returns, board_returns,
                    k_sector=OUTLIER_SECTOR_MAD, k_board=OUTLIER_BOARD_SIGMA,
                    min_gap=0.0):
    """Positions of constituents doing something categorically different.

    `returns` is one trailing return per constituent over the window the
    basket covers; `board_returns` is the same measure for every constituent
    on the board, which is what makes the scale test transfer between daily
    and weekly. None entries are ignored and never flagged. Needs at least
    four usable values, below which "the median constituent" means nothing.

    `min_gap` is an extra absolute floor in the same units, for callers whose
    dispersion is too STABLE for a derived threshold to mean anything - the
    heatmap boards, see HEATMAP_MIN_GAP. It is measured against the SECTOR
    median, not the board's: the concern is one name dragging its own peers,
    and when a whole sector moves together nobody should be flagged. Measured
    against the board median instead, a sector-wide 16% fall would have
    flagged its most extreme member for no good reason.
    """
    usable = [(i, r) for i, r in enumerate(returns) if r is not None]
    board = [r for r in board_returns if r is not None]
    if len(usable) < 4 or len(board) < 20:
        return []
    vals = [r for _, r in usable]
    med, spread = st.median(vals), _mad(vals)
    b_med, b_sigma = st.median(board), _mad(board) * MAD_TO_SIGMA
    if spread <= 0 or b_sigma <= 0:
        return []
    return [i for i, r in usable
            if abs(r - med) > k_sector * spread
            and abs(r - b_med) > k_board * b_sigma
            and abs(r - med) >= min_gap]


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


# The live heatmap boards average a SINGLE SESSION's change, and that needs a
# different scale test from the RRG's multi-period returns. Measured on the
# live board 2026-09-27: session dispersion is small and stable - robust sigma
# 0.99 points across 227 names - so the derived 4-sigma threshold comes out at
# only 3.98 points and flags whatever happened to fall furthest that day
# (FORTIS -4.5%, MEESHO -6.8%). Those are the day's biggest movers, which is
# precisely what the board exists to show; stripping them would repeat the
# mistake of "fixing" a real crash.
#
# So intraday takes an absolute floor instead, calibrated on 112,164
# close-to-close sessions over 2 years across all 227 names:
#     6pp fires 3.82 times a trading day      15pp fires 0.12
#     8pp            1.35                     20pp            0.03
#    10pp            0.56                     25pp            0.01
# 15 points fires about once every eight sessions - rare enough to mean
# something, and comfortably below the genuine events it must catch, all of
# which cleared 22%: POLICYBZR -36.0% (IRDAI commission paper), IEX -29.6%
# (market coupling), INDUSINDBK -27.2% (accounting), ADANIENT -22.6%
# (Hindenburg). Corporate-action gaps never reach this test - they are
# repaired upstream in corporate_actions.py.
#
# The sector test still applies and does real work here: when a WHOLE sector
# moves together - PSU banks on an election result - no name diverges from its
# peers, nothing is flagged, and the average correctly stands.
HEATMAP_MIN_GAP = 15.0
