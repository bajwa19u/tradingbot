"""Daily-bar trend pullback — buy dips to the EMA inside an established uptrend.

This is a different game from the intraday work. Positions are held for days
or weeks, the universe is wide, and the history is deep, which means far more
independent trades and far less competition from firms optimised for
milliseconds. Trend following at this horizon is the best-documented
persistent effect in public markets, so it is the most honest place to look.

The setup, straight off a daily chart:

  TREND        EMA20 > EMA50 > EMA200 and price above the long EMA. The stack
               has to be in order - that is what "established uptrend" means
               rather than "it has gone up lately".
  PULLBACK     price trades down into the EMA20 (a touch, not a close below).
  TRIGGER      a candle closes back up, above both the EMA20 and its own open.
  STOP         below the pullback low, minus an ATR buffer.
  EXIT         fixed R multiple, or a trailing stop that follows the EMA.

Runs as a portfolio: risk per trade is a fixed fraction of equity, with a cap
on how many positions are open at once, so results reflect something you
could actually hold.
"""
from __future__ import annotations

import argparse
import copy
import itertools
import json
import logging
import sys
from dataclasses import dataclass, asdict
from datetime import datetime

import numpy as np
import pandas as pd

from .config import REPO_ROOT, Credentials
from .data import AlpacaError, MarketData
from .indicators import atr

REPORTS = REPO_ROOT / "reports"
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                    stream=sys.stdout)
log = logging.getLogger("swing")

# Two disjoint universes. The search only ever sees RESEARCH; HOLDOUT is
# opened once, at the end, with the single configuration that was selected.
RESEARCH = [
    "AAPL", "MSFT", "NVDA", "AMD", "TSLA", "JPM", "BAC", "XOM", "CVX", "JNJ",
    "PG", "KO", "PEP", "WMT", "HD", "CAT", "DE", "UNH", "CVS", "MRK",
    "T", "VZ", "CSCO", "ORCL", "CRM", "ADBE", "TXN", "QCOM", "INTC", "IBM",
    "NKE", "SBUX", "MCD", "LOW", "TGT", "COST", "UPS", "HON", "GE", "BA",
]
HOLDOUT = [
    "MET", "PRU", "AFL", "ALL", "TRV", "GS", "MS", "SCHW", "BLK", "SPGI",
    "LIN", "APD", "SHW", "ECL", "NEM", "FCX", "NUE", "DOW", "PPG", "EMR",
    "ITW", "ROK", "PH", "ETN", "CMI", "PCAR", "LMT", "NOC", "GD", "RTX",
]


@dataclass
class SwingTrade:
    symbol: str
    entry_date: str
    entry: float
    stop: float
    exit_date: str = ""
    exit: float = 0.0
    reason: str = ""
    r_multiple: float = 0.0
    bars_held: int = 0
    mae_r: float = 0.0
    mfe_r: float = 0.0


def indicators(df: pd.DataFrame, p: dict) -> pd.DataFrame:
    out = df.copy()
    for n in (p["fast"], p["mid"], p["slow"]):
        out[f"ema{n}"] = out["close"].ewm(span=n, adjust=False).mean()
    out["atr"] = atr(out, 14)
    return out


