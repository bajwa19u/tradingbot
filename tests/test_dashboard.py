"""The dashboard reports what the records say and nothing more.

These pin the things that have gone wrong in this project before: trades not
equalling wins plus losses, missing values read as zero, open positions mixed
into closed statistics, a verdict calling a negative number a success, and a
holdout presented as unseen after it had been used.
"""
from __future__ import annotations

import json
import math
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest

from src import dashboard as db
from src import ledger
from src import orb_month as om
from src import orb_research as orr

ROOT = Path(__file__).resolve().parent.parent


# --------------------------------------------------------------------------- metrics
def test_metrics_on_a_known_sequence():
    m = db.metrics([1.0, -0.5, 0.0, 2.0, -1.0])
    assert (m["n"], m["wins"], m["losses"], m["flat"]) == (5, 2, 2, 1)
    assert m["total"] == 1.5 and m["avg"] == 0.3 and m["win_rate"] == 40.0
    assert m["pf"] == 2.0                      # 3.0 won / 1.5 lost
    assert m["avg_win"] == 1.5 and m["avg_loss"] == -0.75
    assert m["max_dd"] == 1.0 and m["cur_dd"] == 1.0   # peak 2.5, last 1.5
    assert m["ci_low"] < m["avg"] < m["ci_high"]


def test_trades_always_equal_wins_plus_losses_plus_flat():
    rng = np.random.default_rng(7)
    for _ in range(50):
        r = list(np.round(rng.normal(0, 1, rng.integers(0, 40)), 1))
        m = db.metrics(r)
        assert m["n"] == m["wins"] + m["losses"] + m["flat"] == len(r)


def test_missing_values_are_skipped_never_counted_as_zero():
    m = db.metrics([1.0, None, float("nan"), "", "junk", True, -1.0])
    assert m["n"] == 2 and m["flat"] == 0


def test_empty_selection_has_no_numbers():
    m = db.metrics([])
    assert m["n"] == 0 and all(m[k] is None for k in ("win_rate", "total", "avg", "pf", "max_dd"))


def test_profit_factor_is_not_invented_without_a_loss():
    assert db.metrics([0.5, 1.0])["pf"] is None
    assert db.metrics([-0.5, -1.0])["pf"] == 0.0


# --------------------------------------------------------------------------- verdicts
def test_a_negative_total_is_called_losing_first_whatever_else_is_true():
    m = db.metrics([0.9] * 40 + [-40.0])          # high win rate, many trades, negative
    assert m["win_rate"] > 90
    assert db.verdict(m, "u")["state"] == "neg"


def test_few_trades_are_too_few_even_when_positive():
    assert db.verdict(db.metrics([1.0, 0.5, -0.2]), "u")["state"] == "few"


def test_positive_but_inside_noise_is_not_called_profitable():
    r = [1.0, -0.95] * 20
    assert db.verdict(db.metrics(r), "u")["state"] == "noise"
    assert db.verdict(db.metrics([0.3, 0.25, 0.35] * 12), "u")["state"] == "pos"


def test_no_trades_is_its_own_state():
    assert db.verdict(db.metrics([]), "u")["state"] == "none"


# --------------------------------------------------------------------------- records
@pytest.fixture
def repo(tmp_path, monkeypatch):
    """An empty repo layout the builder can be pointed at."""
    for d in ("state", "reports", "wf"):
        (tmp_path / d).mkdir()
    monkeypatch.setattr(db, "STATE", tmp_path / "state")
    monkeypatch.setattr(db, "REPORTS", tmp_path / "reports")
    monkeypatch.setattr(db, "WORKFLOWS", tmp_path / "wf")
    monkeypatch.delenv("DAYTRADE_STRATEGY", raising=False)
    return tmp_path


