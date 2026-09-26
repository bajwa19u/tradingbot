"""Self-improving loop — and an honest test of whether improving helps.

The loop: every `refit_days`, search all configurations over the trailing
`lookback_days`, adopt the winner, and trade it forward until the next refit.
Repeat. The strategy rewrites itself as the market changes.

The catch, and the reason this module measures itself: refitting on what just
worked is performance chasing. A rule set rises to the top of a short window
partly because it suited that window and partly because it got lucky, and the
luck does not repeat. An adaptive system can therefore lose to a dumb static
one while feeling far more sophisticated.

So every forward trade here is genuinely out of sample — chosen by data that
ended before the trade began — and the result is reported next to two
yardsticks:

    STATIC     one fixed configuration traded across the whole span
    HINDSIGHT  the single best configuration for the whole span, which
               nobody could have known in advance - an upper bound

If ADAPTIVE does not beat STATIC, the loop is not worth running, however
clever it looks.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime

import pandas as pd

from .config import REPO_ROOT, Credentials
from .data import AlpacaError, MarketData
from .swing import (
    BASE,
    HOLDOUT,
    RESEARCH,
    grid,
    prepare,
    run_portfolio,
    signal_times,
    summarize,
)

REPORTS = REPO_ROOT / "reports"
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                    stream=sys.stdout)
log = logging.getLogger("adaptive")


def score_window(cache: dict, p_name: str, p: dict, lo, hi) -> dict:
    """Run one config over one window, reusing prepared frames."""
    prepared, sigs = cache[p_name]
    return run_portfolio(prepared, p, sigs=sigs, lo=lo, hi=hi)


def build_cache(data: dict, configs: list[tuple[str, dict]]) -> dict:
    """Indicators depend on the config, so prepare once per config, not per
    window. Without this the walk-forward would recompute everything at every
    refit and take hours."""
    cache = {}
    for name, p in configs:
        prepared = prepare(data, p)
        cache[name] = (prepared, signal_times(prepared, p))
    return cache


def walk_forward(data: dict, configs: list[tuple[str, dict]], days: list,
                 lookback: int, refit: int, min_trades: int) -> dict:
    """Refit, trade forward, repeat. Returns the adaptive record plus the log
    of what it chose and why."""
    cache = build_cache(data, configs)
    trades, choices = [], []
    i = lookback
    while i < len(days):
        fit_lo, fit_hi = days[i - lookback], days[i]
        fwd_lo = days[i]
        fwd_hi = days[min(i + refit, len(days) - 1)]
        if fwd_hi <= fwd_lo:
            break

        # --- fit: score every config on data that ends before fwd_lo -------
        ranked = []
        for name, p in configs:
            st = score_window(cache, name, p, fit_lo, fit_hi)["stats"]
            if st["n_trades"] >= min_trades:
                ranked.append((st["expectancy_R"], st["n_trades"], name, p))
        if not ranked:
            i += refit
            continue
        ranked.sort(reverse=True)
        exp, n, name, p = ranked[0]

        # --- trade it forward ---------------------------------------------
        fwd = score_window(cache, name, p, fwd_lo, fwd_hi)
        trades.extend(fwd["trades"])
        choices.append({
            "refit_date": str(fwd_lo.date()),
            "chose": name,
            "fit_expectancy_R": exp,
            "fit_trades": n,
            "forward_trades": fwd["stats"]["n_trades"],
            "forward_expectancy_R": fwd["stats"].get("expectancy_R", 0.0),
        })
        log.info("  %s  fit picked %-34s (%.3fR on %d) -> forward %.3fR on %d",
                 fwd_lo.date(), name, exp, n,
                 fwd["stats"].get("expectancy_R", 0.0), fwd["stats"]["n_trades"])
        i += refit

    return {"trades": trades, "choices": choices}


def stats_from(trade_dicts: list[dict]) -> dict:
    """Recompute headline stats from raw trade dicts."""
    if not trade_dicts:
        return {"n_trades": 0, "expectancy_R": 0.0, "total_R": 0.0,
                "win_rate_pct": 0.0, "max_drawdown_pct": 0.0}
    import numpy as np
    r = np.array([t["r_multiple"] for t in trade_dicts])
    eq, curve = 10000.0, []
    for x in r:
        eq *= (1 + 0.01 * x)
        curve.append(eq)
    curve = np.array(curve)
    peak = np.maximum.accumulate(np.concatenate([[10000.0], curve]))
    dd = (np.concatenate([[10000.0], curve]) - peak) / peak
    return {"n_trades": len(r),
            "expectancy_R": round(float(r.mean()), 4),
            "total_R": round(float(r.sum()), 1),
            "win_rate_pct": round(100 * float((r > 0).mean()), 1),
            "max_drawdown_pct": round(100 * float(dd.min()), 2),
            "return_pct": round(100 * (float(curve[-1]) / 10000 - 1), 1)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2024-01-01",
                    help="first date the adaptive loop may trade")
    ap.add_argument("--end", default=None)
    ap.add_argument("--lookback", type=int, default=252,
                    help="trading days of history each refit fits on")
    ap.add_argument("--refit", type=int, default=21,
                    help="trading days between refits")
    ap.add_argument("--min-trades", type=int, default=30,
                    help="a config needs this many trades in the fit window "
                         "to be eligible - the guard against picking a config "
                         "that got lucky on five trades")
    ap.add_argument("--universe", default="research",
                    choices=["research", "holdout"])
    args = ap.parse_args(argv)

    symbols = RESEARCH if args.universe == "research" else HOLDOUT
    trade_from = pd.Timestamp(args.start, tz="America/New_York")
    fetch_from = (trade_from - pd.Timedelta(days=int(args.lookback * 1.6) + 500)
                  ).date().isoformat()

    try:
        md = MarketData(Credentials.from_env(), feed="iex")
        log.info("Fetching %d %s symbols from %s", len(symbols), args.universe,
                 fetch_from)
        data = md.daily_bars(symbols, start=fetch_from, end=args.end)
    except AlpacaError as exc:
        log.error("Market data unavailable: %s", exc)
        return 1
    data = {s: d for s, d in data.items() if len(d) > 300}
    if not data:
        log.error("No data.")
        return 1

    configs = grid()
    all_days = sorted({d for df in data.values() for d in df.index})
    # the loop may only trade from --start; earlier bars are fitting material
    start_idx = next((i for i, d in enumerate(all_days) if d >= trade_from), None)
    if start_idx is None or start_idx < args.lookback:
        log.error("Not enough history before %s for a %d-day lookback.",
                  args.start, args.lookback)
        return 1
    days = all_days[start_idx - args.lookback:]

    log.info("Walk-forward: %d configs, %d-day lookback, refit every %d days",
             len(configs), args.lookback, args.refit)
    wf = walk_forward(data, configs, days, args.lookback, args.refit,
                      args.min_trades)
    adaptive = stats_from(wf["trades"])

    # --- yardsticks --------------------------------------------------------
    span_lo, span_hi = days[args.lookback], days[-1]
    cache = build_cache(data, configs)
    static_p = dict(BASE)
    static_p.update({"fast": 10, "target_r": 3.0, "stop_atr": 0.3,
                     "trail_ema": True, "min_slope_atr": 2.0})
    static_name = "ema10_tgt3.0_stop0.3_slope2.0"
    static = score_window(cache, static_name, static_p, span_lo, span_hi)["stats"] \
        if static_name in cache else {"n_trades": 0}

    best_hindsight, best_name = None, ""
    for name, p in configs:
        st = score_window(cache, name, p, span_lo, span_hi)["stats"]
        if st["n_trades"] >= 40 and (best_hindsight is None
                                     or st["expectancy_R"] > best_hindsight["expectancy_R"]):
            best_hindsight, best_name = st, name

    payload = {"universe": args.universe, "symbols": len(data),
               "start": args.start, "end": args.end,
               "lookback": args.lookback, "refit": args.refit,
               "adaptive": adaptive, "choices": wf["choices"],
               "static": static, "static_name": static_name,
               "hindsight": best_hindsight, "hindsight_name": best_name}
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / f"adaptive_{args.universe}.json").write_text(
        json.dumps(payload, indent=2, default=str))
    text = render(payload)
    (REPORTS / f"adaptive_{args.universe}.md").write_text(text)
    print("\n" + text)
    return 0


def render(p: dict) -> str:
    a, s, h = p["adaptive"], p["static"], p["hindsight"]
    out = [
        f"# Self-improving loop — {p['universe']} universe",
        "",
        f"**Symbols:** {p['symbols']} · **From:** {p['start']} · "
        f"**Refits:** every {p['refit']} trading days on a {p['lookback']}-day "
        "lookback  ",
        f"**Generated:** {datetime.now():%Y-%m-%d %H:%M}",
        "",
        "Every ADAPTIVE trade was chosen by data that ended before the trade "
        "began. Nothing here is fitted to the trades it is judged on.",
        "",
        "| | Trades | Expectancy | Total R | Win % | Max DD |",
        "|---|---|---|---|---|---|",
        f"| **ADAPTIVE** (refits itself) | {a['n_trades']} | "
        f"**{a['expectancy_R']:+.4f}R** | {a['total_R']:+.1f} | "
        f"{a['win_rate_pct']} | {a['max_drawdown_pct']}% |",
    ]
    if s.get("n_trades"):
        out.append(f"| STATIC (`{p['static_name']}`, never changes) | "
                   f"{s['n_trades']} | {s['expectancy_R']:+.4f}R | "
                   f"{s['total_R']:+.1f} | {s.get('win_rate_pct','—')} | "
                   f"{s['max_drawdown_pct']}% |")
    if h:
        out.append(f"| HINDSIGHT (`{p['hindsight_name']}`, unknowable at the "
                   f"time) | {h['n_trades']} | {h['expectancy_R']:+.4f}R | "
                   f"{h['total_R']:+.1f} | {h.get('win_rate_pct','—')} | "
                   f"{h['max_drawdown_pct']}% |")

    out += ["", "## Does refitting help?", ""]
    if s.get("n_trades"):
        gap = a["expectancy_R"] - s["expectancy_R"]
        if gap > 0.02:
            out.append(f"**Yes — adaptive beat static by {gap:+.4f}R per trade.** "
                       "Refitting earned its complexity here.")
        elif gap < -0.02:
            out.append(f"**No — adaptive LOST to static by {gap:+.4f}R per "
                       "trade.** The loop chased configurations that had just "
                       "had a good run and then stopped working. This is the "
                       "expected failure of performance chasing, and it is the "
                       "reason to measure it rather than assume it.")
        else:
            out.append(f"**No meaningful difference ({gap:+.4f}R).** The extra "
                       "machinery bought nothing.")
    out += ["", "_HINDSIGHT is what the best fixed config would have returned "
                "if you had known in advance which one it was. It is not "
                "achievable; it is there to show how much of the gap is "
                "foresight rather than method._", "",
            "## What it chose, and what happened next", "",
            "| Refit | Chose | Fit expectancy | Forward expectancy | Forward trades |",
            "|---|---|---|---|---|"]
    for c in p["choices"]:
        out.append(f"| {c['refit_date']} | `{c['chose']}` | "
                   f"{c['fit_expectancy_R']:+.3f}R | "
                   f"**{c['forward_expectancy_R']:+.3f}R** | "
                   f"{c['forward_trades']} |")
    out += ["", "_The gap between the fit column and the forward column is the "
                "cost of selection. If fit is consistently high and forward "
                "consistently low, the search is finding noise._"]
    return "\n".join(out)


if __name__ == "__main__":
    raise SystemExit(main())
