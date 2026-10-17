"""The dashboard reports what the records say and nothing more.

These pin the things that have gone wrong in this project before: trades not
equalling wins plus losses, missing values read as zero, a verdict calling a
negative number a success, and the same day counted twice when a backtest and
a live record are joined into one.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

from src import dashboard as db
from src import ledger
from src import orb_month as om
from src import orb_research as orr

ROOT = Path(__file__).resolve().parent.parent


# --------------------------------------------------------------------------- metrics

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
OLD_LEDGER = ("id,date,symbol,side,entry_time,exit_time,entry,exit,reason,pct,source\n"
              "ORB-MSFT-2026-10-05,2026-10-05,MSFT,long,09:38,15:55,,,bell,-0.69,corrected\n"
              "ORB-AAPL-2026-10-13,2026-10-13,AAPL,short,09:40,15:55,344.01,341.27,bell,0.61,replay\n"
              "ORB-META-2026-10-14,2026-10-14,META,short,09:35,15:55,749.14,737.49,bell,0.91,live\n"
              "ORB-BAD-2026-10-14,2026-10-14,BAD,long,09:35,,,,,,live\n")
AUDIT = ("sym,date,period,side,k,R,pct,why,hold\n"
         "AAPL,2026-10-12,test,short,6,0.2,0.27,bell,379\n"
         "MSFT,2026-10-13,test,long,5,-1.0,-1.02,stop,25\n"
         "META,2026-10-14,forward,short,5,0.9,0.91,bell,380\n")
SWING_LEDGER = ("strategy,ticker,side,entry_time,entry,exit_time,exit,reason,ret\n"
                "EMA21 x Weekly VWAP,SHOP,1,2026-09-28 10:30:00-04:00,138.5,2026-10-05 11:30:00-04:00,157.1,cross,0.1343\n"
                "EMA21 x Weekly VWAP,ORCL,1,2026-10-09 15:30:00-04:00,142.0,2026-10-14 13:30:00-04:00,130.8,stop,-0.0790\n")
SWING_BT = ("entry_time,exit_time,side,entry,exit,ret,reason,ticker\n"
            "2026-09-18 09:30:00-04:00,2026-09-21 12:30:00-04:00,1,10,12,0.2149,cross,MSTR\n"
            "2026-09-29 09:30:00-04:00,2026-10-01 12:30:00-04:00,1,10,9,-0.05,stop,COIN\n")


class FakeRepo:
    """A temporary repo folder plus the files 'on GitHub' that fetch_text will serve."""
    def __init__(self, path: Path):
        self.path, self.remote = path, {}

    def __truediv__(self, part):
        return self.path / part


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """An empty repo layout with no network: the builder reads only what a test writes."""
    for d in ("state", "reports"):
        (tmp_path / d).mkdir()
    monkeypatch.setattr(db, "STATE", tmp_path / "state")
    monkeypatch.setattr(db, "REPORTS", tmp_path / "reports")
    monkeypatch.setattr(db, "REPO_ROOT", tmp_path)
    fake = FakeRepo(tmp_path)
    monkeypatch.setattr(db, "fetch_text", lambda repo_, ref, path: fake.remote.get((repo_, path)))
    return fake


def _with_records(repo):
    (repo / "state" / "ledger_daytrade.csv").write_text(OLD_LEDGER)
    (repo / "reports" / "orb_audit_trades.csv").write_text(AUDIT)
    repo.remote[("bajwa19u/vwap-ema-swing", "state/ledger.csv")] = SWING_LEDGER
    repo.remote[("bajwa19u/vwap-ema-swing", "reports/audit_trades.csv")] = SWING_BT
    return db.build(with_actions=False)


def test_one_record_per_bot_backtest_then_real(repo):
    d = _with_records(repo)
    dt = [t for t in d["trades"] if t["bot"] == "daytrade"]
    assert d["bots"]["daytrade"]["live_start"] == "2026-10-14"
    # Backtest before the first live post; from then on only what was posted.
    assert [(t["date"], t["sym"], t["kind"]) for t in dt] == [
        ("2026-10-12", "AAPL", "backtest"), ("2026-10-13", "MSFT", "backtest"), ("2026-10-14", "META", "real")]
    sw = [t for t in d["trades"] if t["bot"] == "swing"]
    assert d["bots"]["swing"]["live_start"] == "2026-09-28"
    assert [(t["sym"], t["kind"]) for t in sw] == [("MSTR", "backtest"), ("SHOP", "real"), ("ORCL", "real")]
    assert sw[0]["ret"] == 21.49 and sw[-1]["ret"] == -7.9          # fractions become percent
    assert all(c["ok"] for c in d["checks"])


def test_replays_corrections_and_blank_results_are_not_real_posts(repo):
    (repo / "state" / "ledger_daytrade.csv").write_text(OLD_LEDGER)
    real = db.daytrade_real()
    assert [(t["sym"], t["ret"]) for t in real] == [("META", 0.91)]   # not the replay, the 5 Oct correction or BAD


def test_no_day_is_counted_twice_on_the_real_record(monkeypatch):
    monkeypatch.setattr(db, "fetch_text", lambda *a: None)          # the committed files only, no network
    d = db.build(with_actions=False)
    for k, b in d["bots"].items():
        mine = [t for t in d["trades"] if t["bot"] == k]
        if b["live_start"]:
            assert all(t["entry_date"] < b["live_start"] for t in mine if t["kind"] == "backtest")
            assert all(t["entry_date"] >= b["live_start"] for t in mine if t["kind"] == "real")
        assert b["all"]["n"] == len(mine) == b["all"]["wins"] + b["all"]["losses"] + b["all"]["flat"]


def test_without_any_real_trade_the_record_is_all_backtest(repo):
    (repo / "reports" / "orb_audit_trades.csv").write_text(AUDIT)
    d = db.build(with_actions=False)
    assert d["bots"]["daytrade"]["live_start"] is None
    assert {t["kind"] for t in d["trades"] if t["bot"] == "daytrade"} == {"backtest"}


def test_the_month_replay_stands_in_when_the_long_backtest_is_missing(repo):
    (repo / "reports" / "orb_month.json").write_text(json.dumps({"trades": [
        {"date": "2026-10-13", "symbol": "TSLA", "side": "long", "result_pct": -0.5, "exit_reason": "stop"}]}))
    ts, src = db.daytrade_backtest()
    assert src == "reports/orb_month.json" and ts[0]["ret"] == -0.5


def test_an_unreachable_source_keeps_the_previous_build(repo):
    prev = {"trades": [{"bot": "swing", "kind": "real", "date": "2026-10-05", "entry_date": "2026-09-28",
                        "sym": "SHOP", "side": "long", "ret": 13.43, "why": "cross", "et": None, "xt": None}]}
    d = db.build(with_actions=False, previous=prev)
    assert [t["sym"] for t in d["trades"] if t["bot"] == "swing"] == ["SHOP"]
    assert d["bots"]["swing"]["cached"] == ["real"]


def test_an_empty_repo_builds_without_inventing_anything(repo):
    d = db.build(with_actions=False)
    assert d["trades"] == [] and all(b["all"]["n"] == 0 for b in d["bots"].values())
    assert all(b["verdict"]["state"] == "none" and b["status"]["state"] == "unknown" for b in d["bots"].values())


def test_malformed_files_do_not_break_the_build(repo):
    (repo / "reports" / "orb_month.json").write_text("[]")
    (repo / "reports" / "orb_audit_trades.csv").write_text("not,a\ncsv")
    repo.remote[("bajwa19u/vwap-ema-swing", "state/ledger.csv")] = "garbage"
    assert db.build(with_actions=False)["trades"] == []


def test_bot_status_needs_run_history_to_say_ok():
    assert db.bot_status("daytrade", None)["state"] == "unknown"
    assert db.bot_status("daytrade", [])["state"] == "unknown"
    runs = [dict(file="live-bot.yml", status="completed", conclusion="failure", at="2026-10-16T20:00:00Z"),
            dict(file="live-bot.yml", status="completed", conclusion="success", at="2026-10-15T20:00:00Z"),
            dict(file="tests.yml", status="completed", conclusion="success", at="2026-10-16T21:00:00Z")]
    st = db.bot_status("daytrade", runs)
    assert st["state"] == "failing" and st["failures"] == 1 and st["last_run"] == "2026-10-15T20:00:00Z"
    assert db.bot_status("daytrade", runs[1:])["state"] == "ok"


def test_today_is_the_last_closed_session():
    from datetime import datetime as dt
    assert db.as_of_session(dt(2026, 10, 16, 9, 0, tzinfo=db.ET)) == "2026-10-15"     # Friday's session not closed yet
    assert db.as_of_session(dt(2026, 10, 16, 16, 5, tzinfo=db.ET)) == "2026-10-16"
    assert db.as_of_session(dt(2026, 10, 18, 12, 0, tzinfo=db.ET)) == "2026-10-16"    # Sunday -> Friday


def test_the_dashboard_job_posts_nothing_and_reads_only_its_token():
    text = (ROOT / ".github" / "workflows" / "dashboard.yml").read_text()
    assert re.search(r'ref:\s*"?\$\{\{ github\.ref_name \}\}', text)   # CLAUDE.md: never overwrite newer state
    for banned in ("DISCORD", "ALPACA", "WEBHOOK"):
        assert banned not in text.upper()
    assert "contents: write" in text and "actions: read" in text


def test_no_secret_reaches_the_output(repo, monkeypatch):
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/123/secret")
    d = json.dumps(_with_records(repo))
    assert "discord.com/api/webhooks" not in d
    assert not re.search(r"gh[pousr]_[A-Za-z0-9]{20,}", d)


# --------------------------------------------------------------------------- page
def test_the_page_embeds_the_data_safely(repo):
    d = _with_records(repo)
    d["bots"]["daytrade"]["detail"] = "</script><script>alert(1)</script>"
    html = db.render_html(d)
    assert "/*__DASHBOARD_DATA__*/null" not in html
    assert "</script><script>alert(1)" not in html
    assert html.startswith("<!doctype html>") and not db.render_html(d, standalone=False).startswith("<!doctype")


def test_the_page_is_simple_themed_and_has_no_record_picker():
    t = db.TEMPLATE.read_text()
    assert "prefers-color-scheme: dark" in t and ':root[data-theme="dark"]' in t
    assert re.search(r"cdnjs\.cloudflare\.com/ajax/libs/echarts/\d+\.\d+\.\d+/", t)     # pinned version
    for gone in ('data-tab="stocks"', "Stock Analysis", "live / paper / backtest", 'data-mode='):
        assert gone not in t
    for p in ("Today", "Week", "Month", "3 months", "Year", "All"):
        assert f'label: "{p}"' in t


def test_the_page_shows_no_r_multiples_or_dollar_amounts():
    t = db.TEMPLATE.read_text()
    shown = re.sub(r"\$\{|`\$|\\\$", "", t)                       # template literals are not dollar signs
    assert "$" not in re.sub(r"<script>.*</script>", "", shown, flags=re.S)
    assert not re.search(r"\bR multiple|\bavg R\b|[0-9]R\b", t)


def _js_metrics_source() -> str:
    t = db.TEMPLATE.read_text()
    return t[t.index("function metrics(rets)"):t.index("// end metrics")]


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_the_page_computes_exactly_what_python_computes():
    cases = [[], [1.0, -0.5, 0.0, 2.0, -1.0], [0.5, 1.0], [-1.04, -1.05, 0.61, None, 2.86],
             list(np.round(np.random.default_rng(3).normal(0, 1.2, 60), 3))]
    if db.REPORTS.joinpath("dashboard.json").exists():
        d = json.loads(db.REPORTS.joinpath("dashboard.json").read_text())
        for b in d["bots"]:
            cases.append([t["ret"] for t in d["trades"] if t["bot"] == b])
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

