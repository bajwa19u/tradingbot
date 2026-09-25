"""Wide search with a locked holdout.

The method, and the reason for each step:

  1. RESEARCH SET — four symbols, recent period. Every strategy family and
     every parameter combination is scored here, across several consecutive
     market periods.

  2. SELECTION — one configuration is chosen, by a rule fixed in advance:
     profitable overall, positive in all but at most one period, at least
     100 trades. Among those, the winner is the one with the best WORST
     period, not the best total. Robustness, not return.

  3. HOLDOUT — that single configuration is run once against data the search
     never touched: different symbols AND an earlier period. One shot. No
     going back to step 2 if the answer is disappointing, because doing that
     turns the holdout into just more training data.

The count of configurations tried is reported alongside the result, because
it is the number that tells you how impressed to be. Search 100 things and
the best one looks good by luck alone; that is arithmetic, not pessimism.
"""
from __future__ import annotations

import argparse
import copy
import itertools
import json
import logging
import sys
from datetime import datetime

import pandas as pd

from .backtest import Backtester
from .config import REPO_ROOT, Credentials, Section, load_config
from .data import AlpacaError, MarketData
from .indicators import resample_bars

REPORTS = REPO_ROOT / "reports"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                    stream=sys.stdout)
log = logging.getLogger("discover")

# Kept apart from the research set on both axes: different companies, and an
# earlier stretch of market history.
HOLDOUT_SYMBOLS = ["META", "AMZN", "GOOGL", "MSFT"]
HOLDOUT_START = "2022-06-01"
HOLDOUT_END = "2024-05-31"


