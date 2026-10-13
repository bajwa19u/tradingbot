"""How every Discord message looks, in both day-trade channels (and, by copy,
the swing channel in the vwap-ema-swing repo). One house style:

  new signal   🔔 BUY CALLS · NVDA     one neutral colour: it is an instruction, not a result
  closed       🟢 SOLD · NVDA CALLS · +0.35%    green for a profit, red for a loss
  missed       ⚪ MISSED · NVDA CALLS            seen too late to act on
  daily report 📊 Day Trades · Daily Report     today, last 5 days, last week, month to date

Messages are Discord embeds (a coloured box with labelled fields), not text
lined up with spaces. Levels are the stock's price; long = calls, short = puts.
No dollar signs and no share counts (house rules).
"""
from __future__ import annotations

import datetime as _dt

import pandas as pd

BLUE, GREEN, RED, GREY, GOLD = 0x5865F2, 0x2ECC71, 0xE74C3C, 0x95A5A6, 0xF1C40F
DISCLAIMER = "Signals only, not financial advice"
CLOSED_BY = {"target": "Target hit", "stop": "Stop hit", "bell": "End of day (15:55)", "close": "End of day (15:55)",
             "time": "Time limit", "breakeven": "Stopped at entry (breakeven)"}


def _px(v) -> str:
    return "–" if v is None else f"{v:,.2f}"


def _pct(v: float) -> str:
    return f"{v:+.2f}%".replace("-", "−")


def contract(t: dict) -> str:
    return "CALLS" if t.get("side") == "long" else "PUTS"


def closed_by(t: dict) -> str:
    why = t.get("reason") or ""
    if why == "stop" and t.get("exit") is not None and abs(t["exit"] - t["entry"]) <= 0.002 * t["entry"]:
        why = "breakeven"
    return CLOSED_BY.get(why, why.capitalize())


def _signal_time(t: dict) -> str:
    """The close of the entry bar (entry_time is the bar's start)."""
    try:
        hh, mm = int(t["entry_time"][:2]), int(t["entry_time"][3:5])
    except (KeyError, ValueError, TypeError):
        return t.get("entry_time", "–")
    bar = 5 if t.get("rule") == "retest" else 1
    m = hh * 60 + mm + bar
    return f"{m // 60:02d}:{m % 60:02d}:00 ET"


def _target(t: dict) -> str:
    return _px(t["target"]) if t.get("target") else "None · held to 15:55"


def signal_embed(t: dict, channel: str, setup: str) -> dict:
    """A trade's one message: new, missed, or closed (the same message is edited)."""
    sym, kind = t["symbol"], contract(t)
    footer = {"text": f"{channel} · {setup} · Levels are the stock price · {DISCLAIMER}"}
    levels = [{"name": "Entry", "value": _px(t["entry"]), "inline": True},
              {"name": "Stop", "value": _px(t["stop"]), "inline": True},
              {"name": "Target", "value": _target(t), "inline": True}]
    if t.get("exit") is not None:
        won = (t.get("pct") or 0) > 0
        move = (t["exit"] / t["entry"] - 1) * 100 * (1 if t["side"] == "long" else -1)
        return {"title": f"{'🟢' if won else '🔴'} SOLD · {sym} {kind} · {_pct(t['pct'] or 0)}",
                "color": GREEN if won else RED,
                "fields": [{"name": "Bought", "value": f"{_px(t['entry'])} at {t['entry_time']} ET", "inline": True},
                           {"name": "Sold", "value": f"{_px(t['exit'])} at {t.get('exit_time') or '–'} ET", "inline": True},
                           {"name": "Result", "value": f"**{_pct(t['pct'] or 0)}** of account", "inline": True},
                           {"name": "Closed by", "value": closed_by(t), "inline": True},
                           {"name": "Stock move", "value": _pct(move), "inline": True},
                           {"name": "Stop · Target", "value": f"{_px(t['stop'])} · {_target(t)}", "inline": True}],
                "footer": footer}
    if t.get("expired"):
        age = t.get("age_s") or 0
        late = f"{age / 60:.0f} min" if age >= 90 else f"{age:.0f} s"
        return {"title": f"⚪ MISSED · {sym} {kind}", "color": GREY,
                "description": f"Signal seen {late} after its bar closed. **Do not enter.**",
                "fields": levels, "footer": footer}
    rr = abs(t["target"] - t["entry"]) / max(abs(t["entry"] - t["stop"]), 1e-9) if t.get("target") else None
    age = t.get("age_s")
    detail = t.get("why_line") or ""
    return {"title": f"🔔 BUY {kind} · {sym}", "color": BLUE,
            "description": (f"Opening-range breakout {'above' if t['side'] == 'long' else 'below'} "
                            f"{_px(t.get('level'))}." if t.get("level") else "") + (f"\n{detail}" if detail else ""),
            "fields": levels + [
                {"name": "Reward : risk", "value": f"{rr:.1f} : 1" if rr else "Open-ended", "inline": True},
                {"name": "Signal", "value": _signal_time(t) + (f" · {age:.0f} s ago" if age is not None else ""), "inline": True},
                {"name": "Exit plan", "value": "Stop, target or 15:55" if t.get("target") else "Stop or 15:55", "inline": True}],
            "footer": footer}


