"""Company fundamentals, as they were known on a given day.

The pre-earnings screen has to answer a question about the past: on 31
December 2022, looking only at what had actually been filed by then, was this
company growing and profitable? Answering it with today's data would be
cheating in the quietest possible way - a company that fell apart in 2024
would still look wonderful in the 2022 screen, and the backtest that followed
would be describing a world that did not exist.

So every number here carries the date it was FILED, and every lookup takes an
as-of date and ignores anything filed after it. That is the whole point of
this module; the rest is arithmetic.

Where it comes from
-------------------
SEC XBRL company facts: https://data.sec.gov/api/xbrl/companyfacts/CIK{n}.json

Straight out of the 10-Q and 10-K filings, free, no key, roughly fifteen
years deep, and it includes the filing date of every single fact. Yahoo and
the other free fundamental feeds give you today's restated view with no way
to ask what was known when, which makes them useless for this.

The awkward part: Q4
--------------------
Companies file three 10-Qs and then a 10-K. The 10-K reports the full year,
not the fourth quarter, so a naive read of "quarterly revenue" has a hole in
it every December. Q4 is recovered by subtracting the three filed quarters
from the filed year, and only when all three are present and actually tile
the year - a guess dressed as a measurement is worse than a gap.
"""
from __future__ import annotations

import logging
import sys
from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s",
                    stream=sys.stdout)
log = logging.getLogger("fundamentals")

SEC_FACTS = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"

# Companies report revenue under whichever tag their accountants prefer, and
# several changed tag when ASC 606 came in around 2018. Tried in order; the
# first that yields a usable series wins.
REVENUE_TAGS = ("RevenueFromContractWithCustomerExcludingAssessedTax",
                "Revenues",
                "SalesRevenueNet",
                "RevenueFromContractWithCustomerIncludingAssessedTax")
INCOME_TAGS = ("NetIncomeLoss",)
EPS_TAGS = ("EarningsPerShareDiluted", "EarningsPerShareBasicAndDiluted")

QUARTER_DAYS = (80, 100)        # a filed "quarter" is about this long
YEAR_DAYS = (340, 380)


@dataclass(frozen=True)
class Fact:
    """One reported number, with the window it covers and when it was filed."""
    start: date
    end: date
    val: float
    filed: date

    @property
    def days(self) -> int:
        return (self.end - self.start).days


def _rows(blob: dict, tag: str, unit: str) -> list[Fact]:
    """Every duration fact for one tag, in the given unit."""
    node = blob.get("facts", {}).get("us-gaap", {}).get(tag)
    if not node:
        return []
    out = []
    for entry in node.get("units", {}).get(unit, []):
        # Instant facts (balance-sheet items) have no start; we only want
        # things measured over a period.
        if not entry.get("start") or not entry.get("end"):
            continue
        try:
            out.append(Fact(start=pd.Timestamp(entry["start"]).date(),
                            end=pd.Timestamp(entry["end"]).date(),
                            val=float(entry["val"]),
                            filed=pd.Timestamp(entry["filed"]).date()))
        except (TypeError, ValueError, KeyError):
            continue
    return out


def known_by(facts: list[Fact], as_of: date) -> dict[tuple[date, date], Fact]:
    """What each period looked like on `as_of`.

    Anything filed later is dropped outright. Where a period was filed more
    than once - restatements, amended filings - the most recent filing that
    still predates `as_of` wins, because that is what someone reading the
    filings that morning would have seen.
    """
    best: dict[tuple[date, date], Fact] = {}
    for f in facts:
        if f.filed > as_of:
            continue
        key = (f.start, f.end)
        prev = best.get(key)
        if prev is None or f.filed > prev.filed:
            best[key] = f
    return best


def _tiles(parts: list[Fact], whole: Fact) -> bool:
    """Do these quarters actually cover the year, end to end, no gaps?

    Filed periods rarely line up to the day - a quarter ending Saturday the
    28th is followed by one starting Monday the 30th - so a few days of slack
    is allowed at each seam, and nothing more.
    """
    if len(parts) != 3:
        return False
    ordered = sorted(parts, key=lambda f: f.start)
    if abs((ordered[0].start - whole.start).days) > 5:
        return False
    for a, b in zip(ordered, ordered[1:]):
        if not 0 <= (b.start - a.end).days <= 5:
            return False
    # The three quarters must stop roughly three months short of the year end.
    return 80 <= (whole.end - ordered[-1].end).days <= 100


