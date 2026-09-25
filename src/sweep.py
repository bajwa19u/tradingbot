"""Parameter sweep — test many rule sets against the same data in one run.

Fetches 1-minute bars once, resamples them to each timeframe locally, then
runs every variant through the identical backtest engine. That makes the
comparison fair: same bars, same slippage, same sizing, only the rules differ.

Variants are defined one-factor-at-a-time against a faithful baseline, so the
output says what each individual rule is worth rather than just which blob of
settings happened to win.

    python -m src.sweep
    python -m src.sweep --start 2025-01-01 --symbols TSLA,NVDA,AAPL,AMD
"""
from __future__ import annotations

import argparse
import copy
import json
import math
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
log = logging.getLogger("sweep")


# ---------------------------------------------------------------------------
# The rule sets under test
# ---------------------------------------------------------------------------
# Faithful to the published methodology: 5-minute opening range built from the
# FIRST 5-minute candle, entries only 09:30-11:00, displacement required before
# the retest counts, two attempts per session, done after one winner.
FAITHFUL = {
    "strategy": {
        "session": {"opening_range_minutes": 5, "no_entries_before": "09:35",
                    "no_entries_after": "11:00", "flatten_at": "15:55"},
        "retest": {"min_displacement_atr": 0.15},
        # A 5-minute opening range is a single bar and is naturally far
        # narrower than a 15-minute one, so the width window must move with it.
        "breakout": {"min_range_atr_multiple": 0.03, "max_range_atr_multiple": 0.45},
        "filters": {"max_trades_per_day": 2, "stop_after_first_win": True,
                    "max_trades_per_symbol_per_day": 1},
    },
}


def variants() -> dict[str, dict]:
    """name -> config overrides (deep-merged onto config.yaml)."""
    def with_faithful(extra: dict | None = None) -> dict:
        base = copy.deepcopy(FAITHFUL)
        if extra:
            base = deep_merge(base, extra)
        return base

    return {
        # what we have been running
        "current-rules": {},

        # the published method
        "faithful": with_faithful(),

        # one factor at a time, each relaxed FROM faithful, to price the rule
        "faithful +late-entries": with_faithful(
            {"strategy": {"session": {"no_entries_after": "14:30"}}}),
        "faithful +15min-range": with_faithful(
            {"strategy": {"session": {"opening_range_minutes": 15,
                                      "no_entries_before": "09:45"}}}),
        "faithful -displacement": with_faithful(
            {"strategy": {"retest": {"min_displacement_atr": 0.0}}}),
        "faithful -stop-after-win": with_faithful(
            {"strategy": {"filters": {"stop_after_first_win": False,
                                      "max_trades_per_day": 4}}}),
        "faithful +shorts-off": with_faithful(
            {"strategy": {"filters": {"trade_shorts": False}}}),
        "faithful +3R-target": with_faithful({"risk": {"reward_multiple": 3.0}}),
        "faithful +no-breakeven": with_faithful({"risk": {"breakeven_after_1R": False}}),
        "faithful +loose-volume": with_faithful(
            {"strategy": {"breakout": {"volume_multiple": 1.0}}}),
        "faithful +partial-at-1R": with_faithful({"risk": {"partial_at_1R": True}}),
        "faithful +tight-window": with_faithful(
            {"strategy": {"session": {"no_entries_after": "10:30"}}}),
        "faithful +fast-retest-only": with_faithful(
            {"strategy": {"retest": {"max_bars_after_break": 4}}}),
        "faithful +strong-volume": with_faithful(
            {"strategy": {"breakout": {"volume_multiple": 1.8}}}),
    }


