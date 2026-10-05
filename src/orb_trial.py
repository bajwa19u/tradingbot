"""Trial run: replay today's session (or any day) with a day-trade rule and,
with --post, send it to the day-trade Discord channel clearly marked as a
trial, so the owner can see what the channel would have shown.

Nothing here touches the live bot's record: no seen-file, no picks file, no
edits to live cards. Every message starts with a TRIAL banner.

Usage: python -m src.orb_trial [--strategy bigtech] [--date YYYY-MM-DD] [--post]
"""
from __future__ import annotations

import argparse
import sys
import time

import pandas as pd

from . import discord_msg as dm
from . import live_bot as lb
from . import orb_live as ol
from .config import Credentials
from .data import MarketData

ET = "America/New_York"
BANNER = "⏪ **TRIAL RUN · not a live signal**"


def replay(strategy: str, now: pd.Timestamp) -> list[dict]:
    ol.use(strategy)
    ol.PICKS_FILE = ol.PICKS_FILE.with_name(f"trial_{strategy}_picks.json")     # never the live file
    trades, _ = ol.scan(now, lambda: MarketData(Credentials.from_env(), feed="iex"), 1.0, dry_run=True)
    return trades


def trial_card(t: dict) -> str:
    text = lb.card(t)
    if t["exit"] is None:
        text = text.replace("NEW SIGNAL · ", "STILL OPEN · ")
    return f"{BANNER}\n{text}"


def tally(trades: list[dict]) -> tuple[int, int, int, int, float]:
    done = [t for t in trades if t["exit"] is not None]
    won = sum(1 for t in done if (t["pct"] or 0) > 0)
    return len(trades), len(done), won, len(done) - won, sum(t["pct"] or 0 for t in done)


def line(t: dict) -> str:
    if t["exit"] is None:
        return f"🕒 {t['side'].upper()} {t['symbol']} {t['entry_time']}→open"
    mark = "✅" if (t["pct"] or 0) > 0 else "❌"
    return f"{mark} {t['side'].upper()} {t['symbol']} {t['entry_time']}→{t['exit_time']}  {t['pct']:+.2f}%"


def summary(day: str, asof: str, big: list[dict], live: list[dict]) -> str:
    n, d, w, l, tot = tally(big)
    n2, d2, w2, l2, tot2 = tally(live)
    rows = "\n".join(line(t) for t in big)
    return (f"{BANNER}\n📊 **Trial summary · Big Tech rule · {day}** (bars through {asof} ET)\n"
            f"**{n} trade{'s' if n != 1 else ''}** · {d} closed: {w} won, {l} lost · {n - d} still open\n"
            f"Closed total **{tot:+.2f}%** of the account (1% risk per trade)\n"
            + (f"{rows}\n" if rows else "No setups on TSLA, AMD, NVDA, META, AAPL or MSFT today.\n")
            + f"\n**Live channel so far today** (stocks-in-play rule, before the switch): {n2} signals · {d2} closed: "
            f"{w2} won, {l2} lost · {n2 - d2} open · closed total **{tot2:+.2f}%**\n"
            f"_From tomorrow the live channel runs the Big Tech rule: TSLA, AMD, NVDA, META, AAPL, MSFT. "
            f"Entries 09:35–09:44, stop to entry once up by its risk, target 2× risk, out by 15:55._")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--strategy", default="bigtech")
    ap.add_argument("--date", default="")
    ap.add_argument("--post", action="store_true")
    args = ap.parse_args(argv)
    real = pd.Timestamp.now(tz=ET) - pd.Timedelta(seconds=30)
    day = pd.Timestamp(args.date).date() if args.date else real.date()
    now = min(real, pd.Timestamp(f"{day} 16:01", tz=ET))
    big = replay(args.strategy, now)
    live = replay("inplay_orb", now)
    msgs = [f"{BANNER}\nReplaying **{day}** with the **Big Tech** day-trade rule, as the channel would have posted it. "
            f"Each card shows where the trade stands now ({now:%H:%M} ET)."]
    msgs += [trial_card(t) for t in big]
    msgs.append(summary(str(day), now.strftime("%H:%M"), big, live))
    for m in msgs:
        print(m + "\n")
    if not args.post:
        return 0
    hook = Credentials.from_env().discord_webhook
    if not hook:
        print("DISCORD_WEBHOOK_URL is not set - nothing sent"); return 1
    for m in msgs:
        dm.post(hook, m)
        time.sleep(1.2)               # stay well under the webhook's rate limit
    print(f"posted {len(msgs)} messages")
    return 0


if __name__ == "__main__":
    sys.exit(main())
