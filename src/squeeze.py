"""Intraday compression break — both directions.

Built to replicate the trade on the AMD chart: price coils into a tight range
on a fast timeframe, breaks out of it on volume, and runs. That chart was a
SHORT, and the existing engine only goes long, only reads daily bars, and only
trades shares. Each of those is a separate reason it could not have seen it.

This file fixes the first two. The third is addressed honestly rather than
pretended at - see `leverage_note` below.

    coil        the last `base_len` bars span less than `squeeze_atr` x ATR
    break       a bar CLOSES outside that range - either side
    volume      that bar trades at least `vol_mult` x the coil's average
    direction   up is a long, down is a short. Symmetric by construction.

Deliberately symmetric: the long and short rules are the same code with the
comparison flipped, so one side cannot quietly get a filter the other does not
have. A test asserts the symmetry on mirrored data.

Intraday realities that a daily backtest never has to face, all handled here:
  - the first bars of the day gap and whip; entries before `no_entry_before`
    are skipped
  - positions are CLOSED at `force_exit` - holding an intraday break overnight
    is a different strategy with different risk
  - shorts can be hard or impossible to borrow on exactly the names that move
    most. That is not modelled, and it flatters the short side.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import asdict, dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from .config import REPO_ROOT, Credentials
from .data import AlpacaError, MarketData
from .forensics import FRESH, MOVERS, UNIVERSES
from .indicators import atr

EASTERN = ZoneInfo("America/New_York")
REPORTS = REPO_ROOT / "reports"
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s",
                    stream=sys.stdout)
log = logging.getLogger("squeeze")

BASE_SQ = {
    "minutes": 5,            # bar size
    "base_len": 12,          # bars in the coil (12 x 5min = one hour)
    "squeeze_atr": 1.5,      # coil must be tighter than this x ATR
    "vol_mult": 1.5,         # break bar volume vs the coil average
    "atr_len": 14,
    "stop_atr": 0.5,         # stop beyond the far side of the coil
    "target_r": 2.0,
    "max_bars": 24,          # give up after two hours
    "no_entry_before": "09:45",   # let the opening auction settle
    "no_entry_after": "15:30",    # nothing new into the close
    "force_exit": "15:55",        # flat overnight, always
    "allow_long": True,
    "allow_short": True,
    "risk_pct": 1.0,
    "slippage_pct": 0.05,
    "max_open": 3,
    "max_entries": 1,        # attempts per symbol per session
    "reenter": False,        # after a stop, take the level again if it breaks
                             # a second time in the same direction
}


@dataclass
class IntradayTrade:
    symbol: str
    direction: str
    entry_time: str
    entry: float
    stop: float
    target: float
    exit_time: str = ""
    exit: float = 0.0
    reason: str = ""
    r_multiple: float = 0.0
    bars_held: int = 0
    move_pct: float = 0.0


def prepare_sq(df: pd.DataFrame, p: dict) -> pd.DataFrame:
    """Coil bounds and volume baseline, all excluding the current bar."""
    out = df.copy()
    n = p["base_len"]
    out["atr"] = atr(out, p["atr_len"])
    out["coil_high"] = out["high"].rolling(n).max().shift(1)
    out["coil_low"] = out["low"].rolling(n).min().shift(1)
    out["coil_vol"] = out["volume"].rolling(n).mean().shift(1)
    return out


def find_breaks(df: pd.DataFrame, p: dict) -> list[tuple[int, str]]:
    """Every bar that closes out of a tight coil on volume, with its side.

    The two directions are the same expression mirrored. If one side ever
    gains a condition the other lacks, the symmetry test fails.
    """
    a, close, vol = df["atr"], df["close"], df["volume"]
    ch, cl, cv = df["coil_high"], df["coil_low"], df["coil_vol"]
    tight = (ch - cl) <= p["squeeze_atr"] * a
    pushed = vol >= p["vol_mult"] * cv
    usable = tight & pushed & a.notna() & ch.notna() & cv.notna() & (a > 0)

    up = usable & (close > ch) & (close > df["open"])
    down = usable & (close < cl) & (close < df["open"])

    lo = pd.Timestamp(p["no_entry_before"]).time()
    hi = pd.Timestamp(p["no_entry_after"]).time()
    times = df.index.tz_convert(EASTERN).time
    in_window = np.array([lo <= t <= hi for t in times])

    out = []
    for i in range(len(df)):
        if not in_window[i] or i < p["base_len"] + p["atr_len"]:
            continue
        if p["allow_long"] and bool(up.iloc[i]):
            out.append((i, "long"))
        elif p["allow_short"] and bool(down.iloc[i]):
            out.append((i, "short"))
    return out


def run_day(df: pd.DataFrame, symbol: str, p: dict) -> list[IntradayTrade]:
    """One symbol, one session, bar by bar. Stop wins ties - pessimistic."""
    breaks = dict(find_breaks(df, p))
    flat = pd.Timestamp(p["force_exit"]).time()
    times = df.index.tz_convert(EASTERN).time
    slip = p["slippage_pct"] / 100.0
    trades: list[IntradayTrade] = []
    pos = None
    attempts = 0
    # After a stop the coil is gone - the range has widened, so `tight` can
    # never be true again and the symbol is finished for the day. That is what
    # happened on AMD: stopped at 12:15, then the real move ran without it.
    # Re-entry keeps the broken level and takes it again if price closes back
    # through it in the same direction.
    armed: tuple[float, str] | None = None

    for i in range(len(df)):
        bar = df.iloc[i]
        high, low, close = float(bar["high"]), float(bar["low"]), float(bar["close"])

        if pos is not None:
            pos["bars"] += 1
            long = pos["dir"] == "long"
            hit_stop = low <= pos["stop"] if long else high >= pos["stop"]
            hit_target = high >= pos["target"] if long else low <= pos["target"]
            out_px, why = None, ""
            if hit_stop:                      # stop first: pessimistic on ties
                out_px, why = pos["stop"], "stop"
            elif hit_target:
                out_px, why = pos["target"], "target"
            elif times[i] >= flat:
                out_px, why = close, "close_of_day"
            elif pos["bars"] >= p["max_bars"]:
                out_px, why = close, "time"

            if out_px is not None:
                fill = out_px * (1 - slip) if long else out_px * (1 + slip)
                r = ((fill - pos["entry"]) / pos["rps"] if long
                     else (pos["entry"] - fill) / pos["rps"])
                move = (100 * (fill - pos["entry"]) / pos["entry"] if long
                        else 100 * (pos["entry"] - fill) / pos["entry"])
                trades.append(IntradayTrade(
                    symbol, pos["dir"], pos["time"], round(pos["entry"], 2),
                    round(pos["stop"], 2), round(pos["target"], 2),
                    str(df.index[i]), round(fill, 2), why, round(r, 3),
                    pos["bars"], round(move, 2)))
                pos = None

        # re-entry on the remembered level
        if (pos is None and armed is not None and p.get("reenter")
                and attempts < p["max_entries"] + 1 and times[i] < flat
                and times[i] >= pd.Timestamp(p["no_entry_before"]).time()
                and times[i] <= pd.Timestamp(p["no_entry_after"]).time()):
            lvl, side_a = armed
            again = (close > lvl if side_a == "long" else close < lvl)
            if again and i not in breaks:
                a = float(bar["atr"]) if bar["atr"] == bar["atr"] else 0.0
                if a > 0:
                    entry = (close * (1 + slip) if side_a == "long"
                             else close * (1 - slip))
                    stop = (lvl - a * p["stop_atr"] if side_a == "long"
                            else lvl + a * p["stop_atr"])
                    rps = abs(entry - stop)
                    if 0 < rps / entry <= 0.10:
                        target = (entry + p["target_r"] * rps if side_a == "long"
                                  else entry - p["target_r"] * rps)
                        pos = {"dir": side_a, "entry": entry, "stop": stop,
                               "rps": rps, "target": target, "bars": 0,
                               "time": str(df.index[i])}
                        attempts += 1
                        armed = None

        if pos is None and i in breaks and times[i] < flat \
                and attempts <= p["max_entries"]:
            side = breaks[i]
            a = float(bar["atr"])
            ch, cl = float(bar["coil_high"]), float(bar["coil_low"])
            entry = close * (1 + slip) if side == "long" else close * (1 - slip)
            stop = (cl - a * p["stop_atr"] if side == "long"
                    else ch + a * p["stop_atr"])
            rps = abs(entry - stop)
            if rps <= 0 or rps / entry > 0.10:
                continue
            target = (entry + p["target_r"] * rps if side == "long"
                      else entry - p["target_r"] * rps)
            pos = {"dir": side, "entry": entry, "stop": stop, "rps": rps,
                   "target": target, "bars": 0, "time": str(df.index[i])}
            attempts += 1
            armed = (ch if side == "long" else cl, side)

    # A position still open when the session's bars run out must be closed at
    # the last price, not discarded. Dropping it deletes the trade from the
    # record entirely - and the ones that never reach a stop or target are
    # disproportionately the ones that went nowhere, so discarding them would
    # quietly delete the flat trades and inflate everything.
    if pos is not None:
        last = df.iloc[-1]
        close = float(last["close"])
        long = pos["dir"] == "long"
        fill = close * (1 - slip) if long else close * (1 + slip)
        r = ((fill - pos["entry"]) / pos["rps"] if long
             else (pos["entry"] - fill) / pos["rps"])
        move = (100 * (fill - pos["entry"]) / pos["entry"] if long
                else 100 * (pos["entry"] - fill) / pos["entry"])
        trades.append(IntradayTrade(
            symbol, pos["dir"], pos["time"], round(pos["entry"], 2),
            round(pos["stop"], 2), round(pos["target"], 2),
            str(df.index[-1]), round(fill, 2), "close_of_day", round(r, 3),
            pos["bars"], round(move, 2)))
    return trades


def leverage_note(move_pct: float) -> str:
    """What the same move is worth on shares, plainly.

    The chart that prompted this showed 334% on a 2.2% move in the stock. That
    multiple is the option contract, not the setup. Quoting an options return
    next to a share backtest would be comparing two different things, so this
    reports the underlying move and says what it is.
    """
    return (f"{move_pct:+.2f}% on the stock. An option on the same move can be "
            "worth many times that - and lose its whole premium on the trades "
            "that go the other way, which this backtest counts as -1R.")


def backtest(data: dict, p: dict) -> dict:
    all_trades: list[IntradayTrade] = []
    for sym, df in data.items():
        if df.empty:
            continue
        d = prepare_sq(df, p)
        for _, day in d.groupby(d.index.tz_convert(EASTERN).date):
            if len(day) < p["base_len"] + p["atr_len"] + 2:
                continue
            all_trades.extend(run_day(day, sym, p))
    return summarize_sq(all_trades, p)


def summarize_sq(trades: list[IntradayTrade], p: dict) -> dict:
    if not trades:
        return {"n": 0, "wins": 0, "losses": 0, "win_rate_pct": 0.0,
                "return_pct": 0.0, "expectancy_R": 0.0, "max_dd_pct": 0.0,
                "by_side": {}, "trades": []}
    trades.sort(key=lambda t: t.exit_time)
    r = np.array([t.r_multiple for t in trades])
    risk = p["risk_pct"] / 100.0
    curve = np.cumprod(1 + risk * r)
    peak = np.maximum.accumulate(np.concatenate([[1.0], curve]))
    dd = (np.concatenate([[1.0], curve]) - peak) / peak
    wins = int((r > 0).sum())

    by_side = {}
    for side in ("long", "short"):
        sub = [t for t in trades if t.direction == side]
        if not sub:
            continue
        rs = np.array([t.r_multiple for t in sub])
        w = int((rs > 0).sum())
        by_side[side] = {
            "n": len(sub), "wins": w, "losses": len(sub) - w,
            "win_rate_pct": round(100 * w / len(sub), 1),
            "return_pct": round(100 * (np.prod(1 + risk * rs) - 1), 1),
            "avg_move_pct": round(float(np.mean([t.move_pct for t in sub])), 2),
        }
    return {"n": len(trades), "wins": wins, "losses": len(trades) - wins,
            "win_rate_pct": round(100 * wins / len(trades), 1),
            "return_pct": round(100 * (float(curve[-1]) - 1), 1),
            "expectancy_R": round(float(r.mean()), 4),
            "max_dd_pct": round(100 * float(dd.min()), 2),
            "by_side": by_side,
            "trades": [asdict(t) for t in trades]}


def render_sq(p: dict) -> str:
    s, cfg = p["stats"], p["config"]
    out = [f"# Intraday squeeze break — {cfg['minutes']}-minute bars", "",
           f"**{p['symbols']} symbols · {p['start']} to {p['end']} · "
           f"{p['generated']}**", "",
           "Coil, then break, either direction. Built to read the setup the "
           "daily long-only rule could not see.", ""]
    if not s["n"]:
        out.append("**No trades.** Either the coil filter is too tight for "
                   "this timeframe or the window is too short.")
        return "\n".join(out)

    out += ["| | Trades | Won | Lost | Win % | Profit |",
            "|---|---|---|---|---|---|",
            f"| **Both sides** | {s['n']} | {s['wins']} | {s['losses']} | "
            f"{s['win_rate_pct']}% | **{s['return_pct']:+.1f}%** |"]
    for side, v in s["by_side"].items():
        out.append(f"| {side} | {v['n']} | {v['wins']} | {v['losses']} | "
                   f"{v['win_rate_pct']}% | {v['return_pct']:+.1f}% |")
    out += ["", f"Worst drop **{s['max_dd_pct']}%**.", ""]

    if len(s["by_side"]) == 2:
        lo, sh = s["by_side"]["long"], s["by_side"]["short"]
        gap = lo["return_pct"] - sh["return_pct"]
        out += [f"**Long vs short:** {abs(gap):.1f}% apart. " + (
            "The short side carries its weight, which is the whole reason "
            "this exists." if sh["return_pct"] > 0 else
            "The short side loses money here, so adding it did not buy what "
            "it was supposed to."), ""]

    best = max(s["trades"], key=lambda t: t["r_multiple"])
    out += ["### The biggest winner", "",
            f"**{best['symbol']} {best['direction']}** — in at "
            f"`${best['entry']:,.2f}`, out at `${best['exit']:,.2f}` "
            f"({best['reason']}), held {best['bars_held']} bars",
            f"{leverage_note(best['move_pct'])}", "",
            "_Shorting is assumed always available. On the names that move "
            "most it often is not, and that flatters the short side here._"]
    return "\n".join(out)


def grid_sq() -> list[tuple[str, dict]]:
    """The three things the AMD post-mortem pointed at, and nothing else.

    Stop width, how long to hold, and whether to take the level a second time.
    Kept deliberately small: this project's single clearest finding is that
    searching configurations does not generalise here - 33 monthly refits fit
    at +0.4R and forward-tested at -1.0R. Every extra knob makes the best
    result look better without making it any more real.
    """
    out = []
    for stop_atr in (0.5, 1.0, 1.5, 2.0):
        for max_bars in (24, 48, 78):
            for reenter in (False, True):
                name = (f"stop{stop_atr}_hold{max_bars}"
                        f"{'_re' if reenter else ''}")
                out.append((name, {**BASE_SQ, "stop_atr": stop_atr,
                                   "max_bars": max_bars, "reenter": reenter,
                                   "max_entries": 2 if reenter else 1}))
    return out


def noise_floor(n_trades: int, n_configs: int) -> float:
    """What the BEST of n_configs returns on luck alone, as a percentage.

    Try enough settings and one of them looks good for free. This is the bar
    any winner has to clear before it means anything.
    """
    if n_trades <= 1 or n_configs < 1:
        return 0.0
    # per-trade SD of ~1R at 1% risk, scaled by the multiple-testing factor
    se = 100 * 0.01 * np.sqrt(n_trades)
    return round(float(se * np.sqrt(2 * np.log(max(n_configs, 2)))), 1)


def render_sweep(p: dict) -> str:
    rows, hold = p["rows"], p.get("holdout")
    out = [f"# Squeeze sweep — {p['config']['minutes']}-minute bars", "",
           f"**{p['symbols']} symbols · from {p['start']} · "
           f"{p['generated']}**", "",
           f"**{len(rows)} settings tried.** Testing this many, the best one "
           f"returns about **{p['noise_floor']:+.1f}%** on luck alone. "
           "Anything near that is nothing.", "",
           "| Settings | Trades | Won | Lost | Win % | Profit | Worst drop |",
           "|---|---|---|---|---|---|---|"]
    for r in rows[:14]:
        warn = "" if r["n"] >= 30 else " ⚠"
        out.append(f"| `{r['name']}` | {r['n']}{warn} | {r['wins']} | "
                   f"{r['losses']} | {r['win_rate_pct']}% | "
                   f"**{r['return_pct']:+.1f}%** | {r['max_dd_pct']}% |")
    out.append("")
    best = rows[0] if rows else None
    if not best or best["return_pct"] <= 0:
        out.append("**Nothing made money.** Widening the stop and holding "
                   "longer did not fix it, so the entry is what is wrong, not "
                   "the management.")
        return "\n".join(out)

    if best["return_pct"] < p["noise_floor"]:
        out += [f"**The best setting, `{best['name']}` at "
                f"{best['return_pct']:+.1f}%, does not clear the "
                f"{p['noise_floor']:+.1f}% noise floor.** With "
                f"{len(rows)} settings tried, a result this size is what "
                "chance produces. Not a finding."]
        return "\n".join(out)

    out += [f"### `{best['name']}` on stocks it has never seen", ""]
    if not hold or not hold.get("n"):
        out.append("_The holdout run produced no trades, so nothing is "
                   "confirmed._")
        return "\n".join(out)
    out += ["| | Tuned on | **Never seen** |", "|---|---|---|",
            f"| Trades | {best['n']} | **{hold['n']}** |",
            f"| Won / lost | {best['wins']} / {best['losses']} | "
            f"**{hold['wins']} / {hold['losses']}** |",
            f"| Win rate | {best['win_rate_pct']}% | "
            f"**{hold['win_rate_pct']}%** |",
            f"| Profit | {best['return_pct']:+.1f}% | "
            f"**{hold['return_pct']:+.1f}%** |",
            f"| Worst drop | {best['max_dd_pct']}% | "
            f"**{hold['max_dd_pct']}%** |", "",
            ("**It held up on unseen names.**" if hold["return_pct"] > 0
             else "**It did not survive unseen names.** The tuned number is "
                  "the fitted one; this is the real one.")]
    return "\n".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default=None,
                    help="YYYY-MM-DD (default: 30 days back)")
    ap.add_argument("--end", default=None)
    ap.add_argument("--minutes", type=int, default=5)
    ap.add_argument("--universe", default="movers", choices=list(UNIVERSES))
    ap.add_argument("--symbols", default=None,
                    help="comma-separated, overrides --universe")
    ap.add_argument("--side", default="both",
                    choices=["both", "long", "short"])
    ap.add_argument("--sweep", action="store_true",
                    help="test stop width, hold length and re-entry, then "
                         "run the best once on unseen symbols")
    args = ap.parse_args(argv)

    p = dict(BASE_SQ)
    p["minutes"] = args.minutes
    p["allow_long"] = args.side in ("both", "long")
    p["allow_short"] = args.side in ("both", "short")

    syms = ([s.strip().upper() for s in args.symbols.split(",")]
            if args.symbols else UNIVERSES[args.universe])
    start = args.start or (pd.Timestamp.now(tz=EASTERN)
                           - pd.Timedelta(days=30)).date().isoformat()
    try:
        md = MarketData(Credentials.from_env(), feed="iex")
        log.info("Fetching %d symbols, %d-minute bars from %s",
                 len(syms), args.minutes, start)
        data = md.intraday_bars(syms, args.minutes, start=start, end=args.end)
    except AlpacaError as exc:
        log.error("Fetch failed: %s", exc)
        return 1
    data = {s: d for s, d in data.items() if not d.empty}
    if not data:
        log.error("No data returned.")
        return 1

    if args.sweep:
        rows = []
        for name, cfg in grid_sq():
            cfg = {**cfg, "minutes": p["minutes"],
                   "allow_long": p["allow_long"],
                   "allow_short": p["allow_short"]}
            st = backtest(data, cfg)
            rows.append({"name": name, "params": cfg,
                         **{k: st[k] for k in ("n", "wins", "losses",
                                               "win_rate_pct", "return_pct",
                                               "max_dd_pct", "expectancy_R")}})
            log.info("  %-22s n=%-4d %+.1f%%  dd %.1f%%", name, st["n"],
                     st["return_pct"], st["max_dd_pct"])
        rows = [r for r in rows if r["n"] >= 15]
        rows.sort(key=lambda r: -r["return_pct"])
        floor = noise_floor(max((r["n"] for r in rows), default=0), len(rows))

        hold = None
        if rows and rows[0]["return_pct"] > floor:
            unseen = [x for x in FRESH if x not in set(syms)]
            log.info("Winner %s - one run on %d unseen symbols",
                     rows[0]["name"], len(unseen))
            try:
                hd = md.intraday_bars(unseen, args.minutes, start=start,
                                      end=args.end)
                hd = {k: v for k, v in hd.items() if not v.empty}
                if hd:
                    hold = backtest(hd, rows[0]["params"])
            except AlpacaError as exc:
                log.warning("Holdout fetch failed: %s", exc)

        payload = {"symbols": len(data), "start": start,
                   "end": args.end or "now", "config": p,
                   "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
                   "rows": rows, "noise_floor": floor, "holdout": hold}
        REPORTS.mkdir(exist_ok=True)
        text = render_sweep(payload)
        (REPORTS / "squeeze_sweep.md").write_text(text)
        (REPORTS / "squeeze_sweep.json").write_text(json.dumps(
            {**payload, "rows": [{k: v for k, v in r.items() if k != "params"}
                                 for r in rows]}, indent=2, default=str))
        print(text)
        return 0

    stats = backtest(data, p)
    payload = {"symbols": len(data), "start": start,
               "end": args.end or "now", "config": p, "stats": stats,
               "generated": datetime.now().strftime("%Y-%m-%d %H:%M")}
    REPORTS.mkdir(exist_ok=True)
    text = render_sq(payload)
    (REPORTS / "squeeze.md").write_text(text)
    slim = {**payload, "stats": {**stats, "trades": stats["trades"][-200:]}}
    (REPORTS / "squeeze.json").write_text(json.dumps(slim, indent=2, default=str))
    print(text)
    log.info("%d trades, %+.1f%%, worst drop %.1f%%",
             stats["n"], stats["return_pct"], stats["max_dd_pct"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
