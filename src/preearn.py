"""Do some stocks reliably rally INTO earnings?

The claim is specific and testable: certain companies drift up in the weeks
before they report, often enough and by enough that you can buy a month or
three beforehand, sell the day before the release, and never carry the risk
of the announcement itself.

There is real literature behind the idea - the "earnings announcement
premium" - but that says something mild about the average stock. The claim
here is stronger: that particular names do it repeatedly, and that you can
identify them in advance.

Where the data comes from
-------------------------
EARNINGS DATES from SEC EDGAR. A company announcing results files an 8-K
carrying item 2.02, "Results of Operations and Financial Condition", on the
day it announces. That is the event itself rather than somebody's estimate of
it, it is free, and it goes back two decades. Nothing else in this project
has had a source that good.

PRICES from Yahoo, ten years of daily bars.

Neither is reachable from the laptop or the cloud container - both sit behind
proxies with short allowlists - so this only runs on a GitHub runner.

The two things that decide whether the answer means anything
-----------------------------------------------------------
MEASURED AGAINST THE MARKET. A stock that gained five percent before every
report between 2016 and 2025 might simply be a stock that went up; most did.
Every return here is the stock's return minus SPY's over the identical
window, so what is being measured is whether the run-up is specific to the
period before earnings rather than a bull market wearing a costume.

SELECTED ON ONE ERA, TESTED ON ANOTHER. Names are chosen using data up to
the end of 2025 and nothing else. 2026 is not looked at until the selection
is fixed. Searching a few hundred stocks across three holding windows WILL
turn up beautiful histories by chance, so the only number worth reading is
what the chosen names did in a year that had no say in choosing them - and
alongside it, what the REJECTED names did in the same year, because if they
did just as well the selection was noise.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time as _time
from datetime import date

import numpy as np
import pandas as pd

from .config import REPO_ROOT

REPORTS = REPO_ROOT / "reports"
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s",
                    stream=sys.stdout)
log = logging.getLogger("preearn")

UA = {"User-Agent": "tradingbot research bajwa19u@gmail.com"}
SEC_TICKERS = "https://www.sec.gov/files/company_tickers.json"
SEC_SUBS = "https://data.sec.gov/submissions/CIK{cik:010d}.json"

WINDOWS = [21, 42, 63]          # trading days before the report: ~1, 2, 3 months
EXIT_GAP = 1                    # sell this many trading days BEFORE the report
SELECT_END = "2025-12-31"       # everything after this is the untouched test
BENCHMARK = "SPY"

# Minimums for a name to be considered at all. A pattern over four reports is
# not a pattern.
MIN_REPORTS = 12
MIN_TEST_REPORTS = 2


def sec_json(url: str, tries: int = 4) -> dict:
    import requests
    for i in range(tries):
        r = requests.get(url, headers=UA, timeout=30)
        if r.status_code == 200:
            return r.json()
        _time.sleep(1.0 + i)          # EDGAR asks for 10 requests/second, tops
    raise RuntimeError(f"EDGAR refused {url}: {r.status_code}")


def cik_for(tickers: list[str]) -> dict[str, int]:
    """Ticker -> CIK, from the SEC's own mapping file."""
    raw = sec_json(SEC_TICKERS)
    by_sym = {v["ticker"].upper(): int(v["cik_str"]) for v in raw.values()}
    out = {t: by_sym[t] for t in tickers if t in by_sym}
    missing = [t for t in tickers if t not in by_sym]
    if missing:
        log.warning("No CIK for: %s", ", ".join(missing))
    return out


def announcement_dates(cik: int) -> list[date]:
    """Every 8-K carrying item 2.02 — the earnings releases themselves.

    The submissions file holds only the most recent thousand filings inline;
    older ones live in separate files it points to, and for a company that
    files often those are most of the history.
    """
    j = sec_json(SEC_SUBS.format(cik=cik))
    out: list[date] = []

    def harvest(block: dict) -> None:
        forms = block.get("form", [])
        items = block.get("items", [""] * len(forms))
        dates = block.get("filingDate", [])
        for f, it, d in zip(forms, items, dates):
            if f == "8-K" and "2.02" in (it or ""):
                out.append(pd.Timestamp(d).date())

    harvest(j["filings"]["recent"])
    for extra in j["filings"].get("files", []):
        try:
            harvest(sec_json("https://data.sec.gov/submissions/" + extra["name"]))
        except Exception as exc:                               # noqa: BLE001
            log.warning("CIK %s extra file %s: %s", cik, extra.get("name"), exc)
    return sorted(set(out))


