"""Rule-by-rule verification of the break-and-retest engine."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.backtest import Backtester                      # noqa: E402
from src.config import load_config                        # noqa: E402
from src.indicators import (                              # noqa: E402
    is_bearish_engulfing, is_bullish_engulfing, is_hammer, is_inverted_hammer,
)
from src.strategy.break_retest import BreakRetestEngine, State  # noqa: E402
from tests import fixtures                                # noqa: E402

# Daily ATR for the fixtures. Opening range is 1.00 wide, so 2.5 puts the
# range at 0.40 of daily ATR - inside the 0.10-0.60 window.
ATR = 2.5


@pytest.fixture
def cfg():
    return load_config()


def run(df, cfg, symbol="TEST"):
    engine = BreakRetestEngine(symbol, cfg, daily_atr=ATR)
    signals = []
    for _, bar in df.iterrows():
        sig = engine.on_bar(bar)
        if sig:
            signals.append(sig)
    return engine, signals


# ---------------------------------------------------------------------------
# Rule 1-5: the happy path
# ---------------------------------------------------------------------------
def test_clean_long_setup_signals(cfg):
    engine, signals = run(fixtures.clean_long_setup(), cfg)
    assert len(signals) == 1, "a textbook setup must produce exactly one signal"
    sig = signals[0]
    assert sig.direction == "long"
    assert sig.pattern == "hammer@level"   # tagged with what was retested
    assert sig.opening_range_high == pytest.approx(100.5)
    assert sig.opening_range_low == pytest.approx(99.5)
    assert sig.level == pytest.approx(100.5)
    assert sig.entry == pytest.approx(100.95)
    # stop below the confirmation low, minus the ATR buffer
    assert sig.stop == pytest.approx(100.5 - ATR * cfg.risk.stop_buffer_atr_multiple)
    assert sig.atr == pytest.approx(ATR)
    assert sig.stop < sig.entry < sig.target
    # target is exactly reward_multiple x risk
    risk = sig.entry - sig.stop
    assert sig.target == pytest.approx(
        sig.entry + cfg.risk.reward_multiple * risk, abs=1e-6)
    assert sig.risk_per_share == pytest.approx(risk, abs=1e-6)
    assert engine.state is State.CONFIRMED


def test_clean_short_setup_signals(cfg):
    _, signals = run(fixtures.clean_short_setup(), cfg)
    assert len(signals) == 1
    sig = signals[0]
    assert sig.direction == "short"
    assert sig.level == pytest.approx(99.5)
    assert sig.stop > sig.entry > sig.target
    risk = sig.stop - sig.entry
    assert sig.target == pytest.approx(
        sig.entry - cfg.risk.reward_multiple * risk, abs=1e-6)


def test_position_sizing_risks_the_configured_amount(cfg):
    _, signals = run(fixtures.clean_long_setup(), cfg)
    sig = signals[0]
    budget = cfg.risk.account_equity * cfg.risk.risk_per_trade_pct / 100.0
    ideal = int(budget // sig.risk_per_share)
    notional_cap = int(
        cfg.risk.account_equity * cfg.risk.max_position_pct_of_equity
        / 100.0 // sig.entry
    )
    assert sig.shares == min(ideal, notional_cap)
    # never risk more than the configured budget
    assert sig.dollar_risk <= budget + 1e-6
    # and when the notional cap bites, the signal must say so
    if sig.shares < ideal:
        assert any("capped" in n for n in sig.notes)


def test_notional_cap_is_disclosed_on_a_small_account(cfg):
    small = load_config()
    small["risk"]["account_equity"] = 2000.0
    _, signals = run(fixtures.clean_long_setup(), small)
    sig = signals[0]
    assert sig.shares * sig.entry <= 2000.0 + 1e-6
    assert any("capped" in n for n in sig.notes)


# ---------------------------------------------------------------------------
# The rejection rules — these are what keep it a strategy, not a gambler
# ---------------------------------------------------------------------------
def test_retest_without_confirmation_candle_is_rejected(cfg):
    engine, signals = run(fixtures.retest_without_confirmation(), cfg)
    assert signals == [], "no confirmation candle means no trade"
    assert any(r.reason == "no_confirmation_candle" for r in engine.rejections)


def test_failed_break_kills_the_setup(cfg):
    engine, signals = run(fixtures.failed_break(), cfg)
    assert signals == []
    assert engine.state is State.INVALIDATED
    assert any(r.reason == "failed_break" for r in engine.rejections)


def test_low_volume_break_is_ignored(cfg):
    engine, signals = run(fixtures.low_volume_break(), cfg)
    assert signals == [], "a break without volume must not produce a signal"
    assert any(r.reason == "break_volume_too_low" for r in engine.rejections)
    assert engine.state is not State.CONFIRMED


def test_late_retest_expires(cfg):
    engine, signals = run(fixtures.retest_too_late(), cfg)
    assert signals == []
    assert engine.state is State.EXPIRED
    assert any(r.reason == "retest_never_came" for r in engine.rejections)


def test_opening_range_too_wide_is_skipped(cfg):
    # width is 1.0; an ATR of 0.5 makes the range 2.0x ATR > max 1.5x
    engine = BreakRetestEngine("TEST", cfg, daily_atr=0.5)
    for _, bar in fixtures.clean_long_setup().iterrows():
        assert engine.on_bar(bar) is None
    assert engine.state is State.INVALIDATED
    assert any(r.reason == "opening_range_too_wide" for r in engine.rejections)


# ---------------------------------------------------------------------------
# Candle pattern primitives
# ---------------------------------------------------------------------------
def test_hammer_detection():
    import pandas as pd
    good = pd.Series({"open": 100.9, "high": 100.98, "low": 100.5, "close": 100.95})
    bad = pd.Series({"open": 100.5, "high": 101.5, "low": 100.4, "close": 101.4})
    assert is_hammer(good)
    assert not is_hammer(bad)
    assert is_inverted_hammer(
        pd.Series({"open": 100.1, "high": 100.6, "low": 100.05, "close": 100.05}))


def test_engulfing_detection():
    import pandas as pd
    prev = pd.Series({"open": 101.0, "high": 101.1, "low": 100.4, "close": 100.5})
    cur = pd.Series({"open": 100.45, "high": 101.3, "low": 100.4, "close": 101.2})
    assert is_bullish_engulfing(prev, cur)
    assert not is_bearish_engulfing(prev, cur)
    assert is_bearish_engulfing(
        pd.Series({"open": 100.5, "high": 101.1, "low": 100.4, "close": 101.0}),
        pd.Series({"open": 101.05, "high": 101.1, "low": 100.3, "close": 100.4}),
    )


# ---------------------------------------------------------------------------
# Backtester: does a known winner book ~+2R and a known loser ~-1R?
# ---------------------------------------------------------------------------
def _daily_stub(df, daily_range: float = 2.5):
    """Prior daily bars whose 14-day ATR equals the ATR the engine tests use."""
    import pandas as pd
    idx = pd.date_range(end=df.index[0].normalize() - pd.Timedelta(days=1),
                        periods=30, freq="D", tz=df.index.tz)
    half = daily_range / 2.0
    return pd.DataFrame(
        {"open": 100.0, "high": 100.0 + half, "low": 100.0 - half,
         "close": 100.0, "volume": 1_000_000.0}, index=idx)


def test_daily_atr_stub_scales_to_intraday_atr(cfg):
    from src.strategy.break_retest import compute_daily_atr
    df = fixtures.clean_long_setup()
    assert compute_daily_atr(_daily_stub(df)) == pytest.approx(ATR, abs=0.05)


def test_backtest_books_a_winner(cfg):
    cfg = load_config()
    cfg["risk"]["exit_style"] = "fixed"      # this test pins the 2R path
    df = fixtures.clean_long_setup()
    result = Backtester(cfg).run({"TEST": df}, {"TEST": _daily_stub(df)})
    trades = result["trades"]
    assert len(trades) == 1
    t = trades[0]
    assert t["exit_reason"] == "target"
    # 2R target minus entry and exit slippage
    assert 1.6 <= t["r_multiple"] <= 2.0
    assert t["pnl"] > 0
    assert result["stats"]["win_rate_pct"] == 100.0


def test_backtest_books_a_loser(cfg):
    cfg = load_config()
    cfg["risk"]["exit_style"] = "fixed"
    df = fixtures.stopped_out_long()
    result = Backtester(cfg).run({"TEST": df}, {"TEST": _daily_stub(df)})
    trades = result["trades"]
    assert len(trades) == 1
    t = trades[0]
    assert t["exit_reason"] in ("stop", "breakeven")
    assert -1.3 <= t["r_multiple"] <= -0.9
    assert t["pnl"] < 0


def test_backtest_respects_max_trades_per_symbol(cfg):
    df = fixtures.clean_long_setup()
    result = Backtester(cfg).run({"TEST": df}, {"TEST": _daily_stub(df)})
    assert len(result["trades"]) <= cfg.strategy.filters.max_trades_per_symbol_per_day


def test_stats_are_internally_consistent(cfg):
    df = fixtures.clean_long_setup()
    result = Backtester(cfg).run({"TEST": df}, {"TEST": _daily_stub(df)})
    s = result["stats"]
    assert s["n_trades"] == len(result["trades"])
    assert s["total_R"] == pytest.approx(
        sum(t["r_multiple"] for t in result["trades"]), abs=0.02)


# ---------------------------------------------------------------------------
# Momentum exit management
# ---------------------------------------------------------------------------
def _run_exits(df, cfg):
    return Backtester(cfg).run({"TEST": df}, {"TEST": _daily_stub(df)})["trades"]


def test_fast_runner_trails_instead_of_capping_at_2R(cfg):
    assert cfg.risk.exit_style == "momentum"
    trades = _run_exits(fixtures.fast_runner(), cfg)
    assert len(trades) == 1
    t = trades[0]
    assert t["exit_reason"] == "trail", t
    # stop was lifted to 2R and trailed, so the result must clear 1.5R
    assert t["r_multiple"] >= 1.5, t
    assert t["pnl"] > 0


def test_slow_grinder_settles_for_the_smaller_target(cfg):
    trades = _run_exits(fixtures.slow_grinder(), cfg)
    assert len(trades) == 1
    t = trades[0]
    assert t["exit_reason"] == "target"
    # target dropped to 1.5R, so it must not book anywhere near 2R
    assert 1.3 <= t["r_multiple"] <= 1.6, t


def test_one_retest_of_entry_moves_stop_to_breakeven(cfg):
    trades = _run_exits(fixtures.retests_entry(), cfg)
    assert len(trades) == 1
    t = trades[0]
    assert t["exit_reason"] == "breakeven", t
    # a scratch, not a full 1R loss
    assert -0.2 <= t["r_multiple"] <= 0.05, t


def test_momentum_style_beats_fixed_on_the_fast_runner(cfg):
    """The whole point: a fast mover should earn more than a capped 2R exit
    minus slippage would have."""
    import copy
    fixed = load_config()
    fixed["risk"]["exit_style"] = "fixed"
    fast = _run_exits(fixtures.fast_runner(), cfg)[0]
    capped = _run_exits(fixtures.fast_runner(), fixed)[0]
    assert fast["r_multiple"] > capped["r_multiple"], (fast, capped)


def test_htf_filter_blocks_trades_against_the_1h_trend(cfg):
    """With 1H context required and a downtrend supplied, a long setup must
    be rejected rather than taken."""
    import pandas as pd
    from src.strategy.break_retest import BreakRetestEngine, State
    c = load_config()
    c["strategy"]["filters"]["require_htf_alignment"] = True
    df = fixtures.clean_long_setup()
    # 1H context says DOWN for the whole session
    bearish = pd.Series([-1.0, -1.0],
                        index=pd.DatetimeIndex([df.index[0] - pd.Timedelta(hours=2),
                                                df.index[0] - pd.Timedelta(hours=1)]))
    eng = BreakRetestEngine("TEST", c, daily_atr=ATR, htf_trend=bearish)
    signals = [s for _, bar in df.iterrows() if (s := eng.on_bar(bar))]
    assert signals == [], "a long must not fire against a 1H downtrend"
    assert any(r.reason == "htf_context_against_long" for r in eng.rejections)

    # and the same setup with bullish context still fires
    bullish = pd.Series([1.0, 1.0], index=bearish.index)
    eng2 = BreakRetestEngine("TEST", c, daily_atr=ATR, htf_trend=bullish)
    signals2 = [s for _, bar in df.iterrows() if (s := eng2.on_bar(bar))]
    assert len(signals2) == 1, "aligned context must not block the trade"


def test_htf_series_is_shifted_to_avoid_lookahead():
    """The 1H trend must only become visible after its candle has closed."""
    import pandas as pd
    from src.backtest import _htf_trend
    from src.config import load_config as lc
    idx = pd.date_range("2026-01-02 09:30", periods=400, freq="5min",
                        tz="America/New_York")
    import numpy as np
    px = pd.Series(np.linspace(100, 110, 400), index=idx)
    df = pd.DataFrame({"open": px, "high": px + 0.1, "low": px - 0.1,
                       "close": px, "volume": 1000.0}, index=idx)
    trend = _htf_trend(df, lc())
    assert trend is not None
    hourly = df.resample("60min", label="left", closed="left",
                         origin="start_day").agg({"close": "last"}).dropna()
    # every trend timestamp must sit at or after the END of its source bar
    assert trend.index[0] >= hourly.index[0] + pd.Timedelta(minutes=60)


# ---------------------------------------------------------------------------
# EMA pullback strategy
# ---------------------------------------------------------------------------
def _ema_cfg():
    c = load_config()
    c["strategy"]["name"] = "ema_pullback"
    c["strategy"]["session"]["no_entries_after"] = "16:00"
    c["strategy"]["filters"]["require_vwap_alignment"] = False
    return c


def test_ema_pullback_fires_on_a_clean_trend_dip():
    from src.strategy import make_engine
    c = _ema_cfg()
    eng = make_engine(c, "TEST", 2.5)
    signals = [s for _, bar in fixtures.ema_pullback_long().iterrows()
               if (s := eng.on_bar(bar))]
    assert len(signals) == 1, f"expected one pullback entry, got {len(signals)}"
    sig = signals[0]
    assert sig.direction == "long"
    assert sig.pattern == "ema_pullback"
    assert sig.stop < sig.entry < sig.target
    risk = sig.entry - sig.stop
    assert sig.target == pytest.approx(sig.entry + 2.0 * risk, abs=1e-6)


def test_ema_pullback_stands_down_in_chop():
    """The whole risk with this pattern is taking it when there is no trend."""
    from src.strategy import make_engine
    c = _ema_cfg()
    eng = make_engine(c, "TEST", 2.5)
    signals = [s for _, bar in fixtures.ema_pullback_chop().iterrows()
               if (s := eng.on_bar(bar))]
    assert signals == [], "a flat market must not produce pullback trades"
    assert any(r.reason == "trend_too_flat" for r in eng.rejections)


def test_strategy_registry_rejects_unknown_names():
    from src.strategy import make_engine
    c = load_config()
    c["strategy"]["name"] = "does_not_exist"
    with pytest.raises(ValueError, match="Unknown strategy"):
        make_engine(c, "TEST", 2.5)


# ---------------------------------------------------------------------------
# Wide search
# ---------------------------------------------------------------------------
def test_every_candidate_config_is_valid_and_buildable():
    """A typo in one grid entry would otherwise only surface 40 minutes into
    a search."""
    from src.discover import candidates, deep_merge
    from src.strategy import make_engine
    from src.config import Section
    base = load_config()
    for name, ov in candidates():
        cfg = Section(deep_merge(dict(base), ov))
        eng = make_engine(cfg, "TEST", 2.5)
        assert eng is not None, name
        assert cfg.strategy.name in name


def test_holdout_never_overlaps_the_research_set():
    from src.discover import HOLDOUT_SYMBOLS
    research = {"TSLA", "NVDA", "AAPL", "AMD"}
    assert not research & set(HOLDOUT_SYMBOLS)


def test_selection_rule_rejects_a_lucky_config():
    """Positive overall but negative in most periods must not be selected."""
    from src.discover import render
    lucky = {"name": "x/lucky/fixed", "n": 300, "expectancy_R": 0.2,
             "total_R": 60.0, "periods_positive": 1, "periods_scored": 4,
             "worst_period_R": -0.5, "max_dd_pct": -30.0}
    payload = {"tried": 114, "scored": 114, "survivors": 0,
               "results": [lucky], "winner": None, "holdout": None}
    class A:
        start, end = "2024-06-01", None
    text = render(payload, ["TSLA"], A(), 5)
    assert "Nothing passed the selection rule" in text
    assert "holdout was not touched" in text


def test_report_warns_about_multiple_testing():
    from src.discover import render
    good = {"name": "x/good/fixed", "n": 300, "expectancy_R": 0.15,
            "total_R": 45.0, "periods_positive": 4, "periods_scored": 4,
            "worst_period_R": 0.05, "max_dd_pct": -9.0}
    hold = {"n": 180, "expectancy_R": 0.09, "total_R": 16.2,
            "periods_positive": 3, "periods_scored": 4,
            "worst_period_R": 0.01, "max_dd_pct": -11.0}
    class A:
        start, end = "2024-06-01", None
    text = render({"tried": 114, "scored": 114, "survivors": 1,
                   "results": [good], "winner": good, "holdout": hold},
                  ["TSLA"], A(), 5)
    assert "configurations tried" in text
    assert "held up on data it had never seen" in text
    assert "Do not re-tune on the holdout" in text


def test_stop_analysis_reports_heat_taken_by_winners(cfg):
    """MAE analysis must distinguish a winner that sailed from one that nearly
    got stopped, otherwise it cannot inform stop placement."""
    df = fixtures.fast_runner()
    res = Backtester(cfg).run({"TEST": df}, {"TEST": _daily_stub(df)})
    sa = res["stats"]["stop_analysis"]
    assert sa["n_wins"] == 1
    # the fast runner barely dipped, so heat must be small
    assert sa["winner_mae_max_R"] < 0.5, sa
    # and a 0.5R stop would therefore NOT have killed it
    assert sa["winners_lost_at_0.5R_stop"] == 0, sa
    assert sa["median_stop_distance_pct"] > 0


def test_fvg_retest_is_accepted_when_price_never_reaches_the_level(cfg):
    """The methodology allows a retest of the breakout's fair-value gap, not
    just of the range level. Without it this setup is thrown away."""
    engine, signals = run(fixtures.fvg_retest_long(), cfg)
    assert len(signals) == 1, [r.reason for r in engine.rejections]
    assert signals[0].pattern.endswith("@fvg"), signals[0].pattern
    # price never came back to the 100.50 level
    lows = fixtures.fvg_retest_long()["low"].iloc[4:]
    assert lows.min() > 100.50


def test_fvg_can_be_switched_off(cfg):
    c = load_config()
    c["strategy"]["retest"]["allow_fvg"] = False
    engine, signals = run(fixtures.fvg_retest_long(), c)
    assert signals == [], "with FVG off, a gap-only retest must not fire"


def test_ema_engine_is_warm_on_the_first_bar_of_the_day():
    """Regression: without prior-session warmup a 50-period EMA is not ready
    until hours into the session, and a 100-period one never is - which
    silently produced ZERO trades for the whole ema_pullback family."""
    from src.strategy import make_engine
    c = load_config()
    c["strategy"]["name"] = "ema_pullback"
    c["strategy"]["ema_pullback"]["slow_ema"] = 100

    cold = make_engine(c, "TEST", 2.5)
    assert cold.ema_slow is None, "no warmup means no EMA, as before the fix"

    warm = make_engine(c, "TEST", 2.5,
                       context={"warmup_closes": [100.0 + i * 0.01
                                                  for i in range(400)]})
    assert warm.ema_slow is not None, "warmup must seed the slow EMA"
    assert warm.ema_fast is not None
    assert len(warm.fast_hist) > int(c["strategy"]["ema_pullback"]["slope_lookback"])


def test_backtester_feeds_prior_session_closes(cfg):
    """The warmup has to actually arrive from the backtester, not just be
    supported by the engine."""
    import pandas as pd
    c = load_config()
    c["strategy"]["name"] = "ema_pullback"
    c["strategy"]["session"]["no_entries_after"] = "15:30"
    df = fixtures.ema_pullback_long()
    # duplicate the day so there IS a prior session to warm up from
    prev = df.copy()
    prev.index = prev.index - pd.Timedelta(days=1)
    two_days = pd.concat([prev, df])
    res = Backtester(c).run({"TEST": two_days}, {"TEST": _daily_stub(two_days)})
    # day two starts warm, so it can trade in the morning rather than never
    entries = [t["entry_time"] for t in res["trades"]]
    assert res["stats"]["n_trades"] >= 1, res["stats"]


def test_verdict_calls_a_tiny_positive_result_untradeable():
    """A holdout expectancy that is positive but trivial must not be reported
    as success - that is how people end up trading noise."""
    from src.discover import render
    w = {"name": "x/w/fixed", "n": 177, "expectancy_R": 0.020, "total_R": 3.5,
         "periods_positive": 3, "periods_scored": 4, "worst_period_R": -0.05,
         "max_dd_pct": -7.1}
    h = {"n": 166, "expectancy_R": 0.007, "total_R": 1.2,
         "periods_positive": 2, "periods_scored": 4, "worst_period_R": -0.1,
         "max_dd_pct": -7.3}
    class A:
        start, end = "2024-06-01", None
    text = render({"tried": 114, "scored": 114, "survivors": 2,
                   "results": [w], "winner": w, "holdout": h}, ["TSLA"], A(), 5)
    assert "too small to trade" in text
    assert "Nothing here justifies risking money" in text
    assert "held up on data it had never seen" not in text


# ---------------------------------------------------------------------------
# Daily trend pullback (swing)
# ---------------------------------------------------------------------------
def _daily_uptrend(n=400, start=50.0, drift=0.0015, wobble=0.012, seed=5):
    """A rising series with regular dips - the shape the setup looks for."""
    import numpy as np, pandas as pd
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2015-01-02", periods=n, tz="America/New_York")
    px = start * np.cumprod(1 + drift + rng.normal(0, wobble, n))
    o = np.concatenate([[start], px[:-1]])
    h = np.maximum(o, px) * (1 + np.abs(rng.normal(0, 0.004, n)))
    l = np.minimum(o, px) * (1 - np.abs(rng.normal(0, 0.006, n)))
    return pd.DataFrame({"open": o, "high": h, "low": l, "close": px,
                         "volume": 1e6}, index=idx)


def test_swing_finds_pullbacks_in_an_uptrend():
    from src.swing import BASE, find_signals, indicators
    df = indicators(_daily_uptrend(), BASE)
    sigs = find_signals(df, BASE)
    assert len(sigs) > 5, f"expected several pullback entries, got {len(sigs)}"


def test_swing_takes_nothing_in_a_downtrend():
    """The trend stack must gate everything - no longs while price is under
    the long EMA."""
    from src.swing import BASE, find_signals, indicators
    df = indicators(_daily_uptrend(drift=-0.0015, seed=9), BASE)
    assert find_signals(df, BASE) == []


def test_swing_portfolio_respects_the_position_cap():
    from src.swing import BASE, prepare, run_portfolio
    import copy
    p = copy.deepcopy(BASE); p["max_open"] = 2
    data = {f"S{i}": _daily_uptrend(seed=i) for i in range(6)}
    res = run_portfolio(prepare(data, p), p)
    assert res["stats"]["n_trades"] > 0
    # never more than max_open held at once
    opens = sorted((t["entry_date"], 1) for t in res["trades"])
    closes = sorted((t["exit_date"], -1) for t in res["trades"])
    live = mx = 0
    for _, delta in sorted(opens + closes):
        live += delta
        mx = max(mx, live)
    assert mx <= p["max_open"], f"held {mx} positions with a cap of {p['max_open']}"


def test_swing_research_and_holdout_universes_are_disjoint():
    from src.swing import RESEARCH, HOLDOUT
    assert not set(RESEARCH) & set(HOLDOUT)
    assert len(HOLDOUT) >= 20


def test_swing_uses_only_closed_bars():
    """A signal on bar i must not depend on data after bar i."""
    from src.swing import BASE, find_signals, indicators
    df = _daily_uptrend()
    full = find_signals(indicators(df, BASE), BASE)
    if not full:
        return
    cut = full[len(full) // 2]
    truncated = find_signals(indicators(df.iloc[:cut + 1], BASE), BASE)
    assert cut in truncated, "signal vanished when future bars were removed"


def test_swing_indicators_are_not_restarted_per_period():
    """Regression: slicing before computing restarted every moving average,
    so the first months of each period traded off averages that had not
    converged. Indicators must come from full history."""
    import copy, pandas as pd
    from src.swing import BASE, prepare, run_portfolio, signal_times
    data = {"S": _daily_uptrend(600, seed=3)}
    p = copy.deepcopy(BASE)
    prepared = prepare(data, p)
    sigs = signal_times(prepared, p)

    days = prepared["S"].index
    mid = days[len(days) // 2]
    # trading only the back half must reuse the SAME signals as the full run
    late_full = {t for t in sigs["S"] if t >= mid}
    res = run_portfolio(prepared, p, sigs=sigs, lo=mid)
    for t in res["trades"]:
        assert pd.Timestamp(t["entry_date"]).date() >= mid.date()
    # and the slow EMA at the window start must already be warm
    assert prepared["S"].loc[mid, f"ema{p['slow']}"] > 0
    assert len(late_full) > 0


def test_swing_warmup_window_excludes_early_trades():
    import copy
    from src.swing import BASE, prepare, run_portfolio
    data = {"S": _daily_uptrend(600, seed=4)}
    p = copy.deepcopy(BASE)
    prepared = prepare(data, p)
    cut = prepared["S"].index[400]
    res = run_portfolio(prepared, p, lo=cut)
    assert all(t["entry_date"] >= str(cut.date()) for t in res["trades"])
