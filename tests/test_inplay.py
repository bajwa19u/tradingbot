"""Stocks in play: selection, sizing and the no-target exit.

The claim being tested is that WHAT you trade matters more than the entry,
so the tests that matter most here are the ones proving the selection is
made from information available at 09:35 and not a minute later.
"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from src import inplay as ip
from src import opening as op

EASTERN = ZoneInfo("America/New_York")


def session(day: str, first5_vol: float, hi: float, lo: float,
            close: float, n: int = 40) -> pd.DataFrame:
    """One session of one-minute bars with a controlled first-five volume."""
    y, m, d = map(int, day.split("-"))
    idx, rows = [], []
    for k in range(n):
        hh, mm = 9 + (30 + k) // 60, (30 + k) % 60
        idx.append(datetime(y, m, d, hh, mm, tzinfo=EASTERN))
        rows.append({"open": close, "high": hi if k < 5 else close,
                     "low": lo if k < 5 else close, "close": close,
                     "volume": first5_vol / 5 if k < 5 else 100.0})
    return pd.DataFrame(rows, index=pd.DatetimeIndex(idx))


def history(days: int, vol: float = 1000.0) -> pd.DataFrame:
    out = []
    for k in range(days):
        out.append(session(f"2026-06-{k + 1:02d}", vol, 101.0, 99.0, 100.0))
    return pd.concat(out)


# --- daily summary -----------------------------------------------------------
def test_daily_frame_records_the_first_five_minutes_only():
    df = session("2026-06-01", 5000.0, 101.0, 99.0, 100.0, n=40)
    d = ip.daily_frame(df)
    assert len(d) == 1
    assert d["first5"].iloc[0] == pytest.approx(5000.0)


def test_atr_excludes_the_session_being_traded():
    """Including today's range in the stop that is set at 09:35 is reading
    the day's own high and low before they have happened."""
    d = ip.daily_frame(history(20))
    d.loc[d.index[-1], "high"] = 1000.0        # a huge day, today
    quiet = ip.atr14(d, len(d) - 1)            # computed BEFORE today
    assert quiet < 50.0, "today's range must not widen today's stop"


def test_atr_needs_history():
    assert ip.atr14(ip.daily_frame(history(1)), 0) == 0.0


# --- relative volume ---------------------------------------------------------
def test_relative_volume_is_a_ratio_to_the_symbols_own_normal():
    d = ip.daily_frame(history(20))
    d.loc[d.index[-1], "first5"] = 5000.0      # five times normal
    assert ip.relative_volume(d, len(d) - 1) == pytest.approx(5.0, abs=0.01)


def test_relative_volume_ignores_a_symbol_with_no_history():
    d = ip.daily_frame(history(20))
    assert ip.relative_volume(d, 1) == 0.0


def test_relative_volume_survives_a_feed_that_sees_a_fraction_of_volume():
    """IEX prints a small slice of real volume. A ratio against the same
    symbol's own recent slice is unaffected by the scale factor — which is
    the only reason selection is testable on this feed at all."""
    d = ip.daily_frame(history(20))
    d.loc[d.index[-1], "first5"] = 4000.0
    full = ip.relative_volume(d, len(d) - 1)
    d["first5"] = d["first5"] * 0.02           # same data, 2% of the volume
    assert ip.relative_volume(d, len(d) - 1) == pytest.approx(full)


# --- selection ---------------------------------------------------------------
def test_in_play_ranks_by_relative_volume_not_by_size():
    dailies = {}
    for sym, spike in (("QUIET", 1.0), ("BUSY", 8.0), ("MID", 3.0)):
        d = ip.daily_frame(history(20))
        d.loc[d.index[-1], "first5"] = 1000.0 * spike
        dailies[sym] = d
    date = dailies["BUSY"].index[-1]
    assert [s for s, _ in ip.in_play(dailies, date, 2)] == ["BUSY", "MID"]


def test_selection_can_be_switched_off_to_reproduce_the_unfiltered_case():
    """The research's own control: the same rule with no selection. If this
    silently kept filtering, the comparison would be meaningless."""
    dailies = {}
    for sym in ("A", "B", "C"):
        dailies[sym] = ip.daily_frame(history(20))
    date = dailies["A"].index[-1]
    assert len(ip.in_play(dailies, date, 0)) == 3


def test_cheap_and_quiet_names_are_excluded():
    d = ip.daily_frame(history(20))
    d["open"] = 2.0                             # under the $5 floor
    d.loc[d.index[-1], "first5"] = 9999.0
    assert ip.in_play({"PENNY": d}, d.index[-1], 20) == []


