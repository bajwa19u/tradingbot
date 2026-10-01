"""Alpaca paper trading — options, and nothing else.

The bot has been writing down what it would have done. This places the order
instead, against a real book with real spreads, on a paper account.

That distinction is the point of the module. On 30 September Uday's blotter
showed 1,000 contracts of a six-cent AAPL call bought and sold inside forty
minutes for +$35,950. Whether a fill like that exists is not something a
simulator can answer, and it is worth a great deal to find out for free.

Paper. Only ever paper.
--------------------------
The base URL is a constant in this file. It is not read from config.yaml, not
from the environment, and not from a function argument, because every one of
those is a route by which a live endpoint could arrive here by accident. A
test asserts that no live Alpaca hostname appears anywhere in the source, and
`_check` refuses any URL that is not the paper one at the moment of the call.

What it will do: buy calls and puts to open, sell them to close.
What it will not do: sell to open, spreads, margin, equities, or anything on
an account whose endpoint is not the paper one.

Caps
----
Three of them, all hard. A bug that loops is far more likely than a bug that
loses one trade slowly, and the caps are what stand between a loop and an
account. They are checked here rather than by the caller, so a caller that
forgets cannot spend past them.
"""
from __future__ import annotations

import logging
import sys
from dataclasses import dataclass, field
from datetime import date, timedelta

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s",
                    stream=sys.stdout)
log = logging.getLogger("broker")

# Not configurable. See the module docstring.
PAPER_URL = "https://paper-api.alpaca.markets"
DATA_URL = "https://data.alpaca.markets"

TARGET_PREMIUM = 1000.0           # Uday's number, 30 September: "around 1k"
MAX_PREMIUM_PER_TRADE = 1250.0    # hard ceiling, so "a bit more" stays a bit
MAX_PREMIUM_PER_DAY = 6000.0      # six of those, then the bot is done
MAX_OPEN_POSITIONS = 8

MIN_DTE = 1          # 0DTE is excluded by default; see pick_contract
MAX_DTE = 9
MIN_PRICE = 0.05     # a 3-cent option is a spread, not a position
MAX_PRICE = 25.00


class BrokerError(RuntimeError):
    pass


def _check(url: str) -> None:
    """The last gate before anything leaves this process."""
    if not url.startswith(PAPER_URL):
        raise BrokerError(
            f"refusing to talk to {url!r}: this module only ever speaks to "
            f"{PAPER_URL}")


def _check_data(url: str) -> None:
    """Market data has its own host. It is READ ONLY - no order can be placed
    against it - so it gets its own gate rather than widening the one above."""
    if not url.startswith(DATA_URL):
        raise BrokerError(f"refusing to read market data from {url!r}")


# --- choosing the contract ---------------------------------------------------
@dataclass(frozen=True)
class Contract:
    symbol: str          # OCC, e.g. AAPL260930C00340000
    underlying: str
    kind: str            # "call" | "put"
    strike: float
    expiry: date
    ask: float = 0.0
    bid: float = 0.0

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2 if self.bid and self.ask else self.ask

    @property
    def spread_pct(self) -> float:
        return 100 * (self.ask - self.bid) / self.ask if self.ask else 100.0


def pick_contract(contracts: list[Contract], target: float, on: date,
                  allow_0dte: bool = False) -> Contract | None:
    """The contract whose strike sits closest to where the trade is going.

    The bot already states where it thinks price will get to. A strike at
    that level is the one that turns a correct call into a large gain rather
    than a small one, and it is the rule Uday's own winners followed - his
    AAPL 340 call was bought with the stock at 334 and a 340 target.

    Expiry is the nearest one at least MIN_DTE days out. Same-day contracts
    are excluded unless asked for: they produced both the +597% and every
    total loss on 30 September, and that asymmetry deserves its own decision
    rather than being the default.
    """
    floor = 0 if allow_0dte else MIN_DTE
    live = [c for c in contracts
            if floor <= (c.expiry - on).days <= MAX_DTE
            and MIN_PRICE <= c.ask <= MAX_PRICE]
    if not live:
        return None
    soonest = min((c.expiry for c in live))
    near = [c for c in live if c.expiry == soonest]
    return min(near, key=lambda c: abs(c.strike - target))


