"""Two calendars: what the shares did each day, and what contracts would have.

The shares calendar is a measurement. Every trade is replayed from one-minute
bars at the prices the rule would really have paid, the same way every other
study in this project works.

The contracts calendar is a MODEL, and the difference matters more than
anything else in this file.

Why the contracts side cannot be a measurement
----------------------------------------------
Backtesting options honestly needs historical option prices - every strike,
every expiry, bid and ask, minute by minute. We do not have that. Alpaca's
free tier does not carry option history, and nothing else here reaches it.

So the contracts calendar prices each trade with Black-Scholes, using the
stock's own realised volatility, and charges a spread on both ends. That is a
reasonable model and it is NOT data. It will be wrong in a specific
direction: real option spreads on short-dated contracts are wider than any
flat assumption, and they are widest exactly where the model is most
optimistic - cheap, nearly worthless strikes on the day they expire. The
30 September blotter is the evidence: a six-cent AAPL call with a real spread
of five to seven cents, which is thirty percent round trip on its own.

Treat the contracts calendar as "the shape the leverage would have had", not
as a profit and loss. Every number it produces is labelled modelled.

The contract chosen
-------------------
Uday's rule: the strike one increment away from spot in the direction of the
trade - one up for a call, one down for a put - expiring the Friday of that
week. Both are what he actually traded on 30 September.
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import sys
from datetime import date, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from . import opening as op
from . import widths as w
from .config import REPO_ROOT, Credentials
from .data import AlpacaError, MarketData
from .forensics import UNIVERSES

EASTERN = ZoneInfo("America/New_York")
REPORTS = REPO_ROOT / "reports"
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s",
                    stream=sys.stdout)
log = logging.getLogger("calendars")

SPREAD_PCT = 3.0       # charged each way on the option, a deliberate floor
RATE = 0.04            # risk-free, near enough for a contract held hours
MIN_VOL, MAX_VOL = 0.15, 2.50
VOL_LOOKBACK = 20


# --- the contract --------------------------------------------------------
def strike_step(price: float) -> float:
    """What a strike ladder actually looks like at this price.

    Not a formula anyone publishes - it is the spacing the big names use, and
    it only has to be close enough that "one strike away" means roughly what
    a human means by it.
    """
    if price < 25:
        return 0.5
    if price < 100:
        return 1.0
    if price < 250:
        return 2.5
    return 5.0


def pick_strike(spot: float, side: str) -> float:
    """One strike away from spot, in the direction of the trade."""
    step = strike_step(spot)
    if side == "long":                      # a call, one strike above
        return math.floor(spot / step) * step + step
    return math.ceil(spot / step) * step - step   # a put, one strike below


def friday_of(d: date) -> date:
    """That week's Friday. A trade taken ON Friday expires the same day."""
    return d + timedelta(days=(4 - d.weekday()))


def norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def bs_price(spot: float, strike: float, years: float, vol: float,
             kind: str) -> float:
    """Black-Scholes. At or past expiry it returns intrinsic value."""
    if years <= 0 or vol <= 0:
        return max(spot - strike, 0.0) if kind == "call" else max(strike - spot, 0.0)
    d1 = ((math.log(spot / strike) + (RATE + vol * vol / 2) * years)
          / (vol * math.sqrt(years)))
    d2 = d1 - vol * math.sqrt(years)
    disc = math.exp(-RATE * years)
    if kind == "call":
        return spot * norm_cdf(d1) - strike * disc * norm_cdf(d2)
    return strike * disc * norm_cdf(-d2) - spot * norm_cdf(-d1)


def realised_vol(closes: list[float]) -> float:
    """Annualised volatility from daily closes, clamped to something sane."""
    if len(closes) < 5:
        return 0.35
    r = np.diff(np.log(np.array(closes, dtype=float)))
    v = float(np.std(r, ddof=1)) * math.sqrt(252)
    return min(MAX_VOL, max(MIN_VOL, v))


def contract_return(t: dict, vol: float) -> dict | None:
    """What the option would have returned on the same entry and exit.

    Time decay is charged for the minutes the trade was actually open, which
    for a contract expiring that Friday is a real cost on the day itself.
    """
    d = pd.Timestamp(t["date"]).date()
    kind = "call" if t["side"] == "long" else "put"
    strike = pick_strike(t["entry"], t["side"])
    expiry = friday_of(d)

    held_min = max(1.0, _minutes(t["entry_time"], t["exit_time"]))
    t0 = max(0.0, ((expiry - d).days + (16 / 24)) / 365.0)
    t1 = max(0.0, t0 - held_min / (365.0 * 24 * 60))

    buy = bs_price(t["entry"], strike, t0, vol, kind) * (1 + SPREAD_PCT / 100)
    sell = bs_price(t["exit"], strike, t1, vol, kind) * (1 - SPREAD_PCT / 100)
    if buy <= 0.01:
        return None                       # too cheap to be a real quote
    return {"strike": strike, "expiry": str(expiry), "kind": kind,
            "buy": round(buy, 3), "sell": round(max(sell, 0.0), 3),
            "pct": round(100 * (max(sell, 0.0) / buy - 1), 2)}


def _minutes(a: str, b: str) -> float:
    f = lambda s: int(s[:2]) * 60 + int(s[3:5])          # noqa: E731
    return max(0.0, f(b) - f(a))