# --- the trade ---------------------------------------------------------------
def test_no_profit_target_means_the_winner_runs_to_the_bell():
    """The AMD lesson: a 2R target closed a five-percent move at two."""
    rows = [("09:30", 100.0, 100.0, 99.0, 99.0, 1000)]
    px = 99.0
    for k in range(1, 300):
        hh, mm = 9 + (30 + k) // 60, (30 + k) % 60
        px -= 0.05
        rows.append((f"{hh:02d}:{mm:02d}", px, px + 0.01, px - 0.01, px, 1000))
    idx, data = [], []
    for hhmm, o, h, l, c, v in rows:
        hh, mm = map(int, hhmm.split(":"))
        idx.append(datetime(2026, 9, 29, hh, mm, tzinfo=EASTERN))
        data.append({"open": o, "high": h, "low": l, "close": c, "volume": v})
    day = pd.DataFrame(data, index=pd.DatetimeIndex(idx))

    free = ip.simulate(day, 0, "short", atr=5.0,
                       p={**ip.BASE, "exit_mode": "close", "atr_frac": 0.10})
    capped = ip.simulate(day, 0, "short", atr=5.0,
                         p={**ip.BASE, "exit_mode": "target", "target_r": 2.0,
                            "atr_frac": 0.10})
    assert free["reason"] == "close" and capped["reason"] == "target"
    assert free["pct"] > capped["pct"] * 3


def test_the_stop_is_a_fraction_of_the_daily_range():
    day = session("2026-09-29", 1000.0, 101.0, 99.0, 100.0, n=30)
    t = ip.simulate(day, 0, "short", atr=4.0, p={**ip.BASE, "atr_frac": 0.25})
    assert t["stop"] - t["entry"] == pytest.approx(1.0, abs=1e-6)


def test_a_stop_wider_than_a_tenth_of_price_is_refused():
    day = session("2026-09-29", 1000.0, 101.0, 99.0, 100.0, n=30)
    assert ip.simulate(day, 0, "short", atr=100.0,
                       p={**ip.BASE, "atr_frac": 0.5}) is None


def test_slippage_is_charged_on_both_ends():
    day = session("2026-09-29", 1000.0, 101.0, 99.0, 100.0, n=30)
    t = ip.simulate(day, 0, "short", atr=4.0, p=dict(ip.BASE))
    assert t["entry"] < 100.0


# --- reporting ---------------------------------------------------------------
def test_tally_is_internally_consistent():
    t = ip.tally([{"pct": 3.0}, {"pct": -1.0}, {"pct": -1.0}], ip.BASE)
    assert t["n"] == t["won"] + t["lost"] == 3
    assert t["win_pct"] == pytest.approx(33.3)
    assert t["profit_pct"] == pytest.approx(1.0)
    assert t["best"] == 3.0 and t["worst"] == -1.0


def test_the_grid_includes_the_no_selection_control():
    g = ip.grid()
    assert any(c["select_top"] == 0 for c in g), \
        "without the unfiltered case there is nothing to compare selection to"
    assert len(g) == 24


def test_results_are_reported_without_r_multiples():
    line = ip.row("x", ip.tally([{"pct": 1.0}], ip.BASE))
    assert "R" not in line


# --- cost sensitivity --------------------------------------------------------
def test_slippage_is_restored_even_when_the_pass_blows_up(monkeypatch):
    """It mutates a module global. Leaving it mutated would silently change
    the costs of every later run in the same process."""
    before = op.SLIP_PCT
    monkeypatch.setattr(ip, "run", lambda *a, **k: (_ for _ in ()).throw(
        RuntimeError("boom")))
    with pytest.raises(RuntimeError):
        ip.sensitivity({}, {}, dict(ip.BASE), set())
    assert op.SLIP_PCT == before


def test_sensitivity_reports_the_cost_level_that_kills_it(monkeypatch):
    seq = iter([[{"pct": 5.0}], [{"pct": 3.0}], [{"pct": 1.0}],
                [{"pct": -1.0}], [{"pct": -3.0}], [{"pct": -5.0}]])
    monkeypatch.setattr(ip, "run", lambda *a, **k: next(seq))
    out = ip.sensitivity({}, {}, dict(ip.BASE), set())
    assert "stops making money at slippage 0.15%" in out


def test_the_command_line_actually_parses():
    """A missing parse_args call cost a nine-minute run and produced a
    NameError after every bar had already been downloaded."""
    a = ip.parse_args([])
    assert (a.days, a.universe, a.symbols) == (60, "wide", "")
    a = ip.parse_args(["--days", "30", "--universe", "core",
                       "--symbols", "amd,nvda"])
    assert a.days == 30 and a.universe == "core" and a.symbols == "amd,nvda"


def test_costs_and_stops_are_settings_not_constants():
    a = ip.parse_args(["--slippage", "0.15", "--stops", "0.2,0.3,0.5"])
    assert a.slippage == 0.15 and a.stops == "0.2,0.3,0.5"


def test_the_grid_follows_the_stop_list():
    before = list(ip.FRACS)
    try:
        ip.FRACS[:] = [0.2, 0.3]
        assert {c["atr_frac"] for c in ip.grid()} == {0.2, 0.3}
    finally:
        ip.FRACS[:] = before
