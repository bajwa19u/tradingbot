"""The in-play ORB rule in the live bot, behind its feature flag.

The things that must hold: the flag defaults to the classic rule; with the
flag on, the live trade is exactly the research's trade; nothing is read
before its bar has closed; a running trade stays open rather than being
closed on bars that have not happened; the card carries every field the
spec asks for and nothing that reads as position size; and a breakout first
seen late goes out as EXPIRED, never as a fresh signal.
"""
from __future__ import annotations

import importlib

import pandas as pd
import pytest

from src import live_bot as lb
from src import orb_live as ol
from src import orb_research as orr
from tests.test_orb_paper import TODAY, FakeMarket, at


@pytest.fixture
def market(monkeypatch, tmp_path):
    monkeypatch.setattr(orr, "POOL", ["AAA", "BBB", "QQQ", "SPY"])
    monkeypatch.setattr(ol, "PICKS_FILE", tmp_path / "picks.json")
    monkeypatch.setattr(ol, "_FEED", None)
    fm = FakeMarket()
    return fm


def scan(fm, when, **kw):
    return ol.scan(at(when), lambda: fm, risk_pct=1.0, **kw)


# --- the flag -------------------------------------------------------------------
def test_the_flag_defaults_to_the_classic_rule(monkeypatch):
    monkeypatch.delenv("DAYTRADE_STRATEGY", raising=False)
    assert lb.strategy() == "classic"


def test_the_shipped_default_is_classic():
    """Off until a forward record passes the gate (reports/orb_research.md)."""
    import os
    if os.environ.get("DAYTRADE_STRATEGY"):
        pytest.skip("flag set in this environment")
    assert importlib.reload(lb).STRATEGY == "classic"


@pytest.mark.parametrize("val,want", [("inplay_orb", "inplay_orb"), (" INPLAY_ORB ", "inplay_orb"),
                                      ("classic", "classic"), ("nonsense", "classic"), ("", "classic")])
def test_the_flag_reads_the_environment(monkeypatch, val, want):
    monkeypatch.setenv("DAYTRADE_STRATEGY", val)
    assert lb.strategy() == want


def test_the_live_bot_runs_the_rule_the_flag_names(monkeypatch):
    called = []
    monkeypatch.setattr(lb, "opening_scan", lambda cfg, now: called.append("classic") or [])
    monkeypatch.setattr(lb, "inplay_orb_scan", lambda cfg, now: called.append("inplay_orb") or [])
    now = at("09:43:05")
    for s in ("classic", "inplay_orb"):
        monkeypatch.setattr(lb, "STRATEGY", s)
        lb.all_trades({"risk_pct": 1.0}, now)
    assert called == ["classic", "inplay_orb"]


def test_the_live_rule_is_the_research_candidate():
    assert ol.RULE == orr.P(universe="top10", orw=(0.35, 9e9), window_end=15, manage="be")


# --- the scan ---------------------------------------------------------------------
def test_the_break_is_found_and_still_open(market):
    trades, newest = scan(market, "09:43:05")
    assert [(t["symbol"], t["side"], t["entry_time"]) for t in trades] == [("AAA", "long", "09:42")]
    t = trades[0]
    assert t["exit"] is None and t["reason"] is None and t["pct"] is None
    assert t["rule"] == "inplay_orb" and t["rank"] == 1 and t["rvol5"] == pytest.approx(3.0, rel=0.05)
    assert newest is not None


def test_nothing_before_the_breakout_bar_closes(market):
    assert scan(market, "09:42:59")[0] == []


def test_nothing_before_the_range_is_complete(market):
    assert scan(market, "09:34:30")[0] == []


def test_the_live_trade_matches_the_research_trade(market):
    trades, _ = scan(market, "16:01:00")
    t = trades[0]
    f = ol.feed(lambda: market)
    D = f.today_days(["AAA", "SPY", "QQQ"], at("16:01:00"), orr.N_MIN)
    sig = orr.first_signal(D["AAA"], D["SPY"].c > D["SPY"].vwap, D["QQQ"].c > D["QQQ"].vwap, ol.RULE, orr.FLAT_IDX - 1)
    R, j, why = orr.exit_r(D["AAA"], sig["kk"], sig["sign"], sig["entry"], sig["stop"], ol.RULE)
    assert (t["entry"], t["stop"], t["target"]) == (round(sig["entry"], 2), round(sig["stop"], 2), round(sig["target"], 2))
    assert t["reason"] == why and t["pct"] == pytest.approx(round(R, 2))


def test_picks_are_saved_once_and_reused(market):
    scan(market, "09:36:05")
    saved = ol.PICKS_FILE.read_text()
    market.frames["BBB"].loc[:, "volume"] *= 50          # a later re-rank would now pick BBB first
    scan(market, "09:50:05")
    assert ol.PICKS_FILE.read_text() == saved


def test_a_dry_run_saves_no_picks(market):
    scan(market, "09:36:05", dry_run=True)
    assert not ol.PICKS_FILE.exists()


# --- the card -----------------------------------------------------------------------
def _open_trade(market):
    return scan(market, "09:43:05")[0][0]


def test_the_card_has_every_field(market):
    t = {**_open_trade(market), "age_s": 5.0}
    text = lb.card(t)
    for want in ("LONG AAA", "Entry", "SL", "TP", "R:R 1:2.0", "signal 09:43:00 ET", "⏱ 5s",
                 "in play", "range", "of daily ATR", "ORB · Stocks in Play"):
        assert want in text, want


def test_the_card_prints_no_money_and_no_share_count(market):
    text = lb.card(_open_trade(market))
    assert "$" not in text and "share" not in text.lower()


def test_a_closed_card_shows_the_result(market):
    t = scan(market, "16:01:00")[0][0]
    text = lb.card(t)
    assert t["exit"] is not None and f"{t['pct']:+.2f}%" in text


def test_a_late_breakout_is_never_posted_as_fresh(market, monkeypatch, tmp_path):
    """Bot starts at 09:50: the 09:42 break is 7 minutes old and must go out EXPIRED."""
    monkeypatch.setattr(lb, "STRATEGY", "inplay_orb")
    monkeypatch.setattr(lb, "STATE", tmp_path)
    monkeypatch.setattr(lb, "_md", lambda: market)
    when = at("09:50:05")
    monkeypatch.setattr(lb.pd.Timestamp, "now", classmethod(lambda cls, tz=None: when))
    sent = []
    monkeypatch.setattr(lb, "print", lambda *a, **k: sent.append(" ".join(map(str, a))), raising=False)
    lb.tick({"risk_pct": 1.0, "equity": 100000}, dry_run=True)
    entry = [m for m in sent if "AAA" in m]
    assert entry and "EXPIRED" in entry[0]
