"""The live wiring: message shape, de-duplication, and the two-rule merge.

These are the failures that reach Discord rather than a log file — a trade
announced twice, a close posted for a position that is still running, or a
result reported in a unit the account holder has said three times he does not
use.
"""
from __future__ import annotations

import pandas as pd
import pytest

from src import live_bot as lb


def trade(**kw):
    base = {"id": "X-1", "rule": "opening", "symbol": "AMD", "side": "short",
            "entry_time": "09:31", "entry": 622.21, "stop": 627.42,
            "target": 611.78, "shares": 3, "risk": 15.6, "level": 625.80,
            "level_name": "pdl", "exit": None, "exit_time": None,
            "reason": None, "pct": None, "cash": None,
            "observe": False, "post": True}
    return {**base, **kw}


# --- messages ----------------------------------------------------------------
def test_entry_message_has_the_five_things_asked_for():
    m = lb.entry_msg(trade())
    assert "AMD" in m                    # name
    assert "622.21" in m                 # price to buy in
    assert "627.42" in m and "🛑" in m    # stop
    assert "611.78" in m and "🎯" in m    # target
    assert "🔻" in m                      # an emoji for the name


def test_entry_message_names_the_level_for_a_watched_trade():
    m = lb.entry_msg(trade(observe=True, level_name="orl", shares=0))
    assert "the opening-range low" in m and "625.80" in m


def test_a_retest_trade_gets_no_opening_footnote():
    m = lb.entry_msg(trade(rule="retest"))
    assert "opening drive" not in m


def test_long_and_short_read_differently():
    s, l = lb.entry_msg(trade()), lb.entry_msg(trade(side="long"))
    assert "SHORT" in s and "🔻" in s
    assert "LONG" in l and "🔺" in l


def test_close_message_is_a_percentage_not_a_multiple():
    m = lb.close_msg(trade(exit=611.78, exit_time="10:45", reason="target",
                           pct=2.0, cash=31.2))
    assert "+2.00%" in m and "✅" in m
    assert "R" not in m.replace("SHORT", "").replace("AMD", "")


def test_close_message_survives_a_missing_cash_figure():
    m = lb.close_msg(trade(exit=627.42, exit_time="09:33", reason="stop",
                           pct=-1.0, cash=None))
    assert "-1.00%" in m and "❌" in m and "+$0.00" in m


def test_hold_limit_exit_is_explained_in_english():
    m = lb.close_msg(trade(exit=620.0, exit_time="11:31", reason="time",
                           pct=0.3, cash=5.0))
    assert "hold limit" in m


# --- the daily recap ---------------------------------------------------------
def test_summary_counts_winners_and_losers_and_a_total():
    ts = [trade(id="a", exit=1.0, pct=2.0, cash=30.0, exit_time="10:00",
                reason="target"),
          trade(id="b", exit=1.0, pct=-1.0, cash=-15.0, exit_time="10:10",
                reason="stop"),
          trade(id="c", exit=1.0, pct=2.0, cash=30.0, exit_time="11:00",
                reason="target")]
    m = lb.summary_msg(ts, "Tuesday 29 September")
    assert "3 trades" in m and "2 won, 1 lost" in m and "67% win rate" in m
    assert "+3.00%" in m and "+$45.00" in m


def test_summary_ignores_positions_that_are_still_open():
    ts = [trade(id="a", exit=1.0, pct=2.0, cash=30.0, exit_time="10:00",
                reason="target"),
          trade(id="b")]                       # still running
    m = lb.summary_msg(ts, "Tuesday 29 September")
    assert "1 trade" in m and "1 won, 0 lost" in m


def test_summary_says_so_on_a_quiet_day():
    assert "no trades today" in lb.summary_msg([], "Tuesday 29 September")


def test_no_user_facing_message_mentions_r_multiples():
    """Stated more than once: win %, profit %, winners versus losers."""
    ts = [trade(id="a", exit=611.78, pct=2.0, cash=30.0, exit_time="10:00",
                reason="target")]
    blob = " ".join([lb.entry_msg(ts[0]), lb.close_msg(ts[0]),
                     lb.summary_msg(ts, "Tuesday 29 September")])
    for banned in (" R\n", " R ", "1R", "2R", "3R", "R-multiple", "R multiple"):
        assert banned not in blob


