"""BEFORE baseline for the profitability audit, from the repo's own records.

Reads only files already committed (no market data), so it runs anywhere and
can be re-run on any commit to see what the records said then. Backtests,
paper signals and posted (live) signals are kept apart and never summed.

  state/ledger_daytrade.csv  day-trade channel; source live = posted,
                             replay = the live rule re-run on the day's bars
                             for days before the ledger, corrected = 5 Oct
                             from reports/live_corrections.md
  state/ledger_inplay.csv    the separate in-play channel (src/inplay_bot.py)
  reports/orb_paper.csv      forward paper record of the Stocks-in-Play ORB
                             candidate; source live = seen by the paper job as
                             it happened, backtest only = filled in afterwards
  reports/orb_month.json     the desk's month replay of the live rule (backtest)

Units: ledger and month replay rows are % of the account with a full stop
costing 1%. The paper record is the stock's own move (with modelled and with
measured costs); it is also shown divided by its risk, i.e. on the same 1%
account basis.

Usage: python -m src.audit_baseline
"""
from __future__ import annotations

import json
import subprocess
import sys

import numpy as np
import pandas as pd

from .config import REPO_ROOT

OUT = REPO_ROOT / "reports" / "audit_baseline.md"
BIGTECH_FROM = "2026-10-06"          # DAYTRADE_STRATEGY=bigtech from this session (commit 1ec4c5f, 5 Oct evening)


def st(r) -> dict:
    r = np.asarray(pd.to_numeric(pd.Series(r), errors="coerce").dropna(), float)
    n = len(r)
    if n == 0:
        return dict(n=0)
    w, l = r[r > 0], r[r <= 0]
    eq = np.cumsum(r)
    return dict(n=n, win=100 * len(w) / n, wins=len(w), losses=len(l), avg=r.mean(),
                pf=w.sum() / -l.sum() if l.sum() < 0 else float("inf"), total=r.sum(),
                dd=float((np.maximum.accumulate(np.concatenate([[0.0], eq]))[1:] - eq).max()),
                avg_w=w.mean() if len(w) else 0.0, avg_l=l.mean() if len(l) else 0.0)


HDR = ("| record | kind | period | trades | win % (won/lost) | avg per trade | PF | cumulative | max DD | avg win / loss |\n"
       "|---|---|---|---|---|---|---|---|---|---|")


def row(name, kind, period, s) -> str:
    if not s.get("n"):
        return f"| {name} | {kind} | {period} | 0 | | | | | | |"
    return (f"| {name} | {kind} | {period} | {s['n']} | {s['win']:.0f}% ({s['wins']}/{s['losses']}) | {s['avg']:+.2f}% | "
            f"{s['pf']:.2f} | {s['total']:+.2f}% | {s['dd']:.2f}% | {s['avg_w']:+.2f}% / {s['avg_l']:+.2f}% |")


def span(df, col="date") -> str:
    return f"{df[col].min()} to {df[col].max()}" if len(df) else "-"


