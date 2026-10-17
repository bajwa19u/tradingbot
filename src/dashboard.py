"""The trading dashboard: one record per bot, built only from records the bots
and their audits already keep, plus the self-contained page that shows it.

Nothing here computes a signal or re-runs a strategy. For each bot it joins two
things that were already written down:

  real       what the bot posted, from the first day it posted
  backtest   the same rule replayed on the days before that

so every period (week, month, year, all) reads as one record. The page marks
where the backtest ends and never offers a way to pick one or the other.

  Day-trade bot   state/ledger_daytrade.csv rows marked 'live' (this repo)
                  backtest: reports/orb_audit_trades.csv (the audit's two-year run of
                  the live big tech rule), else reports/orb_month.json (last month)
  Swing bot       bajwa19u/vwap-ema-swing state/ledger.csv (public repo, read over HTTPS)
                  backtest: that repo's reports/audit_trades.csv, else reports/trades.csv

Rules this file keeps:
  - One calculation per metric: `metrics()`. The page carries a line-for-line
    port; tests/test_dashboard.py runs both on the same records.
  - Bots are never summed together. The day-trade bot reports % of the account
    with 1% risked per trade; the swing bot reports the stock's % move.
  - No day is counted twice: backtest trades stop the day before the first real one.
  - Anything not recorded is None (the page shows a dash), never 0.
  - Verdicts check the all-negative case first.
  - No secrets: run history keeps only workflow names, times and conclusions.

Usage: python -m src.dashboard [--no-actions]
"""
from __future__ import annotations

import argparse
import base64
import csv
import io
import json
import math
import os
import statistics
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from .config import REPO_ROOT

ET = ZoneInfo("America/New_York")
STATE = REPO_ROOT / "state"
REPORTS = REPO_ROOT / "reports"
TEMPLATE = REPO_ROOT / "tools" / "dashboard_template.html"
OUT_JSON = REPORTS / "dashboard.json"
OUT_HTML = REPORTS / "dashboard.html"
OUT_MD = REPORTS / "dashboard.md"
SCHEMA = 2
SMALL_N = 30          # fewer closed trades than this is called too few to judge

BOTS = {
    "daytrade": dict(
        name="Day-trade bot", repo="bajwa19u/tradingbot",
        strategy="Opening-range breakout on TSLA, AMD, NVDA, META, AAPL and MSFT",
        detail="First 1-minute close outside the 09:30-09:34 range before 09:45, range at least 0.35 of "
               "daily ATR. Stop at the session extreme, moved to entry at +1x risk; target 2x risk; out by 15:55. "
               "Posts to the Discord day-trade channel.",
        unit="% of account", unit_long="% of the account per trade, 1% risked, 0.05% slippage a side",
        hold="intraday", workflows=["live-open.yml", "live-bot.yml", "day-end.yml"]),
    "swing": dict(
        name="Swing bot", repo="bajwa19u/vwap-ema-swing",
        strategy="EMA21 crossing the weekly VWAP on hourly bars, long only, held for days",
        detail="Buys when the hourly EMA21 crosses above the weekly VWAP with SPY in an uptrend; exits on the "
               "cross back or the stop. Posts to the Discord VWAP channel.",
        unit="% stock move", unit_long="% move of the stock from entry to exit",
        hold="days", workflows=["scan.yml"]),
}

# Where each record comes from: (repo, ref, path), tried in order. A file in this
# repo is read from disk first; the network is only used when it is missing.
SOURCES = {
    ("daytrade", "backtest"): [("bajwa19u/tradingbot", "main", "reports/orb_audit_trades.csv"),
                               ("bajwa19u/tradingbot", "profitability-audit", "reports/orb_audit_trades.csv")],
    ("swing", "real"): [("bajwa19u/vwap-ema-swing", "main", "state/ledger.csv")],
    ("swing", "backtest"): [("bajwa19u/vwap-ema-swing", "main", "reports/audit_trades.csv"),
                            ("bajwa19u/vwap-ema-swing", "profitability-audit", "reports/audit_trades.csv"),
                            ("bajwa19u/vwap-ema-swing", "main", "reports/trades.csv")],
}


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