OLD_LEDGER = ("id,date,symbol,side,entry_time,exit_time,entry,exit,reason,pct,source\n"
              "ORB-MSFT-2026-10-05,2026-10-05,MSFT,long,09:38,15:55,,,bell,-0.69,corrected\n"
              "ORB-AAPL-2026-10-13,2026-10-13,AAPL,short,09:40,15:55,344.01,341.27,bell,0.61,replay\n"
              "ORB-META-2026-10-14,2026-10-14,META,short,09:35,15:55,749.14,737.49,bell,0.91,live\n"
              "ORB-BAD-2026-10-14,2026-10-14,BAD,long,09:35,,,,,,live\n")


def test_old_ledger_rows_read_blanks_as_not_recorded(repo):
    (repo / "state" / "ledger_daytrade.csv").write_text(OLD_LEDGER)
    ts = db.ledger_trades("daytrade")
    msft = next(t for t in ts if t["symbol"] == "MSFT")
    assert msft["entry"] is None and msft["stop"] is None and msft["ret"] == -0.69
    assert msft["setup"] == "ORB · Stocks in Play"
    assert next(t for t in ts if t["symbol"] == "META")["setup"] == "ORB · Big Tech"
    bad = next(t for t in ts if t["symbol"] == "BAD")
    assert bad["status"] == "unresolved" and bad["ret"] is None


def test_open_paper_signals_stay_out_of_closed_statistics(repo):
    hdr = ",".join(["date", "symbol", "side", "bar", "seen_at", "latency_s", "expired", "source", "entry", "stop",
                    "target", "exit_bar", "exit_reason", "result_pct", "result_real_pct", "gap_pct", "vwap_ok"])
    (repo / "reports" / "orb_paper.csv").write_text(
        hdr + "\n2026-10-15,WMT,long,09:35,09:37:04,64,False,live,121.34,119.77,124.47,09:44,stop,-1.34,-1.2,0.5,True"
              "\n2026-10-15,SHOP,long,09:36,09:37:04,4,False,live,168.9,165,176,,,,,1.0,True\n")
    d = db.build(with_actions=False)
    assert d["summary"]["orb_paper"]["all"]["n"] == 1
    assert d["summary"]["orb_paper"]["open"] == 1
    wmt = next(t for t in d["trades"] if t["symbol"] == "WMT")
    assert wmt["f"]["gap_side"] == "with gap" and wmt["ret_real"] == -1.2


def test_an_empty_repo_builds_without_inventing_anything(repo):
    d = db.build(with_actions=False)
    assert d["trades"] == [] and all(s["all"]["n"] == 0 for s in d["summary"].values())
    assert all(s["verdict"]["state"] == "none" for s in d["summary"].values())
    assert d["health"]["actions"] is None


def test_malformed_files_do_not_break_the_build(repo):
    (repo / "state" / "paper.json").write_text("{not json")
    (repo / "reports" / "orb_month.json").write_text("[]")
    (repo / "state" / "latency.jsonl").write_text('garbage\n{"kind": "tick"}\n')
    d = db.build(with_actions=False)
    assert d["summary"]["swing_paper"]["all"]["n"] == 0


def test_duplicate_ids_are_caught(repo):
    (repo / "state" / "ledger_inplay.csv").write_text(
        "id,date,symbol,side,entry_time,exit_time,entry,exit,reason,pct,source\n"
        "IP-X-orh-2026-10-14,2026-10-14,X,long,09:35,10:00,1,2,stop,-1.0,live\n"
        "IP-X-orh-2026-10-14,2026-10-14,X,long,09:35,10:00,1,2,stop,-1.0,live\n")
    d = db.build(with_actions=False)
    bad = [c for c in d["integrity"] if not c["ok"]]
    assert any(c["book"] == "inplay" and c["check"] == "unique trade ids" for c in bad)


