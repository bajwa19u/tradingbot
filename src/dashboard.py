"""The analytics dashboard's data: one JSON built only from records the repo
already keeps, plus the self-contained page that reads it.

Nothing here computes a signal or re-runs a strategy. It reads what the bots
and studies wrote and puts it side by side:

  books     every closed trade, one record type, from
              state/ledger_daytrade.csv   what the day-trade channel posted
              state/ledger_inplay.csv     what the in-play channel posted
              reports/orb_paper.csv       the ORB candidate's forward paper record
              state/paper.json            the swing breakout's forward paper record
              reports/orb_month.json      the live rule replayed on the last month
  setups    every pick the live rule looked at last month, and why it did not trade
  lab       the research runs (train / validation / test) and the forward record
  health    the latency log, the announce records and GitHub Actions run history

Rules this file keeps:
  - One calculation per metric: `metrics()`. The page carries a line-for-line
    port; tests/test_dashboard.py runs both on the same records.
  - A book's results are only ever summed inside that book. Units differ: the
    channels and the replay report % of the account with 1% risked per trade,
    the ORB paper record reports the stock's % move.
  - Open positions are listed, never counted in closed-trade statistics.
  - Anything not recorded is None (the page shows N/A), never 0.
  - Verdicts check the all-negative case first.
  - No secrets: the Actions API is read with the job's own token and only run
    names, times and conclusions are kept.

Usage: python -m src.dashboard [--no-actions]
"""
from __future__ import annotations

import argparse
import ast
import csv
import json
import math
import os
import re
import statistics
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from .config import REPO_ROOT

ET = ZoneInfo("America/New_York")
STATE = REPO_ROOT / "state"
REPORTS = REPO_ROOT / "reports"
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
TEMPLATE = REPO_ROOT / "tools" / "dashboard_template.html"
OUT_JSON = REPORTS / "dashboard.json"
OUT_HTML = REPORTS / "dashboard.html"
OUT_MD = REPORTS / "dashboard.md"
SCHEMA = 1
SMALL_N = 30          # fewer closed trades than this is called too few to judge
TINY_N = 10           # a group this small gets no win rate comparison at all
SESSION = ("09:30", "16:00")

# Which rule the day-trade channel ran, by date (CLAUDE.md, reports/live_corrections.md,
# and the repo variable's own timestamp, 2026-10-05T17:32Z). Rows that carry a `setup`
# column use that instead.
DAYTRADE_VERSIONS = [("0000-00-00", "ORB · Stocks in Play"), ("2026-10-06", "ORB · Big Tech")]

BOOKS = {
    "daytrade": dict(
        title="Day-trade channel", kind="live", universe="TSLA AMD NVDA META AAPL MSFT", slip="0.05%/side",
        unit="acct", unit_label="% of account, 1% risked per trade",
        costs="0.05% slippage a side, modelled (not fills)",
        source="state/ledger_daytrade.csv",
        about="Every closed trade the day-trade channel posted. 5 Oct is the corrected live record; "
              "rows marked replay were not posted live but re-run on that day's bars when the ledger "
              "was backfilled. Results are what the rule's own exit logic scored, not broker fills."),
    "inplay": dict(
        title="In-play channel", kind="live", universe="top 5 in play (wide list)", slip="0.05%/side",
        unit="acct", unit_label="% of account, 1% risked per trade",
        costs="0.05% slippage a side, modelled (not fills)",
        source="state/ledger_inplay.csv",
        about="Every closed trade the in-play channel posted (top 5 by opening relative volume). "
              "Rows marked replay were backfilled from bars, not posted live."),
    "orb_paper": dict(
        title="ORB candidate · paper", kind="paper", universe="top 10 in play of ~105", slip="0.05%/side",
        unit="move", unit_label="% move of the stock, entry to exit",
        costs="0.05% slippage a side; real-cost column uses the SIP NBBO seconds after each signal",
        source="reports/orb_paper.csv",
        about="Forward record of the ORB in-play candidate. Posts nothing. 'backtest only' rows "
              "were never seen live; 'live' rows were seen by the polling job."),
    "swing_paper": dict(
        title="Swing breakout · paper", kind="paper", universe="35 volatile names, 3% screen", slip="0.03%",
        unit="acct", unit_label="% of account, 1% risked per trade",
        costs="0.03% slippage, pessimistic fills (stop wins ties)",
        source="state/paper.json",
        about="Forward test of the volatility-screened breakout since 28 Sep, replayed daily by "
              "src/paper.py. This rule failed its out-of-sample test before going on paper."),
    "month_replay": dict(
        title="Live rule · month replay", kind="backtest", universe="TSLA AMD NVDA META AAPL MSFT", slip="0.05%/side",
        unit="acct", unit_label="% of account, 1% risked per trade",
        costs="0.05% slippage a side, modelled",
        source="reports/orb_month.json",
        about="The rule the day-trade channel runs now, replayed over the last 21 sessions by "
              "src/orb_month.py. A backtest: it includes days before the rule went live."),
}


# The three bots, as the workflows run them. Each trade record is tagged with one
# bot and one mode; the page never sums across modes. The ORB candidate paper
# record rides inside the in-play job but trades a different rule, so it belongs
# to no bot and is shown only as research.
BOTS = {
    "daytrade": dict(
        name="Day-trade bot", strategy="Opening-range breakout on 6 big tech stocks",
        detail="Posts to the Discord day-trade channel. First 1-minute close outside the 09:30-09:34 range "
               "before 09:45, range at least 0.35 of daily ATR, stop at the session extreme, target 2x risk, "
               "out by 15:55. Ran the in-play list on 5 Oct, big tech from 6 Oct.",
        workflows=["live-open.yml", "live-bot.yml", "day-end.yml"], hold="intraday",
        modes={"live": "Trades posted to Discord (5 Oct is the corrected live record).",
               "backtest": "The live rule replayed on the last 21 sessions (src/orb_month.py)."}),
    "inplay": dict(
        name="In-play bot", strategy="Opening-range breakout on the day's top 5 stocks in play",
        detail="Posts to the Discord in-play channel. Ranks a wide list by first-5-minute relative volume at "
               "09:35, trades the top 5, wide stop at 0.5 ATR, no target, out at 15:55.",
        workflows=["inplay-live.yml"], hold="intraday",
        modes={"live": "Trades posted to Discord.",
               "backtest": "Sessions before the ledger existed, re-run on that day's bars (ledger backfill)."}),
    "swing": dict(
        name="Swing bot", strategy="Volatility-screened breakout on daily bars, held for days",
        detail="Signals at 15:45 ET (preclose), scored after the close (paper). A 10-day coil breaks out "
               "on volume; 1% risk per trade on a $2,000 paper account. Failed its out-of-sample test "
               "before going on paper.",
        workflows=["preclose.yml", "paper.yml", "live.yml"], hold="days",
        modes={"paper": "Forward paper test since 28 Sep, replayed daily by src/paper.py."}),
}
MODES = {"live": "Live", "paper": "Paper", "backtest": "Backtest"}