def daily(symbols: list[str], years: int = 11) -> dict[str, pd.DataFrame]:
    import yfinance as yf
    log.info("Fetching %d years of daily bars for %d symbols",
             years, len(symbols))
    raw = yf.download(symbols, period=f"{years}y", interval="1d",
                      auto_adjust=True, progress=False, threads=True)
    out = {}
    for s in symbols:
        try:
            df = raw.xs(s, axis=1, level=1) if isinstance(raw.columns,
                                                          pd.MultiIndex) else raw
            df = df.dropna(subset=["Close"])
            if len(df) > 400:
                out[s] = df
        except Exception:                                      # noqa: BLE001
            continue
    log.info("Usable price history: %d symbols", len(out))
    return out


# --- the measurement ---------------------------------------------------------
def run_up(px: pd.DataFrame, bench: pd.DataFrame, when: date,
           window: int) -> dict | None:
    """Return over the `window` trading days ending EXIT_GAP days before the
    report, minus the benchmark over exactly the same days.

    Both legs are located by position in the price index rather than by
    calendar date, so holidays and halts cannot quietly stretch one window
    and not the other.
    """
    idx = px.index
    pos = idx.searchsorted(pd.Timestamp(when))
    if pos >= len(idx):
        return None
    sell = pos - EXIT_GAP
    buy = sell - window
    if buy < 0 or sell <= buy:
        return None
    b_t, s_t = idx[buy], idx[sell]
    try:
        b0, s0 = float(px["Close"].iloc[buy]), float(px["Close"].iloc[sell])
        bb = float(bench["Close"].asof(b_t))
        bs = float(bench["Close"].asof(s_t))
    except Exception:                                          # noqa: BLE001
        return None
    if not all(np.isfinite([b0, s0, bb, bs])) or b0 <= 0 or bb <= 0:
        return None
    stock = (s0 / b0 - 1) * 100
    market = (bs / bb - 1) * 100
    return {"report": when, "buy": b_t.date(), "sell": s_t.date(),
            "stock": round(stock, 2), "market": round(market, 2),
            "excess": round(stock - market, 2)}


def history(px: pd.DataFrame, bench: pd.DataFrame, dates: list[date],
            window: int) -> list[dict]:
    out = []
    for d in dates:
        r = run_up(px, bench, d, window)
        if r is not None:
            out.append(r)
    return out


def score(rows: list[dict]) -> dict:
    """How reliable, not how big. One monster quarter should not qualify a
    stock, so the hit rate leads and the median carries the size."""
    if not rows:
        return {"n": 0, "hit": 0.0, "median": 0.0, "mean": 0.0, "worst": 0.0}
    ex = np.array([r["excess"] for r in rows], dtype=float)
    return {"n": len(rows),
            "hit": round(100 * float((ex > 0).mean()), 1),
            "median": round(float(np.median(ex)), 2),
            "mean": round(float(ex.mean()), 2),
            "worst": round(float(ex.min()), 2)}


def split(rows: list[dict], cutoff: str = SELECT_END
          ) -> tuple[list[dict], list[dict]]:
    c = pd.Timestamp(cutoff).date()
    return ([r for r in rows if r["report"] <= c],
            [r for r in rows if r["report"] > c])


def qualifies(s: dict, min_hit: float, min_median: float) -> bool:
    return (s["n"] >= MIN_REPORTS and s["hit"] >= min_hit
            and s["median"] >= min_median)


