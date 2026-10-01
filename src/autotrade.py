"""Every signal the live bot posts, taken on the Alpaca paper account as an
option.

  * LONG signal  -> buy a call, one strike above the at-the-money strike.
  * SHORT signal -> buy a put, one strike below it.
  * Expiry: the last listed expiry on or before this Friday. On a Friday that
    is the same day's contract - Uday's choice, made knowing 0DTE produced
    both the +597% and every total loss on 30 September.
  * Exit: when the signal's stop, target or bell exit fires on the stock, the
    option is sold. The option has no TP or SL of its own; it follows the
    stock's, so the card in Discord and the position in the account always
    end together.
  * Everything still held is sold at PRE_BELL. Nothing is left to expire.

Size is the whole number of contracts nearest TARGET_PREMIUM (about 1,000)
at the ask, never past MAX_PREMIUM_PER_TRADE, and every cap in `broker.py`
still applies.

Stateless, like the bot that calls it. The account is the record: each order
carries a client_order_id derived from the trade's id, so "have I bought this
signal yet" is answered by Alpaca, and a repeated or concurrent run cannot
buy the same signal twice - Alpaca refuses a duplicate id.
"""
from __future__ import annotations

import hashlib
import logging
import os
from datetime import date, timedelta

import pandas as pd

from . import broker as bk

log = logging.getLogger("autotrade")

# Uday asked for this on 30 September, to start trading the next session.
# The house rule is that new behaviour ships switched off until a holdout
# supports it; this one was switched on by explicit request, on paper only.
ENABLED = True

LAST_ENTRY = "15:30"     # no new positions after this
PRE_BELL = "15:45"       # sell everything this module holds
FRESH_MINUTES = 15       # a signal older than this is not chased
BUDGET = bk.TARGET_PREMIUM

OPEN_TAG, CLOSE_TAG = "tb-o", "tb-c"


def order_id(tag: str, day: date, trade_id: str) -> str:
    h = hashlib.sha1(trade_id.encode()).hexdigest()[:16]
    return f"{tag}-{day:%Y%m%d}-{h}"


def this_friday(on: date) -> date:
    return on + timedelta(days=(4 - on.weekday()) % 7)


def choose(contracts: list[bk.Contract], kind: str, spot: float,
           on: date) -> bk.Contract | None:
    """One strike out of the money, in this week's last expiry.

    At the money is the listed strike nearest the stock; "one away" is the
    next listed strike past it in the trade's direction - above for a call,
    below for a put. Strike spacing differs by name (SPY in ones, TSLA in
    fives, some in halves), so it is counted in listed strikes, not dollars.
    """
    fri = this_friday(on)
    week = [c for c in contracts if c.kind == kind and on <= c.expiry <= fri]
    if not week:
        return None
    exp = max(c.expiry for c in week)
    by_strike = {c.strike: c for c in week if c.expiry == exp}
    strikes = sorted(by_strike)
    atm = min(range(len(strikes)), key=lambda i: abs(strikes[i] - spot))
    k = atm + 1 if kind == "call" else atm - 1
    if not 0 <= k < len(strikes):
        return None
    c = by_strike[strikes[k]]
    if not bk.MIN_PRICE <= c.ask <= bk.MAX_PRICE:
        log.info("skip %s: ask %.2f outside %.2f-%.2f", c.symbol, c.ask,
                 bk.MIN_PRICE, bk.MAX_PRICE)
        return None
    return c


