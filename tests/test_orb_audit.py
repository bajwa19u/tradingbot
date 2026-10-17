"""The audit's own rules: the adoption check rejects a smaller loss, and the
SPY trend it filters on is known before the open."""
import datetime as dt

import numpy as np

from src import orb_audit as oa


def _s(n, avg, pf=1.0, t=0.0, no_top2=None):
    return dict(n=n, avg=avg, pf=pf, t=t, no_top2=avg if no_top2 is None else no_top2)


def _res(train, val, tv):
    return {"train": train, "val": val, "train+val": tv}


def test_adopt_rejects_a_smaller_loss():
    """The all-negative case first: better than a losing baseline is not an edge."""
    b = _res(_s(300, -0.10, 0.8), _s(200, -0.10, 0.8), _s(500, -0.10, 0.8))
    c = _res(_s(250, -0.01, 0.95), _s(150, -0.02, 0.95), _s(400, -0.015, 0.95, t=-0.3))
    fails = oa.adopt(b, c, b, c)
    assert any(x.startswith("6:") for x in fails)


def test_adopt_needs_the_noise_floor():
    b = _res(_s(300, 0.0, 1.0), _s(200, 0.0, 1.0), _s(500, 0.0, 1.0))
    c = _res(_s(300, 0.05, 1.1), _s(200, 0.05, 1.1), _s(500, 0.05, 1.1, t=1.0))
    assert any(x.startswith("7:") for x in oa.adopt(b, c, b, c))
    c["train+val"]["t"] = oa.FLOOR + 0.1
    assert oa.adopt(b, c, b, c) == []


class _Day:
    def __init__(self, close):
        self.c = np.array([close])


def test_spy_trend_uses_prior_sessions_only():
    days = [dt.date(2026, 1, 1) + dt.timedelta(days=i) for i in range(30)]
    closes = [100.0] * 29 + [1.0]                    # a crash on the last day
    D = {"SPY": {d: _Day(c) for d, c in zip(days, closes)}}
    reg = oa.spy_trend(D, days)
    # the crash day itself cannot know its own close
    assert reg[days[-1]] == "short" or reg[days[-1]] == "long"
    closes2 = closes[:-1] + [10_000.0]
    reg2 = oa.spy_trend({"SPY": {d: _Day(c) for d, c in zip(days, closes2)}}, days)
    assert reg[days[-1]] == reg2[days[-1]]


def test_audit_baseline_is_the_live_rule():
    from src import orb_live
    assert oa.BASE == orb_live.RULES["bigtech"][0]
