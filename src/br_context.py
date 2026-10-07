"""Break & Retest V1: market context. Bullish / Bearish / Neutral, and a
confidence for a setup. It informs; in V1 it never blocks a trade.

Four votes per symbol, each -1, 0 or +1, summed into a score:

  daily   yesterday's close vs its 20-day average, and that average's slope
  1H      last COMPLETED hourly bar's close vs a 20-bar EMA, and the EMA's slope
  15M     the same on 15-minute bars
  VWAP    price above / below today's session VWAP

score >= bullish_at -> Bullish, <= bearish_at -> Bearish, else Neutral.
Only bars that had closed by the moment asked about are used. Regular-session
bars only, so the EMAs are not bent by thin premarket prints.

SPY and QQQ get the same treatment; together they are the market's bias.
Confidence for a long (mirror for a short):
  HIGH    stock Bullish and market Bullish (neither index Bearish)
  MEDIUM  one of the two aligned and the other Neutral
  LOW     anything else - neutral on both, or either one pointing the other way
"""
from __future__ import annotations

import bisect

import numpy as np
import pandas as pd

from .br_levels import OHLCV, vwap

LABEL = {1: "Bullish", -1: "Bearish", 0: "Neutral"}


def _bars(rth: pd.DataFrame, rule: str, offset: str) -> pd.DataFrame:
    return rth.resample(rule, label="left", closed="left", origin="start_day",
                        offset=offset).agg(OHLCV).dropna(subset=["open"])


def _vote(close: np.ndarray, ema: np.ndarray, k: int, back: int = 3) -> int:
    if k < back or np.isnan(ema[k]) or np.isnan(ema[k - back]):
        return 0
    up = close[k] > ema[k] and ema[k] > ema[k - back]
    dn = close[k] < ema[k] and ema[k] < ema[k - back]
    return 1 if up else -1 if dn else 0


