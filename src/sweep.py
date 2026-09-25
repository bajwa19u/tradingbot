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
            try:
                result = Backtester(variant_cfg).run(by_tf[tf], daily)
            except Exception as exc:  # noqa: BLE001
                log.warning("  %s @ %dm failed: %s", name, tf, exc)
                continue
            st = result["stats"]
            rejects = st.get("rejection_reasons") or {}
            top_reject = max(rejects.items(), key=lambda kv: kv[1])[0] if rejects else ""
            rows.append({
                "top_rejection": top_reject,
                "timeframe": f"{tf}m",
                "variant": name,
                "n": st.get("n_trades", 0),
                "win_rate": st.get("win_rate_pct", 0),
                "expectancy_R": st.get("expectancy_R", 0),
                "total_R": st.get("total_R", 0),
                "profit_factor": st.get("profit_factor", 0),
                "max_dd_pct": st.get("max_drawdown_pct", 0),
            })
            log.info("  %-26s @ %2dm  n=%-4d  exp=%+.3fR  totalR=%+.1f",
                     name, tf, rows[-1]["n"], rows[-1]["expectancy_R"],
                     rows[-1]["total_R"])

    REPORTS.mkdir(exist_ok=True)
    (REPORTS / "sweep.json").write_text(json.dumps(rows, indent=2, default=str))
    (REPORTS / "sweep.md").write_text(render(rows, symbols, args.start, args.end))
    print("\n" + render(rows, symbols, args.start, args.end))
    return 0


def render(rows: list[dict], symbols, start, end) -> str:
    out = [
        "# Rule sweep",
        "",
        f"**Symbols:** {', '.join(symbols)}  ",
        f"**Period:** {start} → {end or 'today'}  ",
        f"**Generated:** {datetime.now():%Y-%m-%d %H:%M}",
        "",
        "Every row ran on identical bars with identical costs. Only the rules "
        "differ. Rows with n < 30 are too small to trust.",
        "",
        "| Timeframe | Variant | Trades | Win % | Expectancy | Total R | PF | Max DD | Top rejection |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in sorted(rows, key=lambda r: -r["expectancy_R"]):
        warn = "" if r["n"] >= 30 else " ⚠"
        out.append(
            f"| {r['timeframe']} | {r['variant']} | {r['n']}{warn} | "
            f"{r['win_rate']} | {r['expectancy_R']:+.3f}R | {r['total_R']:+.1f} | "
            f"{r['profit_factor']} | {r['max_dd_pct']}% | "
            f"`{r.get('top_rejection','')}` |")
    out += [
        "",
        "## How to read this",
        "",
        "- `current-rules` is the baseline that lost 0.234R per trade.",
        "- `faithful` applies the published method: 5-minute opening range, "
        "entries 09:30-11:00 only, displacement before the retest, two "
        "attempts, done after one winner.",
        "- Each `faithful +/-x` row changes exactly ONE rule, so the gap "
        "between it and `faithful` is what that rule is worth.",
        "- A positive expectancy here is necessary but nowhere near "
        "sufficient. Ten variants across three timeframes is thirty chances "
        "for noise to look like skill; the winner has to be re-tested on "
        "dates it never saw before it means anything.",
    ]
    return "\n".join(out)


if __name__ == "__main__":
    raise SystemExit(main())
