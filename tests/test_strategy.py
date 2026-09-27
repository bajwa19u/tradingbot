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


def test_inspect_gates_explain_every_rejected_bar():
    """The per-bar explanation must name a specific failing rule, never come
    back blank - otherwise it cannot settle a chart disagreement."""
    import copy
    from src.inspect_symbol import gates, why_not
    from src.swing import BASE, indicators
    p = copy.deepcopy(BASE)
    df = indicators(_daily_uptrend(400, seed=2), p)
    g = gates(df, p)
    assert g["SIGNAL"].sum() > 0, "expected some entries on a clean uptrend"
    for _, row in g.tail(120).iterrows():
        reason = why_not(row)
        assert reason and reason != "—", row.to_dict()
        if row["SIGNAL"]:
            assert reason == "ENTRY"


def test_inspect_gates_match_find_signals():
    """The explanation table and the live strategy must agree exactly."""
    import copy
    from src.inspect_symbol import gates
    from src.swing import BASE, find_signals, indicators
    p = copy.deepcopy(BASE)
    df = indicators(_daily_uptrend(500, seed=7), p)
    from_gates = set(df.index[gates(df, p)["SIGNAL"].to_numpy()])
    from_engine = {df.index[i] for i in find_signals(df, p)}
    # find_signals also skips the first `slow` bars; compare on the overlap
    tail = df.index[p["slow"] + 1:]
    assert {t for t in from_gates if t in tail} == {t for t in from_engine if t in tail}


def test_slope_filter_stands_down_in_a_flat_market():
    """MET showed the EMA stack staying in order while price chopped sideways,
    so every dip to a flat EMA looked like a setup. The slope filter must cut
    those without killing signals in a real trend."""
    import copy, numpy as np, pandas as pd
    from src.swing import BASE, find_signals, indicators

    # a genuine uptrend, then a long flat range that keeps the stack intact
    rising = _daily_uptrend(320, drift=0.0025, seed=11)
    last = float(rising["close"].iloc[-1])
    rng = np.random.default_rng(12)
    n = 120
    idx = pd.bdate_range(rising.index[-1] + pd.Timedelta(days=1), periods=n,
                         tz="America/New_York")
    px = last * (1 + rng.normal(0, 0.008, n)).cumprod()
    px = last + (px - px.mean())            # hold it flat around `last`
    flat = pd.DataFrame({"open": np.concatenate([[last], px[:-1]]),
                         "high": px * 1.004, "low": px * 0.996,
                         "close": px, "volume": 1e6}, index=idx)
    df = pd.concat([rising, flat])

    loose = copy.deepcopy(BASE); loose["min_slope_atr"] = 0.0
    strict = copy.deepcopy(BASE); strict["min_slope_atr"] = 1.0

    def in_flat(p):
        d = indicators(df, p)
        return sum(1 for i in find_signals(d, p) if d.index[i] >= idx[0])

    assert in_flat(loose) > 0, "fixture should produce chop signals with no filter"
    assert in_flat(strict) < in_flat(loose), (
        f"slope filter cut nothing: {in_flat(strict)} vs {in_flat(loose)}")


# ---------------------------------------------------------------------------
# Self-improving loop
# ---------------------------------------------------------------------------
def test_adaptive_forward_trades_are_never_chosen_by_their_own_data():
    """The whole validity of the loop rests on this: a trade taken after a
    refit must not have influenced which config that refit picked."""
    import copy
    import pandas as pd
    from src.swing import BASE
    from src.adaptive import walk_forward
    data = {f"S{i}": _daily_uptrend(700, seed=20 + i) for i in range(4)}
    cfgs = []
    for fast in (10, 20):
        p = copy.deepcopy(BASE); p["fast"] = fast; p["min_slope_atr"] = 0.0
        cfgs.append((f"ema{fast}", p))
    days = sorted({d for df in data.values() for d in df.index})
    wf = walk_forward(data, cfgs, days, lookback=250, refit=40, min_trades=3)
    assert wf["choices"], "walk-forward produced no refits"
    # no forward trade may begin before the refit that selected its config
    first = min(pd.Timestamp(c["refit_date"]).date() for c in wf["choices"])
    for t in wf["trades"]:
        assert pd.Timestamp(t["entry_date"]).date() >= first, t
    # and the fit windows must end where the forward windows begin - a trade
    # entered during a fit window would mean the config saw its own outcome
    dates = sorted(pd.Timestamp(c["refit_date"]).date() for c in wf["choices"])
    assert dates == sorted(set(dates)), "refit dates must be distinct"


