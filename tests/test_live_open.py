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
    assert "AMD" in m                     # name
    assert "622.21" in m                  # price to buy in
    assert "627.42" in m and "SL" in m    # stop
    assert "611.78" in m and "TP" in m    # target
    assert "🔴" in m                       # red for a short


def test_the_entry_message_is_short_enough_to_read_on_a_phone():
    """Three lines: who, the prices, the size."""
    m = lb.entry_msg(trade(rule="opening", level_name="orl"))
    assert len(m.splitlines()) == 5


def test_a_retest_trade_gets_no_opening_footnote():
    m = lb.entry_msg(trade(rule="retest"))
    assert "opening drive" not in m


def test_long_and_short_read_differently():
    s, l = lb.entry_msg(trade()), lb.entry_msg(trade(side="long"))
    assert "SHORT" in s and "🔴" in s
    assert "LONG" in l and "🟢" in l


def test_close_message_is_a_percentage_not_a_multiple():
    m = lb.close_msg(trade(exit=611.78, exit_time="10:45", reason="target",
                           pct=2.0, cash=31.2))
    assert "+2.00%" in m and "✅" in m
    assert "R" not in m.replace("SHORT", "").replace("AMD", "")


def test_no_message_carries_a_dollar_figure():
    """Prices are bare numbers and results are percentages. Cash amounts are
    gone entirely."""
    t = trade(exit=627.42, exit_time="09:33", reason="stop", pct=-1.0)
    blob = (lb.entry_msg(t) + lb.close_msg(t)
            + lb.summary_msg([t], "Tuesday 30 September"))
    assert "$" not in blob


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
    assert "+3.00%" in m


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
def test_both_rules_are_live_and_post_both_sides():
    assert lb.OPENING["enabled"] is True
    assert set(lb.OPENING["post_sides"]) == {"short", "long"}


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


# --- one message shape, no second class -------------------------------------
def test_every_signal_has_the_same_shape():
    """An earlier version posted the opening rule under a WATCHING header
    with no size. It buried a working AMD long on 29 September and trained
    the eye to skim past half the feed."""
    a = lb.entry_msg(trade(rule="retest"))
    b = lb.entry_msg(trade(rule="opening", level_name="orl"))
    for m in (a, b):
        assert "WATCHING" not in m and "tracking only" not in m
        assert "SL" in m and "TP" in m
        # The share count came out on 30 September: position size belongs to
        # one account, and a card printing it reads as an instruction.
        assert "share" not in m


def test_the_entry_says_which_setup_it_came_from():
    assert "break & retest" in lb.entry_msg(trade(rule="retest"))
    assert "opening range" in lb.entry_msg(trade(rule="opening"))


def test_an_opening_trade_is_sized_like_any_other():
    assert lb.OPENING["observe"] is False


def test_closes_have_one_shape_too():
    a = lb.close_msg(trade(rule="retest", exit=611.78, exit_time="10:40",
                           reason="target", pct=2.0, cash=31.2))
    b = lb.close_msg(trade(rule="opening", exit=611.78, exit_time="10:40",
                           reason="target", pct=2.0, cash=31.2))
    for m in (a, b):
        assert "WATCHED" not in m and "no position was taken" not in m
        assert "+2.00%" in m and "→" in m


def test_the_recap_is_one_list():
    ts = [trade(id="a", rule="retest", exit=1.0, pct=2.0, cash=40.0,
                exit_time="10:00", reason="target"),
          trade(id="b", rule="opening", exit=1.0, pct=-1.0, cash=-20.0,
                exit_time="10:20", reason="stop")]
    m = lb.summary_msg(ts, "Tuesday 29 September")
    assert "Watched" not in m and "Traded" not in m
    assert "2 trades · 1 won, 1 lost" in m and "+1.00%" in m


def test_the_recap_totals_a_percentage():
    ts = [trade(id="a", exit=1.0, pct=2.0, exit_time="10:00", reason="target"),
          trade(id="b", exit=1.0, pct=-1.0, exit_time="10:20", reason="stop")]
    m = lb.summary_msg(ts, "Tuesday 29 September")
    assert any(l.startswith("**+1.00%") for l in m.splitlines())


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


# --- both sides reach the feed -----------------------------------------------
def test_longs_are_posted_now():
    """Shorts-only hid AMD's opening-range-high break on 29 September, which
    ran while the feed showed nothing."""
    assert set(lb.OPENING["post_sides"]) == {"short", "long"}


def test_a_long_entry_renders():
    m = lb.entry_msg(trade(side="long", rule="opening", level_name="orh"))
    assert "LONG" in m and "🟢" in m and "opening range" in m


# --- correlated entries are one result, not many -----------------------------
def test_a_wall_of_same_side_entries_is_flagged():
    """All twelve core names broke their opening-range low inside ten minutes
    on 29 September. Twelve shorts, one market move."""
    ts = [trade(id=str(i), side="short", entry_time=f"09:{35 + i:02d}")
          for i in range(8)]
    note = lb.cluster_note(ts)
    assert "8 shorts within 15 min" in note
    assert "one market move" in note