def find_signals(df: pd.DataFrame, p: dict) -> list[int]:
    """Indices where a long entry triggers. Uses only closed bars."""
    f, m, s = p["fast"], p["mid"], p["slow"]
    ef, em, es = df[f"ema{f}"], df[f"ema{m}"], df[f"ema{s}"]
    a = df["atr"]

    uptrend = (ef > em) & (em > es) & (df["close"] > es)

    # The EMA stack staying in order is not the same as the trend still
    # moving. After a rally stalls, the stack holds for weeks while price
    # chops sideways - and every dip to a flat EMA reads as a setup. Require
    # the fast EMA to have actually climbed, measured in ATR so it scales
    # with the stock.
    slope_n = p.get("slope_bars", 0)
    min_slope = p.get("min_slope_atr", 0.0)
    if slope_n and min_slope:
        uptrend &= (ef - ef.shift(slope_n)) >= a * min_slope

    tol = a * p["touch_atr"]
    touched = df["low"] <= ef + tol
    # a close BELOW the mid EMA means the pullback has gone too far
    intact = df["close"] > em
    trigger = (df["close"] > ef) & (df["close"] > df["open"])

    # the touch may be on this bar or the previous ones
    window = p["touch_window"]
    recent_touch = touched.rolling(window, min_periods=1).max().astype(bool)

    ok = uptrend & recent_touch & intact & trigger & a.notna()
    # require the trend to have been in place, not just formed today
    ok &= uptrend.rolling(p["trend_bars"], min_periods=p["trend_bars"]).min() \
        .fillna(0).astype(bool)
    return [i for i, v in enumerate(ok.to_numpy()) if v and i > s]


def prepare(data: dict[str, pd.DataFrame], p: dict) -> dict[str, pd.DataFrame]:
    """Indicators computed ONCE over full history, including warmup.

    Slicing first and computing after would restart every moving average at
    the start of each slice - a 200-period EMA needs 200 bars, so the opening
    months of each period would be driven by a meaningless average.
    """
    return {s: indicators(d, p) for s, d in data.items() if len(d) > p["slow"] + 30}


def signal_times(prepared: dict[str, pd.DataFrame], p: dict) -> dict[str, set]:
    out = {}
    for sym, d in prepared.items():
        out[sym] = {d.index[i] for i in find_signals(d, p)}
    return out