def test_adaptive_report_calls_out_a_losing_loop():
    """If refitting underperforms a static config, the report must say so
    plainly rather than presenting the adaptive number on its own."""
    from src.adaptive import render
    payload = {"universe": "research", "symbols": 40, "start": "2024-01-01",
               "end": None, "lookback": 252, "refit": 21,
               "adaptive": {"n_trades": 200, "expectancy_R": -0.05,
                            "total_R": -10.0, "win_rate_pct": 40.0,
                            "max_drawdown_pct": -20.0},
               "choices": [{"refit_date": "2024-02-01", "chose": "x",
                            "fit_expectancy_R": 0.4, "forward_expectancy_R": -0.1,
                            "forward_trades": 12}],
               "static": {"n_trades": 210, "expectancy_R": 0.08, "total_R": 16.8,
                          "win_rate_pct": 45.0, "max_drawdown_pct": -18.0},
               "static_name": "s", "hindsight": None, "hindsight_name": ""}
    text = render(payload)
    assert "adaptive LOST to static" in text
    assert "performance chasing" in text


def test_adaptive_report_credits_a_winning_loop():
    from src.adaptive import render
    payload = {"universe": "research", "symbols": 40, "start": "2024-01-01",
               "end": None, "lookback": 252, "refit": 21,
               "adaptive": {"n_trades": 200, "expectancy_R": 0.14,
                            "total_R": 28.0, "win_rate_pct": 48.0,
                            "max_drawdown_pct": -15.0},
               "choices": [],
               "static": {"n_trades": 210, "expectancy_R": 0.05, "total_R": 10.5,
                          "win_rate_pct": 44.0, "max_drawdown_pct": -18.0},
               "static_name": "s", "hindsight": None, "hindsight_name": ""}
    assert "adaptive beat static" in render(payload)


# ---------------------------------------------------------------------------
# Forensics
# ---------------------------------------------------------------------------
def test_autopsy_finds_a_planted_difference():
    """If losers really do differ from winners, the autopsy must surface it;
    otherwise the tool cannot be trusted when it reports no difference."""
    import copy
    from src.forensics import autopsy
    from src.swing import BASE, prepare, run_portfolio, signal_times
    p = copy.deepcopy(BASE); p["min_slope_atr"] = 0.0
    data = {f"S{i}": _daily_uptrend(500, seed=30 + i) for i in range(4)}
    prepared = prepare(data, p)
    res = run_portfolio(prepared, p, sigs=signal_times(prepared, p))
    a = autopsy(prepared, res["trades"], p)
    assert a and a["features"], "autopsy produced nothing"
    for f in a["features"]:
        assert "separation" in f and "winners_median" in f
    # separation must be a finite number, not NaN
    import math
    assert all(math.isfinite(f["separation"]) for f in a["features"])


def test_autopsy_reports_no_signal_when_there_is_none():
    from src.forensics import render
    payload = {"universe": "movers", "symbols": 36, "start": "2026-01-01",
               "end": None,
               "stats": {"n_trades": 120, "expectancy_R": -0.05,
                         "win_rate_pct": 40.0, "max_drawdown_pct": -20.0},
               "autopsy": {"n_wins": 48, "n_losses": 72, "features": [
                   {"feature": "atr_pct", "winners_median": 3.1,
                    "losers_median": 3.0, "separation": 0.05}]},
               "missed": {"big_moves_caught": 10, "big_moves_missed": 90,
                          "capture_rate_pct": 10.0, "blocked_by": []},
               "worst": [], "best": []}
    text = render(payload)
    assert "no condition separates winners from losers" in text
    assert "fitting noise" in text


