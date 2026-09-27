"""Expansion breakout — enter as a trend begins, not on its third pullback.

Built from a finding rather than a search. Forensics on 2026 showed the
pullback strategy caught 18 of 2,148 big moves, and the gates that blocked
the rest were "trend too new", "trend has gone flat" and "EMA stack out of
order". In other words, the big moves of 2026 did not come out of established
uptrends at all. Waiting for a confirmed trend was filtering out the thing
that actually moved.

So this inverts the premise:

  BASE       price coils - the last `base_len` bars span less than
             `squeeze_atr` x ATR. Quiet before loud.
  EXPANSION  a bar closes above the top of that base, on volume above the
             base average. The move is starting, not continuing.
  VOLATILE   the stock's ATR is at least `min_atr_pct` of price. The autopsy
             found winners averaged 5.35% ATR against losers at 3.80%, a
             separation of 0.64 standard deviations - the only condition all
             project that cleanly split the two.

Stops sit under the base. Exits reuse the tested portfolio machinery, so only
the entry logic is new.
"""
from __future__ import annotations

import argparse
import copy
import itertools
import json
import logging
import sys
from datetime import datetime

import numpy as np
import pandas as pd

from .config import REPO_ROOT, Credentials
from .data import AlpacaError, MarketData
from .forensics import MOVERS, UNIVERSES
from .indicators import atr
from .swing import HOLDOUT, RESEARCH, run_portfolio, summarize

REPORTS = REPO_ROOT / "reports"
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                    stream=sys.stdout)
log = logging.getLogger("breakout")

# Thresholds for reading the volatility split. The autopsy measured winners at
# a 5.35% median daily range against 3.80% for losers; 4.0% sits between them,
# so a "loud" half below it is not loud in any sense that matters.
VOL_BAR_PCT = 4.0        # loud half must clear this to test the idea at all
MIN_VOL_SPREAD_PCT = 1.0  # the two halves must differ by at least this much
MIN_HALF_GAP_PCT = 10.0   # profit gap worth calling a finding

BASE_BO = {
    # entry
    "base_len": 15,          # bars that must be coiling
    "squeeze_atr": 2.5,      # base range must be tighter than this x ATR
    "vol_mult": 1.3,         # breakout volume vs the base average
    "min_atr_pct": 4.0,      # volatility floor, from the autopsy
    "require_above_slow": False,   # deliberately OFF - the evidence says the
                                   # EMA stack was blocking the real moves
    # exits / sizing, reused from the swing engine
    "fast": 10, "mid": 50, "slow": 200,
    "stop_atr": 0.3, "target_r": 3.0, "trail_ema": True, "trail_after_r": 1.0,
    "max_hold": 40, "risk_pct": 1.0, "max_open": 8,
    # run_portfolio takes the stop from the low of the last `touch_window`
    # bars, so setting it to base_len puts the stop under the base.
    "touch_window": 15,
    "slope_bars": 0, "min_slope_atr": 0.0, "trend_bars": 0, "touch_atr": 0.0,
}


def indicators_bo(df: pd.DataFrame, p: dict) -> pd.DataFrame:
    out = df.copy()
    for n in (p["fast"], p["mid"], p["slow"]):
        out[f"ema{n}"] = out["close"].ewm(span=n, adjust=False).mean()
    out["atr"] = atr(out, 14)
    n = p["base_len"]
    # the base is the bars BEFORE this one - shift so the current bar's own
    # high can never be part of the level it is breaking out of
    out["base_high"] = out["high"].rolling(n).max().shift(1)
    out["base_low"] = out["low"].rolling(n).min().shift(1)
    out["base_vol"] = out["volume"].rolling(n).mean().shift(1)
    return out


def prepare(data: dict, p: dict) -> dict:
    return {s: indicators_bo(d, p) for s, d in data.items()
            if len(d) > max(p["slow"], p["base_len"]) + 30}


def find_signals_bo(df: pd.DataFrame, p: dict) -> list[int]:
    a, close, vol = df["atr"], df["close"], df["volume"]
    bh, bl, bv = df["base_high"], df["base_low"], df["base_vol"]

    volatile = (100 * a / close) >= p["min_atr_pct"]
    coiled = (bh - bl) <= p["squeeze_atr"] * a
    broke = (close > bh) & (close > df["open"])
    pushed = vol >= p["vol_mult"] * bv
    ok = volatile & coiled & broke & pushed & a.notna() & bh.notna()
    if p.get("require_above_slow"):
        ok &= close > df[f"ema{p['slow']}"]
    return [i for i, v in enumerate(ok.to_numpy()) if v and i > p["base_len"] + 15]