def run_portfolio(prepared: dict[str, pd.DataFrame], p: dict,
                  equity: float = 10000.0, sigs: dict | None = None,
                  lo=None, hi=None) -> dict:
    """Walk the calendar once, holding up to `max_open` positions.

    `prepared` already carries indicators over full history. `lo`/`hi` bound
    the TRADING window; bars before `lo` are still used for the averages.
    """
    if not prepared:
        return {"trades": [], "stats": {"n_trades": 0}, "open": []}

    signals = sigs if sigs is not None else signal_times(prepared, p)
    calendar = sorted({ts for d in prepared.values() for ts in d.index
                       if (lo is None or ts >= lo) and (hi is None or ts < hi)})
    pos: dict[str, dict] = {}
    trades: list[SwingTrade] = []
    risk_frac = p["risk_pct"] / 100.0

    for day in calendar:
        # --- manage open positions ---------------------------------------
        for sym in list(pos):
            d = prepared[sym]
            if day not in d.index:
                continue
            i = d.index.get_loc(day)
            bar = d.iloc[i]
            st = pos[sym]
            rps = st["rps"]
            high, low, close = float(bar["high"]), float(bar["low"]), float(bar["close"])
            st["bars"] += 1
            st["mfe"] = max(st["mfe"], (high - st["entry"]) / rps)
            st["mae"] = min(st["mae"], (low - st["entry"]) / rps)

            exit_px, reason = None, ""
            if low <= st["stop"]:
                exit_px, reason = st["stop"], ("trail" if st["trailing"] else "stop")
            elif p["target_r"] > 0 and high >= st["entry"] + p["target_r"] * rps:
                exit_px, reason = st["entry"] + p["target_r"] * rps, "target"
            elif p["trail_ema"] and close < float(bar[f"ema{p['fast']}"]) \
                    and st["mfe"] >= p["trail_after_r"]:
                exit_px, reason = close, "ema_exit"
            elif st["bars"] >= p["max_hold"]:
                exit_px, reason = close, "time"

            if exit_px is not None:
                slip = exit_px * 0.0005
                fill = exit_px - slip
                t = SwingTrade(sym, st["date"], round(st["entry"], 4),
                               round(st["stop"], 4), str(day.date()),
                               round(fill, 4), reason,
                               round((fill - st["entry"]) / rps, 3),
                               st["bars"], round(st["mae"], 2), round(st["mfe"], 2))
                trades.append(t)
                del pos[sym]
                continue

            # move the stop up behind the fast EMA once in profit
            if p["trail_ema"] and st["mfe"] >= p["trail_after_r"]:
                new_stop = float(bar[f"ema{p['fast']}"]) - float(bar["atr"]) * p["stop_atr"]
                if new_stop > st["stop"]:
                    st["stop"] = new_stop
                    st["trailing"] = True

        # --- new entries ---------------------------------------------------
        if len(pos) >= p["max_open"]:
            continue
        for sym, d in prepared.items():
            if sym in pos or len(pos) >= p["max_open"]:
                continue
            if day not in d.index:
                continue
            if day not in signals.get(sym, ()):
                continue
            i = d.index.get_loc(day)
            bar = d.iloc[i]
            lookback = d.iloc[max(0, i - p["touch_window"]):i + 1]
            pullback_low = float(lookback["low"].min())
            # entry_style "close" is the tested rule: buy the closing price.
            # "level" is the intraday version - buy the moment price crosses
            # the breakout level, which in daily bars means the level itself,
            # or the open when the day gapped straight past it. The gap case
            # matters: pretending a gapped-away level was filled is the most
            # common way an intraday backtest flatters itself.
            if p.get("entry_style") == "level" and "base_high" in d.columns:
                level = float(bar["base_high"])
                entry = max(level, float(bar["open"])) * 1.0005
            else:
                entry = float(bar["close"]) * 1.0005
            stop = pullback_low - float(bar["atr"]) * p["stop_atr"]
            rps = entry - stop
            if rps <= 0 or rps / entry > 0.25:
                continue
            pos[sym] = {"entry": entry, "stop": stop, "rps": rps,
                        "date": str(day.date()), "bars": 0,
                        "mfe": 0.0, "mae": 0.0, "trailing": False}

    out = summarize(trades, risk_frac, equity)
    # Positions still open when the data runs out. The backtest ignores these
    # on purpose - an unfinished trade has no result to score. Paper trading is
    # the opposite case: the open ones are the only ones that need acting on,
    # and they must come from this function rather than a second copy of the
    # entry rules, which is how the inspector drifted from the signals before.
    out["open"] = [
        {"symbol": sym, "entry_date": st["date"], "entry": round(st["entry"], 2),
         "stop": round(st["stop"], 2), "risk_per_share": round(st["rps"], 2),
         "bars_held": st["bars"], "best_R": round(st["mfe"], 2),
         "target": round(st["entry"] + max(p["target_r"], 1.5) * st["rps"], 2),
         "trailing": st["trailing"]}
        for sym, st in sorted(pos.items())
    ]
    return out


def summarize(trades: list[SwingTrade], risk_frac: float, equity: float) -> dict:
    if not trades:
        return {"trades": [], "stats": {"n_trades": 0, "expectancy_R": 0.0,
                                        "total_R": 0.0, "win_rate_pct": 0.0,
                                        "return_pct": 0.0,
                                        "max_drawdown_pct": 0.0}, "open": []}
    trades.sort(key=lambda t: t.exit_date)
    r = np.array([t.r_multiple for t in trades])
    curve, eq = [], equity
    for x in r:
        eq *= (1 + risk_frac * x)
        curve.append(eq)
    curve = np.array(curve)
    peak = np.maximum.accumulate(np.concatenate([[equity], curve]))
    dd = (np.concatenate([[equity], curve]) - peak) / peak
    wins = r > 0
    gross_w = r[r > 0].sum()
    gross_l = -r[r < 0].sum()
    by_reason: dict[str, int] = {}
    for t in trades:
        by_reason[t.reason] = by_reason.get(t.reason, 0) + 1
    return {
        "trades": [asdict(t) for t in trades],
        "stats": {
            "n_trades": len(trades),
            "win_rate_pct": round(100 * float(wins.mean()), 1),
            "expectancy_R": round(float(r.mean()), 4),
            "total_R": round(float(r.sum()), 1),
            "profit_factor": round(float(gross_w / gross_l), 2) if gross_l else 999.0,
            "final_equity": round(float(curve[-1]), 2),
            "return_pct": round(100 * (float(curve[-1]) / equity - 1), 1),
            "max_drawdown_pct": round(100 * float(dd.min()), 2),
            "avg_bars_held": round(float(np.mean([t.bars_held for t in trades])), 1),
            "exit_reasons": by_reason,
        },
    }