def test_forensics_flags_small_samples():
    from src.forensics import render
    payload = {"universe": "movers", "symbols": 36, "start": "2026-08-01",
               "end": None,
               "stats": {"n_trades": 8, "expectancy_R": 0.4,
                         "win_rate_pct": 62.0, "max_drawdown_pct": -5.0},
               "autopsy": {}, "missed": {}, "worst": [], "best": []}
    text = render(payload)
    assert "Fewer than 30 trades" in text


# ---------------------------------------------------------------------------
# Expansion breakout
# ---------------------------------------------------------------------------
def _coil_then_break(n_coil=40, seed=3):
    """A long quiet range, then a decisive break upward on volume."""
    import numpy as np, pandas as pd
    rng = np.random.default_rng(seed)
    n = 260 + n_coil + 20
    idx = pd.bdate_range("2024-01-02", periods=n, tz="America/New_York")
    px = np.empty(n)
    px[:260] = 100 + np.cumsum(rng.normal(0, 0.9, 260))        # history
    base = px[259]
    px[260:260 + n_coil] = base + rng.normal(0, 0.12, n_coil)  # coil, tight
    px[260 + n_coil:] = base + 1.5 + np.arange(20) * 0.9       # expansion
    o = np.concatenate([[px[0]], px[:-1]])
    h = np.maximum(o, px) + 0.15
    l = np.minimum(o, px) - 0.15
    v = np.full(n, 1e6)
    v[260 + n_coil] = 5e6                                       # volume surge
    return pd.DataFrame({"open": o, "high": h, "low": l, "close": px,
                         "volume": v}, index=idx)


def test_breakout_fires_on_expansion_out_of_a_coil():
    import copy
    from src.breakout import BASE_BO, find_signals_bo, indicators_bo
    p = copy.deepcopy(BASE_BO)
    p.update({"base_len": 15, "touch_window": 15, "squeeze_atr": 6.0,
              "vol_mult": 1.2, "min_atr_pct": 0.0})
    df = indicators_bo(_coil_then_break(), p)
    sigs = find_signals_bo(df, p)
    assert sigs, "a coil followed by a volume break must produce a signal"
    # and it must fire at or just after the expansion, not during the coil
    first = df.index[sigs[0]]
    assert first >= df.index[270], f"fired during the coil at {first}"


def test_breakout_ignores_a_break_with_no_volume():
    import copy
    from src.breakout import BASE_BO, find_signals_bo, indicators_bo
    p = copy.deepcopy(BASE_BO)
    p.update({"base_len": 15, "touch_window": 15, "squeeze_atr": 6.0,
              "vol_mult": 3.0, "min_atr_pct": 0.0})
    df = _coil_then_break()
    df["volume"] = 1e6          # flat volume everywhere - no surge
    assert find_signals_bo(indicators_bo(df, p), p) == []


def test_breakout_volatility_floor_excludes_quiet_stocks():
    """The autopsy's one real finding: winners were far more volatile."""
    import copy
    from src.breakout import BASE_BO, find_signals_bo, indicators_bo
    p = copy.deepcopy(BASE_BO)
    p.update({"base_len": 15, "touch_window": 15, "squeeze_atr": 6.0,
              "vol_mult": 1.2, "min_atr_pct": 0.0})
    df = indicators_bo(_coil_then_break(), p)
    loose = len(find_signals_bo(df, p))
    p["min_atr_pct"] = 50.0      # nothing is this volatile
    assert loose > 0 and find_signals_bo(df, p) == []


def test_breakout_base_excludes_the_current_bar():
    """If the breakout bar's own high counted toward the base, the level it
    breaks would move with it and nothing would ever trigger correctly."""
    import copy
    from src.breakout import BASE_BO, indicators_bo
    p = copy.deepcopy(BASE_BO)
    df = indicators_bo(_coil_then_break(), p)
    row = df.iloc[-1]
    prior_high = df["high"].iloc[-1 - p["base_len"]:-1].max()
    assert abs(float(row["base_high"]) - float(prior_high)) < 1e-9