def deep_merge(base: dict, extra: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in extra.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _grid(**axes):
    """Cartesian product of named axes -> list of flat dicts."""
    keys = list(axes)
    return [dict(zip(keys, combo)) for combo in itertools.product(*axes.values())]


def candidates() -> list[tuple[str, dict]]:
    """(name, config-overrides) for everything the search will try."""
    out: list[tuple[str, dict]] = []

    def add(family: str, label: str, overrides: dict):
        for style in ("fixed", "momentum"):
            o = deep_merge(overrides, {"risk": {"exit_style": style}})
            o = deep_merge(o, {"strategy": {"name": family}})
            out.append((f"{family}/{label}/{style}", o))

    # --- break & retest -----------------------------------------------------
    for g in _grid(vol=[1.0, 1.3, 1.8], disp=[0.0, 0.15, 0.30],
                   until=["11:00", "14:30"]):
        add("break_retest",
            f"vol{g['vol']}_disp{g['disp']}_to{g['until']}",
            {"strategy": {
                "session": {"opening_range_minutes": 5,
                            "no_entries_before": "09:35",
                            "no_entries_after": g["until"]},
                "breakout": {"volume_multiple": g["vol"],
                             "min_range_atr_multiple": 0.03,
                             "max_range_atr_multiple": 0.45},
                "retest": {"min_displacement_atr": g["disp"]},
                "filters": {"max_trades_per_day": 2,
                            "stop_after_first_win": True}}})

    # --- ema pullback -------------------------------------------------------
    for g in _grid(fast=[9, 20], slow=[50, 100], slope=[0.05, 0.15, 0.25]):
        add("ema_pullback",
            f"ema{g['fast']}x{g['slow']}_slope{g['slope']}",
            {"strategy": {
                "session": {"no_entries_before": "10:00",
                            "no_entries_after": "15:00"},
                "ema_pullback": {"fast_ema": g["fast"], "slow_ema": g["slow"],
                                 "min_slope_atr": g["slope"]},
                "filters": {"max_trades_per_day": 4,
                            "max_trades_per_symbol_per_day": 2,
                            "stop_after_first_win": False}}})

    # --- vwap reversion -----------------------------------------------------
    for g in _grid(stretch=[0.25, 0.35, 0.50], stop=[0.10, 0.20]):
        add("vwap_reversion",
            f"stretch{g['stretch']}_stop{g['stop']}",
            {"strategy": {
                "session": {"no_entries_before": "10:00",
                            "no_entries_after": "15:00"},
                "vwap_reversion": {"stretch_atr": g["stretch"],
                                   "stop_atr": g["stop"]},
                "filters": {"max_trades_per_day": 4,
                            "max_trades_per_symbol_per_day": 2,
                            "require_vwap_alignment": False,
                            "stop_after_first_win": False}}})

    # --- plain opening-range break (the control) ----------------------------
    for g in _grid(orm=[5, 15, 30], stop=[0.15, 0.30]):
        add("orb_simple",
            f"or{g['orm']}_stop{g['stop']}",
            {"strategy": {
                "session": {"no_entries_before": "09:35",
                            "no_entries_after": "11:00"},
                "orb_simple": {"or_minutes": g["orm"], "stop_atr": g["stop"]},
                "filters": {"max_trades_per_day": 2,
                            "require_vwap_alignment": False,
                            "stop_after_first_win": False}}})

    # --- rsi extremes -------------------------------------------------------
    for g in _grid(os=[20, 25, 30], swing=[3, 5]):
        add("rsi_extreme",
            f"rsi{g['os']}_swing{g['swing']}",
            {"strategy": {
                "session": {"no_entries_before": "10:00",
                            "no_entries_after": "15:00"},
                "rsi_extreme": {"oversold": g["os"], "overbought": 100 - g["os"],
                                "swing_lookback": g["swing"]},
                "filters": {"max_trades_per_day": 4,
                            "max_trades_per_symbol_per_day": 2,
                            "require_vwap_alignment": False,
                            "stop_after_first_win": False}}})

    # --- momentum breakout --------------------------------------------------
    for g in _grid(lb=[6, 12, 24], vol=[1.2, 1.5, 2.0]):
        add("momentum_breakout",
            f"lb{g['lb']}_vol{g['vol']}",
            {"strategy": {
                "session": {"no_entries_before": "10:00",
                            "no_entries_after": "15:00"},
                "momentum_breakout": {"lookback": g["lb"],
                                      "volume_multiple": g["vol"]},
                "filters": {"max_trades_per_day": 4,
                            "max_trades_per_symbol_per_day": 2,
                            "require_vwap_alignment": False,
                            "stop_after_first_win": False}}})
    return out


def score(cfg_dict: dict, bars: dict, daily: dict, edges: list) -> dict:
    """Run one configuration across each period and aggregate."""
    bt = Backtester(Section(cfg_dict))
    per_period, total_n, total_R, worst_dd = [], 0, 0.0, 0.0
    for i in range(len(edges) - 1):
        lo, hi = edges[i], edges[i + 1]
        sl = {s: d[(d.index.normalize() >= lo) & (d.index.normalize() < hi)]
              for s, d in bars.items()}
        st = bt.run(sl, daily)["stats"]
        per_period.append({"n": st.get("n_trades", 0),
                           "expectancy_R": st.get("expectancy_R", 0.0)})
        total_n += st.get("n_trades", 0)
        total_R += st.get("total_R", 0.0)
        worst_dd = min(worst_dd, st.get("max_drawdown_pct", 0.0))
    scored = [p for p in per_period if p["n"] >= 5]
    return {
        "n": total_n,
        "expectancy_R": round(total_R / total_n, 4) if total_n else 0.0,
        "total_R": round(total_R, 1),
        "periods_positive": sum(1 for p in scored if p["expectancy_R"] > 0),
        "periods_scored": len(scored),
        "worst_period_R": round(min((p["expectancy_R"] for p in scored),
                                    default=0.0), 4),
        "max_dd_pct": round(worst_dd, 2),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2024-06-01")
    ap.add_argument("--end", default=None)
    ap.add_argument("--symbols", default="TSLA,NVDA,AAPL,AMD")
    ap.add_argument("--timeframe", type=int, default=5)
    ap.add_argument("--periods", type=int, default=4)
    ap.add_argument("--min-trades", type=int, default=100)
    args = ap.parse_args(argv)

    base = load_config()
    creds = Credentials.from_env()
    research = [s.strip().upper() for s in args.symbols.split(",")]
    tf = args.timeframe

    overlap = set(research) & set(HOLDOUT_SYMBOLS)
    if overlap:
        log.error("Research and holdout symbols overlap (%s). That would "
                  "invalidate the whole exercise.", ", ".join(sorted(overlap)))
        return 1

    try:
        md = MarketData(creds, feed=base.backtest.bar_feed)
        log.info("Research set: %s from %s", ", ".join(research), args.start)
        r_bars = md.intraday_bars(research, tf, start=args.start, end=args.end)
        r_daily = md.daily_bars(research, start=args.start, end=args.end)
    except AlpacaError as exc:
        log.error("Market data unavailable: %s", exc)
        return 1

    r_bars = {s: d for s, d in r_bars.items() if len(d)}
    if not r_bars:
        log.error("No research data returned.")
        return 1

    days = sorted({d for df in r_bars.values() for d in df.index.normalize().unique()})
    n_per = args.periods
    edges = [days[int(len(days) * i / n_per)] for i in range(n_per)]
    edges.append(days[-1] + pd.Timedelta(days=1))
    log.info("%d trading days, %d periods", len(days), n_per)

    todo = candidates()
    log.info("Scoring %d configurations...", len(todo))
    results = []
    for i, (name, ov) in enumerate(todo, 1):
        cfg_dict = deep_merge(dict(base), ov)
        cfg_dict["strategy"]["timeframe_minutes"] = tf
        try:
            st = score(cfg_dict, r_bars, r_daily, edges)
        except Exception as exc:  # noqa: BLE001
            log.warning("  %s failed: %s", name, exc)
            continue
        st["name"] = name
        st["overrides"] = ov
        results.append(st)
        if i % 10 == 0 or i == len(todo):
            log.info("  %d/%d done", i, len(todo))

    # --- selection rule, fixed before looking -------------------------------
    survivors = [r for r in results
                 if r["expectancy_R"] > 0
                 and r["periods_scored"] >= max(2, n_per - 1)
                 and r["periods_positive"] >= r["periods_scored"] - 1
                 and r["n"] >= args.min_trades]
    survivors.sort(key=lambda r: (-r["worst_period_R"], -r["expectancy_R"]))

    holdout_result = None
    winner = survivors[0] if survivors else None
    if winner:
        log.info("Winner: %s — now the single holdout run", winner["name"])
        try:
            h_bars = md.intraday_bars(HOLDOUT_SYMBOLS, tf,
                                      start=HOLDOUT_START, end=HOLDOUT_END)
            h_daily = md.daily_bars(HOLDOUT_SYMBOLS,
                                    start=HOLDOUT_START, end=HOLDOUT_END)
            h_bars = {s: d for s, d in h_bars.items() if len(d)}
            if h_bars:
                hdays = sorted({d for df in h_bars.values()
                                for d in df.index.normalize().unique()})
                hedges = [hdays[int(len(hdays) * i / n_per)] for i in range(n_per)]
                hedges.append(hdays[-1] + pd.Timedelta(days=1))
                cfg_dict = deep_merge(dict(base), winner["overrides"])
                cfg_dict["strategy"]["timeframe_minutes"] = tf
                holdout_result = score(cfg_dict, h_bars, h_daily, hedges)
            else:
                log.warning("Holdout returned no data.")
        except AlpacaError as exc:
            log.warning("Holdout fetch failed: %s", exc)

    REPORTS.mkdir(exist_ok=True)
    payload = {"tried": len(todo), "scored": len(results),
               "survivors": len(survivors),
               "results": sorted(results, key=lambda r: -r["expectancy_R"])[:40],
               "winner": winner, "holdout": holdout_result}
    (REPORTS / "discovery.json").write_text(json.dumps(payload, indent=2, default=str))
    text = render(payload, research, args, tf)
    (REPORTS / "discovery.md").write_text(text)
    print("\n" + text)
    return 0


def render(p: dict, research, args, tf) -> str:
    out = [
        "# Wide search",
        "",
        f"**Research set:** {', '.join(research)} · {args.start} → "
        f"{args.end or 'today'} · {tf}-minute  ",
        f"**Locked holdout:** {', '.join(HOLDOUT_SYMBOLS)} · "
        f"{HOLDOUT_START} → {HOLDOUT_END} — untouched until the end  ",
        f"**Generated:** {datetime.now():%Y-%m-%d %H:%M}",
        "",
        f"**{p['tried']} configurations tried** across 6 strategy families. "
        f"{p['survivors']} passed the selection rule.",
        "",
        "> Search enough configurations and the best one looks good by luck. "
        f"With {p['tried']} tries, expect roughly "
        f"{max(1, int(p['tried'] * 0.05))} to clear a 1-in-20 bar on noise "
        "alone. That is why the holdout below is the only number that counts.",
        "",
        "## Top 15 on the research set",
        "",
        "| Configuration | Trades | Expectancy | Positive in | Worst period | Max DD |",
        "|---|---|---|---|---|---|",
    ]
    for r in p["results"][:15]:
        warn = "" if r["n"] >= 100 else " ⚠"
        out.append(f"| `{r['name']}` | {r['n']}{warn} | {r['expectancy_R']:+.3f}R | "
                   f"{r['periods_positive']}/{r['periods_scored']} | "
                   f"{r['worst_period_R']:+.3f}R | {r['max_dd_pct']}% |")

    out += ["", "## The one that was selected", ""]
    w, h = p.get("winner"), p.get("holdout")
    if not w:
        out += ["**Nothing passed the selection rule.**", "",
                "No configuration was profitable overall while staying positive "
                "across periods on 100+ trades. The holdout was not touched, so "
                "it stays clean for a future attempt.", "",
                "Six families, dozens of parameter sets each, and none of them "
                "held up. That is a real answer: these setups, on these "
                "symbols, at this timeframe, after costs, do not have an edge.",
                "", "Worth trying next, in rough order of promise:", "",
                "1. A longer horizon. Intraday is the most competitive corner "
                "of the market; daily and weekly holding periods face far less "
                "sophisticated competition.",
                "2. Different instruments — the forex pairs you actually trade "
                "are not in this dataset at all.",
                "3. Better data. Free IEX covers a fraction of real volume, so "
                "every volume filter here is working from a sample."]
        return "\n".join(out)

    out += [f"**`{w['name']}`**", "",
            "| | Research set | **Holdout (never seen)** |",
            "|---|---|---|",
            f"| Trades | {w['n']} | **{h['n'] if h else 'n/a'}** |",
            f"| Expectancy | {w['expectancy_R']:+.3f}R | "
            f"**{h['expectancy_R']:+.3f}R**" if h else "| Expectancy | "
            f"{w['expectancy_R']:+.3f}R | n/a |",
            ]
    if h:
        out += [f"| Total R | {w['total_R']:+.1f} | **{h['total_R']:+.1f}** |",
                f"| Positive in | {w['periods_positive']}/{w['periods_scored']} | "
                f"**{h['periods_positive']}/{h['periods_scored']}** |",
                f"| Max drawdown | {w['max_dd_pct']}% | **{h['max_dd_pct']}%** |"]
        out += ["", "### Verdict", ""]
        strong = (h["expectancy_R"] >= 0.05 and h["n"] >= 100
                  and h["periods_positive"] >= h["periods_scored"] - 1)
        weak = h["expectancy_R"] > 0 and h["n"] >= 50
        if weak and not strong:
            out += ["**Positive on the holdout, but too small to trade.**", "",
                    f"Expectancy of {h['expectancy_R']:+.3f}R means about "
                    f"{abs(h['expectancy_R']) * 20:.2f} cents per trade if you "
                    f"risk $20 - roughly ${h['expectancy_R'] * h['n'] * 20:.0f} "
                    f"across all {h['n']} holdout trades. Commissions, wider "
                    "real spreads, or one missed fill erases it.", "",
                    f"It was also positive in only {h['periods_positive']} of "
                    f"{h['periods_scored']} holdout periods, which is close to "
                    "a coin flip.", "",
                    "The right conclusion is not 'it works, trade it smaller'. "
                    "It is that the search did not find an edge worth having, "
                    "and the holdout confirmed the absence rather than a "
                    "presence. Nothing here justifies risking money."]
        elif strong:
            out += ["**It held up on data it had never seen.**", "",
                    "That is the strongest result this process can produce, and "
                    "it is still not a guarantee. Next steps, in order: paper "
                    "trade the live signals for at least three months; compare "
                    "the paper fills against what the backtest predicted; only "
                    "then consider money, at a size where being wrong is "
                    "survivable.", "",
                    "Do not re-tune on the holdout. It has been spent."]
        else:
            out += ["**It did not survive the holdout.**", "",
                    "It looked good on the research set and fell apart on data "
                    "it had not seen. That is the signature of a curve fit, and "
                    "it is exactly what the holdout exists to catch — this "
                    "result just saved you from trading it.", "",
                    "Note what did NOT happen here: nobody went back and picked "
                    "the second-best configuration to try instead. That would "
                    "turn the holdout into training data and the honesty of the "
                    "whole exercise with it."]
    return "\n".join(out)


if __name__ == "__main__":
    raise SystemExit(main())
