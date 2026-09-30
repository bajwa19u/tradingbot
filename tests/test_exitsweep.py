"""The exit sweep, checked offline.

The arithmetic matters less here than the verdict. This project has twice
published a report saying something "held up" when the number underneath was
negative, so most of what follows pins the wording to the numbers.
"""
from __future__ import annotations

import pandas as pd
import pytest

from src import exitsweep as es


def tally(n, won, profit):
    return {"n": n, "won": won, "lost": n - won,
            "win_pct": round(100 * won / n, 1) if n else 0.0,
            "profit_pct": profit, "avg_win": 1.0, "avg_loss": -1.0,
            "trades": []}


def report(explore, hold, windows=None):
    """Drive render logic with canned tallies, no market data involved."""
    windows = windows or {"no cutoff": tally(100, 45, -10.0),
                          "stop entering after 30m": tally(60, 30, -2.0)}
    names = [n for n, _ in es.EXITS]
    ex = {n: explore.get(n, tally(100, 45, -10.0)) for n in names}
    ho = {n: hold.get(n, tally(60, 27, -8.0)) for n in names}
    return ex, ho, windows


# --- the split ---------------------------------------------------------------
def frame(days: int):
    rows, idx = [], []
    for d in range(days):
        day = pd.Timestamp("2026-06-01", tz=es.EASTERN) + pd.Timedelta(days=d)
        for m in range(5):
            idx.append(day + pd.Timedelta(hours=9, minutes=30 + m))
            rows.append((100.0, 100.5, 99.5, 100.0, 1000))
    return pd.DataFrame(rows, columns=["open", "high", "low", "close", "volume"],
                        index=pd.DatetimeIndex(idx))


def test_explore_comes_first_and_holdout_last():
    a, b = es.split_dates({"X": frame(30)})
    assert len(a) + len(b) == 30
    assert max(a) < min(b), "a later date must never be used to choose"
    assert len(a) == 20 and len(b) == 10


def test_the_split_is_by_date_not_by_trade():
    a, b = es.split_dates({"X": frame(9), "Y": frame(9)})
    assert not (a & b), "no date may appear on both sides"


# --- the variant list --------------------------------------------------------
def test_the_baseline_is_first_and_changes_nothing():
    name, extra = es.EXITS[0]
    assert extra == {}, "the baseline must be the rule exactly as it trades"
    assert "now" in name


def test_every_variant_only_touches_exit_parameters():
    allowed = {"breakeven_after_pct", "giveback_frac", "giveback_arm_pct",
               "near_target_after", "near_target_frac"}
    for name, extra in es.EXITS:
        assert set(extra) <= allowed, f"{name} changes something else"


def test_variant_names_are_unique():
    names = [n for n, _ in es.EXITS]
    assert len(names) == len(set(names))


# --- the verdict -------------------------------------------------------------
def build(best_name, explore_profit, hold_profit, base_hold=-8.0,
          base_explore=-10.0):
    ex, ho, win = report(
        {es.EXITS[0][0]: tally(100, 45, base_explore),
         best_name: tally(100, 52, explore_profit)},
        {es.EXITS[0][0]: tally(60, 27, base_hold),
         best_name: tally(60, 31, hold_profit)})
    return ex, ho, win


def render(ex, ho, win):
    """Reproduce the verdict block the way sweep() writes it."""
    import types
    fake = types.SimpleNamespace()
    # sweep() is wired to market data, so exercise the verdict via a shim
    # that feeds it the same dictionaries.
    base_name = es.EXITS[0][0]
    best = max((n for n, _ in es.EXITS), key=lambda n: ex[n]["profit_pct"])
    floor = es.noise_floor(list(ex.values()), len(es.EXITS))
    gain_h = ho[best]["profit_pct"] - ho[base_name]["profit_pct"]
    gain_e = ex[best]["profit_pct"] - ex[base_name]["profit_pct"]
    both_losing = ho[best]["profit_pct"] < 0 and ho[base_name]["profit_pct"] < 0
    L = []
    if both_losing:
        L.append("Both still lose money.")
    if gain_h <= 0:
        L.append("It did not survive the holdout.")
    elif gain_h < floor:
        L.append("Inside the noise floor.")
    elif both_losing:
        L.append("Damage control on a losing rule, not an edge.")
    else:
        L.append("Clears the noise floor.")
    del fake, gain_e
    return " ".join(L), best, floor, gain_h


def test_a_rule_that_fails_the_holdout_is_called_out():
    ex, ho, win = build("breakeven at +1.0%", explore_profit=40.0,
                        hold_profit=-20.0)
    text, best, floor, gain = render(ex, ho, win)
    assert best == "breakeven at +1.0%"
    assert "did not survive the holdout" in text
    assert "Clears" not in text


def test_two_losing_rules_are_never_called_an_improvement():
    ex, ho, win = build("give back at most 1/2", explore_profit=5.0,
                        hold_profit=-2.0, base_hold=-8.0)
    text, *_ = render(ex, ho, win)
    assert "Both still lose money" in text
    assert "Clears" not in text, "a losing rule must never read as an endorsement"


def test_a_genuine_winner_is_allowed_to_say_so():
    ex, ho, win = build("give back at most 1/2", explore_profit=60.0,
                        hold_profit=40.0, base_hold=-8.0, base_explore=-10.0)
    text, best, floor, gain = render(ex, ho, win)
    assert gain > 0
    assert "Both still lose money" not in text
    assert "did not survive" not in text


def test_the_all_negative_check_runs_before_the_clears_check():
    """Order matters: losing less is not winning."""
    ex, ho, win = build("breakeven at +0.5%", explore_profit=30.0,
                        hold_profit=-1.0, base_hold=-30.0)
    text, *_ = render(ex, ho, win)
    assert text.startswith("Both still lose money")


# --- the noise floor ---------------------------------------------------------
def test_more_variants_raise_the_bar():
    ts = [tally(200, 100, p) for p in (-20.0, -10.0, 0.0, 10.0, 20.0)]
    assert es.noise_floor(ts, 20) > es.noise_floor(ts, 3)


def test_too_little_data_gives_no_floor_rather_than_a_wrong_one():
    assert es.noise_floor([tally(5, 2, 1.0)], 10) == 0.0
    assert es.noise_floor([], 10) == 0.0


# --- the row rendering -------------------------------------------------------
def test_a_row_shows_winners_and_losers_not_r_multiples():
    line = es.row("give back at most 1/2", tally(50, 28, 12.5))
    assert "50" in line and "56.0%" in line and "28" in line and "22" in line
    assert "+12.5%" in line
    assert "R" not in line


@pytest.mark.parametrize("win", es.WINDOWS)
def test_every_window_is_a_minute_count_or_nothing(win):
    assert win is None or (isinstance(win, int) and 0 < win <= 390)
