# Free and paid data options for this MVP

Yahoo daily prices now have an optional public-endpoint importer (see public-api.md); other options below remain candidate sources, not integrated feeds. Current tariffs, subscription entitlements, historical IDX coverage and CSV/API export rights have **not been independently verified in this session**. Do not assume a subscription licenses automated extraction. Obtain an actual sample export before choosing a provider.

| Option | Cost category | Useful inputs | Pros | Cons / confirm before use |
|---|---|---|---|---|
| IDX / issuer investor-relations filings | Public/free documents | Financial statements, disclosures, corporate actions | Primary sources; inspect the actual business and accounting | Manual extraction/normalization; not a ready-made valuation or complete broker-history feed. See https://www.idx.co.id/ and issuer IR pages. |
| Yahoo Finance `.JK` history | Usually free public access | Daily prices/volume where ticker covered | Practical starting history; broad familiar tooling | Coverage, adjustments, request limits and usage rights vary; broker flow absent. Regular-market turnover/quotes may require another source. `close*volume` is an estimate, not actual daily traded value. See https://finance.yahoo.com/. |
| Existing Indonesian brokerage account | Account access; entitlements vary | Broker summaries, quotes, chart/history exports where provided | May already cover the most difficult broker input with no extra subscription | Historical depth/export rights vary; screenshots may be truncated. Confirm full daily cohort records, regular-market scope and legal CSV export. Never supply passwords in chat. |
| Stockbit / Stockbit Pro | Access tiers vary; verify current entitlements | Candidate broker-summary/chart/fundamental tools | Familiar IDX research workflow; candidate manual broker input | Confirm whether required features require account/subscription, historical range and supported exports. Subscription UI access does not imply an API. See https://stockbit.com/. |
| RTI Business / RTI Analytics | Public/account features plus possible paid products | Candidate IDX market/financial research and broker data | Indonesia-focused research tools | Verify exact product, complete broker-history fields, export/API and license; no blanket free-flow assumption. See https://www.rti.co.id/. |
| TradingView subscription | Paid tiers; feed charges can be separate | Charting, OHLC/indicator workflow and supported chart export | Useful repeatable technical inspection | Not a substitute for complete IDX broker flow or validated EVA/DDM/RIM. Check export permissions and exchange data entitlements. See https://www.tradingview.com/. |
| WSJ market-data access | Access conditions/subscription vary | Your handoff's preferred statements and reference price | Matches existing valuation source policy | Access/IDX field coverage/export rights must be checked; not assumed to supply daily broker flow. No access has been tested here. See https://www.wsj.com/market-data/. |
| Licensed IDX data distributor / institutional terminal | Paid quotation/license | Potential systematic prices, quotes, financials and possibly broker data | Better candidate for repeatable automation, auditability and support | Higher cost; broker-level data is not guaranteed. Ask specifically for broker/date/net-value/regular-market coverage and rights, not just an IDX price feed. Confirm current distributor arrangements with IDX. |

## Recommendation

**Start free/low cost:** public filings or your existing reviewed valuation workbook; a permitted price-history export; and your existing broker platform's *complete* daily broker summaries. Produce the three documented CSVs. For this minimal tool, valuation methods/structural levels are reviewed inputs, so you can start with a limited watch universe rather than collect the entire exchange immediately.

If using Yahoo for prices, deliberately change `fundamental.allowed_price_sources` to `['Yahoo Finance']` and label both CSVs consistently. This departs from the original handoff's WSJ-only final-price policy; do not quietly switch sources. Preserve actual regular-market turnover from a supported export and current bid/ask when available. Without these, use provisional inspection output, not claimed complete execution validation.

**Pay first for the missing broker coverage**, if your current account does not provide it. Verify complete export capability and at least20 aligned sessions for every favored/avoided/mixed broker before buying. A better chart subscription alone does not resolve that gap. For later automatic universe-wide runs, request a licensed machine-readable feed and historical access rather than depending on manual screenshots or undocumented scraping.

## Questions to ask any paid provider

1. Is the price/turnover universe IDX regular-market equities, with corporate actions and official trading dates? Are quote timestamps available?
2. Does broker history include each broker's regular-market daily buy/sell or net value, including explicit no-activity coverage? Can investor-type foreign/local data be distinguished?
3. How many historical years/sessions, what publication delay, and what happens to delisted/suspended names?
4. Is CSV export or a documented API licensed for this personal screener? What are limits and redisplay restrictions?
5. Can you supply a small actual sample matching these three CSV schemas before payment? What are the current total fees, taxes and data entitlement charges?

The core screen makes no network requests. The default yfinance importer requires no API key; live access succeeded for the15-stock research watchlist on October12,2026. Complete reviewed fundamental and broker coverage is not established. Use the separate price-only research mode while those inputs remain on hold.