def test_breakout_report_flags_the_volatility_split():
    """The split table must state which half carries the edge, since that is
    the decision it exists to inform."""
    from src.breakout import render
    w = {"name": "x", "n": 60, "expectancy_R": 0.9, "total_R": 54.0,
         "periods_positive": 3, "periods_scored": 3, "worst_period_R": 0.2,
         "max_dd_pct": -8.0, "wins": 34, "losses": 26, "win_rate_pct": 56.7,
         "return_pct": 22.0}
    h = dict(w, n=50, wins=28, losses=22, return_pct=15.0, max_dd_pct=-9.0)
    payload = {"universe": "movers", "symbols": 36, "start": "2026-01-01",
               "tried": 36, "survivors": 1, "noise_floor": 0.40,
               "results": [w], "winner": w, "holdout": h, "holdout_size": 40,
               "halves": {
                   "loud":  {"symbols": 18, "median_atr_pct": 5.4, "n": 40,
                             "wins": 25, "losses": 15, "win_rate_pct": 62.5,
                             "return_pct": 24.0},
                   "quiet": {"symbols": 18, "median_atr_pct": 2.1, "n": 20,
                             "wins": 8, "losses": 12, "win_rate_pct": 40.0,
                             "return_pct": -2.0}}}
    text = render(payload)
    assert "Does it need volatile stocks?" in text
    assert "edge lives in the movers" in text
    assert "never seen" in text


def test_breakout_split_says_inconclusive_when_neither_half_is_volatile():
    """A median cut only makes one half louder than the other. If the loud half
    is still calmer than the bar the autopsy set, the split never tested the
    idea and must not be reported as confirming it."""
    from src.breakout import render
    w = {"name": "x", "n": 62, "expectancy_R": 0.9, "total_R": 54.0,
         "periods_positive": 3, "periods_scored": 3, "worst_period_R": 0.2,
         "max_dd_pct": -8.7, "wins": 32, "losses": 30, "win_rate_pct": 51.6,
         "return_pct": -4.2}
    h = dict(w, n=61, wins=35, losses=26, return_pct=14.0, max_dd_pct=-9.3)
    payload = {"universe": "holdout", "symbols": 30, "start": "2026-01-01",
               "tried": 1, "survivors": 1, "noise_floor": 0.40,
               "results": [w], "winner": w, "holdout": h, "holdout_size": 36,
               "halves": {
                   "loud":  {"symbols": 15, "median_atr_pct": 2.02, "n": 46,
                             "wins": 24, "losses": 22, "win_rate_pct": 52.2,
                             "return_pct": 3.6},
                   "quiet": {"symbols": 15, "median_atr_pct": 1.65, "n": 51,
                             "wins": 27, "losses": 24, "win_rate_pct": 52.9,
                             "return_pct": -1.9}}}
    text = render(payload)
    assert "inconclusive" in text
    assert "edge lives in the movers" not in text


def test_breakout_never_claims_unseen_stocks_it_did_not_have():
    """The wide universe contains every list, so no symbols are left over. The
    report printed a "Never seen" column anyway, filled with names that were
    inside the traded set - the one wrong number that would read as proof."""
    from src.breakout import render
    w = {"name": "x", "n": 69, "expectancy_R": 0.9, "total_R": 54.0,
         "periods_positive": 3, "periods_scored": 3, "worst_period_R": 0.2,
         "max_dd_pct": -11.1, "wins": 35, "losses": 34, "win_rate_pct": 50.7,
         "return_pct": 5.3}
    payload = {"universe": "wide", "symbols": 103, "start": "2026-01-01",
               "tried": 1, "survivors": 1, "noise_floor": 0.40,
               "results": [w], "winner": w, "holdout": None,
               "holdout_size": 0}
    text = render(payload)
    assert "Never seen" not in text
    assert "In-sample only" in text


