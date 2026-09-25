"""Run the daily strategy over one symbol and show its reasoning bar by bar.

Answers "would the bot have taken that trade?" and, more usefully, "if not,
which rule stopped it?". Every gate is printed per bar so a disagreement
between the chart and the code is a specific column, not a mystery.

    python -m src.inspect_symbol MET --start 2024-01-01
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime

import pandas as pd

from .config import REPO_ROOT, Credentials
from .data import AlpacaError, MarketData
from .swing import BASE, indicators, prepare, run_portfolio, signal_times

REPORTS = REPO_ROOT / "reports"


def gates(df: pd.DataFrame, p: dict) -> pd.DataFrame:
    """Each rule, evaluated per bar, as its own column."""
    f, m, s = p["fast"], p["mid"], p["slow"]
    ef, em, es = df[f"ema{f}"], df[f"ema{m}"], df[f"ema{s}"]
    a = df["atr"]

    stack = (ef > em) & (em > es) & (df["close"] > es)
    slope_n = p.get("slope_bars", 0)
    rising = pd.Series(True, index=df.index)
    if slope_n and p.get("min_slope_atr", 0.0):
        rising = (ef - ef.shift(slope_n)) >= a * p["min_slope_atr"]
    uptrend = stack & rising
    touched = df["low"] <= ef + a * p["touch_atr"]
    out = pd.DataFrame(index=df.index)
    out["close"] = df["close"].round(2)
    out[f"ema{f}"] = ef.round(2)
    out["stack_ok"] = stack
    out["still_rising"] = rising
    out["held_10d"] = uptrend.rolling(p["trend_bars"],
                                      min_periods=p["trend_bars"]).min().fillna(0).astype(bool)
    out["touched_ema"] = touched.rolling(p["touch_window"],
                                         min_periods=1).max().astype(bool)
    out["above_mid"] = df["close"] > em
    out["green_close_above"] = (df["close"] > ef) & (df["close"] > df["open"])
    out["SIGNAL"] = (out["stack_ok"] & out["still_rising"] & out["held_10d"]
                     & out["touched_ema"] & out["above_mid"]
                     & out["green_close_above"] & a.notna())
    return out


def why_not(row) -> str:
    if row["SIGNAL"]:
        return "ENTRY"
    reasons = {
        "stack_ok": "no uptrend (EMA stack out of order)",
        "still_rising": "trend has gone flat",
        "held_10d": "trend too new",
        "touched_ema": "no pullback to the EMA",
        "above_mid": "closed below the mid EMA - pullback too deep",
        "green_close_above": "no green close back above the EMA",
    }
    missing = [k for k in reasons if k in row.index and not row[k]]
    return "; ".join(reasons[k] for k in missing) or "—"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("symbol")
    ap.add_argument("--start", default="2024-01-01")
    ap.add_argument("--end", default=None)
    ap.add_argument("--fast", type=int, default=None)
    ap.add_argument("--slope", type=float, default=None,
                    help="min ATR the fast EMA must have risen over "
                         "slope_bars; 0 disables the chop filter")
    ap.add_argument("--show", type=int, default=60,
                    help="how many recent bars to print in full")
    args = ap.parse_args(argv)

    p = dict(BASE)
    if args.fast:
        p["fast"] = args.fast
    if args.slope is not None:
        p["min_slope_atr"] = args.slope
    sym = args.symbol.upper()
    trade_from = pd.Timestamp(args.start, tz="America/New_York")
    fetch_from = (trade_from - pd.Timedelta(days=500)).date().isoformat()

    try:
        md = MarketData(Credentials.from_env(), feed="iex")
        data = md.daily_bars([sym], start=fetch_from, end=args.end)
    except AlpacaError as exc:
        print(f"Market data unavailable: {exc}")
        return 1
    df = data.get(sym)
    if df is None or len(df) < p["slow"] + 30:
        print(f"Not enough history for {sym}")
        return 1

    prepared = prepare({sym: df}, p)
    sigs = signal_times(prepared, p)
    res = run_portfolio(prepared, p, sigs=sigs, lo=trade_from)
    table = gates(prepared[sym], p)
    table = table[table.index >= trade_from]

    lines = [f"# {sym} — what the strategy saw",
             "",
             f"**Window:** {args.start} → {args.end or 'today'} · daily bars  ",
             f"**Rules:** EMA{p['fast']}/{p['mid']}/{p['slow']}, "
             f"pullback within {p['touch_atr']} ATR of EMA{p['fast']}, "
             f"stop {p['stop_atr']} ATR under the pullback low  ",
             f"**Generated:** {datetime.now():%Y-%m-%d %H:%M}",
             "",
             f"## Trades it would have taken: {len(res['trades'])}",
             ""]
    if res["trades"]:
        lines += ["| Entry | Exit | Entry px | Exit px | R | Reason | Days |",
                  "|---|---|---|---|---|---|---|"]
        for t in res["trades"]:
            lines.append(f"| {t['entry_date']} | {t['exit_date']} | "
                         f"{t['entry']:.2f} | {t['exit']:.2f} | "
                         f"{t['r_multiple']:+.2f} | {t['reason']} | {t['bars_held']} |")
        st = res["stats"]
        lines += ["", f"**{st['n_trades']} trades · {st['win_rate_pct']}% win rate "
                      f"· {st['expectancy_R']:+.3f}R expectancy · "
                      f"{st['total_R']:+.1f}R total**", ""]
    else:
        lines += ["_None._", ""]

    signals_in_window = sorted(t for t in sigs[sym] if t >= trade_from)
    lines += [f"## Days that met every rule: {len(signals_in_window)}", ""]
    if signals_in_window:
        lines.append(", ".join(str(t.date()) for t in signals_in_window))
    lines += ["", "_A day can meet every rule and still not become a trade if a "
                  "position in this name was already open._", "",
              f"## Last {args.show} bars, rule by rule", "",
              "| Date | Close | EMA | Stack | Rising | Held | Pullback "
              "| Not too deep | Green close | Verdict |",
              "|---|---|---|---|---|---|---|---|---|---|"]
    tick = {True: "✅", False: "·"}
    ema_col = f"ema{p['fast']}"
    for ts, row in table.tail(args.show).iterrows():
        verdict = "**ENTRY**" if row["SIGNAL"] else why_not(row)
        lines.append(
            f"| {ts.date()} | {row['close']:.2f} | {row[ema_col]:.2f} "
            f"| {tick[bool(row['stack_ok'])]} | {tick[bool(row['still_rising'])]} "
            f"| {tick[bool(row['held_10d'])]} "
            f"| {tick[bool(row['touched_ema'])]} | {tick[bool(row['above_mid'])]} "
            f"| {tick[bool(row['green_close_above'])]} | {verdict} |")

    text = "\n".join(lines)
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / f"inspect_{sym}.md").write_text(text)
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