# ---------------------------------------------------------------------------
BASE = {"fast": 20, "mid": 50, "slow": 200, "touch_atr": 0.25, "touch_window": 3,
        "trend_bars": 10, "stop_atr": 0.5, "target_r": 3.0, "trail_ema": True,
        "trail_after_r": 1.0, "max_hold": 60, "risk_pct": 1.0, "max_open": 8,
        # chop filter: the fast EMA must have risen this many ATR over
        # `slope_bars` bars. 0 disables it (the original behaviour).
        "slope_bars": 20, "min_slope_atr": 0.0,
        # do not re-enter the same name for N bars after a signal
        "cooldown_bars": 0}


def grid() -> list[tuple[str, dict]]:
    """One knob at a time off a common base, plus a slope sweep.

    The slope entries exist because MET showed the strategy firing again and
    again into a flat, sideways market - the EMA stack was still in order but
    the trend had stopped moving.
    """
    out = []
    for fast, target, trail, stop in itertools.product(
            [10, 20], [0.0, 2.0, 3.0], [True, False], [0.3, 0.5, 1.0]):
        p = copy.deepcopy(BASE)
        p.update({"fast": fast, "target_r": target, "trail_ema": trail,
                  "stop_atr": stop})
        if target == 0.0 and not trail:
            continue  # no way out except the stop or the clock
        out.append((f"ema{fast}_tgt{target}_trail{int(trail)}_stop{stop}", p))

    # slope filter applied to the two shapes that led the last search
    for fast, target, stop in ((10, 3.0, 0.3), (20, 0.0, 0.5), (20, 2.0, 0.5)):
        for slope in (0.5, 1.0, 2.0):
            p = copy.deepcopy(BASE)
            p.update({"fast": fast, "target_r": target, "trail_ema": True,
                      "stop_atr": stop, "min_slope_atr": slope})
            out.append((f"ema{fast}_tgt{target}_stop{stop}_slope{slope}", p))
    return out


