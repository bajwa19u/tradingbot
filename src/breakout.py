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
    scored = [x for x in per if x["n"] >= 8]
    return {"per_period": per, "n": total_n,
            "expectancy_R": round(total_R / total_n, 4) if total_n else 0.0,
            "total_R": round(total_R, 1),
            "periods_positive": sum(1 for x in scored if x["expectancy_R"] > 0),
            "periods_scored": len(scored),
            "worst_period_R": round(min((x["expectancy_R"] for x in scored),
                                        default=0.0), 4),
            "max_dd_pct": round(worst, 2)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2026-01-01")
    ap.add_argument("--end", default=None)
    ap.add_argument("--periods", type=int, default=3)
    ap.add_argument("--min-trades", type=int, default=40)
    ap.add_argument("--universe", default="movers", choices=list(UNIVERSES))
    ap.add_argument("--only", default=None,
                    help="run ONE named config - no search, no selection. For "
                         "testing an already-chosen config on fresh data.")
    args = ap.parse_args(argv)

    universe = UNIVERSES[args.universe]
    holdout = RESEARCH if args.universe == "movers" else MOVERS
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
                hold = by_periods(hd, winner["params"], args.periods,
                                  trade_from=trade_from)
                prep = prepare(hd, winner["params"])
                full = run_portfolio(prep, winner["params"],
                                     sigs=signal_times_bo(prep, winner["params"]),
                                     lo=trade_from)["stats"]
                hold["win_rate_pct"] = full.get("win_rate_pct")
                hold["return_pct"] = full.get("return_pct")
        except AlpacaError as exc:
            log.warning("Holdout fetch failed: %s", exc)

    # what the best result would look like if the data were pure noise
    n = max((r["n"] for r in results), default=0)
    noise = round(1.3 / np.sqrt(n) * np.sqrt(2 * np.log(len(configs))), 3) \
        if n else 0.0

    payload = {"universe": args.universe, "symbols": len(data),
               "start": args.start, "tried": len(configs),
               "survivors": len(survivors), "noise_floor": noise,
               "results": sorted(results, key=lambda r: -r["expectancy_R"]),
               "winner": winner, "holdout": hold, "holdout_size": len(holdout)}
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / "breakout.json").write_text(json.dumps(payload, indent=2, default=str))
    text = render(payload)
    (REPORTS / "breakout.md").write_text(text)
    print("\n" + text)
    return 0


def render(p: dict) -> str:
    out = [
        "# Expansion breakout",
        "",
        f"**{p['symbols']} {p['universe']} symbols · from {p['start']} · "
        f"{datetime.now():%Y-%m-%d %H:%M}**",
        "",
        f"**{p['tried']} configurations tried.** {p['survivors']} passed.",
        "",
        f"> With this many configurations and this sample size, the best "
        f"result from pure noise would be about **+{p['noise_floor']}R**. "
        "Anything at or below that is indistinguishable from luck.",
        "",
        "| Configuration | Trades | Expectancy | Positive in | Worst period | Max DD |",
        "|---|---|---|---|---|---|",
    ]
    for r in p["results"][:12]:
        warn = "" if r["n"] >= 40 else " ⚠"
        out.append(f"| `{r['name']}` | {r['n']}{warn} | {r['expectancy_R']:+.4f}R | "
                   f"{r['periods_positive']}/{r['periods_scored']} | "
                   f"{r['worst_period_R']:+.4f}R | {r['max_dd_pct']}% |")

    w, h = p.get("winner"), p.get("holdout")
    out += ["", "## Selected", ""]
    if not w:
        out += ["**Nothing passed.** No configuration was profitable while "
                "staying positive across periods on an adequate sample. The "
                "holdout was not opened.", "",
                "Worth noting what that means: a search over "
                f"{p['tried']} configurations could not find a profitable one "
                "even by chance. When a dataset cannot be overfitted, the "
                "premise is wrong for it rather than merely mistuned."]
        return "\n".join(out)

    beats_noise = w["expectancy_R"] > p["noise_floor"]
    out += [f"**`{w['name']}`**", "",
            "| | Search universe | **Holdout (unseen)** |", "|---|---|---|",
            f"| Trades | {w['n']} | **{h['n'] if h else 'n/a'}** |"]
    if h:
        out += [f"| Expectancy | {w['expectancy_R']:+.4f}R | "
                f"**{h['expectancy_R']:+.4f}R** |",
                f"| Total R | {w['total_R']:+.1f} | **{h['total_R']:+.1f}** |",
                f"| Positive in | {w['periods_positive']}/{w['periods_scored']} "
                f"| **{h['periods_positive']}/{h['periods_scored']}** |",
                f"| Win rate | — | **{h.get('win_rate_pct','—')}%** |",
                f"| Max drawdown | {w['max_dd_pct']}% | **{h['max_dd_pct']}%** |"]
    out += ["", "### Verdict", ""]
    if not beats_noise:
        out.append(f"**Below the noise floor.** {w['expectancy_R']:+.4f}R does "
                   f"not clear the +{p['noise_floor']}R a search this size "
                   "produces by chance. Not tradeable.")
    elif h and h["expectancy_R"] > 0 and h["n"] >= 30:
        out.append(f"**Clears the noise floor (+{p['noise_floor']}R) and stayed "
                   "positive on unseen symbols.** That is the first result in "
                   "this project to do both. Paper trade it before anything "
                   "else — and do not re-tune against that holdout.")
    else:
        out.append(f"**Clears the noise floor but did not hold on unseen "
                   "symbols.** The search universe result was fitted; the "
                   "holdout is the honest number.")
    return "\n".join(out)


if __name__ == "__main__":
    raise SystemExit(main())
