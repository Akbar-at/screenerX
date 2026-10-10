# Data-provider pricing check — 10 October 2026

Purpose: prices for obtaining daily IDX broker flows for screenerX, distinguishing subscriptions for a UI from licensed machine-readable data.

## Verified findings

### Stockbit

Official Broker Summary help confirms date selection, net/gross transactions, broker codes and net buy/sell value. It states the feature is available to Stockbit Pro users. It does not establish a licensed public API, complete CSV exports, or a numerical subscription price.

- Feature documentation: https://help.stockbit.com/id/article/bandar-detector-bagaimana-cara-menggunakan-dan-apa-fungsinya-gocgkc/
- Subscription payment help, updated13 April2026: https://help.stockbit.com/id/article/bagaimana-cara-melakukan-pembayaran-stockbit-pro-n6fe42/ — directs users to Stockbit Shop but publishes no prices.
- Shop https://stockbit.com/shop — blocked by this environment's network policy during this check; no price verified.
- Trading-fee help, updated5 August2026: https://help.stockbit.com/id/article/apa-keunggulan-trading-di-stockbit-1sfvywt/ — buy0.15%, sell0.25%, no minimum registration deposit. These are execution fees, **not** broker-data subscription/API prices. They corroborate our configurable fee assumptions for this brokerage only.

Conclusion: confirmed relevant UI feature; current data-subscription price, account entitlement, export completeness and public API remain unverified.

### RTI

The official RTI Investor page lists broker ranking, buy/sell transaction detail and broker activity. Public pages examined do not publish a current numerical API/data-feed tariff.

- https://www.rti.co.id/?m_id=11
- https://www.rti.co.id/?m_id=18
- IDX lists PT RTI Infokom as a local authorized data redistributor: https://www.idx.co.id/id/produk/layanan-data-bei/

Conclusion: request a quote specifically for broker-code by ticker by trading-day regular-market net values, historical coverage and permitted API/export usage. Do not confuse free RTI apps with a free licensed broker feed.

### IDX — numerical institutional reference prices

Official 2026 catalogue/pricelist linked from the IDX data-services page:

https://www.idx.co.id/media/rzfl4wzy/20260513_idx-data-services-catalogue-pricelist-non-ab-2026.pdf

Printed page5 lists **monthly local-IDR direct-connection, non-group, main-connection DISPLAY licence** prices:

| Product | Published monthly licence fee | Coverage relevant here |
|---|---:|---|
| IDX Equity EoD Basic | Rp2,500,000 | Previous/close/change/volume/value/frequency; not a complete OHLC feed and no individual broker flow specified |
| IDX Equity EoD Professional | Rp3,000,000 | Previous/high/low/close/volume/value/frequency and best bid/offer on regular market; no individual broker flow specified |
| IDX Equity EoD | Rp5,500,000 | Wider bundle including Top Brokers, investor-type summaries and other records; a complete ticker-by-broker daily net-value matrix is not established by this description |

These are institutional licence references, **not an all-in retail REST API price or a quote for our use case**. Direct connections require leased-line connectivity per the data-services page. Group status, indirect distributor delivery, non-display use, infrastructure and other charges can change total cost. Automated screening may need a separate non-display licence assessment. Do not purchase Professional expecting broker flows.

Printed page16 lists corresponding indirect-connection non-group/main local monthly DISPLAY licence references: Basic Rp2,300,000; Professional Rp2,700,000; wider EoD Rp5,000,000. Distributor charges are not established by these numbers. Page25 classifies investment/quantitative analysis as Category2 non-display and notes delayed/EoD usage is free if sourced from a redistributor; confirm applicability and the distributor contract instead of automatically adding a real-time non-display fee.

### GoAPI candidate withdrawn

https://goapi.id/ responded successfully, but its current homepage displayed unrelated gambling/SEO articles rather than API plans or documentation. https://docs.goapi.id/ remained blocked at the proxy. No legitimate current API offering or price could be established. Withdraw the earlier candidate; do not enter payment/API credentials there on the basis of our earlier shortlist. This observation does not establish the cause of the changed site.

## Recommendation

For the minimal project, first establish whether Stockbit or the user's existing brokerage provides complete permitted exports at their current account tier. API automation requires a written or published licence/endpoint, not just a subscription UI.

For systematic broker-flow access, obtain an RTI/authorized-distributor quote and sample data. Neither Stockbit's UI documentation nor IDX EoD Professional's price proves a public broker API. No free complete IDX broker-flow API or exact retail API tariff was verified in this check.