def test_swing_open_positions_are_listed_not_valued(repo):
    (repo / "state" / "paper.json").write_text(json.dumps({
        "as_of": "2026-10-15", "settings": {"risk_pct": 1.0}, "n": 1, "wins": 0, "return_pct": -1.0,
        "trades": [{"symbol": "AMD", "entry_date": "2026-10-06", "exit_date": "2026-10-12", "entry": 650, "stop": 589,
                    "exit": 588.8, "reason": "stop", "mfe_r": 0.2, "mae_r": -1.04, "pnl": {"account_pct": -1.0, "move_pct": -9.4}}],
        "open": [{"symbol": "ZM", "entry_date": "2026-10-01", "entry": 93.87, "stop": 84.47, "best_R": 0.64, "shares": 2}]}))
    d = db.build(with_actions=False)
    assert d["summary"]["swing_paper"]["all"]["n"] == 1
    assert d["open"][0]["unrealized"] is None and d["open"][0]["best_acct"] == 0.64
    assert next(t for t in d["trades"] if t["symbol"] == "AMD")["mae"] == -1.04
    assert next(c for c in d["integrity"] if c["check"].startswith("matches src/paper.py"))["ok"]


# --------------------------------------------------------------------------- health
def test_latency_finds_stale_windows_and_gaps(tmp_path):
    f = tmp_path / "latency.jsonl"
    rows = []
    for m in range(0, 60):                              # 09:30-10:29, then nothing until 15:55
        t = f"2026-10-15 {9 + (30 + m) // 60:02d}:{(30 + m) % 60:02d}:04-04:00"
        rows.append({"kind": "tick", "at": t, "stale": 10 <= m < 15, "newest_bar": "2026-10-15 09:39:00-04:00", "scan": 0.3})
    rows.append({"kind": "signal", "id": "ORB-META-2026-10-15", "entry_bar": "09:36", "detected_age_s": 60.5,
                 "posted_age_s": 60.8, "expired": False, "posted_at": "2026-10-15 09:38:00-04:00", "delivered": True})
    f.write_text("\n".join(json.dumps(r) for r in rows) + "\nnot json\n")
    day = db.latency_health(f)["days"][-1]
    assert day["stale"] == [dict(start="09:40", newest_bar="09:39", ticks=5, end="09:44")]
    assert day["gaps"][-1]["start"] == "10:29" and day["gaps"][-1]["minutes"] > 300
    assert day["signals"][0]["delivered"] is True


def test_cron_last_fire():
    at = datetime(2026, 10, 15, 13, 52, tzinfo=timezone.utc)      # a Thursday
    assert db.last_fire("47 12,13 * * 1-5", at) == datetime(2026, 10, 15, 13, 47, tzinfo=timezone.utc)
    assert db.last_fire("*/10 13-21 * * 1-5", at).minute == 50
    sat = datetime(2026, 10, 17, 14, 0, tzinfo=timezone.utc)
    assert db.last_fire("0 13 * * 1-5", sat).day == 16
    assert db.last_fire("bad cron", at) is None


def test_workflows_parse_the_real_schedules():
    flows = {w["file"]: w for w in db.workflows()}
    assert "live-bot.yml" in flows and flows["live-bot.yml"]["crons"]
    assert flows["live-signals.yml"]["crons"] == []       # still off; the dashboard must not change that


def test_the_dashboard_job_posts_nothing_and_reads_only_its_token():
    text = (ROOT / ".github" / "workflows" / "dashboard.yml").read_text()
    assert re.search(r'ref:\s*"?\$\{\{ github\.ref_name \}\}', text)   # CLAUDE.md: never overwrite newer state
    for banned in ("DISCORD", "ALPACA", "WEBHOOK"):
        assert banned not in text.upper()
    assert "contents: write" in text and "actions: read" in text


def test_no_secret_reaches_the_output(repo, monkeypatch):
    (repo / "state" / "live_bot_seen.json").write_text(json.dumps(
        {"date": "2026-10-15", "entries": ["ORB-META-2026-10-15"], "cards": {"ORB-META-2026-10-15": "1559561850922733578"}}))
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/123/secret")
    d = json.dumps(db.build(with_actions=False))
    assert "1559561850922733578" not in d and "discord.com/api/webhooks" not in d
    assert not re.search(r"gh[pousr]_[A-Za-z0-9]{20,}", d)


