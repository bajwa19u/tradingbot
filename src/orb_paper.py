"""ORB on stocks in play - a forward paper record. Observation only.

The 252-session study (reports/orb_research.md) ended with one candidate:
the five-minute opening range on the day's ten most in-play names, only when
that range is at least 0.35 of the stock's daily ATR, first completed
1-minute close outside it before 09:45, stop at the session extreme (moved to
entry at +1x risk), target
2x the risk, out at 15:55. It was flat on training dates, barely positive on
validation, and positive on the untouched test. That is not enough to post
it as a signal, so this records it instead: what it would have said, when we
saw it, and what happened, so the next decision rests on dates nobody chose.

It trades nothing and posts nothing. POST stays False (a test pins it) until
a forward record says otherwise. Every signal is found with the same
`first_signal` and settled with the same `exit_r` as the research, so the
paper record and the backtest cannot drift apart. After the bell each day the
full session is re-run through the research code and the row says whether
the live view and the backtest agreed.

Runs inside the in-play bot's polling loop (that job is already up from
09:20 to 16:05). It fetches its own bars and never touches the in-play
channel; a failure here is logged and ignored.
"""
from __future__ import annotations

import csv
import json
import logging
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd

from . import orb_research as orr
from .config import REPO_ROOT

log = logging.getLogger("orb_paper")

ENABLED = True       # record the candidate every session
POST = False         # never posts to Discord until a forward record supports it

# The research candidate (reports/orb_research.md) plus the two changes that
# passed on both date ranges in reports/orb_improve.md (3 Oct 2026): no entries
# after 09:44 - the 09:45-09:59 breaks lost on the earlier nine months - and
# the stop moves to the entry price once a trade is +1x its risk.
CANDIDATE = orr.P(universe="top10", orw=(0.35, 9e9), window_end=15, manage="be")
MAX_AGE_S = 120      # a signal first seen later than this after its bar closed is marked expired
BAR_LAG_S = 4        # Alpaca publishes a minute bar a few seconds after it closes
# 16:12, not 16:00: real costs come from consolidated (SIP) quotes, which the
# free plan serves 15 minutes late, and the bell exit is at 15:56.
SETTLE_AFTER = "16:12"
CHUNK, WORKERS = 15, 3     # history download: symbols per request, requests in flight

STATE_FILE = REPO_ROOT / "state" / "orb_paper.json"
LEDGER = REPO_ROOT / "reports" / "orb_paper.csv"
SUMMARY = REPO_ROOT / "reports" / "orb_paper.md"

COLUMNS = ["date", "symbol", "side", "bar", "seen_at", "latency_s", "expired", "source",
           "or_high", "or_low", "level", "entry", "stop", "target", "risk_pct",
           "rvol5", "or_width_atr", "displacement", "breakout_rvol", "extension", "gap_pct",
           "vwap_ok", "spy_ok", "qqq_ok", "same_side_10m", "exit_bar", "exit_reason",
           "result_pct", "win", "backtest_agrees", "entry_cost_pct", "exit_cost_pct", "result_real_pct"]


def bar_label(k: int) -> str:
    m = 570 + k
    return f"{m // 60:02d}:{m % 60:02d}"


