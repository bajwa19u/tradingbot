"""Break & Retest V1 - every rule in the spec, on hand-built bars."""
from __future__ import annotations

import pandas as pd
import pytest

from src import br_bench, br_chart, br_discord, br_report, br_run
from src import br_config as bcfg
from src.br_engine import Engine, run_day
from src.br_levels import Level, build_levels, merge, prior_day_levels, resample, split_day
from src.br_trade import plan, run_exit, simulate

ET = "America/New_York"
D1, D2 = "2026-09-24", "2026-09-25"


def frame(day: str, rows) -> pd.DataFrame:
    """rows = (HH:MM, open, high, low, close[, volume])"""
    idx, data = [], []
    for r in rows:
        idx.append(pd.Timestamp(f"{day} {r[0]}", tz=ET))
        data.append({"open": r[1], "high": r[2], "low": r[3], "close": r[4],
                     "volume": r[5] if len(r) > 5 else 1000.0})
    return pd.DataFrame(data, index=pd.DatetimeIndex(idx))


def flat(day: str, start: str, n: int, px: float) -> list:
    t = pd.Timestamp(f"{day} {start}")
    return [(f"{(t + pd.Timedelta(minutes=i)):%H:%M}", px, px + 0.02, px - 0.02, px) for i in range(n)]


@pytest.fixture
def cfg():
    return bcfg.load()


def lv(price=100.0, kind="pdh", dirs=("long",), active=True):
    return Level(kind, kind, price, dirs, active)


def feed(eng: Engine, day: str, rows):
    out = []
    for r in rows:
        out += eng.on_bar(pd.Timestamp(f"{day} {r[0]}", tz=ET), *r[1:5])
    return out


# ---------------------------------------------------------------- levels
def test_previous_day_levels_ignore_the_premarket_and_today(cfg):
    prior = frame(D1, [("08:00", 100, 130, 90, 100)] + flat(D1, "09:30", 390, 100.0)
                  + [("15:59", 100, 101, 99, 100.5)])
    _, rth = split_day(prior)
    lv_ = prior_day_levels(rth)
    assert lv_ == {"pdh": 101.0, "pdl": 99.0, "pdc": 100.5}   # the 08:00 spike is not PDH


def test_pm_levels_only_active_when_open_is_outside_yesterdays_range(cfg):
    pd_lv, pm_lv = {"pdh": 105.0, "pdl": 95.0, "pdc": 100.0}, {"pmh": 102.0, "pml": 98.0}
    levels, state = build_levels(pd_lv, pm_lv, 100.0, cfg)
    assert state == "inside"
    assert {l.kind: l.active for l in levels}["pmh"] is False
    levels, state = build_levels(pd_lv, {"pmh": 108.0, "pml": 104.0}, 106.0, cfg)
    assert state == "above_pdh"
    assert all(l.active for l in levels)


def test_levels_within_tolerance_merge_into_the_higher_priority_one():
    out = merge([lv(100.0, "pmh"), lv(100.05, "pdh")], 0.10)
    assert len(out) == 1 and out[0].kind == "pdh" and out[0].aliases == ["pmh"]


def test_resampled_bars_start_at_the_open():
    rth = frame(D1, flat(D1, "09:30", 10, 100.0))
    assert list(resample(rth, 5).index.strftime("%H:%M")) == ["09:30", "09:35"]


# ---------------------------------------------------------------- the engine
def test_break_retest_confirmation_long(cfg):
    eng = Engine("X", 1, D1, [lv()], cfg, prev_close=99.8)
    done = feed(eng, D1, [("09:30", 99.8, 99.95, 99.7, 99.9),
                          ("09:31", 99.9, 100.4, 99.9, 100.3),      # CLOSE above 100: the break
                          ("09:32", 100.3, 100.5, 100.25, 100.45),  # runs away
                          ("09:33", 100.4, 100.42, 100.05, 100.1),  # comes back: retest (red)
                          ("09:34", 100.1, 100.3, 100.08, 100.28)]) # green close above: confirmation
    c = done[-1]
    assert c.status == "confirmed" and c.direction == "long"
    assert c.entry == 100.28
    assert c.signal_ts == pd.Timestamp(f"{D1} 09:35", tz=ET)       # known when the candle closes
    assert c.break_ts == pd.Timestamp(f"{D1} 09:31", tz=ET)


