"""Live scan — run this on a schedule during market hours.

Each run replays the day's bars from the open through the same engine the
backtest uses, so the logic can never drift between them. Signals already
alerted on are tracked in state/sent.json so a symbol is never fired twice.

    python -m src.run_live
    python -m src.run_live --dry-run      # print, don't notify
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, date
from pathlib import Path
from zoneinfo import ZoneInfo

from .backtest import _parse_time
from .config import Credentials, REPO_ROOT, load_config
from .data import MarketData, trading_days_back
from .notify import Notifier
from .strategy import make_engine
from .strategy.break_retest import compute_daily_atr
from .universe import build_universe

EASTERN = ZoneInfo("America/New_York")
STATE_DIR = REPO_ROOT / "state"
STATE_FILE = STATE_DIR / "sent.json"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("run_live")


def load_state(today: str) -> dict:
    if STATE_FILE.exists():
        try:
            state = json.loads(STATE_FILE.read_text())
            if state.get("date") == today:
                return state
        except json.JSONDecodeError:
            pass
    return {"date": today, "sent": []}


def save_state(state: dict) -> None:
    STATE_DIR.mkdir(exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--config", default=None)
    args = parser.parse_args(argv)

    cfg = load_config(args.config)
    creds = Credentials.from_env()
    now = datetime.now(EASTERN)
    today = now.date().isoformat()

    open_t = _parse_time(cfg.strategy.session.market_open)
    close_t = _parse_time(cfg.strategy.session.market_close)
    if now.weekday() >= 5:
        log.info("Weekend — nothing to do.")
        return 0
    if not (open_t <= now.time() <= close_t):
        log.info("Outside regular trading hours (%s ET) — nothing to do.",
                 now.strftime("%H:%M"))
        return 0

    md = MarketData(creds, feed=cfg.backtest.bar_feed)
    notifier = Notifier(cfg, creds)
    state = load_state(today)
    already_sent = set(state["sent"])

    symbols, candidates = build_universe(md, cfg, now)
    log.info("Scanning %d symbols: %s", len(symbols), ", ".join(symbols))
    for c in candidates:
        if not c.passed:
            log.debug("  skipped %s — %s", c.symbol, c.reason)

    if not symbols:
        log.info("No symbols passed the universe filters today.")
        return 0

    tf = cfg.strategy.timeframe_minutes
    intraday = md.intraday_bars(symbols, tf, start=today)
    daily = md.daily_bars(symbols, start=trading_days_back(40))

    fresh_signals = []
    for sym in symbols:
        bars = intraday.get(sym)
        if bars is None or len(bars) < 4:
            continue
        bars = bars[bars.index.date == now.date()]
        hist = daily.get(sym)
        prior = hist[hist.index.date < now.date()] if hist is not None and len(hist) else None
        a = compute_daily_atr(prior) if prior is not None else 0.0

        engine = make_engine(cfg, sym, a)
        for ts, bar in bars.iterrows():
            signal = engine.on_bar(bar)
            if signal is None:
                continue
            key = f"{sym}:{signal.timestamp.isoformat()}"
            if key in already_sent:
                continue
            fresh_signals.append(signal)
            already_sent.add(key)

    if not fresh_signals:
        log.info("No new setups. (%d symbols evaluated)", len(symbols))
        return 0

    log.info("%d new signal(s)", len(fresh_signals))
    for sig in fresh_signals:
        log.info("  %s %s entry=%.2f stop=%.2f target=%.2f (%s)",
                 sig.symbol, sig.direction, sig.entry, sig.stop,
                 sig.target, sig.pattern)

    if args.dry_run:
        from .notify import format_signal
        for sig in fresh_signals:
            print(format_signal(sig))
        return 0

    notifier.send_signals(fresh_signals)
    state["sent"] = sorted(already_sent)
    save_state(state)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
