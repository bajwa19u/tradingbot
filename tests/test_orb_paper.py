"""The ORB paper record: observation only, and identical to the research.

What matters here is not that it records something. It is that it posts and
trades nothing, that it never reads a bar before that bar has closed, that a
late sighting is marked as late, and that the live view and the research
code agree on the same day's bars.
"""
from __future__ import annotations

import ast
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src import inplay_bot as ib
from src import orb_paper as op
from src import orb_research as orr

ET = "America/New_York"
TODAY = pd.Timestamp("2026-09-30").date()
SRC = Path(__file__).resolve().parent.parent / "src"


def session(day, closes, vol, rng_half=0.5):
    idx = pd.date_range(pd.Timestamp(day).tz_localize(ET) + pd.Timedelta(hours=9, minutes=30),
                        periods=390, freq="min")
    c = np.asarray(closes, float)
    o = np.concatenate([[c[0]], c[:-1]])
    return pd.DataFrame({"open": o, "high": np.maximum(o, c) + 0.01, "low": np.minimum(o, c) - 0.01,
                         "close": c, "volume": np.asarray(vol, float)}, index=idx.tz_convert("UTC"))


def flat_day(day, swing=0.5):
    """A quiet session ranging +-swing around 100."""
    return session(day, 100 + swing * np.sin(np.linspace(0, 6 * np.pi, 390)), np.full(390, 1e6))


def breakout_today():
    """Range 99.6-100.4 in the first five minutes (0.8 of a ~1.0 ATR), first close
    above it on minute 12 (09:42), then a slow drift up into the bell."""
    c = np.full(390, 100.0)
    c[:5] = [99.6, 100.4, 100.0, 99.7, 100.2]
    c[5:12] = 100.1
    c[12:] = np.linspace(100.6, 101.5, 378)
    v = np.full(390, 1e6)
    v[:5] = 3e6                                   # three times its usual opening volume
    return session(TODAY, c, v)


def quiet_today():
    c = np.full(390, 100.0)
    c[:5] = [99.6, 100.4, 100.0, 99.7, 100.2]
    return session(TODAY, c, np.full(390, 1e6))


class FakeMarket:
    def __init__(self):
        prior = pd.bdate_range(end=pd.Timestamp(TODAY) - pd.Timedelta(days=1), periods=22)
        self.frames = {}
        for s, today in (("SPY", quiet_today()), ("QQQ", quiet_today()),
                         ("AAA", breakout_today()), ("BBB", quiet_today())):
            self.frames[s] = pd.concat([flat_day(d) for d in prior] + [today])
        self.calls = []

    def intraday_bars(self, symbols, minutes, start, end=None):
        self.calls.append((tuple(symbols), start, end))
        out = {}
        for s in symbols:
            df = self.frames[s]
            d = df.index.tz_convert(ET).date
            keep = d >= pd.Timestamp(start).date()
            if end:
                keep &= d < pd.Timestamp(end).date()
            out[s] = df[keep]
        return out