def bot_mode(t: dict) -> tuple[str | None, str | None]:
    """(bot, mode) for one trade record, or (None, None) when it belongs to no bot view.

    Day-trade ledger rows marked 'replay' are left out: every one of those sessions
    is also in the month replay, so counting both would count the trade twice."""
    b, src = t["book"], t.get("source")
    if b == "daytrade":
        return ("daytrade", "live") if src in ("live", "corrected") else (None, None)
    if b == "month_replay":
        return "daytrade", "backtest"
    if b == "inplay":
        return "inplay", "live" if src == "live" else "backtest"
    if b == "swing_paper":
        return "swing", "paper"
    return None, None


def hold_minutes(t: dict) -> float | None:
    """Minutes between entry and exit for intraday trades (HH:MM on one day)."""
    a, b = t.get("entry_time") or "", t.get("exit_time") or ""
    if not (re.fullmatch(r"\d\d:\d\d", a) and re.fullmatch(r"\d\d:\d\d", b)):
        return None
    m = (int(b[:2]) * 60 + int(b[3:])) - (int(a[:2]) * 60 + int(a[3:]))
    return float(m) if m >= 0 else None


def as_of_session(now_et: datetime) -> str:
    """The latest weekday whose session has closed by `now_et`: what 'Today' means on the page."""
    d = now_et.date() if now_et.hour >= 16 else now_et.date() - timedelta(days=1)
    while d.weekday() > 4:
        d -= timedelta(days=1)
    return d.isoformat()

# --------------------------------------------------------------------------- helpers
def num(v):
    """A finite float, or None for blanks, NaN and junk. Never 0 for missing."""
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def text(v):
    if v is None:
        return None
    s = str(v).strip()
    return s if s and s.lower() not in ("nan", "none", "null") else None


def flag(v):
    s = text(v)
    if s is None:
        return None
    return {"true": True, "false": False, "yes": True, "no": False}.get(s.lower())


def read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return default


def r4(x):
    return None if x is None else round(float(x), 4)


# --------------------------------------------------------------------------- the one metric
def metrics(rets) -> dict:
    """Closed-trade statistics for one list of per-trade results, in order.

    wins are > 0, losses < 0, flat == 0, and n == wins + losses + flat always.
    The equity line is the running sum (results are a fixed share of the
    account, not compounded). Drawdowns are positive numbers, in the same
    unit as the results. Profit factor is None with no losing trade.
    """
    r = [x for x in (num(v) for v in rets) if x is not None]
    n = len(r)
    wins = [x for x in r if x > 0]
    losses = [x for x in r if x < 0]
    out = dict(n=n, wins=len(wins), losses=len(losses), flat=n - len(wins) - len(losses),
               win_rate=None, total=None, avg=None, avg_win=None, avg_loss=None, pf=None,
               max_dd=None, cur_dd=None, sd=None, ci_low=None, ci_high=None, best=None, worst=None)
    if not n:
        return out
    cum = peak = mdd = 0.0
    for x in r:
        cum += x
        peak = max(peak, cum)
        mdd = max(mdd, peak - cum)
    gl = -sum(losses)
    out.update(win_rate=100.0 * len(wins) / n, total=cum, avg=cum / n,
               avg_win=sum(wins) / len(wins) if wins else None,
               avg_loss=sum(losses) / len(losses) if losses else None,
               pf=sum(wins) / gl if gl > 0 else None,
               max_dd=mdd, cur_dd=peak - cum, best=max(r), worst=min(r))
    if n > 1:
        sd = statistics.stdev(r)
        half = 1.96 * sd / math.sqrt(n)
        out.update(sd=sd, ci_low=cum / n - half, ci_high=cum / n + half)
    return {k: (r4(v) if isinstance(v, float) else v) for k, v in out.items()}


def verdict(m: dict, unit_label: str) -> dict:
    """Is it profitable after costs? The all-negative case is checked first."""
    n, tot = m["n"], m["total"]
    if not n:
        return dict(state="none", text="No closed trades yet.")
    if tot is not None and tot <= 0:
        return dict(state="neg", text=f"No. Net {tot:+.2f} ({unit_label}) over {n} closed trades, "
                                      f"{m['wins']} won, {m['losses']} lost.")
    if n < SMALL_N:
        return dict(state="few", text=f"Net {tot:+.2f} over {n} trades: too few to judge "
                                      f"(under {SMALL_N}). Read it as a record, not a result.")
    if m["ci_low"] is not None and m["ci_low"] > 0:
        return dict(state="pos", text=f"Net {tot:+.2f} over {n} trades and the 95% interval of the "
                                      f"average trade stays above zero.")
    return dict(state="noise", text=f"Net {tot:+.2f} over {n} trades, but the 95% interval of the "
                                    f"average trade includes zero: not distinguishable from noise.")


# --------------------------------------------------------------------------- books
def _version_for(date: str) -> str:
    v = DAYTRADE_VERSIONS[0][1]
    for start, name in DAYTRADE_VERSIONS:
        if date >= start:
            v = name
    return v


def ledger_trades(channel: str) -> list[dict]:
    """The channel ledgers. Extra columns written since Oct 2026 (stop, target,
    setup, rvol, ...) are read when present."""
    out = []
    for row in read_csv(STATE / f"ledger_{channel}.csv"):
        date = text(row.get("date"))
        if not date:
            continue
        setup = text(row.get("setup")) or (_version_for(date) if channel == "daytrade" else "In-play · opening range")
        ret = num(row.get("pct"))
        side = text(row.get("side"))
        gap = num(row.get("gap_pct"))
        out.append(dict(
            id=text(row.get("id")), book=channel, date=date, symbol=text(row.get("symbol")),
            side=side, setup=setup, source=text(row.get("source")),
            entry_time=text(row.get("entry_time")), exit_time=text(row.get("exit_time")),
            entry=num(row.get("entry")), stop=num(row.get("stop")), target=num(row.get("target")),
            exit=num(row.get("exit")), reason=text(row.get("reason")),
            ret=ret, ret_real=None, move=None, status="closed" if ret is not None else "unresolved",
            mfe=None, mae=None, latency_s=None, expired=None,
            f=dict(rvol=num(row.get("rvol")), orw_atr=num(row.get("or_width_atr")), gap_pct=gap,
                   gap_side=_gap_side(gap, side), vwap_ok=flag(row.get("vwap_ok")),
                   spy_ok=flag(row.get("spy_ok")), level=num(row.get("level")))))
    return out