def as_of_session(now_et: datetime) -> str:
    """The latest weekday whose session has closed by `now_et`: what 'Today' means on the page."""
    d = now_et.date() if now_et.hour >= 16 else now_et.date() - timedelta(days=1)
    while d.weekday() > 4:
        d -= timedelta(days=1)
    return d.isoformat()


# --------------------------------------------------------------------------- the one metric
def metrics(rets) -> dict:
    """Closed-trade statistics for one list of per-trade results, in order.

    wins are > 0, losses < 0, flat == 0, and n == wins + losses + flat always.
    The equity line is the running sum (results are a fixed share of the
    account or of the stock, not compounded). Drawdowns are positive numbers,
    in the same unit as the results. Profit factor is None with no losing trade.
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


def verdict(m: dict, unit: str) -> dict:
    """Is it profitable after costs? The all-negative case is checked first."""
    n, tot = m["n"], m["total"]
    if not n:
        return dict(state="none", text="No closed trades yet.")
    if tot is not None and tot <= 0:
        return dict(state="neg", text=f"No. Net {tot:+.2f} ({unit}) over {n} closed trades, "
                                      f"{m['wins']} won, {m['losses']} lost.")
    if n < SMALL_N:
        return dict(state="few", text=f"Net {tot:+.2f} over {n} trades: too few to judge "
                                      f"(under {SMALL_N}). Read it as a record, not a result.")
    if m["ci_low"] is not None and m["ci_low"] > 0:
        return dict(state="pos", text=f"Net {tot:+.2f} over {n} trades and the 95% interval of the "
                                      f"average trade stays above zero.")
    return dict(state="noise", text=f"Net {tot:+.2f} over {n} trades, but the 95% interval of the "
                                    f"average trade includes zero: not distinguishable from noise.")


# --------------------------------------------------------------------------- fetching
def fetch_text(repo: str, ref: str, path: str) -> str | None:
    """A file from a public GitHub repo, or None. Raw HTTPS first, then the gh CLI."""
    try:
        import requests
        r = requests.get(f"https://raw.githubusercontent.com/{repo}/{ref}/{path}", timeout=30)
        if r.status_code == 200:
            return r.text
        if r.status_code == 404:
            return None
    except Exception:                                                 # noqa: BLE001
        pass
    try:
        res = subprocess.run(["gh", "api", f"repos/{repo}/contents/{path}?ref={ref}", "--jq", ".content"],
                             capture_output=True, text=True, timeout=60)
        if res.returncode == 0 and res.stdout.strip():
            return base64.b64decode(res.stdout).decode()
    except Exception:                                                 # noqa: BLE001
        pass
    return None


def load_rows(key: tuple[str, str]) -> tuple[list[dict], str | None]:
    """CSV rows for one source and where they came from, or ([], None)."""
    for repo, ref, path in SOURCES[key]:
        if repo == BOTS["daytrade"]["repo"] and (REPO_ROOT / path).exists():
            return read_csv(REPO_ROOT / path), path
        body = fetch_text(repo, ref, path)
        if body is not None:
            return list(csv.DictReader(io.StringIO(body))), f"{repo}@{ref}:{path}"
    return [], None


# --------------------------------------------------------------------------- records
def trade(bot, kind, date, sym, side, ret, why=None, entry_date=None, et=None, xt=None) -> dict:
    return dict(bot=bot, kind=kind, date=date, entry_date=entry_date or date, sym=sym, side=side,
                ret=r4(ret), why=why, et=et, xt=xt)


def _side(v) -> str | None:
    s = (text(v) or "").lower()
    return {"1": "long", "1.0": "long", "-1": "short", "-1.0": "short"}.get(s, s if s in ("long", "short") else None)


def daytrade_real() -> list[dict]:
    """What the day-trade channel posted. Ledger rows marked 'replay' were re-run after
    the fact and 'corrected' is 5 Oct under the old in-play rule; neither was posted
    by the big tech rule, so the backtest stands in for those days."""
    out = []
    for row in read_csv(STATE / "ledger_daytrade.csv"):
        date, ret = text(row.get("date")), num(row.get("pct"))
        if not date or text(row.get("source")) != "live" or ret is None:
            continue
        out.append(trade("daytrade", "real", date, text(row.get("symbol")), _side(row.get("side")), ret,
                         text(row.get("reason")), et=text(row.get("entry_time")), xt=text(row.get("exit_time"))))
    return out


def daytrade_backtest() -> tuple[list[dict], str | None]:
    rows, src = load_rows(("daytrade", "backtest"))
    out = [trade("daytrade", "backtest", text(r.get("date")), text(r.get("sym")), _side(r.get("side")),
                 num(r.get("pct")), text(r.get("why")))
           for r in rows if text(r.get("date")) and num(r.get("pct")) is not None]
    if out:
        return out, src
    d = read_json(REPORTS / "orb_month.json", {}) or {}
    for t in (d.get("trades") or []) if isinstance(d, dict) else []:
        if text(t.get("date")) and num(t.get("result_pct")) is not None:
            out.append(trade("daytrade", "backtest", text(t["date"]), text(t.get("symbol")), _side(t.get("side")),
                             num(t["result_pct"]), text(t.get("exit_reason")),
                             et=text(t.get("entry_time")), xt=text(t.get("exit_time"))))
    return out, "reports/orb_month.json" if out else None


def _swing(rows: list[dict], kind: str) -> list[dict]:
    """Swing records store the stock move as a fraction; the page shows percent."""
    out = []
    for r in rows:
        exit_t, ret = text(r.get("exit_time")), num(r.get("ret"))
        if not exit_t or ret is None:
            continue
        out.append(trade("swing", kind, exit_t[:10], text(r.get("ticker")), _side(r.get("side")) or "long",
                         100 * ret, text(r.get("reason")), entry_date=(text(r.get("entry_time")) or exit_t)[:10],
                         et=(text(r.get("entry_time")) or "")[11:16] or None, xt=exit_t[11:16] or None))
    return out


def merge(real: list[dict], backtest: list[dict], start: str | None) -> list[dict]:
    """One record: backtest trades that entered before the bot's first real trade, then
    the real trades. With no real trade yet, the whole record is backtest."""
    bt = [t for t in backtest if start is None or t["entry_date"] < start]
    out = bt + real
    return sorted(out, key=lambda t: (t["date"], t["xt"] or "", t["entry_date"], t["sym"] or ""))


def records(previous: dict | None = None) -> tuple[list[dict], dict]:
    """Every trade of both bots and, per bot, where the real record starts and the sources.
    A source that cannot be read now keeps the trades the previous build had for it."""
    prev = [t for t in (previous or {}).get("trades") or [] if isinstance(t, dict)]
    keep = lambda bot, kind: [t for t in prev if t.get("bot") == bot and t.get("kind") == kind]
    meta, trades = {}, []

    dt_real = daytrade_real()
    dt_bt, dt_src = daytrade_backtest()
    sw_rows, sw_src = load_rows(("swing", "real"))
    sw_real = _swing(sw_rows, "real")
    swb_rows, swb_src = load_rows(("swing", "backtest"))
    sw_bt = _swing(swb_rows, "backtest")
    for bot, real, real_src, bt, bt_src in (
            ("daytrade", dt_real, "state/ledger_daytrade.csv", dt_bt, dt_src),
            ("swing", sw_real, sw_src, sw_bt, swb_src)):
        cached = []
        if real_src is None and keep(bot, "real"):
            real, real_src = keep(bot, "real"), "previous build (source unreachable)"
            cached.append("real")
        if bt_src is None and keep(bot, "backtest"):
            bt, bt_src = keep(bot, "backtest"), "previous build (source unreachable)"
            cached.append("backtest")
        start = min((t["entry_date"] for t in real), default=None)
        merged = merge(real, bt, start)
        trades += merged
        meta[bot] = dict(live_start=start, real_source=real_src, backtest_source=bt_src, cached=cached,
                         first=merged[0]["date"] if merged else None, last=merged[-1]["date"] if merged else None)
    return trades, meta


# --------------------------------------------------------------------------- run history
def fetch_runs(repo: str, days: int = 7) -> list[dict] | None:
    """Recent Actions runs of one repo: file, event, time and conclusion only."""
    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    path = f"repos/{repo}/actions/runs?per_page=100&created=>={since}"
    token = os.environ.get("GITHUB_TOKEN")
    try:
        if token:
            import requests
            r = requests.get(f"https://api.github.com/{path}", timeout=30,
                             headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"})
            r.raise_for_status()
            raw = r.json().get("workflow_runs", [])
        else:
            res = subprocess.run(["gh", "api", path, "--jq", ".workflow_runs[]"],
                                 capture_output=True, text=True, timeout=120)
            if res.returncode != 0:
                return None
            raw = [json.loads(x) for x in res.stdout.splitlines() if x.strip()]
    except Exception:                                                 # noqa: BLE001
        return None
    return [dict(file=Path(r.get("path") or "").name, status=r.get("status"), conclusion=r.get("conclusion"),
                 at=r.get("created_at")) for r in raw]


def bot_status(bot: str, runs: list[dict] | None) -> dict:
    """'ok', 'failing' or 'unknown'. Never 'ok' without run history to say so."""
    if runs is None:
        return dict(state="unknown", last_run=None, failures=0)
    mine = sorted((r for r in runs if r["file"] in BOTS[bot]["workflows"]), key=lambda r: r["at"] or "", reverse=True)
    done = [r for r in mine if r["status"] == "completed"]
    fails = [r for r in done if r["conclusion"] in ("failure", "timed_out", "startup_failure")]
    ok = next((r for r in done if r["conclusion"] == "success"), None)
    state = "failing" if done and done[0] in fails else "ok" if ok else "unknown"
    return dict(state=state, last_run=ok["at"] if ok else None, failures=len(fails))


# --------------------------------------------------------------------------- build
def build(with_actions: bool = True, previous: dict | None = None) -> dict:
    now = datetime.now(timezone.utc)
    trades, meta = records(previous)
    bots = {}
    for k, b in BOTS.items():
        mine = [t for t in trades if t["bot"] == k]
        m = metrics(t["ret"] for t in mine)
        real = metrics(t["ret"] for t in mine if t["kind"] == "real")
        runs = fetch_runs(b["repo"]) if with_actions else None
        bots[k] = {**{f: b[f] for f in ("name", "strategy", "detail", "unit", "unit_long", "hold", "repo")},
                   **meta[k], "all": m, "real": real, "verdict": verdict(m, b["unit"]),
                   "real_verdict": verdict(real, b["unit"]), "status": bot_status(k, runs)}
    return dict(schema=SCHEMA, generated=now.astimezone(ET).strftime("%Y-%m-%d %H:%M ET"),
                generated_utc=now.strftime("%Y-%m-%dT%H:%M:%SZ"), as_of=as_of_session(now.astimezone(ET)),
                actions="read" if with_actions else "skipped (--no-actions)",
                bots=bots, trades=trades, checks=checks(trades, bots))


def checks(trades: list[dict], bots: dict) -> list[dict]:
    """What has gone wrong in this project's records before, checked on every build."""
    out = []
    for k, b in bots.items():
        mine = [t for t in trades if t["bot"] == k]
        m = b["all"]
        out.append(dict(bot=k, check="trades = wins + losses + flat",
                        ok=m["n"] == m["wins"] + m["losses"] + m["flat"] == len(mine),
                        detail=f"{m['n']} = {m['wins']} + {m['losses']} + {m['flat']}"))
        start = b["live_start"]
        late_bt = [t for t in mine if t["kind"] == "backtest" and start and t["entry_date"] >= start]
        out.append(dict(bot=k, check="no backtest trade on or after the first real trade", ok=not late_bt,
                        detail=f"real from {start}" if start else "no real trades yet: all backtest"))
        keys = [(t["date"], t["entry_date"], t["sym"], t["side"], t["kind"]) for t in mine]
        dup = len(keys) - len(set(keys))
        out.append(dict(bot=k, check="no trade listed twice", ok=dup == 0, detail=f"{dup} duplicate(s)"))
    return out


