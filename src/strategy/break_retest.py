"""Opening-range break-and-retest — the Scarface Trades methodology.

The rules, in order. Every one is a hard gate; failing any of them means no
trade rather than a lower-quality trade.

  1. OPENING RANGE   First `opening_range_minutes` of the session define a
                     high and a low. The range must be a sane width relative
                     to ATR — too tight and the level is noise, too wide and
                     the move is already spent.

  2. BREAK           A bar must CLOSE beyond the range high (long) or low
                     (short), clearing it by `min_break_pct`, on volume at
                     least `volume_multiple` x the opening-range average.

  3. RETEST          Within `max_bars_after_break` bars, price must come back
                     to the broken level (within `tolerance_atr_multiple` x
                     ATR). If it instead CLOSES back through the level by
                     more than `invalidate_close_beyond_pct`, the break failed
                     and the setup is dead for the day.

  4. CONFIRMATION    The retest must be rejected by a hammer or an engulfing
                     candle in the trade direction. No confirmation candle,
                     no trade — this is the single rule that separates the
                     setup from "buying a pullback".

  5. ENTRY / RISK    Enter at the close of the confirmation candle. Stop goes
                     beyond the confirmation candle's extreme plus an ATR
                     buffer. Target is `reward_multiple` x the risk.

The engine is a per-symbol, per-day state machine so that the identical code
path drives both the backtest and the live scanner. Nothing here touches the
network or the clock.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, time
from enum import Enum
from typing import Any

import numpy as np
import pandas as pd

from ..indicators import atr, confirmation_pattern, vwap


class State(str, Enum):
    WAITING_FOR_RANGE = "waiting_for_range"
    RANGE_SET = "range_set"
    BROKEN = "broken"
    CONFIRMED = "confirmed"
    INVALIDATED = "invalidated"
    EXPIRED = "expired"


@dataclass
class Signal:
    symbol: str
    direction: str                 # "long" | "short"
    timestamp: datetime
    entry: float
    stop: float
    target: float
    risk_per_share: float
    reward_multiple: float
    level: float                   # the broken opening-range level
    pattern: str                   # which confirmation candle fired
    opening_range_high: float
    opening_range_low: float
    atr: float
    vwap: float
    bars_to_retest: int
    shares: int = 0
    dollar_risk: float = 0.0
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["timestamp"] = self.timestamp.isoformat()
        return d

    @property
    def r_label(self) -> str:
        return f"{self.reward_multiple:.0f}R"


@dataclass
class Rejection:
    """Why a candidate setup did not become a signal — this is what makes the
    bot auditable instead of a black box."""
    symbol: str
    timestamp: datetime
    reason: str
    detail: str = ""


class BreakRetestEngine:
    """Feeds on bars for ONE symbol on ONE trading day."""

    def __init__(self, symbol: str, cfg, daily_atr: float,
                 avg_daily_volume: float = 0.0, htf_trend=None):
        self.symbol = symbol
        self.cfg = cfg
        self.s = cfg.strategy
        self.atr = float(daily_atr) if daily_atr and daily_atr > 0 else 0.0
        self.avg_daily_volume = avg_daily_volume
        # Higher-timeframe context (e.g. 1-hour trend), as a Series of +1/-1
        # already shifted so only fully-closed HTF bars are visible.
        self.htf_trend = htf_trend

        self.state = State.WAITING_FOR_RANGE
        self.or_high: float | None = None
        self.or_low: float | None = None
        self.or_avg_volume: float = 0.0
        self.direction: str | None = None
        self.level: float | None = None
        self.break_index: int | None = None
        self.extreme_since_break: float | None = None
        self.retest_seen = False
        self.retest_kind = "level"
        self.rejections: list[Rejection] = []
        self._bars: list[pd.Series] = []
        self._vwap_num = 0.0
        self._vwap_den = 0.0
        self.vwap: float = float("nan")

    # -- helpers ------------------------------------------------------------
    def _reject(self, ts: datetime, reason: str, detail: str = "") -> None:
        self.rejections.append(Rejection(self.symbol, ts, reason, detail))

    def _update_vwap(self, bar: pd.Series) -> None:
        typical = (bar["high"] + bar["low"] + bar["close"]) / 3.0
        self._vwap_num += typical * bar["volume"]
        self._vwap_den += bar["volume"]
        self.vwap = self._vwap_num / self._vwap_den if self._vwap_den else float("nan")

    @staticmethod
    def _as_time(value) -> time:
        if isinstance(value, time):
            return value
        hours, minutes = str(value).split(":")
        return time(int(hours), int(minutes))

    # -- main entry point ---------------------------------------------------
    def on_bar(self, bar: pd.Series) -> Signal | None:
        """Process one completed bar. Returns a Signal on the bar that
        confirms the setup, otherwise None."""
        self._bars.append(bar)
        self._update_vwap(bar)
        ts: datetime = bar.name
        session = self.s.session

        if self.state in (State.CONFIRMED, State.INVALIDATED, State.EXPIRED):
            return None

        open_t = self._as_time(session.market_open)
        or_end_minutes = session.opening_range_minutes

        # --- build the opening range ---------------------------------------
        if self.state is State.WAITING_FOR_RANGE:
            or_bars = [
                b for b in self._bars
                if _minutes_since(b.name, open_t) < or_end_minutes
            ]
            if _minutes_since(ts, open_t) + self.s.timeframe_minutes >= or_end_minutes \
                    and or_bars:
                self.or_high = max(float(b["high"]) for b in or_bars)
                self.or_low = min(float(b["low"]) for b in or_bars)
                self.or_avg_volume = float(np.mean([b["volume"] for b in or_bars]))
                if not self._range_is_tradeable(ts):
                    self.state = State.INVALIDATED
                    return None
                self.state = State.RANGE_SET
            return None

        # --- time windows ---------------------------------------------------
        if ts.time() < self._as_time(session.no_entries_before):
            return None
        if ts.time() > self._as_time(session.no_entries_after):
            if self.state is not State.CONFIRMED:
                self.state = State.EXPIRED
                self._reject(ts, "entry_window_closed")
            return None

        # --- look for the break ---------------------------------------------
        if self.state is State.RANGE_SET:
            self._check_for_break(bar, ts)
            return None

        # --- we are broken: watch for retest + confirmation ------------------
        if self.state is State.BROKEN:
            return self._check_retest(bar, ts)

        return None

    # -- rule 1 -------------------------------------------------------------
    def _range_is_tradeable(self, ts: datetime) -> bool:
        width = (self.or_high or 0) - (self.or_low or 0)
        if width <= 0:
            self._reject(ts, "degenerate_opening_range")
            return False
        if self.atr <= 0:
            return True  # no ATR available — don't block on it
        ratio = width / self.atr
        b = self.s.breakout
        if ratio > b.max_range_atr_multiple:
            self._reject(ts, "opening_range_too_wide",
                         f"{ratio:.2f} ATR > {b.max_range_atr_multiple}")
            return False
        if ratio < b.min_range_atr_multiple:
            self._reject(ts, "opening_range_too_tight",
                         f"{ratio:.2f} ATR < {b.min_range_atr_multiple}")
            return False
        return True

    def _breakout_fvg(self) -> tuple[float, float] | None:
        """The fair-value gap left by the impulse that broke the level.

        A bullish FVG is a three-candle imbalance: the high of the candle
        before the breakout sits BELOW the low of the candle after it, so a
        band of prices was skipped. Price often returns into that band rather
        than all the way back to the level, and the methodology treats a
        retest of either as valid.
        """
        if self.break_index is None or self.break_index < 1:
            return None
        if len(self._bars) < self.break_index + 2:
            return None
        before = self._bars[self.break_index - 1]
        after = self._bars[self.break_index + 1]
        if self.direction == "long":
            lo, hi = float(before["high"]), float(after["low"])
            return (lo, hi) if hi > lo else None
        lo, hi = float(after["high"]), float(before["low"])
        return (lo, hi) if hi > lo else None

    def _volume_baseline(self, b) -> float:
        """What counts as 'normal' volume for this bar.

        Intraday volume is heavily front-loaded: the first 15 minutes routinely
        trade several times what 11:00 does. Measuring a mid-morning breakout
        against the opening range therefore rejects almost every real break,
        which is exactly what the first backtest showed (2711 rejections).
        The default baseline is a rolling window of recent bars, which tracks
        the decay and asks the question the methodology actually asks: is
        volume expanding *relative to what this stock has just been doing*?
        """
        mode = b.get("volume_baseline", "recent")
        if mode == "opening_range":
            return self.or_avg_volume
        lookback = int(b.get("volume_lookback_bars", 6))
        end = len(self._bars) - 1             # exclude the break bar itself
        prior = self._bars[max(0, end - lookback):end]
        # "Relative volume" is meaningless off a single bar - and with a
        # 5-minute opening range that single bar is the highest-volume bar of
        # the day, which would veto every break. No history, no gate.
        if len(prior) < 2:
            return 0.0
        return float(np.mean([float(x["volume"]) for x in prior]))

    # -- rule 2 -------------------------------------------------------------
    def _check_for_break(self, bar: pd.Series, ts: datetime) -> None:
        b = self.s.breakout
        f = self.s.filters
        close = float(bar["close"])
        high = float(bar["high"])
        low = float(bar["low"])

        long_break = (close if b.require_close_beyond else high) > \
            self.or_high * (1 + b.min_break_pct / 100.0)
        short_break = (close if b.require_close_beyond else low) < \
            self.or_low * (1 - b.min_break_pct / 100.0)

        if not (long_break or short_break):
            return

        direction = "long" if long_break else "short"
        if direction == "long" and not f.trade_longs:
            return
        if direction == "short" and not f.trade_shorts:
            return

        baseline = self._volume_baseline(b)
        if baseline > 0 and float(bar["volume"]) < b.volume_multiple * baseline:
            self._reject(ts, "break_volume_too_low",
                         f"{bar['volume']:.0f} < "
                         f"{b.volume_multiple * baseline:.0f} "
                         f"(baseline={b.get('volume_baseline', 'recent')})")
            return

        self.direction = direction
        self.level = self.or_high if direction == "long" else self.or_low
        self.break_index = len(self._bars) - 1
        self.extreme_since_break = high if direction == "long" else low
        self.state = State.BROKEN

    # -- rules 3 + 4 --------------------------------------------------------
    def _check_retest(self, bar: pd.Series, ts: datetime) -> Signal | None:
        r = self.s.retest
        f = self.s.filters
        assert self.level is not None and self.break_index is not None

        bars_since = len(self._bars) - 1 - self.break_index
        if bars_since < r.min_bars_after_break:
            return None
        if bars_since > r.max_bars_after_break:
            self.state = State.EXPIRED
            self._reject(ts, "retest_never_came",
                         f"{bars_since} bars since break")
            return None

        close = float(bar["close"])

        # Track how far price ran before coming back. The methodology calls
        # for "visible space on the chart" between the break and the retest —
        # an immediate pullback that never displaced is not the setup.
        if self.direction == "long":
            self.extreme_since_break = max(self.extreme_since_break or close,
                                           float(bar["high"]))
        else:
            self.extreme_since_break = min(self.extreme_since_break or close,
                                           float(bar["low"]))

        # Failed break — price closed back through the level
        invalid_pct = r.invalidate_close_beyond_pct / 100.0
        if self.direction == "long" and close < self.level * (1 - invalid_pct):
            self.state = State.INVALIDATED
            self._reject(ts, "failed_break", f"close {close:.2f} < level {self.level:.2f}")
            return None
        if self.direction == "short" and close > self.level * (1 + invalid_pct):
            self.state = State.INVALIDATED
            self._reject(ts, "failed_break", f"close {close:.2f} > level {self.level:.2f}")
            return None

        # Did this bar touch the level - or the fair-value gap the breakout
        # left behind? The methodology accepts either: "retest the range
        # itself or a FVG created from the breakout".
        tol = (self.atr * r.tolerance_atr_multiple) if self.atr > 0 \
            else self.level * 0.002
        if self.direction == "long":
            touched = (float(bar["low"]) if r.allow_wick_only else close) \
                <= self.level + tol
        else:
            touched = (float(bar["high"]) if r.allow_wick_only else close) \
                >= self.level - tol

        fvg = self._breakout_fvg() if r.get("allow_fvg", True) else None
        if not touched and fvg is not None:
            lo, hi = fvg
            if self.direction == "long":
                touched = float(bar["low"]) <= hi
            else:
                touched = float(bar["high"]) >= lo
            if touched:
                self.retest_kind = "fvg"
        elif touched:
            self.retest_kind = "level"

        if not touched:
            return None
        self.retest_seen = True

        # "Visible space" gate: the break must have travelled far enough from
        # the level before returning to it.
        min_disp = float(r.get("min_displacement_atr", 0.0))
        if min_disp > 0 and self.atr > 0 and self.extreme_since_break is not None:
            travelled = abs(self.extreme_since_break - self.level)
            if travelled < min_disp * self.atr:
                self._reject(ts, "no_displacement_before_retest",
                             f"{travelled:.2f} < {min_disp * self.atr:.2f}")
                return None

        # Confirmation candle
        if len(self._bars) < 2:
            return None
        prev = self._bars[-2]
        pattern = confirmation_pattern(prev, bar, self.direction, self.s.confirmation)
        if pattern is None:
            self._reject(ts, "no_confirmation_candle",
                         f"retest touched {self.level:.2f} but candle did not reject")
            return None

        if self.s.confirmation.require_volume_uptick and \
                float(bar["volume"]) <= float(prev["volume"]):
            self._reject(ts, "confirmation_volume_flat")
            return None

        if f.get("require_htf_alignment", False) and self.htf_trend is not None:
            try:
                trend = self.htf_trend.asof(ts)
            except Exception:
                trend = None
            if trend is None or (isinstance(trend, float) and np.isnan(trend)):
                pass                      # no context yet - do not block
            elif self.direction == "long" and trend <= 0:
                self._reject(ts, "htf_context_against_long")
                return None
            elif self.direction == "short" and trend >= 0:
                self._reject(ts, "htf_context_against_short")
                return None

        if f.require_vwap_alignment and not np.isnan(self.vwap):
            if self.direction == "long" and close < self.vwap:
                self._reject(ts, "below_vwap_for_long",
                             f"close {close:.2f} < vwap {self.vwap:.2f}")
                return None
            if self.direction == "short" and close > self.vwap:
                self._reject(ts, "above_vwap_for_short",
                             f"close {close:.2f} > vwap {self.vwap:.2f}")
                return None

        return self._build_signal(bar, ts, pattern, bars_since)

    # -- rule 5 -------------------------------------------------------------
    def _build_signal(self, bar: pd.Series, ts: datetime, pattern: str,
                      bars_since: int) -> Signal:
        risk_cfg = self.cfg.risk
        entry = float(bar["close"])
        buffer = (self.atr * risk_cfg.stop_buffer_atr_multiple) if self.atr > 0 \
            else entry * 0.001

        if self.direction == "long":
            stop = min(float(bar["low"]), self.level) - buffer
            risk_per_share = entry - stop
            target = entry + risk_cfg.reward_multiple * risk_per_share
        else:
            stop = max(float(bar["high"]), self.level) + buffer
            risk_per_share = stop - entry
            target = entry - risk_cfg.reward_multiple * risk_per_share

        self.state = State.CONFIRMED

        signal = Signal(
            symbol=self.symbol,
            direction=self.direction,
            timestamp=ts,
            entry=round(entry, 4),
            stop=round(stop, 4),
            target=round(target, 4),
            risk_per_share=round(risk_per_share, 4),
            reward_multiple=risk_cfg.reward_multiple,
            level=round(float(self.level), 4),
            pattern=f"{pattern}@{self.retest_kind}",
            opening_range_high=round(float(self.or_high), 4),
            opening_range_low=round(float(self.or_low), 4),
            atr=round(self.atr, 4),
            vwap=round(self.vwap, 4) if not np.isnan(self.vwap) else 0.0,
            bars_to_retest=bars_since,
        )
        size_signal(signal, risk_cfg)
        return signal


def size_signal(signal: Signal, risk_cfg) -> Signal:
    """Position sizing: risk a fixed % of equity, capped by position size."""
    equity = float(risk_cfg.account_equity)
    dollar_risk = equity * float(risk_cfg.risk_per_trade_pct) / 100.0
    if signal.risk_per_share <= 0:
        signal.shares = 0
        signal.dollar_risk = 0.0
        return signal
    ideal = int(dollar_risk // signal.risk_per_share)
    shares = ideal
    max_notional = equity * float(risk_cfg.max_position_pct_of_equity) / 100.0
    if signal.entry > 0:
        shares = min(shares, int(max_notional // signal.entry))
    signal.shares = max(shares, 0)
    signal.dollar_risk = round(signal.shares * signal.risk_per_share, 2)
    if signal.shares == 0:
        signal.notes.append("position size rounds to 0 shares at current equity")
    elif shares < ideal:
        signal.notes.append(
            f"size capped by max_position_pct_of_equity "
            f"({shares} of {ideal} shares) — actual risk "
            f"${signal.dollar_risk:.2f}, not ${dollar_risk:.2f}"
        )
    return signal


def _minutes_since(ts: datetime, open_time: time) -> float:
    return (ts.hour * 60 + ts.minute) - (open_time.hour * 60 + open_time.minute)


def compute_daily_atr(daily_bars: pd.DataFrame, period: int = 14) -> float:
    """Plain 14-day ATR in dollars.

    Earlier this scaled the daily ATR down by sqrt(3/78) to approximate three
    five-minute bars of volatility. That was wrong in practice: the opening
    range is the most volatile stretch of the session, not an average one, so
    ordinary ranges measured 2-3x the scaled figure and got thrown out as
    "too wide" (538 rejections in the first backtest).

    The value returned is now the raw daily ATR, and every *_atr_multiple in
    config.yaml is a fraction of it — which is also far easier to reason
    about: an opening range is typically 0.2-0.4 of a day's ATR.
    """
    if daily_bars is None or len(daily_bars) < period + 1:
        return 0.0
    value = float(atr(daily_bars, period).iloc[-1])
    return 0.0 if np.isnan(value) else value