def main() -> int:
    try:
        commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
                                cwd=REPO_ROOT).stdout.strip()
    except OSError:
        commit = "?"
    L = ["# Audit baseline (BEFORE) - day-trade bot, from the repo's records", "",
         f"Commit {commit}. Written by `python -m src.audit_baseline`; reads only committed files. "
         "Backtest, paper and posted records are separate rows and are never summed.", "",
         "## Production entry point and active strategy (read from code, workflows and config)", "",
         "- Entry point: `python -m src.live_bot` from `.github/workflows/live-open.yml` (the open, polling) and "
         "`live-bot.yml` (rest of the session); `day-end.yml` settles the day.",
         "- Strategy switch: `live_bot.strategy()` reads the repo variable `DAYTRADE_STRATEGY`, `.strip().lower()`, "
         "default `classic`. The variable is set to `bigtech` (stored as `bigtech\\r\\n\\n`), so the channel runs "
         "`orb_live.RULES['bigtech']` = `orb_paper.CANDIDATE` on TSLA AMD NVDA META AAPL MSFT every day.",
         "- Rule: opening range 09:30-09:34; range >= 0.35 of 14-day ATR; first 1-minute close outside it, "
         "09:35-09:44; stop at the session extreme -/+ 0.02 ATR, moved to entry at +1x risk; target 2x risk; "
         "out at 15:55. Researched at 0.05% slippage a side.",
         "- Orders: none. `autotrade.ENABLED = False` (pinned by a test); signals only.",
         "- Break and retest: off (`retest` not in the live path; settled research).", ""]

    rows = [HDR]
    J = {}
    lg = pd.read_csv(REPO_ROOT / "state" / "ledger_daytrade.csv")
    bt = lg[lg.date >= BIGTECH_FROM]
    for nm, part in (("posted (live)", bt[bt.source == "live"]), ("replay of the live rule", bt[bt.source == "replay"]),
                     ("all ledger rows", bt)):
        s = st(part.pct)
        J[f"daytrade_bigtech_{nm}"] = s
        rows.append(row("day-trade channel, big tech rule", nm, span(part), s))
    first = lg[lg.date < BIGTECH_FROM]
    s = st(first.pct)
    J["daytrade_inplay_day"] = s
    rows.append(row("day-trade channel, 5 Oct (in-play rule)", "posted (corrected)", span(first), s))

    ip = pd.read_csv(REPO_ROOT / "state" / "ledger_inplay.csv")
    for nm, part in (("posted (live)", ip[ip.source == "live"]), ("replay", ip[ip.source == "replay"])):
        s = st(part.pct)
        J[f"inplay_channel_{nm}"] = s
        rows.append(row("in-play channel (inplay_bot)", nm, span(part), s))

    pp = pd.read_csv(REPO_ROOT / "reports" / "orb_paper.csv")
    pp["acct"] = pp.result_pct / pp.risk_pct
    pp["acct_real"] = pp.result_real_pct / pp.risk_pct
    for nm, part in (("paper, seen live", pp[pp.source == "live"]), ("paper, filled in afterwards", pp[pp.source != "live"]),
                     ("paper, all", pp)):
        for col, unit in (("result_pct", "stock move, 0.05%/side"), ("result_real_pct", "stock move, measured costs"),
                          ("acct", "account % at 1% risk"), ("acct_real", "account % at 1% risk, measured costs")):
            s = st(part[col])
            J[f"paper_{nm}_{col}"] = s
            if nm != "paper, filled in afterwards" or col == "acct":
                rows.append(row(f"Stocks-in-Play candidate ({unit})", nm, span(part), s))

    mo = json.loads((REPO_ROOT / "reports" / "orb_month.json").read_text())
    mt = pd.DataFrame(mo["trades"])
    s = st(mt.result_pct)
    J["month_replay"] = s
    rows.append(row(f"month replay of the live rule ({mo.get('switch')})", "backtest", f"{mo.get('from')} to {mo.get('to')}", s))
    L += ["## Records", ""] + rows + [""]

    # the live big tech rule's posted + replay record, split
    L += ["## Day-trade channel, big tech rule: splits (ledger, posted + replay)", ""]
    for col, title in (("symbol", "ticker"), ("side", "side"), ("reason", "exit")):
        L += [f"| {title} | trades | win % | avg | total |", "|---|---|---|---|---|"]
        for k, g in bt.groupby(col):
            s = st(g.pct)
            L.append(f"| {k} | {s['n']} | {s['win']:.0f}% | {s['avg']:+.2f}% | {s['total']:+.2f}% |")
        L.append("")
    pp_live = pp[pp.source == "live"]
    crit = st(pp_live.acct_real)
    L += ["## Stocks-in-Play candidate: promotion criterion on the forward paper record", "",
          f"Criterion fixed in `src/orb_audit.py` before the audit ran: forward paper record positive over >= 60 trades. "
          f"Seen-live paper trades so far: {crit.get('n', 0)}, average {crit.get('avg', float('nan')):+.2f}% of account "
          f"(measured costs). **{'PASS' if crit.get('n', 0) >= 60 and crit.get('avg', -1) > 0 else 'NOT MET'}** - "
          "the candidate stays in paper.", ""]
    L += ["## Research results already on file (backtest; quoted, not re-run here)", "",
          "| study | data | result |", "|---|---|---|",
          "| reports/orb_bigtech.md | IEX 1-min, 2025-09-30 to 2026-10-02 | live rule on big tech: recent 63 sessions 88 trades, "
          "53% win, +0.170%/trade, PF 1.60, +15.0%; earlier 189 sessions 265 trades, 44% win, -0.028%/trade, PF 0.93, -7.5%; "
          "at 0.10% slippage +0.124% / -0.096% |",
          "| reports/orb_improve.md | same | the two adopted changes (entries by 09:44, stop to entry at +1x) |",
          "| reports/orb_checks.md | SIP NBBO | median round-trip cost 0.045%, mean 0.054% |", "",
          "Reproduction, full splits, cost stress and the untouched periods are in `reports/orb_audit.md` "
          "(GitHub Action `ORB audit`).", ""]
    OUT.write_text("\n".join(L) + "\n")
    OUT.with_suffix(".json").write_text(json.dumps(J, indent=1, default=float))
    print("\n".join(L))
    return 0


if __name__ == "__main__":
    sys.exit(main())
