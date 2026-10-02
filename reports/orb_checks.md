# ORB on stocks in play: the open questions

252 sessions (2025-09-30 to 2026-10-02), the same train / validation / test dates as reports/orb_research.md. Results are per trade as a share of the account at the live sizing (a full stop = 1% of the account; the same number is R). Nothing here changes a live setting.

## The gate (fixed before the first run)

1. Measured costs: test per trade > 0.
2. Measured costs: test 95% interval above zero.
3. Stress (the larger of measured + 0.05% per side and 0.10% per side): test > 0.
4. Stress: validation > 0.
5. Measured costs: test > 0 without its best 3 stocks.
6. SIP bars instead of IEX: test > 0 at 0.05% per side.
7. Survivorship-free universe: test > 0 at 0.05% per side.

If the premarket ranking (section 4) is adopted by the usual rule, the gate is run on that version.

## Gate result

Version tested: `top10` with range >= 0.35 ATR.

- PASS: measured costs: test > 0
- PASS: measured costs: test 95% interval above zero
- PASS: stress: test > 0
- FAIL: stress: validation > 0
- PASS: measured costs: test > 0 without best 3 stocks
- PASS: SIP bars: test > 0
- PASS: survivorship-free universe: test > 0

**FAILED.**

## 1. Real execution cost (NBBO at the moment a live signal can act)

1029 trades. Usable quotes for 1018 entries and 1022 exits; the rest (no quote, or more than 1% from the bar - bars are split-adjusted, quotes are not) use 0.05%.

| cost | median | mean | 90th percentile |
|---|---|---|---|
| entry (fill vs the bar close the rule saw) | 0.032% | 0.041% | 0.162% |
| exit | 0.009% | 0.013% | 0.048% |
| round trip | 0.045% | 0.054% | 0.184% |
| assumed so far | 0.100% | 0.100% | 0.100% |

| version | train n | win | per trade | PF | total | val n | win | per trade | PF | total | test n | win | per trade | PF | total |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| assumed 0.05% per side | 609 | 48.4% | -0.004% | 0.99 | -2.3% | 202 | 45.0% | +0.030% | 1.08 | +6.0% | 218 | 54.6% | +0.144% | 1.55 | +31.4% |
| measured costs | 609 | 48.9% | +0.035% | 1.09 | +21.6% | 202 | 46.5% | +0.058% | 1.15 | +11.6% | 218 | 55.5% | +0.173% | 1.67 | +37.8% |
| stress | 609 | 44.8% | -0.079% | 0.82 | -47.9% | 202 | 44.1% | -0.038% | 0.91 | -7.6% | 218 | 52.3% | +0.080% | 1.27 | +17.4% |

- long: measured per trade +0.040% over 546 trades
- short: measured per trade +0.101% over 483 trades


## 2. Consolidated (SIP) bars instead of IEX

252 of 252 sessions have SIP bars for SPY and QQQ.

| version | train n | win | per trade | PF | total | val n | win | per trade | PF | total | test n | win | per trade | PF | total |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| live rule, static 10 (SIP) | 1384 | 39.5% | -0.147% | 0.73 | -203.7% | 436 | 34.9% | -0.190% | 0.67 | -82.9% | 428 | 44.4% | -0.098% | 0.80 | -41.8% |
| candidate top10 (SIP) | 916 | 46.6% | +0.020% | 1.05 | +18.4% | 283 | 47.0% | -0.016% | 0.95 | -4.6% | 310 | 47.7% | +0.017% | 1.05 | +5.2% |
| candidate top10 (IEX, for reference) | 609 | 48.4% | -0.004% | 0.99 | -2.3% | 202 | 45.0% | +0.030% | 1.08 | +6.0% | 218 | 54.6% | +0.144% | 1.55 | +31.4% |

Same names picked from IEX and SIP volume: 2.9 of 10 on average.

### What live does: picks from IEX volume, prices from the consolidated tape

| version | train n | win | per trade | PF | total | val n | win | per trade | PF | total | test n | win | per trade | PF | total |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| IEX picks, SIP prices, 0.025% a side | 816 | 47.2% | +0.023% | 1.06 | +19.1% | 264 | 45.1% | +0.022% | 1.06 | +5.8% | 294 | 52.7% | +0.055% | 1.18 | +16.2% |
| IEX picks, SIP prices, 0.050% a side | 816 | 46.1% | +0.001% | 1.00 | +0.6% | 264 | 44.3% | -0.007% | 0.98 | -1.8% | 294 | 50.7% | +0.030% | 1.09 | +8.8% |
| IEX picks, SIP prices, 0.100% a side | 816 | 44.1% | -0.047% | 0.89 | -38.2% | 264 | 43.2% | -0.051% | 0.88 | -13.4% | 294 | 48.0% | -0.016% | 0.95 | -4.6% |
0.025% a side is about the measured median round trip (section 1).

## 3. Survivorship-free universe (every listed and delisted US equity)

Alpaca lists 14592 US equity tickers on the main exchanges (1870 delisted or inactive). On an average day 1869 pass price >= 5 and 14-day dollar volume >= 50M as known that morning. Ranked the same way, SIP data.

Of 2520 daily picks, 2429 were outside the hand-made pool and 2 are no longer listed.

| version | train n | win | per trade | PF | total | val n | win | per trade | PF | total | test n | win | per trade | PF | total |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| hand-made pool (SIP) | 916 | 46.6% | +0.020% | 1.05 | +18.4% | 283 | 47.0% | -0.016% | 0.95 | -4.6% | 310 | 47.7% | +0.017% | 1.05 | +5.2% |
| every listed name (SIP) | 771 | 43.6% | -0.049% | 0.87 | -37.4% | 267 | 46.1% | -0.023% | 0.93 | -6.2% | 266 | 54.1% | +0.040% | 1.14 | +10.8% |

- names outside the old pool: 1234 trades, per trade -0.034%
- names in the old pool: 70 trades, per trade +0.127%

## 4. Premarket ranking (live-usable through delayed SIP)

Top 10 by 04:00-09:15 consolidated volume against its own 14-session normal, same range filter and rules. Decided on train + validation by the same adoption rule as every stage.

| variant | verdict | train: n | win | avg R | PF | 95% CI | val: n | win | avg R | PF | 95% CI | test: n | win | avg R | PF | 95% CI |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| first-5-minute ranking (current) | incumbent | 609 | 48% | -0.004 | 0.99 | -0.08 to +0.08 | 202 | 45% | +0.030 | 1.08 | -0.10 to +0.16 | 218 | 55% | +0.144 | 1.55 | +0.03 to +0.26 |
| premarket ranking | worse on train | 531 | 47% | -0.038 | 0.91 | -0.11 to +0.04 | 164 | 48% | +0.074 | 1.20 | -0.07 to +0.23 | 201 | 53% | +0.074 | 1.25 | -0.05 to +0.20 |

**Not adopted** (worse on train). The rest of this report tests the first-5-minute version.