def signal_times_bo(prepared: dict, p: dict) -> dict:
    return {s: {d.index[i] for i in find_signals_bo(d, p)}
            for s, d in prepared.items()}


def grid_bo() -> list[tuple[str, dict]]:
    out = []
    for base, squeeze, vol, min_atr in itertools.product(
            [10, 15, 25], [1.8, 2.5, 4.0], [1.0, 1.5], [0.0, 4.0]):
        p = copy.deepcopy(BASE_BO)
        p.update({"base_len": base, "touch_window": base,
                  "squeeze_atr": squeeze, "vol_mult": vol,
                  "min_atr_pct": min_atr})
        out.append((f"base{base}_sq{squeeze}_vol{vol}_atr{min_atr}", p))
    return out


def median_atr_pct(df: pd.DataFrame, upto=None) -> float:
    """How volatile this stock typically is, as a % of price.

    Measured over history BEFORE the trading window, so selecting on it is
    not peeking at the period being tested.
    """
    d = df[df.index < upto] if upto is not None else df
    if len(d) < 60:
        return 0.0
    a = atr(d, 14).tail(120)
    px = d["close"].tail(120)
    return float((100 * a / px).median())


def split_by_volatility(data: dict, upto=None) -> tuple[dict, dict]:
    """Top half vs bottom half of the universe by typical daily range."""
    ranked = sorted(((median_atr_pct(d, upto), s) for s, d in data.items()),
                    reverse=True)
    half = len(ranked) // 2
    loud = {s: data[s] for _, s in ranked[:half]}
    quiet = {s: data[s] for _, s in ranked[half:]}
    return loud, quiet


