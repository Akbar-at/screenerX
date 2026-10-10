# Ajaib access check and public snapshot adapter

Checked10 October2026 after environment publication. No credentials were supplied or requested; no private endpoints or trades used.

## Verified public endpoints

Observed in JavaScript linked by Ajaib's own public website:

Base: `https://external-api.ajaib.co.id/api/v1/public/investment-experience/`

- `asset/codes?asset_type=STOCK` — ticker universe, HTTP200,956 codes in this run. This count is not a guarantee of active eligible common stocks.
- `asset/info?asset_type=STOCK&code=BBCA` — HTTP200; code, price, timestamp, labels.
- `asset/detail?asset_type=STOCK&code=BBCA` — HTTP200; price performance, volume/value, valuation ratios, EPS/book-value/cash-flow-per-share and other summary data.

These are publicly used endpoints, not a verified supported API contract or licence for unrestricted redistribution. No full annual financial statements, EVA/DDM/RIM model output or daily broker-level flow was present in the responses examined. Snapshot timestamps and market scope must be validated before importing into historical decision data; do not invent dates or replace missing histories with current values.

```bash
python -m screenerx.ajaib --tickers BBCA BMRI ANTM AADI AMMN BSDE ERAA BRMS \
  --output data/ajaib-public-snapshots
```

Saves raw response JSON and hashes, ticker universe, combined snapshots and an access/coverage report. Does not silently populate screener valuation or broker CSVs. Yahoo remains the daily historical-price adapter.

## Free broker UI verified

https://ajaib.co.id/terminal explicitly states the desktop terminal is free to install/use, with transactions subject to brokerage fees. The FAQ lists Done Details, Inventory Analysis and **Broker Summary**, and describes login with an Ajaib account.

That is evidence for a free UI with broker-analysis features, **not** proof of a public broker API, complete20-session export coverage or permission for automated extraction. An actual supported export/API response is still needed for screenerX's broker input.

https://ajaib.co.id/ publishes stock execution fees0.1513% buy and0.2513% sell inclusive of the listed components. It also lists an additional0.1% broker fee for market orders and0.25% for forced sell. Do not equate these execution tariffs with a data licence. The existing configurable defaults were not silently changed.

## Remaining access failures

- `https://api.ajaib.co.id/` returns403 with a Cloudflare attention/access-denied page. This is different from the earlier proxy-tunnel domain denial, and does not establish which private data routes exist or their authentication requirements.
- The supplied Reddit thread and its JSON form return403. Its comments could not be verified.

No additional environment publication is needed for the successfully tested public endpoints. The remaining broker-history gap is about available data access/schema, not a claim that all Ajaib domains are blocked.
