"""Every closed trade each day-trade channel has posted, one CSV per channel,
so the daily report can show more than today (last 5 days, last week, month).

Rows are appended when the day's report goes out. Days before the ledger
existed are filled with `--backfill`, which replays the channel's live rule
on that day's bars (source = "replay"); 5 Oct 2026 for the day-trade channel
comes from reports/live_corrections.md (source = "corrected").

Usage: python -m src.ledger --backfill daytrade|inplay --start YYYY-MM-DD --end YYYY-MM-DD [--strategy bigtech]
"""
from __future__ import annotations

import argparse
import sys

import pandas as pd

from .config import REPO_ROOT

STATE = REPO_ROOT / "state"
COLS = ["id", "date", "symbol", "side", "entry_time", "exit_time", "entry", "exit", "reason", "pct", "source"]
# Added 15 Oct 2026 for the dashboard's trade explorer: the plan and the setup
# conditions the bots already compute. Rows written before then leave them blank,
# which the dashboard shows as "not recorded" (never as zero).
EXTRA = ["stop", "target", "setup", "level", "rvol", "or_width_atr", "gap_pct", "vwap_ok", "spy_ok"]
ET = "America/New_York"

# 5 Oct 2026, day-trade channel: what was actually posted (reports/live_corrections.md)
CORRECTED = {"daytrade": [
    dict(id="ORB-MSFT-2026-10-05", date="2026-10-05", symbol="MSFT", side="long", entry_time="09:38", exit_time="15:55",
         entry=None, exit=None, reason="bell", pct=-0.69, source="corrected"),
    dict(id="ORB-BAC-2026-10-05", date="2026-10-05", symbol="BAC", side="short", entry_time="09:40", exit_time="10:19",
         entry=None, exit=None, reason="stop", pct=-1.05, source="corrected"),
    dict(id="ORB-NVDA-2026-10-05", date="2026-10-05", symbol="NVDA", side="long", entry_time="09:41", exit_time="15:55",
         entry=None, exit=None, reason="bell", pct=0.35, source="corrected"),
]}


def path(channel: str):
    return STATE / f"ledger_{channel}.csv"


def load(channel: str) -> pd.DataFrame:
    f = path(channel)
    if not f.exists():
        return pd.DataFrame(columns=COLS)
    return pd.read_csv(f, dtype={"id": str, "date": str, "entry_time": str, "exit_time": str})


def append(channel: str, trades: list[dict], date: str, source: str = "live") -> pd.DataFrame:
    """Add the day's closed trades; a trade id already in the ledger is kept as it was."""
    old = load(channel)
    new = [dict(id=t["id"], date=date, symbol=t["symbol"], side=t["side"], entry_time=t.get("entry_time"),
                exit_time=t.get("exit_time"), entry=t.get("entry"), exit=t.get("exit"), reason=t.get("reason"),
                pct=t.get("pct"), source=t.get("source", source),
                stop=t.get("stop"), target=t.get("target"), setup=t.get("setup"), level=t.get("level"),
                rvol=t.get("rvol5", t.get("rvol")), or_width_atr=t.get("or_width_atr"), gap_pct=t.get("gap"),
                vwap_ok=t.get("vwap_ok"), spy_ok=t.get("spy_ok"))
           for t in trades if t.get("exit") is not None and t["id"] not in set(old["id"])]
    out = pd.concat([old, pd.DataFrame(new, columns=COLS + EXTRA)], ignore_index=True) if new else old
    out = out[[c for c in COLS + EXTRA if c in out.columns] + [c for c in out.columns if c not in COLS + EXTRA]]
    out = out.sort_values(["date", "entry_time"], kind="stable")
    STATE.mkdir(exist_ok=True)
    out.to_csv(path(channel), index=False)
    return out


def _replay_day(channel: str, day, strategy: str) -> list[dict]:
    now = pd.Timestamp(f"{day} 16:01", tz=ET)
    if channel == "daytrade":
        from . import orb_live as ol
        from .config import Credentials
        from .data import MarketData
        ol.use(strategy)
        ol.PICKS_FILE = ol.PICKS_FILE.with_name("ledger_replay_picks.json")
        trades, _ = ol.scan(now, lambda: MarketData(Credentials.from_env(), feed="iex"), 1.0, dry_run=True)
        return trades
    from . import inplay_bot as ib
    from .paper import settings
    trades, _, _ = ib.scan(settings(), now)
    return trades


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backfill", choices=["daytrade", "inplay"], required=True)
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--strategy", default="bigtech")
    args = ap.parse_args(argv)
    rows = [r for r in CORRECTED.get(args.backfill, []) if args.start <= r["date"] <= args.end]
    if rows:                       # what was actually posted, not a replay
        old = load(args.backfill)
        keep = [r for r in rows if r["id"] not in set(old["id"])]
        out = pd.concat([old, pd.DataFrame(keep, columns=COLS)], ignore_index=True).sort_values(["date", "entry_time"])
        STATE.mkdir(exist_ok=True)
        out.to_csv(path(args.backfill), index=False)
    done = {r["date"] for r in CORRECTED.get(args.backfill, [])}
    for day in pd.bdate_range(args.start, args.end).date:
        if str(day) in done:
            continue
        trades = _replay_day(args.backfill, day, args.strategy)
        out = append(args.backfill, trades, str(day), source="replay")
        n = sum(1 for t in trades if t.get("exit") is not None)
        print(f"{day}: {n} closed trades, ledger now {len(out)} rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
