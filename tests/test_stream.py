"""The websocket path: bars land in memory, a minute fires once, and the scans
read from memory instead of the network."""
from __future__ import annotations

import pandas as pd

from src import live_bot as lb
from src import stream as st

ET = "America/New_York"


def bar(sym, t_utc, c=100.0, v=10):
    return {"T": "b", "S": sym, "o": c, "h": c + 1, "l": c - 1, "c": c, "v": v, "t": t_utc}


def test_bars_and_late_corrections_land_in_memory():
    s = st.BarStore({})
    ts = s.add(bar("AMD", "2026-10-01T13:31:00Z", c=100))
    assert ts == pd.Timestamp("2026-10-01 09:31", tz=ET)
    s.add({**bar("AMD", "2026-10-01T13:31:00Z", c=101), "T": "u"})          # correction replaces, not appends
    s.add(bar("AMD", "2026-10-01T13:30:00Z", c=99))                         # out of order still sorts
    df = s.minute_frames()["AMD"]
    assert list(df["close"]) == [99, 101] and df.index.is_monotonic_increasing
    assert s.last_bar == pd.Timestamp("2026-10-01 09:31", tz=ET)
    assert s.add(bar("AMD", "2026-10-01T21:05:00Z")) is None                # after hours ignored


def test_five_minute_bars_match_alpacas_labels():
    s = st.BarStore({})
    for i in range(7):                                                      # 09:30 .. 09:36
        s.add(bar("NVDA", f"2026-10-01T13:{30 + i:02d}:00Z", c=100 + i, v=1))
    f = s.five_minute_frames(pd.Timestamp("2026-10-01").date())["NVDA"]
    assert [t.strftime("%H:%M") for t in f.index] == ["09:30", "09:35"]
    first = f.iloc[0]
    assert (first.open, first.close, first.high, first.low, first.volume) == (100, 104, 105, 99, 5)


def test_a_minute_fires_once_when_every_symbol_is_in():
    trg = st.MinuteTrigger(["A", "B"], settle=1.5)
    m = pd.Timestamp("2026-10-01 09:31", tz=ET)
    trg.arrive("A", m, 0.0)
    assert not trg.due(0.5)
    trg.arrive("B", m, 0.6)
    assert trg.due(0.6)
    trg.fired()
    trg.arrive("A", m, 0.9)                                                 # a correction to that minute
    assert not trg.due(5.0)


def test_a_thin_minute_fires_after_the_settle_time():
    trg = st.MinuteTrigger(["A", "B"], settle=1.5)
    trg.arrive("A", pd.Timestamp("2026-10-01 09:31", tz=ET), 10.0)
    assert not trg.due(11.0) and trg.due(11.6)


def test_scans_read_from_the_stream_not_the_network(monkeypatch):
    class NoNetwork:
        def intraday_bars(self, *a, **k):
            raise AssertionError("fetched over REST while streaming")
    store = st.BarStore({})
    store.add(bar("AMD", "2026-10-01T13:31:00Z"))
    monkeypatch.setattr(lb, "_STREAM", store)
    now = pd.Timestamp("2026-10-01 09:33", tz=ET)
    assert "AMD" in lb._minute_bars(NoNetwork(), now)


def test_the_stream_stays_within_the_free_plan():
    assert len(lb.WATCHLIST) <= st.MAX_SYMBOLS
