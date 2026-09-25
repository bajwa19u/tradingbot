"""Four more strategy families, so the search covers more than one idea.

Each is a well-known retail setup, implemented literally and without
embellishment. The point is not that any of them is clever — it is that the
search has somewhere to look besides break-and-retest, and that whatever
wins had real competition.
"""
from __future__ import annotations

import numpy as np

from .base import BaseEngine, rsi


class VwapReversion(BaseEngine):
    """Price stretches away from VWAP, then a candle closes back toward it.

    The premise is that intraday moves overshoot the volume-weighted average
    and get pulled back. Fails badly in trends, which is what the stretch
    threshold is for.
    """

    name = "vwap_reversion"

    def evaluate(self, bar, ts):
        if np.isnan(self.vwap) or self.atr <= 0 or len(self.bars) < 6:
            return None
        stretch = float(self.p("stretch_atr", 0.35)) * self.atr
        o, h, l, c = (float(bar["open"]), float(bar["high"]),
                      float(bar["low"]), float(bar["close"]))

        # stretched ABOVE vwap and printing a down candle -> fade it
        if c > self.vwap + stretch and c < o:
            return "short", h + self.atr * float(self.p("stop_atr", 0.10)), "vwap_fade"
        if c < self.vwap - stretch and c > o:
            return "long", l - self.atr * float(self.p("stop_atr", 0.10)), "vwap_fade"
        return None


class OpeningRangeBreak(BaseEngine):
    """Plain opening-range breakout: no retest, no confirmation candle.

    Included as the control for break-and-retest. If waiting for the retest
    adds nothing, this should do just as well, and that would be worth
    knowing.
    """

    name = "orb_simple"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.or_high = None
        self.or_low = None
        self.fired = False

    def evaluate(self, bar, ts):
        session = self.cfg.strategy.session
        open_t = self._as_time(session.market_open)
        minutes = (ts.hour * 60 + ts.minute) - (open_t.hour * 60 + open_t.minute)
        window = int(self.p("or_minutes", 15))

        if minutes < window:
            h, l = float(bar["high"]), float(bar["low"])
            self.or_high = h if self.or_high is None else max(self.or_high, h)
            self.or_low = l if self.or_low is None else min(self.or_low, l)
            return None
        if self.or_high is None or self.fired:
            return None

        c = float(bar["close"])
        buf = self.atr * float(self.p("stop_atr", 0.15)) if self.atr > 0 else 0.0
        if c > self.or_high:
            self.fired = True
            return "long", self.or_low - buf, "orb_long"
        if c < self.or_low:
            self.fired = True
            return "short", self.or_high + buf, "orb_short"
        return None


class RsiExtreme(BaseEngine):
    """Mean reversion from an RSI extreme, optionally only with the trend."""

    name = "rsi_extreme"

    def evaluate(self, bar, ts):
        period = int(self.p("rsi_period", 14))
        value = rsi(self.closes, period)
        if value is None or self.atr <= 0:
            return None
        lookback = int(self.p("swing_lookback", 5))
        if len(self.bars) < lookback + 1:
            return None

        o, c = float(bar["open"]), float(bar["close"])
        buf = self.atr * float(self.p("stop_atr", 0.10))
        recent = self.bars[-lookback:]

        if value <= float(self.p("oversold", 25)) and c > o:
            low = min(float(b["low"]) for b in recent)
            return "long", low - buf, "rsi_oversold"
        if value >= float(self.p("overbought", 75)) and c < o:
            high = max(float(b["high"]) for b in recent)
            return "short", high + buf, "rsi_overbought"
        return None


class MomentumBreakout(BaseEngine):
    """Buy strength: a close at the highest point of the last N bars, on
    expanding volume. The opposite premise to mean reversion, deliberately —
    the two cannot both be right, and the search should say which."""

    name = "momentum_breakout"

    def evaluate(self, bar, ts):
        lookback = int(self.p("lookback", 12))
        if len(self.bars) < lookback + 2 or self.atr <= 0:
            return None
        prior = self.bars[-(lookback + 1):-1]
        c = float(bar["close"])
        vol = float(bar["volume"])
        avg_vol = float(np.mean([float(b["volume"]) for b in prior]))
        if avg_vol > 0 and vol < float(self.p("volume_multiple", 1.5)) * avg_vol:
            return None

        buf = self.atr * float(self.p("stop_atr", 0.25))
        highest = max(float(b["high"]) for b in prior)
        lowest = min(float(b["low"]) for b in prior)
        if c > highest:
            return "long", c - buf, "momentum_long"
        if c < lowest:
            return "short", c + buf, "momentum_short"
        return None