# --------------------------------------------------------------------------- lab
def test_forward_rows_are_the_only_unseen_ones():
    d = db.build(with_actions=False)
    for r in d["lab"]["rows"]:
        if (r["holdout_status"] or "").startswith("unseen"):
            assert r["split"] == "forward"
        if r["study"] == "ORB in-play research":
            assert "no longer unseen" in r["holdout_status"]
    assert d["lab"]["noise_floor"]["40"] == round(math.sqrt(2 * math.log(40)), 2)


def test_md_table_parser():
    rows = db.md_table(ROOT / "reports" / "orb_bigtech.md", "## Both date ranges")
    assert rows and rows[0][0] == "version" and len(rows) > 2


# --------------------------------------------------------------------------- page
def test_the_page_embeds_the_data_safely(repo):
    d = db.build(with_actions=False)
    d["books"]["daytrade"]["about"] = "</script><script>alert(1)</script>"
    html = db.render_html(d)
    assert "/*__DASHBOARD_DATA__*/null" not in html
    assert "</script><script>alert(1)" not in html
    assert html.startswith("<!doctype html>") and not db.render_html(d, standalone=False).startswith("<!doctype")


def _js_metrics_source() -> str:
    t = db.TEMPLATE.read_text()
    return t[t.index("function metrics(rets)"):t.index("function verdictOf")]


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_the_page_computes_exactly_what_python_computes():
    cases = [[], [1.0, -0.5, 0.0, 2.0, -1.0], [0.5, 1.0], [-1.04, -1.05, 0.61, None, 2.86],
             list(np.round(np.random.default_rng(3).normal(0, 1.2, 60), 3))]
    if db.REPORTS.joinpath("dashboard.json").exists():
        d = json.loads(db.REPORTS.joinpath("dashboard.json").read_text())
        for b in d["books"]:
            cases.append([t["ret"] for t in d["trades"] if t["book"] == b and t["status"] == "closed"])
    js = _js_metrics_source() + f"\nconsole.log(JSON.stringify({json.dumps(cases)}.map(metrics)));"
    out = json.loads(subprocess.run(["node", "-e", js], capture_output=True, text=True, check=True).stdout)
    for case, got in zip(cases, out):
        assert got == db.metrics(case), case


# --------------------------------------------------------------------------- logging extensions
def test_the_ledger_keeps_the_plan_and_reads_old_files(tmp_path, monkeypatch):
    monkeypatch.setattr(ledger, "STATE", tmp_path)
    (tmp_path / "ledger_daytrade.csv").write_text(OLD_LEDGER.split("ORB-BAD")[0])
    t = {"id": "ORB-NVDA-2026-10-15", "symbol": "NVDA", "side": "long", "entry_time": "09:42", "exit_time": "09:55",
         "entry": 215.9, "exit": 213.09, "reason": "stop", "pct": -1.04, "stop": 213.09, "target": 221.5,
         "setup": "ORB · Big Tech", "rvol5": 1.4, "or_width_atr": 0.44, "gap": 0.9, "vwap_ok": True, "spy_ok": False}
    out = ledger.append("daytrade", [t], "2026-10-15")
    assert list(out.columns[:len(ledger.COLS)]) == ledger.COLS
    row = out[out["id"] == "ORB-NVDA-2026-10-15"].iloc[0]
    assert row["target"] == 221.5 and row["setup"] == "ORB · Big Tech" and row["rvol"] == 1.4
    assert len(out) == 4 and np.isnan(out[out["symbol"] == "MSFT"].iloc[0]["target"])


def _day(o_r=(99.8, 100.2), atr=2.0, path=None) -> orr.Day:
    n = orr.N_MIN
    c = np.full(n, 100.0)
    c[:5] = [100.0, 100.2, 99.8, 100.1, 100.0]
    c[5:] = path if path is not None else np.linspace(100.5, 103.5, n - 5)
    h, l = np.maximum(c, np.r_[c[0], c[:-1]]) + 0.01, np.minimum(c, np.r_[c[0], c[:-1]]) - 0.01
    h[:5], l[:5] = o_r[1], o_r[0]
    return orr.Day(o=np.r_[c[0], c[:-1]], h=h, l=l, c=c, v=np.ones(n), vwap=c.copy(), or_h=o_r[1], or_l=o_r[0],
                   or_w=o_r[1] - o_r[0], rvol5=1.0, vol_base=np.ones(n), prev_c=100.0, atr=atr, adv=1e9, gap=0.0)


