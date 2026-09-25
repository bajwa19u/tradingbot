"""Intraday backtester for the break-and-retest strategy.

This walks bars forward one at a time and only ever looks at data the engine
would have had in real time — no peeking at the bar that has not closed yet.
Entries happen at the close of the confirmation candle (plus slippage), and
exits are resolved bar by bar against stop, target, breakeven and time stop.

Where a single bar touches both the stop and the target, the stop is assumed
to fill first. That is the pessimistic assumption and it keeps the results
honest.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, asdict, field
from datetime import datetime, time
from typing import Any

import numpy as np
import pandas as pd

from .indicators import resample_bars
from .strategy.break_retest import (
    BreakRetestEngine,
    Signal,
    compute_daily_atr,
)


class _Bar:
    """Minimal stand-in for a pandas row.

    At 1-minute resolution the backtest touches millions of bars, and
    `df.loc[ts]` builds a fresh Series every time. This exposes just the
    mapping access the engine uses, which is roughly 50x cheaper.
    """
    __slots__ = ("name", "_v")

    def __init__(self, ts, o, h, l, c, v):
        self.name = ts
        self._v = {"open": o, "high": h, "low": l, "close": c, "volume": v}

    def __getitem__(self, key):
        return self._v[key]


@dataclass
class Trade:
    symbol: str
    direction: str
    entry_time: datetime
    entry: float
    stop: float
    target: float
    exit_time: datetime | None = None
    exit: float | None = None
    exit_reason: str = ""
    r_multiple: float = 0.0
    shares: int = 0
    pnl: float = 0.0
    pattern: str = ""
    bars_held: int = 0
    mae_r: float = 0.0          # worst drawdown in R while open
    mfe_r: float = 0.0          # best excursion in R while open
    entry_hour: int = 0         # for time-of-day analysis
    bars_to_retest: int = 0

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["entry_time"] = self.entry_time.isoformat()
        d["exit_time"] = self.exit_time.isoformat() if self.exit_time else None
        return d


class Backtester:
    def __init__(self, cfg):
        self.cfg = cfg
        self.slippage = float(cfg.backtest.slippage_pct) / 100.0
        self.commission = float(cfg.backtest.commission_per_share)

    # -----------------------------------------------------------------
    def run(self, bars_by_symbol: dict[str, pd.DataFrame],
            daily_by_symbol: dict[str, pd.DataFrame]) -> dict[str, Any]:
        trades: list[Trade] = []
        rejections: list[dict] = []
        days_traded: set = set()
        htf = {sym: _htf_trend(df, self.cfg) for sym, df in bars_by_symbol.items()}

        # Group everything by trading day so the daily trade cap is real
        all_days = sorted({
            d for df in bars_by_symbol.values() if len(df)
            for d in df.index.normalize().unique()
        })

        for day in all_days:
            day_trades, day_rejections = self._run_day(
                day, bars_by_symbol, daily_by_symbol, htf
            )
            trades.extend(day_trades)
            rejections.extend(day_rejections)
            if day_trades:
                days_traded.add(day)

        return self._summarize(trades, rejections, len(all_days))

    # -----------------------------------------------------------------
    def _run_day(self, day, bars_by_symbol, daily_by_symbol,
                 htf_by_symbol: dict | None = None
                 ) -> tuple[list[Trade], list[dict]]:
        cfg = self.cfg
        filters = cfg.strategy.filters
        trades: list[Trade] = []
        rejections: list[dict] = []
        realized_R = 0.0
        taken_today = 0
        won_today = False
        stop_after_win = bool(filters.get("stop_after_first_win", False))

        htf_by_symbol = htf_by_symbol or {}
        engines: dict[str, BreakRetestEngine] = {}
        open_trades: dict[str, tuple[Trade, dict]] = {}
        per_symbol_count: dict[str, int] = {}

        day_slices = {}
        for sym, df in bars_by_symbol.items():
            if not len(df):
                continue
            sl = df[df.index.normalize() == day]
            if len(sl) >= 4:
                day_slices[sym] = sl

        if not day_slices:
            return trades, rejections

        for sym, sl in day_slices.items():
            daily = daily_by_symbol.get(sym)
            prior = daily[daily.index.normalize() < day] if daily is not None \
                and len(daily) else None
            a = compute_daily_atr(prior) if prior is not None else 0.0
            engines[sym] = BreakRetestEngine(sym, cfg, a,
                                             htf_trend=htf_by_symbol.get(sym))

        # One sorted stream of (timestamp, symbol, bar) instead of scanning
        # every symbol at every timestamp.
        events: list = []
        last_bar: dict[str, _Bar] = {}
        for sym, sl in day_slices.items():
            for row in sl.itertuples():
                bar = _Bar(row.Index, row.open, row.high, row.low,
                           row.close, row.volume)
                events.append((row.Index, sym, bar))
                last_bar[sym] = bar
        events.sort(key=lambda e: e[0])

        for ts, sym, bar in events:
            # 1. manage this symbol's open position first
            if sym in open_trades:
                trade, meta = open_trades[sym]
                if self._update_open_trade(trade, meta, bar, ts):
                    trades.append(trade)
                    realized_R += trade.r_multiple
                    if trade.r_multiple > 0:
                        won_today = True
                    del open_trades[sym]
                continue

            # 2. daily guards
            if realized_R <= -abs(cfg.risk.max_daily_loss_R):
                continue
            if taken_today >= filters.max_trades_per_day:
                continue
            if stop_after_win and won_today:
                continue
            if per_symbol_count.get(sym, 0) >= filters.max_trades_per_symbol_per_day:
                continue

            # 3. look for a new signal
            signal = engines[sym].on_bar(bar)
            if signal is None or signal.shares <= 0:
                continue
            trade, meta = self._open_trade(signal)
            open_trades[sym] = (trade, meta)
            per_symbol_count[sym] = per_symbol_count.get(sym, 0) + 1
            taken_today += 1

        # 4. flatten anything still open at the time stop
        for sym, (trade, meta) in open_trades.items():
            last = last_bar[sym]
            self._close_trade(trade, meta, float(last["close"]), last.name,
                              "time_stop")
            trades.append(trade)

        for engine in engines.values():
            for rej in engine.rejections:
                rejections.append({
                    "symbol": rej.symbol,
                    "timestamp": rej.timestamp.isoformat(),
                    "reason": rej.reason,
                    "detail": rej.detail,
                })
        return trades, rejections

    # -----------------------------------------------------------------
    def _open_trade(self, signal: Signal) -> tuple[Trade, dict]:
        slip = self.slippage
        if signal.direction == "long":
            fill = signal.entry * (1 + slip)
        else:
            fill = signal.entry * (1 - slip)
        risk_per_share = abs(fill - signal.stop)
        # Under momentum management the target is not known at entry - it is
        # decided by how the first few candles behave. Start it out of reach
        # so the fixed-target check cannot close the trade first.
        target = signal.target
        if str(self.cfg.risk.get("exit_style", "fixed")) == "momentum":
            reach = 999.0 * risk_per_share
            target = fill + reach if signal.direction == "long" else fill - reach

        trade = Trade(
            symbol=signal.symbol,
            direction=signal.direction,
            entry_time=signal.timestamp,
            entry=round(fill, 4),
            stop=signal.stop,
            target=target,
            shares=signal.shares,
            pattern=signal.pattern,
            entry_hour=signal.timestamp.hour,
            bars_to_retest=signal.bars_to_retest,
        )
        meta = {
            "risk_per_share": risk_per_share if risk_per_share > 0 else 1e-9,
            "moved_to_breakeven": False,
            "partial_taken": False,
            "partial_r": 0.0,
            "remaining": 1.0,
            "peak_R": 0.0,
            "decided": None,
            "trailing": False,
            "original_stop": signal.stop,
        }
        return trade, meta

    def _update_open_trade(self, trade: Trade, meta: dict, bar: pd.Series,
                           ts: datetime) -> bool:
        cfg = self.cfg.risk
        rps = meta["risk_per_share"]
        trade.bars_held += 1
        high, low = float(bar["high"]), float(bar["low"])

        if trade.direction == "long":
            trade.mfe_r = max(trade.mfe_r, (high - trade.entry) / rps)
            trade.mae_r = min(trade.mae_r, (low - trade.entry) / rps)
            hit_stop = low <= trade.stop
            hit_target = high >= trade.target
            reached_1R = high >= trade.entry + rps
        else:
            trade.mfe_r = max(trade.mfe_r, (trade.entry - low) / rps)
            trade.mae_r = min(trade.mae_r, (trade.entry - high) / rps)
            hit_stop = high >= trade.stop
            hit_target = low <= trade.target
            reached_1R = low <= trade.entry - rps

        # Pessimistic: if both are touched in the same bar, the stop wins
        if hit_stop:
            if meta.get("trailing"):
                reason = "trail"
            elif meta["moved_to_breakeven"]:
                reason = "breakeven"
            else:
                reason = "stop"
            self._close_trade(trade, meta, trade.stop, ts, reason)
            return True
        if hit_target:
            self._close_trade(trade, meta, trade.target, ts, "target")
            return True

        if str(cfg.get("exit_style", "fixed")) == "momentum":
            return self._momentum_exit(trade, meta, bar, ts, high, low, rps)

        if reached_1R and cfg.get("partial_at_1R", False) and not meta["partial_taken"]:
            # Bank half the position at 1R, run the rest. Recorded as a
            # weighted R so the trade's final number reflects both exits.
            meta["partial_taken"] = True
            meta["partial_r"] = 1.0
            meta["remaining"] = 0.5
            trade.stop = trade.entry
            meta["moved_to_breakeven"] = True

        if cfg.breakeven_after_1R and reached_1R and not meta["moved_to_breakeven"]:
            trade.stop = trade.entry
            meta["moved_to_breakeven"] = True

        # Time stop
        flatten_at = _parse_time(self.cfg.strategy.session.flatten_at)
        if ts.time() >= flatten_at:
            self._close_trade(trade, meta, float(bar["close"]), ts, "time_stop")
            return True
        return False

    def _momentum_exit(self, trade: Trade, meta: dict, bar, ts: datetime,
                       high: float, low: float, rps: float) -> bool:
        """Discretionary-style exit management.

        The trade is watched for `observe_bars` candles and then handled
        according to how fast it moved:

          fast   — reached `fast_target_R` inside the window: the stop is
                   lifted to that level and then trailed behind each candle,
                   letting the move run instead of capping it.
          medium — got past `slow_target_R` but never convincingly through
                   `fast_target_R`: take the money at `slow_target_R`.
          slow   — never got going: target drops to `slow_target_R`.

        Separately, the first time price comes back and touches the entry
        after having moved away, the stop is moved to entry. One retest is
        allowed, not two.
        """
        risk = self.cfg.risk
        observe = int(risk.get("observe_bars", 3))
        fast_R = float(risk.get("fast_target_R", 2.0))
        slow_R = float(risk.get("slow_target_R", 1.5))
        long = trade.direction == "long"

        def price_at(r: float) -> float:
            return trade.entry + r * rps if long else trade.entry - r * rps

        high_R = (high - trade.entry) / rps if long else (trade.entry - low) / rps
        low_R = (low - trade.entry) / rps if long else (trade.entry - high) / rps
        meta["peak_R"] = max(meta.get("peak_R", 0.0), high_R)

        # --- one retest of entry, then the stop sits at entry ---------------
        if (not meta["moved_to_breakeven"]
                and meta["peak_R"] >= float(risk.get("retest_arm_R", 0.3))
                and low_R <= 0):
            trade.stop = trade.entry
            meta["moved_to_breakeven"] = True

        # --- momentum assessment inside the observation window --------------
        if not meta.get("decided"):
            if high_R >= fast_R:
                # Moved fast. Protect at the fast target and trail from here.
                trade.stop = price_at(fast_R) if long else price_at(fast_R)
                trade.target = price_at(99.0)          # effectively uncapped
                meta["trailing"] = True
                meta["decided"] = "fast"
            elif trade.bars_held >= observe:
                # Window is up and it never ran. Settle for the smaller target.
                trade.target = price_at(slow_R)
                meta["decided"] = "slow"
            elif high_R >= slow_R:
                # Got past the smaller target but has not cleared the big one.
                trade.target = price_at(slow_R)
                meta["decided"] = "medium"

        # --- trail behind each completed candle once running ----------------
        if meta.get("trailing"):
            trail = float(bar["low"]) if long else float(bar["high"])
            trade.stop = max(trade.stop, trail) if long else min(trade.stop, trail)

        flatten_at = _parse_time(self.cfg.strategy.session.flatten_at)
        if ts.time() >= flatten_at:
            self._close_trade(trade, meta, float(bar["close"]), ts, "time_stop")
            return True
        return False

    def _close_trade(self, trade: Trade, meta: dict, price: float,
                     ts: datetime, reason: str) -> None:
        slip = self.slippage
        fill = price * (1 - slip) if trade.direction == "long" else price * (1 + slip)
        trade.exit = round(fill, 4)
        trade.exit_time = ts
        trade.exit_reason = reason
        rps = meta["risk_per_share"]
        if trade.direction == "long":
            move = fill - trade.entry
        else:
            move = trade.entry - fill
        final_r = move / rps
        remaining = meta.get("remaining", 1.0)
        blended = (1.0 - remaining) * meta.get("partial_r", 0.0) + remaining * final_r
        trade.r_multiple = round(blended, 3)
        trade.pnl = round(blended * rps * trade.shares
                          - self.commission * trade.shares * 2, 2)

    # -----------------------------------------------------------------
    def _summarize(self, trades: list[Trade], rejections: list[dict],
                   n_days: int) -> dict[str, Any]:
        if not trades:
            return {
                "trades": [], "rejections": rejections, "stats": {
                    "n_trades": 0, "trading_days": n_days,
                    "note": "No setups met every rule in this period.",
                },
            }

        r = np.array([t.r_multiple for t in trades])
        pnl = np.array([t.pnl for t in trades])
        wins = r > 0
        equity = self.cfg.risk.account_equity
        curve = equity + np.cumsum(pnl)
        peak = np.maximum.accumulate(np.concatenate([[equity], curve]))
        dd = (np.concatenate([[equity], curve]) - peak) / peak
        gross_win = pnl[pnl > 0].sum()
        gross_loss = -pnl[pnl < 0].sum()

        by_reason: dict[str, int] = {}
        for t in trades:
            by_reason[t.exit_reason] = by_reason.get(t.exit_reason, 0) + 1
        rej_counts: dict[str, int] = {}
        for rej in rejections:
            rej_counts[rej["reason"]] = rej_counts.get(rej["reason"], 0) + 1

        stats = {
            "buckets": _buckets(trades),
            "n_trades": len(trades),
            "trading_days": n_days,
            "trades_per_day": round(len(trades) / n_days, 2) if n_days else 0,
            "win_rate_pct": round(100 * wins.mean(), 1),
            "avg_R": round(float(r.mean()), 3),
            "median_R": round(float(np.median(r)), 3),
            "expectancy_R": round(float(r.mean()), 3),
            "total_R": round(float(r.sum()), 2),
            "total_pnl": round(float(pnl.sum()), 2),
            "return_pct": round(100 * float(pnl.sum()) / equity, 2),
            "profit_factor": round(float(gross_win / gross_loss), 2)
            if gross_loss > 0 else float("inf"),
            "max_drawdown_pct": round(100 * float(dd.min()), 2),
            "avg_win_R": round(float(r[wins].mean()), 3) if wins.any() else 0.0,
            "avg_loss_R": round(float(r[~wins].mean()), 3) if (~wins).any() else 0.0,
            "largest_win_R": round(float(r.max()), 2),
            "largest_loss_R": round(float(r.min()), 2),
            "max_consecutive_losses": _max_streak(r <= 0),
            "avg_bars_held": round(float(np.mean([t.bars_held for t in trades])), 1),
            "exit_reasons": by_reason,
            "rejection_reasons": rej_counts,
            "sharpe_of_R": round(float(r.mean() / r.std()), 2)
            if r.std() > 0 else 0.0,
        }
        return {
            "trades": [t.to_dict() for t in trades],
            "rejections": rejections,
            "equity_curve": [round(float(x), 2) for x in curve],
            "stats": stats,
        }


def _htf_trend(df: pd.DataFrame, cfg):
    """+1/-1 trend from higher-timeframe bars, e.g. the 1-hour chart.

    The series index is pushed forward by one HTF bar so that at any moment
    only bars that have actually CLOSED are visible. Without that shift the
    backtest would be reading the close of a candle still forming, which is
    look-ahead and would flatter every result.
    """
    if df is None or not len(df):
        return None
    minutes = int(cfg.strategy.get("htf_minutes", 60))
    period = int(cfg.strategy.get("htf_ema", 20))
    htf = resample_bars(df, minutes)
    if len(htf) < period + 1:
        return None
    ema = htf["close"].ewm(span=period, adjust=False).mean()
    trend = np.sign(htf["close"] - ema)
    trend.index = trend.index + pd.Timedelta(minutes=minutes)
    return trend


def _buckets(trades: list[Trade]) -> dict[str, list[dict]]:
    """Expectancy sliced by attribute.

    This is what turns a backtest from a verdict into a diagnosis: it says
    WHICH trades lose, not just that the average loses. Buckets with fewer
    than 20 trades are reported but should not be acted on — slicing 900
    trades enough ways will always surface a flattering subset by chance.
    """
    def group(key_fn, label_fn=str):
        out: dict = {}
        for t in trades:
            out.setdefault(key_fn(t), []).append(t.r_multiple)
        rows = []
        for key, rs in sorted(out.items(), key=lambda kv: str(kv[0])):
            arr = np.array(rs)
            rows.append({
                "bucket": label_fn(key),
                "n": len(arr),
                "expectancy_R": round(float(arr.mean()), 3),
                "win_rate_pct": round(100 * float((arr > 0).mean()), 1),
                "total_R": round(float(arr.sum()), 2),
                "reliable": len(arr) >= 20,
            })
        return rows

    return {
        "by_hour": group(lambda t: t.entry_hour, lambda h: f"{h:02d}:00-{h:02d}:59"),
        "by_direction": group(lambda t: t.direction),
        "by_pattern": group(lambda t: t.pattern),
        "by_symbol": group(lambda t: t.symbol),
        "by_bars_to_retest": group(lambda t: min(t.bars_to_retest, 6),
                                   lambda b: f"{b}+" if b == 6 else str(b)),
        "by_exit": group(lambda t: t.exit_reason),
    }


def _max_streak(mask: np.ndarray) -> int:
    best = cur = 0
    for value in mask:
        cur = cur + 1 if value else 0
        best = max(best, cur)
    return int(best)


def _parse_time(value) -> time:
    if isinstance(value, time):
        return value
    hours, minutes = str(value).split(":")
    return time(int(hours), int(minutes))