def contracts_for(c: bk.Contract, target: float = BUDGET,
                  ceiling: float = bk.MAX_PREMIUM_PER_TRADE) -> int:
    """The whole number of contracts whose cost at the ask lands nearest
    `target`, a bit over or a bit under, never past `ceiling`."""
    per = c.ask * 100
    if per <= 0 or per > ceiling:
        return 0
    lo = max(1, int(target // per))
    fits = [q for q in (lo, lo + 1) if q * per <= ceiling]
    return min(fits, key=lambda q: abs(q * per - target)) if fits else 0


def _minutes(hhmm: str) -> int:
    return int(hhmm[:2]) * 60 + int(hhmm[3:5])


def _cost(o: dict) -> float:
    """Premium an opening order has used against the daily cap. A pending
    order is counted at the full per-trade cap until it fills - the cap is
    there to stop spending, and an unknown is not a zero."""
    st = str(o.get("status", "")).lower()
    if st in ("canceled", "cancelled", "rejected", "expired"):
        return 0.0
    q, px = float(o.get("filled_qty") or 0), float(o.get("filled_avg_price") or 0)
    if q and px:
        return q * px * 100
    return BUDGET


def ledger(orders: list[dict], day: date) -> tuple[dict, set, float]:
    """Today's orders from this module: opens by id, closed ids, premium."""
    stamp = f"{day:%Y%m%d}"
    opens, closes, spent = {}, set(), 0.0
    for o in orders:
        cid = str(o.get("client_order_id") or "")
        if cid.startswith(f"{OPEN_TAG}-{stamp}-"):
            opens[cid] = o
            spent += _cost(o)
        elif cid.startswith(f"{CLOSE_TAG}-{stamp}-"):
            closes.add(cid)
    return opens, closes, spent


def _close(p: bk.Paper, held: dict, o: dict, cid: str) -> bool:
    sym = o["symbol"]
    qty = min(int(float(o.get("filled_qty") or o.get("qty") or 0)),
              held.get(sym, 0))
    if qty <= 0:
        return False
    try:
        p.sell_to_close(sym, qty, client_order_id=cid)
        held[sym] = held.get(sym, 0) - qty
        return True
    except bk.BrokerError as exc:
        log.error("could not sell %s: %s", sym, exc)
        return False


def run(trades: list[dict], now: pd.Timestamp, p: bk.Paper) -> list[str]:
    """One pass. Returns a line per order placed, for the log."""
    if not ENABLED:
        return []
    day = now.date()
    start = pd.Timestamp(day, tz=now.tz).tz_convert("UTC")
    opens, closes, spent = ledger(p.orders_since(start.isoformat()), day)
    held = {x["symbol"]: abs(int(float(x["qty"]))) for x in p.positions()}
    ours = {o["symbol"] for o in opens.values()}
    p.spent_today = spent
    p.opened = {s: q for s, q in held.items() if s in ours}
    done: list[str] = []
    t_now = now.hour * 60 + now.minute

    # Before the bell: sell everything this module bought today.
    if t_now >= _minutes(PRE_BELL):
        for cid, o in opens.items():
            close_id = CLOSE_TAG + cid[len(OPEN_TAG):]
            if close_id not in closes and _close(p, held, o, close_id):
                done.append(f"pre-bell sell {o['symbol']}")
        return done

    for t in trades:
        if not t.get("post", True):
            continue
        oid = order_id(OPEN_TAG, day, t["id"])
        cid = order_id(CLOSE_TAG, day, t["id"])

        if t.get("exit") is not None:
            # The stock hit its stop, target or the bell: follow it out.
            if oid in opens and cid not in closes and _close(p, held, opens[oid], cid):
                done.append(f"sell {opens[oid]['symbol']} ({t['reason']})")
            continue

        if oid in opens:
            continue
        if t_now > _minutes(LAST_ENTRY):
            continue
        age = t_now - _minutes(t["entry_time"])
        if age > FRESH_MINUTES:
            log.info("skip %s %s: signal is %d min old", t["symbol"],
                     t["entry_time"], age)
            continue

        kind = "put" if t.get("side", "short") == "short" else "call"
        try:
            chain = p.chain(t["symbol"], kind, day, allow_0dte=True,
                            until=this_friday(day), near=float(t["entry"]))
        except bk.BrokerError as exc:
            log.error("no chain for %s: %s", t["symbol"], exc)
            continue
        c = choose(chain, kind, float(t["entry"]), day)
        if c is None:
            log.info("skip %s: no %s one strike out this week", t["symbol"], kind)
            continue
        qty = contracts_for(c)
        if qty <= 0:
            log.info("skip %s: one contract costs more than the cap", c.symbol)
            continue
        try:
            if p.buy_to_open(c, qty, client_order_id=oid):
                opens[oid] = {"symbol": c.symbol, "qty": str(qty)}
                done.append(f"buy {qty} {c.symbol} @~{c.ask:.2f}")
        except bk.BrokerError as exc:
            log.error("could not buy %s: %s", c.symbol, exc)
    return done


def client() -> bk.Paper | None:
    key = os.environ.get("ALPACA_PAPER_KEY") or os.environ.get("ALPACA_API_KEY", "")
    sec = (os.environ.get("ALPACA_PAPER_SECRET")
           or os.environ.get("ALPACA_API_SECRET", ""))
    if not (key and sec):
        log.warning("no Alpaca paper keys - not trading")
        return None
    import requests
    return bk.Paper(key=key, secret=sec, http=requests)