def quarters(facts: list[Fact], as_of: date) -> dict[date, float]:
    """Quarterly values by period end, as known on `as_of`.

    Directly filed quarters are taken as they are. The missing fourth quarter
    of each year is recovered from the annual figure, and skipped entirely
    when the three filed quarters do not cleanly tile that year.
    """
    seen = known_by(facts, as_of).values()
    qs = {f.end: f for f in seen if QUARTER_DAYS[0] <= f.days <= QUARTER_DAYS[1]}
    years = [f for f in seen if YEAR_DAYS[0] <= f.days <= YEAR_DAYS[1]]

    out = {end: f.val for end, f in qs.items()}
    for yr in years:
        if yr.end in out:
            continue                    # Q4 was filed on its own; nothing to do
        inside = [f for f in qs.values()
                  if yr.start - timedelta(days=5) <= f.start
                  and f.end <= yr.end - timedelta(days=60)]
        if _tiles(inside, yr):
            out[yr.end] = yr.val - sum(f.val for f in inside)
    return dict(sorted(out.items()))


def ttm(qs: dict[date, float]) -> dict[date, float]:
    """Trailing twelve months at each quarter end.

    Only computed where the four quarters are genuinely consecutive - a
    company with a gap in its filings gets no TTM at that point rather than a
    sum of whatever four values happen to be nearest.
    """
    ends = sorted(qs)
    out: dict[date, float] = {}
    for i in range(3, len(ends)):
        window = ends[i - 3:i + 1]
        span = (window[-1] - window[0]).days
        if not 240 <= span <= 300:      # three quarters between first and last
            continue
        out[window[-1]] = sum(qs[e] for e in window)
    return out


def series(blob: dict, tags: tuple[str, ...], unit: str,
           as_of: date) -> dict[date, float]:
    """TTM series for the first tag that produces a usable history."""
    best: dict[date, float] = {}
    for tag in tags:
        got = ttm(quarters(_rows(blob, tag, unit), as_of))
        if len(got) > len(best):
            best = got
    return best


# --- the gate ----------------------------------------------------------------
# Deliberately dull thresholds. The point of the fundamental side is to throw
# out companies that are shrinking or losing money, not to be clever about
# which grower is best - that is what the price history is for. Every one of
# these is a floor, not a ranking.
MIN_QUARTERS = 16               # four years of TTM history or we don't judge
GROWTH_HIT = 0.70               # TTM revenue up year-on-year this often
PROFIT_QUARTERS = 8             # TTM net income positive in each of the last N
EPS_LOOKBACK = 12               # TTM EPS must beat its level three years ago


@dataclass(frozen=True)
class Verdict:
    passed: bool
    reason: str
    growth_hit: float = 0.0
    profitable: int = 0
    eps_change: float = 0.0


def judge(blob: dict, as_of: date) -> Verdict:
    """Is this a growing, profitable company as at `as_of`?"""
    rev = series(blob, REVENUE_TAGS, "USD", as_of)
    inc = series(blob, INCOME_TAGS, "USD", as_of)
    eps = series(blob, EPS_TAGS, "USD/shares", as_of)

    if len(rev) < MIN_QUARTERS:
        return Verdict(False, f"only {len(rev)} quarters of revenue")

    ends = sorted(rev)
    yoy = [rev[ends[i]] > rev[ends[i - 4]] for i in range(4, len(ends))]
    hit = sum(yoy) / len(yoy) if yoy else 0.0
    if hit < GROWTH_HIT:
        return Verdict(False, f"revenue grew in only {hit:.0%} of quarters",
                       growth_hit=hit)

    recent = [inc[e] for e in sorted(inc)[-PROFIT_QUARTERS:]]
    if len(recent) < PROFIT_QUARTERS or any(v <= 0 for v in recent):
        return Verdict(False, "not profitable in every recent quarter",
                       growth_hit=hit, profitable=sum(v > 0 for v in recent))

    e_ends = sorted(eps)
    if len(e_ends) <= EPS_LOOKBACK:
        return Verdict(False, "not enough EPS history", growth_hit=hit,
                       profitable=len(recent))
    now, then = eps[e_ends[-1]], eps[e_ends[-1 - EPS_LOOKBACK]]
    change = now - then
    if change <= 0:
        return Verdict(False, "EPS no higher than three years ago",
                       growth_hit=hit, profitable=len(recent),
                       eps_change=change)

    return Verdict(True, "growing and profitable", growth_hit=hit,
                   profitable=len(recent), eps_change=change)
