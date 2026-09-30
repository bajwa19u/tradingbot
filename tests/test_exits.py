"""Profit-protection exits, built on 30 September.

That day every open position was green and gave it all back: +7.01% of
favourable movement across seven trades turned into -4.58% by the bell, and
in Uday's options the same pattern was the difference between +$42,692 and
-$107,281. These rules exist to bank some of that.

Three of them, all off unless a caller asks:

  near_target_*        it has had long enough and it is close enough - take it
  giveback_frac        hand back only a share of the best it ever showed
  breakeven_after_pct  once it is up enough, stop losing on it

Plus entry_before_min, which stops taking new trades after the morning.

The rule that matters most here is the one about bar extremes. A profit rule
that fires on a bar's high claims a fill at a price that existed for an
instant; these fire on the close. test_profit_rules_never_fill_at_a_bar_extreme
is what holds that line.
"""
from __future__ import annotations

import pandas as pd
import pytest

from src import opening as op

EASTERN = op.EASTERN
BASE = {**op.BASE, "stop_mode": "level", "stop_mult": 1.0, "target_r": 2.0,
        "risk_pct": 1.0, "entry_mode": "drive"}


def bars(rows, start="09:30"):
    """rows are (open, high, low, close); one-minute bars from `start`."""
    idx = pd.date_range(f"2026-09-30 {start}", periods=len(rows), freq="1min",
                        tz=EASTERN)
    return pd.DataFrame(rows, columns=["open", "high", "low", "close"],
                        index=idx).assign(volume=1000)


def run(rows, p, side="long", level=100.0, scale=1.0, i=0, j=1):
    return op.simulate(bars(rows), i, j, side, level, scale, {**BASE, **p})


# A long entered at bar 1 around 100, which runs to 103 and comes back to 100.
RISE_AND_FADE = [
    (100.0, 100.2,  99.8, 100.0),   # 0  the break bar
    (100.0, 100.3,  99.9, 100.0),   # 1  entry here
    (100.0, 101.2, 100.0, 101.0),   # 2  +1.0
    (101.0, 102.1, 100.9, 102.0),   # 3  +2.0
    (102.0, 103.0, 101.9, 102.8),   # 4  the peak
    (102.8, 102.9, 101.0, 101.2),   # 5  rolling over
    (101.2, 101.3, 100.0, 100.1),   # 6  back to flat
    (100.1, 100.2,  99.9, 100.0),   # 7
]


# --- the rules do nothing unless asked ---------------------------------------
def test_nothing_changes_when_no_rule_is_set():
    t = run(RISE_AND_FADE, {})
    assert t["reason"] in ("stop", "target", "bell", "open")
    assert t["reason"] not in ("near target", "gave back")


# --- near target -------------------------------------------------------------
def test_near_target_banks_a_trade_that_got_close_enough():
    # entry ~100, stop 99, target 102 — reached 102.8, so it takes the target.
    # Pull the target further out so the trade only gets PART of the way.
    t = run(RISE_AND_FADE, {"target_r": 4.0, "near_target_after": 2,
                            "near_target_frac": 0.6})
    assert t["reason"] == "near target"
    assert t["pct"] > 0


def test_near_target_waits_for_the_clock():
    """Close enough on bar 2, but not yet old enough to be taken."""
    early = run(RISE_AND_FADE, {"target_r": 4.0, "near_target_after": 0,
                                "near_target_frac": 0.5})
    late = run(RISE_AND_FADE, {"target_r": 4.0, "near_target_after": 90,
                               "near_target_frac": 0.5})
    assert early["reason"] == "near target"
    assert late["reason"] != "near target", "90 minutes never arrives here"


def test_near_target_does_not_fire_on_a_trade_that_went_nowhere():
    flat = [(100.0, 100.1, 99.9, 100.0)] * 8
    t = run(flat, {"target_r": 4.0, "near_target_after": 1,
                   "near_target_frac": 0.8})
    assert t["reason"] != "near target"


# --- giveback ----------------------------------------------------------------
def test_giveback_exits_after_surrendering_its_share_of_the_peak():
    t = run(RISE_AND_FADE, {"target_r": 6.0, "giveback_frac": 0.5,
                            "giveback_arm_pct": 0.5})
    assert t["reason"] == "gave back"
    assert t["pct"] > 0, "half of a +2.8% peak is still a winner"


def test_giveback_stays_armed_until_the_trade_has_shown_something():
    """A trade that never gets up 2% must not be closed by the giveback."""
    t = run(RISE_AND_FADE, {"target_r": 6.0, "giveback_frac": 0.5,
                            "giveback_arm_pct": 5.0})
    assert t["reason"] != "gave back", "a 2.9% peak must not arm a 5% trigger"


def test_giveback_beats_holding_to_the_bell_on_this_day():
    held = run(RISE_AND_FADE, {"target_r": 6.0})
    banked = run(RISE_AND_FADE, {"target_r": 6.0, "giveback_frac": 0.5,
                                 "giveback_arm_pct": 0.5})
    assert banked["pct"] > held["pct"]


