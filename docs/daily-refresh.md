# Automatic daily market refresh

Scheduling runs exclusively in Cloudflare. The Windows task and its installation scripts have been removed. The Python service has no local refresh timer. Neon stores durable job state; the Python/yfinance engine runs in a Cloudflare Container, and private R2 stores inputs and reports. Container disk is temporary.

## What changes each day

1. Discover the latest completed IDX session from actual reference candles.
2. Fetch the public Ajaib ticker universe and yfinance prices with two workers.
3. Refresh USD/IDR FX; any cached fallback must still pass currency/date/age validation.
4. Recalculate technical indicators, daily valuation/MOS, conditional entry/stop/targets, coverage and the shortlist.
5. Generate the ranking PNG/PDF and each candidate's chart.
6. Publish `latest.json` atomically. A running bot reloads that pointer when handling the next command; it does not need restarting locally.

Financial statements are retained annual yfinance captures with their real reporting and retrieval dates. Daily market refresh **does not download every company's statements daily**. To ingest new issuer statements, run a new yfinance financial collection and update `BOT_FINANCIAL_SNAPSHOTS` (or rebuild the cloud seed bundle). The engine enforces the existing statement age/alignment limits. Broker flow stays ON_HOLD.

No newer observed session means SKIPPED. A source/publishing failure retains the previous active report and schedules a retry. Price coverage must reach 80% of the returned public universe before publication. Company financial/model gaps remain visible and may leave fewer than ten ranking entries. Three failed attempts stop the job for inspection. Raw ticker listings are not certified as the current complete IDX common-equity list.

## Cloudflare scheduling

The Worker now has two Cron expressions:

- `30 11 * * 1-5`: daily refresh at 18:30 Jakarta.
- `* * * * *`: Telegram dispatch recovery and refresh heartbeat/retries.

Cloudflare Cron uses UTC. [Official documentation](https://developers.cloudflare.com/workers/configuration/cron-triggers/).

The daily trigger inserts a durable pending job in Neon and starts the Python refresh asynchronously. The one-minute trigger recovers dispatch failures and keeps the container alive while the job is running. Leases prevent duplicate processing; completed/skipped days are idempotent.

Cloud publication uploads immutable versioned files to private R2 first, validates their hashes, and switches the active manifest only after the bundle is complete. Older report dates cannot replace newer active dates. Container restarts load that published version and its retained financial captures.

Deployment prerequisites:

1. Apply both bot migrations with `scripts/migrate_bot.py` and grant the runtime role access to `sx_refresh_jobs` as well as the original bot tables.
2. Use the updated Worker, Python image, and `BOT_AUTO_REFRESH=true` configuration. Automatic refresh requires the cloud service, Neon DATABASE_URL, and INPUT_BUNDLE_URL.
3. Seed a bundle that includes financial captures and FX. A ready-made seed is `output/bot-input-refresh-ready-v2`; it contains core JSON, prices, 891 captured financial snapshots, FX, and the hash manifest.
4. Upload it through the authenticated `/internal/bundle/<version>/<filename>` PUT routes, with `manifest.json` **last**. The helper `screenerx.refresh_bundle.publish_bundle` performs this order. These routes require the engine secret.
5. The Worker and Container are deployed through `.github/workflows/deploy-cloudflare.yml` on branch `deploy/cloudflare-20261013`. GitHub Actions uses an encrypted scoped deployment token and builds the image remotely; Cloudflare GitHub OAuth is not needed for this route. The runtime role is `screenerx_engine` with SELECT/INSERT/UPDATE privileges and no role/database creation privilege. Both Cron expressions are confirmed in Cloudflare. The authenticated engine health check returned data date 2026-10-12 and refresh_enabled=true. The first full scheduled market refresh is still awaiting its 18:30 window.

Financial capture replacement still requires a new financial ingestion/import. This schedule recalculates market research daily, not broker flow, subscriptions, or executed trades. It refreshes the reports available to commands; it does not send unsolicited daily digests.


Daily refresh now merges prior real historical candles where the latest Yahoo response omits them. Fresh candles replace overlapping old observations; prior data never fills the new decision-session candle. The retained source hash is recorded. A zero-complete-coverage report cannot replace a previously healthy report; the job retries while the previous publication remains active. This protects against the 2026-10-13 provider response omitting the 2026-10-12 candle across most tickers.