def test_a_blocked_narrow_range_records_what_no_filter_would_have_done():
    x = _day()
    sa = qa = np.ones(orr.N_MIN, dtype=bool)
    p = om.CANDIDATE
    assert orr.first_signal(x, sa, qa, p, orr.FLAT_IDX - 1, x) is None        # 0.2 of ATR: too narrow
    alt = om.alternative(x, sa, qa, x, p, "range too narrow")
    assert alt["rule"] == "no range filter" and alt["side"] == "long" and alt["entry_time"] == "09:35"
    assert alt["result_pct"] > 0
    assert om.alternative(x, sa, qa, x, p, "traded") is None
    assert om.day_move_pct(x) > 0


def test_a_blocked_pick_with_no_alternative_trade_says_so():
    flat = _day(path=np.full(orr.N_MIN - 5, 100.0))
    sa = qa = np.ones(orr.N_MIN, dtype=bool)
    alt = om.alternative(flat, sa, qa, flat, om.CANDIDATE, "range too narrow")
    assert alt == {"rule": "no range filter", "result_pct": None}


# --------------------------------------------------------------------------- bots and data types
def test_each_record_lands_in_one_bot_and_one_data_type():
    t = lambda book, src=None: {"book": book, "source": src}
    assert db.bot_mode(t("daytrade", "live")) == ("daytrade", "live")
    assert db.bot_mode(t("daytrade", "corrected")) == ("daytrade", "live")
    assert db.bot_mode(t("daytrade", "replay")) == (None, None)        # the month replay covers it
    assert db.bot_mode(t("month_replay", "backtest")) == ("daytrade", "backtest")
    assert db.bot_mode(t("inplay", "live")) == ("inplay", "live")
    assert db.bot_mode(t("inplay", "replay")) == ("inplay", "backtest")
    assert db.bot_mode(t("swing_paper", "paper")) == ("swing", "paper")
    assert db.bot_mode(t("orb_paper", "live")) == (None, None)         # research, not a bot


def test_no_trade_is_counted_twice_in_a_bot_view():
    d = db.build(with_actions=False)
    tagged = [t for t in d["trades"] if t["bot"]]
    for t in tagged:
        assert t["mode"] in d["bots"][t["bot"]]["modes"]
    live = {(t["date"], t["symbol"]) for t in tagged if t["bot"] == "daytrade" and t["mode"] == "live"}
    replayed = {(t["date"], t["symbol"]) for t in d["trades"] if t["book"] == "daytrade" and t["source"] == "replay"}
    assert not live & replayed


def test_bot_status_is_unknown_without_run_history():
    d = db.build(with_actions=False)
    assert {b["state"] for b in d["bots"].values()} == {"unknown"}


def test_holding_time_and_today():
    assert db.hold_minutes({"entry_time": "09:35", "exit_time": "15:55"}) == 380
    assert db.hold_minutes({"entry_time": "2026-10-01", "exit_time": "2026-10-05"}) is None
    assert db.hold_minutes({"entry_time": "10:00", "exit_time": "09:00"}) is None
    from datetime import datetime as dt
    fri_am = dt(2026, 10, 16, 9, 0, tzinfo=db.ET)
    assert db.as_of_session(fri_am) == "2026-10-15"                    # Friday's session not closed yet
    assert db.as_of_session(dt(2026, 10, 16, 16, 5, tzinfo=db.ET)) == "2026-10-16"
    assert db.as_of_session(dt(2026, 10, 18, 12, 0, tzinfo=db.ET)) == "2026-10-16"   # Sunday -> Friday


def test_the_page_has_two_pages_and_no_dark_theme():
    t = db.TEMPLATE.read_text()
    assert 'data-tab="overview"' in t and 'data-tab="stocks"' in t
    assert "prefers-color-scheme: dark" not in t and "color-scheme: light" in t
