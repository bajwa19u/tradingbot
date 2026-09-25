"""Run history — what changed between iterations, and what it did.

Every backtest and sweep appends one row here. The value is not the list of
runs, it is the diff: the table shows only the settings that actually vary
across runs, next to the results, so you can see which change moved which
number instead of trying to remember.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import REPO_ROOT

REPORTS = REPO_ROOT / "reports"
HISTORY_JSON = REPORTS / "history.json"
HISTORY_MD = REPORTS / "history.md"

# The knobs worth tracking. Anything here that differs between runs shows up
# as its own column.
TRACKED = [
    ("strategy", ["strategy", "name"]),
    ("timeframe", ["strategy", "timeframe_minutes"]),
    ("or_min", ["strategy", "session", "opening_range_minutes"]),
    ("from", ["strategy", "session", "no_entries_before"]),
    ("until", ["strategy", "session", "no_entries_after"]),
    ("vol_x", ["strategy", "breakout", "volume_multiple"]),
    ("vol_base", ["strategy", "breakout", "volume_baseline"]),
    ("range_max", ["strategy", "breakout", "max_range_atr_multiple"]),
    ("retest_bars", ["strategy", "retest", "max_bars_after_break"]),
    ("displace", ["strategy", "retest", "min_displacement_atr"]),
    ("max/day", ["strategy", "filters", "max_trades_per_day"]),
    ("stop_on_win", ["strategy", "filters", "stop_after_first_win"]),
    ("shorts", ["strategy", "filters", "trade_shorts"]),
    ("vwap", ["strategy", "filters", "require_vwap_alignment"]),
    ("htf", ["strategy", "filters", "require_htf_alignment"]),
    ("exits", ["risk", "exit_style"]),
    ("observe", ["risk", "observe_bars"]),
    ("fastR", ["risk", "fast_target_R"]),
    ("slowR", ["risk", "slow_target_R"]),
    ("arm_R", ["risk", "retest_arm_R"]),
    ("rewardR", ["risk", "reward_multiple"]),
    ("be@1R", ["risk", "breakeven_after_1R"]),
]


def _dig(cfg: dict, path: list[str]) -> Any:
    node: Any = cfg
    for key in path:
        if not isinstance(node, dict) or key not in node:
            return None
        node = node[key]
    return node


def settings_of(cfg: dict) -> dict[str, Any]:
    return {label: _dig(cfg, path) for label, path in TRACKED}


def load() -> list[dict]:
    if not HISTORY_JSON.exists():
        return []
    try:
        return json.loads(HISTORY_JSON.read_text())
    except json.JSONDecodeError:
        return []


def record(kind: str, cfg: dict, stats: dict, *, label: str = "",
           symbols: list[str] | None = None, period: str = "",
           extra: dict | None = None) -> list[dict]:
    """Append one run and rewrite the comparison report."""
    runs = load()
    row = {
        "run": len(runs) + 1,
        "when": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "kind": kind,
        "label": label,
        "symbols": ",".join(symbols or []),
        "period": period,
        "settings": settings_of(cfg),
        "n": stats.get("n_trades", 0),
        "expectancy_R": stats.get("expectancy_R", 0.0),
        "total_R": stats.get("total_R", 0.0),
        "win_rate_pct": stats.get("win_rate_pct", 0.0),
        "max_dd_pct": stats.get("max_drawdown_pct", 0.0),
        "profit_factor": stats.get("profit_factor", 0.0),
    }
    if extra:
        row.update(extra)
    runs.append(row)
    REPORTS.mkdir(exist_ok=True)
    HISTORY_JSON.write_text(json.dumps(runs, indent=2, default=str))
    HISTORY_MD.write_text(render(runs))
    return runs


def render(runs: list[dict]) -> str:
    if not runs:
        return "# Run history\n\nNo runs recorded yet.\n"

    # Only show settings columns that actually differ between runs - a column
    # of identical values teaches nothing.
    keys = [label for label, _ in TRACKED]
    varying = [k for k in keys
               if len({json.dumps(r["settings"].get(k), default=str)
                       for r in runs}) > 1]

    out = [
        "# Run history",
        "",
        f"{len(runs)} run(s). Columns shown are the settings that **changed** "
        "between runs — identical settings are hidden.",
        "",
    ]

    header = ["#", "When", "Kind"] + varying + [
        "Trades", "Expectancy", "Total R", "Win %", "Max DD", "Δ exp"]
    out.append("| " + " | ".join(header) + " |")
    out.append("|" + "---|" * len(header))

    prev = None
    for r in runs:
        delta = ""
        if prev is not None:
            d = r["expectancy_R"] - prev["expectancy_R"]
            delta = f"{d:+.3f}" + (" ✅" if d > 0 else " ❌" if d < 0 else "")
        cells = [str(r["run"]), r["when"], r["kind"]]
        cells += [str(r["settings"].get(k)) for k in varying]
        warn = "" if r["n"] >= 100 else " ⚠"
        cells += [f"{r['n']}{warn}", f"{r['expectancy_R']:+.3f}R",
                  f"{r['total_R']:+.1f}", f"{r['win_rate_pct']}",
                  f"{r['max_dd_pct']}%", delta]
        out.append("| " + " | ".join(cells) + " |")
        prev = r

    scored = [r for r in runs if r["n"] >= 100]
    out += ["", "## Best so far", ""]
    if scored:
        best = max(scored, key=lambda r: r["expectancy_R"])
        out += [f"**Run #{best['run']}** ({best['when']}) — "
                f"{best['expectancy_R']:+.3f}R over {best['n']} trades, "
                f"max drawdown {best['max_dd_pct']}%.", ""]
        changed = {k: best["settings"].get(k) for k in varying}
        if changed:
            out.append("Its settings: " +
                       ", ".join(f"`{k}={v}`" for k, v in changed.items()))
        if best["expectancy_R"] <= 0:
            out += ["", "Note: the best run so far still has **negative "
                    "expectancy**. Nothing here is tradeable yet."]
    else:
        out.append("No run yet has 100+ trades, which is the minimum for the "
                   "numbers to mean anything.")

    out += ["", "## Reading this", "",
            "- **Expectancy** is the average R per trade and is the number "
            "that decides whether there is an edge.",
            "- **Δ exp** compares each run to the one before it. It is only "
            "meaningful when one thing changed.",
            "- Runs with fewer than 100 trades are marked ⚠ and should not "
            "drive decisions.",
            "- Comparing runs over different periods or symbols compares "
            "markets, not rules. Check the period column before concluding."]
    return "\n".join(out)
