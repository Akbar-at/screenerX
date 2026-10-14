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

- `30 0 * * 1-5`: screening starts at 07:30 Jakarta on weekdays, using the latest observed completed session before that morning. Delayed retries retain that morning cutoff.

After successful publication, the top-10 charts and numerical reports are queued to the configured Telegram destination: group `-1003749187440`, **Daily Screening topic 5**. A morning with no new observed trading session sends the latest report with its actual price date. Delivery starts after screening finishes, rather than at exactly 07:30. Failed publication is retried before delivery.

`BOT_DAILY_CHAT_ID` and `BOT_DAILY_TOPIC_ID` configure delivery. The destination must be an authorized open group. A deterministic negative job ID per request day/group/topic keeps scheduled jobs separate from Telegram updates and deduplicates enqueue retries. The existing Neon outbox tracks sent parts and rate-limit retries; minute Cron recovers pending work. The authenticated `/internal/daily-delivery` POST route queues the current report for an initial delivery or recovery; repeating it for the same day does not create another report.
- `* * * * *`: Telegram dispatch recovery and refresh heartbeat/retries.

Cloudflare Cron uses UTC. [Official documentation](https://developers.cloudflare.com/workers/configuration/cron-triggers/).

The daily trigger inserts a durable pending job in Neon and starts the Python refresh asynchronously. The one-minute trigger recovers dispatch failures and keeps the container alive while the job is running. Leases prevent duplicate processing; completed/skipped days are idempotent.

Cloud publication uploads immutable versioned files to private R2 first, validates their hashes, and switches the active manifest only after the bundle is complete. Older report dates cannot replace newer active dates. Container restarts load that published version and its retained financial captures.

Deployment prerequisites:

1. Apply both bot migrations with `scripts/migrate_bot.py` and grant the runtime role access to `sx_refresh_jobs` as well as the original bot tables.
2. Use the updated Worker, Python image, and `BOT_AUTO_REFRESH=true` configuration. Automatic refresh requires the cloud service, Neon DATABASE_URL, and INPUT_BUNDLE_URL.
3. Seed a bundle that includes financial captures and FX. A ready-made seed is `output/bot-input-refresh-ready-v2`; it contains core JSON, prices, 891 captured financial snapshots, FX, and the hash manifest.
4. Upload it through the authenticated `/internal/bundle/<version>/<filename>` PUT routes, with `manifest.json` **last**. The helper `screenerx.refresh_bundle.publish_bundle` performs this order. These routes require the engine secret.
5. The Worker and Container are deployed through `.github/workflows/deploy-cloudflare.yml` on branch `deploy/cloudflare-20261013`. GitHub Actions uses an encrypted scoped deployment token and builds the image remotely; Cloudflare GitHub OAuth is not needed for this route. The runtime role is `screenerx_engine` with SELECT/INSERT/UPDATE privileges and no role/database creation privilege. Both Cron expressions are confirmed in Cloudflare. The first scheduled refresh completed on 2026-10-13 at 18:39 WIB. Its provider-history regression was repaired and automated history retention is deployed.

Financial capture replacement still requires a new financial ingestion/import. This schedule recalculates market research daily, not broker flow, subscriptions, or executed trades. It refreshes the reports available to commands; it does not send unsolicited daily digests.


Daily refresh now merges prior real historical candles where the latest Yahoo response omits them. Fresh candles replace overlapping old observations; prior data never fills the new decision-session candle. The retained source hash is recorded. A zero-complete-coverage report cannot replace a previously healthy report; the job retries while the previous publication remains active. This protects against the 2026-10-13 provider response omitting the 2026-10-12 candle across most tickers.


Refresh recovery and publication checks

- Each attempt merges missing historical candles from the last published, hashed price bundle before screening. Fresh observations win; the new session must come from the provider.
- Retries refetch failed, corrupt, and current-session-missing captures. Healthy captures remain cached. Three bounded attempts run 15 minutes apart through the cloud cron and Neon job state.
- Publication requires the expected completed session, fresh current-session candles for at least 80% of the universe, and at least 50% of the previous complete research coverage (with zero always rejected after a healthy run). This is a conservative outage gate: legitimate large coverage changes may require investigation. It never requires a minimum shortlist size.
- Rejected attempts leave the active R2 manifest and local serving pointer intact. Checks are saved in publication-checks.json and the Neon job result, including the date still being served. After three failures the job is FAILED; the healthy report remains available and the next scheduled day starts a new job. Persistent source outages cannot be repaired by inventing candles.
- The refresh thread renews its Neon lease every minute independently of Worker dispatch.
- GitHub Actions runs recovery regression tests before building or deploying the production image. The integration test removes yesterday from one ticker while another supplies the calendar, then exercises the actual market collection/CSV/core-screen path and verifies automatic restoration.
