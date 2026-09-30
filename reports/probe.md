# Earnings-date sources, from the runner

| source | result |
|---|---|
| SEC EDGAR (8-K filings) | OK — 1000 filings, 102 of them 8-K |
| Nasdaq earnings calendar | FAILED — ReadTimeout: HTTPSConnectionPool(host='api.nasdaq.com', port=443): Read timed out.  |
| Yahoo earnings dates | OK — 25 AAPL earnings dates, back to 2020-10-29 |
| Yahoo 10y daily bars | OK — 2513 daily bars from 2016-09-30 |
