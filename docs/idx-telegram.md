# IDX enrichment in Telegram

ScreenX adds dated IDX data through a small adapter based on the reviewed MIT-licensed `nichsedge/idx-bei` client. `curl_cffi` is pinned to the version used for successful source tests. The adapter uses the Chrome-compatible transport, full headers, bounded browser rotation, cooldown after failures, strict record/date/count validation, and financial pagination.

Commands in the authorized group or private chat:

```text
/idx@ScreenX_idxbot BMRI
/foreign@ScreenX_idxbot PTSN
/broker@ScreenX_idxbot BMRI
/stock@ScreenX_idxbot BMRI technical+broker
/idxbrokers@ScreenX_idxbot
```

The `/idx` dashboard adds daily foreign buy/sell/net volume, reported turnover, frequency, non-regular trading and bid/offer snapshots, plus issuer profiles and reference ratios when available. Every displayed metric is included in its numerical image. `/foreign` and `/broker` show market/foreign activity without importing financial reference data. `/idxbrokers` reports top brokers across the whole exchange. The AI has a `get_idx_metrics` tool and can answer these requests through `/ask` or replies to the bot.

Stock-specific broker buy/sell/net values remain ON_HOLD. The public broker endpoint provides aggregate activity without a ticker or directional split. Foreign activity is volume in shares, not observed rupiah value. Bid/offer is a dated daily snapshot with no quote timestamp; it is not live order-book data. Financial ratios display the requested period, capture date and source fsDate; their accounting-period meaning and units are not verified for valuation input. They do not replace the existing DDM/RIM/EVA calculations or establish reviewed valuations.

Source enrichment is bound to the stored report's price session. Incomplete/future sessions are rejected. Profiles and financial-reference captures are separately dated and are not historical point-in-time replacements for financial captures. A source failure keeps other datasets inspectable and does not block the existing yfinance report publication.

Validated envelopes contain source response hashes, requested parameters, capture date and base64 source evidence. They are cached in `/tmp/screenerx-idx` and in private R2 under `idx/<session>/<dataset>.json`. R2 cache objects are registered by hash/size in the existing Neon `sx_bot_artifacts` table. The authenticated Worker cache routes check envelope identity and hashes. A recreated Container restores this cache before making fresh IDX requests; all tickers share each dated dataset.

The cloud screening runs at **07:30 WIB Monday-Friday** (`30 0 * * 1-5` UTC), using the latest observed completed session before that morning. Monday therefore uses the last observed session, usually Friday; holidays follow observed data. Retries retain the morning cutoff even when delayed until evening. The minute recovery cron remains enabled.

The market pipeline attaches dated IDX captures to every screened company before export/publication. `idx-screening.csv`, ticker JSON, top10.csv and core-run.json contain foreign direction, net volume and its share of session volume. The run also records separate net-buy/net-sell leader lists. These are foreign-volume screens, not broker accumulation or an added valuation score. Existing fundamental/technical/liquidity weights stay unchanged. Missing IDX records remain explicit and do not block healthy Yahoo results. Top-10 Telegram output and its PDF include a companion numerical IDX dashboard for each selected ticker. Native commands fetch on demand if the session has no cache. No Windows scheduled task is needed. `BOT_IDX_ENABLED=true` enables the source in both deployment configurations.

The authenticated `/internal/idx/check` POST route runs source and optional renderer checks without sending Telegram messages. It accepts a ticker and optional completed `as_of`, `reference`, `force`, and `render` settings. This is a private diagnostic route, not an arbitrary URL proxy. Runtime engine access rules and Telegram topic routing remain in effect.

Source tests cover wrong sessions, duplicates, missing/invalid numbers, incomplete pagination, transport retries/cooldown, cache restoration/checksums, archive failures, partial dataset availability, ticker isolation and chart/report output. The cloud deployment runs these alongside existing agent, bot and refresh tests.

Attribution: [source client](https://github.com/nichsedge/idx-bei/blob/afdb5b039b1e437e73cf67a126032523ee0b5770/python/src/idx/core/client.py); a copy of its MIT license is bundled as `screenerx/idx_be_license.txt`.
