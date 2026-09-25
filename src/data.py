"""Market data access via the Alpaca Market Data API.

Only the REST endpoints are used, so there is no SDK dependency to keep in
sync — just `requests`. The free "iex" feed gives real intraday bars; a paid
Alpaca plan unlocks the consolidated "sip" feed, switchable in config.yaml.

Bars are returned as tz-aware US/Eastern DataFrames indexed by timestamp with
columns: open, high, low, close, volume.
"""
from __future__ import annotations

import time as _time
from datetime import date, datetime, timedelta
from typing import Iterable

import pandas as pd
import requests

from .config import Credentials

DATA_BASE = "https://data.alpaca.markets/v2"
EASTERN = "America/New_York"


class AlpacaError(RuntimeError):
    pass


class MarketData:
    def __init__(self, creds: Credentials, feed: str = "iex",
                 session: requests.Session | None = None):
        if not creds.has_alpaca:
            raise AlpacaError(
                "Missing ALPACA_API_KEY / ALPACA_API_SECRET. Add them as "
                "GitHub repository secrets (Settings -> Secrets and variables "
                "-> Actions) or export them locally."
            )
        self.feed = feed
        self.session = session or requests.Session()
        self.session.headers.update({
            "APCA-API-KEY-ID": creds.alpaca_key,
            "APCA-API-SECRET-KEY": creds.alpaca_secret,
            "accept": "application/json",
        })

    # -- low level ----------------------------------------------------------
    def _get(self, path: str, params: dict, retries: int = 4) -> dict:
        url = f"{DATA_BASE}{path}"
        delay = 1.0
        for attempt in range(retries):
            resp = self.session.get(url, params=params, timeout=30)
            if resp.status_code == 200:
                return resp.json()
            if resp.status_code in (429, 500, 502, 503, 504):
                _time.sleep(delay)
                delay *= 2
                continue
            raise AlpacaError(f"{resp.status_code} from {url}: {resp.text[:300]}")
        raise AlpacaError(f"Gave up on {url} after {retries} attempts")

    def _paged_bars(self, symbols: list[str], timeframe: str,
                    start: str, end: str | None, adjustment: str = "split"
                    ) -> dict[str, list[dict]]:
        out: dict[str, list[dict]] = {s: [] for s in symbols}
        page_token = None
        while True:
            params = {
                "symbols": ",".join(symbols),
                "timeframe": timeframe,
                "start": start,
                "limit": 10000,
                "adjustment": adjustment,
                "feed": self.feed,
                "sort": "asc",
            }
            if end:
                params["end"] = end
            if page_token:
                params["page_token"] = page_token
            payload = self._get("/stocks/bars", params)
            for sym, rows in (payload.get("bars") or {}).items():
                out.setdefault(sym, []).extend(rows)
            page_token = payload.get("next_page_token")
            if not page_token:
                break
        return out

    # -- public -------------------------------------------------------------
    def intraday_bars(self, symbols: Iterable[str], minutes: int,
                      start: str, end: str | None = None
                      ) -> dict[str, pd.DataFrame]:
        symbols = list(symbols)
        raw = self._paged_bars(symbols, f"{minutes}Min", start, end)
        return {sym: _to_frame(rows) for sym, rows in raw.items()}

    def daily_bars(self, symbols: Iterable[str], start: str,
                   end: str | None = None) -> dict[str, pd.DataFrame]:
        symbols = list(symbols)
        raw = self._paged_bars(symbols, "1Day", start, end)
        return {sym: _to_frame(rows, daily=True) for sym, rows in raw.items()}

    def snapshots(self, symbols: Iterable[str]) -> dict[str, dict]:
        symbols = list(symbols)
        chunks = [symbols[i:i + 100] for i in range(0, len(symbols), 100)]
        merged: dict[str, dict] = {}
        for chunk in chunks:
            payload = self._get("/stocks/snapshots",
                                {"symbols": ",".join(chunk), "feed": self.feed})
            merged.update(payload.get("snapshots") or payload)
        return merged

    def most_active(self, top: int = 20) -> list[str]:
        """Alpaca's screener — most active names by volume today."""
        url = "https://data.alpaca.markets/v1beta1/screener/stocks/most-actives"
        resp = self.session.get(url, params={"by": "volume", "top": top},
                                timeout=30)
        if resp.status_code != 200:
            return []
        return [row["symbol"] for row in resp.json().get("most_actives", [])]


def _to_frame(rows: list[dict], daily: bool = False) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    df = pd.DataFrame(rows)
    df = df.rename(columns={"t": "timestamp", "o": "open", "h": "high",
                            "l": "low", "c": "close", "v": "volume",
                            "n": "trades", "vw": "vwap_bar"})
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df = df.set_index("timestamp").sort_index()
    df.index = df.index.tz_convert(EASTERN)
    keep = ["open", "high", "low", "close", "volume"]
    df = df[[c for c in keep if c in df.columns]].astype(float)
    if not daily:
        # Regular trading hours only — the methodology is an opening-range play
        df = df.between_time("09:30", "15:59")
    return df


def trading_days_back(days: int) -> str:
    """ISO date roughly `days` trading days ago (calendar-padded)."""
    return (date.today() - timedelta(days=int(days * 1.5) + 5)).isoformat()


def session_fraction_elapsed(now: datetime) -> float:
    """How far through the 6.5-hour RTH session we are, 0..1."""
    open_min = 9 * 60 + 30
    close_min = 16 * 60
    cur = now.hour * 60 + now.minute
    return max(0.0, min(1.0, (cur - open_min) / (close_min - open_min)))