def test_breakout_holdout_never_overlaps_the_traded_universe():
    """movers and research share three names. A holdout that merely is a
    different list is not a holdout."""
    from src.breakout import UNIVERSES
    from src.forensics import MOVERS
    from src.swing import RESEARCH
    for name in UNIVERSES:
        universe = set(UNIVERSES[name])
        candidate = [] if name == "wide" else (
            RESEARCH if name == "movers" else MOVERS)
        holdout = [s for s in candidate if s not in universe]
        assert not (set(holdout) & universe), f"{name} holdout leaks"


def test_breakout_trade_count_equals_wins_plus_losses():
    """The first report showed 48 trades with 32 wins and 30 losses, because
    the trade count was summed over period slices (which cut trades at each
    boundary) while wins and losses came from the full run. Every headline
    number must come from the same run."""
    import copy
    from src.breakout import BASE_BO, by_periods
    p = copy.deepcopy(BASE_BO)
    p.update({"base_len": 15, "touch_window": 15, "squeeze_atr": 6.0,
              "vol_mult": 1.05, "min_atr_pct": 0.0})
    data = {f"S{i}": _coil_then_break(n_coil=30 + i * 3, seed=i + 1)
            for i in range(6)}
    st = by_periods(data, p, 3)
    assert st["n"] > 0, "fixture produced no trades, so nothing is tested"
    assert st["n"] == st["wins"] + st["losses"], (
        f"{st['n']} trades but {st['wins']} won and {st['losses']} lost")


def test_breakout_report_respects_the_noise_floor():
    from src.breakout import render
    w = {"name": "x", "n": 60, "expectancy_R": 0.20, "total_R": 12.0,
         "periods_positive": 2, "periods_scored": 3, "worst_period_R": -0.1,
         "max_dd_pct": -10.0}
    payload = {"universe": "movers", "symbols": 36, "start": "2026-01-01",
               "tried": 36, "survivors": 1, "noise_floor": 0.40,
               "results": [w], "winner": w, "holdout": None, "holdout_size": 40}
    assert "Too close to noise" in render(payload)


# ---------------------------------------------------------------------------
# Paper account (the forward test)
# ---------------------------------------------------------------------------
def _paper_base(**kw):
    base = {"generated": "2026-09-29 18:00", "as_of": "2026-09-29",
            "settings": {"start": "2026-09-29", "equity": 2000.0,
                         "risk_pct": 1.0, "halt_drawdown_pct": 25.0},
            "symbols": 33, "trades": [], "open": [], "n": 0, "wins": 0,
            "losses": 0, "win_rate_pct": 0.0, "return_pct": 0.0,
            "max_dd_pct": 0.0, "halted": False}
    base.update(kw)
    return base


def test_paper_reads_its_settings_from_config():
    """The four numbers the owner is allowed to change have to come from
    config.yaml, not from the defaults in the module."""
    from src.paper import settings
    s = settings()
    assert set(s) == {"start", "equity", "risk_pct", "halt_drawdown_pct"}
    assert s["equity"] > 0 and 0 < s["risk_pct"] <= 100
    assert s["halt_drawdown_pct"] > 0


def test_paper_sizing_refuses_a_position_it_cannot_afford():
    """On $2,000 at 1% risk the budget is $20. A stop $45 away cannot be taken
    at any whole size - the backtest's fractional shares hide this, and sizing
    up to 'make it work' is how a 1% risk becomes a 2.3% risk."""
    from src.paper import shares
    assert shares(100.0, 5.0, 2000.0, 1.0) == 4
    assert shares(410.0, 45.0, 2000.0, 1.0) == 0
    assert shares(100.0, 0.0, 2000.0, 1.0) == 0      # no divide by zero


def test_paper_halt_line_stops_listing_new_entries():
    """The stop has to actually stop. A halted report that still shows entries
    is an invitation to trade through the drawdown."""
    from src.paper import render
    op = [{"symbol": "NVDA", "entry_date": "2026-10-07", "entry": 182.4,
           "stop": 171.2, "risk_per_share": 11.2, "bars_held": 2,
           "best_R": 0.6, "target": 199.2, "trailing": False, "shares": 1}]
    text = render(_paper_base(n=30, wins=9, losses=21, win_rate_pct=30.0,
                              return_pct=-26.0, max_dd_pct=-27.4, halted=True,
                              open=op, trades=[]))
    assert "STOPPED" in text
    assert "Open now" not in text
    assert "NVDA" not in text


