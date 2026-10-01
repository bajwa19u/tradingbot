"""Does the Alpaca paper account actually work? Ask before the bell, not after.

The order code has never spoken to a broker. The first time it does should
not be 09:31 with signals firing, so this runs at 09:00, proves every link in
the chain, and says plainly in Discord whether the bot can trade today.

It checks, in order:

  1. the keys authenticate at all
  2. the account is a PAPER account
  3. options are enabled on it, at a level that can buy calls and puts
  4. a real option chain comes back for a real symbol, with real quotes
  5. contract selection picks something sensible from that chain
  6. the caps are what they should be

It does NOT place an order. There is nothing to learn from a 09:00 fill that
the 09:31 one will not teach, and an order placed here is a position nobody
asked for. The one thing this cannot prove is that a fill happens; everything
short of that, it proves.

Exit code 0 means the bot may trade. Anything else means it may not, and the
live job is expected to check this before it sends anything to a broker.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import date

from . import autotrade as at
from . import broker as bk
from . import discord_msg as dm
from .config import Credentials

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s",
                    stream=sys.stdout)
log = logging.getLogger("smoke")

PROBE = "AAPL"          # liquid, always has a chain, cheap to ask about


class Check:
    def __init__(self) -> None:
        self.rows: list[tuple[bool, str, str]] = []

    def add(self, ok: bool, name: str, detail: str = "") -> bool:
        self.rows.append((ok, name, detail))
        log.info("%s %s %s", "PASS" if ok else "FAIL", name, detail)
        return ok

    @property
    def passed(self) -> bool:
        return all(ok for ok, _, _ in self.rows)

    def message(self, when: str) -> str:
        head = ("✅ **Alpaca paper — ready**" if self.passed
                else "🛑 **Alpaca paper — NOT ready**")
        lines = [f"{'✅' if ok else '❌'} {name}"
                 + (f" · _{d}_" if d else "") for ok, name, d in self.rows]
        tail = ("" if self.passed else
                "\n\n**Paper orders may fail until this is fixed.** Discord signals "
                "are unaffected.")
        return f"{head}  ·  {when}\n" + "\n".join(lines) + tail


def keys() -> tuple[str, str]:
    """Paper keys, falling back to the data keys only if they are separate."""
    return (os.environ.get("ALPACA_PAPER_KEY", ""),
            os.environ.get("ALPACA_PAPER_SECRET", ""))


def run(on: date | None = None) -> Check:
    on = on or date.today()
    c = Check()
    key, secret = keys()
    if not c.add(bool(key and secret), "keys present",
                 "ALPACA_PAPER_KEY / ALPACA_PAPER_SECRET"):
        return c

    import requests
    p = bk.Paper(key=key, secret=secret, http=requests)

    try:
        acct = p.account()
    except Exception as exc:                                   # noqa: BLE001
        c.add(False, "keys authenticate", str(exc)[:120])
        return c
    c.add(True, "keys authenticate", f"account {acct.get('account_number', '?')}")

    # Alpaca does not label paper accounts in a single field, so this leans on
    # the endpoint the module is locked to rather than trusting a flag.
    c.add(bk.PAPER_URL.startswith("https://paper-api."),
          "endpoint is the paper one", bk.PAPER_URL)

    lvl = acct.get("options_trading_level")
    c.add(bool(lvl) and int(lvl) >= 1, "options enabled",
          f"level {lvl}" if lvl else "no options level on this account")

    # The same request, the same contract and the same sizing the auto-trader
    # uses. On 1 October this probed a deep in-the-money call the bot would
    # never buy, priced it over the cap, and reported "not ready" while every
    # real check had passed.
    try:
        chain = p.chain(PROBE, "call", on, allow_0dte=True,
                        until=at.this_friday(on))
    except Exception as exc:                                   # noqa: BLE001
        c.add(False, f"{PROBE} option chain", str(exc)[:120])
        return c
    c.add(len(chain) > 0, f"{PROBE} option chain",
          f"{len(chain)} contracts priced")

    if chain:
        spot = last_price(p, PROBE) or sorted(x.strike for x in chain)[len(chain) // 2]
        pick = at.choose(chain, "call", spot, on)
        c.add(pick is not None, "contract selection",
              f"{pick.symbol} at {pick.ask:.2f}" if pick else "nothing suitable")
        if pick:
            n = at.contracts_for(pick)
            c.add(n > 0, "sizing",
                  f"{n} contracts for about "
                  f"{n * pick.ask * 100:.0f} at the ask")

    c.add(bk.MAX_PREMIUM_PER_TRADE == 1250.0
          and bk.MAX_PREMIUM_PER_DAY is None
          and bk.MAX_OPEN_POSITIONS == 30,
          "caps unchanged", "about 1,000 a trade (1,250 max) · no daily limit · 30 positions")
    return c


def last_price(p: bk.Paper, symbol: str) -> float:
    """The stock's last trade, or 0 when the data API will not say."""
    try:
        r = p._get_data(f"/v2/stocks/{symbol}/trades/latest", {"feed": "iex"})
        return float((r.get("trade") or {}).get("p") or 0)
    except Exception:                                          # noqa: BLE001
        return 0.0


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true",
                    help="print the result instead of sending it")
    return ap.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    c = run()
    when = "pre-market check"
    text = c.message(when)
    print("\n" + text)
    if not args.dry_run:
        hook = Credentials.from_env().discord_webhook
        if hook:
            dm.post(hook, text)
        else:
            log.warning("no Discord webhook set — result not sent")
    return 0 if c.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
