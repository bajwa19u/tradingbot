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
    assert sig.pattern == "hammer"
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
