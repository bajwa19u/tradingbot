"""Hand-built bar sequences with known-correct outcomes.

These exist so the strategy rules can be proven without a data connection,
and so that a future edit to config.yaml or the engine that silently breaks
a rule fails loudly instead.
"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

EASTERN = ZoneInfo("America/New_York")
DAY = datetime(2026, 9, 24)


def bars(rows: list[tuple[str, float, float, float, float, float]]) -> pd.DataFrame:
    """rows = (hh:mm, open, high, low, close, volume)"""
    index, data = [], []
    for hhmm, o, h, l, c, v in rows:
        hour, minute = map(int, hhmm.split(":"))
        index.append(datetime(DAY.year, DAY.month, DAY.day, hour, minute,
                              tzinfo=EASTERN))
        data.append({"open": o, "high": h, "low": l, "close": c, "volume": v})
    return pd.DataFrame(data, index=pd.DatetimeIndex(index))


# Opening range: high 100.5, low 99.5 (width 1.0). ATR passed in as 1.0.
_OPENING_RANGE = [
    ("09:30", 100.0, 100.5, 99.5, 100.1, 50_000),
    ("09:35", 100.1, 100.4, 99.8, 100.0, 40_000),
    ("09:40", 100.0, 100.45, 99.9, 100.3, 45_000),
]


def clean_long_setup() -> pd.DataFrame:
    """Break above 100.5, retest it, hammer confirmation, then run to target."""
    return bars(_OPENING_RANGE + [
        # break: closes well above the range on 1.3x+ volume
        ("09:45", 100.3, 101.30, 100.25, 101.20, 120_000),
        # retest: wicks back to the level and rejects — hammer
        ("09:50", 100.90, 100.98, 100.50, 100.95, 70_000),
        # follow-through to the 2R target (entry ~100.95, stop ~100.40)
        ("09:55", 100.95, 101.60, 100.90, 101.55, 80_000),
        ("10:00", 101.55, 102.40, 101.50, 102.30, 90_000),
        ("10:05", 102.30, 102.60, 102.10, 102.50, 60_000),
    ])


def retest_without_confirmation() -> pd.DataFrame:
    """Price returns to the level but the candle does not reject it — the rule
    that separates this setup from 'buying any pullback'. Must NOT signal."""
    return bars(_OPENING_RANGE + [
        ("09:45", 100.3, 101.30, 100.25, 101.20, 120_000),
        # comes back but closes weak in the middle of its own range: no hammer,
        # no engulfing
        ("09:50", 100.95, 101.00, 100.55, 100.70, 70_000),
        ("09:55", 100.70, 100.85, 100.60, 100.75, 50_000),
    ])


def failed_break() -> pd.DataFrame:
    """Break, then price closes back inside the range — setup is dead."""
    return bars(_OPENING_RANGE + [
        ("09:45", 100.3, 101.30, 100.25, 101.20, 120_000),
        ("09:50", 101.10, 101.15, 100.00, 100.10, 90_000),
        # even a textbook hammer after this must be ignored
        ("09:55", 100.90, 100.98, 100.50, 100.95, 70_000),
    ])


def low_volume_break() -> pd.DataFrame:
    """Same shape as the clean setup but the break bar has no volume."""
    return bars(_OPENING_RANGE + [
        ("09:45", 100.3, 101.30, 100.25, 101.20, 20_000),   # < 1.3x OR average
        ("09:50", 100.90, 100.98, 100.50, 100.95, 70_000),
    ])


def clean_short_setup() -> pd.DataFrame:
    """Mirror image: break below 99.5, retest, shooting star, run to target."""
    return bars(_OPENING_RANGE + [
        ("09:45", 99.70, 99.75, 98.70, 98.80, 120_000),
        # retest up into the level and reject — shooting star
        ("09:50", 99.10, 99.50, 99.02, 99.05, 70_000),
        ("09:55", 99.05, 99.10, 98.40, 98.45, 80_000),
        ("10:00", 98.45, 98.50, 97.60, 97.70, 90_000),
        ("10:05", 97.70, 97.90, 97.40, 97.50, 60_000),
    ])


def stopped_out_long() -> pd.DataFrame:
    """Valid signal that then fails — must record a ~-1R loss."""
    return bars(_OPENING_RANGE + [
        ("09:45", 100.3, 101.30, 100.25, 101.20, 120_000),
        ("09:50", 100.90, 100.98, 100.50, 100.95, 70_000),
        ("09:55", 100.95, 101.00, 100.20, 100.25, 80_000),   # takes out the stop
        ("10:00", 100.25, 100.40, 100.00, 100.10, 60_000),
    ])


def retest_too_late() -> pd.DataFrame:
    """Break runs away and only retests after the window expires."""
    trailing = [("09:45", 100.3, 101.30, 100.25, 101.20, 120_000)]
    price = 101.2
    for i in range(9):                      # 9 bars > max_bars_after_break (8)
        hhmm = f"{9 + (50 + i * 5) // 60}:{(50 + i * 5) % 60:02d}"
        trailing.append((hhmm, price, price + 0.3, price + 0.1, price + 0.25, 60_000))
        price += 0.25
    # only now does it come back
    trailing.append(("10:35", 100.90, 100.98, 100.50, 100.95, 70_000))
    return bars(_OPENING_RANGE + trailing)