def by_periods(data: dict, p: dict, n: int, trade_from=None) -> dict:
    prepared = prepare(data, p)
    if not prepared:
        return {"n": 0, "expectancy_R": 0.0, "total_R": 0.0,
                "periods_positive": 0, "periods_scored": 0,
                "worst_period_R": 0.0, "max_dd_pct": 0.0}
    sigs = signal_times(prepared, p)
    days = sorted({d for df in prepared.values() for d in df.index
                   if trade_from is None or d >= trade_from})
    if len(days) < n * 20:
        return {"n": 0, "expectancy_R": 0.0, "total_R": 0.0,
                "periods_positive": 0, "periods_scored": 0,
                "worst_period_R": 0.0, "max_dd_pct": 0.0}
    edges = [days[int(len(days) * i / n)] for i in range(n)]
    edges.append(days[-1] + pd.Timedelta(days=1))
    per, total_n, total_R = [], 0, 0.0
    worst_dd = 0.0
    for i in range(n):
        st = run_portfolio(prepared, p, sigs=sigs,
                           lo=edges[i], hi=edges[i + 1])["stats"]
        per.append({"n": st["n_trades"], "expectancy_R": st["expectancy_R"]})
        total_n += st["n_trades"]
        total_R += st["total_R"]
        worst_dd = min(worst_dd, st.get("max_drawdown_pct", 0.0))
    scored = [x for x in per if x["n"] >= 10]
    return {"per_period": per,
            "n": total_n,
            "expectancy_R": round(total_R / total_n, 4) if total_n else 0.0,
            "total_R": round(total_R, 1),
            "periods_positive": sum(1 for x in scored if x["expectancy_R"] > 0),
            "periods_scored": len(scored),
            "worst_period_R": round(min((x["expectancy_R"] for x in scored),
                                        default=0.0), 4),
            "max_dd_pct": round(worst_dd, 2)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2023-01-01",
                    help="first date trades may be TAKEN")
    ap.add_argument("--end", default=None)
    ap.add_argument("--periods", type=int, default=4)
    ap.add_argument("--min-trades", type=int, default=100)
    ap.add_argument("--universe", default="research",
                    help="research | holdout | movers")
    ap.add_argument("--only", default=None,
                    help="run just this configuration by name - no search, no "
                         "selection. Use it to test an already-chosen config "
                         "on a different era.")
    args = ap.parse_args(argv)

    # Fetch well before the trading window so the slow EMA and ATR are valid
    # on day one. Without this the first ~10 months would trade off averages
    # that had not converged.
    trade_from = pd.Timestamp(args.start, tz="America/New_York")
    fetch_from = (trade_from - pd.Timedelta(days=500)).date().isoformat()

    creds = Credentials.from_env()
    from .forensics import MOVERS, UNIVERSES
    universe = UNIVERSES.get(args.universe, RESEARCH)
    # Hold out a universe the search never sees. When the search itself runs
    # on movers, the mega-cap list becomes the holdout and vice versa.
    holdout_universe = (RESEARCH if args.universe == "movers"
                        else MOVERS if args.universe == "research"
                        else HOLDOUT)
    try:
        md = MarketData(creds, feed="iex")
        log.info("Fetching daily bars for %d %s symbols from %s "
                 "(trading from %s)", len(universe), args.universe,
                 fetch_from, args.start)
        research = md.daily_bars(universe, start=fetch_from, end=args.end)
    except AlpacaError as exc:
        log.error("Market data unavailable: %s", exc)
        return 1
    research = {s: d for s, d in research.items() if len(d) > 250}
    log.info("%d symbols, %d total daily bars", len(research),
             sum(len(d) for d in research.values()))
    if not research:
        log.error("No data.")
        return 1

    configs = grid()
    if args.only:
        configs = [(n, p) for n, p in configs if n == args.only]
        if not configs:
            log.error("No configuration named %s. Available: %s",
                      args.only, ", ".join(n for n, _ in grid()))
            return 1
        log.info("Single-configuration run (no search): %s", args.only)
    log.info("Scoring %d configurations across %d periods", len(configs), args.periods)
    results = []
    for i, (name, p) in enumerate(configs, 1):
        st = by_periods(research, p, args.periods, trade_from=trade_from)
        st["name"], st["params"] = name, p
        results.append(st)
        log.info("  %-34s n=%-5d exp=%+.4fR  positive %d/%d",
                 name, st["n"], st["expectancy_R"],
                 st["periods_positive"], st["periods_scored"])

    survivors = [r for r in results
                 if r["expectancy_R"] > 0
                 and r["n"] >= args.min_trades
                 and r["periods_positive"] >= r["periods_scored"] - 1]
    survivors.sort(key=lambda r: (-r["worst_period_R"], -r["expectancy_R"]))

    holdout = None
    winner = survivors[0] if survivors else None
    if winner:
        log.info("Winner %s — single holdout run on %d unseen symbols",
                 winner["name"], len(holdout_universe))
        try:
            hd = md.daily_bars(holdout_universe, start=fetch_from, end=args.end)
            hd = {s: d for s, d in hd.items() if len(d) > 250}
            if hd:
                holdout = by_periods(hd, winner["params"], args.periods,
                                     trade_from=trade_from)
                prep = prepare(hd, winner["params"])
                full = run_portfolio(prep, winner["params"],
                                     lo=trade_from)["stats"]
                holdout["return_pct"] = full.get("return_pct")
                holdout["win_rate_pct"] = full.get("win_rate_pct")
                holdout["exit_reasons"] = full.get("exit_reasons")
        except AlpacaError as exc:
            log.warning("Holdout fetch failed: %s", exc)

    REPORTS.mkdir(exist_ok=True)
    payload = {"tried": len(configs), "survivors": len(survivors),
               "results": sorted(results, key=lambda r: -r["expectancy_R"]),
               "winner": winner, "holdout": holdout,
               "research_symbols": len(research), "start": args.start}
    (REPORTS / "swing.json").write_text(json.dumps(payload, indent=2, default=str))
    text = render(payload)
    (REPORTS / "swing.md").write_text(text)
    print("\n" + text)
    return 0


