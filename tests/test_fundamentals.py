"""The fundamentals reader, checked against filings we build ourselves.

Nothing here touches the network. The blobs below are shaped exactly like
the SEC's company-facts JSON - three quarters filed on their own and the
fourth left inside an annual figure, every fact carrying its filing date -
because that shape is what the code has to survive.

The test that matters most is test_later_filings_change_nothing. A screen
that quietly reads the future looks superb in a backtest and loses money in
public, and the only way to catch it is to run the same question against a
file that has the future in it and one that does not, and demand the same
answer.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from src import fundamentals as fd


# --- building fake filings ---------------------------------------------------
def q_ends(year: int) -> list[tuple[date, date]]:
    """(start, end) for the four calendar quarters of a year."""
    return [(date(year, 1, 1), date(year, 3, 31)),
            (date(year, 4, 1), date(year, 6, 30)),
            (date(year, 7, 1), date(year, 9, 30)),
            (date(year, 10, 1), date(year, 12, 31))]


def fact(start: date, end: date, val: float, filed: date | None = None) -> dict:
    return {"start": start.isoformat(), "end": end.isoformat(), "val": val,
            "filed": (filed or end + timedelta(days=40)).isoformat(),
            "form": "10-Q", "fy": end.year, "fp": "Q1"}


def company(years: range, revenue, income, eps) -> dict:
    """A filer that reports Q1-Q3 quarterly and folds Q4 into the 10-K.

    `revenue`, `income` and `eps` are called with (year, quarter) and return
    that quarter's value, so a test can make a company grow, shrink or lose
    money without touching the plumbing.
    """
    rev, inc, e = [], [], []
    for y in years:
        qs = q_ends(y)
        rq = [revenue(y, i) for i in range(4)]
        iq = [income(y, i) for i in range(4)]
        eq = [eps(y, i) for i in range(4)]
        for i in range(3):                      # Q1-Q3 filed on their own
            rev.append(fact(qs[i][0], qs[i][1], rq[i]))
            inc.append(fact(qs[i][0], qs[i][1], iq[i]))
            e.append(fact(qs[i][0], qs[i][1], eq[i]))
        year_end = date(y, 12, 31)
        filed = year_end + timedelta(days=55)   # the 10-K, a bit later
        rev.append(fact(date(y, 1, 1), year_end, sum(rq), filed))
        inc.append(fact(date(y, 1, 1), year_end, sum(iq), filed))
        e.append(fact(date(y, 1, 1), year_end, sum(eq), filed))
    return {"facts": {"us-gaap": {
        "Revenues": {"units": {"USD": rev}},
        "NetIncomeLoss": {"units": {"USD": inc}},
        "EarningsPerShareDiluted": {"units": {"USD/shares": e}},
    }}}


def grower(base: float, rate: float):
    """Value for (year, quarter), compounding `rate` a year."""
    return lambda y, q: base * (rate ** (y - 2014)) * (1 + 0.02 * q)


GOOD = dict(years=range(2014, 2023),
            revenue=grower(1_000_000, 1.12),
            income=grower(120_000, 1.14),
            eps=grower(1.00, 1.14))
AS_OF = date(2022, 12, 31)


# --- point-in-time -----------------------------------------------------------
def test_facts_filed_later_are_invisible():
    blob = company(**GOOD)
    rows = fd._rows(blob, "Revenues", "USD")
    early = fd.known_by(rows, date(2016, 6, 30))
    assert early, "some 2014-2016 filings should be visible"
    assert all(f.filed <= date(2016, 6, 30) for f in early.values())
    assert max(f.end for f in early.values()) < date(2016, 6, 30)


def test_restatement_takes_the_latest_filing_not_the_first():
    start, end = date(2020, 1, 1), date(2020, 3, 31)
    rows = [fd.Fact(start, end, 100.0, date(2020, 5, 1)),
            fd.Fact(start, end, 90.0, date(2021, 2, 1))]
    assert fd.known_by(rows, date(2020, 12, 31))[(start, end)].val == 100.0
    assert fd.known_by(rows, date(2021, 12, 31))[(start, end)].val == 90.0


# --- the Q4 hole -------------------------------------------------------------
def test_fourth_quarter_comes_out_of_the_annual_figure():
    blob = company(**GOOD)
    qs = fd.quarters(fd._rows(blob, "Revenues", "USD"), AS_OF)
    assert date(2019, 12, 31) in qs
    r = GOOD["revenue"]
    assert qs[date(2019, 12, 31)] == pytest.approx(r(2019, 3), rel=1e-9)


def test_a_year_missing_a_quarter_is_skipped_not_guessed():
    blob = company(**GOOD)
    rows = [f for f in fd._rows(blob, "Revenues", "USD")
            if not (f.start == date(2019, 4, 1) and f.days < 200)]
    qs = fd.quarters(rows, AS_OF)
    assert date(2019, 12, 31) not in qs, "Q4 must not be invented from two quarters"
    assert date(2018, 12, 31) in qs, "other years are unaffected"


def test_ttm_needs_four_consecutive_quarters():
    qs = {date(2020, 3, 31): 1.0, date(2020, 6, 30): 1.0,
          date(2020, 9, 30): 1.0, date(2020, 12, 31): 1.0}
    assert fd.ttm(qs)[date(2020, 12, 31)] == pytest.approx(4.0)
    gappy = dict(qs)
    gappy.pop(date(2020, 6, 30))
    gappy[date(2021, 3, 31)] = 1.0
    assert date(2021, 3, 31) not in fd.ttm(gappy)


# --- the gate ----------------------------------------------------------------
def test_a_growing_profitable_company_passes():
    v = fd.judge(company(**GOOD), AS_OF)
    assert v.passed, v.reason
    assert v.growth_hit > 0.9
    assert v.eps_change > 0


def test_a_shrinking_company_fails():
    blob = company(years=range(2014, 2023),
                   revenue=grower(1_000_000, 0.97),
                   income=grower(120_000, 0.97),
                   eps=grower(1.00, 0.97))
    v = fd.judge(blob, AS_OF)
    assert not v.passed
    assert "revenue" in v.reason


def test_a_company_that_loses_money_fails_even_while_growing():
    blob = company(years=range(2014, 2023),
                   revenue=grower(1_000_000, 1.30),
                   income=lambda y, q: -50_000.0,
                   eps=lambda y, q: -0.40)
    v = fd.judge(blob, AS_OF)
    assert not v.passed
    assert "profitable" in v.reason


def test_flat_eps_fails_even_with_revenue_growth():
    blob = company(years=range(2014, 2023),
                   revenue=grower(1_000_000, 1.20),
                   income=grower(100_000, 1.02),
                   eps=lambda y, q: 1.00)
    v = fd.judge(blob, AS_OF)
    assert not v.passed
    assert "EPS" in v.reason


def test_too_short_a_history_is_refused_rather_than_judged():
    v = fd.judge(company(years=range(2020, 2023), revenue=grower(1e6, 1.2),
                         income=grower(1e5, 1.2), eps=grower(1.0, 1.2)),
                 AS_OF)
    assert not v.passed
    assert "quarters" in v.reason


# --- the one that catches lookahead -----------------------------------------
def test_later_filings_change_nothing():
    """The 2018 verdict must not know that 2019-2022 happened.

    Same company, judged as at the end of 2018, from two files: one that
    stops there and one that also contains four more years in which the
    business collapses. If the answers differ, the screen is reading the
    future.
    """
    short = company(years=range(2010, 2019),
                    revenue=grower(1_000_000, 1.12),
                    income=grower(120_000, 1.14),
                    eps=grower(1.00, 1.14))

    def collapse(base, rate):
        good = grower(base, rate)
        return lambda y, q: good(y, q) if y < 2019 else -abs(good(2018, q))

    long = company(years=range(2010, 2023),
                   revenue=collapse(1_000_000, 1.12),
                   income=collapse(120_000, 1.14),
                   eps=collapse(1.00, 1.14))

    cutoff = date(2018, 12, 31)
    a, b = fd.judge(short, cutoff), fd.judge(long, cutoff)
    assert a.passed and b.passed, (a.reason, b.reason)
    assert a.growth_hit == pytest.approx(b.growth_hit)
    assert a.eps_change == pytest.approx(b.eps_change)

    # ...and by 2022 the collapse must actually show up, or the test above
    # proved nothing.
    assert not fd.judge(long, date(2022, 12, 31)).passed
