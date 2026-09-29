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
    line = w.row(1.0, 2.0, w.tally([{"pct": 1.0, "reason": "stop"}]))
    assert "R" not in line


def test_a_level_target_that_falls_back_is_detectable():
    """Rows identical to the multiple's row are how a broken level target
    hides. The report has to be able to say the level was never used."""
    src = open("src/widths.py").read()
    assert "Did the level target actually get used?" in src
    assert "Never used." in src
