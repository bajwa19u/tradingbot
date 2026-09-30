"""Buying into earnings: the windows, the benchmark, and the era split."""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from src import preearn as pe


def series(start="2024-01-01", n=400, step=0.1, base=100.0):
    idx = pd.bdate_range(start, periods=n)
    return pd.DataFrame({"Close": base + np.arange(n) * step}, index=idx)


def flat(start="2024-01-01", n=400, base=100.0):
    idx = pd.bdate_range(start, periods=n)
    return pd.DataFrame({"Close": [base] * n}, index=idx)


# --- the window --------------------------------------------------------------
def test_it_sells_before_the_report_never_through_it():
    px, bm = series(), flat()
    d = px.index[200].date()
    r = pe.run_up(px, bm, d, 21)
    assert r["sell"] < d, "the position must be closed before the announcement"


def test_the_holding_window_is_the_length_asked_for():
    px, bm = series(), flat()
    d = px.index[200].date()
    for w in (21, 42, 63):
        r = pe.run_up(px, bm, d, w)
        held = np.busday_count(r["buy"], r["sell"])
        assert abs(held - w) <= 3, f"{w}: got {held} business days"


def test_a_report_too_early_in_the_history_is_skipped():
    px, bm = series(), flat()
    assert pe.run_up(px, bm, px.index[5].date(), 63) is None


# --- the benchmark, which is the whole point ---------------------------------
def test_a_stock_that_only_matched_the_market_scores_zero():
    """A stock that rose 5% before every report during a bull market has
    found nothing. Excess return is what stops that being a discovery."""
    px = series(step=0.1)
    r = pe.run_up(px, px.copy(), px.index[200].date(), 21)
    assert r["excess"] == pytest.approx(0.0, abs=0.01)
    assert r["stock"] > 0, "it did rise — it just did not beat anything"


def test_beating_the_market_shows_up_as_positive_excess():
    r = pe.run_up(series(step=0.2), series(step=0.05),
                  series().index[200].date(), 21)
    assert r["excess"] > 0 and r["excess"] < r["stock"]


def test_losing_to_the_market_shows_up_as_negative_excess():
    r = pe.run_up(series(step=0.05), series(step=0.2),
                  series().index[200].date(), 21)
    assert r["excess"] < 0


# --- scoring -----------------------------------------------------------------
def test_the_hit_rate_leads_and_one_huge_quarter_does_not_carry_it():
    """Reliability is the claim being tested, not a single lucky run."""
    rows = [{"excess": 40.0}] + [{"excess": -1.0} for _ in range(9)]
    s = pe.score(rows)
    assert s["hit"] == 10.0 and s["median"] < 0
    assert s["mean"] > 0, "the mean is exactly what would mislead here"


def test_a_short_history_cannot_qualify():
    s = {"n": 4, "hit": 100.0, "median": 5.0}
    assert not pe.qualifies(s, 65.0, 1.0), "four reports is not a pattern"


def test_qualifying_needs_both_reliability_and_size():
    assert not pe.qualifies({"n": 20, "hit": 90.0, "median": 0.1}, 65.0, 1.0)
    assert not pe.qualifies({"n": 20, "hit": 40.0, "median": 9.0}, 65.0, 1.0)
    assert pe.qualifies({"n": 20, "hit": 70.0, "median": 2.0}, 65.0, 1.0)


# --- the era split -----------------------------------------------------------
def test_the_test_year_is_held_back():
    rows = [{"report": date(2024, 5, 1), "excess": 1.0},
            {"report": date(2025, 12, 31), "excess": 2.0},
            {"report": date(2026, 2, 1), "excess": 3.0}]
    sel, test = pe.split(rows)
    assert len(sel) == 2 and len(test) == 1
    assert test[0]["report"].year == 2026


def test_the_cutoff_day_itself_belongs_to_selection():
    sel, test = pe.split([{"report": date(2025, 12, 31), "excess": 1.0}])
    assert len(sel) == 1 and not test


# --- the universe ------------------------------------------------------------
def test_the_universe_is_not_just_tech():
    u = set(pe.UNIVERSE)
    for name, probe in (("banks", {"JPM", "GS"}), ("health", {"UNH", "LLY"}),
                        ("energy", {"XOM", "CVX"}), ("staples", {"KO", "PG"}),
                        ("industrials", {"CAT", "HON"}),
                        ("utilities", {"NEE", "DUK"})):
        assert probe & u, f"no {name} in the universe"
    assert len(pe.UNIVERSE) == len(set(pe.UNIVERSE)) >= 150


def test_reports_never_mention_r_multiples():
    assert "R" not in pe.row("AAPL", pe.score([{"excess": 1.0}]))
