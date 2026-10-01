"""Configuration loading and validation.

Everything tunable lives in config.yaml. This module loads it, applies
defaults, and exposes it as a dotted-access object so the rest of the code
reads like `cfg.strategy.retest.max_bars_after_break`.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import time
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = REPO_ROOT / "config.yaml"


class Section(dict):
    """A dict that also supports attribute access, recursively."""

    def __getattr__(self, item: str) -> Any:
        try:
            value = self[item]
        except KeyError as exc:  # pragma: no cover - defensive
            raise AttributeError(item) from exc
        return Section(value) if isinstance(value, dict) else value

    def __setattr__(self, key: str, value: Any) -> None:
        self[key] = value


def parse_hhmm(value: str) -> time:
    hours, minutes = value.split(":")
    return time(int(hours), int(minutes))


def load_config(path: str | os.PathLike | None = None) -> Section:
    path = Path(path) if path else DEFAULT_CONFIG_PATH
    with open(path, "r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}
    cfg = Section(raw)
    _validate(cfg)
    return cfg


def _validate(cfg: Section) -> None:
    required = ["universe", "strategy", "risk", "backtest", "notifications"]
    missing = [key for key in required if key not in cfg]
    if missing:
        raise ValueError(f"config.yaml is missing required sections: {missing}")

    tf = cfg.strategy.timeframe_minutes
    if 60 % tf and tf not in (5, 10, 15, 30):
        raise ValueError(f"timeframe_minutes={tf} is not a clean intraday interval")

    if cfg.risk.reward_multiple <= 0:
        raise ValueError("risk.reward_multiple must be > 0")
    if not 0 < cfg.risk.risk_per_trade_pct <= 10:
        raise ValueError("risk.risk_per_trade_pct must be between 0 and 10")

    orm = cfg.strategy.session.opening_range_minutes
    if orm % tf:
        raise ValueError(
            f"opening_range_minutes ({orm}) must be a multiple of "
            f"timeframe_minutes ({tf})"
        )


@dataclass(frozen=True)
class Credentials:
    """Secrets come from the environment, never from config.yaml."""

    alpaca_key: str = ""
    alpaca_secret: str = ""
    discord_webhook: str = ""
    # A second channel, for a strategy that is not the one in the main feed.
    # Keeping the feeds apart is the point: two rules with different evidence
    # behind them should not be read as one stream of signals.
    discord_webhook_inplay: str = ""
    telegram_token: str = ""
    telegram_chat_id: str = ""
    smtp_host: str = ""
    smtp_user: str = ""
    smtp_password: str = ""
    email_to: str = ""

    @classmethod
    def from_env(cls) -> "Credentials":
        # Either pair works for market data - Alpaca's paper keys read the
        # same bars as the live ones. Accepting both means a run does not die
        # with a bare 401 just because the secrets were set under the other
        # name, which is exactly what killed the first sweep.
        return cls(
            alpaca_key=(os.environ.get("ALPACA_API_KEY")
                        or os.environ.get("ALPACA_PAPER_KEY", "")),
            alpaca_secret=(os.environ.get("ALPACA_API_SECRET")
                           or os.environ.get("ALPACA_PAPER_SECRET", "")),
            discord_webhook=os.environ.get("DISCORD_WEBHOOK_URL", ""),
            discord_webhook_inplay=os.environ.get("DISCORD_WEBHOOK_INPLAY", ""),
            telegram_token=os.environ.get("TELEGRAM_BOT_TOKEN", ""),
            telegram_chat_id=os.environ.get("TELEGRAM_CHAT_ID", ""),
            smtp_host=os.environ.get("SMTP_HOST", ""),
            smtp_user=os.environ.get("SMTP_USER", ""),
            smtp_password=os.environ.get("SMTP_PASSWORD", ""),
            email_to=os.environ.get("EMAIL_TO", ""),
        )

    @property
    def has_alpaca(self) -> bool:
        return bool(self.alpaca_key and self.alpaca_secret)
