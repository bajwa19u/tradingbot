"""The hold-cap study: does the clock get put back, and does varying it work."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from src import holds
from src import opening as op

EASTERN = ZoneInfo("America/New_York")


def drifting_day(minutes: int = 300, step: float = -0.02) -> pd.DataFrame:
    """A day that grinds slowly in one direction — never stops, never targets,
    so the ONLY thing that closes it is the clock."""
    rows, idx, px = [], [], 100.0
    for k in range(minutes):
        hh, mm = 9 + (30 + k) // 60, (30 + k) % 60
        if hh > 15 or (hh == 15 and mm > 58):
            break
        idx.append(datetime(2026, 9, 29, hh, mm, tzinfo=EASTERN))
        nxt = px + step
        rows.append({"open": px, "high": max(px, nxt) + 0.01,
                     "low": min(px, nxt) - 0.01, "close": nxt, "volume": 1000})
        px = nxt
    return pd.DataFrame(rows, index=pd.DatetimeIndex(idx))


# --- the clock is put back ---------------------------------------------------
def test_the_cap_is_restored_afterwards():
    before = op.MAX_HOLD_MIN
    with holds.with_cap(30):
        assert op.MAX_HOLD_MIN == 30
    assert op.MAX_HOLD_MIN == before


def test_the_cap_is_restored_even_when_the_block_raises():
    """It mutates a module global. A leak here silently rewrites the costs of
    every later run in the same process."""
    before = op.MAX_HOLD_MIN
    with pytest.raises(RuntimeError):
        with holds.with_cap(30):
            raise RuntimeError("boom")
    assert op.MAX_HOLD_MIN == before


def test_zero_means_no_cap_not_instant_exit():
    """`0` reads like 'close immediately'. It must mean the opposite."""
    with holds.with_cap(0):
        assert op.MAX_HOLD_MIN >= 1000


# --- the cap actually changes the exit ---------------------------------------
def test_a_tighter_cap_closes_a_drifter_sooner():
    day = drifting_day()
    with holds.with_cap(30):
        short = op.simulate(day, 0, 0, "short", 101.0, 1.0, dict(op.BASE))
    with holds.with_cap(120):
        longer = op.simulate(day, 0, 0, "short", 101.0, 1.0, dict(op.BASE))
    assert short["exit_time"] < longer["exit_time"]
    assert short["reason"] == longer["reason"] == "time"


def test_no_cap_lets_a_drifter_reach_the_bell():
    """Drift gentle enough that it never reaches the target — so the only
    thing left that can close it is the closing bell."""
    day = drifting_day(minutes=400, step=-0.002)
    with holds.with_cap(0):
        t = op.simulate(day, 0, 0, "short", 101.0, 1.0, dict(op.BASE))
    assert t["reason"] == "time" and t["exit_time"] >= "15:55"


def test_letting_a_winner_run_beats_capping_it():
    """A position drifting the right way should end up better with more
    time. If this ever inverts, the exit logic is wrong, not the market."""
    day = drifting_day(step=-0.02)          # falling, so a short gains
    with holds.with_cap(30):
        early = op.simulate(day, 0, 0, "short", 101.0, 1.0, dict(op.BASE))
    with holds.with_cap(0):
        late = op.simulate(day, 0, 0, "short", 101.0, 1.0, dict(op.BASE))
    assert late["pct"] > early["pct"]


# --- config comes from the live bot ------------------------------------------
def test_the_settings_are_the_live_bots_own():
    """Retyping them here is how a study quietly stops describing the thing
    that actually trades."""
    from src.live_bot import OPENING
    p = holds.cfg()
    assert p["levels"] == OPENING["levels"]
    assert p["entry_mode"] == OPENING["entry_mode"]
    assert p["stop_mode"] == OPENING["stop_mode"]
    assert p["target_r"] == OPENING["target_r"]


def test_runtime_only_keys_are_dropped():
    p = holds.cfg()
    for k in ("enabled", "observe", "post_sides"):
        assert k not in p


# --- reporting ---------------------------------------------------------------
def test_the_no_cap_row_is_labelled_in_english():
    assert holds.label(0) == "no cap (stop/target/bell)"
    assert holds.label(120) == "120 min"


def test_caps_include_the_live_setting_and_the_extremes():
    assert 120 in holds.CAPS, "the live cap must be in the comparison"
    assert 0 in holds.CAPS, "so must no cap at all"


def test_tally_is_consistent_and_ignores_unfinished():
    t = holds.tally([{"pct": 2.0, "reason": "target"},
                     {"pct": -1.0, "reason": "stop"},
                     {"pct": 0.5, "reason": "open"}])
    assert t["n"] == 2 and t["won"] + t["lost"] == 2
    assert t["profit_pct"] == pytest.approx(1.0)


def test_rows_never_mention_r_multiples():
    assert "R" not in holds.row("120 min", holds.tally([{"pct": 1.0,
                                                         "reason": "stop"}]))