def window_stats(rows: pd.DataFrame) -> dict:
    """rows: one per closed trade with a `pct` column (% of account)."""
    r = rows["pct"].astype(float) if len(rows) else pd.Series(dtype=float)
    w = int((r > 0).sum())
    return {"n": len(r), "won": w, "lost": len(r) - w, "total": float(r.sum()),
            "win": 100 * w / len(r) if len(r) else None}


def windows(ledger: pd.DataFrame, day: _dt.date) -> list[tuple[str, dict]]:
    """Today, the last 5 sessions, last calendar week (Mon-Fri) and month to date."""
    if ledger is None or not len(ledger):
        ledger = pd.DataFrame(columns=["date", "pct"])
    d = pd.to_datetime(ledger["date"]).dt.date
    sessions = sorted({x for x in d if x <= day} | {day})
    last5 = set(sessions[-5:])
    monday = day - _dt.timedelta(days=day.weekday())
    lw_start, lw_end = monday - _dt.timedelta(days=7), monday - _dt.timedelta(days=3)
    return [("Today", window_stats(ledger[d == day])),
            ("Last 5 days", window_stats(ledger[d.isin(last5)])),
            (f"Last week ({lw_start:%-d}–{lw_end:%-d %b})", window_stats(ledger[(d >= lw_start) & (d <= lw_end)])),
            (f"{day:%B} to date", window_stats(ledger[(d >= day.replace(day=1)) & (d <= day)]))]


def _window_value(s: dict) -> str:
    if not s["n"]:
        return "No trades"
    return f"**{_pct(s['total'])}**\nWin rate {s['win']:.0f}%\n{s['won']} won · {s['lost']} lost"


def daily_report_embed(channel: str, day: _dt.date, today: list[dict], ledger: pd.DataFrame, sizing: str) -> dict:
    """The end-of-day report: today's trades, then performance over four windows."""
    done = [t for t in today if t.get("exit") is not None]
    tot = sum(t.get("pct") or 0 for t in done)
    lines = []
    for t in sorted(done, key=lambda x: x.get("entry_time") or ""):
        won = (t.get("pct") or 0) > 0
        lines.append(f"{'🟢' if won else '🔴'} **{t['symbol']}** {contract(t).title()}  ·  "
                     f"{t['entry_time']} → {t.get('exit_time')}  ·  {closed_by(t)}  ·  **{_pct(t.get('pct') or 0)}**")
    body = "\n".join(lines) if lines else "No trades today: no setup met the rules."
    open_ = [t for t in today if t.get("exit") is None]
    if open_:
        body += "\n" + "\n".join(f"⏳ **{t['symbol']}** {contract(t).title()} still open" for t in open_)
    return {"title": f"📊 {channel} · Daily Report", "color": GREEN if tot > 0 else RED if tot < 0 else GREY,
            "description": f"**{day:%A %-d %B %Y}**\n\n{body}",
            "fields": [{"name": nm, "value": _window_value(s), "inline": True} for nm, s in windows(ledger, day)],
            "footer": {"text": f"{sizing} · {DISCLAIMER}"}}


def picks_embed(picks: list[tuple], day_label: str, note: str) -> dict:
    if not picks:
        return {"title": "📋 Watchlist", "color": GREY, "description": f"**{day_label}**\nNothing unusual at the open."}
    return {"title": "📋 Today's Watchlist", "color": BLUE,
            "description": f"**{day_label}**\n" + "\n".join(f"**{s}**  ·  opening volume {r:.1f}× normal" for s, r in picks),
            "footer": {"text": note}}


def alert_embed(title: str, text: str) -> dict:
    return {"title": f"⚠️ {title}", "color": GOLD, "description": text}


def as_text(msg) -> str:
    """Plain-text rendering of an embed, for logs, dry runs and tests."""
    if isinstance(msg, str):
        return msg
    parts = [msg.get("title", "")]
    if msg.get("description"):
        parts.append(msg["description"])
    parts += [f"{f['name']}: {f['value']}" for f in msg.get("fields", [])]
    if msg.get("footer"):
        parts.append(msg["footer"]["text"])
    return "\n".join(parts)