def _gap_side(gap, side):
    if gap is None or side not in ("long", "short") or gap == 0:
        return None
    return "with gap" if (gap > 0) == (side == "long") else "against gap"


def orb_paper_trades() -> list[dict]:
    out = []
    for row in read_csv(REPORTS / "orb_paper.csv"):
        date, sym = text(row.get("date")), text(row.get("symbol"))
        if not (date and sym):
            continue
        ret = num(row.get("result_pct"))
        reason = text(row.get("exit_reason"))
        side = text(row.get("side"))
        gap = num(row.get("gap_pct"))
        expired = flag(row.get("expired"))
        src = text(row.get("source"))
        out.append(dict(
            id=f"OP-{sym}-{date}", book="orb_paper", date=date, symbol=sym, side=side,
            setup="ORB candidate (top 10 in play, BE at +1x)",
            source=("live, expired" if expired else src),
            entry_time=text(row.get("bar")), exit_time=text(row.get("exit_bar")),
            entry=num(row.get("entry")), stop=num(row.get("stop")), target=num(row.get("target")),
            exit=None, reason=reason, ret=ret, ret_real=num(row.get("result_real_pct")), move=ret,
            status="closed" if ret is not None and reason else "open",
            mfe=None, mae=None, latency_s=num(row.get("latency_s")), expired=expired,
            f=dict(rvol=num(row.get("rvol5")), orw_atr=num(row.get("or_width_atr")), gap_pct=gap,
                   gap_side=_gap_side(gap, side), vwap_ok=flag(row.get("vwap_ok")),
                   spy_ok=flag(row.get("spy_ok")), qqq_ok=flag(row.get("qqq_ok")),
                   or_high=num(row.get("or_high")), or_low=num(row.get("or_low")), level=num(row.get("level")),
                   risk_pct=num(row.get("risk_pct")), breakout_rvol=num(row.get("breakout_rvol")),
                   displacement=num(row.get("displacement")), extension=num(row.get("extension")),
                   same_side_10m=num(row.get("same_side_10m")), seen_at=text(row.get("seen_at")),
                   backtest_agrees=text(row.get("backtest_agrees")),
                   entry_cost_pct=num(row.get("entry_cost_pct")), exit_cost_pct=num(row.get("exit_cost_pct")))))
    return out


def swing_paper() -> tuple[list[dict], list[dict], dict]:
    d = read_json(STATE / "paper.json", {}) or {}
    risk = num((d.get("settings") or {}).get("risk_pct")) or None
    trades, open_ = [], []
    for t in d.get("trades") or []:
        pnl = t.get("pnl") or {}
        sym, date = text(t.get("symbol")), text(t.get("exit_date"))
        if not (sym and date):
            continue
        r_to_acct = (lambda v: None if v is None or risk is None else v * risk)
        trades.append(dict(
            id=f"SW-{sym}-{text(t.get('entry_date'))}", book="swing_paper", date=date, symbol=sym,
            side="long", setup="Breakout base10_sq4.0_vol1.0, 3% screen", source="paper",
            entry_time=text(t.get("entry_date")), exit_time=date,
            entry=num(t.get("entry")), stop=num(t.get("stop")), target=num(t.get("target")),
            exit=num(t.get("exit")), reason=text(t.get("reason")),
            ret=num(pnl.get("account_pct")), ret_real=None, move=num(pnl.get("move_pct")),
            status="closed" if num(pnl.get("account_pct")) is not None else "unresolved",
            mfe=r_to_acct(num(t.get("mfe_r"))), mae=r_to_acct(num(t.get("mae_r"))),
            latency_s=None, expired=None, f=dict(bars_held=num(t.get("bars_held")), why=text(t.get("why")))))
    for p in d.get("open") or []:
        open_.append(dict(
            book="swing_paper", symbol=text(p.get("symbol")), entry_date=text(p.get("entry_date")),
            entry=num(p.get("entry")), stop=num(p.get("stop")), target=num(p.get("target")),
            bars_held=num(p.get("bars_held")),
            best_acct=None if num(p.get("best_R")) is None or risk is None else round(num(p.get("best_R")) * risk, 3),
            sizeable=bool(p.get("shares")), unrealized=None,
            note="No mark price is stored, so unrealized P&L is N/A."))
    meta = dict(as_of=text(d.get("as_of")), generated=text(d.get("generated")),
                settings=d.get("settings") or {}, halted=d.get("halted"),
                reported=dict(n=d.get("n"), wins=d.get("wins"), losses=d.get("losses"),
                              return_pct=d.get("return_pct"), max_dd_pct=d.get("max_dd_pct")))
    return trades, open_, meta


def month_replay() -> tuple[list[dict], dict]:
    d = read_json(REPORTS / "orb_month.json", {}) or {}
    trades = []
    for t in d.get("trades") or []:
        date, sym = text(t.get("date")), text(t.get("symbol"))
        if not (date and sym):
            continue
        side, gap = text(t.get("side")), num(t.get("gap_pct"))
        trades.append(dict(
            id=f"BT-{sym}-{date}", book="month_replay", date=date, symbol=sym, side=side,
            setup=text(d.get("strategy")) or "live rule", source="backtest",
            entry_time=text(t.get("entry_time")), exit_time=text(t.get("exit_time")),
            entry=num(t.get("entry")), stop=num(t.get("stop")), target=num(t.get("target")),
            exit=num(t.get("exit")), reason=text(t.get("exit_reason")),
            ret=num(t.get("result_pct")), ret_real=None, move=num(t.get("move_pct")),
            status="closed" if num(t.get("result_pct")) is not None else "unresolved",
            mfe=None, mae=None, latency_s=None, expired=None,
            f=dict(rvol=num(t.get("rvol5")), orw_atr=num(t.get("or_width_atr")), gap_pct=gap,
                   gap_side=_gap_side(gap, side), rank=num(t.get("rank")),
                   risk_pct=num(t.get("risk_pct_price")), hold_min=num(t.get("hold_min")))))
    return trades, d


