"""The house style for every Discord message (13 Oct 2026, the owner's spec):
a buy is one neutral style that says BUY CALLS or BUY PUTS; a sale is green
for a profit and red for a loss; the daily report covers today, the last 5
days, last week and the month, with no text lined up by spaces and pipes."""
from __future__ import annotations

import datetime as dt

import pandas as pd

from src import cards as c
from src import ledger


def trade(**kw):
    t = {"id": "ORB-NVDA-2026-10-13", "rule": "inplay_orb", "symbol": "NVDA", "side": "long", "entry_time": "09:41",
         "entry": 237.77, "stop": 235.10, "target": 243.11, "level": 236.90, "exit": None, "exit_time": None,
         "reason": None, "pct": None, "age_s": 1.0}
    return {**t, **kw}


def test_a_buy_says_calls_or_puts_and_is_never_red_or_green():
    long_, short = c.signal_embed(trade(), "Day Trades", "ORB"), c.signal_embed(trade(side="short"), "Day Trades", "ORB")
    assert long_["title"] == "🔔 BUY CALLS · NVDA" and short["title"] == "🔔 BUY PUTS · NVDA"
    assert long_["color"] == short["color"] == c.BLUE
    for e in (long_, short):
        assert "🟢" not in e["title"] and "🔴" not in e["title"]


def test_a_sale_is_green_for_a_profit_and_red_for_a_loss():
    won = c.signal_embed(trade(exit=243.11, exit_time="11:02", reason="target", pct=1.98), "Day Trades", "ORB")
    lost = c.signal_embed(trade(exit=235.10, exit_time="10:05", reason="stop", pct=-1.02), "Day Trades", "ORB")
    assert won["title"].startswith("🟢 SOLD · NVDA CALLS") and won["color"] == c.GREEN and "+1.98%" in won["title"]
    assert lost["title"].startswith("🔴 SOLD · NVDA CALLS") and lost["color"] == c.RED and "−1.02%" in lost["title"]
    assert "Target hit" in c.as_text(won) and "Stop hit" in c.as_text(lost)


def test_a_stop_at_the_entry_price_reads_as_breakeven():
    e = c.signal_embed(trade(exit=237.77, exit_time="10:30", reason="stop", pct=-0.02), "Day Trades", "ORB")
    assert "Stopped at entry (breakeven)" in c.as_text(e)


def test_a_late_signal_is_missed_not_a_buy():
    e = c.signal_embed(trade(expired=True, age_s=420), "Day Trades", "ORB")
    assert e["title"] == "⚪ MISSED · NVDA CALLS" and "Do not enter" in e["description"] and e["color"] == c.GREY


def test_no_dollar_signs_or_share_counts():
    for t in (trade(), trade(exit=243.11, exit_time="11:02", reason="target", pct=1.98)):
        text = c.as_text(c.signal_embed({**t, "shares": 11}, "Day Trades", "ORB"))
        assert "$" not in text and "share" not in text.lower()


def _ledger():
    rows = [("2026-10-01", 1.0), ("2026-10-01", -1.0), ("2026-10-05", 0.5), ("2026-10-06", -1.0),
            ("2026-10-07", 2.0), ("2026-10-08", 0.3), ("2026-10-09", -0.4), ("2026-10-12", 1.1), ("2026-10-13", -0.2)]
    return pd.DataFrame([{"id": f"t{i}", "date": d, "pct": p} for i, (d, p) in enumerate(rows)])


def test_the_report_windows_are_today_5_days_last_week_and_month():
    w = dict(c.windows(_ledger(), dt.date(2026, 10, 13)))
    assert list(w)[0] == "Today" and w["Today"]["n"] == 1 and round(w["Today"]["total"], 2) == -0.2
    assert w["Last 5 days"]["n"] == 5                                    # 7, 8, 9, 12, 13 Oct
    lw = [k for k in w if k.startswith("Last week")][0]
    assert lw == "Last week (5–9 Oct)" and w[lw]["n"] == 5 and round(w[lw]["total"], 2) == 1.4
    assert w["October to date"]["n"] == 9 and w["October to date"]["won"] == 5


def test_the_daily_report_is_a_formatted_box_with_four_windows():
    today = [trade(exit=243.11, exit_time="11:02", reason="target", pct=1.98),
             trade(symbol="AAPL", side="short", exit=335.0, exit_time="15:55", reason="bell", pct=-0.4)]
    e = c.daily_report_embed("Day Trades", dt.date(2026, 10, 13), today, _ledger(), "sizing")
    assert e["title"] == "📊 Day Trades · Daily Report"
    assert [f["name"] for f in e["fields"]][0] == "Today" and len(e["fields"]) == 4
    text = c.as_text(e)
    assert "Win rate" in text and "|" not in text
    assert "🟢 **NVDA** Calls" in e["description"] and "🔴 **AAPL** Puts" in e["description"]


def test_the_ledger_keeps_each_trade_once(tmp_path, monkeypatch):
    monkeypatch.setattr(ledger, "STATE", tmp_path)
    t = trade(exit=243.11, exit_time="11:02", reason="target", pct=1.98)
    ledger.append("daytrade", [t, trade(id="open-one")], "2026-10-13")
    ledger.append("daytrade", [t], "2026-10-13")
    df = ledger.load("daytrade")
    assert len(df) == 1 and df.iloc[0]["pct"] == 1.98         # open trades are not recorded


def test_a_dry_run_report_does_not_write_the_ledger(tmp_path, monkeypatch):
    from src import live_bot as lb
    monkeypatch.setattr(ledger, "STATE", tmp_path)
    lb.daily_report([trade(exit=243.11, exit_time="11:02", reason="target", pct=1.98)], dt.date(2026, 10, 13),
                    "Day Trades", "daytrade", write=False)
    assert not (tmp_path / "ledger_daytrade.csv").exists()