class Feed:
    """One trading day's observation. `md` is anything with Alpaca's
    `intraday_bars(symbols, minutes, start, end=None)`."""

    def __init__(self, md, p: orr.P = CANDIDATE):
        self.md, self.p = md, p
        self.hist: dict[str, dict] = {}       # symbol -> {date: 5x390 array}, sessions before today
        self.hist_for = None
        self.newest: pd.Timestamp | None = None   # start time of the newest bar fetched today
        self.quotes_md = None                     # SIP client for real costs at settle time (optional)

    # ------------------------------------------------------------------ data
    def history(self, today, symbols) -> None:
        """Prior sessions for `symbols`, fetched once a day (before the bell when possible)."""
        if self.hist_for != today:
            self.hist, self.hist_for = {}, today
        need = [s for s in symbols if s not in self.hist]
        if not need:
            return
        start = (pd.Timestamp(today) - pd.Timedelta(days=int((orr.LOOKBACK + 6) * 1.6))).date()
        chunks = [need[i:i + CHUNK] for i in range(0, len(need), CHUNK)]

        def fetch(chunk):
            return chunk, self.md.intraday_bars(chunk, 1, start=start.isoformat(), end=str(today))

        # A few chunks at once: the warm-up is ~90 paged requests, and done one
        # after another it took most of a minute. Three workers stay inside
        # Alpaca's 200-a-minute limit; the client retries a 429 anyway.
        with ThreadPoolExecutor(max_workers=min(WORKERS, len(chunks))) as pool:
            for chunk, got in pool.map(fetch, chunks):
                for s in chunk:
                    df = got.get(s)
                    days = orr.to_days(df) if df is not None and len(df) else {}
                    self.hist[s] = {d: a for d, a in days.items() if d < today}

    def today_days(self, symbols, now: pd.Timestamp, k_end: int) -> dict:
        """{symbol: Day} for today, built only from bars that have closed."""
        today = now.date()
        got = self.md.intraday_bars(list(symbols), 1, start=str(today))
        open_ts = now.normalize() + pd.Timedelta(hours=9, minutes=30)
        stamps = [df.index[-1].tz_convert(orr.EASTERN) for df in got.values() if df is not None and len(df)]
        self.newest = max(stamps) if stamps else None
        out = {}
        for s in symbols:
            df = got.get(s)
            prior = self.hist.get(s, {})
            if df is None or df.empty or len(prior) < orr.LOOKBACK + 1:
                continue
            idx = df.index.tz_convert(orr.EASTERN)
            df = df[(idx >= open_ts) & (idx < open_ts + pd.Timedelta(minutes=k_end))]
            arr = orr.to_days(df, min_bars=1).get(today)
            if arr is None:
                continue
            days = {**prior, today: arr}
            ds = sorted(days)
            out[s] = orr.make_day(days, ds, len(ds) - 1, orr._true_ranges(days, ds))
        return out

    # ------------------------------------------------------------------ the rule
    def scan(self, state: dict, now: pd.Timestamp) -> list[dict]:
        """New signals since the last call. Picks are fixed at 09:35 and kept."""
        open_ts = now.normalize() + pd.Timedelta(hours=9, minutes=30)
        k_end = int((now - open_ts - pd.Timedelta(seconds=BAR_LAG_S)).total_seconds() // 60)
        if k_end < 5 or k_end > self.p.window_end + 10:   # keep looking a while so late sightings are logged (as expired)
            return []
        today = now.date()
        k_end = min(k_end, self.p.window_end)
        if not state["picks"]:
            self.history(today, orr.POOL)
            D = self.today_days(orr.POOL, now, k_end)
            state["picks"] = orr.select({s: {today: x} for s, x in D.items()}, today, self.p.universe)
            state["picked_at"] = now.strftime("%H:%M:%S")
            log.info("ORB paper picks: %s", state["picks"])
        else:
            self.history(today, state["picks"] + ["SPY", "QQQ"])
            D = self.today_days(state["picks"] + ["SPY", "QQQ"], now, k_end)
        if "SPY" not in D or "QQQ" not in D:
            return []
        sa, qa = D["SPY"].c > D["SPY"].vwap, D["QQQ"].c > D["QQQ"].vwap
        done = {r["symbol"] for r in state["signals"]}
        new = []
        for s in state["picks"]:
            if s in done or s not in D:
                continue
            sig = orr.first_signal(D[s], sa, qa, self.p, k_end, D["SPY"])
            if sig is None:
                continue
            close = open_ts + pd.Timedelta(minutes=sig["k"] + 1)
            age = (now - close).total_seconds()
            new.append(row(s, D[s], sig, today, source="live",
                           seen_at=now.strftime("%H:%M:%S"), latency=age))
        for r in new:
            r["same_side_10m"] = sum(1 for q in state["signals"] + new if q["side"] == r["side"]
                                     and r["k"] - 10 <= q["k"] < r["k"])
        state["signals"] += new
        return new

    def settle(self, state: dict, now: pd.Timestamp) -> list[dict]:
        """After the bell: outcomes for every live signal, plus the backtest's
        own view of the day so a missed or different signal is visible."""
        today = now.date()
        if not state["picks"]:                # started too late to watch: pick from the full day
            self.history(today, orr.POOL)
            D = self.today_days(orr.POOL, now, orr.N_MIN)
            state["picks"] = orr.select({s: {today: x} for s, x in D.items()}, today, self.p.universe)
        syms = state["picks"] + ["SPY", "QQQ"]
        self.history(today, syms)
        D = self.today_days(syms, now, orr.N_MIN)
        if "SPY" not in D or "QQQ" not in D:
            return []
        sa, qa = D["SPY"].c > D["SPY"].vwap, D["QQQ"].c > D["QQQ"].vwap
        live = {r["symbol"]: r for r in state["signals"]}
        out = []
        for s in state["picks"]:
            x = D.get(s)
            bt = orr.first_signal(x, sa, qa, self.p, orr.FLAT_IDX - 1, D["SPY"]) if x is not None else None
            r = live.get(s)
            if r is None and bt is None:
                continue
            if r is None:                     # the backtest sees a signal the live feed never did
                r = row(s, x, bt, today, source="backtest only", seen_at="", latency=None)
            if x is not None:
                sign = 1 if r["side"] == "long" else -1
                R, j, why = orr.exit_r(x, r["k"], sign, r["entry"], r["stop"], self.p)
                r.update(exit_bar=bar_label(j), exit_reason=why,
                         result_pct=float(round(float(R) * abs(r["entry"] - r["stop"]) / r["entry"] * 100, 3)),
                         win=bool(R > 0))
            if x is not None and self.quotes_md is not None and r.get("exit_reason"):
                self.real_costs(r, x, now)
            r["backtest_agrees"] = ("missed live" if r["source"] == "backtest only" else
                                    "no signal" if bt is None else
                                    "yes" if (bt["k"], bt["side"]) == (r["k"], r["side"]) else
                                    f"differs ({bt['side']} at {bar_label(bt['k'])})")
            out.append(r)
        state["settled"] = True
        return out


    def real_costs(self, r: dict, x, now: pd.Timestamp) -> None:
        """What the trade would really have cost: the NBBO a couple of seconds
        after it was SEEN (not after its bar closed), and at the exit. Same
        definitions as src/orb_checks.py; a missing quote leaves the fields empty."""
        from . import orb_checks as oc
        sgn = 1 if r["side"] == "long" else -1
        open_ts = now.normalize() + pd.Timedelta(hours=9, minutes=30)
        try:
            seen = (pd.Timestamp(f"{now.date()} {r['seen_at']}", tz=orr.EASTERN) if r.get("seen_at")
                    else open_ts + pd.Timedelta(minutes=r["k"] + 1, seconds=4))
            c = float(x.c[r["k"]])
            q = oc.nbbo_at(self.quotes_md, r["symbol"], seen, (2, 15))
            ce = sgn * ((q[1] if sgn > 0 else q[0]) - c) / c if q else None
            j = int(r["exit_bar"][:2]) * 60 + int(r["exit_bar"][3:]) - 570      # exit minute index
            if r["exit_reason"] == "target":
                cx = 0.0
            elif r["exit_reason"] == "bell":
                q = oc.nbbo_at(self.quotes_md, r["symbol"], open_ts + pd.Timedelta(minutes=j + 1))
                cj = float(x.c[j])
                cx = sgn * (cj - (q[0] if sgn > 0 else q[1])) / cj if q else None
            else:
                q = oc.nbbo_at(self.quotes_md, r["symbol"], open_ts + pd.Timedelta(minutes=j), (0, 60))
                cx = (q[1] - q[0]) / (q[0] + q[1]) if q else None
        except Exception as exc:                                   # noqa: BLE001
            log.warning("ORB paper: no quotes for %s (%s)", r["symbol"], exc)
            return
        if ce is not None and abs(ce) > oc.MAX_GAP:
            ce = None
        r["entry_cost_pct"] = None if ce is None else round(ce * 100, 3)
        r["exit_cost_pct"] = None if cx is None else round(cx * 100, 3)
        if ce is not None and cx is not None and r.get("result_pct") is not None:
            # result_pct already paid 0.05% a side; swap that for what was measured
            r["result_real_pct"] = round(r["result_pct"] + 2 * self.p.slip * 100 - (ce + cx) * 100, 3)


def row(sym: str, x, sig: dict, today, source: str, seen_at: str, latency) -> dict:
    r = dict(
        date=str(today), symbol=sym, side=sig["side"], k=sig["k"], bar=bar_label(sig["k"]),
        seen_at=seen_at, latency_s=None if latency is None else round(latency, 1),
        expired=None if latency is None else bool(latency > MAX_AGE_S), source=source,
        or_high=round(x.or_h, 4), or_low=round(x.or_l, 4), level=round(sig["level"], 4),
        entry=round(sig["entry"], 4), stop=round(sig["stop"], 4), target=round(sig["target"], 4),
        risk_pct=round(abs(sig["entry"] - sig["stop"]) / sig["entry"] * 100, 3),
        rvol5=round(x.rvol5, 2), or_width_atr=round(sig["orw"], 3), displacement=round(sig["disp"], 3),
        breakout_rvol=round(sig["bvol"], 2), extension=round(sig["ext"], 3),
        gap_pct=round(x.gap * 100, 2) if x.gap == x.gap else None,
        vwap_ok=bool(sig["vwap_ok"]), spy_ok=bool(sig["spy_ok"]), qqq_ok=bool(sig["qqq_ok"]), same_side_10m=0)
    return {k: (v.item() if isinstance(v, np.generic) else v) for k, v in r.items()}


# ---------------------------------------------------------------------- files
def load_state(date: str) -> dict:
    blank = {"date": date, "picks": [], "picked_at": "", "signals": [], "settled": False}
    try:
        s = json.loads(STATE_FILE.read_text())
    except (OSError, json.JSONDecodeError):
        return blank
    return {**blank, **s} if s.get("date") == date else blank


def save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=1, default=str))