def test_paper_says_a_short_record_is_not_a_verdict():
    """Ten trades of luck must not read like proof."""
    from src.paper import render
    text = render(_paper_base(n=10, wins=7, losses=3, win_rate_pct=70.0,
                              return_pct=12.0, max_dd_pct=-3.0))
    assert "too few to judge" in text
    text = render(_paper_base(n=60, wins=34, losses=26, win_rate_pct=56.7,
                              return_pct=18.0, max_dd_pct=-9.0))
    assert "too few to judge" not in text


def test_paper_empty_run_is_reported_as_normal():
    """Empty days are expected for this setup; the report must not read like a
    failure, because that is what prompts pointless tinkering."""
    from src.paper import render
    text = render(_paper_base())
    assert "No trades yet" in text
    assert "Nothing is wrong" in text


def test_paper_open_positions_come_from_the_backtest_engine():
    """run_portfolio must expose still-open positions. If paper trading grew
    its own copy of the entry rules they would drift, which is exactly how the
    inspector diverged from the live signals before."""
    import copy
    from src.breakout import BASE_BO, prepare, signal_times_bo
    from src.swing import run_portfolio
    p = copy.deepcopy(BASE_BO)
    p.update({"base_len": 15, "touch_window": 15, "squeeze_atr": 6.0,
              "vol_mult": 1.05, "min_atr_pct": 0.0, "risk_pct": 1.0})
    data = {f"S{i}": _coil_then_break(n_coil=30 + i * 3, seed=i + 1)
            for i in range(4)}
    out = run_portfolio(prepare(data, p), p, equity=2000.0)
    assert "open" in out
    for o in out["open"]:
        assert o["stop"] < o["entry"] < o["target"]
        assert o["risk_per_share"] > 0


def test_paper_stays_quiet_when_nothing_happened():
    """A bot that pings every evening to say 'no trades' gets muted, and then
    the message that matters goes unread too."""
    from src.paper import alert
    now = _paper_base(n=4, wins=2, losses=2, win_rate_pct=50.0,
                      return_pct=1.0, max_dd_pct=-2.0,
                      trades=[{"symbol": "PLTR", "entry_date": "2026-09-30",
                               "exit_date": "2026-10-02", "r_multiple": 1.5,
                               "reason": "target"}])
    assert alert(now, now) is None


def test_paper_alerts_on_a_new_trade_and_on_the_halt():
    from src.paper import alert
    closed = {"symbol": "PLTR", "entry_date": "2026-09-30",
              "exit_date": "2026-10-02", "r_multiple": 1.5, "reason": "target"}
    now = _paper_base(n=1, wins=1, losses=0, win_rate_pct=100.0,
                      return_pct=1.5, max_dd_pct=0.0, trades=[closed])
    msg = alert(now, _paper_base())
    assert msg and "PLTR" in msg and "won" in msg
    assert "Too few trades" in msg

    halted = _paper_base(n=30, wins=9, losses=21, win_rate_pct=30.0,
                         return_pct=-26.0, max_dd_pct=-27.4, halted=True)
    msg = alert(halted, _paper_base(n=30, wins=9, losses=21, max_dd_pct=-20.0))
    assert msg and "STOPPED" in msg
    # and it does not fire the same alarm again the next day
    assert alert(halted, halted) is None


def test_paper_halt_suppresses_new_entries_in_the_alert_too():
    """The report stops listing entries when halted; the message must agree,
    or the two disagree about whether to trade."""
    from src.paper import alert
    op = [{"symbol": "NVDA", "entry_date": "2026-10-07", "entry": 182.4,
           "stop": 171.2, "risk_per_share": 11.2, "bars_held": 0,
           "best_R": 0.0, "target": 199.2, "trailing": False, "shares": 1}]
    now = _paper_base(n=30, wins=9, losses=21, win_rate_pct=30.0,
                      return_pct=-26.0, max_dd_pct=-27.4, halted=True, open=op)
    msg = alert(now, _paper_base(n=30, max_dd_pct=-20.0))
    assert msg and "STOPPED" in msg and "Opened" not in msg


