"""The pre-earnings list: companies that must clear two gates, not one.

The idea, in Uday's words: find companies that reliably get bid up in the
weeks before they report, buy one to three months ahead, and sell just before
the release. No charts, no intraday, nothing to do with the rest of this
project.

Two gates, and a name has to clear both
---------------------------------------
FUNDAMENTAL (src/fundamentals.py): growing revenue, profitable every recent
quarter, earnings per share higher than three years ago - judged only from
filings that existed on the selection date. A company can have a beautiful
pre-earnings price record and be quietly falling apart; that record is not
worth buying.

HISTORY (src/preearn.py): enough reports to mean anything, a majority of them
positive, and a positive median - all measured as excess return over SPY, so
a stock that merely went up in a bull market does not qualify for having gone
up in a bull market.

Why the cutoff moved to 2022
----------------------------
The first version of this selected on everything through 2025 and tested on
2026 - thirty trades. Thirty trades cannot separate a real effect from a run
of luck: a fair coin shows 20 heads in 30 flips about one time in twenty. So
selection now stops at the end of 2022 and 2023 onwards is untouched, which
buys roughly four times the evidence at the cost of three years of hindsight
in the selection. That is the right trade.

What this still cannot tell us
------------------------------
The universe is 176 companies that exist and are large TODAY. Firms that
were large in 2016 and then failed are missing from it, and their absence
flatters every result here. Nothing in this file fixes that; it is a reason
to treat a modest edge as possibly no edge at all.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd

from . import fundamentals as fd
from . import preearn as pe
from .config import REPO_ROOT

REPORTS = REPO_ROOT / "reports"
CACHE = REPO_ROOT / "cache"
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s",
                    stream=sys.stdout)
log = logging.getLogger("preearn_screen")

SELECT_END = "2022-12-31"       # everything after this is untouched
WINDOWS = (21, 42, 63)          # trading days held: about 1, 2 and 3 months

# The history gate. Set to be demanding enough that a handful of names pass
# out of 176, and then left alone - tuning these until the out-of-sample
# result improves is how a backtest becomes a work of fiction.
MIN_REPORTS = 12
MIN_HIT = 65.0                  # percent of reports with a positive excess
MIN_MEDIAN = 1.0                # percent, median excess return
TARGET_MIN, TARGET_MAX = 10, 15


@dataclass
class Name:
    symbol: str
    verdict: fd.Verdict | None = None
    rows: list[dict] = field(default_factory=list)   # every run-up measured
    note: str = ""

    def before(self, cutoff: date) -> list[dict]:
        return [r for r in self.rows if r["report"] <= cutoff]

    def after(self, cutoff: date) -> list[dict]:
        return [r for r in self.rows if r["report"] > cutoff]


# --- gathering ---------------------------------------------------------------
def company_facts(cik: int) -> dict:
    """XBRL facts for one filer, cached on disk.

    These files run to several megabytes each and 176 of them is most of a
    gigabyte, so a re-run reads the cache rather than asking the SEC again.
    """
    CACHE.mkdir(exist_ok=True)
    f = CACHE / f"facts_{cik:010d}.json"
    if f.exists():
        try:
            return json.loads(f.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    blob = pe.sec_json(fd.SEC_FACTS.format(cik=cik))
    try:
        f.write_text(json.dumps(blob))
    except OSError as exc:
        log.warning("Could not cache %s: %s", f.name, exc)
    return blob


@dataclass
class Raw:
    """The expensive half: prices, report dates and a fundamental verdict.

    Gathered once and reused for every holding window, because downloading a
    gigabyte of filings three times to answer three versions of the same
    question would be silly.
    """
    bench: pd.DataFrame
    prices: dict[str, pd.DataFrame] = field(default_factory=dict)
    dates: dict[str, list[date]] = field(default_factory=dict)
    verdicts: dict[str, fd.Verdict] = field(default_factory=dict)
    notes: dict[str, str] = field(default_factory=dict)


def gather(symbols: list[str], cutoff: date) -> Raw:
    """Everything both gates need, one company at a time."""
    ciks = pe.cik_for(symbols)
    prices = pe.daily(sorted(set(symbols) | {pe.BENCHMARK}))
    bench = prices.get(pe.BENCHMARK)
    if bench is None:
        raise RuntimeError(f"no price history for {pe.BENCHMARK}")

    raw = Raw(bench=bench)
    for i, sym in enumerate(symbols, 1):
        px = prices.get(sym)
        if px is None:
            raw.notes[sym] = "no price history"
            continue
        cik = ciks.get(sym)
        if cik is None:
            raw.notes[sym] = "no CIK"
            continue
        raw.prices[sym] = px
        try:
            raw.dates[sym] = pe.announcement_dates(cik)
            raw.verdicts[sym] = fd.judge(company_facts(cik), cutoff)
        except Exception as exc:                               # noqa: BLE001
            raw.notes[sym] = f"failed: {exc}"
            log.warning("%s: %s", sym, exc)
        if i % 25 == 0:
            log.info("gathered %d/%d", i, len(symbols))
    return raw


def measure(raw: Raw, window: int) -> dict[str, Name]:
    """Turn the gathered material into one Name per company, for one window."""
    out: dict[str, Name] = {}
    for sym, px in raw.prices.items():
        n = Name(sym, verdict=raw.verdicts.get(sym),
                 note=raw.notes.get(sym, ""))
        n.rows = pe.history(px, raw.bench, raw.dates.get(sym, []), window)
        out[sym] = n
    return out


# --- selecting ---------------------------------------------------------------
def history_gate(rows: list[dict]) -> tuple[bool, dict]:
    s = pe.score(rows)
    ok = (s["n"] >= MIN_REPORTS and s["hit"] >= MIN_HIT
          and s["median"] >= MIN_MEDIAN)
    return ok, s


def select(names: dict[str, Name], cutoff: date
           ) -> tuple[list[tuple[str, dict]], list[tuple[str, dict]]]:
    """(qualified, rejected), each as (symbol, selection-era score).

    Qualified means both gates. Rejected is everything else that had enough
    reports to be judged at all - it is the control group, and without it a
    good-looking result on the chosen names means nothing.
    """
    passed, failed = [], []
    for sym, n in sorted(names.items()):
        rows = n.before(cutoff)
        ok_hist, s = history_gate(rows)
        if s["n"] < MIN_REPORTS:
            continue                        # not enough evidence either way
        ok_fund = bool(n.verdict and n.verdict.passed)
        (passed if (ok_hist and ok_fund) else failed).append((sym, s))

    # Ranked by reliability first, size second - the same order the gate
    # itself cares about.
    passed.sort(key=lambda kv: (-kv[1]["hit"], -kv[1]["median"]))
    return passed, failed


def trim(passed: list[tuple[str, dict]]) -> tuple[list[tuple[str, dict]], str]:
    """Hold the list to TARGET_MAX by rank, and say so when it was cut.

    If fewer than TARGET_MIN pass, the list stays short. Loosening the gate
    until the list is the size we wanted is the exact move that turns a
    screen into a story.
    """
    if len(passed) > TARGET_MAX:
        return passed[:TARGET_MAX], (
            f"{len(passed)} names cleared both gates; kept the top "
            f"{TARGET_MAX} by hit rate")
    if len(passed) < TARGET_MIN:
        return passed, (
            f"only {len(passed)} names cleared both gates - short of the "
            f"{TARGET_MIN} asked for, and not loosened to reach it")
    return passed, f"{len(passed)} names cleared both gates"


# --- testing -----------------------------------------------------------------
def pooled(names: dict[str, Name], syms: list[str], cutoff: date) -> list[dict]:
    return [r for s in syms for r in names[s].after(cutoff)]


def by_year(rows: list[dict]) -> dict[int, dict]:
    out: dict[int, list[dict]] = {}
    for r in rows:
        out.setdefault(r["report"].year, []).append(r)
    return {y: pe.score(rs) for y, rs in sorted(out.items())}


def portfolio(rows: list[dict], equity: float, max_open: int) -> dict:
    """What the list would actually have done with a small account.

    Positions are taken in date order and refused when `max_open` are already
    held, which is the real constraint on $2,000 - not whether the signal was
    good, but whether there was money free when it fired. Equal weight, no
    compounding between overlapping trades, costs ignored.
    """
    if not rows:
        return {"taken": 0, "skipped": 0, "hit": 0.0, "total": 0.0, "each": 0.0}
    ordered = sorted(rows, key=lambda r: r["buy"])
    open_until: list[date] = []
    taken, skipped = [], 0
    for r in ordered:
        open_until = [d for d in open_until if d > r["buy"]]
        if len(open_until) >= max_open:
            skipped += 1
            continue
        open_until.append(r["sell"])
        taken.append(r)
    slice_ = equity / max_open
    pnl = sum(slice_ * r["excess"] / 100 for r in taken)
    ex = np.array([r["excess"] for r in taken], dtype=float)
    return {"taken": len(taken), "skipped": skipped,
            "hit": round(100 * float((ex > 0).mean()), 1),
            "total": round(pnl, 2),
            "each": round(float(np.median(ex)), 2)}


# --- report ------------------------------------------------------------------
def render(window: int, cutoff: date, names: dict[str, Name],
           kept: list[tuple[str, dict]], note: str,
           rejected: list[tuple[str, dict]], equity: float,
           max_open: int) -> str:
    out = [f"## Holding {window} trading days into the report", "", note, ""]

    if not kept:
        out.append("Nothing to test.")
        return "\n".join(out)

    syms = [s for s, _ in kept]
    out += ["| stock | reports | hit rate | median excess | revenue growth |",
            "|---|---|---|---|---|"]
    for sym, s in kept:
        v = names[sym].verdict
        g = f"{v.growth_hit:.0%}" if v else "—"
        out.append(f"| {sym} | {s['n']} | {s['hit']:.0f}% | "
                   f"{s['median']:+.2f}% | {g} |")

    picked = pooled(names, syms, cutoff)
    others = pooled(names, [s for s, _ in rejected], cutoff)
    p, o = pe.score(picked), pe.score(others)

    out += ["", f"### What happened after {cutoff}", "",
            "| | trades | hit rate | median excess | worst |",
            "|---|---|---|---|---|",
            f"| **the list** | {p['n']} | {p['hit']:.0f}% | "
            f"{p['median']:+.2f}% | {p['worst']:+.2f}% |",
            f"| everything rejected | {o['n']} | {o['hit']:.0f}% | "
            f"{o['median']:+.2f}% | {o['worst']:+.2f}% |"]

    edge = p["median"] - o["median"]
    out += ["", f"Separation: **{edge:+.2f}%** median excess. "
            + ("The list beat the names it rejected." if edge > 0 else
               "**The list did no better than the names it rejected — "
               "on this evidence the screen is not selecting anything.**"), ""]

    out += ["### Year by year", "",
            "| year | trades | hit rate | median excess |", "|---|---|---|---|"]
    years = by_year(picked)
    for y, s in years.items():
        out.append(f"| {y} | {s['n']} | {s['hit']:.0f}% | {s['median']:+.2f}% |")
    good = sum(1 for s in years.values() if s["median"] > 0)
    out += ["", f"Positive in {good} of {len(years)} test years.", ""]

    sim = portfolio(picked, equity, max_open)
    out += [f"### With {equity:,.0f} dollars, {max_open} positions at a time", "",
            f"- {sim['taken']} trades taken, {sim['skipped']} missed for lack "
            f"of free capital",
            f"- {sim['hit']:.0f}% of them positive, median {sim['each']:+.2f}%",
            f"- **{sim['total']:+,.2f}** against the market, before costs", "",
            "_Excess over SPY, so this is what the strategy added beyond "
            "simply holding the index — not the account's total change._", ""]
    return "\n".join(out)


def run(symbols: list[str], windows, cutoff: date, equity: float,
        max_open: int) -> str:
    parts = ["# Buying into earnings", "",
             f"Selected on reports up to **{cutoff}**, tested on everything "
             f"after. {len(symbols)} companies considered.", "",
             f"A name qualifies only by clearing both gates: growing and "
             f"profitable on the filings that existed at {cutoff}, and at "
             f"least {MIN_REPORTS} reports with a {MIN_HIT:.0f}% hit rate and "
             f"a {MIN_MEDIAN:+.1f}% median excess return into them.", ""]
    raw = gather(symbols, cutoff)
    for w in windows:
        log.info("=== window %d ===", w)
        names = measure(raw, w)
        passed, rejected = select(names, cutoff)
        kept, note = trim(passed)
        parts.append(render(w, cutoff, names, kept, note, rejected,
                            equity, max_open))
    return "\n".join(parts)


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cutoff", default=SELECT_END)
    ap.add_argument("--windows", default=",".join(str(w) for w in WINDOWS))
    ap.add_argument("--equity", type=float, default=2000.0)
    ap.add_argument("--max-open", type=int, default=3)
    ap.add_argument("--symbols", default="")
    return ap.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    symbols = ([s.strip().upper() for s in args.symbols.split(",") if s.strip()]
               or pe.UNIVERSE)
    windows = [int(w) for w in args.windows.split(",") if w.strip()]
    text = run(symbols, windows, pd.Timestamp(args.cutoff).date(),
               args.equity, args.max_open)
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / "preearn_screen.md").write_text(text)
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
