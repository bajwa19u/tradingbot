"""How much a given break is worth, on the only evidence that survived.

Every signal carries a confidence level. This module decides it, and the
levels are not invented - each one is a bucket that was measured on 3,388
breaks across 97 trading days, on an explore split and then on a holdout the
filter was not chosen on (reports/orb_autopsy.md).

The two inputs
--------------
WITH THE GAP. Whether the break runs the same way the stock gapped overnight
- long after a gap up, short after a gap down. Of everything measured, this
was the only thing that separated outcomes on both splits, and it separated
them hard: with the gap +53.4% over the period, against it -90.3%.

THE CROWD. How many other names broke the same way within ten minutes. On its
own it is weak. Combined with the gap it is the best bucket there is.

What the buckets actually did
-----------------------------
                                      explore              holdout
  HIGH   with the gap, crowd of 5+    51.2% / +28.6%       52.1% / +34.1%
  MEDIUM with the gap, crowd under 5  46.7% /  -2.2%       38.7% /  -7.1%
  LOW    against the gap              ~46%  / heavy loss   ~46%  / heavy loss

Read that twice before trusting a medium. The whole of the gap edge lives in
the crowd subset: with the gap and nobody else moving, the rule lost money on
both splits. HIGH is the only bucket that has ever made money here, and the
strategy as a whole is down -36.9% over the period it was measured on.

The medium row is arithmetic rather than a printed result - the autopsy
reports "with the gap" and "with the gap AND crowd of 5+", and medium is what
is left when you take the second from the first. Profit is a sum of per-trade
percentages so it subtracts cleanly; the win counts round to the nearest
trade, so treat them as close rather than exact.

A confidence level is a ranking, not a promise. It says this break belongs to
a group that did better than the others, on 97 days of one summer. It does
not say the trade will win.
"""
from __future__ import annotations

CROWD = 5                       # names breaking the same way within 10 min

HIGH, MEDIUM, LOW = "high", "medium", "low"

LABEL = {HIGH: "🟩 HIGH", MEDIUM: "🟨 MED", LOW: "🟥 LOW"}

# Why each level was given, short enough to sit on a Discord card.
WHY = {
    HIGH: "with the gap, {cohort} names breaking together",
    MEDIUM: "with the gap, but only {cohort} names moving",
    LOW: "against the overnight gap",
}


def minute_of(hhmm: str) -> int:
    """Minutes since the bell. Negative before it."""
    return int(hhmm[:2]) * 60 + int(hhmm[3:5]) - (9 * 60 + 30)


def gap_pct(open_px: float, prev_close: float) -> float:
    """Overnight gap as a percentage of yesterday's close."""
    if not prev_close:
        return 0.0
    return (open_px - prev_close) / prev_close * 100


def with_gap(gap: float, side: str) -> bool:
    """Does the break run the same way the stock gapped?"""
    return (gap > 0) == (side == "long")


def level(trade: dict) -> str | None:
    """high, medium or low - or None when the inputs are not there.

    Returning None rather than guessing matters: a card that says "medium"
    because a field was missing is worse than one that says nothing, since
    the first is a claim and the second is an absence.
    """
    if "with_gap" not in trade or trade.get("cohort") is None:
        return None
    if not trade["with_gap"]:
        return LOW
    return HIGH if trade["cohort"] >= CROWD else MEDIUM


def note(trade: dict) -> str:
    """The level and its one-line reason, for the card."""
    lv = level(trade)
    if lv is None:
        return ""
    return f"{LABEL[lv]} · {WHY[lv].format(cohort=trade.get('cohort', 0))}"


def tag(trades: list[dict], window_min: int = 10) -> list[dict]:
    """Fill in `cohort` across one morning's trades, in place.

    Has to be done over the whole universe for the day rather than per
    symbol, because the question is how many OTHER names were breaking at the
    same time. Trades without a numeric `minute` are left alone and will
    simply carry no confidence level.
    """
    timed = [t for t in trades if isinstance(t.get("minute"), (int, float))]
    for t in timed:
        t["cohort"] = sum(1 for o in timed
                          if o["side"] == t["side"]
                          and abs(o["minute"] - t["minute"]) <= window_min)
    return trades
