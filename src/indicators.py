"""Candle patterns, market structure and indicator helpers.

Pure functions over pandas DataFrames with columns:
    open, high, low, close, volume   (index = tz-aware timestamps, US/Eastern)

Keeping these separate and pure is what makes the strategy testable without
any market data connection.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

OHLCV = ["open", "high", "low", "close", "volume"]


# ---------------------------------------------------------------------------
# Indicators
# ---------------------------------------------------------------------------
def true_range(df: pd.DataFrame) -> pd.Series:
    prev_close = df["close"].shift(1)
    ranges = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ],
        axis=1,
    )
    return ranges.max(axis=1)


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Wilder's ATR."""
    tr = true_range(df)
    return tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def vwap(df: pd.DataFrame) -> pd.Series:
    """Session VWAP — resets each trading day."""
    typical = (df["high"] + df["low"] + df["close"]) / 3.0
    pv = typical * df["volume"]
    day = df.index.normalize()
    cum_pv = pv.groupby(day).cumsum()
    cum_vol = df["volume"].groupby(day).cumsum()
    return cum_pv / cum_vol.replace(0, np.nan)


def relative_volume(intraday_volume: float, avg_daily_volume: float,
                    fraction_of_session_elapsed: float) -> float:
    """Today's volume pace vs. what an average day would have done by now."""
    if avg_daily_volume <= 0 or fraction_of_session_elapsed <= 0:
        return 0.0
    expected = avg_daily_volume * fraction_of_session_elapsed
    return float(intraday_volume / expected) if expected else 0.0


# ---------------------------------------------------------------------------
# Candle anatomy
# ---------------------------------------------------------------------------
def _body(o: float, c: float) -> float:
    return abs(c - o)


def _upper_wick(o: float, h: float, c: float) -> float:
    return h - max(o, c)


def _lower_wick(o: float, l: float, c: float) -> float:
    return min(o, c) - l


def is_hammer(bar: pd.Series, lower_wick_ratio: float = 2.0,
              upper_wick_max_ratio: float = 0.8) -> bool:
    """Bullish hammer: long lower wick, small body, little upper wick."""
    o, h, l, c = bar["open"], bar["high"], bar["low"], bar["close"]
    body = _body(o, c)
    if body <= 0:
        body = (h - l) * 0.001 or 1e-9   # doji — treat body as ~zero, not invalid
    lower = _lower_wick(o, l, c)
    upper = _upper_wick(o, h, c)
    if (h - l) <= 0:
        return False
    return lower >= lower_wick_ratio * body and upper <= upper_wick_max_ratio * body


def is_inverted_hammer(bar: pd.Series, upper_wick_ratio: float = 2.0,
                       lower_wick_max_ratio: float = 0.8) -> bool:
    """Bearish shooting star — the short-side mirror of the hammer."""
    o, h, l, c = bar["open"], bar["high"], bar["low"], bar["close"]
    body = _body(o, c)
    if body <= 0:
        body = (h - l) * 0.001 or 1e-9
    upper = _upper_wick(o, h, c)
    lower = _lower_wick(o, l, c)
    if (h - l) <= 0:
        return False
    return upper >= upper_wick_ratio * body and lower <= lower_wick_max_ratio * body


def is_bullish_engulfing(prev: pd.Series, bar: pd.Series,
                         min_body_ratio: float = 1.0) -> bool:
    prev_body = _body(prev["open"], prev["close"])
    body = _body(bar["open"], bar["close"])
    if body <= 0 or prev_body <= 0:
        return False
    return (
        bar["close"] > bar["open"]                     # current is green
        and prev["close"] < prev["open"]               # previous is red
        and bar["close"] >= prev["open"]               # engulfs the body
        and bar["open"] <= prev["close"]
        and body >= min_body_ratio * prev_body
    )


def is_bearish_engulfing(prev: pd.Series, bar: pd.Series,
                         min_body_ratio: float = 1.0) -> bool:
    prev_body = _body(prev["open"], prev["close"])
    body = _body(bar["open"], bar["close"])
    if body <= 0 or prev_body <= 0:
        return False
    return (
        bar["close"] < bar["open"]
        and prev["close"] > prev["open"]
        and bar["close"] <= prev["open"]
        and bar["open"] >= prev["close"]
        and body >= min_body_ratio * prev_body
    )


def confirmation_pattern(prev: pd.Series, bar: pd.Series, direction: str,
                         cfg) -> str | None:
    """Return the name of the confirming pattern, or None if the bar does not
    confirm the retest in the given direction."""
    patterns = list(cfg.patterns)
    if direction == "long":
        if "hammer" in patterns and is_hammer(
            bar, cfg.hammer_lower_wick_ratio, cfg.hammer_upper_wick_max_ratio
        ):
            return "hammer"
        if "engulfing" in patterns and is_bullish_engulfing(
            prev, bar, cfg.engulfing_min_body_ratio
        ):
            return "bullish_engulfing"
    else:
        if "hammer" in patterns and is_inverted_hammer(
            bar, cfg.hammer_lower_wick_ratio, cfg.hammer_upper_wick_max_ratio
        ):
            return "shooting_star"
        if "engulfing" in patterns and is_bearish_engulfing(
            prev, bar, cfg.engulfing_min_body_ratio
        ):
            return "bearish_engulfing"
    return None


# ---------------------------------------------------------------------------
# Market structure
# ---------------------------------------------------------------------------
def swing_low(df: pd.DataFrame, lookback: int = 3) -> float:
    return float(df["low"].tail(lookback).min())


def swing_high(df: pd.DataFrame, lookback: int = 3) -> float:
    return float(df["high"].tail(lookback).max())


def resample_bars(df: pd.DataFrame, minutes: int) -> pd.DataFrame:
    """Aggregate 1-minute bars up to the strategy timeframe."""
    rule = f"{minutes}min"
    out = df.resample(rule, label="left", closed="left", origin="start_day").agg(
        {"open": "first", "high": "max", "low": "min",
         "close": "last", "volume": "sum"}
    )
    return out.dropna(subset=["open", "high", "low", "close"])