class Book:
    """Everything one symbol needs to answer "what was the context at t"."""

    def __init__(self, rth: pd.DataFrame, daily: pd.DataFrame, cfg):
        """`rth`: regular-session 1-minute bars over many days. `daily`:
        daily bars indexed by date (complete sessions only)."""
        self.cfg = cfg
        n = cfg.context.ema_len
        self.series = {}
        for name, rule, off in (("h1", "60min", "30min"), ("m15", "15min", "0min")):
            parts = [_bars(g, rule, off) for _, g in rth.groupby(rth.index.date)]
            b = pd.concat(parts) if parts else pd.DataFrame(columns=list(OHLCV))
            ends = (b.index + pd.Timedelta(rule)).tz_convert("UTC").asi8 if len(b) else np.array([])
            close = b.close.to_numpy(float)
            ema = np.array(b.close.ewm(span=n, adjust=False).mean(), dtype=float)   # writable copy
            if len(ema) >= n:
                ema[:n - 1] = np.nan
            else:
                ema[:] = np.nan
            self.series[name] = (list(ends), close, ema)
        d = daily.sort_index()
        sma = d.close.rolling(20).mean()
        tr = pd.concat([d.high - d.low, (d.high - d.close.shift()).abs(),
                        (d.low - d.close.shift()).abs()], axis=1).max(axis=1)
        atr = tr.rolling(14).mean()
        vote = np.where((d.close > sma) & (sma > sma.shift(5)), 1,
                        np.where((d.close < sma) & (sma < sma.shift(5)), -1, 0))
        # Today's vote and ATR come from YESTERDAY's row: no peeking at today's close.
        self.day_vote = dict(zip(list(d.index[1:]), vote[:-1]))
        self.day_atr = dict(zip(list(d.index[1:]), atr.to_numpy(float)[:-1]))
        self.day_sma = dict(zip(list(d.index[1:]), sma.to_numpy(float)[:-1]))
        self.today = {}
        for day, g in rth.groupby(rth.index.date):
            self.today[day] = (g, vwap(g))

    def atr(self, day) -> float:
        v = self.day_atr.get(day, np.nan)
        return float(v) if v == v else np.nan

    def _tf_vote(self, name: str, t: pd.Timestamp) -> int:
        ends, close, ema = self.series[name]
        k = bisect.bisect_right(ends, t.tz_convert("UTC").value) - 1
        return _vote(close, ema, k) if k >= 0 else 0

    def at(self, t) -> dict:
        """Context using only bars that had closed by time `t` (tz-aware)."""
        t = pd.Timestamp(t)
        day = t.date()
        votes = {"daily": int(self.day_vote.get(day, 0)),
                 "h1": self._tf_vote("h1", t), "m15": self._tf_vote("m15", t)}
        g, vw = self.today.get(day, (None, None))
        px, vw_px, ext, consolidating = np.nan, np.nan, False, False
        if g is not None:
            done = g.index + pd.Timedelta(minutes=1) <= t
            if done.any():
                last = int(np.flatnonzero(done)[-1])
                px, vw_px = float(g.close.iloc[last]), float(vw.iloc[last])
                atr = self.atr(day)
                if atr == atr and atr > 0:
                    ext = abs(px - vw_px) / atr > self.cfg.context.extended_vwap_atr
                    w = g.iloc[max(0, last - 29):last + 1]
                    consolidating = (w.high.max() - w.low.min()) < 0.25 * atr and len(w) >= 15
        if px == px and vw_px == vw_px:
            votes["vwap"] = 1 if px > vw_px * 1.0005 else -1 if px < vw_px * 0.9995 else 0
        else:
            votes["vwap"] = 0
        score = sum(votes.values())
        c = self.cfg.context
        bias = 1 if score >= c.bullish_at else -1 if score <= c.bearish_at else 0
        return {"bias": bias, "bias_label": LABEL[bias], "score": score, **{f"v_{k}": v for k, v in votes.items()},
                "price": px, "vwap": vw_px, "above_vwap": px > vw_px if px == px and vw_px == vw_px else None,
                "extended": bool(ext), "consolidating": bool(consolidating)}


def market(spy: dict, qqq: dict) -> int:
    """+1 / -1 when both indexes lean the same way or one does and the other
    is neutral; 0 when they are both neutral or disagree."""
    a, b = spy["bias"], qqq["bias"]
    if a == -b and a != 0:
        return 0
    return int(np.sign(a + b))


def confidence(direction: str, stock_bias: int, market_bias: int) -> str:
    s = 1 if direction == "long" else -1
    st, mk = s * stock_bias, s * market_bias
    if st > 0 and mk > 0:
        return "HIGH"
    if (st > 0 and mk == 0) or (st == 0 and mk > 0):
        return "MEDIUM"
    return "LOW"


def describe(symbol: str, direction: str, ctx: dict, spy: dict, qqq: dict) -> dict:
    """Everything a signal reports about its context, in one flat dict."""
    mk = market(spy, qqq)
    sym_bias = spy["bias"] if symbol == "SPY" else qqq["bias"] if symbol == "QQQ" else ctx["bias"]
    s = 1 if direction == "long" else -1
    return {"stock_bias": LABEL[sym_bias], "stock_score": ctx["score"],
            "spy_bias": spy["bias_label"], "qqq_bias": qqq["bias_label"], "market_bias": LABEL[mk],
            "vwap_side": "Above" if ctx["above_vwap"] else "Below" if ctx["above_vwap"] is False else "n/a",
            "vwap_supports": None if ctx["above_vwap"] is None else bool(ctx["above_vwap"]) == (s > 0),
            "extended": ctx["extended"], "consolidating": ctx["consolidating"],
            "v_daily": ctx["v_daily"], "v_h1": ctx["v_h1"], "v_m15": ctx["v_m15"], "v_vwap": ctx["v_vwap"],
            "confidence": confidence(direction, sym_bias, mk),
            "counter_bias": s * sym_bias < 0}
