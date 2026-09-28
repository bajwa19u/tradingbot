"""The opening-drive rule, proven on hand-built days.

The point of every test here is the same: this rule exists because the old
one could not see the first fifteen minutes, so the things worth proving are
that it does see them, that it is not secretly reading the future, and that
it still refuses the trades it should refuse.
"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from src import opening as op

EASTERN = ZoneInfo("America/New_York")


def frame(day: str, rows: list[tuple[str, float, float, float, float, float]]
          ) -> pd.DataFrame:
    y, m, d = map(int, day.split("-"))
    idx, data = [], []
    for hhmm, o, h, l, c, v in rows:
        hh, mm = map(int, hhmm.split(":"))
        idx.append(datetime(y, m, d, hh, mm, tzinfo=EASTERN))
        data.append({"open": o, "high": h, "low": l, "close": c, "volume": v})
    return pd.DataFrame(data, index=pd.DatetimeIndex(idx))


def minutes(day, start, n, o, step, rng=0.5, vol=1000):  # noqa: PLR0913
    """n one-minute bars walking by `step` a bar."""
    hh, mm = map(int, start.split(":"))
    rows, px = [], o
    for k in range(n):
        t = f"{hh + (mm + k) // 60:02d}:{(mm + k) % 60:02d}"
        nxt = px + step
        rows.append((t, px, max(px, nxt) + rng, min(px, nxt) - rng, nxt, vol))
        px = nxt
    return frame(day, rows)


@pytest.fixture
def prior():
    """A prior session that sets pdh=105, pdl=95, pdc=100, scale=1.0."""
    return frame("2026-09-24", [
        ("09:30", 100.0, 105.0, 99.5, 104.0, 9_000),
        ("09:31", 104.0, 104.5, 103.5, 104.0, 9_000),
        ("09:32", 104.0, 104.5, 103.5, 104.0, 9_000),
        ("09:33", 104.0, 104.5, 103.5, 104.0, 9_000),
        ("09:34", 104.0, 104.5, 103.5, 104.0, 9_000),
        ("09:35", 104.0, 104.5, 103.5, 104.0, 9_000),
        ("15:00", 104.0, 104.5, 95.0, 100.0, 9_000),
    ])


# --- levels ------------------------------------------------------------------
def test_levels_are_the_prior_session_and_the_premarket(prior):
    pre = minutes("2026-09-25", "08:00", 40, 101.0, 0.0, rng=1.0)
    lv = op.session_levels(prior, pre)
    assert lv == {"pdh": 105.0, "pdl": 95.0, "pdc": 100.0,
                  "pmh": 102.0, "pml": 100.0}


def test_a_one_bar_premarket_is_not_a_premarket(prior):
    """The free IEX feed gave AMD a single premarket bar on 28 September, so
    its high and its low were the same number. A level built from that is not
    a level, and using it puts three copies of one trade on the book."""
    pre = frame("2026-09-25", [("08:00", 101.0, 102.0, 100.0, 101.0, 500)])
    assert set(op.session_levels(prior, pre)) == {"pdh", "pdl", "pdc"}


def test_premarket_can_be_switched_off_entirely(prior):
    pre = minutes("2026-09-25", "08:00", 40, 101.0, 0.0, rng=1.0)
    assert set(op.session_levels(prior, pre, use_premarket=False)) == {
        "pdh", "pdl", "pdc"}


def test_only_one_trade_per_symbol_per_day(prior):
    """Yesterday's low and the premarket low sit a few cents apart. Taking
    both is one idea at twice the risk."""
    day = minutes("2026-09-25", "09:30", 15, 99.0, -0.6)
    p = {**op.BASE, "side": "short", "max_per_symbol": 1}
    assert len(op.day_trades(day, prior, p)) == 1
    assert len(op.day_trades(day, prior, {**p, "max_per_symbol": 3})) >= 1


def test_the_session_stop_sits_above_a_spike_the_bar_stop_misses():
    """The AMD failure in one test: break, then a spike to a new session
    high, then the real move. A stop on the level dies in the spike."""
    day = frame("2026-09-25", [
        ("09:30", 100.0, 106.0, 99.0, 99.0, 1000),   # session high 106
        ("09:31", 99.0, 99.5, 98.0, 98.0, 1000)])    # break bar, high 99.5
    bar = op.simulate(day, 1, 1, "short", 100.0, 1.0,
                      {**op.BASE, "stop_mode": "bar"})
    ses = op.simulate(day, 1, 1, "short", 100.0, 1.0,
                      {**op.BASE, "stop_mode": "session"})
    assert ses["stop"] > bar["stop"]
    assert ses["stop"] > 106.0


def test_levels_survive_a_missing_premarket(prior):
    lv = op.session_levels(prior, prior.iloc[:0])
    assert set(lv) == {"pdh", "pdl", "pdc"}


def test_scale_uses_the_prior_days_opening_window(prior):
    # the 09:30-09:35 bars average (105-99.5, then 1.0 x5) -> 1.75
    assert op.minute_scale(prior) == pytest.approx(1.75, abs=1e-9)


def test_scale_of_nothing_is_zero():
    assert op.minute_scale(pd.DataFrame()) == 0.0


# --- the thing this whole module exists for ----------------------------------
def test_catches_a_drive_that_never_retests(prior):
    """The AMD case: straight down from the bell, no pullback, no warmup.

    The old rule missed this three separate ways. If this test ever fails,
    the regression is the entire reason this module was written.
    """
    day = minutes("2026-09-25", "09:30", 12, 99.0, -0.6)   # opens under pdc
    p = {**op.BASE, "entry_mode": "drive", "side": "short"}
    trades = op.day_trades(day, prior, p)
    assert trades, "a drive off the open must produce a trade"
    t = trades[0]
    assert t["side"] == "short"
    assert t["entry_time"] < "09:45", "the whole point is entering before 09:45"


def test_the_retest_mode_is_what_missed_it(prior):
    """Same day, retest mode: correctly produces nothing. Proves the two
    modes genuinely differ rather than both quietly taking the trade."""
    day = minutes("2026-09-25", "09:30", 12, 99.0, -0.6)
    p = {**op.BASE, "entry_mode": "retest", "side": "short"}
    assert op.day_trades(day, prior, p) == []


def test_entry_can_happen_on_the_very_first_bar(prior):
    """09:30 opens above the prior low and the first bar closes under it.
    The old rule could not have an opinion here; this one must."""
    day = frame("2026-09-25", [
        ("09:30", 96.0, 96.1, 92.8, 93.0, 5000),
        ("09:31", 93.0, 93.2, 92.0, 92.2, 5000)])
    brk = op.opening_breaks(day, {"pdl": 95.0}, 1.0, {**op.BASE, "side": "short"})
    assert brk and brk[0][0] == 0 and brk[0][3] == "pdl"


# --- no peeking --------------------------------------------------------------
def test_side_is_decided_by_the_open_not_by_the_outcome(prior):
    """A level above the 09:30 open is resistance even if price later
    collapses through it. Deciding that after the fact is look-ahead."""
    day = minutes("2026-09-25", "09:30", 20, 101.0, 0.4)
    lv = {"pdh": 105.0}
    brk = op.opening_breaks(day, lv, 1.0, {**op.BASE, "side": "both"})
    assert brk and brk[0][1] == "long"


def test_nothing_outside_the_window_is_taken(prior):
    day = minutes("2026-09-25", "10:05", 30, 99.0, -0.5)
    assert op.day_trades(day, prior, {**op.BASE, "side": "short"}) == []


def test_only_the_first_break_of_each_level_counts(prior):
    rows = [("09:30", 100.5, 100.6, 98.0, 98.0, 1000),  # breaks pdc = 100
            ("09:31", 98.0, 101.0, 97.9, 100.5, 1000),  # recovers above it
            ("09:32", 100.5, 100.6, 98.0, 98.2, 1000)]  # breaks it again
    day = frame("2026-09-25", rows)
    brk = op.opening_breaks(day, {"pdc": 100.0}, 1.0, {**op.BASE, "side": "short"})
    assert len(brk) == 1 and brk[0][0] == 0


def test_a_level_already_broken_at_the_open_is_not_a_long(prior):
    """Opening below a level makes it resistance-turned... nothing. It is
    support that is already gone, and it must not become a long signal."""
    day = minutes("2026-09-25", "09:30", 10, 90.0, -0.3)
    brk = op.opening_breaks(day, {"pdl": 95.0}, 1.0, {**op.BASE, "side": "long"})
    assert brk == []


# --- refusals ----------------------------------------------------------------
def test_penetration_rejects_a_nick_through_the_level(prior):
    day = frame("2026-09-25", [
        ("09:30", 100.4, 100.5, 99.8, 99.9, 1000),   # 0.1 through pdc
        ("09:31", 99.9, 100.0, 99.7, 99.8, 1000)])
    loose = op.opening_breaks(day, {"pdc": 100.0}, 1.0,
                              {**op.BASE, "pen": 0.0, "side": "short"})
    strict = op.opening_breaks(day, {"pdc": 100.0}, 1.0,
                               {**op.BASE, "pen": 0.5, "side": "short"})
    assert loose and not strict


def test_a_close_back_through_the_level_kills_the_retest(prior):
    day = frame("2026-09-25", [
        ("09:30", 99.0, 99.1, 97.0, 97.2, 1000),     # break of pdc
        ("09:31", 97.2, 100.8, 97.1, 100.6, 1000)])  # closes back above
    p = {**op.BASE, "entry_mode": "retest", "retest_depth": 0.5, "side": "short"}
    assert op.entry_index(day, 0, "short", 100.0, 1.0, p) is None


def test_a_dead_symbol_is_skipped(prior):
    flat = frame("2026-09-24", [("09:30", 100.0, 100.0, 100.0, 100.0, 10)] * 1)
    day = minutes("2026-09-25", "09:30", 10, 99.0, -0.5)
    assert op.day_trades(day, flat, dict(op.BASE)) == []


def test_an_unsizeable_stop_is_refused(prior):
    day = minutes("2026-09-25", "09:30", 10, 99.0, -0.5)
    # a scale so wide the stop is more than 10% away
    p = {**op.BASE, "stop_mult": 200.0, "side": "short"}
    assert op.simulate(day, 0, 0, "short", 100.0, 5.0, p) is None


# --- trade mechanics ---------------------------------------------------------
def test_stop_wins_ties_within_a_bar():
    """One bar that touches both stop and target must be filed as the loss.
    Resolving it the other way is the cheapest way to fake a good backtest."""
    day = frame("2026-09-25", [
        ("09:30", 99.0, 99.0, 99.0, 99.0, 1000),
        ("09:31", 99.0, 110.0, 90.0, 99.0, 1000)])
    t = op.simulate(day, 0, 0, "short", 100.0, 1.0,
                    {**op.BASE, "stop_mode": "level", "stop_mult": 1.0})
    assert t["reason"] == "stop" and t["pct"] < 0


def test_slippage_hurts_both_ends():
    day = frame("2026-09-25", [
        ("09:30", 99.0, 99.0, 99.0, 99.0, 1000),
        ("09:31", 99.0, 99.0, 90.0, 90.0, 1000)])
    p = {**op.BASE, "stop_mult": 1.0, "target_r": 2.0}
    t = op.simulate(day, 0, 0, "short", 100.0, 1.0, p)
    assert t["entry"] < 99.0, "a short fills below the close, not at it"
    assert t["reason"] == "target"
    assert t["r"] < 2.0, "slippage must cost something"


def test_the_hold_limit_closes_a_drifting_trade():
    rows = [("09:30", 99.0, 99.0, 99.0, 99.0, 1000)]
    for k in range(1, 200):
        hh, mm = 9 + (30 + k) // 60, (30 + k) % 60
        rows.append((f"{hh:02d}:{mm:02d}", 99.0, 99.2, 98.9, 99.0, 1000))
    day = frame("2026-09-25", rows)
    t = op.simulate(day, 0, 0, "short", 100.0, 1.0, dict(op.BASE))
    assert t["reason"] == "time"
    assert t["exit_time"] <= "11:31", "must be out within the hold limit"


# --- reporting ---------------------------------------------------------------
def test_tally_counts_winners_and_losers_consistently():
    trades = [{"pct": 2.0, "side": "short"}, {"pct": -1.0, "side": "short"},
              {"pct": 2.0, "side": "long"}]
    t = op.tally(trades, {"target_r": 2.0, "risk_pct": 1.0})
    assert t["n"] == t["won"] + t["lost"] == 3
    assert t["won"] == 2 and t["win_pct"] == pytest.approx(66.7)
    assert t["profit_pct"] == pytest.approx(3.0)
    assert t["short"]["n"] == 2 and t["long"]["n"] == 1


def test_breakeven_matches_the_target():
    # win 1 in 3 when a winner pays twice what a loser costs
    assert op.tally([], {"target_r": 2.0})["breakeven_win_pct"] == 33.3
    assert op.tally([], {"target_r": 3.0})["breakeven_win_pct"] == 25.0
    assert op.tally([], {"target_r": 1.0})["breakeven_win_pct"] == 50.0


def test_noise_floor_shrinks_with_more_trades():
    assert op.noise_floor(100, 24, 2.0) > op.noise_floor(10_000, 24, 2.0) > 0


def test_grid_is_small_enough_to_interpret():
    g = op.grid()
    assert len(g) == 36
    assert len({c["name"] for c in g}) == 36


def test_reports_never_mention_r_multiples():
    """The one formatting rule that is not negotiable: results are reported
    in win %, profit %, winners and losers."""
    row = op.fmt_row("x", op.tally([{"pct": 1.0, "side": "short"}],
                                   {"target_r": 2.0, "risk_pct": 1.0}))
    assert "R" not in row and "r=" not in row
