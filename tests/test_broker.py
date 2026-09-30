"""The paper broker, with no network anywhere in sight.

Two kinds of test here. Most check the arithmetic — which contract gets
picked, how many of them a budget buys, whether a cap refuses an order.

The first two check something else: that this module cannot reach a live
account. That is not a unit test so much as a standing guarantee, and it is
written so that it fails if someone later makes the endpoint configurable.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import pytest

from src import broker as bk


# --- a fake Alpaca -----------------------------------------------------------
@dataclass
class Reply:
    status_code: int = 200
    payload: object = field(default_factory=dict)

    @property
    def text(self) -> str:
        return json.dumps(self.payload)

    def json(self):
        return self.payload


@dataclass
class FakeHTTP:
    """Records what it was asked to do; never opens a socket."""
    gets: list = field(default_factory=list)
    posts: list = field(default_factory=list)
    positions: list = field(default_factory=list)
    # Reads and writes fail separately: "the broker won't tell me what I
    # hold" and "the broker won't let me sell it" are different outages and
    # flatten() has to survive both.
    get_status: int = 200
    post_status: int = 200

    def get(self, url, headers=None, params=None, timeout=None):
        self.gets.append(url)
        if url.endswith("/v2/positions"):
            return Reply(self.get_status, self.positions)
        return Reply(self.get_status, {"status": "ACTIVE", "equity": "100000"})

    def post(self, url, headers=None, json=None, timeout=None):
        self.posts.append(json)
        return Reply(self.post_status, {"id": "o1", **(json or {})})


def paper(**kw) -> bk.Paper:
    return bk.Paper(key="k", secret="s", http=FakeHTTP(), **kw)


def contract(strike, expiry, ask=1.00, kind="call", bid=None):
    return bk.Contract(
        symbol=bk.occ("AAPL", expiry, kind, strike), underlying="AAPL",
        kind=kind, strike=strike, expiry=expiry, ask=ask,
        bid=ask - 0.05 if bid is None else bid)


TODAY = date(2026, 9, 30)


# --- it cannot reach a live account -----------------------------------------
def test_a_live_endpoint_is_refused_outright():
    with pytest.raises(bk.BrokerError, match="only ever speaks to"):
        bk._check("https://api.alpaca.markets/v2/orders")


def test_no_live_alpaca_hostname_appears_in_the_source():
    """If someone makes the endpoint configurable, this is what catches it."""
    src = (Path(bk.__file__)).read_text()
    assert "https://api.alpaca.markets" not in src
    assert src.count("PAPER_URL = ") == 1
    assert "paper-api.alpaca.markets" in src


def test_every_call_goes_through_the_paper_host():
    p = paper()
    p.account()
    p.buy_to_open(contract(340, date(2026, 10, 2), ask=1.00), 1)
    for url in p.http.gets:
        assert url.startswith(bk.PAPER_URL)


# --- choosing the contract ---------------------------------------------------
def test_it_takes_the_strike_nearest_the_target():
    exp = date(2026, 10, 2)
    cs = [contract(s, exp) for s in (330, 335, 340, 345, 350)]
    assert bk.pick_contract(cs, target=341.0, on=TODAY).strike == 340
    assert bk.pick_contract(cs, target=334.0, on=TODAY).strike == 335


def test_it_takes_the_nearest_expiry_that_is_not_today():
    near, far = date(2026, 10, 1), date(2026, 10, 9)
    cs = [contract(340, far), contract(400, near)]
    # the far one has the better strike; the near expiry still wins
    assert bk.pick_contract(cs, target=340, on=TODAY).expiry == near


def test_same_day_contracts_are_excluded_unless_asked_for():
    cs = [contract(340, TODAY, ask=0.06), contract(340, date(2026, 10, 2))]
    assert bk.pick_contract(cs, 340, TODAY).expiry != TODAY
    assert bk.pick_contract(cs, 340, TODAY, allow_0dte=True).expiry == TODAY


def test_contracts_too_cheap_or_too_dear_are_skipped():
    exp = date(2026, 10, 2)
    cs = [contract(340, exp, ask=0.01), contract(345, exp, ask=99.0),
          contract(360, exp, ask=2.00)]
    assert bk.pick_contract(cs, target=340, on=TODAY).strike == 360


def test_nothing_suitable_returns_none_rather_than_a_bad_fill():
    assert bk.pick_contract([], 340, TODAY) is None
    stale = [contract(340, date(2026, 8, 1))]
    assert bk.pick_contract(stale, 340, TODAY) is None


# --- sizing ------------------------------------------------------------------
def test_size_prices_at_the_ask_not_the_middle():
    c = bk.Contract("X", "AAPL", "call", 340, date(2026, 10, 2), ask=2.00,
                    bid=1.00)
    assert bk.size(c, 1000.0) == 5        # 1000 / (2.00*100), not the 1.50 mid


def test_size_never_exceeds_the_per_trade_cap():
    c = contract(340, date(2026, 10, 2), ask=1.00)
    assert bk.size(c, 50_000.0) == int(bk.MAX_PREMIUM_PER_TRADE // 100)


def test_a_worthless_quote_buys_nothing():
    c = bk.Contract("X", "AAPL", "call", 340, date(2026, 10, 2), ask=0.0)
    assert bk.size(c, 1000.0) == 0


# --- the caps ----------------------------------------------------------------
def test_an_order_over_the_per_trade_cap_is_refused():
    p = paper()
    assert p.buy_to_open(contract(340, date(2026, 10, 2), ask=20.0), 10) is None
    assert p.http.posts == []


def test_the_day_stops_buying_once_the_daily_cap_is_reached():
    p = paper()
    c = contract(340, date(2026, 10, 2), ask=1.00)   # 100 per contract
    for _ in range(int(bk.MAX_PREMIUM_PER_DAY // 1000)):
        assert p.buy_to_open(c, 10) is not None      # 1000 each
    assert p.buy_to_open(c, 10) is None
    assert p.spent_today <= bk.MAX_PREMIUM_PER_DAY


def test_it_will_not_hold_more_than_the_position_limit():
    p = paper()
    exp = date(2026, 10, 2)
    for i in range(bk.MAX_OPEN_POSITIONS):
        assert p.buy_to_open(contract(300 + i, exp, ask=0.50), 1) is not None
    assert p.buy_to_open(contract(400, exp, ask=0.50), 1) is None


def test_zero_contracts_is_not_an_order():
    p = paper()
    assert p.buy_to_open(contract(340, date(2026, 10, 2)), 0) is None
    assert p.sell_to_close("AAPL261002C00340000", 0) is None
    assert p.http.posts == []


# --- closing -----------------------------------------------------------------
def test_selling_clears_the_position_it_was_tracking():
    p = paper()
    c = contract(340, date(2026, 10, 2), ask=1.00)
    p.buy_to_open(c, 5)
    assert c.symbol in p.opened
    p.sell_to_close(c.symbol, 5)
    assert c.symbol not in p.opened


def test_a_partial_sale_leaves_the_rest_open():
    p = paper()
    c = contract(340, date(2026, 10, 2), ask=1.00)
    p.buy_to_open(c, 5)
    p.sell_to_close(c.symbol, 2)
    assert p.opened[c.symbol] == 3


def test_flatten_closes_everything_it_is_holding():
    p = paper()
    p.http.positions = [{"symbol": "AAPL261002C00340000", "qty": "5"},
                        {"symbol": "MSFT261002P00500000", "qty": "-3"}]
    p.flatten()
    sold = [o["symbol"] for o in p.http.posts]
    assert sold == ["AAPL261002C00340000", "MSFT261002P00500000"]
    assert all(o["side"] == "sell" for o in p.http.posts)


def test_flatten_keeps_going_when_one_leg_fails():
    p = paper()
    p.http.positions = [{"symbol": "AAA261002C00100000", "qty": "1"},
                        {"symbol": "BBB261002C00100000", "qty": "1"}]
    p.http.post_status = 500
    p.flatten()                       # must not raise
    assert len(p.http.posts) == 2, "one refused leg must not abandon the other"


def test_flatten_survives_not_being_able_to_read_positions():
    p = paper()
    p.http.positions = [{"symbol": "AAA261002C00100000", "qty": "1"}]
    p.http.get_status = 500
    assert p.flatten() == []          # nothing sold, nothing raised


# --- OCC symbols -------------------------------------------------------------
def test_occ_matches_the_format_alpaca_uses():
    assert bk.occ("AAPL", date(2026, 9, 30), "call", 340.0) == \
        "AAPL260930C00340000"
    assert bk.occ("TSLA", date(2026, 9, 30), "put", 347.5) == \
        "TSLA260930P00347500"


@pytest.mark.parametrize("sym,strike", [
    ("AAPL260930C00340000", 340.0),
    ("TSLA260930P00347500", 347.5),
    ("SPY260930P00762000", 762.0),
    ("GOOG261002C00360000", 360.0),
])
def test_parsing_an_occ_symbol_gives_the_strike_back(sym, strike):
    und, exp, kind, s = bk.parse_occ(sym)
    assert s == strike
    assert bk.occ(und, exp, kind, s) == sym


# --- the caps are the numbers we agreed -------------------------------------
def test_the_caps_are_what_uday_asked_for():
    assert bk.MAX_PREMIUM_PER_TRADE == 1000.0
    assert bk.MAX_PREMIUM_PER_DAY == 6000.0
    assert bk.MAX_OPEN_POSITIONS == 8