def render_md(d: dict) -> str:
    L = ["# Dashboard summary", "", f"Built {d['generated']} from the bots' own records. "
         "Open `reports/dashboard.html` in a browser for the interactive version.", "",
         "Each bot is one record: backtest before its first real trade, real trades from then on. "
         "The two bots are in different units and are never added together.", "",
         "| bot | unit | record | trades | won / lost | win % | profit | verdict |",
         "|---|---|---|---|---|---|---|---|"]
    f = lambda v: "N/A" if v is None else f"{v:+.2f}%"
    for k, b in d["bots"].items():
        for label, m, v in ((f"all, {b['first']} to {b['last']}", b["all"], b["verdict"]),
                            (f"real only, from {b['live_start'] or 'none yet'}", b["real"], b["real_verdict"])):
            wr = "N/A" if m["win_rate"] is None else f"{m['win_rate']:.0f}%"
            L.append(f"| {b['name']} | {b['unit']} | {label} | {m['n']} | {m['wins']} / {m['losses']} | {wr} | "
                     f"{f(m['total'])} | {v['text']} |")
    L += ["", "## Sources", ""]
    for b in d["bots"].values():
        L.append(f"- {b['name']}: real from `{b['real_source']}`, backtest from `{b['backtest_source']}`"
                 + (f" (kept from the previous build: {', '.join(b['cached'])})" if b["cached"] else ""))
    L += ["", "## Checks", ""]
    L += [f"- {'OK' if c['ok'] else 'FAIL'} · {c['bot']} · {c['check']}: {c['detail']}" for c in d["checks"]]
    return "\n".join(L) + "\n"