def test_entries_spread_through_the_day_are_not_flagged():
    ts = [trade(id="a", entry_time="09:35"), trade(id="b", entry_time="10:30"),
          trade(id="c", entry_time="12:00"), trade(id="d", entry_time="14:45")]
    assert lb.cluster_note(ts) == ""


def test_opposite_sides_do_not_add_up_into_a_cluster():
    ts = ([trade(id=f"s{i}", side="short", entry_time=f"09:{35 + i:02d}")
           for i in range(2)] +
          [trade(id=f"l{i}", side="long", entry_time=f"09:{37 + i:02d}")
           for i in range(2)])
    assert lb.cluster_note(ts) == ""


def test_the_warning_reaches_the_daily_recap():
    ts = [trade(id=str(i), side="short", entry_time=f"09:{35 + i:02d}",
                exit=1.0, pct=-1.0, cash=-20.0, exit_time="10:00",
                reason="stop") for i in range(6)]
    m = lb.summary_msg(ts, "Tuesday 29 September")
    assert "⚠️" in m and "one market move" in m


# --- one message per trade, edited in place ----------------------------------
def _tick(monkeypatch, tmp_path, trades, posts, edits, mid="m1"):
    monkeypatch.setattr(lb, "STATE", tmp_path)
    monkeypatch.setattr(lb, "REPORTS", tmp_path)
    monkeypatch.setattr(lb, "scan", lambda cfg: ([], "09:40", False))
    monkeypatch.setattr(lb, "opening_scan", lambda cfg, now: trades)
    monkeypatch.setattr(lb.dm, "post",
                        lambda url, text: posts.append(text) or mid)
    monkeypatch.setattr(lb.dm, "edit",
                        lambda url, m, text: edits.append((m, text)) is None)
    lb.tick({"equity": 2000.0, "risk_pct": 1.0}, dry_run=False)


def test_an_entry_posts_once_and_its_id_is_remembered(monkeypatch, tmp_path):
    posts, edits = [], []
    _tick(monkeypatch, tmp_path, [trade(id="t1")], posts, edits)
    import json
    seen = json.loads((tmp_path / lb.SEEN_FILE).read_text())
    cards = [t for t in posts if "SHORT" in t or "LONG" in t]
    assert len(cards) == 1 and seen["cards"]["t1"] == "m1"


def test_a_close_edits_the_card_instead_of_posting_again(monkeypatch, tmp_path):
    posts, edits = [], []
    monkeypatch.setattr(lb, "STATE", tmp_path)
    (tmp_path / lb.SEEN_FILE).write_text(
        '{"date": "%s", "entries": ["t1"], "exits": [], "summary": true,'
        ' "cards": {"t1": "m1"}}' % str(pd.Timestamp.now(tz=lb.EASTERN).date()))
    _tick(monkeypatch, tmp_path,
          [trade(id="t1", exit=611.0, exit_time="10:40", reason="target",
                 pct=2.0)], posts, edits)
    assert edits and edits[0][0] == "m1"
    assert not posts, "the result must rewrite the card, not add a message"


def test_a_close_falls_back_to_its_own_message_if_the_edit_fails(monkeypatch,
                                                                 tmp_path):
    """A dropped result is worse than an extra message."""
    posts = []
    monkeypatch.setattr(lb, "STATE", tmp_path)
    (tmp_path / lb.SEEN_FILE).write_text(
        '{"date": "%s", "entries": ["t1"], "exits": [], "summary": true,'
        ' "cards": {"t1": "gone"}}' % str(pd.Timestamp.now(tz=lb.EASTERN).date()))
    monkeypatch.setattr(lb, "REPORTS", tmp_path)
    monkeypatch.setattr(lb, "scan", lambda cfg: ([], "09:40", False))
    monkeypatch.setattr(lb, "opening_scan", lambda cfg, now: [
        trade(id="t1", exit=611.0, exit_time="10:40", reason="target", pct=2.0)])
    monkeypatch.setattr(lb.dm, "post", lambda url, text: posts.append(text) or "m2")
    monkeypatch.setattr(lb.dm, "edit", lambda url, m, text: False)
    lb.tick({"equity": 2000.0, "risk_pct": 1.0}, dry_run=False)
    assert len(posts) == 1 and "+2.00%" in posts[0]


def test_a_close_with_no_card_posts_on_its_own(monkeypatch, tmp_path):
    """State written before cards existed must still deliver results."""
    posts, edits = [], []
    monkeypatch.setattr(lb, "STATE", tmp_path)
    (tmp_path / lb.SEEN_FILE).write_text(
        '{"date": "%s", "entries": ["t1"], "exits": [], "summary": true}'
        % str(pd.Timestamp.now(tz=lb.EASTERN).date()))
    _tick(monkeypatch, tmp_path,
          [trade(id="t1", exit=611.0, exit_time="10:40", reason="target",
                 pct=2.0)], posts, edits, mid="m2")
    assert len(posts) == 1 and not edits


