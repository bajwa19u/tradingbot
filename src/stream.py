"""Live minute bars over Alpaca's websocket, for the live bot.

Polling found a closed bar up to a minute late and re-downloaded the day each
time. The stream pushes each one-minute bar within a second or two of its
close; the bot keeps the day in memory and runs the same rules the moment a
minute's bars are in.

The free plan allows one connection and 30 symbols, IEX only. The day-trade
watchlist is 10 names; anything past 30 is dropped with a warning rather than
risking the subscription being refused.

Pure parts (BarStore, MinuteTrigger) are tested; the connection itself is a
thin loop and falls back to REST polling whenever it is down.
"""
from __future__ import annotations

import json
import logging
import time as _time

import pandas as pd

from .data import _to_frame

log = logging.getLogger("stream")

URL = "wss://stream.data.alpaca.markets/v2/iex"
MAX_SYMBOLS = 30


class BarStore:
    """One-minute bars per symbol, seeded from REST, extended by the stream."""

    def __init__(self, seed: dict[str, pd.DataFrame]):
        self.frames = {s: df.copy() for s, df in seed.items()}
        self.last_bar: pd.Timestamp | None = None
        for df in self.frames.values():
            if len(df):
                self.last_bar = max(self.last_bar or df.index[-1], df.index[-1])

    def add(self, msg: dict) -> pd.Timestamp | None:
        """A bar ("b") or a late correction ("u"). Returns the bar's start time."""
        row = _to_frame([msg], extended=True)
        if row.empty:                       # outside 04:00-15:59, not used
            return None
        sym, ts = msg["S"], row.index[0]
        df = self.frames.get(sym)
        if df is None or df.empty:
            self.frames[sym] = row
        else:
            self.frames[sym] = pd.concat([df[df.index != ts], row]).sort_index()
        self.last_bar = max(self.last_bar or ts, ts)
        return ts

    def minute_frames(self) -> dict[str, pd.DataFrame]:
        return self.frames

    def five_minute_frames(self, today) -> dict[str, pd.DataFrame]:
        """Today's regular-session bars rolled up to 5 minutes, labelled by
        their start like Alpaca's own 5Min bars (09:30, 09:35, ...)."""
        out = {}
        for s, df in self.frames.items():
            d = df[df.index.date == today].between_time("09:30", "15:59")
            if d.empty:
                out[s] = d
                continue
            out[s] = d.resample("5min", label="left", closed="left").agg(
                {"open": "first", "high": "max", "low": "min", "close": "last",
                 "volume": "sum"}).dropna(subset=["open"])
        return out


class MinuteTrigger:
    """Decides when a minute's bars are in: every watched symbol has reported,
    or `settle` seconds have passed since the first one did (a thin IEX
    minute can have no trades and so no bar at all)."""

    def __init__(self, symbols, settle: float = 1.5):
        self.symbols, self.settle = set(symbols), settle
        self.minute: pd.Timestamp | None = None
        self.seen: set = set()
        self.first_at: float | None = None
        self.done: pd.Timestamp | None = None

    def arrive(self, sym: str, ts: pd.Timestamp | None, now: float) -> None:
        if ts is None or (self.done is not None and ts <= self.done):
            return                          # a correction to a minute already handled
        if self.minute is None or ts > self.minute:
            self.minute, self.seen, self.first_at = ts, set(), now
        if ts == self.minute:
            self.seen.add(sym)

    def due(self, now: float) -> bool:
        if self.minute is None or self.minute == self.done:
            return False
        return self.symbols <= self.seen or now - self.first_at >= self.settle

    def fired(self) -> None:
        self.done = self.minute


def connect(key: str, secret: str, symbols: list[str], timeout: float = 10.0):
    """Open, authenticate and subscribe to minute bars. Raises on failure."""
    import websocket                       # websocket-client
    syms = list(dict.fromkeys(symbols))
    if len(syms) > MAX_SYMBOLS:
        log.warning("Stream limited to %d symbols; dropping %s", MAX_SYMBOLS, syms[MAX_SYMBOLS:])
        syms = syms[:MAX_SYMBOLS]
    ws = websocket.create_connection(URL, timeout=timeout)
    _expect(ws, "connected")
    ws.send(json.dumps({"action": "auth", "key": key, "secret": secret}))
    _expect(ws, "authenticated")
    ws.send(json.dumps({"action": "subscribe", "bars": syms, "updatedBars": syms}))
    ws.settimeout(1.0)
    log.info("Streaming %d symbols", len(syms))
    return ws


def _expect(ws, what: str) -> None:
    for m in json.loads(ws.recv()):
        if m.get("T") == "error":
            raise ConnectionError(f"stream error {m.get('code')}: {m.get('msg')}")
        if m.get("T") == "success" and m.get("msg") == what:
            return
    raise ConnectionError(f"stream: expected {what}")


def read(ws) -> list[dict]:
    """Messages waiting on the socket, or [] after a one-second timeout.
    Raises ConnectionError when the stream reports an error or closes."""
    import websocket
    try:
        raw = ws.recv()
    except websocket.WebSocketTimeoutException:
        return []
    except (websocket.WebSocketConnectionClosedException, OSError) as exc:
        raise ConnectionError(f"stream closed: {exc}") from exc
    msgs = json.loads(raw) if raw else []
    for m in msgs:
        if m.get("T") == "error":
            raise ConnectionError(f"stream error {m.get('code')}: {m.get('msg')}")
    return [m for m in msgs if m.get("T") in ("b", "u")]


def now_s() -> float:
    return _time.time()
