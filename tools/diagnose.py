"""Alpaca connectivity diagnostic.

Prints exactly what the data API returns, with no secrets in the output, so a
failing run can be understood from the committed log instead of guessing at
exit codes.

    python -m tools.diagnose
"""
from __future__ import annotations

import json
import os
import sys
from datetime import date, timedelta

import requests

DATA = "https://data.alpaca.markets"


def mask(value: str) -> str:
    if not value:
        return "(empty)"
    return f"{value[:4]}…{value[-2:]} (len {len(value)})"


def main() -> int:
    key = os.environ.get("ALPACA_API_KEY", "")
    secret = os.environ.get("ALPACA_API_SECRET", "")

    print("=" * 62)
    print("ALPACA DIAGNOSTIC")
    print("=" * 62)
    print(f"ALPACA_API_KEY    : {mask(key)}")
    print(f"ALPACA_API_SECRET : {mask(secret)}")
    if not (key and secret):
        print("\nFAIL: credentials missing from the environment.")
        return 1

    headers = {
        "APCA-API-KEY-ID": key,
        "APCA-API-SECRET-KEY": secret,
        "accept": "application/json",
    }

    start = (date.today() - timedelta(days=20)).isoformat()
    checks = [
        ("daily bars, iex",
         f"{DATA}/v2/stocks/bars",
         {"symbols": "AAPL", "timeframe": "1Day", "start": start,
          "limit": 5, "feed": "iex"}),
        ("5-minute bars, iex",
         f"{DATA}/v2/stocks/bars",
         {"symbols": "AAPL", "timeframe": "5Min", "start": start,
          "limit": 5, "feed": "iex"}),
        ("5-minute bars, sip",
         f"{DATA}/v2/stocks/bars",
         {"symbols": "AAPL", "timeframe": "5Min", "start": start,
          "limit": 5, "feed": "sip"}),
        ("5-minute bars, no feed param",
         f"{DATA}/v2/stocks/bars",
         {"symbols": "AAPL", "timeframe": "5Min", "start": start, "limit": 5}),
        ("most-active screener",
         f"{DATA}/v1beta1/screener/stocks/most-actives",
         {"by": "volume", "top": 3}),
    ]

    ok_any = False
    for label, url, params in checks:
        print(f"\n--- {label} ---")
        print(f"    params: {json.dumps(params)}")
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=30)
        except Exception as exc:  # noqa: BLE001
            print(f"    EXCEPTION: {type(exc).__name__}: {exc}")
            continue
        print(f"    HTTP {resp.status_code}")
        body = resp.text[:600]
        print(f"    body: {body}")
        if resp.status_code == 200:
            try:
                payload = resp.json()
                bars = (payload.get("bars") or {}).get("AAPL")
                if bars is not None:
                    print(f"    -> {len(bars)} AAPL bars returned")
                    if bars:
                        ok_any = True
            except Exception:
                pass

    print("\n" + "=" * 62)
    if ok_any:
        print("RESULT: at least one bars request returned data.")
        return 0
    print("RESULT: no bars request returned data. See the HTTP codes above:")
    print("  401/403 -> keys wrong, or the plan does not cover that feed")
    print("  200 with empty bars -> the date range has no history on that feed")
    return 1


if __name__ == "__main__":
    sys.exit(main())
