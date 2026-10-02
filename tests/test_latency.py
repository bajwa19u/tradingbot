"""Signal speed: poll on the bar boundary, fetch only what changed, never post
a stale or late signal as if it were fresh. 1 October posted ten opening
signals together at 10:13, 13-43 minutes after their bars closed."""
from __future__ import annotations

import json

import pandas as pd
import pytest

from src import autotrade
from src import live_bot as lb

ET = "America/New_York"


def trade(**kw):
    base = {"id": "X-1", "rule": "opening", "symbol": "AMD", "side": "short",
            "entry_time": "09:31", "entry": 622.21, "stop": 627.42, "target": 611.78,
            "shares": 3, "risk": 15.6, "level": 625.80, "level_name": "pdl", "exit": None,
            "exit_time": None, "reason": None, "pct": None, "cash": None,
            "observe": False, "post": True}
    return {**base, **kw}


def wire(monkeypatch, tmp_path, trades, posts):
    monkeypatch.setattr(lb, "STATE", tmp_path)
    monkeypatch.setattr(lb, "REPORTS", tmp_path)
    monkeypatch.setattr(lb, "scan", lambda cfg: ([], "09:40", False))
    monkeypatch.setattr(lb, "opening_scan", lambda cfg, now: [dict(t) for t in trades])
    monkeypatch.setattr(lb.dm, "post", lambda url, text: posts.append(text) or f"m{len(posts)}")
    monkeypatch.setattr(lb.dm, "edit", lambda url, m, text: True)
    monkeypatch.setattr(lb.autotrade, "ENABLED", False)


def test_poll_wakes_just_after_the_minute_closes():
    now = pd.Timestamp("2026-10-01 09:30:57", tz=ET)
    assert lb.seconds_to_next_poll(now, 60) == pytest.approx(60 - 57 + lb.BAR_LAG_S)
    now = pd.Timestamp("2026-10-01 09:31:04.5", tz=ET)
    assert lb.seconds_to_next_poll(now, 45) == pytest.approx(59.5)


def test_signal_age_counts_from_the_bar_close():
    now = pd.Timestamp("2026-10-01 09:32:05", tz=ET)
    assert lb.signal_age(trade(entry_time="09:31"), now) == pytest.approx(5)          # 1-min bar closed 09:32
    assert lb.signal_age(trade(rule="retest", entry_time="09:50"), now.replace(hour=9, minute=55, second=3)) \
        == pytest.approx(3)                                                            # 5-min bar closed 09:55


def test_a_fresh_signal_shows_its_age_and_is_not_expired(monkeypatch, tmp_path):
    posts = []
    wire(monkeypatch, tmp_path, [trade(id="f1")], posts)
    monkeypatch.setattr(lb, "signal_age", lambda t, now: 6.0)
    lb.tick({"equity": 2000.0, "risk_pct": 1.0}, dry_run=False)
    assert "⏱ 6s" in posts[0] and "EXPIRED" not in posts[0]
    assert len(posts[0].splitlines()) == 5


def test_a_late_signal_is_posted_as_expired_and_remembered(monkeypatch, tmp_path):
    posts = []
    wire(monkeypatch, tmp_path, [trade(id="late")], posts)
    monkeypatch.setattr(lb, "signal_age", lambda t, now: 13 * 60.0)
    lb.tick({"equity": 2000.0, "risk_pct": 1.0}, dry_run=False)
    assert "EXPIRED" in posts[0] and "13 min late" in posts[0]
    seen = json.loads((tmp_path / lb.SEEN_FILE).read_text())
    assert "late" in seen["expired"]
    rows = [json.loads(x) for x in (tmp_path / lb.LATENCY_FILE).read_text().splitlines()]
    assert any(r["kind"] == "signal" and r["id"] == "late" and r["expired"] for r in rows)
    assert any(r["kind"] == "tick" and "total" in r for r in rows)


def test_stale_data_suppresses_new_signals_and_warns_once(monkeypatch, tmp_path):
    posts = []
    wire(monkeypatch, tmp_path, [trade(id="s1")], posts)
    monkeypatch.setattr(lb, "stale_since", lambda now: pd.Timestamp("2026-10-01 10:02", tz=ET))
    lb.tick({"equity": 2000.0, "risk_pct": 1.0}, dry_run=False)
    lb.tick({"equity": 2000.0, "risk_pct": 1.0}, dry_run=False)
    assert sum("DATA WARNING" in x for x in posts) == 1          # warned once, not every tick
    assert not any("AMD" in x for x in posts)                   # the signal itself was held back


def test_the_auto_trader_never_buys_an_expired_signal():
    class Paper:
        def orders_since(self, *_): return []
        def positions(self): return []
        def chain(self, *a, **k): raise AssertionError("tried to buy an expired signal")
    now = pd.Timestamp("2026-10-01 10:00:30", tz=ET)
    t = trade(id="e1", entry_time="09:59", expired=True)
    assert autotrade.run([t], now, Paper()) == []


def test_prior_days_are_fetched_once_then_only_today(monkeypatch):
    calls = []
    idx_y = pd.date_range("2026-09-30 15:58", periods=2, freq="1min", tz="UTC").tz_convert(ET)
    idx_t = pd.date_range("2026-10-01 13:30", periods=3, freq="1min", tz="UTC").tz_convert(ET)

    class MD:
        def intraday_bars(self, syms, minutes, start, end=None, extended=False):
            calls.append(start)
            frame = lambda ix: pd.DataFrame({"open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1.0}, index=ix)
            if len(calls) == 1:
                return {"AMD": frame(idx_y.append(idx_t[:2]))}
            return {"AMD": frame(idx_t)}
    lb._PRIOR.clear()
    now = pd.Timestamp("2026-10-01 09:33", tz=ET)
    first = lb._minute_bars(MD(), now)
    second = lb._minute_bars(MD(), now)
    assert calls[0] == "2026-09-25" and calls[1] == "2026-10-01"
    assert len(first["AMD"]) == 4 and len(second["AMD"]) == 5      # yesterday's 2 + today's 3, no duplicates
    assert second["AMD"].index.is_monotonic_increasing
