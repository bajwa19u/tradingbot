"""Stop width and target: the rescue/cost accounting has to be symmetric."""
from __future__ import annotations

import pytest

from src import widths as w
from src import opening as op


def t(sym, date, when, side, pct, reason="stop"):
    return {"symbol": sym, "date": date, "entry_time": when, "side": side,
            "pct": pct, "reason": reason}


def test_a_rescued_loser_is_counted_once():
    base = [t("AMD", "2026-09-29", "09:36", "short", -1.0)]
    wide = [t("AMD", "2026-09-29", "09:36", "short", +2.0, "target")]
    assert w.rescue_count(base, wide) == (1, 0, 0)


def test_a_loser_that_fails_from_further_away_is_counted_as_worse():
    """The half of the trade that gets forgotten. If this ever stops being
    counted, every wider stop will look free."""
    base = [t("AMD", "2026-09-29", "09:36", "short", -1.0)]
    wide = [t("AMD", "2026-09-29", "09:36", "short", -2.4)]
    assert w.rescue_count(base, wide) == (0, 1, 0)


def test_a_winner_is_never_called_a_rescue():
    base = [t("AMD", "2026-09-29", "09:36", "short", +2.0, "target")]
    wide = [t("AMD", "2026-09-29", "09:36", "short", +2.0, "target")]
    assert w.rescue_count(base, wide) == (0, 0, 1)


def test_trades_are_matched_on_identity_not_position():
    base = [t("AMD", "2026-09-29", "09:36", "short", -1.0),
            t("NVDA", "2026-09-29", "09:36", "short", -1.0)]
    wide = [t("NVDA", "2026-09-29", "09:36", "short", +2.0, "target"),
            t("AMD", "2026-09-29", "09:36", "short", -1.0)]
    assert w.rescue_count(base, wide) == (1, 0, 1)


def test_an_unmatched_trade_is_skipped_not_guessed():
    base = [t("AMD", "2026-09-29", "09:36", "short", -1.0)]
    assert w.rescue_count(base, []) == (0, 0, 0)


def test_the_same_symbol_on_two_days_is_two_trades():
    base = [t("AMD", "2026-09-29", "09:36", "short", -1.0),
            t("AMD", "2026-09-30", "09:36", "short", -1.0)]
    wide = [t("AMD", "2026-09-29", "09:36", "short", +2.0, "target"),
            t("AMD", "2026-09-30", "09:36", "short", -1.0)]
    assert w.rescue_count(base, wide) == (1, 0, 1)


# --- the sweep grid ----------------------------------------------------------
def test_the_grid_includes_doing_nothing():
    assert 0.0 in w.PADS, "the no-change control has to be in the comparison"
    assert w.OPENING["target_r"] in w.TARGETS


def test_the_grid_includes_a_structural_target():
    assert "level" in w.TARGETS


def test_a_level_variant_switches_mode_rather_than_setting_a_multiple():
    q = w.variant(dict(op.BASE), 1.0, "level")
    assert q["target_mode"] == "level"
    assert q["target_r"] == op.BASE["target_r"], "the multiple is untouched"


def test_variant_only_changes_the_things_under_test():
    p = dict(op.BASE)
    q = w.variant(p, 1.0, 3.0)
    assert q["stop_pad_pct"] == 1.0 and q["target_r"] == 3.0
    keys = ("stop_pad_pct", "target_r", "target_mode")
    assert {k: v for k, v in q.items() if k not in keys} == \
           {k: v for k, v in p.items() if k not in keys}


def test_settings_come_from_the_live_bot():
    p = w.cfg()
    assert p["stop_mode"] == w.OPENING["stop_mode"]
    for k in ("enabled", "observe", "post_sides"):
        assert k not in p


# --- reporting ---------------------------------------------------------------
def test_tally_separates_average_win_from_average_loss():
    r = w.tally([{"pct": 2.0, "reason": "target"},
                 {"pct": -1.0, "reason": "stop"},
                 {"pct": -3.0, "reason": "stop"}])
    assert r["avg_win"] == pytest.approx(2.0)
    assert r["avg_loss"] == pytest.approx(-2.0)
    assert r["n"] == 3 and r["won"] + r["lost"] == 3


def test_unfinished_trades_are_excluded():
    r = w.tally([{"pct": 2.0, "reason": "target"}, {"pct": 9.9, "reason": "open"}])
    assert r["n"] == 1


def test_rows_never_mention_r_multiples():
    line = w.row(5, 1.0, 2.0, w.tally([{"pct": 1.0, "reason": "stop"}]))
    assert "R" not in line


def test_a_level_target_that_falls_back_is_detectable():
    """Rows identical to the multiple's row are how a broken level target
    hides. The report has to be able to say the level was never used."""
    src = open("src/widths.py").read()
    assert "Did the level target actually get used?" in src
    assert "Never used." in src


# --- opening-range length as a swept dimension -------------------------------
def test_the_range_length_travels_in_the_config():
    q = w.variant(dict(op.BASE), 1.0, 2.0, 30)
    assert q["or_minutes"] == 30


def test_omitting_the_range_leaves_it_alone():
    p = {**op.BASE, "or_minutes": 5}
    assert w.variant(p, 1.0, 2.0)["or_minutes"] == 5


def test_the_default_range_list_is_the_live_one():
    assert w.ORS == [5], "the sweep must default to what actually trades"


def test_a_longer_range_produces_a_wider_band():
    """A 30-minute range cannot be narrower than the 5-minute range inside
    it. If it ever is, the range is being built from the wrong bars."""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    import pandas as pd
    E = ZoneInfo("America/New_York")
    idx, rows, px = [], [], 100.0
    for k in range(40):
        hh, mm = 9 + (30 + k) // 60, (30 + k) % 60
        idx.append(datetime(2026, 9, 29, hh, mm, tzinfo=E))
        px += 0.1
        rows.append({"open": px, "high": px + 0.2, "low": px - 0.2,
                     "close": px, "volume": 1000})
    day = pd.DataFrame(rows, index=pd.DatetimeIndex(idx))
    five, _ = op.opening_range(day, 5)
    thirty, _ = op.opening_range(day, 30)
    assert thirty["orh"] - thirty["orl"] >= five["orh"] - five["orl"]
    assert thirty["orh"] >= five["orh"] and thirty["orl"] <= five["orl"]


def test_every_range_length_gets_the_same_window():
    """A longer range with a fixed 10:00 close is starved, not tested."""
    q5 = w.variant(dict(op.BASE), 0.0, 2.0, 5)
    q30 = w.variant(dict(op.BASE), 0.0, 2.0, 30)
    assert q5["win_after_range_min"] == q30["win_after_range_min"] == w.WIN_AFTER
