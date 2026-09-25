"""EMA pullback — trend continuation.

In an established trend, price repeatedly pulls back to a moving average and
resumes. The setup is: trend is up, price dips to the fast EMA, a candle
rejects it and closes back above, you enter on that close with a stop under
the pullback low.

The honest caveat, built into the filters rather than the prose: a trend is
*defined* by pullbacks that hold, so on any chart of a completed trend this
pattern looks infallible. The pullbacks that did not hold are the ones that
ended the trend, and the eye stops counting them. Everything here is
therefore gated on trend conditions measured BEFORE the pullback, never on
what price did afterwards.

Same interface as BreakRetestEngine: feed it bars, it returns a Signal.
"""
from __future__ import annotations

from collections import deque
from datetime import datetime, time

import numpy as np
import pandas as pd

from .break_retest import Rejection, Signal, size_signal


class EmaPullbackEngine:
    """One symbol, one trading day."""

    def __init__(self, symbol: str, cfg, daily_atr: float,
                 avg_daily_volume: float = 0.0, htf_trend=None):
        self.symbol = symbol
        self.cfg = cfg
        self.p = cfg.strategy.get("ema_pullback", {})
        self.atr = float(daily_atr) if daily_atr and daily_atr > 0 else 0.0
        self.htf_trend = htf_trend

        self.fast_n = int(self.p.get("fast_ema", 20))
        self.slow_n = int(self.p.get("slow_ema", 50))
        self.ema_fast: float | None = None
        self.ema_slow: float | None = None
        self.fast_hist: deque = deque(maxlen=200)
        self._seed: list[float] = []

        self.bars: list = []
        self.rejections: list[Rejection] = []
        self.touch_index: int | None = None
        self.touch_low: float | None = None
        self.touch_high: float | None = None
        self.touch_dir: str | None = None
        self.signals_today = 0
        self._vwap_num = 0.0
        self._vwap_den = 0.0
        self.vwap = float("nan")

    # ------------------------------------------------------------------
    def _reject(self, ts, reason, detail=""):
        self.rejections.append(Rejection(self.symbol, ts, reason, detail))

    @staticmethod
    def _as_time(value) -> time:
        if isinstance(value, time):
            return value
        h, m = str(value).split(":")
        return time(int(h), int(m))

    def _update_emas(self, close: float) -> None:
        if self.ema_slow is None:
            self._seed.append(close)
            if len(self._seed) >= self.slow_n:
                self.ema_slow = float(np.mean(self._seed[-self.slow_n:]))
                self.ema_fast = float(np.mean(self._seed[-self.fast_n:]))
            return
        kf = 2.0 / (self.fast_n + 1)
        ks = 2.0 / (self.slow_n + 1)
        self.ema_fast = close * kf + self.ema_fast * (1 - kf)
        self.ema_slow = close * ks + self.ema_slow * (1 - ks)

    # ------------------------------------------------------------------
    def on_bar(self, bar) -> Signal | None:
        self.bars.append(bar)
        close = float(bar["close"])
        typical = (float(bar["high"]) + float(bar["low"]) + close) / 3.0
        self._vwap_num += typical * float(bar["volume"])
        self._vwap_den += float(bar["volume"])
        self.vwap = self._vwap_num / self._vwap_den if self._vwap_den else float("nan")

        self._update_emas(close)
        if self.ema_fast is None or self.ema_slow is None:
            return None
        self.fast_hist.append(self.ema_fast)

        ts: datetime = bar.name
        session = self.cfg.strategy.session
        if ts.time() < self._as_time(session.no_entries_before):
            return None
        if ts.time() > self._as_time(session.no_entries_after):
            return None

        filters = self.cfg.strategy.filters
        if self.signals_today >= int(filters.max_trades_per_symbol_per_day):
            return None

        direction = self._trend_direction(ts)
        if direction is None:
            return None

        # --- has price just pulled back INTO the fast EMA? -----------------
        tol = self.atr * float(self.p.get("touch_tolerance_atr", 0.05)) \
            if self.atr > 0 else self.ema_fast * 0.0005
        low, high = float(bar["low"]), float(bar["high"])

        if direction == "long":
            touched = low <= self.ema_fast + tol
            broke = close < self.ema_slow
        else:
            touched = high >= self.ema_fast - tol
            broke = close > self.ema_slow

        if broke:
            # Trend structure gone - forget any pending pullback.
            self.touch_index = None
            return None

        if touched:
            if self.touch_index is None or direction != self.touch_dir:
                self.touch_index = len(self.bars) - 1
                self.touch_low = low
                self.touch_high = high
                self.touch_dir = direction
            else:
                self.touch_low = min(self.touch_low, low)
                self.touch_high = max(self.touch_high, high)

        if self.touch_index is None:
            return None

        bars_since = len(self.bars) - 1 - self.touch_index
        if bars_since > int(self.p.get("max_bars_since_touch", 3)):
            self._reject(ts, "pullback_went_stale", f"{bars_since} bars")
            self.touch_index = None
            return None

        # --- confirmation: candle rejects the EMA and closes back with trend
        opened = float(bar["open"])
        if direction == "long":
            confirmed = close > opened and close > self.ema_fast
        else:
            confirmed = close < opened and close < self.ema_fast
        if not confirmed:
            return None

        if filters.require_vwap_alignment and not np.isnan(self.vwap):
            if direction == "long" and close < self.vwap:
                self._reject(ts, "below_vwap_for_long")
                return None
            if direction == "short" and close > self.vwap:
                self._reject(ts, "above_vwap_for_short")
                return None

        return self._build(bar, ts, direction, bars_since)

    # ------------------------------------------------------------------
    def _trend_direction(self, ts) -> str | None:
        """Trend measured only from data available before the pullback."""
        f = self.cfg.strategy.filters
        lookback = int(self.p.get("slope_lookback", 10))
        if len(self.fast_hist) <= lookback:
            return None
        slope = self.fast_hist[-1] - self.fast_hist[-1 - lookback]
        min_slope = float(self.p.get("min_slope_atr", 0.10))
        if self.atr > 0 and abs(slope) < min_slope * self.atr:
            self._reject(ts, "trend_too_flat",
                         f"slope {slope:.3f} < {min_slope * self.atr:.3f}")
            return None

        up = self.ema_fast > self.ema_slow and slope > 0
        down = self.ema_fast < self.ema_slow and slope < 0
        if up and f.trade_longs:
            direction = "long"
        elif down and f.trade_shorts:
            direction = "short"
        else:
            return None

        if f.get("require_htf_alignment", False) and self.htf_trend is not None:
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
        return direction

    def _build(self, bar, ts, direction: str, bars_since: int) -> Signal:
        risk_cfg = self.cfg.risk
        entry = float(bar["close"])
        buffer = self.atr * float(risk_cfg.stop_buffer_atr_multiple) \
            if self.atr > 0 else entry * 0.001

        if direction == "long":
            stop = min(float(self.touch_low), float(bar["low"])) - buffer
            risk = entry - stop
            target = entry + risk_cfg.reward_multiple * risk
        else:
            stop = max(float(self.touch_high), float(bar["high"])) + buffer
            risk = stop - entry
            target = entry - risk_cfg.reward_multiple * risk

        self.signals_today += 1
        self.touch_index = None

        sig = Signal(
            symbol=self.symbol, direction=direction, timestamp=ts,
            entry=round(entry, 4), stop=round(stop, 4), target=round(target, 4),
            risk_per_share=round(risk, 4),
            reward_multiple=risk_cfg.reward_multiple,
            level=round(float(self.ema_fast), 4), pattern="ema_pullback",
            opening_range_high=round(float(self.ema_fast), 4),
            opening_range_low=round(float(self.ema_slow), 4),
            atr=round(self.atr, 4),
            vwap=round(self.vwap, 4) if not np.isnan(self.vwap) else 0.0,
            bars_to_retest=bars_since,
        )
        return size_signal(sig, risk_cfg)
