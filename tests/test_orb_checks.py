"""The checks behind the open questions: the pieces that decide a number.

A cost measured from a bad quote, a premarket ratio that peeks at today, or a
paper-API call that could ever place an order would each make the report say
something false; these pin them.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src import orb_checks as oc
from src import orb_research as orr

SRC = Path(__file__).resolve().parent.parent / "src"


def test_first_sane_quote_skips_empty_crossed_and_wide_ones():
    qs = [{"bp": 0, "ap": 10.0}, {"bp": 10.02, "ap": 10.01}, {"bp": 9.0, "ap": 10.0},
          {"bp": 10.00, "ap": 10.01}]
    assert oc.first_nbbo(qs) == (10.00, 10.01)
    assert oc.first_nbbo([]) is None


def test_reprice_takes_the_round_trip_off_in_units_of_risk():
    rows = pd.DataFrame({"R": [1.0, -1.0], "risk_pct": [1.0, 2.0]})
    out = oc.reprice(rows, pd.Series([0.001, 0.001]))      # 0.1% of price round trip
    assert out.R.tolist() == pytest.approx([0.9, -1.05])


class _X:                                                  # a stand-in Day
    pass


def test_premarket_ratio_uses_only_earlier_sessions():
    days = {d: _X() for d in pd.bdate_range("2026-01-01", periods=20).date}
    ds = sorted(days)
    pm = {"AAA": {d: 100.0 for d in ds}}
    pm["AAA"][ds[-1]] = 300.0
    oc.attach_pm({"AAA": days}, pm)
    assert days[ds[-1]].pm_rvol == pytest.approx(3.0)
    assert np.isnan(days[ds[5]].pm_rvol)                   # fewer than 10 earlier sessions: no ratio


def test_no_premarket_trades_means_zero_not_missing():
    days = {d: _X() for d in pd.bdate_range("2026-01-01", periods=20).date}
    ds = sorted(days)
    pm = {"AAA": {d: 100.0 for d in ds[:-1]}}               # nothing traded before today's bell
    oc.attach_pm({"AAA": days}, pm)
    assert days[ds[-1]].pm_rvol == 0.0


def test_premarket_selection_ranks_by_the_premarket_ratio(monkeypatch):
    monkeypatch.setattr(orr, "POOL", ["AAA", "BBB", "SPY", "QQQ"])
    d = pd.Timestamp("2026-01-05").date()
    def day(rv, pm):
        x = _X(); x.prev_c, x.adv, x.rvol5, x.pm_rvol = 50.0, 1e8, rv, pm
        return x
    D = {"AAA": {d: day(5.0, 1.0)}, "BBB": {d: day(1.0, 4.0)}}
    assert orr.select(D, d, "top1") == ["AAA"]
    assert orr.select(D, d, "pm1") == ["BBB"]


def test_the_checks_only_ever_read_from_the_paper_api():
    src = (SRC / "orb_checks.py").read_text()
    assert "https://api.alpaca.markets" not in src
    assert "/v2/assets" in src and "/v2/orders" not in src and "requests.post" not in src


def test_quotes_are_never_asked_for_inside_the_15_minute_window():
    now = pd.Timestamp.now(tz=oc.ET)
    assert (now - pd.Timestamp(oc.sip_end())).total_seconds() >= 15 * 60