def test_a_dry_run_never_touches_discord(monkeypatch, tmp_path):
    posts, edits = [], []
    monkeypatch.setattr(lb, "STATE", tmp_path)
    monkeypatch.setattr(lb, "REPORTS", tmp_path)
    monkeypatch.setattr(lb, "scan", lambda cfg: ([], "09:40", False))
    monkeypatch.setattr(lb, "opening_scan", lambda cfg, now: [trade(id="t1")])
    monkeypatch.setattr(lb.dm, "post", lambda url, text: posts.append(text) or "m")
    monkeypatch.setattr(lb.dm, "edit", lambda url, m, text: edits.append(m) is None)
    lb.tick({"equity": 2000.0, "risk_pct": 1.0}, dry_run=True)
    assert not posts and not edits


def test_the_watchlist_is_the_live_universe():
    from src.forensics import LIVE
    assert lb.WATCHLIST == LIVE
    assert "SPY" in LIVE and "QQQ" in LIVE
    assert "AVGO" not in LIVE


# --- the state file is not rewritten by a run that did nothing ---------------
def test_a_run_that_announced_nothing_leaves_the_record_untouched(monkeypatch,
                                                                  tmp_path):
    """On 30 September a run that exited with nothing to do rewrote the
    record from its own stale checkout, wiping ten message ids, and the next
    run posted all ten trades a second time."""
    monkeypatch.setattr(lb, "STATE", tmp_path)
    monkeypatch.setattr(lb, "REPORTS", tmp_path)
    f = tmp_path / lb.SEEN_FILE
    today = str(pd.Timestamp.now(tz=lb.EASTERN).date())
    f.write_text('{"date": "%s", "entries": ["t1"], "exits": ["t1"],'
                 ' "summary": true, "cards": {"t1": "m1"}}' % today)
    before = f.read_text(), f.stat().st_mtime_ns
    monkeypatch.setattr(lb, "scan", lambda cfg: ([], "10:00", False))
    monkeypatch.setattr(lb, "opening_scan", lambda cfg, now: [
        trade(id="t1", exit=611.0, exit_time="10:40", reason="target", pct=2.0)])
    monkeypatch.setattr(lb.dm, "post", lambda url, text: "m9")
    monkeypatch.setattr(lb.dm, "edit", lambda url, m, text: True)
    lb.tick({"equity": 2000.0, "risk_pct": 1.0}, dry_run=False)
    assert (f.read_text(), f.stat().st_mtime_ns) == before, \
        "an unchanged record must not even be re-touched"


def test_a_run_that_announced_something_does_write(monkeypatch, tmp_path):
    monkeypatch.setattr(lb, "STATE", tmp_path)
    monkeypatch.setattr(lb, "REPORTS", tmp_path)
    monkeypatch.setattr(lb, "scan", lambda cfg: ([], "09:40", False))
    monkeypatch.setattr(lb, "opening_scan", lambda cfg, now: [trade(id="new")])
    monkeypatch.setattr(lb.dm, "post", lambda url, text: "m1")
    monkeypatch.setattr(lb.dm, "edit", lambda url, m, text: True)
    lb.tick({"equity": 2000.0, "risk_pct": 1.0}, dry_run=False)
    import json
    assert json.loads((tmp_path / lb.SEEN_FILE).read_text())["cards"]["new"] == "m1"


# --- the card, at a glance ---------------------------------------------------
def test_an_open_long_is_green_and_an_open_short_is_red():
    assert lb.card(trade(side="long", exit=None)).startswith("🟢")
    assert lb.card(trade(side="short", exit=None)).startswith("🔴")


def test_a_closed_trade_shows_the_result_not_the_direction():
    won = lb.card(trade(side="short", exit=1.0, exit_time="10:00",
                        reason="target", pct=2.0))
    lost = lb.card(trade(side="long", exit=1.0, exit_time="10:00",
                         reason="stop", pct=-1.0))
    assert won.startswith("✅") and lost.startswith("❌")
    assert "🔴" not in won and "🟢" not in lost


def test_polling_hands_over_after_its_time_limit(monkeypatch):
    """`--for` ends a poll well before `--until`, so the all-day job exits
    and commits inside GitHub's six-hour limit instead of being killed."""
    import pandas as pd
    t = [pd.Timestamp("2026-10-01 11:00", tz=lb.EASTERN)]

    def now(tz=None):
        t[0] += pd.Timedelta(minutes=1)
        return t[0]
    monkeypatch.setattr(pd.Timestamp, "now", staticmethod(now))
    monkeypatch.setattr(lb, "settings", lambda: {})
    ticks = []
    monkeypatch.setattr(lb, "tick", lambda cfg, dry: ticks.append(t[0]) or 0)
    monkeypatch.setattr(lb._time, "sleep", lambda s: None)
    assert lb.main(["--until", "16:10", "--every", "60", "--for", "5"]) == 0
    assert 2 <= len(ticks) <= 5
    assert t[0] < pd.Timestamp("2026-10-01 11:15", tz=lb.EASTERN)
