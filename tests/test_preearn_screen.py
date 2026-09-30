"""The two-gate screen, checked without touching the network.

Two things here are guards against mistakes already made in this project
rather than hypothetical ones:

  * test_selection_never_sees_the_test_era - the split has to be real.
  * test_report_says_so_when_the_screen_found_nothing - twice now a report
    has announced that something "held up" while the underlying number was
    negative. The verdict text is now part of the test suite.
"""
from __future__ import annotations

from datetime import date

import pytest

from src import fundamentals as fd
from src import preearn_screen as ps


def row(report: date, excess: float) -> dict:
    return {"report": report, "buy": report.replace(day=1), "sell": report,
            "stock": excess, "market": 0.0, "excess": excess}


def rows(year_from: int, n: int, excess: float) -> list[dict]:
    """n reports, one a quarter, starting in January of year_from."""
    out = []
    for i in range(n):
        y, m = year_from + i // 4, (i % 4) * 3 + 1
        out.append(row(date(y, m, 15), excess))
    return out


PASS = fd.Verdict(True, "growing and profitable", growth_hit=0.9,
                  profitable=8, eps_change=1.5)
FAIL = fd.Verdict(False, "revenue grew in only 40% of quarters", growth_hit=0.4)
CUTOFF = date(2022, 12, 31)


def name(sym: str, verdict, rs: list[dict]) -> ps.Name:
    return ps.Name(sym, verdict=verdict, rows=rs)


# --- both gates, not either --------------------------------------------------
def test_a_name_needs_both_gates():
    good = rows(2016, 16, 4.0)                 # 100% hit, +4% median
    names = {
        "BOTH": name("BOTH", PASS, good),
        "HISTORY_ONLY": name("HISTORY_ONLY", FAIL, good),
        "FUNDS_ONLY": name("FUNDS_ONLY", PASS, rows(2016, 16, -3.0)),
    }
    passed, rejected = ps.select(names, CUTOFF)
    assert [s for s, _ in passed] == ["BOTH"]
    assert set(s for s, _ in rejected) == {"HISTORY_ONLY", "FUNDS_ONLY"}


def test_a_name_with_no_fundamental_verdict_cannot_pass():
    names = {"X": name("X", None, rows(2016, 16, 5.0))}
    passed, rejected = ps.select(names, CUTOFF)
    assert not passed
    assert [s for s, _ in rejected] == ["X"]


def test_too_few_reports_is_neither_passed_nor_used_as_a_control():
    names = {"THIN": name("THIN", PASS, rows(2016, 4, 5.0))}
    passed, rejected = ps.select(names, CUTOFF)
    assert not passed and not rejected


def test_selection_never_sees_the_test_era():
    """A name that is dreadful before the cutoff and superb after must fail."""
    before = rows(2016, 16, -5.0)
    after = [row(date(2024, m, 15), 30.0) for m in (1, 4, 7, 10)]
    names = {"LATE": name("LATE", PASS, before + after)}
    passed, _ = ps.select(names, CUTOFF)
    assert not passed
    n = names["LATE"]
    assert all(r["report"] <= CUTOFF for r in n.before(CUTOFF))
    assert all(r["report"] > CUTOFF for r in n.after(CUTOFF))


# --- list size ---------------------------------------------------------------
def test_a_long_list_is_cut_to_the_target():
    passed = [(f"S{i}", {"hit": 90 - i, "median": 2.0, "n": 20})
              for i in range(25)]
    kept, note = ps.trim(passed)
    assert len(kept) == ps.TARGET_MAX
    assert kept[0][0] == "S0", "cut should keep the best, not the first 15"
    assert "kept the top" in note


def test_a_short_list_is_left_short_and_says_so():
    passed = [("A", {"hit": 80, "median": 2.0, "n": 20})]
    kept, note = ps.trim(passed)
    assert len(kept) == 1
    assert "not loosened" in note


# --- the portfolio constraint ------------------------------------------------
def test_capital_limits_how_many_signals_can_be_taken():
    overlapping = [{"report": date(2023, 2, 1), "buy": date(2023, 1, 3),
                    "sell": date(2023, 1, 31), "excess": 5.0}
                   for _ in range(6)]
    sim = ps.portfolio(overlapping, equity=2000.0, max_open=3)
    assert sim["taken"] == 3
    assert sim["skipped"] == 3


def test_positions_free_up_when_they_close():
    seq = [{"report": date(2023, m, 28), "buy": date(2023, m, 1),
            "sell": date(2023, m, 27), "excess": 2.0} for m in (1, 2, 3, 4)]
    sim = ps.portfolio(seq, equity=2000.0, max_open=1)
    assert sim["taken"] == 4 and sim["skipped"] == 0


