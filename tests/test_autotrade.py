"""The paper auto-trader, with a fake account and no network.

What is pinned: which contract a signal buys, that a signal is bought once
and sold once, that the sale follows the stock's exit, that nothing is held
past the pre-bell sweep, and that the caps still bite when the record of
what was spent lives in Alpaca rather than in this process.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import pandas as pd

from src import autotrade as at
from src import broker as bk

THU = date(2026, 10, 1)
FRI = date(2026, 10, 2)
NEXT_FRI = date(2026, 10, 9)


def strip(under="AAPL", kind="put", expiry=FRI, strikes=(225, 227.5, 230,
                                                          232.5, 235), ask=1.5):
    return [bk.Contract(symbol=bk.occ(under, expiry, kind, s), underlying=under,
                        kind=kind, strike=s, expiry=expiry, ask=ask, bid=ask - .05)
            for s in strikes]


@dataclass
class FakePaper(bk.Paper):
    key: str = "k"
    secret: str = "s"
    orders: list = field(default_factory=list)
    held: list = field(default_factory=list)
    contracts: list = field(default_factory=list)
    sent: list = field(default_factory=list)

    def orders_since(self, after):
        return list(self.orders)

    def positions(self):
        return list(self.held)

    def chain(self, underlying, kind, on, allow_0dte=False, until=None, near=None):
        return [c for c in self.contracts
                if c.underlying == underlying and c.kind == kind]

    def _post(self, path, body):
        self.sent.append(body)
        return {"id": str(len(self.sent)), **body}


def sig(**kw):
    t = {"id": "AAPL-2026-10-01 14:00-231.00", "symbol": "AAPL", "side": "short",
         "entry_time": "10:00", "entry": 230.4, "stop": 232.0, "target": 227.0,
         "exit": None, "exit_time": None, "reason": None, "pct": None}
    return {**t, **kw}


def at_time(hhmm, day=THU):
    return pd.Timestamp(f"{day} {hhmm}", tz="America/New_York")


# --- which contract ----------------------------------------------------------
def test_a_short_buys_the_put_one_strike_below_the_money():
    c = at.choose(strip(kind="put"), "put", 230.4, THU)
    assert c.strike == 227.5 and c.expiry == FRI


def test_a_long_buys_the_call_one_strike_above_the_money():
    c = at.choose(strip(kind="call"), "call", 230.4, THU)
    assert c.strike == 232.5


def test_next_weeks_contracts_are_never_chosen():
    both = strip(expiry=NEXT_FRI) + strip(expiry=FRI, ask=2.0)
    assert at.choose(both, "put", 230.4, THU).expiry == FRI
    assert at.choose(strip(expiry=NEXT_FRI), "put", 230.4, THU) is None


def test_a_holiday_friday_falls_back_to_thursday():
    c = at.choose(strip(expiry=THU), "put", 230.4, THU)
    assert c.expiry == THU


def test_on_friday_it_is_the_same_day_contract():
    c = at.choose(strip(expiry=FRI) + strip(expiry=NEXT_FRI), "put", 230.4, FRI)
    assert c.expiry == FRI


def test_no_strike_past_the_edge_of_the_chain_means_no_trade():
    assert at.choose(strip(kind="put"), "put", 224.0, THU) is None


def test_a_three_cent_option_is_not_bought():
    assert at.choose(strip(ask=0.03), "put", 230.4, THU) is None


# --- opening -----------------------------------------------------------------
def test_a_fresh_signal_is_bought_with_its_own_order_id():
    p = FakePaper(contracts=strip())
    out = at.run([sig()], at_time("10:05"), p)
    assert len(p.sent) == 1 and out
    o = p.sent[0]
    assert o["side"] == "buy" and o["symbol"] == bk.occ("AAPL", FRI, "put", 227.5)
    assert o["client_order_id"] == at.order_id(at.OPEN_TAG, THU, sig()["id"])
    assert int(o["qty"]) * 1.5 * 100 <= bk.MAX_PREMIUM_PER_TRADE


def test_a_signal_already_bought_is_not_bought_again():
    oid = at.order_id(at.OPEN_TAG, THU, sig()["id"])
    p = FakePaper(contracts=strip(), orders=[
        {"client_order_id": oid, "symbol": "X", "status": "filled",
         "filled_qty": "6", "filled_avg_price": "1.5"}])
    at.run([sig()], at_time("10:10"), p)
    assert p.sent == []


def test_a_stale_signal_is_not_chased():
    p = FakePaper(contracts=strip())
    at.run([sig(entry_time="10:00")], at_time("10:30"), p)
    assert p.sent == []


def test_nothing_new_is_opened_late_in_the_day():
    p = FakePaper(contracts=strip())
    at.run([sig(entry_time="15:35")], at_time("15:36"), p)
    assert p.sent == []


def test_an_unposted_signal_is_not_traded():
    p = FakePaper(contracts=strip())
    at.run([sig(post=False)], at_time("10:05"), p)
    assert p.sent == []


def test_the_daily_cap_holds_across_runs():
    spent = [{"client_order_id": f"{at.OPEN_TAG}-20261001-{i}", "symbol": f"S{i}",
              "status": "filled", "filled_qty": "10", "filled_avg_price": "1.0"}
             for i in range(6)]
    p = FakePaper(contracts=strip(), orders=spent)
    at.run([sig()], at_time("10:05"), p)
    assert p.sent == []


def test_yesterdays_orders_do_not_count_against_today():
    old = [{"client_order_id": f"{at.OPEN_TAG}-20260930-{i}", "symbol": f"S{i}",
            "status": "filled", "filled_qty": "10", "filled_avg_price": "1.0"}
           for i in range(6)]
    p = FakePaper(contracts=strip(), orders=old)
    at.run([sig()], at_time("10:05"), p)
    assert len(p.sent) == 1


# --- closing -----------------------------------------------------------------
def opened(qty=6):
    sym = bk.occ("AAPL", FRI, "put", 227.5)
    oid = at.order_id(at.OPEN_TAG, THU, sig()["id"])
    return sym, {"client_order_id": oid, "symbol": sym, "status": "filled",
                 "filled_qty": str(qty), "filled_avg_price": "1.5"}


def test_the_option_is_sold_when_the_stock_hits_its_target():
    sym, o = opened()
    p = FakePaper(orders=[o], held=[{"symbol": sym, "qty": "6"}])
    at.run([sig(exit=227.0, reason="target", exit_time="10:40")],
           at_time("10:45"), p)
    assert p.sent == [{"symbol": sym, "qty": "6", "side": "sell",
                       "type": "market", "time_in_force": "day",
                       "client_order_id": at.order_id(at.CLOSE_TAG, THU,
                                                      sig()["id"])}]


def test_a_sale_already_made_is_not_made_twice():
    sym, o = opened()
    done = {"client_order_id": at.order_id(at.CLOSE_TAG, THU, sig()["id"]),
            "symbol": sym, "status": "filled"}
    p = FakePaper(orders=[o, done], held=[{"symbol": sym, "qty": "6"}])
    at.run([sig(exit=232.0, reason="stop", exit_time="10:40")],
           at_time("10:45"), p)
    assert p.sent == []


def test_it_never_sells_more_than_the_account_holds():
    sym, o = opened(qty=6)
    p = FakePaper(orders=[o], held=[{"symbol": sym, "qty": "2"}])
    at.run([sig(exit=232.0, reason="stop", exit_time="10:40")],
           at_time("10:45"), p)
    assert p.sent[0]["qty"] == "2"


def test_nothing_held_means_nothing_sold():
    _, o = opened()
    p = FakePaper(orders=[o], held=[])
    at.run([sig(exit=232.0, reason="stop", exit_time="10:40")],
           at_time("10:45"), p)
    assert p.sent == []


def test_the_pre_bell_sweep_sells_its_own_positions_and_nothing_else():
    sym, o = opened()
    p = FakePaper(orders=[o], held=[{"symbol": sym, "qty": "6"},
                                    {"symbol": "MSFT261002C00500000", "qty": "3"}])
    at.run([sig()], at_time("15:46"), p)
    assert [b["symbol"] for b in p.sent] == [sym]
    assert all(b["side"] == "sell" for b in p.sent)


def test_switched_off_it_does_nothing():
    p = FakePaper(contracts=strip())
    at.ENABLED, was = False, at.ENABLED
    try:
        assert at.run([sig()], at_time("10:05"), p) == []
    finally:
        at.ENABLED = was
    assert p.sent == []
