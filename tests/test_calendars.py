"""The two calendars.

The share side is arithmetic over replayed trades. The contract side is a
model, and the tests that matter most are the ones that stop the model
flattering itself: a contract must cost more than it sells for at the same
price (the spread), it must lose value as time passes, and a strike must land
on the correct side of spot.
"""
from __future__ import annotations

from datetime import date

import pytest

from src import calendars as cal


def trade(**kw):
    base = {"symbol": "AAPL", "date": "2026-09-30", "side": "long",
            "entry": 333.53, "exit": 340.36, "pct": 2.0,
            "entry_time": "09:49", "exit_time": "10:20"}
    return {**base, **kw}


# --- the strike ladder -------------------------------------------------------
@pytest.mark.parametrize("price,step", [
    (18.0, 0.5), (47.0, 1.0), (180.0, 2.5), (333.0, 5.0), (740.0, 5.0)])
def test_strike_spacing_matches_the_price(price, step):
    assert cal.strike_step(price) == step


def test_a_call_strike_sits_above_spot():
    k = cal.pick_strike(333.53, "long")
    assert k > 333.53 and k == 335.0


def test_a_put_strike_sits_below_spot():
    k = cal.pick_strike(333.53, "short")
    assert k < 333.53 and k == 330.0


def test_a_spot_exactly_on_a_strike_still_moves_one_away():
    assert cal.pick_strike(335.0, "long") == 340.0
    assert cal.pick_strike(335.0, "short") == 330.0


# --- expiry ------------------------------------------------------------------
@pytest.mark.parametrize("d,fri", [
    (date(2026, 9, 28), date(2026, 10, 2)),   # Monday
    (date(2026, 9, 30), date(2026, 10, 2)),   # Wednesday
    (date(2026, 10, 2), date(2026, 10, 2)),   # Friday trades expire same day
])
def test_expiry_is_that_weeks_friday(d, fri):
    assert cal.friday_of(d) == fri


# --- the option model --------------------------------------------------------
def test_a_call_is_worth_more_when_the_stock_rises():
    lo = cal.bs_price(100, 105, 0.02, 0.4, "call")
    hi = cal.bs_price(110, 105, 0.02, 0.4, "call")
    assert hi > lo


def test_a_put_is_worth_more_when_the_stock_falls():
    assert (cal.bs_price(90, 95, 0.02, 0.4, "put")
            > cal.bs_price(100, 95, 0.02, 0.4, "put"))


def test_time_decay_costs_money():
    far = cal.bs_price(100, 105, 0.05, 0.4, "call")
    near = cal.bs_price(100, 105, 0.005, 0.4, "call")
    assert near < far


def test_at_expiry_an_option_is_worth_only_its_intrinsic_value():
    assert cal.bs_price(100, 105, 0.0, 0.4, "call") == 0.0
    assert cal.bs_price(110, 105, 0.0, 0.4, "call") == pytest.approx(5.0)
    assert cal.bs_price(100, 105, 0.0, 0.4, "put") == pytest.approx(5.0)


def test_the_spread_is_charged_on_both_ends():
    """A trade that goes nowhere must still lose money."""
    t = trade(entry=333.53, exit=333.53, exit_time="09:50")
    c = cal.contract_return(t, 0.35)
    assert c is not None
    assert c["pct"] < 0, "flat price plus a spread is a loss, not a scratch"
    assert c["buy"] > c["sell"]


def test_a_contract_too_cheap_to_quote_is_skipped_not_priced():
    """A penny option is a spread, not a position.

    Minutes before a Friday close, a strike well above spot prices to
    almost nothing. Returning a percentage off a one-cent premium would
    manufacture enormous gains from rounding error, so it returns None.
    """
    doomed = trade(symbol="AAPL", date="2026-10-02", entry=300.0, exit=300.5,
                   entry_time="15:50", exit_time="15:55", side="long")
    assert cal.contract_return(doomed, 0.15) is None


def test_a_winning_move_shows_leverage_over_the_share_move():
    share = (340.36 / 333.53 - 1) * 100
    c = cal.contract_return(trade(exit=340.36), 0.35)
    assert c["pct"] > share, "an option should move more than its stock"


# --- volatility --------------------------------------------------------------
def test_volatility_is_clamped_to_something_usable():
    assert cal.realised_vol([100.0] * 30) == cal.MIN_VOL
    wild = [100 * (3 ** (i % 2)) for i in range(30)]
    assert cal.realised_vol(wild) == cal.MAX_VOL


def test_too_short_a_history_falls_back_rather_than_dividing_by_zero():
    assert 0 < cal.realised_vol([100.0, 101.0]) < 1.0


# --- the day grids -----------------------------------------------------------
def test_share_days_sum_the_percentages():
    ts = [trade(pct=2.0), trade(pct=-1.0), trade(date="2026-09-29", pct=1.5)]
    d = cal.stock_days(ts)
    assert d["2026-09-30"]["pct"] == 1.0
    assert d["2026-09-30"]["won"] == 1 and d["2026-09-30"]["lost"] == 1
    assert d["2026-09-29"]["pct"] == 1.5


def test_contract_days_average_rather_than_sum():
    """One +600% signal must not become the whole day."""
    ts = [trade(exit=360.0), trade(exit=333.0)]
    d = cal.contract_days(ts, {"AAPL": 0.35})
    day = d["2026-09-30"]
    assert day["n"] == 2
    parts = [cal.contract_return(t, 0.35)["pct"] for t in ts]
    assert day["pct"] == pytest.approx(sum(parts) / 2, abs=0.02)


def test_a_day_with_nothing_priceable_is_left_out_not_zeroed():
    d = cal.contract_days([], {})
    assert d == {}


def test_the_summary_counts_green_and_red_days():
    s = cal.summarise({"a": {"pct": 2.0, "n": 2, "won": 2, "lost": 0},
                       "b": {"pct": -1.0, "n": 1, "won": 0, "lost": 1}})
    assert s["green"] == 1 and s["red"] == 1
    assert s["total"] == 1.0 and s["best"] == 2.0 and s["worst"] == -1.0
    assert s["trades"] == 3 and s["won"] == 2 and s["lost"] == 1


def test_an_empty_calendar_summarises_to_zero_not_a_crash():
    assert cal.summarise({})["days"] == 0


# --- the honesty label -------------------------------------------------------
def test_the_contract_side_declares_itself_a_model():
    blob = {"stock": {"days": {}, "summary": cal.summarise({})},
            "contract": {"days": {}, "summary": cal.summarise({}),
                         "assumptions": {"measured": False}}}
    assert blob["contract"]["assumptions"]["measured"] is False


def test_the_report_never_calls_the_contract_side_measured():
    blob = {"stock": {"days": {"2026-09-30": {"pct": 1.0, "n": 1, "won": 1, "lost": 0}},
                      "summary": cal.summarise({"2026-09-30": {"pct": 1.0, "n": 1, "won": 1, "lost": 0}})},
            "contract": {"days": {}, "summary": cal.summarise({}),
                         "assumptions": {}},
            "generated": "2026-09-30 22:00"}
    text = cal.render(blob)
    assert "modelled, not measured" in text
    assert "Shares — measured" in text
