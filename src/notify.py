"""Signal delivery: Discord, Telegram, email, or plain console.

Delivery never raises — a broken webhook must not take down the scan. Every
failure is logged and the run continues.
"""
from __future__ import annotations

import json
import logging
import smtplib
from email.message import EmailMessage

import requests

from .config import Credentials
from .strategy.break_retest import Signal

log = logging.getLogger(__name__)


def format_signal(sig: Signal, include_levels: bool = True) -> str:
    arrow = "LONG" if sig.direction == "long" else "SHORT"
    lines = [
        f"**{sig.symbol} — {arrow}**  ({sig.pattern.replace('_', ' ')})",
        f"Entry `{sig.entry:.2f}`  |  Stop `{sig.stop:.2f}`  |  "
        f"Target `{sig.target:.2f}` ({sig.r_label})",
        f"Risk `${sig.risk_per_share:.2f}`/share  ·  size `{sig.shares}` shares  "
        f"·  `${sig.dollar_risk:.2f}` at risk",
    ]
    if include_levels:
        lines.append(
            f"OR `{sig.opening_range_low:.2f}`–`{sig.opening_range_high:.2f}`  ·  "
            f"level `{sig.level:.2f}`  ·  VWAP `{sig.vwap:.2f}`  ·  "
            f"retest after {sig.bars_to_retest} bars"
        )
    lines.append(f"_{sig.timestamp:%Y-%m-%d %H:%M} ET · signal only, not an order_")
    if sig.notes:
        lines.append("⚠ " + "; ".join(sig.notes))
    return "\n".join(lines)


class Notifier:
    def __init__(self, cfg, creds: Credentials):
        self.cfg = cfg
        self.creds = creds
        self.channels = list(cfg.notifications.channels)

    def send(self, text: str, subject: str = "TradingBot signal") -> None:
        for channel in self.channels:
            try:
                getattr(self, f"_send_{channel}")(text, subject)
            except AttributeError:
                log.warning("Unknown notification channel: %s", channel)
            except Exception as exc:  # noqa: BLE001
                log.error("Notification via %s failed: %s", channel, exc)

    def send_signals(self, signals: list[Signal]) -> None:
        if not signals:
            return
        include = self.cfg.notifications.include_chart_levels
        body = "\n\n".join(format_signal(s, include) for s in signals)
        header = f"🎯 {len(signals)} break-and-retest setup" \
                 f"{'s' if len(signals) != 1 else ''}\n\n"
        self.send(header + body)

    # -- channels -----------------------------------------------------------
    def _send_console(self, text: str, subject: str) -> None:
        print(f"\n=== {subject} ===\n{text}\n")

    def _send_discord(self, text: str, subject: str) -> None:
        url = self.creds.discord_webhook
        if not url:
            log.warning("DISCORD_WEBHOOK_URL not set — skipping Discord")
            return
        for chunk in _chunk(text, 1900):
            resp = requests.post(url, json={"content": chunk}, timeout=20)
            if resp.status_code >= 300:
                raise RuntimeError(f"Discord {resp.status_code}: {resp.text[:200]}")

    def _send_telegram(self, text: str, subject: str) -> None:
        token, chat = self.creds.telegram_token, self.creds.telegram_chat_id
        if not (token and chat):
            log.warning("Telegram credentials not set — skipping")
            return
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        for chunk in _chunk(text, 3800):
            resp = requests.post(
                url, json={"chat_id": chat, "text": chunk,
                           "parse_mode": "Markdown"}, timeout=20)
            if resp.status_code >= 300:
                raise RuntimeError(f"Telegram {resp.status_code}: {resp.text[:200]}")

    def _send_email(self, text: str, subject: str) -> None:
        c = self.creds
        if not (c.smtp_host and c.smtp_user and c.smtp_password and c.email_to):
            log.warning("SMTP credentials not set — skipping email")
            return
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = c.smtp_user
        msg["To"] = c.email_to
        msg.set_content(text)
        with smtplib.SMTP_SSL(c.smtp_host, 465, timeout=30) as server:
            server.login(c.smtp_user, c.smtp_password)
            server.send_message(msg)


def _chunk(text: str, size: int) -> list[str]:
    if len(text) <= size:
        return [text]
    out, current = [], ""
    for line in text.split("\n"):
        if len(current) + len(line) + 1 > size:
            out.append(current)
            current = line
        else:
            current = f"{current}\n{line}" if current else line
    if current:
        out.append(current)
    return out
