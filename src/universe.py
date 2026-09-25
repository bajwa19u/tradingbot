"""Building the daily scan list.

Watchlist names are always included. On top of that, the day's most active
symbols are pulled from Alpaca's screener and every candidate is put through
the liquidity / volatility / relative-volume gates in config.yaml before it
is allowed anywhere near the strategy engine.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import numpy as np
import pandas as pd

from .data import MarketData, session_fraction_elapsed
from .indicators import atr, relative_volume


@dataclass
class Candidate:
    symbol: str
    price: float
    avg_daily_volume: float
    relative_volume: float
    atr_pct: float
    passed: bool
    reason: str = ""


def build_universe(md: MarketData, cfg, now: datetime | None = None
                   ) -> tuple[list[str], list[Candidate]]:
    u = cfg.universe
    now = now or datetime.now()

    symbols = list(dict.fromkeys(u.watchlist))
    if u.include_top_movers:
        try:
            movers = md.most_active(top=u.top_movers_count * 3)
            for sym in movers:
                if sym not in symbols:
                    symbols.append(sym)
        except Exception:
            pass  # screener is a bonus, never a hard dependency

    from .data import trading_days_back
    daily = md.daily_bars(symbols, start=trading_days_back(40))

    elapsed = max(session_fraction_elapsed(now), 0.05)
    candidates: list[Candidate] = []

    for sym in symbols:
        df = daily.get(sym)
        if df is None or len(df) < 21:
            candidates.append(Candidate(sym, 0, 0, 0, 0, False, "insufficient_history"))
            continue

        history = df.iloc[:-1]
        today = df.iloc[-1]
        price = float(today["close"])
        adv = float(history["volume"].tail(20).mean())
        a = float(atr(history, 14).iloc[-1])
        atr_pct = 100 * a / price if price else 0.0
        rvol = relative_volume(float(today["volume"]), adv, elapsed)

        reason = ""
        if not (u.min_price <= price <= u.max_price):
            reason = "price_out_of_range"
        elif adv < u.min_avg_daily_volume:
            reason = "illiquid"
        elif atr_pct < u.min_atr_pct:
            reason = "not_volatile_enough"
        elif rvol < u.min_relative_volume:
            reason = f"relative_volume {rvol:.2f} < {u.min_relative_volume}"

        candidates.append(
            Candidate(sym, round(price, 2), adv, round(rvol, 2),
                      round(atr_pct, 2), reason == "", reason)
        )

    passed = [c for c in candidates if c.passed]
    # Highest relative volume first — that is where the clean breaks live
    passed.sort(key=lambda c: c.relative_volume, reverse=True)

    watchlist_set = set(u.watchlist)
    keep = [c.symbol for c in passed if c.symbol in watchlist_set]
    extras = [c.symbol for c in passed if c.symbol not in watchlist_set]
    keep.extend(extras[: u.top_movers_count])
    return keep, candidates