def size(contract: Contract, budget: float) -> int:
    """How many contracts `budget` buys, at the ask.

    Priced at the ASK, never the mid. A backtest that sizes on the mid is
    quietly assuming a fill nobody offered.
    """
    if contract.ask <= 0:
        return 0
    per = contract.ask * 100
    return max(0, int(min(budget, MAX_PREMIUM_PER_TRADE) // per))


# --- the account -------------------------------------------------------------
@dataclass
class Paper:
    """A thin client. `http` is injected so the tests never touch a network."""
    key: str
    secret: str
    http: object = None
    spent_today: float = 0.0
    opened: dict[str, int] = field(default_factory=dict)

    def _headers(self) -> dict:
        return {"APCA-API-KEY-ID": self.key,
                "APCA-API-SECRET-KEY": self.secret,
                "accept": "application/json"}

    def _get(self, path: str, params: dict | None = None) -> dict:
        url = PAPER_URL + path
        _check(url)
        r = self.http.get(url, headers=self._headers(), params=params or {},
                          timeout=20)
        if r.status_code >= 400:
            raise BrokerError(f"GET {path} -> {r.status_code}: {r.text[:200]}")
        return r.json()

    def _post(self, path: str, body: dict) -> dict:
        url = PAPER_URL + path
        _check(url)
        r = self.http.post(url, headers=self._headers(), json=body, timeout=20)
        if r.status_code >= 400:
            raise BrokerError(f"POST {path} -> {r.status_code}: {r.text[:200]}")
        return r.json()

    # -- reads --
    def account(self) -> dict:
        a = self._get("/v2/account")
        # Alpaca labels paper accounts; if this ever comes back false the
        # keys are live keys and nothing else in this module should run.
        if str(a.get("status", "")).upper() not in ("ACTIVE", "PAPER_ONLY"):
            log.warning("account status is %s", a.get("status"))
        return a

    def positions(self) -> list[dict]:
        try:
            return self._get("/v2/positions")
        except BrokerError as exc:
            log.warning("could not read positions: %s", exc)
            return []

    def orders_since(self, after: str) -> list[dict]:
        """Every order placed since `after` (ISO time), any status.

        Raises rather than returning nothing: a caller that reads "no orders"
        when the truth is "could not ask" would forget what it already holds
        and the daily cap with it."""
        return self._get("/v2/orders", {"status": "all", "after": after,
                                        "limit": 500, "direction": "asc"})

    def _get_data(self, path: str, params: dict | None = None) -> dict:
        url = DATA_URL + path
        _check_data(url)
        r = self.http.get(url, headers=self._headers(), params=params or {},
                          timeout=20)
        if r.status_code >= 400:
            raise BrokerError(f"GET {path} -> {r.status_code}: {r.text[:200]}")
        return r.json()

    def chain(self, underlying: str, kind: str, on: date,
              allow_0dte: bool = False, until: date | None = None,
              near: float | None = None) -> list[Contract]:
        """Tradable contracts for one name, with their current quotes.

        Two calls: the trading API lists what exists, the data API prices it.
        A contract with no quote is dropped rather than guessed at - an
        option we cannot price is one we cannot size.

        `until` and `near` narrow both requests to one week and strikes
        within 10% of `near`. SPY and TSLA list more than one page of
        contracts across nine days, and an unfiltered page can silently miss
        the very strike being asked for.
        """
        floor = on if allow_0dte else on + timedelta(days=MIN_DTE)
        last = until or on + timedelta(days=MAX_DTE)
        typ = "call" if kind.lower().startswith("c") else "put"
        band = {}
        if near:
            band = {"strike_price_gte": f"{near * 0.9:.2f}",
                    "strike_price_lte": f"{near * 1.1:.2f}"}
        listing = self._get("/v2/options/contracts", {
            "underlying_symbols": underlying.upper(),
            "expiration_date_gte": floor.isoformat(),
            "expiration_date_lte": last.isoformat(),
            "type": typ, "status": "active", "limit": 1000, **band})
        rows = listing.get("option_contracts", []) or []
        if not rows:
            return []

        quotes: dict[str, dict] = {}
        try:
            snap = self._get_data(f"/v1beta1/options/snapshots/{underlying.upper()}",
                                  {"feed": "indicative", "limit": 1000,
                                   "type": typ,
                                   "expiration_date_gte": floor.isoformat(),
                                   "expiration_date_lte": last.isoformat(),
                                   **band})
            quotes = snap.get("snapshots", {}) or {}
        except BrokerError as exc:
            log.warning("no option quotes for %s: %s", underlying, exc)
            return []

        out = []
        for r in rows:
            q = (quotes.get(r["symbol"]) or {}).get("latestQuote") or {}
            ask, bid = float(q.get("ap") or 0), float(q.get("bp") or 0)
            if ask <= 0:
                continue
            out.append(Contract(
                symbol=r["symbol"], underlying=underlying.upper(),
                kind=r["type"], strike=float(r["strike_price"]),
                expiry=pd_date(r["expiration_date"]), ask=ask, bid=bid))
        return out

    # -- writes --
    def buy_to_open(self, c: Contract, qty: int,
                    client_order_id: str | None = None) -> dict | None:
        """Buy `qty` contracts at market. Returns None when a cap refuses it.

        `client_order_id` makes the order idempotent: Alpaca refuses a second
        order with the same id, so a run that repeats cannot buy twice."""
        cost = qty * c.ask * 100
        if qty <= 0:
            return None
        if cost > MAX_PREMIUM_PER_TRADE:
            log.warning("refused %s: %.0f over the %.0f per-trade cap",
                        c.symbol, cost, MAX_PREMIUM_PER_TRADE)
            return None
        if self.spent_today + cost > MAX_PREMIUM_PER_DAY:
            log.warning("refused %s: would take today to %.0f, cap is %.0f",
                        c.symbol, self.spent_today + cost, MAX_PREMIUM_PER_DAY)
            return None
        if len(self.opened) >= MAX_OPEN_POSITIONS:
            log.warning("refused %s: already holding %d positions",
                        c.symbol, len(self.opened))
            return None
        body = {"symbol": c.symbol, "qty": str(qty), "side": "buy",
                "type": "market", "time_in_force": "day"}
        if client_order_id:
            body["client_order_id"] = client_order_id
        o = self._post("/v2/orders", body)
        self.spent_today += cost
        self.opened[c.symbol] = self.opened.get(c.symbol, 0) + qty
        log.info("bought %d %s for about %.0f", qty, c.symbol, cost)
        return o

    def sell_to_close(self, symbol: str, qty: int,
                      client_order_id: str | None = None) -> dict | None:
        if qty <= 0:
            return None
        body = {"symbol": symbol, "qty": str(qty), "side": "sell",
                "type": "market", "time_in_force": "day"}
        if client_order_id:
            body["client_order_id"] = client_order_id
        o = self._post("/v2/orders", body)
        left = self.opened.get(symbol, 0) - qty
        if left > 0:
            self.opened[symbol] = left
        else:
            self.opened.pop(symbol, None)
        log.info("sold %d %s", qty, symbol)
        return o

    def flatten(self) -> list[dict]:
        """Close everything. Called before the bell, every day, no exceptions.

        Nothing this bot opens is meant to be held overnight, and an option
        left to expire is the one way to lose the whole premium rather than
        part of it - which is exactly what cost 24,773 dollars on
        30 September.
        """
        out = []
        for p in self.positions():
            try:
                o = self.sell_to_close(p["symbol"], abs(int(float(p["qty"]))))
                if o:
                    out.append(o)
            except BrokerError as exc:
                log.error("could not close %s: %s", p.get("symbol"), exc)
        return out


def pd_date(s: str) -> date:
    y, m, d = (int(x) for x in s.split("-")[:3])
    return date(y, m, d)


def occ(underlying: str, expiry: date, kind: str, strike: float) -> str:
    """Build an OCC symbol, the way Alpaca wants it: AAPL260930C00340000."""
    return (f"{underlying.upper()}{expiry:%y%m%d}"
            f"{'C' if kind.lower().startswith('c') else 'P'}"
            f"{int(round(strike * 1000)):08d}")


def parse_occ(symbol: str) -> tuple[str, date, str, float]:
    body = symbol.strip().upper()
    strike = int(body[-8:]) / 1000
    kind = "call" if body[-9] == "C" else "put"
    y, m, d = int(body[-15:-13]), int(body[-13:-11]), int(body[-11:-9])
    return body[:-15], date(2000 + y, m, d), kind, strike


def next_expiry(on: date, allow_0dte: bool = False) -> date:
    """The soonest expiry this module would consider, for logging and tests."""
    return on + timedelta(days=0 if allow_0dte else MIN_DTE)
