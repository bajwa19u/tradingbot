"""The trial run: labelled as a trial on every message, and never touching the live record."""
from __future__ import annotations

import pandas as pd

from src import orb_live as ol
from src import orb_research as orr
from src import orb_trial as tr
from tests.test_orb_paper import FakeMarket, at


def test_every_message_is_marked_as_a_trial(monkeypatch, tmp_path, capsys):
    fm = FakeMarket()
    monkeypatch.setattr(orr, "POOL", ["AAA", "BBB", "QQQ", "SPY"])
    monkeypatch.setattr(orr, "BIG_TECH", ["AAA", "BBB"])
    monkeypatch.setattr(tr, "MarketData", lambda *a, **k: fm)
    monkeypatch.setattr(ol, "PICKS_FILE", tmp_path / "live_picks.json")
    monkeypatch.setattr(tr.pd.Timestamp, "now", classmethod(lambda cls, tz=None: at("13:00:00")))
    posted = []
    monkeypatch.setattr(tr.dm, "post", lambda url, text: posted.append(text) or "m")
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://example.invalid/hook")
    try:
        assert tr.main(["--post"]) == 0
    finally:
        ol.use("inplay_orb")
    assert len(posted) >= 3 and all(m.startswith(tr.BANNER) for m in posted)
    assert any("LONG AAA" in m for m in posted)
    assert "Trial summary" in posted[-1] and "Live channel so far today" in posted[-1]
    assert not (tmp_path / "live_picks.json").exists()          # the live picks file is never written


def test_an_open_trade_is_not_called_a_new_signal():
    t = {"symbol": "AAA", "side": "long", "rule": "inplay_orb", "entry_time": "09:42", "entry": 100.6, "stop": 99.5,
         "target": 102.8, "exit": None, "rank": 1, "rvol5": 3.0, "or_width_atr": 0.8, "breakout_rvol": 1.0,
         "gap": 0.0, "ranked": False, "setup": "ORB · Big Tech", "risk_pct_price": 1.1}
    text = tr.trial_card(t)
    assert "NEW SIGNAL" not in text and "STILL OPEN" in text