def by_periods(data: dict, p: dict, n: int, trade_from=None) -> dict:
    prepared = prepare(data, p)
    if not prepared:
        return {"n": 0, "expectancy_R": 0.0, "total_R": 0.0,
                "periods_positive": 0, "periods_scored": 0,
                "worst_period_R": 0.0, "max_dd_pct": 0.0}
    sigs = signal_times_bo(prepared, p)
    days = sorted({d for df in prepared.values() for d in df.index
                   if trade_from is None or d >= trade_from})
    if len(days) < n * 15:
        return {"n": 0, "expectancy_R": 0.0, "total_R": 0.0,
                "periods_positive": 0, "periods_scored": 0,
                "worst_period_R": 0.0, "max_dd_pct": 0.0}
    edges = [days[int(len(days) * i / n)] for i in range(n)]
    edges.append(days[-1] + pd.Timedelta(days=1))
    per, total_n, total_R, worst = [], 0, 0.0, 0.0
    for i in range(n):
        st = run_portfolio(prepared, p, sigs=sigs,
                           lo=edges[i], hi=edges[i + 1])["stats"]
        per.append({"n": st["n_trades"], "expectancy_R": st["expectancy_R"]})
        total_n += st["n_trades"]
        total_R += st["total_R"]
        worst = min(worst, st.get("max_drawdown_pct", 0.0))
    full = run_portfolio(prepared, p, sigs=sigs, lo=trade_from)
    fs = full["stats"]
    wins = sum(1 for t in full["trades"] if t["r_multiple"] > 0)
    n_full = len(full["trades"])
    scored = [x for x in per if x["n"] >= 8]
    # Everything reported to a human comes from the single full-window run, so
    # trades always equals won + lost. The per-period slices cut trades at each
    # boundary, so their trade count is smaller and must not be mixed in.
    return {"per_period": per, "n": n_full, "n_periods_sum": total_n,
            "wins": wins, "losses": n_full - wins,
            "win_rate_pct": fs.get("win_rate_pct", 0.0),
            "return_pct": fs.get("return_pct", 0.0),
            "expectancy_R": round(total_R / total_n, 4) if total_n else 0.0,
            "total_R": round(total_R, 1),
            "periods_positive": sum(1 for x in scored if x["expectancy_R"] > 0),
            "periods_scored": len(scored),
            "worst_period_R": round(min((x["expectancy_R"] for x in scored),
                                        default=0.0), 4),
            "max_dd_pct": round(fs.get("max_drawdown_pct", worst), 2)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2026-01-01")
    ap.add_argument("--end", default=None)
    ap.add_argument("--periods", type=int, default=3)
    ap.add_argument("--min-trades", type=int, default=40)
    ap.add_argument("--universe", default="movers", choices=list(UNIVERSES))
    ap.add_argument("--vol-split", action="store_true",
                    help="also score the loud and quiet halves of the "
                         "universe separately")
    ap.add_argument("--min-atr-pct", type=float, default=0.0,
                    help="drop symbols whose typical daily range is below "
                         "this %% of price, judged on history before the "
                         "trading window")
    ap.add_argument("--only", default=None,
                    help="run ONE named config - no search, no selection. For "
                         "testing an already-chosen config on fresh data.")
    args = ap.parse_args(argv)

    universe = UNIVERSES[args.universe]
    # A holdout has to be symbols this run never touched. "wide" is every list
    # at once, so nothing is left over and the column must not be printed -
    # claiming "never seen" for names inside the tuning set is the worst kind of
    # wrong number, because it reads as the confirmation the whole run exists to
    # produce.
    # Also, movers and research share three names (TSLA, NVDA, AMD), so the
    # holdout has to have the traded universe subtracted from it, not merely be
    # a different list.
    candidate = [] if args.universe == "wide" else (
        RESEARCH if args.universe == "movers" else MOVERS)
    holdout = [s for s in candidate if s not in set(universe)]
    if len(holdout) != len(candidate):
        log.info("Holdout trimmed to %d symbols - %d were in the traded "
                 "universe", len(holdout), len(candidate) - len(holdout))
    trade_from = pd.Timestamp(args.start, tz="America/New_York")
    fetch_from = (trade_from - pd.Timedelta(days=500)).date().isoformat()

    try:
        md = MarketData(Credentials.from_env(), feed="iex")
        log.info("Fetching %d %s symbols", len(universe), args.universe)
        data = md.daily_bars(universe, start=fetch_from, end=args.end)
    except AlpacaError as exc:
        log.error("Market data unavailable: %s", exc)
        return 1
    data = {s: d for s, d in data.items() if len(d) > 260}
    if not data:
        log.error("No data.")
        return 1

    if args.min_atr_pct:
        before = len(data)
        data = {s: d for s, d in data.items()
                if median_atr_pct(d, trade_from) >= args.min_atr_pct}
        log.info("Volatility screen >= %.1f%%: kept %d of %d symbols",
                 args.min_atr_pct, len(data), before)
        if not data:
            log.error("Screen removed every symbol.")
            return 1

    configs = grid_bo()
    if args.only:
        configs = [(n, q) for n, q in configs if n == args.only]
        if not configs:
            log.error("No config named %s. Available: %s", args.only,
                      ", ".join(n for n, _ in grid_bo()))
            return 1
        log.info("Single-config validation run (no search): %s", args.only)
    log.info("Scoring %d breakout configurations", len(configs))
    results = []
    for name, p in configs:
        st = by_periods(data, p, args.periods, trade_from=trade_from)
        st["name"], st["params"] = name, p
        results.append(st)
        log.info("  %-34s n=%-4d exp=%+.4fR  positive %d/%d",
                 name, st["n"], st["expectancy_R"],
                 st["periods_positive"], st["periods_scored"])

    survivors = [r for r in results
                 if r["expectancy_R"] > 0 and r["n"] >= args.min_trades
                 and r["periods_positive"] >= max(1, r["periods_scored"] - 1)]
    survivors.sort(key=lambda r: (-r["worst_period_R"], -r["expectancy_R"]))

    hold = None
    winner = survivors[0] if survivors else None
    if winner:
        log.info("Winner %s — one run on %d unseen symbols", winner["name"],
                 len(holdout))
        try:
            hd = md.daily_bars(holdout, start=fetch_from, end=args.end)
            hd = {s: d for s, d in hd.items() if len(d) > 260}
            if hd:
                # by_periods already reports win rate, return and drawdown from
                # its own full-window run, so there is nothing to recompute.
                hold = by_periods(hd, winner["params"], args.periods,
                                  trade_from=trade_from)
        except AlpacaError as exc:
            log.warning("Holdout fetch failed: %s", exc)

    halves = {}
    if args.vol_split and winner:
        loud, quiet = split_by_volatility(data, trade_from)
        for label, subset in (("loud", loud), ("quiet", quiet)):
            if subset:
                halves[label] = by_periods(subset, winner["params"],
                                           args.periods, trade_from=trade_from)
                halves[label]["symbols"] = len(subset)
                halves[label]["median_atr_pct"] = round(float(np.median(
                    [median_atr_pct(d, trade_from) for d in subset.values()])), 2)
                log.info("  %-5s half: %d symbols, %d trades, %.1f%% win, "
                         "%+.1f%% return", label, len(subset),
                         halves[label]["n"], halves[label].get("win_rate_pct", 0),
                         halves[label].get("return_pct", 0))

    # what the best result would look like if the data were pure noise
    n = max((r["n"] for r in results), default=0)
    noise = round(1.3 / np.sqrt(n) * np.sqrt(2 * np.log(len(configs))), 3) \
        if n else 0.0

    payload = {"universe": args.universe, "symbols": len(data),
               "start": args.start, "tried": len(configs),
               "survivors": len(survivors), "noise_floor": noise,
               "results": sorted(results, key=lambda r: -r["expectancy_R"]),
               "winner": winner, "holdout": hold, "holdout_size": len(holdout),
               "halves": halves}
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / "breakout.json").write_text(json.dumps(payload, indent=2, default=str))
    text = render(payload)
    (REPORTS / "breakout.md").write_text(text)
    print("\n" + text)
    return 0


