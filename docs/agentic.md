# OpenRouter agentic deployment option

This build adds an optional agent to the existing Cloudflare Container/Worker + Neon + R2 bot. The model selects research tools and explains their results. Existing functions calculate the financial/technical values and produce numerical tables, chart images and PDFs. Broker flow stays ON_HOLD; financial estimates remain unreviewed. No order execution or broker feed is added.

## Tools and Telegram behavior

| Tool | Existing capability |
| --- | --- |
| analyze_stock | Select technical/fundamental/broker combinations and run `/stock`, `/chart` or `/report`; attach original reports |
| get_shortlist | Read the existing qualified combined research shortlist |
| get_coverage | Read run date, universe coverage and unfilled shortlist slots |
| get_status | Read run date and fundamental/broker availability |

Examples after enabling:

```text
/ask Compare the technical and fundamental analysis of BBCA and BMRI
/ask@ScreenX_idxbot Analisis PTSN teknikal saja, kirim chart
/ask@ScreenX_idxbot Buat PDF fundamental BMRI, jelaskan asumsi dan data yang kurang
/ask@ScreenX_idxbot Cek teknikal dan broker flow PTSN
```

`/agent` is an alias for `/ask`. In private authorized chats, ordinary natural-language messages also invoke the agent when enabled. In enabled groups, users can **reply to a ScreenX message** with an ordinary question, without a slash command. That reply includes a bounded quote from the replied-to bot message as context. No other conversation history is shared across users or topics. Mentions such as `@ScreenX_idxbot Cek teknikal PTSN` are also supported when Telegram delivers them. With privacy mode enabled and the bot a regular member, replies and addressed commands work; plain mentions require the bot to be an admin or privacy mode disabled in BotFather. See [Telegram's delivery rules](https://core.telegram.org/bots/faq#what-messages-will-my-bot-get). Ordinary unaddressed group conversation is ignored, even if Telegram sends it. Commands addressed to other bots are ignored in groups. Existing access checks, topic routing, durable delivery, and chart/PDF uploads still apply.

Numerical source reports are attached unchanged. The model's summary is supplementary and can still make mistakes; the system prompt tells it to use tool facts, avoid repeating numerical values, state source dates, and preserve missing-data statuses. A prompt is not a guarantee against hallucinations. API/tool failures keep reports already generated and give an error with direct-command fallback. Tool validation rejects unknown functions, extra fields, command injection in tickers, invalid modes and invalid formats.

## Configuration

Add these to the ignored `.env.bot` for a local agent preview, or use cloud configuration for deployment:

```dotenv
BOT_AGENT_ENABLED=true
OPENROUTER_API_KEY=
OPENROUTER_MODEL=
AGENT_MAX_ROUNDS=6
AGENT_MAX_TOOL_CALLS=12
AGENT_MAX_TOKENS=1200
AGENT_TIMEOUT_SECONDS=90
```

Choose an explicit model supporting tools from the [OpenRouter tool-compatible model list](https://openrouter.ai/models?supported_parameters=tools). The client uses the [OpenRouter tool-calling protocol](https://openrouter.ai/docs/guides/features/tool-calling), sends tools on every turn, returns each result with its matching tool_call_id, preserves reasoning_details when provided, and requires providers to support requested parameters. The API key is sent only as the OpenRouter Authorization header. Research tools cannot read secrets, invoke a shell, modify configuration, send arbitrary messages, or execute orders.

Defaults bound each request to six model calls and twelve tool calls. Tools run sequentially, duplicate successful analyses within a request reuse results, and model output tokens are bounded per call. The deadline is checked between calls; an in-progress local renderer cannot be forcibly interrupted. Limits bound work, not an exact currency spend. Each request starts a fresh tool context; process failure before outbox staging can cause a new API charge on a durable retry. Source dates come from stored production inputs; the agent does not fetch live broker/company facts or create new mode-specific rankings.

## Cloud deployment

Both `workers/bot/wrangler.jsonc` and `wrangler.agentic.jsonc` enable the agent on the **same existing screenerx-telegram Worker**, queues, container, R2 bucket and Neon database. The production default is `z-ai/glm-4.7-flash` with reasoning disabled. Direct commands and scheduled refresh continue in the same runtime. Future automatic releases retain agent mode.

1. Push the production build to `deploy/cloudflare-20261013` to run the existing deployment workflow. It validates the Python agent, refresh and Worker tests before deployment. The optional manual workflow must be available on the default branch for GitHub's workflow-dispatch UI; the automatic production route does not require merging to the default branch.
2. Configure encrypted GitHub repository secret **SCREENERX_OPENROUTER_API_KEY**. The existing **SCREENERX_CLOUDFLARE_DEPLOY_TOKEN** supplies Cloudflare deployment access. Keep all other existing cloud secrets, including Telegram and DATABASE_URL.
3. Install the configured key using `python scripts/configure_agent_cloud.py`, which writes Cloudflare and encrypted GitHub secrets without printing their values. Automatic deployment retains the Cloudflare secret. The optional **Deploy ScreenX OpenRouter agent** workflow permits another explicitly selected model. No API key is written to public configuration or source.
4. Wait for the Cloudflare container rollout. If the idle engine still serves the preceding image/config, POST `/internal/engine/restart` with ENGINE_SECRET, then check `/internal/engine/health`. Restart refuses active refresh/delivery leases. Inputs/state remain in R2/Neon.
5. Verify health reports **agent_enabled=true**, **agent_configured=true**, and the current renderer version, then issue an actual `/ask` command. Health checks configuration presence, not OpenRouter key validity or model availability.

The daily cloud refresh and stored input bundle remain available. To disable natural-language analysis, set `BOT_AGENT_ENABLED=false` in the production configuration and deploy it. Direct commands remain usable. No local scheduled tasks are required.

For a machine with Docker and Wrangler configured, equivalent deployment commands from `workers/bot` are:

```text
npx wrangler secret put OPENROUTER_API_KEY --config wrangler.agentic.jsonc
npx wrangler deploy --config wrangler.agentic.jsonc --var OPENROUTER_MODEL:YOUR_MODEL_ID
```

Wrangler prompts for the secret; do not put its value in command-line arguments or commit it. The existing Windows workspace uses cloud CI for container builds because Docker is not installed locally.

## Validation

```text
python -m unittest tests.test_agent tests.test_analysis_modes tests.test_telegram_bot tests.test_reporting_tables
cd workers/bot
npm run check
npm test
```

Provider tests use HTTP fixtures and consume no OpenRouter credits. Production validation additionally checks a real OpenRouter request against the saved production bundle without sending a test message to Telegram.


Reasoning can be controlled with AGENT_REASONING_ENABLED=true/false; leave it empty/default to preserve the provider default. Set it only for a compatible model. The agent executes tools sequentially in its own loop, without sending parallel_tool_calls (some low-cost providers reject that parameter with require_parameters=true). Responses reaching the token limit are treated as incomplete and keep their original reports attached. See scripts/benchmark_agent.py for the bounded model benchmark.


Benchmark (2026-10-13): production uses z-ai/glm-4.7-flash with reasoning disabled for reliable tool orchestration; inclusionai/ling-3.0-flash is the cheaper/faster alternative with a coverage miss in repeated tests. Results and token forecasts are in output/agentic-benchmark/report.md and forecast.json. This recommendation concerns tool coverage; manual spot checks found factual errors in generated financial commentary. Original engine reports remain authoritative and generated summaries are labeled as AI.

Production API requests reject providers above $0.10 per million input tokens, $0.50 per million output tokens, or any per-request surcharge using [OpenRouter max_price routing](https://openrouter.ai/docs/guides/routing/provider-selection#max-price). The serialized context is capped at 100 KB; model rounds, tool calls and output tokens have separate limits. These are per-request work and pricing limits, not a monthly dollar cap. Change the OpenRouter key's own credit limit if a total account ceiling is required.
