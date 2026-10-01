"""Reading the real paper account.

The rule that matters: an OPEN position has no result. This project already
reported a day from its closed losers alone and made a profitable morning
look like a rout, so a half-filled book must never produce a number.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from src import account as ac
from src import broker as bk


@dataclass
class Reply:
    status_code: int = 200
    payload: object = field(default_factory=list)

    @property
    def text(self):
        return str(self.payload)

    def json(self):
        return self.payload


@dataclass
class FakeHTTP:
    rows: list = field(default_factory=list)
    calls: list = field(default_factory=list)

    def get(self, url, headers=None, params=None, timeout=None):
        self.calls.append(url)
        return Reply(200, self.rows)

    def post(self, *a, **k):
        raise AssertionError("reading the account must never place an order")


def fill(sym, side, qty, price, when):
    return {"symbol": sym, "side": side, "qty": str(qty),
            "price": str(price), "transaction_time": when}


def F(sym, side, qty, price, when):
    return ac.Fill(sym, side, qty, price, when, when[:10])


# --- what counts as an option ------------------------------------------------
def test_an_occ_symbol_is_recognised_as_an_option():
    assert F("AAPL260930C00340000", "buy", 1, 0.06, "2026-09-30T13:52:00Z").is_option
    assert F("AAPL260930C00340000", "buy", 1, 0.06, "2026-09-30T13:52:00Z").multiplier == 100


def test_a_plain_ticker_is_not_an_option():
    f = F("AAPL", "buy", 10, 333.0, "2026-09-30T13:52:00Z")
    assert not f.is_option and f.multiplier == 1


# --- matching ----------------------------------------------------------------
def test_a_buy_then_sell_closes_and_scores():
    rows = [F("AAPL", "buy", 10, 100.0, "2026-09-30T14:00:00Z"),
            F("AAPL", "sell", 10, 102.0, "2026-09-30T15:00:00Z")]
    t = ac.round_trips(rows)
    assert len(t) == 1
    assert t[0]["pnl"] == pytest.approx(20.0)
    assert t[0]["pct"] == pytest.approx(2.0)


def test_an_option_pays_a_hundred_times_the_contract_move():
    rows = [F("AAPL260930C00340000", "buy", 10, 0.06, "2026-09-30T13:52:00Z"),
            F("AAPL260930C00340000", "sell", 10, 0.42, "2026-09-30T14:02:00Z")]
    t = ac.round_trips(rows)
    assert t[0]["pnl"] == pytest.approx((0.42 - 0.06) * 10 * 100)


def test_an_open_position_produces_no_result_at_all():
    rows = [F("AAPL", "buy", 10, 100.0, "2026-09-30T14:00:00Z")]
    assert ac.round_trips(rows) == []
    assert ac.open_positions(rows) == {"AAPL": 10}


def test_a_partial_close_scores_only_what_closed():
    rows = [F("AAPL", "buy", 10, 100.0, "2026-09-30T14:00:00Z"),
            F("AAPL", "sell", 4, 110.0, "2026-09-30T15:00:00Z")]
    t = ac.round_trips(rows)
    assert len(t) == 1 and t[0]["qty"] == 4
    assert t[0]["pnl"] == pytest.approx(40.0)
    assert ac.open_positions(rows) == {"AAPL": 6}


def test_fills_are_matched_oldest_first():
    rows = [F("X", "buy", 1, 10.0, "2026-09-30T14:00:00Z"),
            F("X", "buy", 1, 20.0, "2026-09-30T14:30:00Z"),
            F("X", "sell", 1, 15.0, "2026-09-30T15:00:00Z")]
    t = ac.round_trips(rows)
    assert t[0]["buy"] == 10.0, "the earliest open buy closes first"
    assert ac.open_positions(rows) == {"X": 1}


def test_two_symbols_do_not_cross_match():
    rows = [F("A", "buy", 1, 10.0, "2026-09-30T14:00:00Z"),
            F("B", "sell", 1, 99.0, "2026-09-30T14:10:00Z")]
    assert ac.round_trips(rows) == []


# --- days --------------------------------------------------------------------
def test_days_group_and_count_winners():
    trips = [{"date": "2026-09-30", "pnl": 10.0}, {"date": "2026-09-30", "pnl": -4.0},
             {"date": "2026-10-01", "pnl": 7.0}]
    d = ac.by_day(trips)
    assert d["2026-09-30"] == {"pnl": 6.0, "n": 2, "won": 1, "lost": 1}
    assert d["2026-10-01"]["won"] == 1


def test_a_breakeven_trade_counts_as_a_loss_not_a_win():
    d = ac.by_day([{"date": "2026-09-30", "pnl": 0.0}])
    assert d["2026-09-30"]["won"] == 0 and d["2026-09-30"]["lost"] == 1


def test_the_summary_counts_green_and_red_sessions():
    s = ac.summarise({"a": {"pnl": 5.0, "n": 2, "won": 2, "lost": 0},
                      "b": {"pnl": -3.0, "n": 1, "won": 0, "lost": 1}})
    assert s["green"] == 1 and s["red"] == 1
    assert s["pnl"] == 2.0 and s["trades"] == 3 and s["win_pct"] == pytest.approx(66.7)


def test_an_empty_account_summarises_to_zero():
    assert ac.summarise({})["trades"] == 0


# --- fetching ----------------------------------------------------------------
def test_fills_come_back_oldest_first():
    http = FakeHTTP(rows=[fill("A", "buy", 1, 10, "2026-09-30T15:00:00Z"),
                          fill("A", "buy", 1, 11, "2026-09-30T14:00:00Z")])
    got = ac.fills(bk.Paper(key="k", secret="s", http=http))
    assert [f.when for f in got] == ["2026-09-30T14:00:00Z",
                                     "2026-09-30T15:00:00Z"]


def test_a_malformed_row_is_skipped_not_fatal():
    http = FakeHTTP(rows=[{"symbol": "A"},
                          fill("A", "buy", 1, 10, "2026-09-30T14:00:00Z")])
    assert len(ac.fills(bk.Paper(key="k", secret="s", http=http))) == 1


def test_reading_the_account_only_ever_talks_to_the_paper_host():
    http = FakeHTTP(rows=[])
    ac.fills(bk.Paper(key="k", secret="s", http=http))
    assert all(u.startswith(bk.PAPER_URL) for u in http.calls)


def test_reading_the_account_never_places_an_order():
    http = FakeHTTP(rows=[fill("A", "buy", 1, 10, "2026-09-30T14:00:00Z")])
    ac.fills(bk.Paper(key="k", secret="s", http=http))   # FakeHTTP.post raises


# --- the report --------------------------------------------------------------
def test_an_empty_account_says_so_rather_than_printing_zeros():
    text = ac.render({"days": {}, "summary": ac.summarise({}), "open": {},
                      "generated": "2026-10-01 02:00 UTC"})
    assert "No closed round trips" in text


def test_open_positions_are_named_as_having_no_result():
    text = ac.render({"days": {"2026-09-30": {"pnl": 5.0, "n": 1, "won": 1, "lost": 0}},
                      "summary": ac.summarise({"2026-09-30": {"pnl": 5.0, "n": 1,
                                                              "won": 1, "lost": 0}}),
                      "open": {"AAPL": 10}, "generated": "x"})
    assert "no result yet" in text and "AAPL ×10" in text
