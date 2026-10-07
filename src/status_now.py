"""Where both day-trade channels stand right now: every trade today, closed
results, and open trades marked to the latest one-minute close. Prints only;
posts nothing and writes nothing.

Usage: python -m src.status_now   (DAYTRADE_STRATEGY decides the day-trade rule)
"""
from __future__ import annotations

import sys

import pandas as pd

from . import inplay_bot as ib
from . import live_bot as lb
from . import orb_live as ol
from .config import Credentials
from .data import MarketData
from .paper import settings

ET = "America/New_York"


def marks(trades: list[dict], now: pd.Timestamp) -> dict[str, float]:
    syms = sorted({t["symbol"] for t in trades if t["exit"] is None})
    if not syms:
        return {}
    got = MarketData(Credentials.from_env(), feed="iex").intraday_bars(syms, 1, start=str(now.date()))
    return {s: float(df.close.iloc[-1]) for s, df in got.items() if len(df)}


def block(name: str, trades: list[dict], last: dict[str, float]) -> str:
    L = [f"## {name}", ""]
    if not trades:
        return "\n".join(L + ["No trades today.", ""])
    L += ["| ticker | side | in | out | entry | stop | target | exit / last | status | result |", "|---|---|---|---|---|---|---|---|---|---|"]
    closed, opened = 0.0, 0.0
    for t in trades:
        sgn = 1 if t["side"] == "long" else -1
        tgt = f"{t['target']:.2f}" if t.get("target") else "none"
        if t["exit"] is not None:
            closed += t["pct"] or 0
            L.append(f"| {t['symbol']} | {t['side']} | {t['entry_time']} | {t['exit_time']} | {t['entry']:.2f} | {t['stop']:.2f} | {tgt} | "
                     f"{t['exit']:.2f} | closed ({t['reason']}) | {t['pct']:+.2f}% |")
        else:
            px = last.get(t["symbol"])
            u = sgn * (px - t["entry"]) / abs(t["entry"] - t["stop"]) if px else 0.0
            opened += u
            L.append(f"| {t['symbol']} | {t['side']} | {t['entry_time']} | open | {t['entry']:.2f} | {t['stop']:.2f} | {tgt} | "
                     f"{px:.2f} | open | {u:+.2f}% (unrealized) |")
    n_c = sum(1 for t in trades if t["exit"] is not None)
    won = sum(1 for t in trades if t["exit"] is not None and (t["pct"] or 0) > 0)
    L += ["", f"Trades: {len(trades)} · closed {n_c} ({won} won, {n_c - won} lost) · open {len(trades) - n_c}",
          f"Closed P/L: {closed:+.2f}% · open P/L: {opened:+.2f}% · total if closed now: {closed + opened:+.2f}%", ""]
    return "\n".join(L)


def main(argv=None) -> int:
    now = pd.Timestamp.now(tz=ET) - pd.Timedelta(seconds=10)
    cfg = settings()
    lb._DRY[0] = True                      # never write the live picks file
    day = lb.inplay_orb_scan(cfg, now) if lb.STRATEGY in lb.ORB_STRATEGIES else lb.opening_scan(cfg, now)
    inp, picks, _ = ib.scan(cfg, now)
    last = marks(day + inp, now)
    print(f"# Status at {now:%H:%M} ET, {now:%A %d %B}\n")
    print(f"Day-trade rule running: {lb.STRATEGY}\n")
    print(block("Day-trade channel", day, last))
    print(block("In-play channel", inp, last))
    print("In-play picks: " + ", ".join(f"{s} {r:.1f}x" for s, r in picks))
    return 0


if __name__ == "__main__":
    sys.exit(main())
