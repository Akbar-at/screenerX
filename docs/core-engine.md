# Coverage-qualified and explainable core engine

The pure `CoreEngine` separates inspection, required-input coverage, quality checks and ranking. It is independent of network calls, filesystem storage, Neon, Workers and Telegram. `CoreService` supplies source/storage adapters and a private/local HTTP facade. WSJ is the default financial provider; explicitly selected yfinance financials are supported under the same coverage gates. Broker flow remains ON_HOLD.

## Screen an explicit universe

```powershell
python -m screenerx screen --prices data/prices.csv --wsj-pages data/wsj-pages-2026-10-12 --universe data/idx-companies.csv --as-of 2026-10-09 --output output/core-run
```

The universe CSV needs a ticker column. Every requested company is retained even if data is missing. This accepts an entire supplied IDX common-equity universe without a hardcoded15-company limit. It does not claim that a complete exchange universe was discovered from existing price files. An authoritative listing import is a separate upstream input.

Instead of WSJ pages, `--snapshots path/to/wsj/raw` accepts normalized WSJ snapshots and checks available referenced evidence-file hashes. Statement source URL/hash references remain required. Provider mismatches cannot fall back to Yahoo company data. `--fx-snapshot` supplies dated FX where necessary.

Outputs: core-run.json, top10.csv, coverage.csv, report.md and tickers/<symbol>.json for every company. Existing outputs are preserved. Production's WSJ path now uses this core for its main top10. The explicitly selected Yahoo financial-provider path remains separately labeled legacy research.

## Full coverage is scoped to research

Every selected entry must have a current sourced coherent OHLCV candle, the configured history minimum (120 by default), session alignment, matching WSJ identity and all three statement source references, fresh aligned financials, every applicable valuation model, at least two models, complete sensitivity scenarios, technical indicators, liquidity data, an observed stop/entry/target interval and configured cost estimates.

Quality gates reject excessive model disagreement, modeled value/price outliers, low liquidity and nontradable/no-volume candles. The value-only discount filter applies when enabled. Coverage remains required even if a scoring component has zero weight.

EVA is NOT_APPLICABLE only for a known financial sector. DDM is NOT_APPLICABLE only for explicitly observed zero annual common dividends. Missing dividends, unsustainable baseline payout, missing inputs or nonpositive modeled values are UNAVAILABLE; they cannot bypass coverage. A nonpayer with only one model fails the minimum-two-model rule. If four entries pass, four are selected and six slots stay unfilled.

An observed calendar cannot detect a session missing from every company; a supplied official calendar is stronger. Standalone inspection without one labels ticker-local continuity. Statements retrieved today are not historical publication proof. Quotes, actual regular-market turnover, analyst review, original-strategy signal confirmation and broker coverage remain separate readiness facts. Current outputs are research-only. Low reward/risk and weak trend are visible cautions. The original composite CLI retains its stricter reviewed-valuation/broker/execution gates.

## Explainable scoring

The separate core profile uses fundamental50%, technical40%, liquidity10%. These are declared weights, not broker weights redistributed around missing data.

| Component | Raw score |
|---|---|
| Fundamental MOS |50 if MOS meets the configured threshold;25 if positive; otherwise0 |
| Model agreement |30 for dispersion<=15%;20 at<=30%;10 otherwise; the independent quality gate still applies |
| Bear-case MOS |20 if stressed MOS meets the configured threshold |
| Technical trend |25 close>SMA20;25 SMA20>SMA60 |
| Technical momentum |20 MACD>signal;15 Stochastic K>D |
| Volume |15 if volume multiple meets its threshold |
| Liquidity |min(100,100 times median turnover/full-credit turnover); full credit at5 times minimum turnover by default |

Each contribution is raw score times declared weight/100; the total is their sum. Missing required inputs have no aggregate score. Ties use MOS, turnover, then ticker. Markdown explains factor values, thresholds, awarded points, weighted contributions and important cautions in plain sentences. JSON retains full scenarios, traces, source hashes and a comparison with the next-ranked company. Adjust `core-config.json` with `--profile`; production accepts `--core-profile`.

## Any IDX ticker lookup

```powershell
python -m screenerx inspect --ticker TLKM --prices data/prices.csv --wsj-pages data/wsj-pages-2026-10-12 --as-of 2026-10-09 --output output/TLKM.json
python -m screenerx inspect --ticker SMGR --live --output output/SMGR.json
```

Lookup is independent of shortlist membership. Symbols normalize to uppercase IDX names; .JK is accepted. Live mode fetches Yahoo prices and uses a saved WSJ capture when available, otherwise requests WSJ directly. WSJ failures still return available technical evidence and missing-data reasons. Statuses distinguish AVAILABLE, PARTIAL, NOT_CACHED and SOURCE_UNAVAILABLE. Invalid syntax is rejected; a network failure is not proof that a ticker does not exist. The supported scope is IDX, not arbitrary international exchanges. Standalone lookup leaves top10 membership unknown without a ranked universe/run.

## Local/private API

```powershell
python -m screenerx serve --prices data/prices.csv --wsj-pages data/wsj-pages-2026-10-12 --universe data/idx-companies.csv --as-of 2026-10-09
```

Default bind:127.0.0.1:8000. GET /health, /v1/top10, /v1/coverage, /v1/tickers/TLKM. Live inspection requires server --allow-live and request ?live=true. It can involve slow provider requests, so future Telegram orchestration should enqueue it. Cloud authentication, Neon/R2 adapters and cloud jobs remain deployment work; this facade returns ordinary JSON for those adapters.

## Verification and real-data result

Tests cover score reconciliation, applicability, missing evidence, stale/gapped/invalid prices, source mismatch, zero-weight gates, deterministic ties, unfilled slots, future exclusion, CLI preservation, any-symbol lookup and HTTP errors. Saved WSJ inputs through October9,2026 produced four covered entries from15 supplied companies; six slots stayed empty. A live SMGR lookup outside the watchlist returned partial evidence and exposed WSJ failures. This validates the provided inputs, not full-exchange acquisition.
# Explicit Yahoo company-financial mode

The user-authorized all-universe Yahoo run selects `financial_provider='yfinance'` explicitly. WSJ remains the default. The Yahoo mode verifies ticker/symbol identity, retains raw snapshot file hashes, and applies the same statement alignment, currency/FX, model applicability, scenario, technical and liquidity gates. It does not relabel Yahoo inputs as WSJ or weaken missing-data rules.

```powershell
python -m screenerx core screen --financial-provider yfinance --prices output/market-wide-2026-10-12/prices.csv --universe output/market-wide-2026-10-12/universe.csv --as-of 2026-10-09 --snapshots output/yfinance-all-2026-10-12/raw --fx-snapshot output/yfinance-all-2026-10-12/USDIDR.json --output output/yahoo-core-replay
```

`screenerx.yahoo_market` collects and resumes company snapshots and creates the valuation and core reports together. Once Yahoo reports a rate limit, pending uncaptured companies are deferred rather than flooding the service. Rerunning after a cooldown reuses captures and attempts remaining gaps.