def test_portfolio_total_is_the_slice_not_the_whole_account():
    one = [{"report": date(2023, 2, 1), "buy": date(2023, 1, 3),
            "sell": date(2023, 1, 31), "excess": 10.0}]
    sim = ps.portfolio(one, equity=3000.0, max_open=3)
    assert sim["total"] == pytest.approx(100.0)   # 10% of a 1000 slice


def test_no_trades_is_not_a_crash():
    assert ps.portfolio([], 2000.0, 3)["taken"] == 0


# --- the report's verdict ----------------------------------------------------
def build(picked_excess: float, rejected_excess: float):
    names = {
        "GOOD": name("GOOD", PASS,
                     rows(2016, 16, 4.0)
                     + [row(date(2023 + i // 4, (i % 4) * 3 + 1, 15),
                            picked_excess) for i in range(8)]),
        "MEH": name("MEH", FAIL,
                    rows(2016, 16, 4.0)
                    + [row(date(2023 + i // 4, (i % 4) * 3 + 1, 15),
                           rejected_excess) for i in range(8)]),
    }
    passed, rejected = ps.select(names, CUTOFF)
    kept, note = ps.trim(passed)
    return ps.render(21, CUTOFF, names, kept, note, rejected, 2000.0, 3)


def test_report_says_so_when_the_screen_found_nothing():
    text = build(picked_excess=1.0, rejected_excess=6.0)
    assert "not selecting anything" in text
    assert "beat the names it rejected" not in text


def test_report_claims_separation_only_when_there_is_some():
    text = build(picked_excess=6.0, rejected_excess=1.0)
    assert "beat the names it rejected" in text
    assert "not selecting anything" not in text


def test_report_counts_the_positive_test_years():
    text = build(picked_excess=3.0, rejected_excess=0.5)
    assert "Positive in 2 of 2 test years." in text


def test_report_is_honest_that_returns_are_excess_over_the_index():
    assert "not the account's total change" in build(4.0, 1.0)


def test_empty_list_renders_without_inventing_a_verdict():
    text = ps.render(21, CUTOFF, {}, [], "nothing passed", [], 2000.0, 3)
    assert "Nothing to test." in text
    assert "%" not in text.split("Nothing to test.")[1]


# --- the whole thing, wired up ----------------------------------------------
# This cannot run against the SEC or Yahoo from here, and a wiring mistake in
# run() would otherwise only show up nine minutes into a live run. So the
# four things that reach the network are replaced and the rest runs for real.
def frame(days: int, drift: float, seed: int):
    import numpy as np
    import pandas as pd
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2014-01-01", periods=days)
    steps = rng.normal(drift, 0.01, days)
    return pd.DataFrame({"Close": 100 * np.exp(np.cumsum(steps))}, index=idx)


@pytest.fixture
def offline(monkeypatch, tmp_path):
    import pandas as pd
    syms = ["AAA", "BBB", "CCC"]
    prices = {s: frame(2600, 0.0004, i) for i, s in enumerate(syms)}
    prices["SPY"] = frame(2600, 0.0003, 99)
    reports = [d.date() for d in
               pd.date_range("2015-02-10", "2026-08-10", freq="QE")]

    monkeypatch.setattr(ps.pe, "daily", lambda *a, **k: prices)
    monkeypatch.setattr(ps.pe, "cik_for",
                        lambda ts: {t: i + 1 for i, t in enumerate(ts)})
    monkeypatch.setattr(ps.pe, "announcement_dates", lambda cik: reports)
    monkeypatch.setattr(ps, "company_facts", lambda cik: {})
    monkeypatch.setattr(ps.fd, "judge",
                        lambda blob, as_of: PASS if blob is not None else FAIL)
    monkeypatch.setattr(ps, "REPORTS", tmp_path)
    return syms


def test_run_produces_a_report_for_every_window(offline):
    text = ps.run(offline, [21, 63], CUTOFF, 2000.0, 3)
    assert "Holding 21 trading days" in text
    assert "Holding 63 trading days" in text
    assert "Selected on reports up to **2022-12-31**" in text


def test_main_writes_the_report_where_it_is_told(offline, tmp_path):
    assert ps.main(["--windows", "21", "--symbols", ",".join(offline)]) == 0
    written = (tmp_path / "preearn_screen.md").read_text()
    assert "Buying into earnings" in written


def test_main_does_not_touch_the_committed_reports_directory(offline):
    import subprocess
    ps.main(["--windows", "21", "--symbols", ",".join(offline)])
    dirty = subprocess.run(["git", "status", "--porcelain", "reports"],
                           capture_output=True, text=True,
                           cwd=ps.REPO_ROOT).stdout.strip()
    assert not dirty, f"the test suite wrote into reports/: {dirty}"
