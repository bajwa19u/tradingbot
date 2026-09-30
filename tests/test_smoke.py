"""The pre-market check, with no broker anywhere near it.

What matters here is that a FAILURE is loud and returns a non-zero exit code,
because the live job is meant to refuse to trade on that. A check that fails
quietly is worse than no check.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import pytest

from src import broker as bk
from src import smoke as sm

TODAY = date(2026, 10, 1)


@dataclass
class Reply:
    status_code: int = 200
    payload: object = field(default_factory=dict)

    @property
    def text(self):
        return str(self.payload)

    def json(self):
        return self.payload


@dataclass
class FakeHTTP:
    level: int = 2
    contracts: list = field(default_factory=list)
    quotes: dict = field(default_factory=dict)
    fail: str = ""

    def get(self, url, headers=None, params=None, timeout=None):
        if self.fail and self.fail in url:
            return Reply(500, {"message": "nope"})
        if "/v2/account" in url:
            return Reply(200, {"account_number": "PA123",
                               "options_trading_level": self.level})
        if "/v2/options/contracts" in url:
            return Reply(200, {"option_contracts": self.contracts})
        if "/options/snapshots/" in url:
            return Reply(200, {"snapshots": self.quotes})
        return Reply(200, {})

    def post(self, url, headers=None, json=None, timeout=None):
        raise AssertionError("the pre-market check must never place an order")


def chain_of(strikes, exp="2026-10-02", ask=1.50):
    cs, qs = [], {}
    for s in strikes:
        sym = bk.occ("AAPL", bk.pd_date(exp), "call", s)
        cs.append({"symbol": sym, "type": "call", "strike_price": str(s),
                   "expiration_date": exp})
        qs[sym] = {"latestQuote": {"ap": ask, "bp": ask - 0.10}}
    return cs, qs


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("ALPACA_PAPER_KEY", "k")
    monkeypatch.setenv("ALPACA_PAPER_SECRET", "s")


def with_http(monkeypatch, http):
    import types
    monkeypatch.setitem(__import__("sys").modules, "requests",
                        types.SimpleNamespace(get=http.get, post=http.post))


# --- the happy path ----------------------------------------------------------
def test_everything_healthy_passes_and_says_ready(env, monkeypatch):
    cs, qs = chain_of([330, 335, 340, 345])
    with_http(monkeypatch, FakeHTTP(contracts=cs, quotes=qs))
    c = sm.run(TODAY)
    assert c.passed, [r for r in c.rows if not r[0]]
    msg = c.message("pre-market check")
    assert "ready" in msg and "NOT ready" not in msg


def test_a_healthy_check_exits_zero(env, monkeypatch):
    cs, qs = chain_of([330, 340, 350])
    with_http(monkeypatch, FakeHTTP(contracts=cs, quotes=qs))
    assert sm.main(["--dry-run"]) == 0


# --- the failures that must stop trading ------------------------------------
def test_missing_keys_fail_immediately(monkeypatch):
    monkeypatch.delenv("ALPACA_PAPER_KEY", raising=False)
    monkeypatch.delenv("ALPACA_PAPER_SECRET", raising=False)
    c = sm.run(TODAY)
    assert not c.passed
    assert len(c.rows) == 1, "it should stop rather than keep probing"


def test_options_disabled_is_a_failure(env, monkeypatch):
    cs, qs = chain_of([340])
    with_http(monkeypatch, FakeHTTP(level=0, contracts=cs, quotes=qs))
    c = sm.run(TODAY)
    assert not c.passed
    assert any("options enabled" in n for ok, n, _ in c.rows if not ok)


def test_an_empty_chain_is_a_failure(env, monkeypatch):
    with_http(monkeypatch, FakeHTTP(contracts=[], quotes={}))
    c = sm.run(TODAY)
    assert not c.passed


def test_unquoted_contracts_do_not_count_as_a_chain(env, monkeypatch):
    cs, _ = chain_of([330, 340])
    with_http(monkeypatch, FakeHTTP(contracts=cs, quotes={}))
    c = sm.run(TODAY)
    assert not c.passed, "contracts with no price cannot be sized"


def test_a_failure_exits_non_zero(env, monkeypatch):
    with_http(monkeypatch, FakeHTTP(level=0, contracts=[], quotes={}))
    assert sm.main(["--dry-run"]) == 1


def test_a_failing_message_says_no_orders_will_be_placed(env, monkeypatch):
    with_http(monkeypatch, FakeHTTP(level=0, contracts=[], quotes={}))
    msg = sm.run(TODAY).message("pre-market check")
    assert "NOT ready" in msg
    assert "No orders will be placed" in msg
    assert "Discord signals are unaffected" in msg


def test_a_dead_account_endpoint_fails_gracefully(env, monkeypatch):
    with_http(monkeypatch, FakeHTTP(fail="/v2/account"))
    c = sm.run(TODAY)
    assert not c.passed


# --- it must never trade -----------------------------------------------------
def test_the_check_never_places_an_order(env, monkeypatch):
    cs, qs = chain_of([330, 340, 350])
    http = FakeHTTP(contracts=cs, quotes=qs)
    with_http(monkeypatch, http)
    sm.run(TODAY)          # FakeHTTP.post raises if it is ever called


def test_the_caps_check_notices_if_someone_raises_them(env, monkeypatch):
    cs, qs = chain_of([340])
    with_http(monkeypatch, FakeHTTP(contracts=cs, quotes=qs))
    monkeypatch.setattr(bk, "MAX_PREMIUM_PER_TRADE", 50_000.0)
    c = sm.run(TODAY)
    assert not c.passed
    assert any("caps" in n for ok, n, _ in c.rows if not ok)