# --- de-duplication ----------------------------------------------------------
def test_an_opening_trade_id_is_stable_across_reruns():
    """The whole day is replayed every poll. If the id moved, every poll
    would post the same trade again."""
    ids = {f"OPEN-AMD-pdl-2026-09-29" for _ in range(5)}
    assert len(ids) == 1


def test_seen_file_defaults_every_field(tmp_path, monkeypatch):
    monkeypatch.setattr(lb, "STATE", tmp_path)
    (tmp_path / lb.SEEN_FILE).write_text('{"date": "2026-09-29"}')
    s = lb.load_seen("2026-09-29")
    assert s["entries"] == [] and s["exits"] == [] and s["summary"] is False


def test_a_foreign_seen_file_does_not_crash_the_run(tmp_path, monkeypatch):
    monkeypatch.setattr(lb, "STATE", tmp_path)
    (tmp_path / lb.SEEN_FILE).write_text("not json at all")
    assert lb.load_seen("2026-09-29")["entries"] == []


def test_yesterdays_seen_file_is_ignored(tmp_path, monkeypatch):
    monkeypatch.setattr(lb, "STATE", tmp_path)
    (tmp_path / lb.SEEN_FILE).write_text(
        '{"date": "2026-09-28", "entries": ["OPEN-AMD-pdl-2026-09-28"]}')
    assert lb.load_seen("2026-09-29")["entries"] == []


# --- the merge ---------------------------------------------------------------
def test_the_opening_rule_is_in_observation_mode():
    """Both holdout studies failed. It runs to gather a forward record; it
    must not quietly become a trading rule without another study."""
    assert lb.OPENING["enabled"] is True
    assert lb.OPENING["observe"] is True