# --------------------------------------------------------------------------- rejected setups
def setups(month: dict) -> dict:
    """Every pick the live rule considered in the month replay, what happened to it,
    and (where orb_month recorded one) what an explicitly named alternative rule
    would have done with the same entry, stop, exit and costs."""
    picks = []
    for day in month.get("days") or []:
        for p in day.get("picks") or []:
            alt = p.get("alt") or {}
            picks.append(dict(date=day.get("date"), symbol=p.get("symbol"), outcome=p.get("outcome"),
                              rvol=num(p.get("rvol5")), orw_atr=num(p.get("or_width_atr")),
                              gap_pct=num(p.get("gap_pct")), day_move=num(p.get("day_move_pct")),
                              alt_rule=text(alt.get("rule")), alt_ret=num(alt.get("result_pct")),
                              alt_side=text(alt.get("side")), alt_entry=text(alt.get("entry_time")),
                              alt_reason=text(alt.get("exit_reason"))))
    counts: dict[str, int] = {}
    for p in picks:
        counts[p["outcome"] or "not recorded"] = counts.get(p["outcome"] or "not recorded", 0) + 1
    alts = {}
    for p in picks:
        if p["outcome"] != "traded" and p["alt_rule"]:
            alts.setdefault(p["alt_rule"], []).append(p["alt_ret"])
    # The 5 Oct big-tech study already measured what the two filters keep out.
    study = md_table(REPORTS / "orb_bigtech.md", "## Both date ranges")
    return dict(evaluated=len(picks), counts=counts, picks=picks,
                alternatives={k: dict(metrics=metrics(v), taken=sum(x is not None for x in v), considered=len(v))
                              for k, v in alts.items()},
                alt_recorded=any(p["alt_rule"] for p in picks),
                study=study, study_source="reports/orb_bigtech.md · Both date ranges")


def md_table(path: Path, heading: str) -> list[list[str]]:
    """Rows of the first markdown table under `heading` (header row first)."""
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return []
    try:
        i = lines.index(heading)
    except ValueError:
        return []
    rows = []
    for ln in lines[i + 1:]:
        if ln.startswith("|"):
            cells = [c.strip() for c in ln.strip().strip("|").split("|")]
            if not all(set(c) <= set("-: ") for c in cells):
                rows.append(cells)
        elif rows:
            break
    return rows


# --------------------------------------------------------------------------- research lab
def _p_params(s: str | None) -> dict:
    """`P(universe='top10', orw=(0.35, 9e9), ...)` -> {name: value text}."""
    if not s or not s.startswith("P("):
        return {}
    try:
        call = ast.parse(s, mode="eval").body
        return {k.arg: ast.unparse(k.value) for k in call.keywords}
    except (SyntaxError, AttributeError):
        return {}


def _r_stats(st: dict | None, **meta) -> dict:
    """Research stats are in R at 1% risk, so avg R x 1% = % of account per trade."""
    st = st or {}
    return dict(meta, trades=st.get("n", st.get("trades")), win_rate=r4(num(st.get("win"))),
                avg=r4(num(st.get("avg"))), total=r4(num(st.get("total"))), pf=r4(num(st.get("pf"))),
                max_dd=r4(num(st.get("dd"))), unit="acct")


def _pct(s: str):
    m = re.match(r"^([+-]?\d+(?:\.\d+)?)%?$", (s or "").replace("−", "-"))
    return float(m.group(1)) if m else None


def lab(books: dict) -> dict:
    research = read_json(REPORTS / "orb_research.json", {}) or {}
    checks = read_json(REPORTS / "orb_checks.json", {}) or {}
    improve = read_json(REPORTS / "orb_improve.json", {}) or {}
    bigtech = read_json(REPORTS / "orb_bigtech.json", {}) or {}
    rows = []
    cand = _p_params(research.get("candidate"))
    if research.get("test"):
        rows.append(_r_stats(research["test"], study="ORB in-play research", label="candidate", split="test",
                             holdout_status="used again 3 Oct (orb_checks, orb_improve): no longer unseen",
                             dates="last third of 252 sessions to 2 Oct 2026", universe="top 10 in play of ~105",
                             slippage="0.05%/side", variants=40, params=cand, source="reports/orb_research.json · test"))
    for split in ("train", "val", "test"):
        st = (checks.get("measured") or {}).get(split)
        if st:
            rows.append(_r_stats(st, study="ORB checks (measured costs)", label="candidate", split=split,
                                 holdout_status="test reused" if split == "test" else "",
                                 dates="252 sessions to 2 Oct 2026, split by date", universe="top 10 in play of ~105",
                                 slippage="measured SIP NBBO", variants=None,
                                 params=cand, source=f"reports/orb_checks.json · measured.{split}"))
    fin = _p_params(improve.get("final"))
    for win, block in (improve.get("comparison") or {}).items():
        for lbl, st in block.items():
            rows.append(_r_stats(st, study="ORB improvement", label=lbl, split=f"{win} to 2 Oct (in-sample)",
                                 holdout_status="selection window: in-sample", dates=f"last {win} to 2026-10-02",
                                 universe="top 10 in play of ~105", slippage="0.05%/side", variants=13,
                                 params=fin if lbl == "improved" else cand,
                                 source=f"reports/orb_improve.json · comparison.{win}.{lbl}"))
    tbl = md_table(REPORTS / "orb_bigtech.md", "## Both date ranges")
    for cells in tbl[1:]:
        if len(cells) < 11:
            continue
        for split, off in (("recent 63 sessions (looked at)", 1), ("earlier 189 sessions (confirm)", 6)):
            avg, total = _pct(cells[off + 2]), _pct(cells[off + 4])
            rows.append(dict(study="Big tech list", label=cells[0], split=split,
                             holdout_status="in-sample" if off == 1 else "confirmation range, read once",
                             dates="2026-07-07..2026-10-02" if off == 1 else "2025-09-30..2026-07-06",
                             universe="TSLA AMD NVDA META AAPL MSFT" if "in-play" not in cells[0] else "top 10 in play",
                             slippage="0.05%/side", variants=5, params={},
                             trades=int(cells[off]) if cells[off].isdigit() else None,
                             win_rate=_pct(cells[off + 1]), avg=avg, total=total, pf=num(cells[off + 3]),
                             max_dd=None, unit="acct", source="reports/orb_bigtech.md · Both date ranges"))
    # Forward records: dates no study chose.
    for key, label, pred in (("daytrade", "posted live (big tech rule)", lambda t: t["source"] == "live"),
                             ("daytrade", "ledger incl. replay & corrected", lambda t: True),
                             ("inplay", "posted live", lambda t: t["source"] == "live"),
                             ("orb_paper", "seen live in time", lambda t: t["source"] == "live"),
                             ("orb_paper", "all (backtest view)", lambda t: True),
                             ("swing_paper", "forward paper", lambda t: True)):
        ts = [t for t in books[key] if t["status"] == "closed" and pred(t)]
        m = metrics(t["ret"] for t in ts)
        dates = sorted(t["date"] for t in ts)
        rows.append(dict(study="Forward record", label=f"{BOOKS[key]['title']} · {label}", split="forward",
                         holdout_status="unseen: dates after the rule was chosen",
                         dates=f"{dates[0]}..{dates[-1]}" if dates else "none",
                         universe=BOOKS[key]["universe"] if "replay" not in label else BOOKS[key]["universe"] + " (5 Oct: top 10 in play)",
                         slippage=BOOKS[key]["slip"], variants=None, params={}, trades=m["n"],
                         win_rate=m["win_rate"], avg=m["avg"], total=m["total"], pf=m["pf"],
                         max_dd=m["max_dd"], unit=BOOKS[key]["unit"], source=BOOKS[key]["source"]))
    return dict(rows=rows,
                noise_floor={str(n): round(math.sqrt(2 * math.log(n)), 2) for n in (5, 13, 40, 114)},
                gates=dict(orb_research=dict(passed=research.get("gate_passed"), lines=research.get("gate")),
                           orb_checks=dict(passed=checks.get("passed"), lines=checks.get("gate"))),
                bigtech_windows={w: {k: _r_stats(v) for k, v in blk.items()} for w, blk in bigtech.items()})


