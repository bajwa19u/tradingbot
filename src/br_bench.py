"""Break & Retest V1: benchmark trades - setups a human picked by hand.

Each benchmark in br_benchmarks.yaml is matched against what the strategy
did that session, and gets exactly one status:

  detected             a signal on the same symbol, side (and level, if given)
                       within `window_min` of the benchmark's time
  entered_differently  a signal that day, same side, but at another time or level
  rejected             the setup was seen near that time but not taken - with
                       the rule that rejected it
  missed               nothing near that time: no breakout of a matching level
  no_data              the date is outside the data, or the session is incomplete

The point is to learn why the rules disagree with a human, not to bend the
rules until they agree - a benchmark is evidence, never a target.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import yaml

from .config import REPO_ROOT

PATH = REPO_ROOT / "br_benchmarks.yaml"


def load(path=None) -> list[dict]:
    p = Path(path) if path else PATH
    if not p.exists():
        return []
    raw = yaml.safe_load(p.read_text()) or {}
    return [b for b in (raw.get("benchmarks") or []) if b.get("symbol") and b.get("date")]


def _t(b: dict) -> pd.Timestamp:
    return pd.Timestamp(f"{b['date']} {b.get('time', '09:30')}", tz="America/New_York")


def _level_ok(b: dict, kind: str) -> bool:
    want = str(b.get("level") or "").lower().replace(" ", "_")
    return not want or want in str(kind).lower()


def evaluate(benchmarks: list[dict], decided: pd.DataFrame, ev: pd.DataFrame,
             have_dates: set, window_min: int = 15) -> list[dict]:
    out = []
    for b in benchmarks:
        sym, side, t = b["symbol"].upper(), str(b.get("direction", "")).lower(), _t(b)
        d = t.date()
        res = {**b, "status": "missed", "why": "", "matched": ""}
        if d not in have_dates:
            res.update(status="no_data", why="date outside the data loaded")
            out.append(res)
            continue
        day = lambda df: df[(df.symbol == sym) & (df.date.astype(str) == str(d))  # noqa: E731
                            & ((df.direction == side) if side else True)] if len(df) else df
        near = lambda df, col: df[(pd.to_datetime(df[col]) - t).abs() <= pd.Timedelta(minutes=window_min)]  # noqa: E731
        taken = day(decided[decided.taken]) if len(decided) else decided
        hit = taken[[_level_ok(b, k) for k in taken.level_kind]] if len(taken) else taken
        if len(hit) and len(near(hit, "signal_ts")):
            r = near(hit, "signal_ts").iloc[0]
            res.update(status="detected", matched=_desc(r))
        elif len(taken):
            r = taken.iloc[0]
            res.update(status="entered_differently", matched=_desc(r),
                       why="signal that day, but a different time or level")
        else:
            seen = day(ev)
            if len(seen):
                seen = seen[[_level_ok(b, k) for k in seen.level_kind]]
            cand = near(seen, "t_known") if len(seen) and "t_known" in seen else seen.iloc[0:0]
            if len(cand):
                r = cand.iloc[0]
                blocked = decided[(decided.symbol == sym) & (decided.level_name == r.level_name)
                                  & (decided.date.astype(str) == str(d)) & ~decided.taken] if len(decided) else decided
                why = blocked.reject_reason.iloc[0] if len(blocked) else r.status
                res.update(status="rejected", why=f"{why}", matched=_desc(r))
            else:
                res.update(why="no breakout of a matching level near that time")
        out.append(res)
    return out


def _desc(r) -> str:
    t = pd.Timestamp(r.get("signal_ts") if pd.notna(r.get("signal_ts")) else r.get("t_known"))
    return f"{r.symbol} {r.direction} {r.level_name} {r.level:.2f} at {t:%H:%M} ({r.tf}m)"


def markdown(results: list[dict]) -> str:
    if not results:
        return ("No benchmark trades entered yet. Add them to `br_benchmarks.yaml` "
                "(symbol, date, time, direction, level, note).")
    lines = ["| symbol | date | time | side | level | status | why | strategy saw |", "|---|---|---|---|---|---|---|---|"]
    for r in results:
        lines.append(f"| {r['symbol']} | {r['date']} | {r.get('time', '')} | {r.get('direction', '')} | "
                     f"{r.get('level', '')} | **{r['status']}** | {r['why']} | {r['matched']} |")
    return "\n".join(lines)