def test_a_wick_through_the_level_is_not_a_break(cfg):
    eng = Engine("X", 1, D1, [lv()], cfg, prev_close=99.8)
    feed(eng, D1, [("09:30", 99.8, 100.6, 99.7, 99.9)] + [r for r in flat(D1, "09:31", 10, 99.9)])
    assert not any(t.stage != "armed" for t in eng.trackers)


def test_no_entry_on_the_breakout_candle_itself(cfg):
    eng = Engine("X", 1, D1, [lv()], cfg, prev_close=99.8)
    out = feed(eng, D1, [("09:30", 99.9, 100.4, 99.95, 100.3)])    # breaks AND dips near the level
    assert out == [] and eng.trackers[0].stage == "broken"


def test_small_dip_through_the_level_is_wiggle_room_not_failure(cfg):
    eng = Engine("X", 1, D1, [lv()], cfg, prev_close=99.8)
    out = feed(eng, D1, [("09:30", 99.9, 100.4, 99.9, 100.3),
                         ("09:31", 100.3, 100.3, 99.9, 99.92),     # closes 0.08% below: allowed
                         ("09:32", 99.92, 100.2, 99.9, 100.15)])   # green, back above: confirmed
    assert out and out[-1].status == "confirmed"


def test_a_meaningful_close_back_through_is_a_failed_breakout(cfg):
    eng = Engine("X", 1, D1, [lv()], cfg, prev_close=99.8)
    out = feed(eng, D1, [("09:30", 99.9, 100.4, 99.9, 100.3),
                         ("09:31", 100.3, 100.3, 99.6, 99.7)])     # closes 0.3% below
    assert out[-1].status == "failed_breakout"


def test_short_is_the_mirror(cfg):
    eng = Engine("X", 1, D1, [lv(100.0, "pdl", ("short",))], cfg, prev_close=100.2)
    out = feed(eng, D1, [("09:30", 100.1, 100.15, 99.6, 99.7),     # close below support
                         ("09:31", 99.7, 99.95, 99.65, 99.9),      # back up to it
                         ("09:32", 99.9, 99.93, 99.6, 99.65)])     # red close below: confirmed
    assert out[-1].status == "confirmed" and out[-1].direction == "short"


def test_retest_must_come_within_the_window(cfg):
    c = bcfg.load(retest={"max_minutes_after_break": 5})
    eng = Engine("X", 1, D1, [lv()], c, prev_close=99.8)
    out = feed(eng, D1, [("09:30", 99.9, 100.6, 99.9, 100.5)] + flat(D1, "09:31", 6, 101.0))
    assert out[-1].status == "retest_timeout"


def test_inactive_and_gap_levels_complete_but_carry_a_blocker(cfg):
    eng = Engine("X", 1, D1, [lv(100.0, "pmh", active=False)], cfg, prev_close=99.8)
    out = feed(eng, D1, [("09:30", 99.9, 100.4, 99.9, 100.3), ("09:31", 100.3, 100.35, 100.05, 100.32)])
    assert out[-1].status == "confirmed" and "inactive_level" in out[-1].blockers
    eng = Engine("X", 1, D1, [lv()], cfg, prev_close=100.6)          # premarket already above
    out = feed(eng, D1, [("09:30", 100.6, 100.8, 100.5, 100.7), ("09:31", 100.7, 100.7, 100.05, 100.3),
                         ("09:32", 100.3, 100.5, 100.25, 100.45)])
    assert out and "gap_beyond_level" in out[-1].blockers