def test_a_broken_rule_does_not_silence_the_other(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("data feed on fire")
    monkeypatch.setattr(lb, "scan", boom)
    monkeypatch.setattr(lb, "opening_scan",
                        lambda cfg, now: [trade(entry_time="09:31")])
    now = pd.Timestamp("2026-09-29 09:50", tz=lb.EASTERN)
    trades, _, _ = lb.all_trades({"equity": 2000.0, "risk_pct": 1.0}, now)
    assert len(trades) == 1


def test_trades_come_out_in_time_order(monkeypatch):
    monkeypatch.setattr(lb, "scan", lambda cfg: (
        [trade(id="r", rule="retest", entry_time="10:20")], "10:20", False))
    monkeypatch.setattr(lb, "opening_scan", lambda cfg, now: [
        trade(id="o2", symbol="TSLA", entry_time="09:31"),
        trade(id="o1", symbol="AMD", entry_time="09:30")])
    now = pd.Timestamp("2026-09-29 11:00", tz=lb.EASTERN)
    trades, _, _ = lb.all_trades({"equity": 2000.0, "risk_pct": 1.0}, now)
    assert [t["entry_time"] for t in trades] == ["09:30", "09:31", "10:20"]


def test_the_retest_rule_is_not_polled_before_its_window_opens(monkeypatch):
    called = []
    monkeypatch.setattr(lb, "scan", lambda cfg: called.append(1) or ([], "", False))
    monkeypatch.setattr(lb, "opening_scan", lambda cfg, now: [])
    lb.all_trades({}, pd.Timestamp("2026-09-29 09:31", tz=lb.EASTERN))
    assert called == [], "no point fetching 5-minute bars it cannot act on"
    lb.all_trades({}, pd.Timestamp("2026-09-29 09:50", tz=lb.EASTERN))
    assert called == [1]


def test_the_day_is_done_after_the_bell(monkeypatch):
    monkeypatch.setattr(lb, "scan", lambda cfg: ([], "15:55", False))
    monkeypatch.setattr(lb, "opening_scan", lambda cfg, now: [])
    _, _, done = lb.all_trades({}, pd.Timestamp("2026-09-29 16:01",
                                                tz=lb.EASTERN))
    assert done is True


# --- the window --------------------------------------------------------------
def test_the_opening_rule_moves_the_start_of_the_day_to_the_bell():
    assert lb.BELL == "09:30"
    assert lb.OPEN_T == "09:45", "the retest rule keeps its own window"


# --- observation mode --------------------------------------------------------
def test_a_watched_entry_is_not_shaped_like_a_signal():
    """If it reads like the traded alerts it will be taken like them."""
    m = lb.entry_msg(trade(observe=True, shares=0, level_name="orl"))
    assert "👀" in m and "WATCHING" in m
    assert "tracking only" in m and "no position" in m
    assert "risking" not in m and "shares" not in m


def test_a_watched_entry_still_carries_the_prices():
    m = lb.entry_msg(trade(observe=True, shares=0, level_name="orl"))
    assert "622.21" in m and "627.42" in m and "611.78" in m


def test_a_watched_close_says_no_position_was_taken():
    m = lb.close_msg(trade(observe=True, shares=0, exit=611.78,
                           exit_time="10:40", reason="target", pct=2.0,
                           cash=0.0))
    assert "WATCHED" in m and "no position was taken" in m
    assert "✅" not in m, "the traded tick is reserved for traded results"


def test_watched_results_are_kept_out_of_the_accounts_total():
    ts = [trade(id="r", exit=1.0, pct=2.0, cash=30.0, exit_time="10:00",
                reason="target"),
          trade(id="w", observe=True, shares=0, exit=1.0, pct=-1.0, cash=0.0,
                exit_time="10:20", reason="stop")]
    m = lb.summary_msg(ts, "Tuesday 29 September")
    traded, watched = m.split("**Watched**")
    assert "+2.00%" in traded and "1 trade · 1 won, 0 lost" in traded
    assert "-1.00%" in watched


def test_summary_says_so_when_only_the_watched_rule_fired():
    ts = [trade(id="w", observe=True, shares=0, exit=1.0, pct=2.0, cash=0.0,
                exit_time="10:20", reason="target")]
    m = lb.summary_msg(ts, "Tuesday 29 September")
    assert "nothing fired today" in m and "Watched" in m


def test_a_trade_not_marked_for_posting_never_reaches_the_feed(monkeypatch,
                                                               tmp_path):
    """Longs off the opening range are recorded for the study and kept out
    of the feed. A bug here is a wall of Discord messages."""
    monkeypatch.setattr(lb, "STATE", tmp_path)
    monkeypatch.setattr(lb, "REPORTS", tmp_path)
    monkeypatch.setattr(lb, "scan", lambda cfg: ([], "09:31", False))
    monkeypatch.setattr(lb, "opening_scan", lambda cfg, now: [
        trade(id="keep", observe=True, shares=0, post=True),
        trade(id="drop", observe=True, shares=0, post=False, side="long")])
    sent = []
    monkeypatch.setattr(lb, "notify", sent.append)
    lb.tick({"equity": 2000.0, "risk_pct": 1.0}, dry_run=False)
    entries = [m for m in sent if "WATCHING" in m]
    assert len(entries) == 1
    assert "LONG" not in " ".join(entries)


def test_the_cash_total_sits_on_the_totals_line():
    """It once landed on the last trade's line, which read as though that
    one losing trade had made $146."""
    ts = [trade(id="a", exit=1.0, pct=2.0, cash=40.0, exit_time="10:00",
                reason="target"),
          trade(id="b", exit=1.0, pct=-1.0, cash=-20.0, exit_time="10:10",
                reason="stop")]
    m = lb.summary_msg(ts, "Tuesday 29 September")
    lines = m.splitlines()
    total = next(l for l in lines if l.startswith("**+1.00%"))
    assert "+$20.00" in total
    assert not any("+$20.00" in l for l in lines if l.startswith(("✅", "❌")))


def test_two_breaks_on_the_same_bar_get_different_ids():
    """A collision here is invisible: the recap counts both trades and
    Discord only ever shows one of them."""
    import pandas as pd
    from src import live_bot as m
    day = pd.DataFrame(
        {"open": [10.0], "high": [10.0], "low": [10.0], "close": [10.0],
         "atr": [1.0]},
        index=pd.DatetimeIndex([pd.Timestamp("2026-09-29 09:50", tz=m.EASTERN)]))
    ids = {f"AMZN-{str(day.index[0])[:16]}-{lvl:.2f}" for lvl in (246.86, 247.15)}
    assert len(ids) == 2
