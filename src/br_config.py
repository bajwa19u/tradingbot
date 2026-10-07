"""Break & Retest V1 settings: br_config.yaml over the defaults below.

Kept apart from config.yaml on purpose. That file drives the deployed bot;
nothing tuned here can change what it posts.
"""
from __future__ import annotations

import copy
from pathlib import Path

import yaml

from .config import REPO_ROOT, Section

PATH = REPO_ROOT / "br_config.yaml"

DEFAULTS: dict = {
    "universe": {"symbols": ["SPY", "QQQ", "AAPL", "TSLA", "AMD", "NVDA", "MU", "GOOGL",
                             "AMZN", "HOOD", "SHOP", "COIN", "SNDK"],
                 "benchmark_symbol": "SNDK", "market_symbols": ["SPY", "QQQ"]},
    "session": {"premarket_start": "04:00", "open": "09:30", "signals_until": "11:30",
                "time_exit": "15:55", "live_start": "09:00"},
    "levels": {"long": ["pdh", "pmh", "pdc", "swing_high"],
               "short": ["pdl", "pml", "pdc", "swing_low"],
               "pm_levels_need_outside_open": True, "swing_left": 3, "swing_right": 3,
               "merge_within_pct": 0.10},
    "breakout": {"min_close_beyond_pct": 0.0, "allow_gap_breaks": False,
                 "max_attempts_per_level": 2},
    "retest": {"tolerance_pct": 0.10, "max_minutes_after_break": 45,
               "min_bars_after_break": 1, "fail_close_pct": 0.15,
               "min_displacement_pct": 0.0},
    "confirmation": {"max_bars_after_touch": 3, "require_close_beyond_level": True},
    "timeframes": {"setup": [1, 3, 5]},
    "risk": {"risk_dollars": 1000.0, "stop_buffer_pct": 0.50, "stop_ref": "level",
             "target_r": 2.0, "slippage_pct": 0.025, "max_open_per_symbol": 1,
             "max_signals_per_symbol_per_day": 2},
    "context": {"bullish_at": 2, "bearish_at": -2, "ema_len": 20,
                "extended_vwap_atr": 0.6, "block_counter_bias": False},
    "analysis": {"post_exit_minutes": [5, 10, 15, 30],
                 "alt_stop_pcts": [0.25, 0.35, 0.50, 0.75, 1.00],
                 "alt_stop_atr_mult": 0.25, "alt_targets_r": [1.5, 2.0, 3.0, 4.0],
                 "alt_time_minutes": [60, 120, 180],
                 "in_sample_fraction": 0.60},
    "backtest": {"days": 252, "feed": "sip", "charts": "sample", "chart_sample": 12},
    "live": {"feed": "iex", "discord_secret": "DISCORD_BR_WEBHOOK_URL",
             "post_daily_summary": True},
}


def _merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def load(path: str | Path | None = None, **overrides) -> Section:
    """Settings as dotted access. `overrides` are nested dicts, for tests and
    one-off variants: load(risk={"stop_buffer_pct": 0.35})."""
    p = Path(path) if path else PATH
    raw = yaml.safe_load(p.read_text()) if p.exists() else {}
    cfg = _merge(_merge(DEFAULTS, raw), overrides)
    _check(cfg)
    return Section(cfg)


def _check(c: dict) -> None:
    if c["risk"]["target_r"] <= 0 or c["risk"]["stop_buffer_pct"] <= 0:
        raise ValueError("risk.target_r and risk.stop_buffer_pct must be > 0")
    if c["risk"]["stop_ref"] not in ("level", "retest_extreme"):
        raise ValueError("risk.stop_ref must be 'level' or 'retest_extreme'")
    for tf in c["timeframes"]["setup"]:
        if tf not in (1, 2, 3, 5, 10, 15):
            raise ValueError(f"timeframes.setup: {tf} is not a supported bar size")
    if not 0 < c["analysis"]["in_sample_fraction"] < 1:
        raise ValueError("analysis.in_sample_fraction must be between 0 and 1")
