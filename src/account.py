"""What the Alpaca paper account actually did — the real fills, not a model.

Everything else in this project is a simulation: the bot writes down what it
would have done and prices it from bars. This reads the account itself. If an
order filled, it is here; if it filled at a worse price than the simulation
assumed, that shows up too, which is the whole point.

Alpaca's activities endpoint gives every fill with its time, price and
quantity. Fills are matched oldest-first per symbol — buy then sell closes a
position — and only CLOSED round trips produce a profit or loss. A position
still open has no result yet, and saying otherwise is how a mid-day tally
ends up reading far worse than the day really is.

Options and shares both land here. An option's profit is per contract times
one hundred, which is the one piece of arithmetic worth getting right.

Read-only. This module places nothing and cancels nothing.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import defaultdict, deque
from dataclasses import dataclass

from . import broker as bk
from .config import REPO_ROOT

REPORTS = REPO_ROOT / "reports"
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s",
                    stream=sys.stdout)
log = logging.getLogger("account")

PAGE = 100


@dataclass(frozen=True)
class Fill:
    symbol: str
    side: str          # "buy" | "sell"
    qty: float
    price: float
    when: str          # ISO timestamp
    date: str          # YYYY-MM-DD

    @property
    def is_option(self) -> bool:
        # OCC symbols are the underlying plus 15 characters of date, type
        # and strike. Nothing else in an equities account looks like that.
        return len(self.symbol) > 15 and self.symbol[-9] in "CP"

    @property
    def multiplier(self) -> int:
        return 100 if self.is_option else 1


def fills(p: bk.Paper, after: str = "") -> list[Fill]:
    """Every fill on the account, oldest first."""
    out: list[Fill] = []
    page_token = ""
    while True:
        params = {"page_size": PAGE}
        if after:
            params["after"] = after
        if page_token:
            params["page_token"] = page_token
        rows = p._get("/v2/account/activities/FILL", params)
        if not isinstance(rows, list) or not rows:
            break
        for r in rows:
            try:
                when = str(r["transaction_time"])
                out.append(Fill(symbol=r["symbol"].upper(),
                                side=str(r["side"]).lower(),
                                qty=abs(float(r["qty"])),
                                price=float(r["price"]),
                                when=when, date=when[:10]))
            except (KeyError, TypeError, ValueError):
                continue
        if len(rows) < PAGE:
            break
        page_token = rows[-1].get("id", "")
        if not page_token:
            break
    out.sort(key=lambda f: f.when)
    return out


def round_trips(rows: list[Fill]) -> list[dict]:
    """Match buys to sells per symbol, oldest first.

    A sell closes the earliest open buy. Anything still open at the end is
    left out entirely rather than marked to anything - an open position has
    no result, and inventing one is the mistake this project already made
    once by reporting a day from its closed losers alone.
    """
    books: dict[str, deque] = defaultdict(deque)
    done = []
    for f in rows:
        if f.side == "buy":
            books[f.symbol].append([f, f.qty])
            continue
        left = f.qty
        while left > 1e-9 and books[f.symbol]:
            open_fill, open_qty = books[f.symbol][0]
            take = min(left, open_qty)
            m = f.multiplier
            done.append({
                "symbol": f.symbol, "qty": take,
                "opened": open_fill.when, "closed": f.when,
                "date": f.date,
                "buy": round(open_fill.price, 4), "sell": round(f.price, 4),
                "pnl": round((f.price - open_fill.price) * take * m, 2),
                "pct": round(100 * (f.price / open_fill.price - 1), 2)
                if open_fill.price else 0.0,
                "option": f.is_option})
            left -= take
            if open_qty - take <= 1e-9:
                books[f.symbol].popleft()
            else:
                books[f.symbol][0][1] = open_qty - take
    return done


def open_positions(rows: list[Fill]) -> dict[str, float]:
    books: dict[str, float] = defaultdict(float)
    for f in rows:
        books[f.symbol] += f.qty if f.side == "buy" else -f.qty
    return {s: q for s, q in books.items() if abs(q) > 1e-9}


def by_day(trips: list[dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for t in trips:
        d = out.setdefault(t["date"], {"pnl": 0.0, "n": 0, "won": 0, "lost": 0})
        d["pnl"] += t["pnl"]
        d["n"] += 1
        d["won" if t["pnl"] > 0 else "lost"] += 1
    for d in out.values():
        d["pnl"] = round(d["pnl"], 2)
    return dict(sorted(out.items()))


def summarise(days: dict[str, dict]) -> dict:
    if not days:
        return {"days": 0, "green": 0, "red": 0, "pnl": 0.0, "trades": 0,
                "won": 0, "lost": 0, "win_pct": 0.0}
    trades = sum(d["n"] for d in days.values())
    won = sum(d["won"] for d in days.values())
    return {"days": len(days),
            "green": sum(1 for d in days.values() if d["pnl"] > 0),
            "red": sum(1 for d in days.values() if d["pnl"] <= 0),
            "pnl": round(sum(d["pnl"] for d in days.values()), 2),
            "trades": trades, "won": won, "lost": trades - won,
            "win_pct": round(100 * won / trades, 1) if trades else 0.0}


def render(blob: dict) -> str:
    s = blob["summary"]
    L = ["# The paper account, as it really traded", "",
         f"Read from Alpaca at {blob['generated']}", ""]
    if not s["trades"]:
        L.append("No closed round trips on the account yet.")
        return "\n".join(L)
    L += [f"- {s['days']} sessions · **{s['green']} green, {s['red']} red**",
          f"- {s['trades']} closed trades · {s['won']} won, {s['lost']} lost · "
          f"**{s['win_pct']:.1f}% win rate**",
          f"- **{s['pnl']:+,.2f}** realised", ""]
    if blob.get("open"):
        L += ["Still open (no result yet): "
              + ", ".join(f"{k} ×{v:g}" for k, v in blob["open"].items()), ""]
    L += ["| date | trades | won | lost | P/L |", "|---|---|---|---|---|"]
    for d, v in blob["days"].items():
        L.append(f"| {d} | {v['n']} | {v['won']} | {v['lost']} | "
                 f"{v['pnl']:+,.2f} |")
    return "\n".join(L)


def build(p: bk.Paper, after: str = "") -> dict:
    import pandas as pd
    rows = fills(p, after)
    log.info("%d fills on the account", len(rows))
    trips = round_trips(rows)
    days = by_day(trips)
    return {"days": days, "summary": summarise(days),
            "open": open_positions(rows), "trips": trips[-200:],
            "generated": str(pd.Timestamp.utcnow())[:16] + " UTC"}


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--after", default="",
                    help="only fills after this ISO date")
    return ap.parse_args(argv)


def main(argv=None) -> int:
    import os
    args = parse_args(argv)
    key = os.environ.get("ALPACA_PAPER_KEY") or os.environ.get("ALPACA_API_KEY", "")
    secret = (os.environ.get("ALPACA_PAPER_SECRET")
              or os.environ.get("ALPACA_API_SECRET", ""))
    if not (key and secret):
        log.error("no Alpaca paper keys in the environment")
        return 1
    import requests
    p = bk.Paper(key=key, secret=secret, http=requests)
    try:
        blob = build(p, args.after)
    except bk.BrokerError as exc:
        log.error("could not read the account: %s", exc)
        return 1
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / "account.json").write_text(json.dumps(blob, indent=2))
    text = render(blob)
    (REPORTS / "account.md").write_text(text)
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