# --- the universe ------------------------------------------------------------
# Deliberately spread across sectors rather than the tech names the rest of
# this project trades. If a pre-earnings drift exists it should not care what
# a company sells, and a list that is all semiconductors would only tell us
# about semiconductors.
UNIVERSE = [
    # tech / semis
    "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "AVGO", "AMD", "INTC",
    "QCOM", "TXN", "MU", "AMAT", "LRCX", "KLAC", "ADI", "NXPI", "ON", "MRVL",
    "CRM", "ORCL", "ADBE", "NOW", "INTU", "PANW", "SNPS", "CDNS", "ANET",
    "IBM", "CSCO", "ACN", "UBER", "ABNB", "BKNG", "NFLX", "TSLA", "SHOP",
    # financials
    "JPM", "BAC", "WFC", "GS", "MS", "C", "SCHW", "BLK", "SPGI", "CME",
    "AXP", "V", "MA", "PYPL", "COF", "USB", "PNC", "TFC", "BK", "AIG",
    "MET", "PRU", "ALL", "TRV", "CB", "PGR", "AFL",
    # health care
    "UNH", "JNJ", "LLY", "ABBV", "MRK", "PFE", "TMO", "ABT", "DHR", "BMY",
    "AMGN", "GILD", "VRTX", "REGN", "ISRG", "SYK", "BSX", "MDT", "ZTS",
    "CI", "ELV", "HCA", "MCK", "CVS",
    # consumer
    "WMT", "COST", "TGT", "HD", "LOW", "MCD", "SBUX", "NKE", "TJX", "DG",
    "KO", "PEP", "PG", "PM", "MO", "MDLZ", "CL", "KMB", "GIS", "KHC",
    "SYY", "YUM", "CMG", "DRI", "MAR", "HLT", "RCL", "CCL", "LVS", "DIS",
    # industrials, energy, materials, utilities, real estate, telecom
    "CAT", "DE", "HON", "GE", "MMM", "BA", "LMT", "RTX", "NOC", "GD",
    "UPS", "FDX", "UNP", "CSX", "NSC", "EMR", "ETN", "ITW", "PH", "ROK",
    "XOM", "CVX", "COP", "EOG", "SLB", "PSX", "VLO", "MPC", "OXY", "HAL",
    "LIN", "APD", "SHW", "ECL", "NEM", "FCX", "DOW", "DD", "NUE",
    "NEE", "DUK", "SO", "D", "AEP", "EXC", "SRE", "XEL",
    "AMT", "PLD", "CCI", "EQIX", "SPG", "O", "PSA",
    "T", "VZ", "TMUS", "CMCSA",
]


# --- report ------------------------------------------------------------------
HEAD = ("| stock | reports | hit rate | median excess | mean | worst |"
        "\n|---|---|---|---|---|---|")


def row(sym: str, s: dict) -> str:
    return (f"| {sym} | {s['n']} | {s['hit']:.0f}% | {s['median']:+.2f}% | "
            f"{s['mean']:+.2f}% | {s['worst']:+.2f}% |")


def basket(rows: list[dict]) -> dict:
    """Every trade the selected names would have produced, pooled."""
    return score(rows)