def deep_merge(base: dict, extra: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = value
    return out


# ---------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2025-01-01")
    parser.add_argument("--end", default=None)
    parser.add_argument("--symbols", default="TSLA,NVDA,AAPL,AMD")
    parser.add_argument("--timeframes", default="1,2,5")
    parser.add_argument("--periods", type=int, default=5)
    args = parser.parse_args(argv)

    cfg = load_config()
    creds = Credentials.from_env()
    symbols = [s.strip().upper() for s in args.symbols.split(",")]
    timeframes = [int(t) for t in args.timeframes.split(",")]

    log.info("Fetching 1-minute bars for %s from %s", ", ".join(symbols), args.start)
    try:
        md = MarketData(creds, feed=cfg.backtest.bar_feed)
        minute = md.intraday_bars(symbols, 1, start=args.start, end=args.end)
        daily = md.daily_bars(symbols, start=args.start, end=args.end)
    except AlpacaError as exc:
        log.error("Market data unavailable: %s", exc)
        return 1

    total_bars = sum(len(df) for df in minute.values())
    log.info("Got %d one-minute bars", total_bars)
    if total_bars == 0:
        log.error("No data returned — nothing to sweep.")
        return 1

    # Resample once per timeframe, reuse across every variant
    by_tf: dict[int, dict[str, pd.DataFrame]] = {}
    for tf in timeframes:
        by_tf[tf] = {
            sym: (df if tf == 1 else resample_bars(df, tf))
            for sym, df in minute.items() if len(df)
        }
        log.info("timeframe %dm: %d bars",
                 tf, sum(len(d) for d in by_tf[tf].values()))

    # A single train/test split cannot separate "these rules work" from
    # "the holdout happened to be an easy market". Splitting the period into
    # N consecutive chunks and scoring each one does: a rule set that is
    # positive in 4 of 5 different market regimes is credible, one that is
    # positive only in the last chunk is a passenger on a good period.
    n_periods = args.periods
    all_days = sorted({d for df in minute.values() if len(df)
                       for d in df.index.normalize().unique()})
    if len(all_days) < 20 * n_periods:
        log.error("Only %d trading days for %d periods - use a longer range.",
                  len(all_days), n_periods)
        return 1
    edges = [all_days[int(len(all_days) * i / n_periods)] for i in range(n_periods)]
    edges.append(all_days[-1] + pd.Timedelta(days=1))
    log.info("Testing %d periods: %s", n_periods,
             ", ".join(f"{edges[i].date()}→{edges[i+1].date()}"
                       for i in range(n_periods)))

    def period_slice(frames: dict, i: int) -> dict:
        lo, hi = edges[i], edges[i + 1]
        return {sym: df[(df.index.normalize() >= lo) & (df.index.normalize() < hi)]
                for sym, df in frames.items()}

    rows = []
    for tf in timeframes:
        for name, overrides in variants().items():
            variant_cfg = Section(deep_merge(dict(cfg), overrides))
            variant_cfg["strategy"]["timeframe_minutes"] = tf
            # The opening range must be a whole number of bars. Round UP to
            # the nearest bar rather than dropping the variant, so every rule
            # set is represented at every timeframe.
            orm = variant_cfg["strategy"]["session"]["opening_range_minutes"]
            variant_cfg["strategy"]["session"]["opening_range_minutes"] = \
                int(math.ceil(orm / tf) * tf)
            per_period, total_n, total_R, worst_dd = [], 0, 0.0, 0.0
            failed = False
            for i in range(n_periods):
                try:
                    res = Backtester(variant_cfg).run(period_slice(by_tf[tf], i), daily)
                except Exception as exc:  # noqa: BLE001
                    log.warning("  %s @ %dm period %d failed: %s", name, tf, i, exc)
                    failed = True
                    break
                st = res["stats"]
                per_period.append({"n": st.get("n_trades", 0),
                                   "expectancy_R": st.get("expectancy_R", 0.0)})
                total_n += st.get("n_trades", 0)
                total_R += st.get("total_R", 0.0)
                worst_dd = min(worst_dd, st.get("max_drawdown_pct", 0.0))
            if failed:
                continue
            scored = [p for p in per_period if p["n"] >= 5]
            positive = sum(1 for p in scored if p["expectancy_R"] > 0)
            overall = (total_R / total_n) if total_n else 0.0
            rows.append({
                "timeframe": f"{tf}m",
                "variant": name,
                "n": total_n,
                "expectancy_R": round(overall, 3),
                "total_R": round(total_R, 1),
                "periods_positive": positive,
                "periods_scored": len(scored),
                "worst_period_R": round(min((p["expectancy_R"] for p in scored),
                                            default=0.0), 3),
                "max_dd_pct": round(worst_dd, 2),
                "per_period": per_period,
            })
            log.info("  %-28s @ %2dm  n=%-4d exp=%+.3fR  positive in %d/%d periods",
                     name, tf, total_n, overall, positive, len(scored))

    REPORTS.mkdir(exist_ok=True)
    (REPORTS / "sweep.json").write_text(json.dumps(rows, indent=2, default=str))
    (REPORTS / "sweep.md").write_text(render(rows, symbols, args.start, args.end))
    print("\n" + render(rows, symbols, args.start, args.end))
    return 0


def render(rows: list[dict], symbols, start, end) -> str:
    out = [
        "# Rule sweep — consistency across market periods",
        "",
        f"**Symbols:** {', '.join(symbols)}  ",
        f"**Period:** {start} → {end or 'today'}  ",
        f"**Generated:** {datetime.now():%Y-%m-%d %H:%M}",
        "",
        "The period is cut into consecutive chunks and every rule set is "
        "scored in each one separately. **Consistency is the column that "
        "matters.** A rule set that only works in one chunk was carried by "
        "that market, not by its rules.",
        "",
        "| TF | Variant | Trades | Expectancy | Total R | **Positive in** | "
        "Worst period | Max DD |",
        "|---|---|---|---|---|---|---|---|",
    ]
    ranked = sorted(rows, key=lambda r: (-r.get("periods_positive", 0),
                                         -r["expectancy_R"]))
    for r in ranked:
        warn = "" if r["n"] >= 100 else " ⚠"
        out.append(
            f"| {r['timeframe']} | {r['variant']} | {r['n']}{warn} | "
            f"{r['expectancy_R']:+.3f}R | {r['total_R']:+.1f} | "
            f"**{r.get('periods_positive',0)}/{r.get('periods_scored',0)}** | "
            f"{r.get('worst_period_R',0):+.3f}R | {r['max_dd_pct']}% |")

    survivors = [r for r in ranked
                 if r["expectancy_R"] > 0
                 and r.get("periods_scored", 0) >= 4
                 and r.get("periods_positive", 0) >= r.get("periods_scored", 0) - 1
                 and r["n"] >= 100]
    out += ["", "## Verdict", ""]
    if survivors:
        out += [f"**{len(survivors)} rule set(s) were profitable overall AND "
                f"positive in all but at most one period, on 100+ trades.**", ""]
        for r in survivors:
            out.append(f"- `{r['variant']}` @ {r['timeframe']} — "
                       f"{r['expectancy_R']:+.3f}R over {r['n']} trades, "
                       f"positive in {r['periods_positive']}/"
                       f"{r['periods_scored']} periods, worst "
                       f"{r['worst_period_R']:+.3f}R, max DD {r['max_dd_pct']}%")
        out += ["",
                "That is the strongest evidence a backtest can give, and it is "
                "still not proof. Before money: re-run on symbols not in this "
                "list, confirm the drawdown is one you could sit through, and "
                "paper-trade the live signals for several months. Free IEX data "
                "understates volume, so the volume filter behaves differently "
                "live than it does here."]
    else:
        best = ranked[0] if ranked else None
        out += ["**No rule set was profitable overall while staying positive "
                "across periods on an adequate sample.**", ""]
        if best:
            out.append(f"Closest was `{best['variant']}` @ {best['timeframe']}: "
                       f"{best['expectancy_R']:+.3f}R over {best['n']} trades, "
                       f"positive in {best.get('periods_positive',0)}/"
                       f"{best.get('periods_scored',0)} periods.")
        out += ["",
                "This is a result, not a failure of the test. Honest options:",
                "",
                "1. Different symbols or a longer history — the edge may be "
                "universe- or regime-specific.",
                "2. Rework the exits. Entries are rarely the binding constraint.",
                "3. Conclude this setup does not survive mechanical testing on "
                "these names, and stop funding it.",
                "",
                "What not to do: add variants until one goes green. With enough "
                "attempts one always will, and that one is noise."]
    out += ["", "## Notes", "",
            "- Slippage 0.03% each side; a bar touching both stop and target "
            "is scored as a loss.",
            "- A period needs 5+ trades to be scored at all.",
            "- `faithful` = published method: 5-minute opening range, entries "
            "09:30-11:00, displacement before retest, 2 attempts, done after a win.",
            "- Each `faithful +/-x` changes exactly ONE rule, so the gap to "
            "`faithful` prices that rule."]
    return "\n".join(out)


if __name__ == "__main__":
    raise SystemExit(main())
