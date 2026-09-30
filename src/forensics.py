"""Trade forensics — why losers lose, and what the rules threw away.

Two questions, both diagnostic rather than exploratory:

  AUTOPSY     For every trade taken, record the conditions at entry, then
              compare winners against losers attribute by attribute. If
              losers share something winners do not, that is a rule worth
              adding. If the two look identical, the entry filter has no
              more information to give and tuning it is wasted effort.

  MISSED      For every day a symbol went on to make a big move, check
              whether the strategy entered. If not, which gate blocked it?
              A gate that repeatedly blocks large winners is costing money;
              one that blocks nothing is decoration.

Neither of these tunes anything. They say where the information is, so any
change made afterwards has a reason behind it rather than a better backtest.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime

import numpy as np
import pandas as pd

from .config import REPO_ROOT, Credentials
from .data import AlpacaError, MarketData
from .swing import BASE, HOLDOUT, RESEARCH, prepare, run_portfolio, signal_times

REPORTS = REPO_ROOT / "reports"
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                    stream=sys.stdout)
log = logging.getLogger("forensics")

# High-beta, high-volume names — the kind of stock the setup was written for,
# as opposed to the mega-caps everything has been tested on so far.
MOVERS = [
    "TSLA", "NVDA", "AMD", "PLTR", "COIN", "MARA", "SOFI", "AFRM", "RBLX",
    "SNAP", "U", "DKNG", "CVNA", "SMCI", "MSTR", "ARM", "RKLB", "RIVN",
    "SHOP", "ROKU", "NET", "DDOG", "CRWD", "SNOW", "ABNB", "HOOD", "TTD",
    "ENPH", "FSLR", "PLUG", "UPST", "IONQ", "LCID", "NIO", "BABA", "ZM",
]

# Everything at once. Its only job is the volatility split: a median cut can
# only separate what the universe already contains, so asking whether the edge
# needs volatile stocks requires a list that holds both kinds.
WIDE = sorted(set(MOVERS) | set(HOLDOUT) | set(RESEARCH))

# A clean holdout for the VOLATILITY-SCREENED rule.
#
# Why this list had to exist: research and holdout are mega-caps. Screening
# them at 3% daily range left 2 symbols and 6 trades - no test at all. A rule
# that only trades movers can only be checked against movers.
#
# Chosen by CATEGORY, not by performance: sectors that are structurally
# volatile - crypto miners and treasuries, quantum, space and eVTOL, small
# modular nuclear, beaten-down growth software, EV charging, biotech. No 2026
# return was looked at before writing this list, and the 3% screen is applied
# to history BEFORE the trading window. Names already used anywhere else in
# this project are excluded by construction (asserted in the tests).
#
# Selecting a "volatile sector" list is still a judgement informed by the past.
# It is not a judgement informed by these stocks' returns, which is the thing
# that would invalidate the test.
FRESH = [
    # crypto miners and treasury companies
    "RIOT", "CLSK", "HUT", "BITF", "WULF", "CIFR", "CORZ", "IREN", "BTBT",
    # quantum and AI infrastructure
    "RGTI", "QBTS", "SOUN", "BBAI", "AI", "APLD",
    # space and electric aviation
    "ASTS", "LUNR", "RDW", "JOBY", "ACHR",
    # small modular nuclear and power
    "OKLO", "SMR", "LEU", "NNE",
    # beaten-down growth software
    "PATH", "S", "FVRR", "TWLO", "ZS", "OKTA", "GTLB", "MDB", "APP", "RDDT",
    # EV, charging and storage
    "QS", "CHPT", "BLNK", "LYFT",
    # retail-heavy and high-short-interest
    "GME", "AMC", "OPEN", "BYND", "WOLF", "TLRY",
    # biotech
    "MRNA", "NVAX", "VKTX", "CRSP", "BEAM", "NTLA", "RXRX",
]

# The watchlist this bot trades: the big names plus whatever is actually in
# play. Not a clean holdout - NVDA, TSLA, AMD and MU are all in lists this
# project has already used - so results here are IN-SAMPLE and confirm
# nothing. The familiar names are the most misleading precisely because a
# number on NVDA feels more real than the same number on RDW.
# Big tech only, AVGO dropped: over the live record and the backtests it
# never contributed a winner worth the slot. NFLX and ORCL are added because
# they are unambiguously in the same bucket and more names means more breaks
# to measure, which is the whole point of an autopsy.
BIGTECH = [
    "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA", "AMD",
    "MU", "PLTR", "SMCI", "NFLX", "ORCL",
]

CORE = [
    # the ones everyone watches
    "NVDA", "TSLA", "AMD", "AAPL", "MSFT", "META", "AMZN", "GOOGL",
    # in play right now - memory/AI supercycle and the high-beta AI names
    "MU", "AVGO", "PLTR", "SMCI",
]
TECH10 = CORE          # old name, kept so nothing breaks

UNIVERSES = {
    "bigtech": BIGTECH,"research": RESEARCH, "holdout": HOLDOUT, "movers": MOVERS,
             "core": CORE, "tech10": CORE,
             "fresh": FRESH,
             "wide": WIDE}


def features_at(df: pd.DataFrame, i: int, p: dict) -> dict:
    """Conditions on the entry bar. Only backward-looking values."""
    bar = df.iloc[i]
    f, m, s = p["fast"], p["mid"], p["slow"]
    ef = float(bar[f"ema{f}"])
    a = float(bar["atr"])
    close = float(bar["close"])
    prior = df.iloc[max(0, i - 20):i]
    slope_n = p.get("slope_bars", 20)
    ef_then = float(df[f"ema{f}"].iloc[max(0, i - slope_n)])
    prev_close = float(df["close"].iloc[i - 1]) if i else close
    return {
        "atr_pct": round(100 * a / close, 2) if close else 0.0,
        "ext_from_ema_atr": round((close - ef) / a, 2) if a else 0.0,
        "slope_atr": round((ef - ef_then) / a, 2) if a else 0.0,
        "rvol": round(float(bar["volume"]) / float(prior["volume"].mean()), 2)
        if len(prior) and prior["volume"].mean() else 0.0,
        "gap_pct": round(100 * (float(bar["open"]) - prev_close) / prev_close, 2)
        if prev_close else 0.0,
        "above_slow_atr": round((close - float(bar[f"ema{s}"])) / a, 2) if a else 0.0,
        "range_pct": round(100 * (float(bar["high"]) - float(bar["low"])) / close, 2)
        if close else 0.0,
    }


def autopsy(prepared: dict, trades: list[dict], p: dict) -> dict:
    """Winners vs losers, attribute by attribute."""
    rows = []
    for t in trades:
        df = prepared.get(t["symbol"])
        if df is None:
            continue
        ts = pd.Timestamp(t["entry_date"]).tz_localize(df.index.tz) \
            if pd.Timestamp(t["entry_date"]).tz is None else pd.Timestamp(t["entry_date"])
        if ts not in df.index:
            continue
        i = df.index.get_loc(ts)
        feat = features_at(df, i, p)
        feat["r"] = t["r_multiple"]
        feat["win"] = t["r_multiple"] > 0
        feat["symbol"] = t["symbol"]
        rows.append(feat)
    if not rows:
        return {}
    d = pd.DataFrame(rows)
    keys = [c for c in d.columns if c not in ("r", "win", "symbol")]
    out = []
    for k in keys:
        w = d.loc[d["win"], k]
        l = d.loc[~d["win"], k]
        if not len(w) or not len(l):
            continue
        # how separated are the two groups, in pooled standard deviations?
        pooled = np.sqrt((w.var(ddof=1) + l.var(ddof=1)) / 2) or 1e-9
        out.append({
            "feature": k,
            "winners_median": round(float(w.median()), 2),
            "losers_median": round(float(l.median()), 2),
            "separation": round(float((w.mean() - l.mean()) / pooled), 2),
        })
    out.sort(key=lambda r: -abs(r["separation"]))
    return {"n_wins": int(d["win"].sum()), "n_losses": int((~d["win"]).sum()),
            "features": out}


def missed(prepared: dict, sigs: dict, trades: list[dict], p: dict,
           lo, hi, move_atr: float = 3.0, horizon: int = 20) -> dict:
    """Days a stock went on to make a big move without us being in it."""
    from .inspect_symbol import gates, why_not
    taken = {(t["symbol"], t["entry_date"]) for t in trades}
    blocked: dict[str, list[float]] = {}
    caught = missed_n = 0

    for sym, df in prepared.items():
        g = gates(df, p)
        window = df[(df.index >= lo) & (df.index < hi)]
        if len(window) < horizon + 2:
            continue
        for ts in window.index[:-horizon]:
            i = df.index.get_loc(ts)
            a = float(df["atr"].iloc[i])
            if not a or np.isnan(a):
                continue
            entry = float(df["close"].iloc[i])
            fwd = df.iloc[i + 1:i + 1 + horizon]
            run_up = (float(fwd["high"].max()) - entry) / a
            if run_up < move_atr:
                continue          # not a big move, nothing to miss
            if (sym, str(ts.date())) in taken:
                caught += 1
                continue
            missed_n += 1
            reason = why_not(g.loc[ts]) if ts in g.index else "—"
            for part in reason.split("; "):
                blocked.setdefault(part, []).append(run_up)

    ranked = sorted(
        ({"gate": k, "opportunities_blocked": len(v),
          "median_move_atr": round(float(np.median(v)), 2)}
         for k, v in blocked.items()),
        key=lambda r: -r["opportunities_blocked"])
    return {"big_moves_caught": caught, "big_moves_missed": missed_n,
            "capture_rate_pct": round(100 * caught / (caught + missed_n), 1)
            if (caught + missed_n) else 0.0,
            "blocked_by": ranked}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2026-01-01")
    ap.add_argument("--end", default=None)
    ap.add_argument("--universe", default="movers", choices=list(UNIVERSES))
    ap.add_argument("--move-atr", type=float, default=3.0,
                    help="a 'big move' is a run-up of this many ATR")
    args = ap.parse_args(argv)

    symbols = UNIVERSES[args.universe]
    trade_from = pd.Timestamp(args.start, tz="America/New_York")
    fetch_from = (trade_from - pd.Timedelta(days=500)).date().isoformat()

    p = dict(BASE)
    p.update({"fast": 10, "target_r": 3.0, "stop_atr": 0.3, "trail_ema": True,
              "min_slope_atr": 2.0})

    try:
        md = MarketData(Credentials.from_env(), feed="iex")
        log.info("Fetching %d %s symbols", len(symbols), args.universe)
        data = md.daily_bars(symbols, start=fetch_from, end=args.end)
    except AlpacaError as exc:
        log.error("Market data unavailable: %s", exc)
        return 1
    data = {s: d for s, d in data.items() if len(d) > 250}
    if not data:
        log.error("No data.")
        return 1

    prepared = prepare(data, p)
    sigs = signal_times(prepared, p)
    hi = pd.Timestamp(args.end, tz="America/New_York") if args.end \
        else max(d.index[-1] for d in prepared.values()) + pd.Timedelta(days=1)
    res = run_portfolio(prepared, p, sigs=sigs, lo=trade_from, hi=hi)

    payload = {
        "universe": args.universe, "symbols": len(data),
        "start": args.start, "end": args.end,
        "stats": res["stats"],
        "autopsy": autopsy(prepared, res["trades"], p),
        "missed": missed(prepared, sigs, res["trades"], p, trade_from, hi,
                         args.move_atr),
        "worst": sorted(res["trades"], key=lambda t: t["r_multiple"])[:10],
        "best": sorted(res["trades"], key=lambda t: -t["r_multiple"])[:10],
    }
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / f"forensics_{args.universe}.json").write_text(
        json.dumps(payload, indent=2, default=str))
    text = render(payload)
    (REPORTS / f"forensics_{args.universe}.md").write_text(text)
    print("\n" + text)
    return 0


def render(p: dict) -> str:
    s, a, m = p["stats"], p["autopsy"], p["missed"]
    out = [f"# Trade forensics — {p['universe']} universe",
           "",
           f"**{p['symbols']} symbols · from {p['start']} · "
           f"{datetime.now():%Y-%m-%d %H:%M}**",
           "",
           "## Baseline", "",
           f"{s.get('n_trades', 0)} trades · "
           f"{s.get('expectancy_R', 0):+.4f}R expectancy · "
           f"{s.get('win_rate_pct', 0)}% win rate · "
           f"{s.get('max_drawdown_pct', 0)}% max drawdown",
           ""]
    if s.get("n_trades", 0) < 30:
        out.append("_⚠ Fewer than 30 trades. Everything below is suggestive "
                   "only; at this sample size patterns appear by chance._")
        out.append("")

    if a:
        out += ["## Autopsy — do losers differ from winners?", "",
                f"{a['n_wins']} winners vs {a['n_losses']} losers. "
                "**Separation** is the gap between the two groups in pooled "
                "standard deviations: above 0.5 is worth a rule, below 0.2 is "
                "noise.", "",
                "| Condition at entry | Winners | Losers | Separation |",
                "|---|---|---|---|"]
        for f in a["features"]:
            flag = " ⬅" if abs(f["separation"]) >= 0.5 else ""
            out.append(f"| {f['feature']} | {f['winners_median']} | "
                       f"{f['losers_median']} | **{f['separation']:+.2f}**{flag} |")
        strong = [f for f in a["features"] if abs(f["separation"]) >= 0.5]
        out += ["", "**Read:** " + (
            "no condition separates winners from losers by even half a "
            "standard deviation. The entry filter has no more information to "
            "give — adding rules based on these would be fitting noise."
            if not strong else
            "; ".join(f"`{f['feature']}` differs by {f['separation']:+.2f} SD"
                      for f in strong) + ". Worth testing as a rule."), ""]

    if m:
        out += ["## What we missed", "",
                f"Big moves (a run-up of {3.0} ATR within 20 days) in this "
                f"universe and period:", "",
                f"- **Caught:** {m['big_moves_caught']}",
                f"- **Missed:** {m['big_moves_missed']}",
                f"- **Capture rate:** {m['capture_rate_pct']}%", "",
                "### Which gate blocked the moves we missed", "",
                "| Gate | Opportunities blocked | Median move |",
                "|---|---|---|"]
        for b in m["blocked_by"][:8]:
            out.append(f"| {b['gate']} | {b['opportunities_blocked']} | "
                       f"{b['median_move_atr']} ATR |")
        out += ["", "_A gate near the top of this list is expensive. But "
                    "removing it also lets through every move it correctly "
                    "avoided — the autopsy above is what says whether that "
                    "trade is worth making._", ""]

    if p.get("worst"):
        out += ["## Ten worst trades", "",
                "| Symbol | Entry | Exit | R | Reason | Days |",
                "|---|---|---|---|---|---|"]
        for t in p["worst"]:
            out.append(f"| {t['symbol']} | {t['entry_date']} | {t['exit_date']} "
                       f"| {t['r_multiple']:+.2f} | {t['reason']} | "
                       f"{t['bars_held']} |")
        out.append("")
    if p.get("best"):
        out += ["## Ten best trades", "",
                "| Symbol | Entry | Exit | R | Reason | Days |",
                "|---|---|---|---|---|---|"]
        for t in p["best"]:
            out.append(f"| {t['symbol']} | {t['entry_date']} | {t['exit_date']} "
                       f"| {t['r_multiple']:+.2f} | {t['reason']} | "
                       f"{t['bars_held']} |")
    return "\n".join(out)


if __name__ == "__main__":
    raise SystemExit(main())
