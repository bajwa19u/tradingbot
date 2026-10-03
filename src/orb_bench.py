"""How long the live in-play ORB signal takes to produce, on real Alpaca data.

Replays one past session through the exact live code path (orb_live.scan)
with the clock pinned, timing each stage, once with the old one-request-at-a-
time warm-up and once with the parallel one. Nothing is posted or written
outside reports/orb_bench.md.

Usage: python -m src.orb_bench [--date YYYY-MM-DD]
"""
from __future__ import annotations

import argparse
import sys
import tempfile
import time
from pathlib import Path

import pandas as pd

from . import orb_live as ol
from . import orb_paper as op
from .config import REPO_ROOT, Credentials
from .data import MarketData

REPORT = REPO_ROOT / "reports" / "orb_bench.md"
DEFAULT = (op.WORKERS, op.CHUNK)            # the live settings
ET = "America/New_York"


def at(day, hms):
    return pd.Timestamp(f"{day} {hms}", tz=ET)


def timed(fn):
    t0 = time.perf_counter()
    out = fn()
    return time.perf_counter() - t0, out


def scenario(day, workers: int, chunk: int) -> dict:
    op.WORKERS, op.CHUNK = workers, chunk
    md = lambda: MarketData(Credentials.from_env(), feed="iex")
    res = {}
    # a normal morning: warm-up before the bell, then the ticks
    ol._FEED, ol.PICKS_FILE = None, Path(tempfile.mkdtemp()) / "p.json"
    res["warm-up before the bell"], _ = timed(lambda: ol.warm(at(day, "09:20:00"), md))
    res["09:36 tick (picks the 10 + first check)"], (t1, _) = timed(lambda: ol.scan(at(day, "09:36:04"), md, 1.0, dry_run=True))
    res["09:40 tick"], _ = timed(lambda: ol.scan(at(day, "09:40:04"), md, 1.0, dry_run=True))
    res["09:59 tick"], (t3, _) = timed(lambda: ol.scan(at(day, "09:59:04"), md, 1.0, dry_run=True))
    res["15:56 tick (managing exits)"], _ = timed(lambda: ol.scan(at(day, "15:56:04"), md, 1.0, dry_run=True))
    # a job that started late: no warm-up, first tick at 09:45 does everything
    ol._FEED, ol.PICKS_FILE = None, Path(tempfile.mkdtemp()) / "p.json"
    res["late start: first tick at 09:45, cold"], (t4, _) = timed(lambda: ol.scan(at(day, "09:45:04"), md, 1.0, dry_run=True))
    res["_signals"] = len(t3)
    return res


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default="")
    args = ap.parse_args(argv)
    day = pd.Timestamp(args.date).date() if args.date else (pd.Timestamp.now(tz=ET) - pd.offsets.BDay(1)).date()
    before = scenario(day, workers=1, chunk=25)
    after = scenario(day, workers=DEFAULT[0], chunk=DEFAULT[1])
    L = ["# In-play ORB signal speed", "",
         f"Session replayed: {day}, real Alpaca IEX data, on a GitHub runner. {after['_signals']} signals that morning.", "",
         "| stage | before (seconds) | after (seconds) |", "|---|---|---|"]
    for k in before:
        if not k.startswith("_"):
            L.append(f"| {k} | {before[k]:.1f} | {after[k]:.1f} |")
    L += ["", "A signal's bar closes on the minute; the bot checks 4 seconds later, so a check's time is roughly "
          "how long after the bar a signal is ready (plus Discord, about half a second)."]
    out = "\n".join(L) + "\n"
    REPORT.parent.mkdir(exist_ok=True)
    REPORT.write_text(out)
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
