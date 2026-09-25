"""Strategy registry.

Both engines share one interface: construct with (symbol, cfg, daily_atr,
avg_daily_volume, htf_trend), then feed bars to on_bar() which returns a
Signal or None. That lets the backtester, sweep and live scanner run any
strategy without knowing which one it is.
"""
from __future__ import annotations

from .break_retest import BreakRetestEngine, Signal, compute_daily_atr  # noqa: F401
from .ema_pullback import EmaPullbackEngine

ENGINES = {
    "break_retest": BreakRetestEngine,
    "ema_pullback": EmaPullbackEngine,
}


def make_engine(cfg, symbol: str, daily_atr: float,
                avg_daily_volume: float = 0.0, htf_trend=None):
    name = str(cfg.strategy.get("name", "break_retest"))
    try:
        cls = ENGINES[name]
    except KeyError:
        raise ValueError(
            f"Unknown strategy '{name}'. Choose one of: {', '.join(ENGINES)}"
        ) from None
    return cls(symbol, cfg, daily_atr, avg_daily_volume, htf_trend)
