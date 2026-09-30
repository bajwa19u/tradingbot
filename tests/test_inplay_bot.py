"""The second channel: its own feed, its own record, its own webhook."""
from __future__ import annotations

import json

import pandas as pd
import pytest

from src import inplay_bot as b


# Pinned to the middle of a session. Without this the end-of-day summary
# fires whenever the suite happens to run after 16:00 Eastern, and tests that
# count Discord posts fail every evening.
MIDDAY = pd.Timestamp("2026-09-30 11:00", tz=b.EASTERN)


def trade(**kw):
    t = {"id": "IP-NVDA-orl-2026-10-01", "rule": "inplay", "symbol": "NVDA",
         "side": "short", "entry_time": "09:36", "entry": 182.40,
         "stop": 184.10, "target": 179.00, "shares": 11, "risk": 18.7,
         "rvol": 6.2, "level": 182.9, "level_name": "orl", "exit": None,
         "exit_time": None, "reason": None, "pct": None, "post": True}
    t.update(kw)
    return t


# --- the two feeds must not touch each other ---------------------------------
def test_it_keeps_its_own_record_file():
    from src import live_bot
    assert b.SEEN_FILE != live_bot.SEEN_FILE, \
        "sharing a record with the main bot is how one feed eats the other's ids"


def test_it_posts_to_its_own_webhook(monkeypatch, tmp_path):
    """The whole point of a second channel is that these do not mix."""
    monkeypatch.setattr(b, "STATE", tmp_path)
    monkeypatch.setattr(b, "REPORTS", tmp_path)
    monkeypatch.setattr(b, "scan", lambda cfg, now: ([trade()], [], "09:40"))
    used = []
    monkeypatch.setattr(b.dm, "post", lambda url, text: used.append(url) or "m1")
    monkeypatch.setenv("DISCORD_WEBHOOK_INPLAY", "https://second")
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://main")
    b.tick({"equity": 2000.0, "risk_pct": 1.0}, dry_run=False, now=MIDDAY)
    assert used and all(u == "https://second" for u in used)


def test_nothing_is_sent_when_the_second_webhook_is_missing(monkeypatch,
                                                            tmp_path):
    monkeypatch.setattr(b, "STATE", tmp_path)
    monkeypatch.setattr(b, "scan", lambda cfg, now: ([trade()], [], "09:40"))
    monkeypatch.setenv("DISCORD_WEBHOOK_INPLAY", "")
    sent = []
    monkeypatch.setattr(b.dm, "post", lambda url, text: sent.append(url) or "m")
    assert b.tick({"equity": 2000.0, "risk_pct": 1.0}, dry_run=False, now=MIDDAY) == 0
    assert not sent, "it must never fall back to the main channel"


# --- the record ---------------------------------------------------------------
def test_yesterdays_record_is_ignored(tmp_path, monkeypatch):
    monkeypatch.setattr(b, "STATE", tmp_path)
    (tmp_path / b.SEEN_FILE).write_text('{"date": "2026-09-30", '
                                        '"entries": ["x"], "picks": true}')
    s = b.load_seen("2026-10-01")
    assert s["entries"] == [] and s["picks"] is False


def test_a_broken_record_does_not_stop_the_run(tmp_path, monkeypatch):
    monkeypatch.setattr(b, "STATE", tmp_path)
    (tmp_path / b.SEEN_FILE).write_text("not json")
    assert b.load_seen("2026-10-01")["cards"] == {}


def test_a_run_that_sent_nothing_leaves_the_record_alone(monkeypatch, tmp_path):
    monkeypatch.setattr(b, "STATE", tmp_path)
    monkeypatch.setattr(b, "REPORTS", tmp_path)
    monkeypatch.setattr(b, "scan", lambda cfg, now: ([], [], "—"))
    monkeypatch.setenv("DISCORD_WEBHOOK_INPLAY", "https://second")
    b.tick({"equity": 2000.0, "risk_pct": 1.0}, dry_run=False, now=MIDDAY)
    assert not (tmp_path / b.SEEN_FILE).exists()


def test_a_close_edits_the_card(monkeypatch, tmp_path):
    monkeypatch.setattr(b, "STATE", tmp_path)
    monkeypatch.setattr(b, "REPORTS", tmp_path)
    today = str(pd.Timestamp.now(tz=b.EASTERN).date())
    (tmp_path / b.SEEN_FILE).write_text(json.dumps(
        {"date": today, "entries": ["IP-NVDA-orl-2026-10-01"], "exits": [],
         "summary": True, "picks": True,
         "cards": {"IP-NVDA-orl-2026-10-01": "m1"}}))
    monkeypatch.setattr(b, "scan", lambda cfg, now: (
        [trade(exit=179.0, exit_time="11:20", reason="target", pct=2.0)],
        [], "11:20"))
    edits, posts = [], []
    monkeypatch.setattr(b.dm, "edit", lambda u, m, t: edits.append(m) is None)
    monkeypatch.setattr(b.dm, "post", lambda u, t: posts.append(t) or "m2")
    monkeypatch.setenv("DISCORD_WEBHOOK_INPLAY", "https://second")
    b.tick({"equity": 2000.0, "risk_pct": 1.0}, dry_run=False, now=MIDDAY)
    assert edits == ["m1"] and not posts


# --- the selection ------------------------------------------------------------
def test_the_ranking_is_announced_once(monkeypatch, tmp_path):
    monkeypatch.setattr(b, "STATE", tmp_path)
    monkeypatch.setattr(b, "REPORTS", tmp_path)
    monkeypatch.setattr(b, "scan",
                        lambda cfg, now: ([], [("NVDA", 8.2)], "09:36"))
    posts = []
    monkeypatch.setattr(b.dm, "post", lambda u, t: posts.append(t) or "m")
    monkeypatch.setenv("DISCORD_WEBHOOK_INPLAY", "https://second")
    b.tick({"equity": 2000.0, "risk_pct": 1.0}, dry_run=False, now=MIDDAY)
    assert len(posts) == 1 and "In play" in posts[0] and "NVDA" in posts[0]
    b.tick({"equity": 2000.0, "risk_pct": 1.0}, dry_run=False, now=MIDDAY)
    assert len(posts) == 1, "the ranking is news once, not every minute"


def test_a_quiet_morning_says_so():
    assert "nothing unusual" in b.picks_msg([], "Thursday 01 October")


def test_it_trades_only_a_handful():
    assert b.RULE["select_top"] == b.TOP_N <= 5
    assert b.UNIVERSE == "wide", "selection needs a wide universe to select FROM"


def test_the_stop_is_the_wide_one_on_purpose():
    """The tight stop measured better and stops making money at 0.10%
    slippage. An edge that lives inside the spread is not an edge."""
    assert b.RULE["atr_frac"] >= 0.15


def test_a_dry_run_sends_nothing(monkeypatch, tmp_path):
    monkeypatch.setattr(b, "STATE", tmp_path)
    monkeypatch.setattr(b, "scan", lambda cfg, now: ([trade()], [], "09:40"))
    sent = []
    monkeypatch.setattr(b.dm, "post", lambda u, t: sent.append(t) or "m")
    b.tick({"equity": 2000.0, "risk_pct": 1.0}, dry_run=True, now=MIDDAY)
    assert not sent
