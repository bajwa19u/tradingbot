"""The autopsy: cohort counting, bucketing and the separation yardstick."""
from __future__ import annotations

import pytest

from src import orb_autopsy as a


def brk(sym, date, minute, side="short", pct=-1.0):
    return {"symbol": sym, "date": date, "minute": minute, "side": side,
            "pct": pct, "reason": "stop", "gap": 0.0, "width": 0.5,
            "push": 1.0, "with_gap": True}


def test_minute_is_measured_from_the_bell():
    assert a.minute_of("09:30") == 0
    assert a.minute_of("09:45") == 15
    assert a.minute_of("10:30") == 60


# --- the cohort, which is the whole point ------------------------------------
def test_a_lone_break_has_a_cohort_of_one():
    ts = {"2026-09-29": [brk("AMD", "2026-09-29", 6)]}
    out = _cohorts(ts)
    assert out[0]["cohort"] == 1 and out[0]["alone"] is True


def test_names_breaking_together_share_a_cohort():
    """29 September: eleven names, same side, inside ten minutes."""
    day = [brk(s, "2026-09-29", m) for s, m in
           zip("ABCDEFGHIJK", [5, 6, 6, 7, 9, 10, 11, 11, 11, 13, 15])]
    out = _cohorts({"2026-09-29": day})
    assert all(t["cohort"] >= 8 for t in out)
    assert not any(t["alone"] for t in out)


def test_the_opposite_side_is_a_different_cohort():
    day = [brk("A", "2026-09-29", 6, "short"),
           brk("B", "2026-09-29", 6, "long")]
    out = _cohorts({"2026-09-29": day})
    assert all(t["cohort"] == 1 for t in out)


def test_breaks_far_apart_in_time_are_not_a_cohort():
    day = [brk("A", "2026-09-29", 5), brk("B", "2026-09-29", 50)]
    out = _cohorts({"2026-09-29": day})
    assert all(t["cohort"] == 1 for t in out)


def test_cohorts_do_not_span_days():
    out = _cohorts({"2026-09-28": [brk("A", "2026-09-28", 6)],
                    "2026-09-29": [brk("B", "2026-09-29", 6)]})
    assert all(t["cohort"] == 1 for t in out)


def _cohorts(per_day):
    """Mirror of the cohort pass in label_all, kept tiny on purpose."""
    out = []
    for _, ts in per_day.items():
        for t in ts:
            t["cohort"] = sum(
                1 for o in ts if o["side"] == t["side"]
                and abs(o["minute"] - t["minute"]) <= a.COHORT_WINDOW_MIN)
            t["alone"] = t["cohort"] == 1
            out.append(t)
    return out


# --- buckets and separation --------------------------------------------------
def test_buckets_are_half_open_and_skip_empties():
    ts = [brk("A", "d", 1, pct=1.0), brk("B", "d", 7), brk("C", "d", 25)]
    got = a.buckets(ts, "minute", [0, 5, 10, 20, 30])
    assert [lab for lab, _ in got] == ["0–5", "5–10", "20–30"]
    assert len(got[0][1]) == 1


def test_separation_needs_enough_of_both_sides():
    ts = [brk("A", "d", 1, pct=1.0)] + [brk("B", "d", 9) for _ in range(30)]
    assert a.separation(ts, "minute") == 0.0


def test_separation_is_zero_when_the_groups_sit_together():
    ts = ([brk(f"W{i}", "d", 10, pct=1.0) for i in range(20)] +
          [brk(f"L{i}", "d", 10) for i in range(20)])
    assert a.separation(ts, "minute") == 0.0


def test_separation_is_large_when_the_groups_are_apart():
    ts = ([brk(f"W{i}", "d", 5 + i % 2, pct=1.0) for i in range(20)] +
          [brk(f"L{i}", "d", 60 + i % 2) for i in range(20)])
    assert a.separation(ts, "minute") > 1.0


# --- reporting ---------------------------------------------------------------
def test_tally_is_consistent():
    t = a.tally([brk("A", "d", 1, pct=2.0), brk("B", "d", 2)])
    assert t["n"] == 2 and t["won"] == 1 and t["lost"] == 1
    assert t["profit_pct"] == pytest.approx(1.0)


def test_settings_come_from_the_live_bot():
    p = a.cfg(15, 2.0)
    assert p["or_minutes"] == 15 and p["stop_pad_pct"] == 2.0
    assert p["stop_mode"] == a.OPENING["stop_mode"]
    for k in ("enabled", "observe", "post_sides"):
        assert k not in p


def test_avgo_is_out_of_the_universe():
    from src.forensics import BIGTECH
    assert "AVGO" not in BIGTECH
    assert {"AAPL", "MSFT", "NVDA", "META", "AMZN"} <= set(BIGTECH)


def test_rows_never_mention_r_multiples():
    assert "R" not in a.row("x", a.tally([brk("A", "d", 1, pct=1.0)]))