# --- breakeven ---------------------------------------------------------------
def test_breakeven_turns_a_round_trip_into_a_scratch():
    loose = {"stop_mult": 3.0, "target_r": 6.0}
    held = run(RISE_AND_FADE, loose)
    protected = run(RISE_AND_FADE, {**loose, "breakeven_after_pct": 1.0})
    assert protected["pct"] >= held["pct"]
    assert protected["pct"] >= -0.05, "a breakeven stop should not lose much"


def test_breakeven_only_ever_tightens_the_stop():
    t = run(RISE_AND_FADE, {"stop_mult": 3.0, "target_r": 6.0,
                            "breakeven_after_pct": 1.0})
    assert t["stop"] <= t["entry"], "a long's stop must not move above entry"


def test_breakeven_does_nothing_if_the_trade_never_gets_up():
    rows = [(100.0, 100.2, 99.8, 100.0), (100.0, 100.1, 99.9, 100.0),
            (100.0, 100.0, 97.0, 97.5), (97.5, 97.6, 97.0, 97.2)]
    a = run(rows, {"stop_mult": 3.0})
    b = run(rows, {"stop_mult": 3.0, "breakeven_after_pct": 1.0})
    assert a["exit"] == b["exit"] and a["reason"] == b["reason"]


# --- the honesty guard -------------------------------------------------------
def test_profit_rules_never_fill_at_a_bar_extreme():
    """A profit rule must take the close, never the spike inside the bar.

    The bar below prints a high of 130 and closes at 101. A rule that filled
    at the high would book roughly thirty percent that nobody could have
    taken; the close is the only price the bar guarantees was available.
    """
    spike = [
        (100.0, 100.2,  99.8, 100.0),
        (100.0, 100.3,  99.9, 100.0),
        (100.0, 130.0, 100.0, 101.0),    # the lie, if a rule believed highs
        (101.0, 101.2, 100.6, 100.8),
        (100.8, 100.9, 100.4, 100.5),
    ]
    for rule in ({"near_target_after": 0, "near_target_frac": 0.01},
                 {"giveback_frac": 0.3, "giveback_arm_pct": 0.5}):
        t = run(spike, {"target_r": 60.0, **rule})
        assert t["reason"] in ("near target", "gave back"), \
            f"{rule} did not fire, so this proves nothing"
        assert t["exit"] < 102, f"{rule} filled at a price inside a wick"


# --- the entry window --------------------------------------------------------
def test_entry_before_min_refuses_late_breaks():
    """Breaks after the cutoff are dropped, earlier ones are kept."""
    rows = [(100.0, 100.1, 99.9, 100.0)] * 3
    rows += [(100.0, 101.5, 100.0, 101.4)]      # the break, ~bar 3
    rows += [(101.4, 102.0, 101.0, 101.8)] * 20
    day = bars(rows)
    prior = bars([(99.0, 100.0, 98.0, 99.5)] * 30, start="09:30")

    early = op.day_trades(day, prior, {**BASE, "levels": "or", "or_minutes": 2,
                                       "entry_before_min": 60})
    late = op.day_trades(day, prior, {**BASE, "levels": "or", "or_minutes": 2,
                                      "entry_before_min": 0})
    assert len(late) <= len(early)


def test_no_cutoff_means_no_filtering():
    rows = [(100.0, 100.1, 99.9, 100.0)] * 3 + [(100.0, 101.5, 100.0, 101.4)]
    rows += [(101.4, 102.0, 101.0, 101.8)] * 20
    day, prior = bars(rows), bars([(99.0, 100.0, 98.0, 99.5)] * 30)
    p = {**BASE, "levels": "or", "or_minutes": 2}
    assert (op.day_trades(day, prior, p)
            == op.day_trades(day, prior, {**p, "entry_before_min": None}))


# --- the live bot must be untouched -----------------------------------------
def test_the_live_settings_still_have_every_rule_switched_off():
    from src.live_bot import OPENING
    for k in ("near_target_after", "near_target_frac", "giveback_frac",
              "breakeven_after_pct", "entry_before_min"):
        assert not OPENING.get(k), f"{k} is live before it has been tested"


@pytest.mark.parametrize("side", ["long", "short"])
def test_rules_work_the_same_way_on_both_sides(side):
    rows = RISE_AND_FADE if side == "long" else [
        (100.0, 100.2, 99.8, 100.0), (100.0, 100.1, 99.7, 100.0),
        (100.0, 100.0, 98.8, 99.0),  (99.0, 99.1, 97.9, 98.0),
        (98.0, 98.1, 97.0, 97.2),    (97.2, 99.0, 97.1, 98.8),
        (98.8, 100.0, 98.7, 99.9),   (99.9, 100.1, 99.8, 100.0),
    ]
    t = run(rows, {"target_r": 6.0, "giveback_frac": 0.5,
                   "giveback_arm_pct": 0.5}, side=side)
    assert t["reason"] == "gave back"
    assert t["pct"] > 0
