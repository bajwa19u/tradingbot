"""Confidence levels, and the card that shows them.

The levels are buckets from reports/orb_autopsy.md, so the thing worth
testing is not that the function returns a string - it is that the buckets
match the ones that were measured, that a missing input produces no level
rather than a wrong one, and that the card no longer prints a share count.
"""
from __future__ import annotations

import pytest

from src import confidence as cf
from src import live_bot as lb


def trade(**kw) -> dict:
    base = {"symbol": "AAPL", "side": "long", "rule": "opening",
            "entry_time": "09:49", "entry": 333.53, "stop": 330.12,
            "target": 340.36, "shares": 5, "exit": None}
    return {**base, **kw}


# --- the buckets -------------------------------------------------------------
def test_with_the_gap_and_a_crowd_is_high():
    assert cf.level(trade(with_gap=True, cohort=5)) == cf.HIGH
    assert cf.level(trade(with_gap=True, cohort=40)) == cf.HIGH


def test_with_the_gap_but_alone_is_medium():
    assert cf.level(trade(with_gap=True, cohort=4)) == cf.MEDIUM
    assert cf.level(trade(with_gap=True, cohort=1)) == cf.MEDIUM


def test_against_the_gap_is_low_however_big_the_crowd():
    assert cf.level(trade(with_gap=False, cohort=50)) == cf.LOW


def test_the_crowd_threshold_is_the_one_that_was_measured():
    """Five, because that is the bucket the autopsy tested and reported."""
    assert cf.CROWD == 5


# --- missing inputs ----------------------------------------------------------
def test_no_level_rather_than_a_guess():
    assert cf.level(trade(cohort=9)) is None            # no with_gap
    assert cf.level(trade(with_gap=True)) is None       # no cohort
    assert cf.level(trade()) is None


def test_a_trade_with_no_level_gets_no_badge():
    assert cf.note(trade()) == ""


# --- the two inputs ----------------------------------------------------------
@pytest.mark.parametrize("gap,side,expected", [
    (1.5, "long", True),      # gapped up, breaking up
    (1.5, "short", False),    # gapped up, breaking down
    (-1.5, "short", True),
    (-1.5, "long", False),
])
def test_with_gap_matches_direction(gap, side, expected):
    assert cf.with_gap(gap, side) is expected


def test_gap_is_measured_against_yesterdays_close():
    assert cf.gap_pct(102.0, 100.0) == pytest.approx(2.0)
    assert cf.gap_pct(99.0, 100.0) == pytest.approx(-1.0)
    assert cf.gap_pct(100.0, 0.0) == 0.0          # no division by zero


def test_minutes_are_counted_from_the_bell():
    assert cf.minute_of("09:30") == 0
    assert cf.minute_of("09:49") == 19
    assert cf.minute_of("10:05") == 35


def test_the_study_and_the_bot_count_minutes_the_same_way():
    """If these ever diverge the labels stop meaning what they measured."""
    from src import orb_autopsy as oa
    assert oa.minute_of is cf.minute_of


# --- the crowd count ---------------------------------------------------------
def test_cohort_counts_only_the_same_side_and_nearby_in_time():
    ts = [trade(side="long", minute=10), trade(side="long", minute=15),
          trade(side="long", minute=19), trade(side="short", minute=12),
          trade(side="long", minute=45)]
    cf.tag(ts)
    assert [t["cohort"] for t in ts] == [3, 3, 3, 1, 1]


def test_a_trade_counts_itself_so_alone_means_one():
    ts = [trade(side="long", minute=10)]
    cf.tag(ts)
    assert ts[0]["cohort"] == 1


def test_trades_without_a_minute_are_left_alone():
    ts = [trade(side="long"), trade(side="long", minute=10)]
    cf.tag(ts)
    assert "cohort" not in ts[0]
    assert cf.level(ts[0]) is None


# --- the card ----------------------------------------------------------------
def test_the_open_card_no_longer_prints_a_share_count():
    text = lb.card(trade(with_gap=True, cohort=8, shares=5))
    assert "share" not in text
    assert "5 " not in text.replace("5.", "").replace("5,", "")


def test_the_open_card_shows_the_level():
    text = lb.card(trade(with_gap=True, cohort=8))
    assert "HIGH" in text
    assert "8 names breaking together" in text


def test_the_open_card_still_shows_the_prices():
    text = lb.card(trade(with_gap=True, cohort=8))
    for want in ("LONG AAPL", "333.53", "330.12", "340.36", "opening range"):
        assert want in text


def test_a_losing_card_keeps_the_level_it_was_given():
    text = lb.card(trade(with_gap=True, cohort=9, exit=330.10,
                         exit_time="10:12", reason="stop", pct=-1.02))
    assert "HIGH" in text
    assert "-1.02%" in text
    assert "❌" in text
    assert "share" not in text


def test_a_low_confidence_card_says_low():
    text = lb.card(trade(side="short", with_gap=False, cohort=12))
    assert "LOW" in text
    assert "against the overnight gap" in text


def test_a_card_without_the_inputs_still_renders():
    text = lb.card(trade())
    assert "LONG AAPL" in text
    assert "HIGH" not in text and "MED" not in text and "LOW" not in text