# --------------------------------------------------------------------------- health
def _cron_fields(expr: str):
    parts = expr.split()
    if len(parts) != 5:
        return None

    def field(s, lo, hi):
        vals = set()
        for part in s.split(","):
            step = 1
            if "/" in part:
                part, st = part.split("/")
                step = int(st)
            if part == "*":
                a, b = lo, hi
            elif "-" in part:
                a, b = (int(x) for x in part.split("-"))
            else:
                a = b = int(part)
            vals.update(range(a, b + 1, step))
        return vals
    try:
        return (field(parts[0], 0, 59), field(parts[1], 0, 23), field(parts[2], 1, 31),
                field(parts[3], 1, 12), {d % 7 for d in field(parts[4], 0, 7)})
    except ValueError:
        return None


def last_fire(expr: str, before: datetime) -> datetime | None:
    """The latest time (UTC) at or before `before` that a cron expression fires."""
    f = _cron_fields(expr)
    if f is None:
        return None
    mins, hours, doms, mons, dows = f
    t = before.replace(second=0, microsecond=0)
    for _ in range(60 * 24 * 8):
        if (t.minute in mins and t.hour in hours and t.day in doms and t.month in mons
                and (t.isoweekday() % 7) in dows):
            return t
        t -= timedelta(minutes=1)
    return None


def workflows() -> list[dict]:
    out = []
    for f in sorted(WORKFLOWS.glob("*.yml")):
        try:
            y = yaml.safe_load(f.read_text()) or {}
        except yaml.YAMLError as exc:
            out.append(dict(file=f.name, name=f.name, crons=[], dispatch=False, error=str(exc)[:200]))
            continue
        on = y.get("on", y.get(True)) or {}
        on = {k: None for k in on} if isinstance(on, list) else on if isinstance(on, dict) else {on: None}
        crons = [c.get("cron") for c in (on.get("schedule") or []) if isinstance(c, dict)]
        out.append(dict(file=f.name, name=y.get("name") or f.name, crons=crons,
                        dispatch="workflow_dispatch" in on, push="push" in on))
    return out