@pytest.fixture
def feed(monkeypatch, tmp_path):
    monkeypatch.setattr(orr, "POOL", ["AAA", "BBB", "QQQ", "SPY"])
    monkeypatch.setattr(op, "STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(op, "LEDGER", tmp_path / "ledger.csv")
    monkeypatch.setattr(op, "SUMMARY", tmp_path / "summary.md")
    monkeypatch.setattr(op, "_FEED", None)
    return op.Feed(FakeMarket())


def at(hhmmss):
    return pd.Timestamp(f"{TODAY} {hhmmss}", tz=ET)


def blank():
    return op.load_state(str(TODAY))


# --- it is observation only ---------------------------------------------------
def test_it_never_posts():
    assert op.POST is False


def test_it_imports_nothing_that_posts_or_trades():
    tree = ast.parse((SRC / "orb_paper.py").read_text())
    names = {a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for a in n.names}
    names |= {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    for banned in ("discord_msg", "broker", "autotrade", "notify", "paper"):
        assert banned not in names


def test_the_candidate_is_the_one_the_research_chose():
    assert op.CANDIDATE == orr.P(universe="top10", orw=(0.35, 9e9), window_end=15, manage="be")
    assert (op.CANDIDATE.window_end, op.CANDIDATE.stop, op.CANDIDATE.target, op.CANDIDATE.manage) == (15, "D", 2.0, "be")


# --- live detection -----------------------------------------------------------
def test_picks_by_opening_volume_and_finds_the_break(feed):
    st = blank()
    new = feed.scan(st, at("09:43:05"))
    assert st["picks"][0] == "AAA"
    assert [(r["symbol"], r["side"], r["bar"]) for r in new] == [("AAA", "long", "09:42")]
    assert new[0]["latency_s"] == pytest.approx(5.0)
    assert new[0]["expired"] is False


def test_a_bar_that_has_not_closed_is_not_used(feed):
    st = blank()
    assert feed.scan(st, at("09:42:50")) == []          # 09:42 bar closes at 09:43


def test_a_signal_is_recorded_once(feed):
    st = blank()
    feed.scan(st, at("09:43:05"))
    assert feed.scan(st, at("09:44:05")) == []
    assert len(st["signals"]) == 1


def test_a_late_sighting_is_marked_expired(feed):
    st = blank()
    new = feed.scan(st, at("09:50:05"))
    assert new and new[0]["expired"] is True and new[0]["latency_s"] > op.MAX_AGE_S


def test_nothing_after_the_entry_window(feed):
    st = blank()
    assert feed.scan(st, at("10:30:00")) == []


def test_history_is_fetched_once_a_day(feed):
    st = blank()
    feed.scan(st, at("09:43:05"))
    n = sum(1 for _, _, end in feed.md.calls if end)
    feed.scan(st, at("09:44:05"))
    assert sum(1 for _, _, end in feed.md.calls if end) == n


# --- the live view and the research agree -------------------------------------
def test_live_signal_matches_the_research_on_the_full_day(feed):
    st = blank()
    feed.scan(st, at("09:43:05"))
    rows = feed.settle(st, at("16:01:00"))
    assert len(rows) == 1
    r = rows[0]
    assert r["backtest_agrees"] == "yes"
    assert r["exit_reason"] in ("bell", "target", "stop")
    assert r["win"] is True and r["result_pct"] > 0


def test_a_day_never_watched_live_still_gets_the_backtest_view(feed):
    st = blank()
    rows = feed.settle(st, at("16:01:00"))
    assert [(r["symbol"], r["source"], r["backtest_agrees"]) for r in rows] == [("AAA", "backtest only", "missed live")]


# --- the loop -------------------------------------------------------------------
def test_tick_writes_the_ledger_and_a_summary_without_R(feed, monkeypatch):
    monkeypatch.setattr(op, "_FEED", feed)
    op.tick(at("09:43:05"), lambda: None)
    op.tick(at("16:13:00"), lambda: None, quotes_factory=None)
    assert op.LEDGER.exists()
    text = op.SUMMARY.read_text()
    assert "win %" in text and "100%" in text
    assert " R " not in text and "R per" not in text          # house rule: never R
    op.tick(at("16:14:00"), lambda: None, quotes_factory=None)                      # settles once
    assert len(pd.read_csv(op.LEDGER)) == 1


def test_dry_run_writes_nothing(feed, monkeypatch):
    monkeypatch.setattr(op, "_FEED", feed)
    op.tick(at("09:43:05"), lambda: None, dry_run=True)
    op.tick(at("16:13:00"), lambda: None, dry_run=True, quotes_factory=None)
    assert not op.LEDGER.exists() and not op.STATE_FILE.exists()


def test_weekends_do_nothing(feed, monkeypatch):
    monkeypatch.setattr(op, "_FEED", feed)
    op.tick(pd.Timestamp("2026-10-03 09:43:05", tz=ET), lambda: None)
    assert feed.md.calls == []


def test_a_paper_failure_never_stops_the_inplay_channel(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("no data")
    monkeypatch.setattr(op, "tick", boom)
    ib.paper_tick(at("09:43:05"), dry_run=True)               # must not raise


# --- real costs ------------------------------------------------------------------
class FakeQuotes:
    """A one-cent-wide market around the bar's own price."""
    def __init__(self, fm):
        self.fm = fm

    def quotes(self, symbol, start, end, limit=100):
        t = pd.Timestamp(start)
        df = self.fm.frames[symbol]
        px = float(df[df.index <= t].close.iloc[-1])
        return [{"bp": px - 0.005, "ap": px + 0.005}]


def test_settle_measures_real_costs_from_quotes(feed):
    feed.quotes_md = FakeQuotes(feed.md)
    st = blank()
    feed.scan(st, at("09:43:05"))
    r = feed.settle(st, at("16:13:00"))[0]
    assert 0 < r["entry_cost_pct"] < 0.01          # half-spread plus a few seconds of drift
    assert r["exit_cost_pct"] is not None and r["result_real_pct"] is not None
    # half a cent each way is far cheaper than the assumed 0.05% a side
    assert r["result_real_pct"] > r["result_pct"]


def test_a_quote_far_from_the_bar_is_not_a_cost(feed):
    class Split(FakeQuotes):
        def quotes(self, *a, **k):
            return [{"bp": 49.99, "ap": 50.01}]            # unadjusted price after a 2-for-1 split
    feed.quotes_md = Split(feed.md)
    st = blank()
    feed.scan(st, at("09:43:05"))
    r = feed.settle(st, at("16:13:00"))[0]
    assert r.get("entry_cost_pct") is None and r.get("result_real_pct") is None


def test_settling_waits_for_the_quote_delay():
    assert op.SETTLE_AFTER >= "16:12"