def append_ledger(rows: list[dict]) -> None:
    LEDGER.parent.mkdir(exist_ok=True)
    new = not LEDGER.exists()
    with LEDGER.open("a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
        if new:
            w.writeheader()
        w.writerows(rows)


def summary_text(df: pd.DataFrame) -> str:
    """Win %, profit % and winners vs losers - never R (house rule)."""
    L = ["# ORB on stocks in play - forward paper record", "",
         "Observation only: nothing is posted or traded. Rule: the 10 names with the most abnormal "
         "first-five-minute volume, range at least 0.35 of daily ATR, first 1-minute close outside "
         "the 09:30-09:34 range before 09:45, stop at the session extreme (moved to entry once +1x risk), target 2x the risk, out at 15:55. "
         "Results are the stock's move from entry to exit after 0.05% slippage each way.", ""]
    df = df[df.result_pct.notna()] if len(df) else df
    if not len(df):
        return "\n".join(L + ["No settled signals yet."]) + "\n"
    live = df[df.source == "live"]

    def line(name, g):
        if not len(g):
            return f"| {name} | 0 | | | | | |"
        w = g.result_pct > 0
        return (f"| {name} | {len(g)} | {100 * w.mean():.0f}% | {int(w.sum())} / {int((~w).sum())} | "
                f"{g.result_pct.mean():+.2f}% | {g.result_pct[w].mean() if w.any() else 0:+.2f}% / "
                f"{g.result_pct[~w].mean() if (~w).any() else 0:+.2f}% | {g.result_pct.sum():+.1f}% |")

    L += [f"{df.date.nunique()} sessions, {df.date.min()} to {df.date.max()}.", "",
          "| signals | count | win % | winners / losers | avg per trade | avg winner / loser | total |",
          "|---|---|---|---|---|---|---|",
          line("all (backtest view of each day)", df),
          line("seen live in time", live[live.expired == False]),          # noqa: E712
          line("seen live but late (expired)", live[live.expired == True]),  # noqa: E712
          line("long", df[df.side == "long"]), line("short", df[df.side == "short"]), ""]
    if "result_real_pct" in df and df.result_real_pct.notna().any():
        q = df[df.result_real_pct.notna()]
        L += [f"With real quotes (the NBBO seconds after each signal was seen, and at the exit): "
              f"{q.result_real_pct.mean():+.2f}% per trade over {len(q)} trades, against "
              f"{q.result_pct.mean():+.2f}% at the assumed 0.05% a side. Median entry cost "
              f"{q.entry_cost_pct.median():.3f}%, exit {q.exit_cost_pct.median():.3f}%.", ""]
    if len(live):
        agree = (live.backtest_agrees == "yes").mean() * 100
        L += [f"Live and backtest agreed on {agree:.0f}% of live signals; "
              f"{(df.source == 'backtest only').sum()} backtest signals were never seen live. "
              f"Median latency {live.latency_s.median():.0f}s after the bar closed.", ""]
    L += ["## Last 10", "", "| date | stock | side | bar | seen | result | exit |", "|---|---|---|---|---|---|---|"]
    for _, r in df.tail(10).iterrows():
        L.append(f"| {r.date} | {r.symbol} | {r.side} | {r.bar} | {r.seen_at or '-'} | {r.result_pct:+.2f}% | {r.exit_reason} {r.exit_bar} |")
    return "\n".join(L) + "\n"


# ---------------------------------------------------------------------- entry point
_FEED: Feed | None = None


def _sip():
    from .config import Credentials
    from .data import MarketData
    return MarketData(Credentials.from_env(), feed="sip")


def tick(now: pd.Timestamp, md_factory, dry_run: bool = False, quotes_factory=_sip) -> None:
    """Called every loop of the in-play bot. Cheap when there is nothing to do."""
    global _FEED
    if not ENABLED or now.weekday() > 4:
        return
    if _FEED is None:
        _FEED = Feed(md_factory())
    state = load_state(str(now.date()))
    t = now.time()
    if t < pd.Timestamp("09:35").time():
        _FEED.history(now.date(), orr.POOL)              # warm up before the bell
        return
    if state["settled"]:
        return
    if t >= pd.Timestamp(SETTLE_AFTER).time():
        if _FEED.quotes_md is None and quotes_factory is not None:
            try:
                _FEED.quotes_md = quotes_factory()
            except Exception as exc:                               # noqa: BLE001
                log.warning("ORB paper: no quote client (%s) - costs not measured", exc)
        rows = _FEED.settle(state, now)
        if not dry_run:
            if rows:
                append_ledger(rows)
            save_state(state)
            SUMMARY.parent.mkdir(exist_ok=True)
            SUMMARY.write_text(summary_text(pd.read_csv(LEDGER) if LEDGER.exists() else pd.DataFrame()))
        log.info("ORB paper settled %d signal(s)", len(rows))
        return
    before = (len(state["picks"]), len(state["signals"]))
    new = _FEED.scan(state, now)
    for r in new:
        log.info("ORB paper: %s %s %s at %s, seen %ss after the close%s", r["symbol"], r["side"],
                 r["entry"], r["bar"], r["latency_s"], " (expired)" if r["expired"] else "")
    if not dry_run and (len(state["picks"]), len(state["signals"])) != before:
        save_state(state)


def why_not(feed: Feed, day, sym: str, now: pd.Timestamp) -> str:
    """Plain-English account of one symbol on one day under the live rule:
    was it picked, did its range qualify, did it break, and when."""
    open_ts = now.normalize() + pd.Timedelta(hours=9, minutes=30)
    k_end = int(min(orr.N_MIN, max(6, (now - open_ts).total_seconds() // 60)))
    feed.history(day, orr.POOL)
    D = feed.today_days(orr.POOL, now, k_end)
    p, L = feed.p, [f"{sym} on {day} under the day-trade rule (bars through minute {k_end}):"]
    if sym not in orr.POOL:
        return L[0] + f"\n- {sym} is not in the ~105-stock list the rule chooses from."
    ranked = sorted(((x.rvol5, s) for s, x in D.items() if s not in ("SPY", "QQQ") and x.rvol5 == x.rvol5
                     and x.prev_c >= 5 and x.adv >= 5e7), reverse=True)
    picks = orr.select({s: {day: x} for s, x in D.items()}, day, p.universe)
    x = D.get(sym)
    if x is None:
        return L[0] + "\n- No usable data for it that day."
    pos = next((i + 1 for i, (_, s) in enumerate(ranked) if s == sym), None)
    L.append(f"- Opening volume {x.rvol5:.2f}x its normal: rank {pos} of {len(ranked)}. "
             + ("PICKED (top 10)." if sym in picks else f"NOT picked: the 10th pick was at {ranked[9][0]:.2f}x."))
    ratio = x.or_w / x.atr if x.atr else 0
    L.append(f"- Opening range 09:30-09:34: {x.or_l:.2f} - {x.or_h:.2f}, {ratio:.2f} of its daily ATR "
             + ("(wide enough)." if ratio >= p.orw[0] else f"(too narrow; needs {p.orw[0]})."))
    first = next((k for k in range(5, k_end) if x.c[k] > x.or_h or x.c[k] < x.or_l), None)
    if first is None:
        L.append("- Never closed outside its opening range.")
    else:
        side = "above" if x.c[first] > x.or_h else "below"
        L.append(f"- First 1-minute close {side} the range: {bar_label(first)} at {x.c[first]:.2f}"
                 + (" (inside the 09:35-09:44 entry window)." if first < p.window_end else " (after the 09:44 entry cutoff)."))
    prev = sorted(feed.hist.get(sym, {}))
    if prev:
        pdh, pdl = float(feed.hist[sym][prev[-1]][1].max()), float(feed.hist[sym][prev[-1]][2].min())
        up = next((k for k in range(0, k_end) if x.c[k] > pdh), None)
        L.append(f"- Previous day high {pdh:.2f}, low {pdl:.2f}. "
                 + (f"First close above the previous high: {bar_label(up)} at {x.c[up]:.2f} (not a setup this rule trades)." if up is not None
                    else "Never closed above the previous high."))
    return "\n".join(L)


def main(argv=None) -> int:
    """`python -m src.orb_paper --check [--date YYYY-MM-DD]`: settle one past
    session from scratch and print it, writing nothing. Proves the data path."""
    import argparse
    from .config import Credentials
    from .data import MarketData
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--date", default="")
    ap.add_argument("--why", default="", help="explain why this symbol was or wasn't traded that day")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    day = pd.Timestamp(args.date or pd.Timestamp.now(tz=orr.EASTERN).date()).date()
    now = pd.Timestamp(f"{day} 16:01", tz=orr.EASTERN)
    feed = Feed(MarketData(Credentials.from_env(), feed="iex"))
    if args.why:
        print(why_not(feed, day, args.why.upper(), min(now, pd.Timestamp.now(tz=orr.EASTERN) - pd.Timedelta(minutes=1))))
        return 0
    state = {"date": str(day), "picks": [], "picked_at": "", "signals": [], "settled": False}
    rows = feed.settle(state, now)
    print(f"{day}: picks {state['picks']}")
    for r in rows:
        print({k: r.get(k) for k in ("symbol", "side", "bar", "entry", "stop", "target", "or_width_atr",
                                     "exit_reason", "exit_bar", "result_pct", "backtest_agrees")})
    print(summary_text(pd.DataFrame(rows)) if rows else "no signals")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
