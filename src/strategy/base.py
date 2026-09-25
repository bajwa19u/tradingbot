"""Shared machinery for the simpler strategy families.

Each family only has to answer one question per bar: "is there a trade here,
and where does the stop go?" Everything else — session windows, VWAP, trade
caps, position sizing, rejection logging — lives here so a new idea costs a
dozen lines instead of a file.
"""
from __future__ import annotations

from datetime import datetime, time

import numpy as np

from .break_retest import Rejection, Signal, size_signal


class BaseEngine:
    """One symbol, one trading day."""

    name = "base"

    def __init__(self, symbol: str, cfg, daily_atr: float,
                 avg_daily_volume: float = 0.0, htf_trend=None, context=None):
        self.symbol = symbol
        self.cfg = cfg
        self.params = cfg.strategy.get(self.name, {}) or {}
        self.atr = float(daily_atr) if daily_atr and daily_atr > 0 else 0.0
        self.htf_trend = htf_trend
        self.context = context or {}

        self.bars: list = []
        self.closes: list[float] = []
        self.rejections: list[Rejection] = []
        self.signals_today = 0
        self._vwap_num = 0.0
        self._vwap_den = 0.0
        self.vwap = float("nan")

    # -- helpers ------------------------------------------------------------
    def _reject(self, ts, reason, detail=""):
        self.rejections.append(Rejection(self.symbol, ts, reason, detail))

    @staticmethod
    def _as_time(value) -> time:
        if isinstance(value, time):
            return value
        h, m = str(value).split(":")
        return time(int(h), int(m))

    def p(self, key, default):
        return self.params.get(key, default)

    # -- template method ----------------------------------------------------
    def on_bar(self, bar) -> Signal | None:
        self.bars.append(bar)
        close = float(bar["close"])
        self.closes.append(close)

        vol = float(bar["volume"])
        typical = (float(bar["high"]) + float(bar["low"]) + close) / 3.0
        self._vwap_num += typical * vol
        self._vwap_den += vol
        self.vwap = self._vwap_num / self._vwap_den if self._vwap_den else float("nan")

        ts: datetime = bar.name
        session = self.cfg.strategy.session
        if ts.time() < self._as_time(session.no_entries_before):
            return None
        if ts.time() > self._as_time(session.no_entries_after):
            return None

        filters = self.cfg.strategy.filters
        if self.signals_today >= int(filters.max_trades_per_symbol_per_day):
            return None

        found = self.evaluate(bar, ts)
        if found is None:
            return None
        direction, stop, pattern = found

        if direction == "long" and not filters.trade_longs:
            return None
        if direction == "short" and not filters.trade_shorts:
            return None

        if filters.get("require_htf_alignment", False) and self.htf_trend is not None:
            try:
                trend = self.htf_trend.asof(ts)
            except Exception:
                trend = None
            if trend is not None and not (isinstance(trend, float) and np.isnan(trend)):
                if direction == "long" and trend <= 0:
                    self._reject(ts, "htf_context_against_long")
                    return None
                if direction == "short" and trend >= 0:
                    self._reject(ts, "htf_context_against_short")
                    return None

        return self._build(bar, ts, direction, float(stop), pattern)

    # subclasses implement this
    def evaluate(self, bar, ts) -> tuple[str, float, str] | None:
        raise NotImplementedError

    # -- signal construction ------------------------------------------------
    def _build(self, bar, ts, direction: str, stop: float, pattern: str) -> Signal | None:
        risk_cfg = self.cfg.risk
        entry = float(bar["close"])
        risk = entry - stop if direction == "long" else stop - entry
        if risk <= 0:
            return None
        # A stop so tight that noise takes it out is not a trade.
        if self.atr > 0 and risk < self.atr * float(self.p("min_risk_atr", 0.02)):
            self._reject(ts, "stop_too_tight")
            return None

        target = (entry + risk_cfg.reward_multiple * risk if direction == "long"
                  else entry - risk_cfg.reward_multiple * risk)
        self.signals_today += 1
        sig = Signal(
            symbol=self.symbol, direction=direction, timestamp=ts,
            entry=round(entry, 4), stop=round(stop, 4), target=round(target, 4),
            risk_per_share=round(risk, 4),
            reward_multiple=risk_cfg.reward_multiple,
            level=round(entry, 4), pattern=pattern,
            opening_range_high=0.0, opening_range_low=0.0,
            atr=round(self.atr, 4),
            vwap=round(self.vwap, 4) if not np.isnan(self.vwap) else 0.0,
            bars_to_retest=0,
        )
        return size_signal(sig, risk_cfg)


# ---------------------------------------------------------------------------
# small indicator helpers used by the families below
# ---------------------------------------------------------------------------
def rsi(closes: list[float], period: int = 14) -> float | None:
    if len(closes) < period + 1:
        return None
    deltas = np.diff(np.asarray(closes[-(period + 1):], dtype=float))
    gains = deltas[deltas > 0].sum() / period
    losses = -deltas[deltas < 0].sum() / period
    if losses == 0:
        return 100.0
    rs = gains / losses
    return 100.0 - 100.0 / (1.0 + rs)


def ema_of(values: list[float], period: int) -> float | None:
    if len(values) < period:
        return None
    k = 2.0 / (period + 1)
    out = float(np.mean(values[:period]))
    for v in values[period:]:
        out = v * k + out * (1 - k)
    return out
