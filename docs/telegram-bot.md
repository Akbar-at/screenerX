# Telegram bot and IHSF-style research reports

The implemented bot produces original screenerX reports in Indonesian, following the references' chart + analysis + strategy structure. It uses real saved engine output; it does not reproduce Fortis branding, old price levels, broker claims, or claims that positions have been bought. Candlesticks, SMA20/SMA60, volume, conditional entry/targets/stop, DDM/RIM/EVA and scenarios come from the run. Broker flow stays ON_HOLD. A research rank does not override a poor net reward/risk or missing confirmation.

## Commands

| Command | Response |
|---|---|
| `/start`, `/help` | Indonesian command guide |
| `/top10`, `/top` | PNG ranking summary, then a standalone chart + full narrative for every qualified candidate; empty slots stay empty |
| `/stock BBNI` | Standalone candlestick/volume PNG + complete narrative |
| `/chart BBNI` | Standalone candlestick/volume PNG |
| `/valuation BBNI` | Standalone chart + models, statement period, scenarios and risks |
| `/report` | Multi-page PDF: summary + each shortlisted stock |
| `/report TLKM` | Standalone chart + single-stock PDF, including partial coverage |
| `/coverage`, `/status` | Coverage, run date, delivery state |
| `/stock CODE live` | Explicit yfinance lookup, including tickers outside the saved universe; requires BOT_ALLOW_LIVE=true |

Default commands use stored data, including all 957 collected codes, not just the shortlist. Live requests remain unranked single-stock inspections for the saved run's price date. yfinance may fail/rate-limit; incomplete inputs stay visible. No market-wide refresh runs in a chat/webhook request.