def test_swing_highs_become_levels_after_they_are_confirmed(cfg):
    eng = Engine("X", 1, D1, [], cfg, prev_close=100.0)
    rows = [("09:30", 100, 100.2, 99.9, 100.1), ("09:31", 100.1, 100.3, 100, 100.2),
            ("09:32", 100.2, 100.4, 100.1, 100.3), ("09:33", 100.3, 101.0, 100.2, 100.4),   # pivot high 101
            ("09:34", 100.4, 100.5, 100.1, 100.2), ("09:35", 100.2, 100.4, 100.0, 100.1),
            ("09:36", 100.1, 100.3, 99.9, 100.0)]
    feed(eng, D1, rows)
    assert any(l.kind == "swing_high" and l.price == 101.0 for l in eng.levels)


def test_no_bars_after_the_signal_window_are_used(cfg):
    lvl = [lv()]
    bars = frame(D1, flat(D1, "09:30", 120, 99.9) + [("11:30", 99.9, 100.4, 99.9, 100.3),
                                                     ("11:31", 100.3, 100.35, 100.05, 100.3)])
    out = run_day("X", 1, D1, lvl, bars, cfg, 99.8, until_min=11 * 60 + 30)
    assert not any(c.status == "confirmed" for c in out)


# ---------------------------------------------------------------- trades
def test_size_comes_from_risk_over_stop_distance(cfg):
    p = plan("long", 100.28, 100.0, 100.05, cfg)
    assert p["stop"] == pytest.approx(99.5)                       # 0.5% below the level
    assert p["shares"] == int(1000 // p["risk_per_share"])
    assert p["target"] == pytest.approx(p["entry"] + 2 * p["risk_per_share"])
    assert p["dollar_risk"] <= 1000


def test_stop_wins_a_bar_that_touches_both(cfg):
    import numpy as np
    r, k, why = run_exit(np.array([103.0]), np.array([98.0]), np.array([100.0]), 1, 100.0, 99.0, 102.0, 0.0)
    assert why == "stop" and r == pytest.approx(-1.0)


def _rth(rows):
    return frame(D1, rows)


def test_post_stop_recovery_is_classified(cfg):
    p = plan("long", 100.0, 100.0, None, cfg)                     # stop ~99.5
    rows = [("10:00", 100, 100.1, 99.4, 99.6)] + [(f"10:{i:02d}", 100, 102.5, 99.9, 102) for i in range(1, 20)]
    res = simulate(_rth(rows), pd.Timestamp(f"{D1} 10:00", tz=ET), "long", p, cfg, level=100.0)
    assert res["outcome"] == "stop"
    assert res["sl_class"] == "STOP-OUT -> 2R RECOVERY"
    rows = [("10:00", 100, 100.1, 99.4, 99.6)] + [(f"10:{i:02d}", 99, 99.2, 98.5, 98.6) for i in range(1, 20)]
    res = simulate(_rth(rows), pd.Timestamp(f"{D1} 10:00", tz=ET), "long", p, cfg, level=100.0)
    assert res["sl_class"] == "TRUE FAILURE"


def test_post_target_continuation_is_measured(cfg):
    p = plan("long", 100.0, 100.0, None, cfg)
    rps = p["risk_per_share"]
    up = [(f"10:{i:02d}", 100 + i * 0.3, 100 + i * 0.3 + 0.1, 100 + i * 0.3 - 0.1, 100 + i * 0.3 + 0.05)
          for i in range(0, 40)]
    res = simulate(_rth(up), pd.Timestamp(f"{D1} 10:00", tz=ET), "long", p, cfg, level=100.0)
    assert res["outcome"] == "target" and res["r"] == pytest.approx(2.0)
    assert res["tp_3r_30"] and res["tp_extra_r_30"] > 1
    assert res["mfe_r_eod"] > 3 and res["beyond_2r_eod"] > 1
    assert "alt_stop_0.25pct" in res and "alt_trail_after_2r" in res and res["mfe_r"] >= 2


# ---------------------------------------------------------------- pipeline
def _two_days():
    prior = flat(D1, "09:30", 390, 99.5)
    prior[100] = ("11:10", 99.5, 100.0, 99.4, 99.6)                # PDH 100.0
    today = flat(D2, "04:00", 60, 99.6) + [("09:30", 99.6, 99.8, 99.5, 99.7),
                                           ("09:31", 99.7, 100.4, 99.7, 100.3),
                                           ("09:32", 100.3, 100.6, 100.3, 100.5),
                                           ("09:33", 100.5, 100.5, 100.05, 100.1),
                                           ("09:34", 100.1, 100.4, 100.08, 100.35)]
    t = pd.Timestamp(f"{D2} 09:35")
    today += [(f"{(t + pd.Timedelta(minutes=i)):%H:%M}", 100.35 + i * 0.01, 100.4 + i * 0.01,
               100.3 + i * 0.01, 100.37 + i * 0.01) for i in range(380)]
    return pd.concat([frame(D1, prior), frame(D2, today)])


def test_pipeline_produces_a_taken_signal_with_context(cfg):
    df = _two_days()
    data = {s: df for s in ("SPY", "QQQ", "AAA")}
    c = bcfg.load(universe={"symbols": ["SPY", "QQQ", "AAA"]})
    sess = br_run.sessions(data)
    ev, setups = br_run.run(sess, {}, [pd.Timestamp(D2).date()], c)
    dec = br_run.decide(ev, [1, 3, 5], c)
    taken = dec[dec.taken & (dec.symbol == "AAA")]
    assert len(taken) == 1
    t = taken.iloc[0]
    assert t.level_kind == "pdh" and t.tf == 1 and t.confidence in ("HIGH", "MEDIUM", "LOW")
    # the synthetic PMH (99.62) breaks too, and opened inside PDH-PDL, so it is rejected, not taken
    assert set(dec.reject_reason) <= {"", "inactive_level", "position_open", "max_signals_per_day"}


def test_benchmarks_report_detected_and_missed(cfg):
    df = _two_days()
    c = bcfg.load(universe={"symbols": ["SPY", "QQQ", "AAA"]})
    sess = br_run.sessions({s: df for s in ("SPY", "QQQ", "AAA")})
    ev, _ = br_run.run(sess, {}, [pd.Timestamp(D2).date()], c)
    dec = br_run.decide(ev, [1, 3, 5], c)
    res = br_bench.evaluate([{"symbol": "AAA", "date": D2, "time": "09:35", "direction": "long"},
                             {"symbol": "AAA", "date": D2, "time": "09:35", "direction": "short"},
                             {"symbol": "AAA", "date": "2020-01-02", "time": "09:35", "direction": "long"}],
                            dec, ev, {pd.Timestamp(D2).date()})
    assert [r["status"] for r in res] == ["detected", "missed", "no_data"]


def test_a_losing_result_is_never_called_working():
    s = br_report.stats(pd.DataFrame({"r": [-1.0, 2.0, -1.0, -1.0], "duration_min": [5] * 4}))
    assert br_report.verdict(s).startswith("LOSING")


# ---------------------------------------------------------------- outputs
def _sig():
    return {"direction": "long", "symbol": "NVDA", "signal_ts": pd.Timestamp(f"{D2} 09:47", tz=ET),
            "level": 181.2, "level_kind": "pdh", "tf": 1, "entry": 181.5, "stop": 180.29, "target": 183.92,
            "target_r": 2.0, "risk_dollars": 1000, "market_bias": "Bullish", "spy_bias": "Bullish",
            "qqq_bias": "Bullish", "vwap_side": "Above", "confidence": "HIGH"}


def test_discord_card_has_every_field_the_spec_lists():
    text = br_discord.card(_sig())
    for want in ("🟢 BREAK & RETEST LONG", "NVDA", "Time: 9:47 AM ET", "Level: $181.20 PDH", "Break: Confirmed",
                 "Retest: Confirmed", "Confirmation: Bullish close", "Entry: $181.50", "Stop: $180.29",
                 "Target: $183.92", "R:R: 2.0", "Risk: $1,000", "Market Bias: Bullish", "SPY: Bullish",
                 "QQQ: Bullish", "VWAP: Above", "Confidence: HIGH"):
        assert want in text, want


def test_without_a_webhook_nothing_is_sent():
    assert br_discord.post(None, "hello") is None


def test_chart_renders_a_png(tmp_path, cfg):
    day = _two_days()
    day = day[day.index.date == pd.Timestamp(D2).date()]
    tr = {"level": 100.0, "level_name": "pdh", "entry": 100.35, "stop": 99.5, "target": 102.05,
          "signal_ts": pd.Timestamp(f"{D2} 09:35", tz=ET), "exit_ts": None, "outcome": None}
    p = br_chart.render(tmp_path / "x.png", "AAA", "long", day, pd.Timestamp(f"{D2} 09:45", tz=ET),
                        {"pdh": 100.0, "pdl": 99.4}, tr)
    assert p.exists() and p.stat().st_size > 5000
    assert set(br_chart.snapshots({**tr, "outcome": "stop", "exit_ts": tr["signal_ts"]}, cfg)) == \
        {"signal", "plus5", "plus10", "stop"}


# ---------------------------------------------------------------- live
class FakeMD:
    def __init__(self, df):
        self.df = df

    def intraday_bars(self, symbols, minutes, start, end=None, extended=False):
        tz = lambda x: x.tz_localize(ET) if x.tzinfo is None else x       # noqa: E731
        s, e = tz(pd.Timestamp(start)), tz(pd.Timestamp(end)) if end else None
        out = {}
        for sym in symbols:
            d = self.df[self.df.index >= s]
            out[sym] = d[d.index < e] if e is not None else d
        return out

    def daily_bars(self, symbols, start, end=None):
        return {}


def test_live_session_signals_on_the_closing_minute_and_logs_latency(tmp_path, cfg, monkeypatch):
    from src import br_live
    df = _two_days()
    c = bcfg.load(universe={"symbols": ["SPY", "QQQ", "AAA"]})
    today = pd.Timestamp(D2).date()
    live_df = df[df.index < pd.Timestamp(f"{D2} 09:30", tz=ET)]
    s = br_live.Session(c, dry_run=True, md_iex=FakeMD(df), md_sip=FakeMD(live_df), today=today)
    s.dir_state, s.dir_charts = tmp_path / "state", tmp_path / "charts"
    s.prepare()
    s.premarket()
    s.poll(pd.Timestamp(f"{D2} 09:30", tz=ET))
    got = []
    for m in pd.date_range(f"{D2} 09:30", f"{D2} 09:40", freq="1min", tz=ET):
        got += s.on_minute(m, m + pd.Timedelta(minutes=1, seconds=2))
    aaa = [g for g in got if g["symbol"] == "AAA"]
    assert len(aaa) == 1 and aaa[0]["signal_ts"] == pd.Timestamp(f"{D2} 09:35", tz=ET)
    lat = (tmp_path / "state" / "latency.jsonl").read_text()
    assert '"detect_s": 2.0' in lat
    assert any(p.name.endswith("_signal.png") for p in (tmp_path / "charts").iterdir())


def test_v1_settings_load_and_validate():
    c = bcfg.load()
    assert c.risk.stop_buffer_pct == 0.5 and c.risk.target_r == 2.0 and c.risk.risk_dollars == 1000
    assert c.session.signals_until == "11:30"
    assert "SNDK" in c.universe.symbols and len(c.universe.symbols) == 13
    assert c.context.block_counter_bias is False          # V1: bias informs, never blocks
    with pytest.raises(ValueError):
        bcfg.load(risk={"stop_ref": "nonsense"})