# --- the calendars -------------------------------------------------------
def by_date(trades: list[dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for t in trades:
        out.setdefault(str(t["date"]), []).append(t)
    return dict(sorted(out.items()))


def stock_days(trades: list[dict]) -> dict[str, dict]:
    """Per-day result on the shares: percentages summed at 1% risk a trade,
    which is the convention every other report in this project uses."""
    out = {}
    for d, ts in by_date(trades).items():
        won = sum(1 for t in ts if t["pct"] > 0)
        out[d] = {"pct": round(sum(t["pct"] for t in ts), 2),
                  "n": len(ts), "won": won, "lost": len(ts) - won}
    return out


def contract_days(trades: list[dict], vols: dict[str, float]) -> dict[str, dict]:
    """Per-day result on contracts, equal weight across that day's signals.

    Option returns cannot be added together the way 1%-risk share trades can -
    one of them can be +600% - so a day is the AVERAGE return of its signals,
    which is what splitting the day's budget evenly across them would give.
    """
    out = {}
    for d, ts in by_date(trades).items():
        rows = []
        for t in ts:
            c = contract_return(t, vols.get(t["symbol"], 0.35))
            if c:
                rows.append(c)
        if not rows:
            continue
        won = sum(1 for c in rows if c["pct"] > 0)
        out[d] = {"pct": round(float(np.mean([c["pct"] for c in rows])), 2),
                  "n": len(rows), "won": won, "lost": len(rows) - won,
                  "modelled": True}
    return out


def vols_for(data: dict[str, pd.DataFrame]) -> dict[str, float]:
    out = {}
    for sym, df in data.items():
        if not len(df):
            continue
        closes = [float(d[1]["close"].iloc[-1]) for d in op.by_day(df)]
        if closes:
            out[sym] = round(realised_vol(closes[-VOL_LOOKBACK:]), 4)
    return out


def summarise(days: dict[str, dict]) -> dict:
    if not days:
        return {"days": 0, "green": 0, "red": 0, "total": 0.0, "best": 0.0,
                "worst": 0.0, "trades": 0, "won": 0, "lost": 0}
    v = [d["pct"] for d in days.values()]
    return {"days": len(days),
            "green": sum(1 for x in v if x > 0), "red": sum(1 for x in v if x <= 0),
            "total": round(sum(v), 2), "best": round(max(v), 2),
            "worst": round(min(v), 2),
            "trades": sum(d["n"] for d in days.values()),
            "won": sum(d["won"] for d in days.values()),
            "lost": sum(d["lost"] for d in days.values())}


def build(data: dict[str, pd.DataFrame]) -> dict:
    p = w.cfg()
    trades = [t for t in w.trades_for(data, None, p) if t.get("reason") != "open"]
    log.info("%d closed trades across %d symbols", len(trades), len(data))
    vols = vols_for(data)
    stock, contract = stock_days(trades), contract_days(trades, vols)
    return {"stock": {"days": stock, "summary": summarise(stock)},
            "contract": {"days": contract, "summary": summarise(contract),
                         "assumptions": {
                             "pricing": "Black-Scholes on realised volatility",
                             "spread_pct_each_way": SPREAD_PCT,
                             "strike": "one strike from spot, in the trade's direction",
                             "expiry": "the Friday of that week",
                             "measured": False}},
            "generated": str(pd.Timestamp.now(tz=EASTERN))[:16]}


def render(blob: dict) -> str:
    s, c = blob["stock"]["summary"], blob["contract"]["summary"]
    L = ["# Two calendars", "", f"Generated {blob['generated']} ET", "",
         "## Shares — measured", "",
         f"- {s['days']} sessions · **{s['green']} green, {s['red']} red**",
         f"- {s['trades']} trades · {s['won']} won, {s['lost']} lost · "
         f"**{100 * s['won'] / s['trades']:.1f}% win rate**"
         if s["trades"] else "- no trades",
         f"- total **{s['total']:+.2f}%** · best day {s['best']:+.2f}% · "
         f"worst {s['worst']:+.2f}%", "",
         "## Contracts — modelled, not measured", "",
         "Black-Scholes on realised volatility, 3% spread charged each way, "
         "one strike from spot, expiring that Friday. Real spreads on "
         "short-dated contracts are wider than this, so read it as the shape "
         "of the leverage rather than a profit and loss.", "",
         f"- {c['days']} sessions · **{c['green']} green, {c['red']} red**",
         f"- {c['trades']} signals priced · {c['won']} won, {c['lost']} lost · "
         f"**{100 * c['won'] / c['trades']:.1f}% win rate**"
         if c["trades"] else "- nothing priceable",
         f"- average day **{c['total'] / max(c['days'], 1):+.2f}%** · "
         f"best {c['best']:+.2f}% · worst {c['worst']:+.2f}%"]
    return "\n".join(L)


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--universe", default="bigtech")
    ap.add_argument("--symbols", default="")
    return ap.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    symbols = ([s.strip().upper() for s in args.symbols.split(",") if s.strip()]
               or UNIVERSES.get(args.universe) or UNIVERSES["bigtech"])
    md = MarketData(Credentials.from_env(), feed="iex")
    try:
        data = op.fetch(md, symbols, args.days)
    except AlpacaError as exc:
        log.error("could not fetch bars: %s", exc)
        return 1
    if not data:
        log.error("no usable price history came back for %s", ", ".join(symbols))
        return 1
    blob = build(data)
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / "calendars.json").write_text(json.dumps(blob, indent=2))
    text = render(blob)
    (REPORTS / "calendars.md").write_text(text)
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