def render_html(d: dict, template: Path = TEMPLATE, standalone: bool = True) -> str:
    """The page with the data inlined, so it opens from disk with no server.
    `standalone=False` leaves out the document skeleton (for hosts that add their own)."""
    payload = json.dumps(d, separators=(",", ":"), default=str).replace("</", "<\\/")
    page = template.read_text().replace("/*__DASHBOARD_DATA__*/null", payload, 1)
    return ('<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">'
            f'</head><body>\n{page}\n</body></html>\n') if standalone else page


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-actions", action="store_true", help="skip the GitHub Actions run history")
    ap.add_argument("--artifact", type=Path, help="also write the page without a document skeleton here")
    args = ap.parse_args(argv)
    d = build(with_actions=not args.no_actions, previous=read_json(OUT_JSON))
    REPORTS.mkdir(exist_ok=True)
    OUT_JSON.write_text(json.dumps(d, indent=1, default=str))
    OUT_MD.write_text(render_md(d))
    OUT_HTML.write_text(render_html(d))
    if args.artifact:
        args.artifact.write_text(render_html(d, standalone=False))
    bad = [c for c in d["checks"] if not c["ok"]]
    for k, b in d["bots"].items():
        print(f"dashboard: {b['name']}: {b['all']['n']} trades ({b['real']['n']} real from {b['live_start']}); "
              f"backtest from {b['backtest_source']}")
    print(f"dashboard: {len(bad)} failed check(s); actions: {d['actions']}")
    for c in bad:
        print(f"  FAIL {c['bot']}: {c['check']} - {c['detail']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
