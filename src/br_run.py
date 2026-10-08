"""Break & Retest V1: from minute bars to candidates, signals and trades.

Shared by the historical backtest (`br_backtest`) and the end-of-day replay of
a live session (`br_daily`), so the daily report is the same code as the
baseline.

Pipeline for one session and one symbol:
  1. levels: PDH/PDL/PDC from the previous session's regular hours,
     PMH/PML from 04:00-09:29, the PMH/PML activation rule
  2. the engine, once per setup timeframe, on bars that CLOSE by 11:30
  3. every confirmed setup is sized and followed on 1-minute bars
  4. a VARIANT decides which confirmed setups become signals: its timeframes,
     then the blockers (inactive level, gap break, counter-bias if enabled),
     one open trade per symbol, a daily cap. "combined" = every timeframe,
     first confirmation per symbol/level/direction - what the live bot does.
  5. rejected setups are followed too. A blocked-but-complete setup is
     simulated exactly like a trade; a setup that never completed is
     simulated as if bought at the breakout close (`hypo = at_break`), to ask
     whether waiting for the retest cost money.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from . import br_context as bc
from .br_engine import run_day
from .br_levels import build_levels, hhmm, premarket_levels, prior_day_levels, resample, split_day
from .br_trade import plan, simulate

FAILURES = ("failed_breakout", "retest_timeout", "confirm_timeout", "window_closed")


def level_key(symbol, date, direction, kind, price, pct: float = 0.10) -> tuple:
    """One level, whatever bar size saw it. A swing pivot is named after the
    bar it printed on, which differs between 1-, 3- and 5-minute bars, so
    levels are identified by kind and price (to within `pct` %), not by name."""
    fam = "swing" if str(kind).startswith("swing") else kind
    return (symbol, str(date), direction, fam, round(math.log(price) / math.log1p(pct / 100)))


def _keys(df: pd.DataFrame, cfg) -> pd.Series:
    pct = cfg.levels.merge_within_pct
    return pd.Series([level_key(r.symbol, r.date, r.direction, r.level_kind, r.level, pct)
                      for r in df.itertuples()], index=df.index, dtype=object)


def sessions(data: dict[str, pd.DataFrame], min_rth_bars: int = 300, partial_day=None) -> dict[str, dict]:
    """{symbol: {date: extended 1-minute day}}, complete regular sessions only
    - except `partial_day`, today while it is still trading, kept as far as it goes."""
    out = {}
    for s, df in data.items():
        days = {}
        for d, g in df.groupby(df.index.date):
            _, rth = split_day(g)
            if len(rth) >= min_rth_bars or (d == partial_day and len(rth)):
                days[d] = g
        out[s] = days
    return out


def books(sess: dict[str, dict], daily: dict[str, pd.DataFrame], cfg) -> dict[str, bc.Book]:
    out = {}
    for s, days in sess.items():
        if not days:
            continue
        rth = pd.concat([split_day(g)[1] for _, g in sorted(days.items())])
        out[s] = bc.Book(rth, daily.get(s, pd.DataFrame(columns=["open", "high", "low", "close"])), cfg)
    return out


def day_setup(days: dict, d, cfg) -> dict | None:
    """Levels and bars for one symbol-session, or None if it cannot be traded
    (no previous session to take levels from)."""
    dates = sorted(days)
    i = dates.index(d)
    if i == 0:
        return None
    pre, rth = split_day(days[d], cfg.session.premarket_start, cfg.session.open)
    _, prior_rth = split_day(days[dates[i - 1]])
    pd_lv, pm_lv = prior_day_levels(prior_rth), premarket_levels(pre)
    if not pd_lv:
        return None
    levels, state = build_levels(pd_lv, pm_lv, float(rth.open.iloc[0]), cfg)
    prev_close = float(pre.close.iloc[-1]) if len(pre) else pd_lv["pdc"]
    return {"pre": pre, "rth": rth, "levels": levels, "open_state": state, "prev_close": prev_close,
            "lv": {**pd_lv, **pm_lv}, "day": days[d], "pm_bars": len(pre)}


def candidates_for(symbol: str, d, setup: dict, cfg) -> list:
    out = []
    until = hhmm(cfg.session.signals_until)
    for tf in cfg.timeframes.setup:
        bars = resample(setup["rth"], tf)
        out += run_day(symbol, tf, d, setup["levels"], bars, cfg, setup["prev_close"], until)
    return out


def context_for(bk: dict, symbol: str, direction: str, t) -> dict:
    spy = bk["SPY"].at(t) if "SPY" in bk else _blank()
    qqq = bk["QQQ"].at(t) if "QQQ" in bk else _blank()
    me = bk[symbol].at(t) if symbol in bk else _blank()
    return bc.describe(symbol, direction, me, spy, qqq)


def _blank() -> dict:
    return {"bias": 0, "bias_label": "Neutral", "score": 0, "v_daily": 0, "v_h1": 0, "v_m15": 0,
            "v_vwap": 0, "above_vwap": None, "extended": False, "consolidating": False}


def evaluate(cands: list, setups: dict, bk: dict, cfg, extras: bool = True) -> pd.DataFrame:
    """One row per candidate: setup facts, context, the trade (or the
    hypothetical one for a setup that never completed)."""
    rows = []
    for c in cands:
        st = setups[(c.symbol, c.date)]
        row = c.to_dict()
        row.update(open_state=st["open_state"], pm_bars=st["pm_bars"],
                   **{k: st["lv"].get(k) for k in ("pdh", "pdl", "pdc", "pmh", "pml")})
        atr = bk[c.symbol].atr(c.date) if c.symbol in bk else np.nan
        row["atr"] = atr
        if c.status == "confirmed":
            t, close, hypo = c.signal_ts, c.entry, "signal"
        elif c.break_ts is not None:
            t = pd.Timestamp(c.break_ts) + pd.Timedelta(minutes=c.tf)
            close, hypo = c.break_close, "at_break"
        else:
            rows.append(row)
            continue
        row["hypo"] = hypo
        row["t_known"] = t
        row.update(context_for(bk, c.symbol, c.direction, t))
        p = plan(c.direction, close, c.level, c.touch_extreme, cfg)
        if not p:
            rows.append(row)
            continue
        row.update({f"plan_{k}": v for k, v in p.items()})
        res = simulate(st["rth"], t, c.direction, p, cfg, level=c.level,
                       touch_extreme=c.touch_extreme, atr=atr, alternatives=(hypo == "signal" and extras))
        row.update(res)
        # The same breakout bought at its close, no retest: what dropping the
        # retest rule would do. Measured on EVERY breakout, it is the fair
        # comparison for the rejected ones below.
        if hypo == "signal" and extras:
            tb = pd.Timestamp(c.break_ts) + pd.Timedelta(minutes=c.tf)
            pb = plan(c.direction, c.break_close, c.level, None, cfg)
            rb = simulate(st["rth"], tb, c.direction, pb, cfg, alternatives=False) if pb else {}
            row["r_at_break"] = rb.get("r")
        else:
            row["r_at_break"] = res.get("r")
        rows.append(row)
    df = pd.DataFrame(rows)
    if len(df):
        df["minute"] = pd.to_datetime(df["t_known"]).dt.hour * 60 + pd.to_datetime(df["t_known"]).dt.minute \
            if "t_known" in df else np.nan
    return df


def decide(ev: pd.DataFrame, tfs, cfg) -> pd.DataFrame:
    """Which confirmed setups become signals under a variant. Returns the
    confirmed rows for those timeframes with `taken` and `reject_reason`."""
    if ev.empty:
        return ev.assign(taken=False, reject_reason="")
    conf = ev[(ev.status == "confirmed") & ev.tf.isin(list(tfs)) & ev.outcome.notna()].copy()
    conf = conf.sort_values(["signal_ts", "tf"])
    conf["taken"], conf["reject_reason"] = False, ""
    seen, busy, count = set(), {}, {}
    keys = _keys(conf, cfg)
    for idx, r in conf.iterrows():
        key = keys[idx]
        if key in seen:
            conf.at[idx, "reject_reason"] = "duplicate_timeframe"
            continue
        seen.add(key)
        reasons = [b for b in str(r.blockers or "").split(";") if b]
        if cfg.context.block_counter_bias and r.get("counter_bias"):
            reasons.append("counter_bias")
        sym_day = (r.symbol, str(r.date))
        if busy.get(r.symbol) is not None and pd.Timestamp(r.signal_ts) <= busy[r.symbol]:
            reasons.append("position_open")
        if count.get(sym_day, 0) >= cfg.risk.max_signals_per_symbol_per_day:
            reasons.append("max_signals_per_day")
        if r.outcome == "no_data":
            reasons.append("no_data")
        if reasons:
            conf.at[idx, "reject_reason"] = reasons[0]
            continue
        conf.at[idx, "taken"] = True
        count[sym_day] = count.get(sym_day, 0) + 1
        busy[r.symbol] = pd.Timestamp(r.exit_ts) if pd.notna(r.exit_ts) else None
    return conf[conf.reject_reason != "duplicate_timeframe"]


def failures(ev: pd.DataFrame, tfs, cfg) -> pd.DataFrame:
    """Setups that never completed, once each (lowest timeframe that saw the
    breakout), with their at-the-break hypothetical."""
    if ev.empty:
        return ev
    f = ev[ev.status.isin(FAILURES) & ev.tf.isin(list(tfs))].sort_values("tf")
    f = f.assign(_k=_keys(f, cfg).astype(str) + f.attempt.astype(str))
    return f.drop_duplicates("_k").drop(columns="_k")


def run(sess: dict, daily: dict, dates: list, cfg, symbols=None, extras: bool = True) -> tuple[pd.DataFrame, dict]:
    """All candidates on `dates`, evaluated. Returns (evaluated rows, setups)."""
    bk = books(sess, daily, cfg)
    syms = symbols or cfg.universe.symbols
    cands, setups = [], {}
    for d in dates:
        for s in syms:
            days = sess.get(s, {})
            if d not in days:
                continue
            st = day_setup(days, d, cfg)
            if st is None:
                continue
            setups[(s, d)] = st
            cands += candidates_for(s, d, st, cfg)
    return evaluate(cands, setups, bk, cfg, extras), setups