def render(p: dict) -> str:
    """Plain terms: trades won, trades lost, win rate, profit."""
    out = [
        "# Expansion breakout",
        "",
        f"**{p['symbols']} {p['universe']} symbols · from {p['start']} · "
        f"{datetime.now():%Y-%m-%d %H:%M}**",
        "",
        f"**{p['tried']} settings tried.** {p['survivors']} passed.",
        "",
    ]
    if p["tried"] > 1:
        out += [f"> Trying {p['tried']} settings on data this size produces a "
                f"best result of roughly **+{p['noise_floor']}R** by luck "
                "alone. Treat anything near that as noise.", ""]

    out += ["| Settings | Trades | Won | Lost | Win % | Profit |",
            "|---|---|---|---|---|---|"]
    for r in p["results"][:12]:
        warn = "" if r["n"] >= 40 else " ⚠"
        out.append(f"| `{r['name']}` | {r['n']}{warn} | {r.get('wins','—')} | "
                   f"{r.get('losses','—')} | {r.get('win_rate_pct','—')}% | "
                   f"**{r.get('return_pct',0):+.1f}%** |")

    w, h = p.get("winner"), p.get("holdout")
    out += ["", "## Selected", ""]
    if not w:
        out += ["**Nothing passed.** No setting was profitable while staying "
                "positive across periods on an adequate number of trades. The "
                "unseen stocks were not touched.", "",
                f"Worth noting: a search over {p['tried']} settings could not "
                "find a profitable one even by accident. When a dataset cannot "
                "be overfitted, the idea is wrong for it rather than mistuned."]
        return "\n".join(out)

    out += [f"**`{w['name']}`**", ""]
    if h and p.get("holdout_size"):
        out += ["| | Tuned on | **Never seen** |", "|---|---|---|",
                f"| Trades | {w['n']} | **{h['n']}** |",
                f"| Won / lost | {w.get('wins','—')} / {w.get('losses','—')} | "
                f"**{h.get('wins','—')} / {h.get('losses','—')}** |",
                f"| Win rate | {w.get('win_rate_pct','—')}% | "
                f"**{h.get('win_rate_pct','—')}%** |",
                f"| Profit | {w.get('return_pct',0):+.1f}% | "
                f"**{h.get('return_pct',0):+.1f}%** |",
                f"| Worst drop | {w['max_dd_pct']}% | **{h['max_dd_pct']}%** |"]
    else:
        out += ["| | Tuned on |", "|---|---|",
                f"| Trades | {w['n']} |",
                f"| Won / lost | {w.get('wins','—')} / {w.get('losses','—')} |",
                f"| Win rate | {w.get('win_rate_pct','—')}% |",
                f"| Profit | {w.get('return_pct',0):+.1f}% |",
                f"| Worst drop | {w['max_dd_pct']}% |", "",
                "**No unseen stocks in this run.** Every symbol on the lists "
                "was traded, so there is nothing left to check the result "
                "against. These numbers are in-sample and prove nothing on "
                "their own."]

    halves = p.get("halves") or {}
    if halves:
        out += ["", "## Does it need volatile stocks?", "",
                "Same settings, universe split by typical daily range.", "",
                "| Half | Symbols | Typical range | Trades | Won | Lost | Win % | Profit |",
                "|---|---|---|---|---|---|---|---|"]
        for label in ("loud", "quiet"):
            hh = halves.get(label)
            if not hh:
                continue
            out.append(f"| **{label}** | {hh.get('symbols','—')} | "
                       f"{hh.get('median_atr_pct','—')}% | {hh['n']} | "
                       f"{hh.get('wins','—')} | {hh.get('losses','—')} | "
                       f"{hh.get('win_rate_pct','—')}% | "
                       f"**{hh.get('return_pct',0):+.1f}%** |")
        loud, quiet = halves.get("loud"), halves.get("quiet")
        if loud and quiet:
            gap = loud.get("return_pct", 0) - quiet.get("return_pct", 0)
            # The split is a median cut, so "loud" only means louder than the
            # rest of this universe. If the loud half is still calmer than the
            # bar the autopsy set (winners averaged 5.35% daily range), the
            # test never put the idea under load and must not be read as
            # confirming it.
            loud_atr = loud.get("median_atr_pct") or 0.0
            quiet_atr = quiet.get("median_atr_pct") or 0.0
            spread = loud_atr - quiet_atr
            if loud_atr < VOL_BAR_PCT:
                out += ["", "**Read:** inconclusive, and not because of the "
                        f"result. The loud half's typical daily range is only "
                        f"{loud_atr:.1f}%, against the {VOL_BAR_PCT:.1f}% "
                        "average of past winners — so both halves are quiet "
                        "names and neither tested the idea. Re-run this split "
                        "on a universe that actually contains movers."]
            elif spread < MIN_VOL_SPREAD_PCT:
                out += ["", "**Read:** inconclusive. The two halves differ by "
                        f"only {spread:.1f}% in typical daily range, which is "
                        "too little separation to attribute anything to "
                        "volatility."]
            elif gap > MIN_HALF_GAP_PCT:
                out += ["", "**Read:** the volatile half returned "
                        f"{gap:+.1f}% more than the quiet half, on a real "
                        f"{spread:.1f}% separation in daily range. The edge "
                        "lives in the movers — screen the quiet names out."]
            else:
                out += ["", "**Read:** the halves are within "
                        f"{abs(gap):.1f}% of each other despite a {spread:.1f}%"
                        " separation in daily range. Volatility does not "
                        "explain the result, so screening on it would not "
                        "help."]

    out += ["", "### Verdict", ""]
    beats = w["expectancy_R"] > p["noise_floor"] or p["tried"] == 1
    if not beats:
        out.append(f"**Too close to noise.** {w.get('return_pct',0):+.1f}% on "
                   f"the tuned set does not clear what {p['tried']} settings "
                   "produce by chance. Not tradeable.")
    elif not p.get("holdout_size"):
        out.append("**In-sample only.** This run traded every symbol on the "
                   "lists, so there were no unseen stocks to check against. "
                   "Use it to compare halves or settings against each other, "
                   "never as evidence the rule works.")
    elif h and h.get("return_pct", 0) > 0 and h["n"] >= 30:
        out.append(f"**Profitable on stocks it had never seen: "
                   f"{h.get('return_pct',0):+.1f}% over {h['n']} trades, "
                   f"{h.get('wins','—')} winners against "
                   f"{h.get('losses','—')} losers.** Paper trade it next. Do "
                   "not re-tune against those stocks - they have been used.")
    else:
        out.append("**Worked where it was tuned, not on unseen stocks.** The "
                   "unseen number is the honest one.")
    return "\n".join(out)


if __name__ == "__main__":
    raise SystemExit(main())
