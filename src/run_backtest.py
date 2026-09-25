"""Historical validation.

    python -m src.run_backtest
    python -m src.run_backtest --start 2024-01-01 --symbols AAPL,NVDA

Writes reports/backtest_<timestamp>.json plus a human-readable
reports/latest.md so results are reviewable straight from the repo.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date, datetime
from pathlib import Path

from .backtest import Backtester
from .config import REPO_ROOT, Credentials, load_config
from .data import MarketData

REPORTS = REPO_ROOT / "reports"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                    stream=sys.stdout)
log = logging.getLogger("backtest")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=None)
    parser.add_argument("--start", default=None)
    parser.add_argument("--end", default=None)
    parser.add_argument("--symbols", default=None, help="comma-separated override")
    args = parser.parse_args(argv)

    cfg = load_config(args.config)
    creds = Credentials.from_env()

    start = args.start or cfg.backtest.start
    end = args.end or cfg.backtest.end
    if args.symbols:
        symbols = [s.strip().upper() for s in args.symbols.split(",")]
    else:
        symbols = cfg.backtest.symbols or list(cfg.universe.watchlist)

    log.info("Backtesting %s from %s to %s", ", ".join(symbols), start, end or "now")

    from .data import AlpacaError
    try:
        md = MarketData(creds, feed=cfg.backtest.bar_feed)
        tf = cfg.strategy.timeframe_minutes
        intraday = md.intraday_bars(symbols, tf, start=start, end=end)
        daily = md.daily_bars(symbols, start=start, end=end)
    except AlpacaError as exc:
        log.error("Market data unavailable: %s", exc)
        return 1

    if not any(len(df) for df in intraday.values()):
        log.error(
            "Alpaca returned no intraday bars for %s between %s and %s. "
            "The free 'iex' feed has limited history — try a more recent "
            "start date, or switch backtest.bar_feed to 'sip' if your "
            "Alpaca plan includes it.",
            ", ".join(symbols), start, end or "today",
        )
        return 1

    for sym in symbols:
        n = len(intraday.get(sym, []))
        log.info("  %s: %d intraday bars", sym, n)
        if n == 0:
            log.warning("  %s returned no bars — check the feed setting "
                        "(free 'iex' has less history than 'sip')", sym)

    result = Backtester(cfg).run(intraday, daily)

    REPORTS.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = REPORTS / f"backtest_{stamp}.json"
    json_path.write_text(json.dumps(result, indent=2, default=str))

    md_text = render_markdown(result, symbols, start, end, cfg)
    (REPORTS / "latest.md").write_text(md_text)
    print("\n" + md_text)
    log.info("Wrote %s and reports/latest.md", json_path.name)
    return 0


def render_markdown(result: dict, symbols: list[str], start, end, cfg) -> str:
    s = result["stats"]
    lines = [
        "# Break-and-retest backtest",
        "",
        f"**Period:** {start} → {end or 'today'}  ",
        f"**Symbols:** {', '.join(symbols)}  ",
        f"**Timeframe:** {cfg.strategy.timeframe_minutes}-minute  ",
        f"**Target:** {cfg.risk.reward_multiple}R, risking "
        f"{cfg.risk.risk_per_trade_pct}% of ${cfg.risk.account_equity:,.0f}  ",
        f"**Generated:** {datetime.now():%Y-%m-%d %H:%M}",
        "",
    ]
    if s.get("n_trades", 0) == 0:
        lines += ["## No trades", "", s.get("note", ""), "",
                  "Rejection breakdown:", ""]
        for reason, count in sorted(result["stats"].get("rejection_reasons", {}).items(),
                                    key=lambda kv: -kv[1]):
            lines.append(f"- `{reason}` — {count}")
        return "\n".join(lines)

    lines += [
        "## Headline", "",
        "| Metric | Value |", "|---|---|",
        f"| Trades | {s['n_trades']} over {s['trading_days']} days "
        f"({s['trades_per_day']}/day) |",
        f"| Win rate | {s['win_rate_pct']}% |",
        f"| Expectancy | {s['expectancy_R']}R per trade |",
        f"| Total | {s['total_R']}R · ${s['total_pnl']:,.2f} ({s['return_pct']}%) |",
        f"| Profit factor | {s['profit_factor']} |",
        f"| Max drawdown | {s['max_drawdown_pct']}% |",
        f"| Avg win / avg loss | {s['avg_win_R']}R / {s['avg_loss_R']}R |",
        f"| Worst losing streak | {s['max_consecutive_losses']} |",
        f"| Avg hold | {s['avg_bars_held']} bars |",
        "",
        "## How trades ended", "",
    ]
    for reason, count in sorted(s["exit_reasons"].items(), key=lambda kv: -kv[1]):
        pct = 100 * count / s["n_trades"]
        lines.append(f"- **{reason}** — {count} ({pct:.0f}%)")

    lines += ["", "## Why setups were rejected", "",
              "_This is the filter doing its job — high counts here are healthy._", ""]
    for reason, count in sorted(s.get("rejection_reasons", {}).items(),
                                key=lambda kv: -kv[1])[:12]:
        lines.append(f"- `{reason}` — {count}")

    b = s.get("buckets", {})
    titles = {
        "by_hour": "By entry hour (ET)",
        "by_direction": "By direction",
        "by_pattern": "By confirmation pattern",
        "by_bars_to_retest": "By bars between break and retest",
        "by_symbol": "By symbol",
    }
    if b:
        lines += ["", "## Where the money actually goes", "",
                  "_Buckets with n < 20 are marked unreliable - slicing enough "
                  "ways always finds a flattering subset by chance._", ""]
        for key, title in titles.items():
            rows = b.get(key) or []
            if not rows:
                continue
            lines += [f"### {title}", "",
                      "| Bucket | n | Expectancy | Win rate | Total R | |",
                      "|---|---|---|---|---|---|"]
            for r in rows:
                flag = "" if r["reliable"] else "low n"
                lines.append(
                    f"| {r['bucket']} | {r['n']} | {r['expectancy_R']:+.3f}R | "
                    f"{r['win_rate_pct']}% | {r['total_R']:+.1f} | {flag} |")
            lines.append("")

    lines += ["", "## Last 15 trades", "",
              "| Symbol | Dir | Entry time | Entry | Exit | R | Exit reason |",
              "|---|---|---|---|---|---|---|"]
    for t in result["trades"][-15:]:
        lines.append(
            f"| {t['symbol']} | {t['direction']} | {t['entry_time'][:16]} | "
            f"{t['entry']:.2f} | {t['exit']:.2f} | {t['r_multiple']:+.2f} | "
            f"{t['exit_reason']} |"
        )
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
