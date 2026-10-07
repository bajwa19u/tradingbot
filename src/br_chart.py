"""Break & Retest V1: trade chart screenshots.

Rendered from bar data, not captured from a screen, so the live bot (at the
signal, +5 and +10 minutes) and the end-of-day replay (stop / target, after
the fact) draw exactly the same picture of the same moment. A chart drawn
"as of" a time shows only the bars that had closed by then.
"""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

from .br_levels import vwap  # noqa: E402

UP, DOWN = "#26a69a", "#ef5350"
LEVEL_STYLE = {"pdh": ("#1e88e5", "PDH"), "pdl": ("#1e88e5", "PDL"), "pdc": ("#8e24aa", "PDC"),
               "pmh": ("#fb8c00", "PMH"), "pml": ("#fb8c00", "PML")}


def render(path: str | Path, symbol: str, direction: str, day_1m: pd.DataFrame, as_of,
           levels: dict, trade: dict, title_note: str = "", lookback_min: int = 75,
           strategy: str = "Break & Retest V1") -> Path:
    """Draw `day_1m` (today's extended 1-minute bars) up to `as_of`.

    levels: {"pdh": px, "pdl": px, "pmh": px, "pml": px, "pdc": px} (missing ok)
    trade:  {"level": px, "level_name": str, "entry": px, "stop": px,
             "target": px, "signal_ts": ts, "exit_ts": ts|None, "outcome": str|None}
    """
    as_of = pd.Timestamp(as_of)
    sig = pd.Timestamp(trade["signal_ts"])
    start = min(sig - pd.Timedelta(minutes=lookback_min), sig.normalize() + pd.Timedelta(hours=9, minutes=15))
    bars = day_1m[(day_1m.index >= start) & (day_1m.index + pd.Timedelta(minutes=1) <= as_of)]
    rth_all = day_1m[(day_1m.index.hour * 60 + day_1m.index.minute) >= 570]
    rth = rth_all[rth_all.index + pd.Timedelta(minutes=1) <= as_of]
    vw = vwap(rth) if len(rth) else pd.Series(dtype=float)

    fig, ax = plt.subplots(figsize=(11, 6), dpi=90)
    xs = {t: i for i, t in enumerate(bars.index)}
    for t, r in bars.iterrows():
        x, col = xs[t], UP if r.close >= r.open else DOWN
        ax.vlines(x, r.low, r.high, color=col, linewidth=0.8)
        lo, hi = sorted((r.open, r.close))
        ax.add_patch(plt.Rectangle((x - 0.35, lo), 0.7, max(hi - lo, 1e-6), color=col))
    if len(vw):
        vx = [xs[t] for t in vw.index if t in xs]
        ax.plot(vx, [vw[t] for t in vw.index if t in xs], color="#6d4c41", linewidth=1.2, label="VWAP")
    n = max(len(bars), 1)
    for k, px in levels.items():
        if px is None or px != px:
            continue
        col, name = LEVEL_STYLE.get(k, ("#757575", k.upper()))
        ax.axhline(px, color=col, linewidth=0.9, linestyle="--", alpha=0.8)
        ax.text(n - 1, px, f" {name} {px:.2f}", color=col, fontsize=8, va="bottom", ha="right")
    ax.axhline(trade["level"], color="black", linewidth=1.6, alpha=0.7)
    ax.text(0, trade["level"], f" {trade.get('level_name', 'level')} {trade['level']:.2f}",
            fontsize=8, va="bottom", fontweight="bold")
    for key, col in (("entry", "#1565c0"), ("stop", DOWN), ("target", UP)):
        px = trade.get(key)
        if px:
            ax.axhline(px, color=col, linewidth=1.3)
            ax.text(n - 1, px, f"{key.upper()} {px:.2f} ", color=col, fontsize=9, va="top", ha="right")
    for key, mark, col in (("signal_ts", "^" if direction == "long" else "v", "#1565c0"),
                           ("exit_ts", "X", "black")):
        t = trade.get(key)
        if t is None:
            continue
        t = pd.Timestamp(t) - pd.Timedelta(minutes=1) if key == "signal_ts" else pd.Timestamp(t)
        if t in xs:
            y = trade["entry"] if key == "signal_ts" else trade.get("exit_px", trade["entry"])
            ax.plot(xs[t], y, marker=mark, color=col, markersize=11)
    ticks = [i for i, t in enumerate(bars.index) if t.minute % 15 == 0]
    ax.set_xticks(ticks, [f"{bars.index[i]:%H:%M}" for i in ticks], fontsize=8)
    ax.set_xlim(-1, n + 1)
    side = "LONG" if direction == "long" else "SHORT"
    outcome = f" — {trade['outcome'].upper()}" if trade.get("outcome") else ""
    ax.set_title(f"{symbol}  {side}  ·  {strategy}  ·  as of {as_of:%Y-%m-%d %H:%M} ET{outcome}"
                 + (f"\n{title_note}" if title_note else ""), fontsize=10)
    ax.grid(alpha=0.15)
    if len(vw):
        ax.legend(loc="upper left", fontsize=8)
    fig.tight_layout()
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path)
    plt.close(fig)
    return path


def snapshots(trade: dict, cfg) -> dict:
    """The moments a trade is photographed: name -> as-of time."""
    sig = pd.Timestamp(trade["signal_ts"])
    out = {"signal": sig, "plus5": sig + pd.Timedelta(minutes=5), "plus10": sig + pd.Timedelta(minutes=10)}
    if trade.get("outcome") == "stop" and trade.get("exit_ts") is not None:
        out["stop"] = pd.Timestamp(trade["exit_ts"]) + pd.Timedelta(minutes=1)
    if trade.get("outcome") == "target" and trade.get("exit_ts") is not None:
        out["target"] = pd.Timestamp(trade["exit_ts"]) + pd.Timedelta(minutes=1)
    return out