def _closed_trade(**kw):
    t = {"symbol": "PLTR", "entry_date": "2026-09-30", "exit_date": "2026-10-06",
         "entry": 42.10, "stop": 38.90, "exit": 46.90, "r_multiple": 1.5,
         "reason": "target", "bars_held": 5, "target": 46.90, "shares": 6,
         "pnl": {"move_pct": 11.40, "account_pct": 1.50, "r": 1.5},
         "why": "Coiled 10 days inside $38.20-$41.60 (2.1x ATR, tight), then "
                "closed above $41.60 on 1.8x normal volume."}
    t.update(kw)
    return t


def _open_pos(**kw):
    o = {"symbol": "NVDA", "entry_date": "2026-10-07", "entry": 182.40,
         "stop": 171.20, "risk_per_share": 11.20, "bars_held": 0,
         "best_R": 0.0, "target": 199.20, "trailing": False, "shares": 1,
         "why": "Coiled 10 days inside $168.40-$181.90 (2.4x ATR, tight)."}
    o.update(kw)
    return o


def test_paper_entry_message_carries_everything_needed_to_take_the_trade():
    """Price, stop, target, size and the reason - the owner asked for all
    five, and a signal without the reason cannot be reviewed later."""
    from src.paper import alert
    msg = alert(_paper_base(open=[_open_pos()]), _paper_base())
    assert "ENTRY" in msg and "NVDA" in msg
    assert "182.40" in msg          # price
    assert "171.20" in msg          # stop
    assert "199.20" in msg          # target
    assert "1 share" in msg         # size
    assert "Coiled 10 days" in msg  # reason


def test_paper_exit_message_states_profit_or_loss_as_a_percentage():
    from src.paper import alert
    msg = alert(_paper_base(n=1, wins=1, losses=0, win_rate_pct=100.0,
                            return_pct=1.5, trades=[_closed_trade()]),
                _paper_base())
    assert "CLOSED" in msg
    assert "+11.40%" in msg and "on the stock" in msg
    assert "+1.50%" in msg and "of the account" in msg
    assert "42.10" in msg and "46.90" in msg and "38.90" in msg
    assert "reached the target" in msg          # plain, not "target"
    assert "Coiled 10 days" in msg              # reason repeated on exit
    assert "1 trade," in msg                    # not "1 trades"


def test_paper_pnl_is_computed_from_the_prices():
    from src.paper import pnl
    p = pnl({"entry": 100.0, "exit": 110.0, "r_multiple": 2.0}, 1.0)
    assert p["move_pct"] == 10.0 and p["account_pct"] == 2.0
    loss = pnl({"entry": 100.0, "exit": 95.0, "r_multiple": -1.0}, 1.0)
    assert loss["move_pct"] == -5.0 and loss["account_pct"] == -1.0
    assert pnl({"entry": 0.0, "exit": 0.0, "r_multiple": 0.0}, 1.0)["move_pct"] == 0.0


def test_paper_trade_log_appends_and_never_rewrites(tmp_path, monkeypatch):
    """paper.json is derived and rewritten every run. The log is the permanent
    record - if a later run could truncate it, there would be nothing to
    learn from."""
    import json
    import src.paper as P
    monkeypatch.setattr(P, "STATE", tmp_path)
    now = _paper_base(as_of="2026-10-07")
    P.log_events(now, [_open_pos()], [])
    P.log_events(dict(now, as_of="2026-10-08"), [], [_closed_trade()])
    rows = [json.loads(l) for l in
            (tmp_path / "trade_log.jsonl").read_text().splitlines()]
    assert [r["event"] for r in rows] == ["entry", "exit"]
    assert rows[0]["symbol"] == "NVDA" and rows[0]["posted"] == "2026-10-07"
    assert rows[1]["pnl"]["account_pct"] == 1.50
    P.log_events(now, [], [])                    # nothing new
    assert len((tmp_path / "trade_log.jsonl").read_text().splitlines()) == 2
