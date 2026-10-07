"""Break & Retest V1: the levels a session can break, and bar plumbing.

Previous-day levels come from the previous session's REGULAR hours only
(09:30-15:59), never from today's bars. Premarket levels come from 04:00-09:29
of today. Swing levels are found by the engine as the session prints them.

Every frame here is 1-minute bars, tz-aware US/Eastern, indexed by the bar's
START time, columns open/high/low/close/volume - the shape `data.py` returns.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

EASTERN = "America/New_York"
PRIORITY = ("pdh", "pdl", "pmh", "pml", "pdc", "swing_high", "swing_low")
OHLCV = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}


@dataclass
class Level:
    name: str                 # "pdh", "pmh", "swing_high@10:12", ...
    kind: str                 # pdh | pdl | pdc | pmh | pml | swing_high | swing_low
    price: float
    directions: tuple         # which way a break of it is traded: ("long",), ("short",) or both
    active: bool = True
    note: str = ""            # why it is inactive, when it is
    aliases: list = field(default_factory=list)   # merged levels at the same price

    @property
    def label(self) -> str:
        return self.kind.upper() if not self.kind.startswith("swing") else self.name


def minutes(ts) -> int:
    t = pd.Timestamp(ts)
    return t.hour * 60 + t.minute


def hhmm(s: str) -> int:
    h, m = s.split(":")
    return int(h) * 60 + int(m)


def split_day(day: pd.DataFrame, pre_start="04:00", open_="09:30"):
    """(premarket, regular session) for one day of extended 1-minute bars."""
    m = day.index.hour * 60 + day.index.minute
    pre = day[(m >= hhmm(pre_start)) & (m < hhmm(open_))]
    rth = day[(m >= hhmm(open_)) & (m < 16 * 60)]
    return pre, rth


def by_date(df: pd.DataFrame) -> dict:
    return {d: g for d, g in df.groupby(df.index.date)}


def prior_day_levels(prior_rth: pd.DataFrame) -> dict:
    """PDH / PDL / PDC from the previous session's regular hours."""
    if prior_rth is None or prior_rth.empty:
        return {}
    return {"pdh": float(prior_rth.high.max()), "pdl": float(prior_rth.low.min()),
            "pdc": float(prior_rth.close.iloc[-1])}


def premarket_levels(pre: pd.DataFrame) -> dict:
    if pre is None or pre.empty:
        return {}
    return {"pmh": float(pre.high.max()), "pml": float(pre.low.min())}


def open_state(open_px: float, pd_lv: dict) -> str:
    if not pd_lv:
        return "unknown"
    if open_px > pd_lv["pdh"]:
        return "above_pdh"
    if open_px < pd_lv["pdl"]:
        return "below_pdl"
    return "inside"


def build_levels(pd_lv: dict, pm_lv: dict, open_px: float, cfg) -> tuple[list[Level], str]:
    """The fixed levels for a session, with the PMH/PML activation rule applied.

    PMH/PML are ACTIVE only when the regular session opens above PDH or below
    PDL (`levels.pm_levels_need_outside_open`). Otherwise they are kept but
    marked inactive, so a setup off them is tracked and reported as rejected
    rather than silently ignored.
    """
    state = open_state(open_px, pd_lv)
    longs, shorts = set(cfg.levels.long), set(cfg.levels.short)
    out: list[Level] = []
    for kind, price in {**pd_lv, **pm_lv}.items():
        dirs = tuple(d for d, ok in (("long", kind in longs), ("short", kind in shorts)) if ok)
        if not dirs:
            continue
        lv = Level(kind, kind, price, dirs)
        if kind in ("pmh", "pml") and cfg.levels.pm_levels_need_outside_open and state == "inside":
            lv.active, lv.note = False, "inactive_level: opened inside PDH-PDL"
        out.append(lv)
    return merge(out, cfg.levels.merge_within_pct), state


def merge(levels: list[Level], within_pct: float) -> list[Level]:
    """Levels within `within_pct` of each other are one level. The one that
    survives is the highest-priority name; directions are unioned and the
    level is active if any merged member was."""
    rank = {k: i for i, k in enumerate(PRIORITY)}
    keep: list[Level] = []
    for lv in sorted(levels, key=lambda x: rank.get(x.kind, 99)):
        twin = next((k for k in keep if abs(k.price - lv.price) <= k.price * within_pct / 100), None)
        if twin is None:
            keep.append(lv)
            continue
        twin.aliases.append(lv.name)
        twin.directions = tuple(dict.fromkeys(twin.directions + lv.directions))
        if lv.active and not twin.active:
            twin.active, twin.note = True, ""
    return keep


def resample(rth: pd.DataFrame, tf: int) -> pd.DataFrame:
    """Regular-session bars of `tf` minutes, labelled by their start (09:30,
    09:35, ...). A bucket is only complete when its last minute exists; the
    caller decides what is complete, this just aggregates."""
    if tf == 1 or rth.empty:
        return rth
    return rth.resample(f"{tf}min", label="left", closed="left", origin="start_day",
                        offset="30min").agg(OHLCV).dropna(subset=["open"])


def vwap(rth: pd.DataFrame) -> pd.Series:
    """Session VWAP at each 1-minute bar's close (typical price x volume)."""
    tp = (rth.high + rth.low + rth.close) / 3
    v = rth.volume.clip(lower=0)
    cv = v.cumsum()
    return (tp * v).cumsum() / cv.where(cv > 0)