def research(data: dict[str, pd.DataFrame], bench: pd.DataFrame,
             dates: dict[str, list[date]], window: int,
             min_hit: float, min_median: float, top: int) -> str:
    picked, rejected, all_scores = [], [], {}
    for sym, px in data.items():
        rows = history(px, bench, dates.get(sym, []), window)
        sel, test = split(rows)
        s_sel, s_test = score(sel), score(test)
        all_scores[sym] = (s_sel, s_test, sel, test)
        if qualifies(s_sel, min_hit, min_median):
            picked.append(sym)
        elif s_sel["n"] >= MIN_REPORTS:
            rejected.append(sym)

    picked.sort(key=lambda s: (-all_scores[s][0]["hit"],
                               -all_scores[s][0]["median"]))
    picked = picked[:top]

    L = [f"# Buying into earnings — {window} trading days "
         f"(~{round(window / 21)} month{'s' if window > 30 else ''})", "",
         f"{len(data)} stocks · earnings dates from SEC 8-K item 2.02 · "
         f"returns are excess of {BENCHMARK} over the identical window · "
         f"sell {EXIT_GAP} day before the report", "",
         f"Selected on reports up to {SELECT_END}. Everything after that was "
         f"not looked at until the names were fixed.", "",
         f"Bar to qualify: at least {MIN_REPORTS} past reports, a hit rate of "
         f"{min_hit:.0f}% or better, and a median excess of "
         f"{min_median:+.1f}% or better.", ""]

    if not picked:
        L += ["## Nothing qualified", "",
              f"No stock cleared that bar on the selection era. That is a "
              f"result, not a failure to find one: the claim is that such "
              f"stocks exist and are identifiable in advance, and at this "
              f"threshold they are not.", ""]
        return "\n".join(L) + "\n"

    L += [f"## The {len(picked)} that qualified, on the selection era "
          f"(through {SELECT_END})", "", HEAD]
    for s in picked:
        L.append(row(s, all_scores[s][0]))

    L += ["", "## The same names in 2026 — the year that had no say", "", HEAD]
    for s in picked:
        t = all_scores[s][1]
        L.append(row(s, t) if t["n"] else f"| {s} | 0 | — | — | — | — |")

    sel_pool = [r for s in picked for r in all_scores[s][2]]
    test_pool = [r for s in picked for r in all_scores[s][3]]
    rej_pool = [r for s in rejected for r in all_scores[s][3]]

    L += ["", "## What actually matters", "",
          "| group | trades | hit rate | median excess | mean |",
          "|---|---|---|---|---|"]
    for name, pool in (("picked, selection era", sel_pool),
                       ("picked, 2026", test_pool),
                       ("REJECTED, 2026", rej_pool)):
        b = basket(pool)
        L.append(f"| {name} | {b['n']} | {b['hit']:.0f}% | "
                 f"{b['median']:+.2f}% | {b['mean']:+.2f}% |")

    p, r = basket(test_pool), basket(rej_pool)
    L += ["", "## Verdict", ""]
    if p["n"] < MIN_TEST_REPORTS * max(1, len(picked)) // 2:
        L.append(f"- Only {p['n']} trades in 2026 — too few to conclude "
                 f"anything either way yet.")
    if p["median"] <= 0:
        L.append(f"- **The chosen names did not beat the market into earnings "
                 f"in 2026** (median {p['median']:+.2f}%). The selection "
                 f"picked up a pattern that did not carry forward.")
    elif r["n"] >= 20 and p["median"] <= r["median"]:
        L.append(f"- The chosen names made {p['median']:+.2f}% in 2026 and the "
                 f"REJECTED ones made {r['median']:+.2f}%. Selecting did no "
                 f"better than not selecting, so the screen found nothing.")
    else:
        L.append(f"- **The chosen names beat the market into earnings in 2026 "
                 f"— median {p['median']:+.2f}%, hit rate {p['hit']:.0f}% — "
                 f"while the names that failed the screen managed "
                 f"{r['median']:+.2f}%.** That is the shape a real effect "
                 f"would have. It is one year, so it is a reason to keep "
                 f"going rather than a reason to size up.")
    return "\n".join(L) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--windows", default="21,42,63",
                    help="trading days before the report")
    ap.add_argument("--min-hit", type=float, default=65.0)
    ap.add_argument("--min-median", type=float, default=1.0)
    ap.add_argument("--top", type=int, default=20)
    ap.add_argument("--symbols", default="")
    args = ap.parse_args(argv)

    syms = ([s.strip().upper() for s in args.symbols.split(",") if s.strip()]
            or UNIVERSE)
    windows = [int(w) for w in args.windows.split(",") if w.strip()]

    ciks = cik_for(syms)
    log.info("Resolved %d CIKs of %d symbols", len(ciks), len(syms))
    dates: dict[str, list[date]] = {}
    for i, (sym, cik) in enumerate(ciks.items(), 1):
        try:
            dates[sym] = announcement_dates(cik)
        except Exception as exc:                               # noqa: BLE001
            log.warning("%s: %s", sym, exc)
        if i % 25 == 0:
            log.info("  earnings dates: %d/%d", i, len(ciks))
        _time.sleep(0.12)                       # EDGAR fair-use rate limit
    log.info("Earnings dates for %d symbols, %d releases in total",
             len(dates), sum(len(v) for v in dates.values()))

    prices = daily(sorted(set(list(dates) + [BENCHMARK])))
    bench = prices.get(BENCHMARK)
    if bench is None:
        log.error("No benchmark history — cannot measure excess returns.")
        return 1
    data = {s: p for s, p in prices.items() if s != BENCHMARK and s in dates}

    REPORTS.mkdir(exist_ok=True)
    parts, js = [], {}
    for w in windows:
        body = research(data, bench, dates, w, args.min_hit, args.min_median,
                        args.top)
        parts.append(body)
        log.info("window %d done", w)
    out = "\n\n---\n\n".join(parts)
    (REPORTS / "preearn.md").write_text(out)
    (REPORTS / "preearn.json").write_text(json.dumps(
        {"universe": len(data), "windows": windows,
         "releases": {s: len(v) for s, v in dates.items()}},
        indent=2, default=str))
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
