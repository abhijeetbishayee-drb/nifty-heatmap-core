#!/usr/bin/env python3
"""Rewrite NIFTY50 in __init__.py from NSE's own published constituent list.

WHY THIS EXISTS
---------------
NIFTY50 was hardcoded and never reconciled against NSE. By 2026-10-06 nine of
the fifty were wrong in both directions -- the board carried BPCL, BRITANNIA,
DIVISLAB, HEROMOTOCO, INDUSINDBK, LTM, TVSMOTOR, UPL and WIPRO, none of which
are in the index, and omitted BEL, BSE, ETERNAL, INDIGO, JIOFIN, MAXHEALTH,
SHRIRAMFIN, TMPV and TRENT, all of which are. Every gainer/loser ranking and
breadth count on that board was therefore computed over the wrong 50, and the
error was invisible because a wrong-but-live ticker renders exactly like a
right one. LTM is not even an NSE symbol; it resolved on Yahoo at a plausible
price and sat there unnoticed.

NSE reconstitutes semi-annually, so a list maintained by hand is a list that
is wrong for most of its life. This script replaces the memory of a human with
NSE's own file -- the same archive path, with the same plain User-Agent, that
nifty-ema-board's build_universe.py already relies on.

WHY IT REWRITES SOURCE RATHER THAN FETCHING AT IMPORT
-----------------------------------------------------
Consumers import NIFTY50 as a module constant, and one of them (pnf-charts)
does not import this package at all -- it AST-parses this file over HTTP to
avoid pulling in our runtime deps. A literal in the source is the only form
that serves all of them, and it keeps the universe diffable in review: a
reconstitution shows up as a commit, not as a silent change of behaviour.

VALIDATION IS FAIL-LOUD, AND NOTHING PARTIAL IS EVER WRITTEN
------------------------------------------------------------
Every check below must pass before the file is touched. A bad or truncated
NSE response leaves the committed list exactly as it was -- the board stays
correct-as-of-yesterday rather than becoming wrong today.
"""
from __future__ import annotations

import ast
import csv
import io
import re
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / "nifty_heatmap_core" / "__init__.py"
SRC = "https://nsearchives.nseindia.com/content/indices/ind_nifty50list.csv"

# Archive CSVs serve to a plain browser UA; only www.nseindia.com/api/* needs
# the Playwright route. Same finding as nifty-ema-board/scripts/build_universe.
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

SYMBOL_OK = re.compile(r"^[A-Z0-9&-]{1,20}$")
PER_LINE = 5


def fetch() -> list[str]:
    r = requests.get(SRC, headers={"User-Agent": UA, "Accept": "text/csv,*/*"},
                     timeout=30)
    r.raise_for_status()
    rows = list(csv.DictReader(io.StringIO(r.text)))
    if not rows:
        sys.exit("NSE returned no rows")
    key = next(c for c in rows[0] if "Symbol" in c)
    return [x[key].strip() for x in rows if x[key].strip()]


def validate(syms: list[str]) -> None:
    """Refuse to write anything that is not recognisably the NIFTY 50."""
    sys.path.insert(0, str(ROOT))
    from nifty_heatmap_core import FNO_ALL                     # noqa: PLC0415
    from nifty_heatmap_core.company_names import COMPANY_NAMES  # noqa: PLC0415

    problems = []
    if len(syms) != 50:
        problems.append(f"expected 50 constituents, NSE gave {len(syms)}")
    if len(set(syms)) != len(syms):
        problems.append("duplicate symbols in the NSE list")
    bad = [s for s in syms if not SYMBOL_OK.match(s)]
    if bad:
        problems.append(f"symbols that do not look like NSE tickers: {bad}")

    # The documented invariant: NIFTY50 is a strict subset of FNO_ALL, which is
    # what lets one Yahoo sweep feed every board. A newcomer missing from the
    # sector taxonomy must be placed by hand -- guessing its sector here would
    # put a name on the RRG in the wrong group.
    fno = {t.replace(".NS", "") for t in FNO_ALL}
    orphans = sorted(set(syms) - fno)
    if orphans:
        problems.append(
            f"not in FNO_SECTORS, add them to a sector first: {orphans}")

    # A name with no mapping renders as a bare ticker, which is how LTM hid.
    unnamed = sorted(s for s in syms if s not in COMPANY_NAMES)
    if unnamed:
        problems.append(f"no company name mapped: {unnamed}")

    if problems:
        sys.exit("NIFTY 50 refresh REFUSED:\n  - " + "\n  - ".join(problems))


def render(syms: list[str]) -> str:
    lines = []
    for i in range(0, len(syms), PER_LINE):
        chunk = ", ".join(f'"{s}.NS"' for s in syms[i:i + PER_LINE])
        lines.append(f"    {chunk},")
    return "NIFTY50 = [\n" + "\n".join(lines) + "\n]"


def main() -> int:
    syms = fetch()
    validate(syms)

    text = TARGET.read_text()
    old = next((n for n in ast.parse(text).body
                if isinstance(n, ast.Assign)
                and any(getattr(t, "id", None) == "NIFTY50" for t in n.targets)),
               None)
    if old is None:
        sys.exit("NIFTY50 assignment not found in __init__.py")

    before = [e.value.replace(".NS", "") for e in old.value.elts]
    if before == syms:
        print(f"NIFTY 50 unchanged ({len(syms)} names)")
        return 0

    lines = text.splitlines(keepends=True)
    head = "".join(lines[:old.lineno - 1])
    tail = "".join(lines[old.end_lineno:])
    TARGET.write_text(head + render(syms) + "\n" + tail)

    gone, came = sorted(set(before) - set(syms)), sorted(set(syms) - set(before))
    print(f"NIFTY 50 updated: -{len(gone)} +{len(came)}")
    for s in gone: print(f"  out  {s}")
    for s in came: print(f"  in   {s}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
