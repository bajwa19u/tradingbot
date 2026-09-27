"""Paper account — the forward test.

Everything in this repo before this file was a backtest, and the single
clearest finding of the project is that backtests here have been wrong. The
adaptive loop searched configurations 33 times: fit expectancy averaged +0.4R,
forward expectancy about -1.0R. A forward test is the only measurement that has
not lied.

So this file does one thing: it runs the chosen rule on today's real bars, day
after day, and keeps score. No search, no parameters to pick, nothing to tune.

The design choice that matters: the ledger is DERIVED, not stored. Every run
replays the whole period from `paper.start` through the same `run_portfolio`
the backtest uses, and writes the result out. Nothing accumulates in a state
file that could drift, corrupt, or silently disagree with the backtest. If the
engine changes, the paper record changes with it and stays honest. The cost is
a full refetch each run, which takes seconds.

    python -m src.paper              # score it, write reports/paper.md
    python -m src.paper --dry-run    # print, write nothing
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime

import pandas as pd

from .breakout import (BASE_BO, median_atr_pct, prepare, signal_times_bo)
from .config import REPO_ROOT, Credentials, load_config
from .data import AlpacaError, MarketData
from .forensics import MOVERS
from .swing import run_portfolio

REPORTS = REPO_ROOT / "reports"
STATE = REPO_ROOT / "state"
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s",
                    stream=sys.stdout)
log = logging.getLogger("paper")

# The rule being forward tested. Fixed deliberately: this is the config that
# returned +14.6% where it was tuned and +14.5% on stocks it had never seen,
# with the volatility screen applied to both sides. Changing anything here
# restarts the forward test, so it is not a knob.
RULE = dict(BASE_BO)
RULE.update({"base_len": 10, "squeeze_atr": 4.0, "vol_mult": 1.0,
             "min_atr_pct": 0.0, "touch_window": 10})

SCREEN_ATR_PCT = 3.0      # universe screen: skip names quieter than this
DEFAULT_HALT_PCT = 25.0   # stop trading at this drawdown until reviewed


def settings() -> dict:
    """Paper-account settings from config.yaml, with defaults."""
    try:
        paper = dict(load_config().get("paper") or {})
    except Exception as exc:                      # config is optional here
        log.warning("Could not read config.yaml (%s); using defaults", exc)
        paper = {}
    return {"start": str(paper.get("start", "2026-09-29")),
            "equity": float(paper.get("equity", 2000.0)),
            "risk_pct": float(paper.get("risk_pct", 1.0)),
            "halt_drawdown_pct": float(paper.get("halt_drawdown_pct",
                                                 DEFAULT_HALT_PCT))}


def screened(data: dict, before: pd.Timestamp) -> dict:
    """Keep only names volatile enough, judged on history before the window."""
    keep = {s: d for s, d in data.items()
            if median_atr_pct(d, before) >= SCREEN_ATR_PCT}
    log.info("Screen >= %.1f%%: kept %d of %d", SCREEN_ATR_PCT,
             len(keep), len(data))
    return keep


def why(prepared: dict, symbol: str, entry_date: str, p: dict) -> str:
    """Plain-language reason this trade was taken.

    Read off the entry bar itself rather than written by hand, so it can never
    describe a setup other than the one the rule actually fired on. Every
    number here is a condition in `find_signals_bo`.
    """
    df = prepared.get(symbol)
    if df is None:
        return "—"
    rows = df.index[df.index.astype(str).str.startswith(entry_date)]
    if len(rows) == 0:
        return "—"
    bar = df.loc[rows[0]]
    a, close = float(bar["atr"]), float(bar["close"])
    bh, bl, bv = (float(bar["base_high"]), float(bar["base_low"]),
                  float(bar["base_vol"]))
    tight = (bh - bl) / a if a else 0.0
    rvol = float(bar["volume"]) / bv if bv else 0.0
    atr_pct = 100 * a / close if close else 0.0
    return (f"Coiled {p['base_len']} days inside ${bl:,.2f}–${bh:,.2f} "
            f"({tight:.1f}x ATR, tight), then closed above ${bh:,.2f} on "
            f"{rvol:.1f}x normal volume. Daily range {atr_pct:.1f}% — "
            "volatile enough to move.")


def pnl(t: dict, risk_pct: float) -> dict:
    """What the trade did, three ways: the stock's move, the account's, and R."""
    entry, ex = float(t["entry"]), float(t.get("exit") or 0.0)
    move = 100 * (ex - entry) / entry if entry and ex else 0.0
    return {"move_pct": round(move, 2),
            "account_pct": round(t["r_multiple"] * risk_pct, 2),
            "r": t["r_multiple"]}


def shares(entry: float, risk_per_share: float, equity: float,
           risk_pct: float) -> int:
    """Whole shares at the configured risk. Returns 0 when one share would
    already risk more than the budget - a real constraint on a small account,
    and one the backtest's fractional sizing hides."""
    if risk_per_share <= 0:
        return 0
    return int((equity * risk_pct / 100.0) // risk_per_share)


def score(argv=None) -> dict:
    cfg = settings()
    start = pd.Timestamp(cfg["start"], tz="America/New_York")
    fetch_from = (start - pd.Timedelta(days=500)).date().isoformat()

    md = MarketData(Credentials.from_env(), feed="iex")
    data = md.daily_bars(MOVERS, start=fetch_from)
    data = {s: d for s, d in data.items() if len(d) > 260}
    if not data:
        raise AlpacaError("no data returned")
    data = screened(data, start)

    p = dict(RULE)
    p["risk_pct"] = cfg["risk_pct"]
    prepared = prepare(data, p)
    result = run_portfolio(prepared, p, equity=cfg["equity"],
                           sigs=signal_times_bo(prepared, p), lo=start)

    st = result["stats"]
    closed = result["trades"]
    wins = sum(1 for t in closed if t["r_multiple"] > 0)
    last_bar = max((d.index[-1] for d in prepared.values()), default=None)

    for o in result["open"]:
        o["shares"] = shares(o["entry"], o["risk_per_share"], cfg["equity"],
                             cfg["risk_pct"])
        o["why"] = why(prepared, o["symbol"], o["entry_date"], p)
    for t in closed:
        t["why"] = why(prepared, t["symbol"], t["entry_date"], p)
        t["pnl"] = pnl(t, cfg["risk_pct"])
        t["target"] = round(t["entry"] + max(p["target_r"], 1.5)
                            * (t["entry"] - t["stop"]), 2)
        t["shares"] = shares(t["entry"], t["entry"] - t["stop"],
                             cfg["equity"], cfg["risk_pct"])

    dd = st.get("max_drawdown_pct", 0.0)
    return {"generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "as_of": str(last_bar.date()) if last_bar is not None else "—",
            "settings": cfg, "symbols": len(data),
            "trades": closed, "open": result["open"],
            "n": len(closed), "wins": wins, "losses": len(closed) - wins,
            "win_rate_pct": st.get("win_rate_pct", 0.0),
            "return_pct": st.get("return_pct", 0.0),
            "max_dd_pct": dd,
            "halted": dd <= -cfg["halt_drawdown_pct"]}


def render(r: dict) -> str:
    c = r["settings"]
    out = ["# Paper account", "",
           f"**Forward test since {c['start']} · bars through {r['as_of']} · "
           f"{r['symbols']} symbols · generated {r['generated']}**", "",
           "Not a backtest. These are the trades the rule would have taken "
           "since the day it was chosen, on bars it had never seen when the "
           "choice was made.", ""]

    if r["n"] == 0 and not r["open"]:
        out += ["**No trades yet.** Empty stretches are normal for this setup "
                "- it waits for a coil to break on volume, which does not "
                "happen every day. Nothing is wrong."]
        return "\n".join(out)

    out += ["| Trades | Won | Lost | Win % | Profit |",
            "|---|---|---|---|---|",
            f"| {r['n']} | {r['wins']} | {r['losses']} | "
            f"{r['win_rate_pct']}% | **{r['return_pct']:+.1f}%** |", ""]

    if r["n"] < 20:
        out += [f"> {r['n']} closed trade{'s' if r['n'] != 1 else ''} is too few to judge. The backtest "
                "needed 50 or more before its numbers stopped moving around. "
                "Read this as a record, not a verdict, until then.", ""]

    if r["halted"]:
        out += ["## STOPPED", "",
                f"Drawdown reached **{r['max_dd_pct']}%**, past the "
                f"{c['halt_drawdown_pct']}% line. No new entries are listed "
                "below. This is the agreed stop, not a suggestion — raising "
                "the line to keep trading is the one move that turns a bad "
                "month into a ruined account.", ""]
    else:
        room = c["halt_drawdown_pct"] + r["max_dd_pct"]
        out += [f"Worst drop so far **{r['max_dd_pct']}%**, against the "
                f"{c['halt_drawdown_pct']}% stop line — {room:.1f}% of room "
                "left.", ""]

    if r["open"] and not r["halted"]:
        out += ["## Open now", "",
                f"Sized at {c['risk_pct']:.0f}% of ${c['equity']:,.0f} risked "
                "per trade.", "",
                "| Symbol | Entered | Entry | Stop | Target | Shares | Best so far |",
                "|---|---|---|---|---|---|---|"]
        for o in r["open"]:
            sz = o["shares"] if o["shares"] else "— too small"
            trail = " (trailing)" if o["trailing"] else ""
            out.append(f"| **{o['symbol']}** | {o['entry_date']} | "
                       f"${o['entry']:.2f} | ${o['stop']:.2f}{trail} | "
                       f"${o['target']:.2f} | {sz} | {o['best_R']}R |")
        out.append("")
        for o in r["open"]:
            out.append(f"- **{o['symbol']}** — {o.get('why', '—')}")
        out.append("")
        if any(not o["shares"] for o in r["open"]):
            out += ["> A row marked *too small* means one share would risk "
                    f"more than {c['risk_pct']:.0f}% of the account. Skip it "
                    "rather than sizing up.", ""]

    if r["trades"]:
        out += ["## Closed", "",
                "| Symbol | In | Out | Entry | Exit | Stock | Account | "
                "Why it ended |",
                "|---|---|---|---|---|---|---|---|"]
        for t in reversed(r["trades"][-25:]):
            pl = t.get("pnl") or {}
            out.append(f"| {t['symbol']} | {t['entry_date']} | "
                       f"{t['exit_date']} | ${float(t.get('entry') or 0):,.2f} "
                       f"| ${float(t.get('exit') or 0):,.2f} | "
                       f"{pl.get('move_pct', 0):+.2f}% | "
                       f"**{pl.get('account_pct', 0):+.2f}%** | "
                       f"{_plain_reason(t['reason'])} |")
        if len(r["trades"]) > 25:
            out.append("")
            out.append(f"*Showing the last 25 of {len(r['trades'])}.*")
    return "\n".join(out)


def previous() -> dict:
    """Yesterday's scoring, so today's message can say what actually changed."""
    path = STATE / "paper.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("Could not read the previous run (%s)", exc)
        return {}


def _key(t: dict) -> tuple:
    return (t["symbol"], t["entry_date"], t.get("exit_date", ""))


def changes(now: dict, before: dict) -> tuple[list, list, bool]:
    """What is new since the last run: positions opened, trades closed, and
    whether the halt has just tripped."""
    opened = [o for o in now["open"]
              if _key(o) not in {_key(o2) for o2 in before.get("open", [])}]
    closed = [t for t in now["trades"]
              if _key(t) not in {_key(t2) for t2 in before.get("trades", [])}]
    return opened, closed, bool(now["halted"] and not before.get("halted"))


def alert(now: dict, before: dict) -> str | None:
    """The message to send, or None when nothing happened.

    Silence on quiet days is deliberate. A bot that pings every evening to say
    "no trades" gets muted within a week, and then the one message that matters
    goes unread too.
    """
    opened, closed, newly_halted = changes(now, before)
    if not (opened or closed or newly_halted):
        return None

    c = now["settings"]
    lines = [f"**TradingBot — {now['as_of']}**", ""]

    if newly_halted:
        lines += [f"🛑 **STOPPED — drawdown {now['max_dd_pct']}% passed the "
                  f"{c['halt_drawdown_pct']}% line.** No new entries until "
                  "this is reviewed.", ""]

    for t in closed:
        # Every field is read defensively: a message that raises would take
        # down the whole scoring run, and the record matters more than the ping.
        won = t["r_multiple"] > 0
        p = t.get("pnl") or {}
        size = t.get("shares") or 0
        entry, ex = float(t.get("entry") or 0), float(t.get("exit") or 0)
        cash = size * (ex - entry)
        lines += [f"{'🟢' if won else '🔴'} **CLOSED — {t['symbol']}** "
                  f"({'won' if won else 'lost'})",
                  f"Entered `${entry:,.2f}` on {t['entry_date']} · "
                  f"exited `${ex:,.2f}` on {t['exit_date']}",
                  f"Stop was `${t.get('stop', 0):,.2f}` · target was "
                  f"`${t.get('target', 0):,.2f}` · held "
                  f"{t.get('bars_held', 0)} days",
                  f"**P/L: {p.get('move_pct', 0):+.2f}% on the stock · "
                  f"{p.get('account_pct', 0):+.2f}% of the account** "
                  f"({p.get('r', 0):+.2f}R"
                  + (f", ${cash:+,.2f} on {size} share"
                     f"{'s' if size != 1 else ''}" if size else "")
                  + ")",
                  f"Ended on: {_plain_reason(t['reason'])}",
                  f"_Why it was taken: {t.get('why', '—')}_", ""]

    if opened and not now["halted"]:
        for o in opened:
            size = (f"{o['shares']} share{'s' if o['shares'] != 1 else ''}"
                    if o["shares"] else "**0 — too small for this account**")
            risk = o["shares"] * o["risk_per_share"]
            gain = o["shares"] * (o["target"] - o["entry"])
            lines += [f"🔵 **ENTRY — {o['symbol']}**",
                      f"Price `${o['entry']:,.2f}` on {o['entry_date']}",
                      f"Stop `${o['stop']:,.2f}` "
                      f"({100 * (o['entry'] - o['stop']) / o['entry']:.1f}% "
                      f"below) · target `${o['target']:,.2f}` "
                      f"(+{100 * (o['target'] - o['entry']) / o['entry']:.1f}%)",
                      f"Size {size}"
                      + (f" · risking `${risk:,.2f}` to make `${gain:,.2f}`"
                         if o["shares"] else ""),
                      f"**Why:** {o.get('why', '—')}", ""]

    lines += [f"Record so far: **{now['n']} trade"
              f"{'s' if now['n'] != 1 else ''}, {now['wins']} won, "
              f"{now['losses']} lost, {now['win_rate_pct']}% win, "
              f"{now['return_pct']:+.1f}%**"]
    if now["n"] < 20:
        lines.append("_Too few trades to mean anything yet._")
    lines.append("_Paper only. No orders are being placed._")
    return "\n".join(lines)


def _plain_reason(reason: str) -> str:
    return {"stop": "hit the stop loss",
            "trail": "trailing stop caught it after it had run",
            "target": "reached the target",
            "ema_exit": "closed below the moving average after being in profit",
            "time": "ran out of time and was closed at the close",
            }.get(reason, reason)


def log_events(now: dict, opened: list, closed: list) -> None:
    """Append every posted event to state/trade_log.jsonl, forever.

    state/paper.json is rewritten on each run because the ledger is derived.
    This file is the opposite: append-only, never rewritten, so there is a
    permanent record of what was posted and when - which is what makes it
    possible later to ask why the losers lost.
    """
    if not (opened or closed):
        return
    STATE.mkdir(exist_ok=True)
    path = STATE / "trade_log.jsonl"
    rows = ([{"event": "entry", "posted": now["as_of"], **o} for o in opened]
            + [{"event": "exit", "posted": now["as_of"], **t} for t in closed])
    with path.open("a", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, default=str) + "\n")
    log.info("Logged %d event(s) to %s", len(rows), path.name)