Each stock/valuation analysis includes a standalone candlestick chart with volume, SMA20/SMA60, the final session date, and available conditional levels. `/top10` sends one chart and narrative for every qualified stock. Full-page PNGs and PDFs are still generated. Telegram delivery is paced for private/group chats and retains retry handling, following the [Telegram delivery limits](https://core.telegram.org/bots/faq#my-bot-is-hitting-limits-how-do-i-avoid-this).

## Local preview and polling

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt -r requirements-bot.txt
.\.venv\Scripts\python.exe -m screenerx.telegram_bot preview --run-dir output/top10-yfinance-latest-2026-10-12/core --prices output/top10-yfinance-latest-2026-10-12/prices.csv --command '/stock BBNI'
```

Preview makes files without contacting Telegram. Concrete samples are in `output/telegram-preview`: BBNI PNG/PDF, shortlist PNG, and a nine-page PDF containing the eight qualified candidates from October 12.

For the live private bot, copy `.env.bot.example` to ignored `.env.bot`, set the BotFather token, and set both allowed Telegram **user IDs** and **chat IDs**. A private chat's ID is commonly the user's ID; a group chat has its own ID. The bot checks both. Existing Neon/Cloudflare account keys in `.env` are not a bot token or PostgreSQL connection string.

```powershell
.\.venv\Scripts\python.exe -m screenerx.telegram_bot poll
```

Polling requires that the bot have no active webhook. SQLite persists jobs and individual message delivery states locally. Configuration files are loaded without logging secrets. Missing credentials fail closed. Use one polling process per token.

## Cloudflare + Neon + R2 deployment

Implemented layout:

- `workers/bot`: authenticated Telegram webhook, Neon durable acceptance, Queues dispatch/consumer, recovery Cron, private R2 inputs/artifacts, and Python Container routing.
- `services/bot/Dockerfile`: Python bot/renderer service. The deterministic engine remains Python.
- Container configuration uses one `basic` instance (1 GiB memory) to hold the full price/report bundle and render charts; measure usage before resizing. [Cloudflare instance types](https://developers.cloudflare.com/containers/platform/limits/).
- `db/migrations/001_telegram.sql`: inbound jobs, delivery outbox, archived artifact hashes.
- `scripts/prepare_bot_bundle.py`: hashed core JSON + price CSV bundle. Upload inputs privately to R2.
- `scripts/migrate_bot.py`: explicit migration step; runtime roles do not need CREATE TABLE privileges.

Deployment steps:

1. Create a Neon database/branch and a PostgreSQL connection string. Apply both migrations using a migration role (`DATABASE_URL` then `.\.venv\Scripts\python.exe scripts/migrate_bot.py`). Give the runtime role SELECT/INSERT/UPDATE on the bot tables and `sx_refresh_jobs`.
2. Install Docker Desktop or another supported Docker runtime. Container image builds require Docker; it is unavailable in this workspace. Worker-only type checking and a dry-run bundle succeeded with container rollout disabled; the Docker image and hosted flow are not yet verified.
3. In `workers/bot`, install dependencies with `npm ci`, authenticate Wrangler (`npx wrangler login` or a scoped `CLOUDFLARE_API_TOKEN`), and create `screenerx-bot` and `screenerx-bot-dead` Queues and `screenerx-reports` R2 bucket using Wrangler. Adjust names in `wrangler.jsonc` if needed. The existing `.env` account API key is not automatically loaded by Wrangler.
4. Set Worker secrets through `npx wrangler secret put`: `DATABASE_URL`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_WEBHOOK_SECRET`, `ENGINE_SECRET`. Set allowlists and the future Worker URL + `/internal/bundle` in `wrangler.jsonc` vars. Set BOT_ALLOW_LIVE only if desired.
5. Build a new input bundle:

```powershell
.\.venv\Scripts\python.exe scripts/prepare_bot_bundle.py --run-dir output/top10-yfinance-latest-2026-10-12/core --prices output/top10-yfinance-latest-2026-10-12/prices.csv --output output/bot-input-bundle-next
```

Use the updated seed `output/bot-input-refresh-ready`, which includes retained financials and FX as well as prices and core results. Once the Worker is deployed, publish through its authenticated routes with `.\.venv\Scripts\python.exe -m screenerx.refresh_bundle --bundle output/bot-input-refresh-ready`. Configure INPUT_BUNDLE_URL and ENGINE_SECRET first. The helper uploads immutable versioned files and writes the active manifest last; the container verifies hashes. Do not make the bucket public. The older `output/bot-input-bundle` is a report-only sample and is not suitable for automatic financial recalculation.

6. Run `npm run check`, `npm test`, then `npm run deploy`. Containers require a Cloudflare plan that supports them. Secrets are forwarded into the Python container; none are baked into its image.
7. With the token and the same webhook secret configured locally, register the endpoint:

```powershell
.\.venv\Scripts\python.exe -m screenerx.telegram_bot set-webhook --url https://<worker>.workers.dev/telegram/webhook
```

8. Start the bot in Telegram, run `/coverage`, `/stock BBNI`, `/top10`, and `/report`. Verify that an unauthorized user/chat is rejected. Check Neon job/outbox rows and private R2 `reports/` objects for delivery evidence.

The cloud flow stores an update in Neon before acknowledging Telegram. Queue transport can duplicate messages; Python claims jobs with leases and skips already delivered outbox parts. A one-minute Cron repairs missing dispatch and expired leases. Telegram 429 schedules a retry; ambiguous sends are recorded UNCERTAIN and are not automatically resent. After eight processing attempts a job is failed for inspection. This avoids promising exactly-once Telegram delivery, which the API cannot guarantee.

Automatic daily market refresh is now implemented: see [daily-refresh.md](daily-refresh.md). The local task runs at 18:30 Jakarta, and the Worker daily Cron starts the cloud coordinator after deployment. Financial captures are retained and dated rather than fetched for every company every day. Subscription/watchlist management and executed-position tracking remain outside this release.

## Validation and remaining activation inputs

Python tests cover authorization, duplicate updates, partial delivery, rate limits, ambiguous sends, expired leases, webhook persistence, and recommendation coverage/risk gates. Worker tests cover secret checks and both allowlists. Reports were generated from the October 12 real-data run and visually inspected against the reference structure.

The screenx production Neon schema and runtime role, private screenerx-reports R2 bucket, and both Queues are provisioned. DATABASE_URL and engine/webhook secrets are saved in ignored .env.bot. Worker and Container deployment remain pending: the current Cloudflare key is accepted by resource APIs but rejected by Workers Builds. Add a user-scoped CLOUDFLARE_API_TOKEN with Workers Builds Configuration Edit and deployment permissions, and connect the GitHub repository through Cloudflare's Builds integration. Telegram activation separately needs a BotFather token and allowed user/chat IDs. The engine can serve refreshes while Telegram delivery is disabled. Keep all credentials in ignored environment files or cloud secrets.
