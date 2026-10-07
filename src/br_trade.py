"""Break & Retest V1: sizing a signal, and following a trade - and the
market after it ends.

Fill conventions (the house rules):
  entry   the confirmation candle's close, plus slippage against us
  stop    a resting order: hit when a bar's low (long) / high (short) reaches
          it; filled at the stop, plus slippage. On a bar that touches both
          stop and target, the STOP wins.
  target  a resting limit: hit when a bar's high / low reaches it; no slippage
  time    still open at `session.time_exit`: out at that bar's close, plus slippage

Trades are always followed on 1-minute bars, whatever timeframe found them.
R is the trade's own stop distance; dollars assume `risk.risk_dollars` at risk.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from .br_levels import hhmm


def stop_base(direction: str, level: float, touch_extreme: float | None, ref: str) -> float:
    if ref == "retest_extreme" and touch_extreme is not None:
        return min(level, touch_extreme) if direction == "long" else max(level, touch_extreme)
    return level


def plan(direction: str, close: float, level: float, touch_extreme: float | None, cfg,
         stop_pct: float | None = None, stop_px: float | None = None) -> dict:
    """Entry, stop, size and target for a confirmed setup."""
    s = 1 if direction == "long" else -1
    r = cfg.risk
    entry = close * (1 + s * r.slippage_pct / 100)
    if stop_px is None:
        pct = r.stop_buffer_pct if stop_pct is None else stop_pct
        stop_px = stop_base(direction, level, touch_extreme, r.stop_ref) * (1 - s * pct / 100)
    rps = s * (entry - stop_px)
    if not rps > 0:
        return {}
    shares = math.floor(r.risk_dollars / rps)
    target = entry + s * r.target_r * rps
    return {"entry": entry, "stop": stop_px, "risk_per_share": rps, "shares": shares,
            "target": target, "target_r": r.target_r, "dollar_risk": shares * rps,
            "potential_profit": shares * r.target_r * rps,
            "stop_pct_of_entry": 100 * rps / entry}


def _first(mask: np.ndarray) -> int:
    idx = np.flatnonzero(mask)
    return int(idx[0]) if len(idx) else len(mask)


def run_exit(h, l, c, s: int, entry: float, stop: float, target: float | None,
             slip: float) -> tuple[float, int, str]:
    """(R, index of the exit bar, reason) over arrays that start at entry and
    end at the time exit. Stop wins a tie."""
    n = len(c)
    if n == 0:
        return 0.0, -1, "no_data"
    rps = s * (entry - stop)
    ks = _first(l <= stop) if s > 0 else _first(h >= stop)
    kt = n if target is None else (_first(h >= target) if s > 0 else _first(l <= target))
    if ks < n and ks <= kt:
        return s * (stop * (1 - s * slip) - entry) / rps, ks, "stop"
    if kt < n:
        return s * (target - entry) / rps, kt, "target"
    return s * (c[-1] * (1 - s * slip) - entry) / rps, n - 1, "time"


def run_trail(h, l, c, s: int, entry: float, stop: float, arm_r: float, slip: float) -> float:
    """Fixed stop until `arm_r` is reached, then a stop 1R behind the best
    price seen (never below +1R once armed)."""
    rps = s * (entry - stop)
    cur, armed, best = stop, False, entry
    for k in range(len(c)):
        if (l[k] <= cur) if s > 0 else (h[k] >= cur):
            return s * (cur * (1 - s * slip) - entry) / rps
        fav = h[k] if s > 0 else l[k]
        best = max(best, fav) if s > 0 else min(best, fav)
        if not armed and s * (best - entry) >= arm_r * rps:
            armed = True
        if armed:
            cur = max(cur, best - rps) if s > 0 else min(cur, best + rps)
    return s * (c[-1] * (1 - s * slip) - entry) / rps if len(c) else 0.0


def simulate(rth: pd.DataFrame, signal_ts, direction: str, p: dict, cfg,
             level: float | None = None, touch_extreme: float | None = None,
             atr: float | None = None, alternatives: bool = True) -> dict:
    """Follow one planned trade (`plan()` output) through today's 1-minute
    regular-session bars from `signal_ts` (the moment the signal is known)."""
    s = 1 if direction == "long" else -1
    slip = cfg.risk.slippage_pct / 100
    t_exit = hhmm(cfg.session.time_exit)
    after = rth[(rth.index >= pd.Timestamp(signal_ts))]
    m_after = after.index.hour * 60 + after.index.minute
    path = after[m_after < t_exit]                 # bars the trade can live through
    if path.empty or not p:
        return {"outcome": "no_data"}
    h, l, c = (path[x].to_numpy(float) for x in ("high", "low", "close"))
    entry, stop, target, rps = p["entry"], p["stop"], p["target"], p["risk_per_share"]
    r, k, why = run_exit(h, l, c, s, entry, stop, target, slip)
    exit_ts = path.index[k]
    exit_px = {"stop": stop * (1 - s * slip), "target": target,
               "time": c[k] * (1 - s * slip)}.get(why, np.nan)
    live = slice(0, k + 1)
    fav = (h[live].max() if s > 0 else l[live].min())
    adv = (l[live].min() if s > 0 else h[live].max())
    # The whole rest of the session (to the bell), regardless of the exit.
    rest = rth[rth.index >= pd.Timestamp(signal_ts)]
    fav_eod = rest.high.max() if s > 0 else rest.low.min()
    lvl = lambda R: entry + s * R * rps                                  # noqa: E731
    hit = lambda frame, R: bool(((frame.high >= lvl(R)) if s > 0 else (frame.low <= lvl(R))).any())  # noqa: E731
    t2 = None
    two = (rest.high >= lvl(2)) if s > 0 else (rest.low <= lvl(2))
    if two.any():
        t2 = rest.index[int(np.argmax(two.to_numpy()))]
    out = {"outcome": why, "exit_ts": exit_ts, "exit_px": exit_px, "r": r,
           "pnl": p["shares"] * r * rps, "win": r > 0,
           "duration_min": int((exit_ts - pd.Timestamp(signal_ts)).total_seconds() // 60) + 1,
           "mfe_r": s * (fav - entry) / rps, "mae_r": s * (adv - entry) / rps,
           "high_after_entry": float(h[live].max()), "low_after_entry": float(l[live].min()),
           "mfe_r_eod": s * (fav_eod - entry) / rps,
           "reached_1r": hit(path.iloc[live], 1), "reached_2r": why == "target",
           "reached_2r_eod": t2 is not None, "t_2r": t2,
           "beyond_2r_eod": max(0.0, s * (fav_eod - entry) / rps - 2.0)}
    out.update(_post_exit(rth, exit_ts, why, s, entry, rps, target, cfg))
    if alternatives:
        out.update(_alternatives(h, l, c, s, entry, stop, slip, cfg, direction, level,
                                 touch_extreme, atr))
    return out


def _window(rth: pd.DataFrame, t0, minutes: int) -> pd.DataFrame:
    t0 = pd.Timestamp(t0)
    return rth[(rth.index > t0) & (rth.index <= t0 + pd.Timedelta(minutes=minutes))]


def _post_exit(rth, exit_ts, why, s, entry, rps, target, cfg) -> dict:
    """What the market did AFTER the trade ended. This is the evidence for
    whether the stop was too tight and whether 2R left money behind."""
    out = {}
    hz = list(cfg.analysis.post_exit_minutes)
    fav_of = lambda w: (w.high.max() if s > 0 else w.low.min())     # noqa: E731
    adv_of = lambda w: (w.low.min() if s > 0 else w.high.max())     # noqa: E731
    if why == "stop":
        for m in hz:
            w = _window(rth, exit_ts, m)
            if w.empty:
                continue
            best = s * (fav_of(w) - entry) / rps
            out[f"sl_mfe_{m}"] = best
            out[f"sl_entry_{m}"] = best >= 0
            out[f"sl_1r_{m}"] = best >= 1
            out[f"sl_2r_{m}"] = best >= 2
        rest = rth[rth.index > pd.Timestamp(exit_ts)]
        if len(rest):
            best = s * (fav_of(rest) - entry) / rps
            out.update(sl_mfe_eod=best, sl_entry_eod=best >= 0, sl_1r_eod=best >= 1, sl_2r_eod=best >= 2)
        last = hz[-1]
        if out.get(f"sl_2r_{last}"):
            out["sl_class"] = "STOP-OUT -> 2R RECOVERY"
        elif out.get(f"sl_entry_{last}"):
            out["sl_class"] = "POSSIBLY TOO-TIGHT STOP"
        else:
            out["sl_class"] = "TRUE FAILURE"
    elif why == "target":
        for m in hz:
            w = _window(rth, exit_ts, m)
            if w.empty:
                continue
            out[f"tp_extra_r_{m}"] = max(0.0, s * (fav_of(w) - target) / rps)
            out[f"tp_3r_{m}"] = s * (fav_of(w) - entry) / rps >= 3
            out[f"tp_4r_{m}"] = s * (fav_of(w) - entry) / rps >= 4
        w5 = _window(rth, exit_ts, min(hz))
        out["tp_reversed_fast"] = bool(len(w5)) and s * (adv_of(w5) - entry) / rps <= 1.0
        rest = rth[rth.index > pd.Timestamp(exit_ts)]
        if len(rest):
            out["tp_extra_r_eod"] = max(0.0, s * (fav_of(rest) - target) / rps)
    return out


def _alternatives(h, l, c, s, entry, stop, slip, cfg, direction, level, touch_extreme, atr) -> dict:
    """The same entry with other stops (each with its own 2R) and other
    targets on the baseline stop. Exploratory: the report says how many
    variants were looked at."""
    out = {}
    rps = s * (entry - stop)
    tr = cfg.risk.target_r
    if level is not None:
        base = stop_base(direction, level, touch_extreme, cfg.risk.stop_ref)
        alts = {f"stop_{p:g}pct": base * (1 - s * p / 100) for p in cfg.analysis.alt_stop_pcts}
        if atr and atr == atr:
            alts[f"stop_{cfg.analysis.alt_stop_atr_mult:g}atr"] = base - s * cfg.analysis.alt_stop_atr_mult * atr
        for name, sp in alts.items():
            r_ps = s * (entry - sp)
            if r_ps > 0:
                out[f"alt_{name}"] = run_exit(h, l, c, s, entry, sp, entry + s * tr * r_ps, slip)[0]
    for t in cfg.analysis.alt_targets_r:
        out[f"alt_target_{t:g}r"] = run_exit(h, l, c, s, entry, stop, entry + s * t * rps, slip)[0]
    out["alt_target_none"] = run_exit(h, l, c, s, entry, stop, None, slip)[0]
    out["alt_trail_after_2r"] = run_trail(h, l, c, s, entry, stop, 2.0, slip)
    return out