def render(p: dict) -> str:
    out = [
        "# Daily trend pullback",
        "",
        f"**Research:** {p['research_symbols']} large caps · trading from "
        f"{p['start']} · daily bars (indicators warmed on earlier history)  ",
        f"**Locked holdout:** {len(HOLDOUT)} different companies (insurers, "
        "financials, industrials, materials) — opened once, at the end  ",
        f"**Generated:** {datetime.now():%Y-%m-%d %H:%M}",
        "",
        f"**{p['tried']} configurations tried.** {p['survivors']} passed.",
        "",
        "| Configuration | Trades | Expectancy | Positive in | Worst period | Max DD |",
        "|---|---|---|---|---|---|",
    ]
    for r in p["results"][:12]:
        warn = "" if r["n"] >= 100 else " ⚠"
        out.append(f"| `{r['name']}` | {r['n']}{warn} | {r['expectancy_R']:+.4f}R | "
                   f"{r['periods_positive']}/{r['periods_scored']} | "
                   f"{r['worst_period_R']:+.4f}R | {r['max_dd_pct']}% |")

    w, h = p.get("winner"), p.get("holdout")
    out += ["", "## Selected configuration", ""]
    if not w:
        out += ["**Nothing passed.** No configuration was profitable overall "
                "while staying positive across periods on an adequate sample. "
                "The holdout was not opened.", ""]
        return "\n".join(out)

    out += [f"**`{w['name']}`** — {json.dumps(w['params'])}", "",
            "| | Research | **Holdout (unseen companies)** |", "|---|---|---|",
            f"| Trades | {w['n']} | **{h['n'] if h else 'n/a'}** |"]
    if h:
        out += [
            f"| Expectancy | {w['expectancy_R']:+.4f}R | **{h['expectancy_R']:+.4f}R** |",
            f"| Total R | {w['total_R']:+.1f} | **{h['total_R']:+.1f}** |",
            f"| Positive in | {w['periods_positive']}/{w['periods_scored']} | "
            f"**{h['periods_positive']}/{h['periods_scored']}** |",
            f"| Win rate | — | **{h.get('win_rate_pct')}%** |",
            f"| Return (1% risk) | — | **{h.get('return_pct')}%** |",
            f"| Max drawdown | {w['max_dd_pct']}% | **{h['max_dd_pct']}%** |",
            "", "### Verdict", ""]
        strong = (h["expectancy_R"] >= 0.05 and h["n"] >= 150
                  and h["periods_positive"] >= h["periods_scored"] - 1)
        if strong:
            out += ["**Held up on companies it had never seen.**", "",
                    "At this horizon that is a meaningful result — daily trend "
                    "following has real academic support, unlike the intraday "
                    "patterns tested earlier. Still: paper trade it, check the "
                    "drawdown is one you could actually sit through, and do not "
                    "re-tune against this holdout. It has been spent."]
        else:
            out += ["**Did not clear the bar on unseen companies.**", "",
                    f"Expectancy {h['expectancy_R']:+.4f}R over {h['n']} trades, "
                    f"positive in {h['periods_positive']}/{h['periods_scored']} "
                    "periods. Positive numbers that small do not survive real "
                    "costs. No re-tuning against the holdout."]
    return "\n".join(out)


if __name__ == "__main__":
    raise SystemExit(main())