def notify(text: str) -> None:
    try:
        from .notify import Notifier
        Notifier(load_config(), Credentials.from_env()).send(
            text, subject="TradingBot — paper account")
    except Exception as exc:                      # never fail the run over this
        log.error("Could not send the alert: %s", exc)


def sample() -> str:
    """A worked example of the alert, built with invented numbers.

    It goes through `alert()` like any other day, so what lands in the channel
    is the real format rather than a hand-copied imitation of it. A mock-up
    written by hand would stop matching the code the first time the code
    changed, and then it would be teaching the wrong thing.
    """
    c = {"start": "2026-09-29", "equity": 2000.0, "risk_pct": 1.0,
         "halt_drawdown_pct": 25.0}
    win = {"symbol": "PLTR", "entry_date": "2026-09-30",
           "exit_date": "2026-10-06", "entry": 42.10, "stop": 38.90,
           "exit": 46.90, "r_multiple": 1.5, "reason": "target",
           "bars_held": 5, "target": 46.90, "shares": 6,
           "why": "Coiled 10 days inside $38.20–$41.60 (2.1x ATR, tight), "
                  "then closed above $41.60 on 1.8x normal volume. Daily "
                  "range 4.3% — volatile enough to move."}
    loss = {"symbol": "COIN", "entry_date": "2026-10-02",
            "exit_date": "2026-10-05", "entry": 310.50, "stop": 288.30,
            "exit": 288.30, "r_multiple": -1.0, "reason": "stop",
            "bars_held": 3, "target": 343.80, "shares": 0,
            "why": "Coiled 10 days inside $296.10–$308.90 (2.2x ATR, tight), "
                   "then closed above $308.90 on 1.4x normal volume. Daily "
                   "range 5.1% — volatile enough to move."}
    for t in (win, loss):
        t["pnl"] = pnl(t, c["risk_pct"])
    live = {"symbol": "NVDA", "entry_date": "2026-10-07", "entry": 182.40,
            "stop": 171.20, "risk_per_share": 11.20, "bars_held": 0,
            "best_R": 0.0, "target": 199.20, "trailing": False, "shares": 1,
            "why": "Coiled 10 days inside $168.40–$181.90 (2.4x ATR, tight), "
                   "then closed above $181.90 on 1.6x normal volume. Daily "
                   "range 3.6% — volatile enough to move."}
    now = {"as_of": "2026-10-07", "settings": c, "trades": [win, loss],
           "open": [live], "n": 2, "wins": 1, "losses": 1,
           "win_rate_pct": 50.0, "return_pct": 0.5, "max_dd_pct": -1.0,
           "halted": False}
    empty = {"as_of": "", "settings": c, "trades": [], "open": [], "n": 0,
             "wins": 0, "losses": 0, "win_rate_pct": 0.0, "return_pct": 0.0,
             "max_dd_pct": 0.0, "halted": False}
    banner = ("⚠️ **SAMPLE — NOT A REAL SIGNAL.** Invented numbers, sent once "
              "so you can see the format. ⚠️\n\n")
    return banner + alert(now, empty) + (
        "\n\n⚠️ **END OF SAMPLE.** The first real one comes after a day the "
        "rule actually fires. ⚠️")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="print the report instead of writing it")
    ap.add_argument("--no-notify", action="store_true",
                    help="score and write, but send nothing")
    ap.add_argument("--sample", action="store_true",
                    help="send one worked example of the alert and exit")
    args = ap.parse_args(argv)

    if args.sample:
        text = sample()
        print(text)
        if not args.dry_run:
            notify(text)
            log.info("Sample sent.")
        return 0

    before = previous()          # read before the write overwrites it
    try:
        r = score()
    except AlpacaError as exc:
        log.error("Data fetch failed: %s", exc)
        return 1

    text = render(r)
    message = alert(r, before)
    if args.dry_run:
        print(text)
        print("\n--- Discord message " + ("---\n" + message if message
                                          else "--- (nothing to send)"))
        return 0

    REPORTS.mkdir(exist_ok=True)
    STATE.mkdir(exist_ok=True)
    (REPORTS / "paper.md").write_text(text)
    (STATE / "paper.json").write_text(json.dumps(r, indent=2, default=str))
    log.info("%d closed, %d open, %+.1f%%, worst drop %.1f%%",
             r["n"], len(r["open"]), r["return_pct"], r["max_dd_pct"])
    if r["halted"]:
        log.error("HALTED at %.1f%% drawdown", r["max_dd_pct"])

    opened, closed, _ = changes(r, before)
    log_events(r, opened, closed)

    if message and not args.no_notify:
        notify(message)
        log.info("Alert sent.")
    elif not message:
        log.info("Nothing changed today — staying quiet.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