def fetch_runs(days: int = 14) -> tuple[list[dict] | None, str]:
    """Recent Actions runs: names, events, times, conclusions. Nothing else is kept."""
    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    repo = os.environ.get("GITHUB_REPOSITORY") or "bajwa19u/tradingbot"
    path = f"repos/{repo}/actions/runs?per_page=100&created=>={since}"
    raw: list[dict] = []
    token = os.environ.get("GITHUB_TOKEN")
    try:
        if token:
            import requests
            for page in range(1, 6):
                r = requests.get(f"https://api.github.com/{path}&page={page}", timeout=30,
                                 headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"})
                r.raise_for_status()
                got = r.json().get("workflow_runs", [])
                raw += got
                if len(got) < 100:
                    break
            how = "GitHub API (job token)"
        else:
            res = None
            for _ in range(2):                       # one retry: the local network drops reads now and then
                res = subprocess.run(["gh", "api", "--paginate", path, "--jq", ".workflow_runs[]"],
                                     capture_output=True, text=True, timeout=120)
                if res.returncode == 0:
                    break
            if res.returncode != 0:
                # The raw error can carry local addresses; keep only what kind of failure it was.
                kind = "network" if re.search(r"tcp|dial|timeout|connection", res.stderr, re.I) else "auth or API"
                return None, f"gh CLI failed ({kind} error)"
            raw = [json.loads(x) for x in res.stdout.splitlines() if x.strip()]
            how = "gh CLI"
    except Exception as exc:                                          # noqa: BLE001
        return None, f"unavailable ({type(exc).__name__})"
    keep = ("name", "path", "event", "status", "conclusion", "created_at", "updated_at", "run_started_at", "head_branch")
    return [{k: r.get(k) for k in keep} for r in raw], how


def _utc(s):
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def actions_summary(runs: list[dict] | None, flows: list[dict], now: datetime) -> list[dict]:
    by_file = {}
    for r in runs or []:
        by_file.setdefault(Path(r.get("path") or "").name, []).append(r)
    out = []
    for w in flows:
        rs = sorted(by_file.get(w["file"], []), key=lambda r: r.get("created_at") or "", reverse=True)
        week = [r for r in rs if (_utc(r.get("created_at")) or now) >= now - timedelta(days=7)]
        done = [r for r in rs if r.get("status") == "completed"]
        ok = next((r for r in done if r.get("conclusion") == "success"), None)
        delays = []
        for r in week:
            if r.get("event") != "schedule":
                continue
            c = _utc(r.get("run_started_at") or r.get("created_at"))
            fires = [last_fire(e, c) for e in w["crons"]] if c else []
            fires = [f for f in fires if f]
            if fires:
                delays.append((c - max(fires)).total_seconds() / 60)
        count = {}
        for r in week:
            k = r.get("conclusion") or r.get("status") or "unknown"
            count[k] = count.get(k, 0) + 1
        out.append(dict(file=w["file"], name=w["name"], crons=w["crons"], dispatch=w["dispatch"],
                        scheduled=bool(w["crons"]),
                        last_run=rs[0].get("created_at") if rs else None,
                        last_conclusion=(rs[0].get("conclusion") or rs[0].get("status")) if rs else None,
                        last_success=ok.get("updated_at") if ok else None, week=count,
                        failures=[dict(at=r.get("created_at"), event=r.get("event")) for r in week
                                  if r.get("conclusion") in ("failure", "timed_out", "startup_failure")][:10],
                        start_delay_med_min=round(statistics.median(delays), 1) if delays else None,
                        start_delay_max_min=round(max(delays), 1) if delays else None))
    return out


def _hhmm(ts: str | None):
    return ts[11:16] if ts and len(ts) >= 16 else None


def latency_health(path: Path, sessions: int = 10) -> dict:
    """Per session: polling coverage, data staleness, scan time, and every signal's age."""
    rows = []
    try:
        with open(path) as f:
            for ln in f:
                try:
                    rows.append(json.loads(ln))
                except json.JSONDecodeError:
                    continue
    except OSError:
        return dict(available=False, days=[])
    by = {}
    for r in rows:
        at = r.get("at") if r.get("kind") == "tick" else r.get("posted_at")
        if at:
            by.setdefault(at[:10], {"ticks": [], "signals": []})["ticks" if r.get("kind") == "tick" else "signals"].append(r)
    days = []
    for d in sorted(by)[-sessions:]:
        ticks = sorted(by[d]["ticks"], key=lambda r: r["at"])
        inside = [r for r in ticks if SESSION[0] <= _hhmm(r["at"]) < SESSION[1]]
        # coverage: gaps of more than 10 minutes between ticks inside the session
        gaps, prev = [], f"{d} {SESSION[0]}"
        for r in inside + [{"at": f"{d} 15:55"}]:
            a, b = datetime.fromisoformat(prev[:16]), datetime.fromisoformat(r["at"][:16])
            if (b - a).total_seconds() > 600:
                gaps.append(dict(start=prev[11:16], end=r["at"][11:16], minutes=int((b - a).total_seconds() // 60)))
            prev = max(prev, r["at"])
        stale, cur = [], None
        for r in inside:
            if r.get("stale"):
                cur = cur or dict(start=_hhmm(r["at"]), newest_bar=_hhmm(r.get("newest_bar")), ticks=0)
                cur["ticks"] += 1
                cur["end"] = _hhmm(r["at"])
            elif cur:
                stale.append(cur)
                cur = None
        if cur:
            stale.append(cur)
        scans = sorted(x for x in (num(r.get("scan")) for r in inside) if x is not None)
        sigs = [dict(id=s.get("id"), entry_bar=s.get("entry_bar"), posted=_hhmm(s.get("posted_at")), detected_s=r4(num(s.get("detected_age_s"))),
                     posted_s=r4(num(s.get("posted_age_s"))), expired=bool(s.get("expired")),
                     delivered=s.get("delivered") if "delivered" in s else None) for s in by[d]["signals"]]
        days.append(dict(date=d, ticks=len(inside), first=_hhmm(inside[0]["at"]) if inside else None,
                         last=_hhmm(inside[-1]["at"]) if inside else None, gaps=gaps, stale=stale,
                         scan_med=scans[len(scans) // 2] if scans else None,
                         scan_p95=scans[int(len(scans) * 0.95)] if scans else None,
                         scan_max=scans[-1] if scans else None, signals=sigs,
                         last_tick=ticks[-1]["at"] if ticks else None))
    return dict(available=True, days=days, total_rows=len(rows))


def seen_records() -> list[dict]:
    """What each bot recorded as announced on its last session. A Discord message
    id means Discord accepted the post; the ids themselves are not copied."""
    out = []
    for name, f in (("Day-trade channel", "live_bot_seen.json"), ("In-play channel", "inplay_bot_seen.json")):
        s = read_json(STATE / f, {}) or {}
        entries, cards = s.get("entries") or [], s.get("cards") or {}
        out.append(dict(channel=name, date=s.get("date"), entries=len(entries),
                        with_message_id=sum(1 for e in entries if cards.get(e)),
                        exits=len(s.get("exits") or []), summary=bool(s.get("summary")),
                        strategy=s.get("strategy"), expired=len(s.get("expired") or [])))
    return out


def _const(module: str, name: str):
    """A module-level constant read from source, without importing (and so without
    pulling in the broker or the network)."""
    try:
        tree = ast.parse((REPO_ROOT / "src" / f"{module}.py").read_text())
    except (OSError, SyntaxError):
        return None
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == name for t in node.targets):
            try:
                return ast.literal_eval(node.value)
            except ValueError:
                return None
    return None


def config_checks(flows: list[dict]) -> list[dict]:
    raw = os.environ.get("DAYTRADE_STRATEGY")
    by_file = {w["file"]: w for w in flows}
    ls = by_file.get("live-signals.yml", {})
    out = [
        dict(item="Order placement (autotrade.ENABLED)", value=str(_const("autotrade", "ENABLED")),
             state="ok" if _const("autotrade", "ENABLED") is False else "warn",
             note="Signals only since 1 Oct 2026; a test pins it off."),
        dict(item="ORB paper record posts to Discord (orb_paper.POST)", value=str(_const("orb_paper", "POST")),
             state="ok" if _const("orb_paper", "POST") is False else "warn", note="Observation only."),
        dict(item="Day-trade rule switch (DAYTRADE_STRATEGY)",
             value=(raw.strip().lower() or "(empty)") if raw is not None else "not visible here",
             state="info" if raw is None else ("warn" if raw != raw.strip() else "ok"),
             note=("Raw value carries whitespace/CR; every reader strips it." if raw is not None and raw != raw.strip()
                   else "Read from the workflow's vars when built in Actions." if raw is None else "")),
        dict(item="live-signals.yml schedule", value="unscheduled" if not ls.get("crons") else "scheduled",
             state="info" if not ls.get("crons") else "warn",
             note="Disabled 26 Sep (old break-and-retest rule). Superseded by live-open.yml + live-bot.yml, "
                  "which are scheduled. Left off."),
    ]
    return out


def issues(health: dict, books: dict) -> list[dict]:
    """Confirmed problems, worst first, from the records above."""
    out = []
    days = health["latency"].get("days", [])
    recent = {d["date"] for d in days[-5:]}
    for d in days:
        lvl = "serious" if d["date"] in recent else "past"
        for s in d["stale"]:
            out.append(dict(level=lvl, area="Market data", date=d["date"], bot="daytrade",
                            text=f"{d['date']}: data stale {s['start']}-{s['end']} ET (newest bar stuck at "
                                 f"{s['newest_bar']}, {s['ticks']} polls). New signals were held."))
        for g in d["gaps"]:
            if g["minutes"] >= 30:
                out.append(dict(level=lvl, area="Coverage", date=d["date"], bot="daytrade",
                                text=f"{d['date']}: no live-bot scan logged {g['start']}-{g['end']} ET "
                                     f"({g['minutes']} min). A signal in that window could not post on time."))
    short = [(d["date"], g) for d in days if d["date"] in recent for g in d["gaps"] if g["minutes"] < 30]
    if short:
        worst = max(g["minutes"] for _, g in short)
        when = sorted({g["start"] for _, g in short})
        out.append(dict(level="warning", area="Coverage", date=max(d for d, _ in short), bot="daytrade",
                        text=f"Last 5 sessions: {len(short)} poll gap(s) of 10-29 min (worst {worst} min), starting at "
                             f"{', '.join(when)} ET. 10:04 is when the opening job hands over to the session job; "
                             f"stops and targets hit in a gap post late."))
    # Signal age: only posts made during the session; catch-up posts after the bell are expected to be old.
    sigs = [s for d in days if d["date"] in recent for s in d["signals"]
            if s["posted"] and SESSION[0] <= s["posted"] < SESSION[1]]
    fresh = [s for s in sigs if not s["expired"] and s["detected_s"] is not None]
    late = [s for s in fresh if s["detected_s"] > 30]
    if late:
        out.append(dict(level="warning", area="Latency", date=max(d["date"] for d in days), bot="daytrade",
                        text=f"Last 5 sessions: {len(late)} of {len(fresh)} on-time signals were first detected "
                             f"about {statistics.median(s['detected_s'] for s in late):.0f} s after their bar closed, "
                             f"i.e. one poll late (still inside the 120 s expiry). The others took "
                             f"{statistics.median([s['detected_s'] for s in fresh if s['detected_s'] <= 30] or [0]):.1f} s."))
    if sigs and all(s["delivered"] is None for s in sigs):
        out.append(dict(level="info", area="Delivery", date=None, bot="daytrade",
                        text="Discord delivery per signal was not logged before this dashboard; the live bot now "
                             "records it. Until then delivery is inferred from saved Discord message ids."))
    for a in health.get("actions") or []:
        if a["failures"]:
            out.append(dict(level="serious", area="Actions", date=a["failures"][0]["at"][:10],
                            bot=next((k for k, b in BOTS.items() if a["file"] in b["workflows"]), None),
                            text=f"{a['name']}: {len(a['failures'])} failed run(s) in the last 7 days, latest {a['failures'][0]['at']}."))
    tests = next((a for a in health.get("actions") or [] if a["file"] == "tests.yml"), None)
    if tests and tests["last_conclusion"] not in (None, "success"):
        out.append(dict(level="serious", area="Tests", date=None, bot=None, text=f"Last test run: {tests['last_conclusion']}."))
    replay = sum(1 for t in books["daytrade"] if t["source"] == "replay")
    if replay:
        out.append(dict(level="info", area="Records", date=None, bot="daytrade",
                        text=f"{replay} of {len(books['daytrade'])} day-trade ledger rows are replays, not posts. "
                             f"They are left out of the bot views: the month replay covers the same sessions."))
    out.append(dict(level="info", area="Records", date=None, bot="inplay",
                    text="The in-play channel writes no latency log, so its signal ages are not tracked."))
    rank = {"serious": 0, "warning": 1, "info": 2, "past": 3}
    return sorted(out, key=lambda x: (rank[x["level"]], -int((x.get("date") or "0").replace("-", "") or 0)))


# --------------------------------------------------------------------------- integrity
def integrity(books: dict, month_trades: list[dict]) -> list[dict]:
    checks = []
    for key, ts in books.items():
        ids = [t["id"] for t in ts]
        dup = len(ids) - len(set(ids))
        closed = [t for t in ts if t["status"] == "closed"]
        m = metrics(t["ret"] for t in closed)
        checks.append(dict(book=key, check="unique trade ids", ok=dup == 0, detail=f"{dup} duplicate id(s)"))
        checks.append(dict(book=key, check="trades = wins + losses + flat",
                           ok=m["n"] == m["wins"] + m["losses"] + m["flat"] == len(closed),
                           detail=f"{m['n']} = {m['wins']} + {m['losses']} + {m['flat']}"))
        other = len(ts) - len(closed)
        checks.append(dict(book=key, check="open / unresolved rows kept out of closed stats", ok=True,
                           detail=f"{other} row(s) excluded"))
    # Live posts against the replay of the same rule on the same days.
    live = {(t["date"], t["symbol"]): t for t in books["daytrade"] if t["source"] == "live"}
    bt = {(t["date"], t["symbol"]): t for t in month_trades}
    overlap = sorted(set(live) & set(bt))
    days = {d for d, _ in live} & {t["date"] for t in month_trades}
    only_live = [k for k in live if k[0] in days and k not in bt]
    only_bt = [k for k in bt if k[0] in days and k not in live]
    diff = [k for k in overlap if live[k]["ret"] is not None and bt[k]["ret"] is not None
            and abs(live[k]["ret"] - bt[k]["ret"]) > 0.05]
    checks.append(dict(book="daytrade", check="live posts match the month replay",
                       ok=not (only_live or only_bt or diff),
                       detail=f"{len(days)} shared session(s): {len(overlap)} trades in both, "
                              f"{len(only_live)} only live, {len(only_bt)} only in replay, "
                              f"{len(diff)} with results >0.05 apart"))
    return checks


# --------------------------------------------------------------------------- bot status
def bot_status(trades: list[dict], health: dict, sw_meta: dict) -> dict:
    """Per bot: its workflows' last runs, how fresh its records are, and its warnings.
    A bot is never called healthy just because its workflow exists: with no run
    history the status is 'unknown'."""
    acts = {a["file"]: a for a in health.get("actions") or []}
    seen = {s["channel"]: s for s in health.get("seen") or []}
    lat = (health.get("latency") or {}).get("days") or []
    out = {}
    for key, b in BOTS.items():
        runs = [acts[w] for w in b["workflows"] if w in acts]
        last_ok = max((a["last_success"] for a in runs if a["last_success"]), default=None)
        fails = sorted((f for a in runs for f in a["failures"]), key=lambda f: f["at"], reverse=True)
        mine = [t for t in trades if t["bot"] == key]
        latest = max((t["date"] for t in mine), default=None)
        if key == "daytrade":
            fresh = dict(label="Last live-bot scan", value=lat[-1]["last_tick"][:16] if lat and lat[-1]["last_tick"] else None)
            rec = seen.get("Day-trade channel")
        elif key == "inplay":
            fresh = dict(label="Last announce record", value=(seen.get("In-play channel") or {}).get("date"))
            rec = seen.get("In-play channel")
        else:
            fresh = dict(label="Paper record generated", value=sw_meta.get("generated"))
            rec = None
        state = "unknown" if not runs else "failing" if fails else "ok" if last_ok else "unknown"
        warn = [i for i in health.get("issues", []) if i.get("bot") == key and i["level"] in ("serious", "warning")]
        if state == "ok" and any(i["level"] == "serious" for i in warn):
            state = "attention"
        out[key] = {k: b[k] for k in ("name", "strategy", "detail", "hold", "modes", "workflows")}
        out[key].update(state=state, last_success=last_ok, failures=fails[:5], latest_trade=latest,
                        freshness=fresh, announce=rec, warnings=warn,
                        open=sum(1 for t in mine if t["status"] == "open"))
    return out


# --------------------------------------------------------------------------- build
def build(with_actions: bool = True) -> dict:
    now = datetime.now(timezone.utc)
    sw_trades, sw_open, sw_meta = swing_paper()
    mo_trades, mo = month_replay()
    books = dict(daytrade=ledger_trades("daytrade"), inplay=ledger_trades("inplay"),
                 orb_paper=orb_paper_trades(), swing_paper=sw_trades, month_replay=mo_trades)
    for ts in books.values():
        ts.sort(key=lambda t: (t["date"], t["exit_time"] or "", t["entry_time"] or "", t["symbol"] or ""))
    summary = {}
    for k, ts in books.items():
        closed = [t for t in ts if t["status"] == "closed"]
        m = metrics(t["ret"] for t in closed)
        live = metrics(t["ret"] for t in closed if t["source"] == "live") if k in ("daytrade", "inplay", "orb_paper") else None
        real = metrics(t["ret_real"] for t in closed if t["ret_real"] is not None) if k == "orb_paper" else None
        dates = sorted({t["date"] for t in closed})
        summary[k] = dict(all=m, live=live, real_costs=real, verdict=verdict(m, BOOKS[k]["unit_label"]),
                          live_verdict=verdict(live, BOOKS[k]["unit_label"]) if live else None,
                          first=dates[0] if dates else None, last=dates[-1] if dates else None,
                          sessions=len(dates), open=sum(1 for t in ts if t["status"] == "open"))
    # Swing: our recomputation must agree with what src/paper.py reported.
    rep = sw_meta["reported"]
    sm = summary["swing_paper"]["all"]
    swing_check = dict(book="swing_paper", check="matches src/paper.py's own totals",
                       ok=(rep.get("n") == sm["n"] and rep.get("wins") == sm["wins"]
                           and (rep.get("return_pct") is None or sm["total"] is None
                                or abs(rep["return_pct"] - sm["total"]) < 0.05)),
                       detail=f"paper.py: {rep.get('n')} trades, {rep.get('wins')} won, {rep.get('return_pct')}% · "
                              f"here: {sm['n']} trades, {sm['wins']} won, {sm['total']}%")
    flows = workflows()
    runs, how = fetch_runs() if with_actions else (None, "skipped (--no-actions)")
    health = dict(latency=latency_health(STATE / "latency.jsonl"), seen=seen_records(),
                  actions=actions_summary(runs, flows, now) if runs is not None else None,
                  actions_source=how, config=config_checks(flows))
    health["issues"] = issues(health, books)
    trades = [t for ts in books.values() for t in ts]
    for t in trades:
        t["bot"], t["mode"] = bot_mode(t)
        t["hold_min"] = hold_minutes(t) if t["book"] != "swing_paper" else None
        t["hold_days"] = num((t.get("f") or {}).get("bars_held")) if t["book"] == "swing_paper" else None
    bots = bot_status(trades, health, sw_meta)
    data = dict(
        schema=SCHEMA, generated=now.astimezone(ET).strftime("%Y-%m-%d %H:%M ET"),
        generated_utc=now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        as_of=as_of_session(now.astimezone(ET)), bots=bots, modes=MODES,
        excluded=dict(daytrade_replay=sum(1 for t in books["daytrade"] if t["source"] == "replay")),
        thresholds=dict(small_n=SMALL_N, tiny_n=TINY_N),
        books=BOOKS, summary=summary, trades=trades, open=sw_open,
        swing_meta=sw_meta, setups=setups(mo),
        month_meta=dict(strategy=mo.get("strategy"), rules=mo.get("rules"), sizing=mo.get("sizing"),
                        start=mo.get("from"), end=mo.get("to")),
        lab=lab(books), health=health,
        integrity=integrity(books, mo_trades) + [swing_check])
    return data


def render_md(d: dict) -> str:
    L = ["# Dashboard summary", "", f"Built {d['generated']} from the repo's own records. "
         "Open `reports/dashboard.html` in a browser for the interactive version.", "",
         "Win %, profit % and winners against losers. Each book is in its own unit and never summed with another.", "",
         "| book | unit | trades | won / lost | win % | net | avg per trade | worst drop | verdict |",
         "|---|---|---|---|---|---|---|---|---|"]
    f = lambda v, s="": "N/A" if v is None else f"{v:+.2f}{s}"
    for k, b in d["books"].items():
        m, v = d["summary"][k]["all"], d["summary"][k]["verdict"]
        wr = "N/A" if m["win_rate"] is None else f"{m['win_rate']:.0f}%"
        dd = "N/A" if m["max_dd"] is None else f"-{m['max_dd']:.2f}"
        L.append(f"| {b['title']} | {b['unit_label']} | {m['n']} | {m['wins']} / {m['losses']} | {wr} | "
                 f"{f(m['total'])} | {f(m['avg'])} | {dd} | {v['text']} |")
    L += ["", "## Issues", ""]
    L += [f"- **{i['level']}** · {i['area']}: {i['text']}" for i in d["health"]["issues"]] or ["- none found"]
    L += ["", "## Integrity checks", ""]
    L += [f"- {'OK' if c['ok'] else 'FAIL'} · {c['book']} · {c['check']}: {c['detail']}" for c in d["integrity"]]
    return "\n".join(L) + "\n"


def render_html(d: dict, template: Path = TEMPLATE, standalone: bool = True) -> str:
    """The page with the data inlined, so it opens from disk with no server.
    `standalone=False` leaves out the document skeleton (for hosts that add their own)."""
    payload = json.dumps(d, separators=(",", ":"), default=str).replace("</", "<\\/")
    page = template.read_text().replace("/*__DASHBOARD_DATA__*/null", payload, 1)
    return f'<!doctype html>\n<html lang="en"><head><meta charset="utf-8"></head><body>\n{page}\n</body></html>\n' \
        if standalone else page


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-actions", action="store_true", help="skip the GitHub Actions run history")
    args = ap.parse_args(argv)
    d = build(with_actions=not args.no_actions)
    REPORTS.mkdir(exist_ok=True)
    OUT_JSON.write_text(json.dumps(d, indent=1, default=str))
    OUT_MD.write_text(render_md(d))
    OUT_HTML.write_text(render_html(d))
    bad = [c for c in d["integrity"] if not c["ok"]]
    print(f"dashboard: {len(d['trades'])} trade records, {len(d['health']['issues'])} issue(s), "
          f"{len(bad)} integrity failure(s); actions: {d['health']['actions_source']}")
    for c in bad:
        print(f"  FAIL {c['book']}: {c['check']} - {c['detail']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
