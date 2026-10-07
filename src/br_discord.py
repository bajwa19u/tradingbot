"""Break & Retest V1: the Discord card, with its chart attached.

Posts to its own webhook (secret `DISCORD_BR_WEBHOOK_URL`), never the live
bot's channel. No webhook set = nothing is sent; the card is still written to
the log so a dry run shows exactly what would have gone out.

The card follows the V1 spec, which asks for the dollar risk on it. That
differs from the older house rule for the live bot's cards (no dollar signs,
no share counts); share counts are still left off.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import requests

log = logging.getLogger(__name__)
TIMEOUT = 15
NAMES = {"pdh": "PDH", "pdl": "PDL", "pdc": "PDC", "pmh": "PMH", "pml": "PML",
         "swing_high": "Swing high", "swing_low": "Swing low"}


def card(sig: dict) -> str:
    """sig: the flat signal record built by the backtest/live runner."""
    long = sig["direction"] == "long"
    head = "🟢 BREAK & RETEST LONG" if long else "🔴 BREAK & RETEST SHORT"
    t = sig["signal_ts"]
    when = f"{t:%-I:%M %p} ET" if hasattr(t, "strftime") else str(t)
    conf = "Bullish close" if long else "Bearish close"
    lvl = NAMES.get(sig["level_kind"], sig["level_kind"])
    lines = [
        head,
        f"**{sig['symbol']}**",
        f"Time: {when}",
        f"Level: ${sig['level']:.2f} {lvl}" + (f" ({sig['tf']}m)" if sig.get("tf") else ""),
        "Break: Confirmed",
        "Retest: Confirmed",
        f"Confirmation: {conf}",
        f"Entry: ${sig['entry']:.2f}",
        f"Stop: ${sig['stop']:.2f}",
        f"Target: ${sig['target']:.2f}",
        f"R:R: {sig['target_r']:.1f}",
        f"Risk: ${sig['risk_dollars']:,.0f}",
        f"Market Bias: {sig['market_bias']}",
        f"SPY: {sig['spy_bias']}",
        f"QQQ: {sig['qqq_bias']}",
        f"VWAP: {sig['vwap_side']}",
        f"Confidence: {sig['confidence']}",
    ]
    if sig.get("notes"):
        lines.append("⚠ " + "; ".join(sig["notes"]))
    return "\n".join(lines)


def result_line(sig: dict, outcome: str, r: float) -> str:
    word = {"target": "2R target reached", "stop": "stopped out", "time": "closed at time exit"}.get(outcome, outcome)
    side = "LONG" if sig["direction"] == "long" else "SHORT"
    return f"{sig['symbol']} {side} @ {sig['entry']:.2f} — {word} ({r:+.2f}R)"


def post(url: str | None, text: str, image: str | Path | None = None) -> str | None:
    """Send; return the message id, or None if it did not go out."""
    if not url:
        log.info("[no BR webhook — not sent]\n%s", text)
        return None
    try:
        if image and Path(image).exists():
            with open(image, "rb") as fh:
                resp = requests.post(url, params={"wait": "true"},
                                     data={"payload_json": json.dumps({"content": text[:1900]})},
                                     files={"files[0]": (Path(image).name, fh, "image/png")},
                                     timeout=TIMEOUT)
        else:
            resp = requests.post(url, params={"wait": "true"}, json={"content": text[:1900]},
                                 timeout=TIMEOUT)
        if resp.status_code >= 300:
            log.error("Discord %s: %s", resp.status_code, resp.text[:200])
            return None
        return str(resp.json().get("id") or "") or None
    except Exception as exc:                                   # noqa: BLE001
        log.error("Discord post failed: %s", exc)
        return None
