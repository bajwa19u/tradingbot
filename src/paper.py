"""Paper account — the forward test.

Everything in this repo before this file was a backtest, and the single
clearest finding of the project is that backtests here have been wrong. The
adaptive loop searched configurations 33 times: fit expectancy averaged +0.4R,
forward expectancy about -1.0R. A forward test is the only measurement that has
not lied.

So this file does one thing: it runs the chosen rule on today's real bars, day
after day, and keeps score. No search, no parameters to pick, nothing to tune.

The design choice that matters: the ledger is DERIVED, not stored. Every run
replays the whole period from `paper.start` through the same `run_portfolio`
the backtest uses, and writes the result out. Nothing accumulates in a state
file that could drift, corrupt, or silently disagree with the backtest. If the
engine changes, the paper record changes with it and stays honest. The cost is
a full refetch each run, which takes seconds.

    python -m src.paper              # score it, write reports/paper.md
    python -m src.paper --dry-run    # print, write nothing
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime

import pandas as pd

from .breakout import (BASE_BO, median_atr_pct, prepare, signal_times_bo)
from .config import REPO_ROOT, Credentials, load_config
from .data import AlpacaError, MarketData
from .forensics import MOVERS
from .swing import run_portfolio

REPORTS = REPO_ROOT / "reports"
STATE = REPO_ROOT / "state"
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s",
                    stream=sys.stdout)
log = logging.getLogger("paper")

# The rule being forward tested. Fixed deliberately: this is the config that
# returned +14.6% where it was tuned and +14.5% on stocks it had never seen,
# with the volatility screen applied to both sides. Changing anything here
# restarts the forward test, so it is not a knob.
RULE = dict(BASE_BO)
RULE.update({"base_len": 10, "squeeze_atr": 4.0, "vol_mult": 1.0,
             "min_atr_pct": 0.0, "touch_window": 10})

SCREEN_ATR_PCT = 3.0      # universe screen: skip names quieter than this
DEFAULT_HALT_PCT = 25.0   # stop trading at this drawdown until reviewed


def settings() -> dict:
    """Paper-account settings from config.yaml, with defaults."""
    try:
        paper = dict(load_config().get("paper") or {})
    except Exception as exc:                      # config is optional here
        log.warning("Could not read config.yaml (%s); using defaults", exc)
        paper = {}
    return {"start": str(paper.get("start", "2026-09-29")),
            "equity": float(paper.get("equity", 2000.0)),
            "risk_pct": float(paper.get("risk_pct", 1.0)),
            "halt_drawdown_pct": float(paper.get("halt_drawdown_pct",
                                                 DEFAULT_HALT_PCT))}


def screened(data: dict, before: pd.Timestamp) -> dict:
    """Keep only names volatile enough, judged on history before the window."""
    keep = {s: d for s, d in data.items()
            if median_atr_pct(d, before) >= SCREEN_ATR_PCT}
    log.info("Screen >= %.1f%%: kept %d of %d", SCREEN_ATR_PCT,
             len(keep), len(data))
    return keep


def shares(entry: float, risk_per_share: float, equity: float,
           risk_pct: float) -> int:
    """Whole shares at the configured risk. Returns 0 when one share would
    already risk more than the budget - a real constraint on a small account,
    and one the backtest's fractional sizing hides."""
    if risk_per_share <= 0:
        return 0
    return int((equity * risk_pct / 100.0) // risk_per_share)


def score(argv=None) -> dict:
    cfg = settings()
    start = pd.Timestamp(cfg["start"], tz="America/New_York")
    fetch_from = (start - pd.Timedelta(days=500)).date().isoformat()

    md = MarketData(Credentials.from_env(), feed="iex")
    data = md.daily_bars(MOVERS, start=fetch_from)
    data = {s: d for s, d in data.items() if len(d) > 260}
    if not data:
        raise AlpacaError("no data returned")
    data = screened(data, start)

    p = dict(RULE)
    p["risk_pct"] = cfg["risk_pct"]
    prepared = prepare(data, p)
    result = run_portfolio(prepared, p, equity=cfg["equity"],
                           sigs=signal_times_bo(prepared, p), lo=start)

    st = result["stats"]
    closed = result["trades"]
    wins = sum(1 for t in closed if t["r_multiple"] > 0)
    last_bar = max((d.index[-1] for d in prepared.values()), default=None)

    for o in result["open"]:
        o["shares"] = shares(o["entry"], o["risk_per_share"], cfg["equity"],
                             cfg["risk_pct"])

    dd = st.get("max_drawdown_pct", 0.0)
    return {"generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "as_of": str(last_bar.date()) if last_bar is not None else "—",
            "settings": cfg, "symbols": len(data),
            "trades": closed, "open": result["open"],
            "n": len(closed), "wins": wins, "losses": len(closed) - wins,
            "win_rate_pct": st.get("win_rate_pct", 0.0),
            "return_pct": st.get("return_pct", 0.0),
            "max_dd_pct": dd,
            "halted": dd <= -cfg["halt_drawdown_pct"]}


def render(r: dict) -> str:
    c = r["settings"]
    out = ["# Paper account", "",
           f"**Forward test since {c['start']} · bars through {r['as_of']} · "
           f"{r['symbols']} symbols · generated {r['generated']}**", "",
           "Not a backtest. These are the trades the rule would have taken "
           "since the day it was chosen, on bars it had never seen when the "
           "choice was made.", ""]

    if r["n"] == 0 and not r["open"]:
        out += ["**No trades yet.** Empty stretches are normal for this setup "
                "- it waits for a coil to break on volume, which does not "
                "happen every day. Nothing is wrong."]
        return "\n".join(out)

    out += ["| Trades | Won | Lost | Win % | Profit |",
            "|---|---|---|---|---|",
            f"| {r['n']} | {r['wins']} | {r['losses']} | "
            f"{r['win_rate_pct']}% | **{r['return_pct']:+.1f}%** |", ""]

    if r["n"] < 20:
        out += [f"> {r['n']} closed trades is too few to judge. The backtest "
                "needed 50 or more before its numbers stopped moving around. "
                "Read this as a record, not a verdict, until then.", ""]

    if r["halted"]:
        out += ["## STOPPED", "",
                f"Drawdown reached **{r['max_dd_pct']}%**, past the "
                f"{c['halt_drawdown_pct']}% line. No new entries are listed "
                "below. This is the agreed stop, not a suggestion — raising "
                "the line to keep trading is the one move that turns a bad "
                "month into a ruined account.", ""]
    else:
        room = c["halt_drawdown_pct"] + r["max_dd_pct"]
        out += [f"Worst drop so far **{r['max_dd_pct']}%**, against the "
                f"{c['halt_drawdown_pct']}% stop line — {room:.1f}% of room "
                "left.", ""]

    if r["open"] and not r["halted"]:
        out += ["## Open now", "",
                f"Sized at {c['risk_pct']:.0f}% of ${c['equity']:,.0f} risked "
                "per trade.", "",
                "| Symbol | Entered | Entry | Stop | Target | Shares | Best so far |",
                "|---|---|---|---|---|---|---|"]
        for o in r["open"]:
            sz = o["shares"] if o["shares"] else "— too small"
            trail = " (trailing)" if o["trailing"] else ""
            out.append(f"| **{o['symbol']}** | {o['entry_date']} | "
                       f"${o['entry']:.2f} | ${o['stop']:.2f}{trail} | "
                       f"${o['target']:.2f} | {sz} | {o['best_R']}R |")
        out.append("")
        if any(not o["shares"] for o in r["open"]):
            out += ["> A row marked *too small* means one share would risk "
                    f"more than {c['risk_pct']:.0f}% of the account. Skip it "
                    "rather than sizing up.", ""]

    if r["trades"]:
        out += ["## Closed", "",
                "| Symbol | In | Out | Result | Why it ended |",
                "|---|---|---|---|---|"]
        for t in reversed(r["trades"][-25:]):
            mark = "won" if t["r_multiple"] > 0 else "lost"
            out.append(f"| {t['symbol']} | {t['entry_date']} | "
                       f"{t['exit_date']} | {mark} | {t['reason']} |")
        if len(r["trades"]) > 25:
            out.append("")
            out.append(f"*Showing the last 25 of {len(r['trades'])}.*")
    return "\n".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="print the report instead of writing it")
    args = ap.parse_args(argv)
    try:
        r = score()
    except AlpacaError as exc:
        log.error("Data fetch failed: %s", exc)
        return 1

    text = render(r)
    if args.dry_run:
        print(text)
        return 0

    REPORTS.mkdir(exist_ok=True)
    STATE.mkdir(exist_ok=True)
    (REPORTS / "paper.md").write_text(text)
    (STATE / "paper.json").write_text(json.dumps(r, indent=2, default=str))
    log.info("%d closed, %d open, %+.1f%%, worst drop %.1f%%",
             r["n"], len(r["open"]), r["return_pct"], r["max_dd_pct"])
    if r["halted"]:
        log.error("HALTED at %.1f%% drawdown", r["max_dd_pct"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
