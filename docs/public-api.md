# Public API adapter

The first public-API integration fetches IDX daily OHLCV from Yahoo's unauthenticated chart endpoint:

`https://query1.finance.yahoo.com/v8/finance/chart/{TICKER}.JK`

This is not a supported official Yahoo API contract. Its schema/access and rate limits can change. No key, login scraping or private broker endpoint is used. TLS verification and inherited network proxy settings remain active.

## Usage

```bash
python -m screenerx.fetch --tickers BBCA BMRI ANTM \
  --as-of 2026-10-08 --output data/yahoo-2026-10-08
```

Defaults:400 calendar days of history,20-second request timeout, at most2 retries for429/502/503/504. These are adjustable CLI flags.403/network policy failures are not retried unchanged. The output directory must be new. A missing requested session is an error, not permission to substitute yesterday's quote. Same-day requests are refused before18:00 Jakarta to avoid labeling an in-progress candle as completed; use the actual latest completed trading session.

Output:

- `prices.csv`: screen-compatible OHLCV and explicitly estimated turnover.
- `raw/{ticker}.json`: exact successful API response before parsing.
- `api-run.json`: URLs, payload hashes, quality notes, action events and per-ticker failures.
- `api-errors.csv`: failed symbols/reasons. Any failed symbol causes nonzero exit even if others succeeded.
- `screen-config.json`: copy of supplied base config with Yahoo added as an explicitly permitted price source. It never changes the root default WSJ policy or valuation input numbers.

Review split/action price consistency using the returned events and your upstream records before supplying `--actions-reviewed`. This flag is your attestation, not an automatic data audit. The importer uses the OHLC quote array, not dividend-adjusted close, and does not silently guess adjustment factors. Null candles are recorded as missing rather than converted to zero.

Once reviewed valuations/levels and broker flows exist, use:

```bash
python -m screenerx \
  --prices data/yahoo-2026-10-08/prices.csv \
  --valuations data/valuations.csv --brokers data/brokers.csv \
  --config data/yahoo-2026-10-08/screen-config.json \
  --as-of 2026-10-08 --include-provisional --output output/api-screen
```

Valuation price/date/source must match the Yahoo price CSV, with model values actually refreshed using that input where needed. Do not simply relabel a different price as Yahoo. Corporate-action attestation is still required even for provisional screening.

## Coverage limits

| Input | Adapter supplies | Consequence |
|---|---|---|
| Daily OHLCV | Yes, if API permits access and symbol is covered | ATR/Stoch RSI/MACD can be calculated |
| Verified regular-market traded value | No; `close*volume` proxy only | Flow percentiles, liquidity and participation remain provisional |
| Timestamped bid/ask | No | Execution quality unverified |
| Raw financial statements / reviewed EVA/DDM/RIM | No | Fundamental CSV remains required |
| Broker-code daily net flows | No | Broker CSV remains required; no invented broker score |
| Frozen structural support/targets | No | Reviewed levels remain required |

Rows with `traded_value_basis=close_times_volume_estimate` cannot become ELIGIBLE merely by adding quotes. All relevant windows must be replaced with real regular-market turnover labeled `actual_regular` to establish that aspect of readiness.

As of this implementation, live access from this cloud was blocked by the egress proxy (403 during HTTPS tunnel creation). A draft adding **query1.finance.yahoo.com** was saved. Saving that draft does not apply it. Review and save network changes in environment settings, then publish the environment; afterward rerun the fetch to validate actual API availability. Parser/adapter tests use fixtures and do not establish a live Yahoo response.

A complete public-API-only three-perspective screener still needs a permitted, documented fundamentals source and a broker-flow source with the required coverage. No such complete broker endpoint has been verified here. If you have a provider's public docs, use them to establish schema, IDX coverage, authentication, historical depth and export rights before writing that adapter. Do not drop the broker gate or redistribute its weight to hide missing input.
