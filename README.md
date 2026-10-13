# screenerX

Python CLI for an IDX research shortlist: **up to ten qualifying tickers**, with conditional entry, TP1, optional TP2 and stop-loss prices. The full screen ranks fundamental/broker/technical/execution evidence. Price-only research works independently while broker flow and reviewed valuations are on hold. Python 3.10+; yfinance downloads require the dependencies below.

## Production runs with real data

The core engine now requires complete research coverage before selecting the top10 and explains every score contribution and exclusion. Inspect **any IDX ticker**, including companies outside the shortlist:

```powershell
python -m screenerx inspect --ticker SMGR --live
python -m screenerx screen --prices data/prices.csv --wsj-pages data/wsj-pages-2026-10-12 --universe data/idx-companies.csv --output output/core-run
```

Missing WSJ data remains explicit; it is never filled with Yahoo company metrics. Every requested company gets an inspection result. Results are not padded to ten. See [core coverage, scoring and API](docs/core-engine.md).

```powershell
python -m pip install -r requirements.txt
python -m screenerx.production
```

Fetches fresh Yahoo/yfinance prices and uses **WSJ company financials** for DDM/RIM/EVA by default. Broker flow stays **ON_HOLD**. There is no Yahoo company-data fallback. Direct WSJ requests currently encounter an HTTP401 challenge in this workspace; use captured WSJ pages for a concrete run:

```powershell
python -m screenerx.production --wsj-pages data/wsj-pages-2026-10-12
```

Captured WSJ excerpts retain source URLs, table units, retrieval method and years. These are saved source data, not a continuously refreshed WSJ API. Yahoo remains the price-history/FX provider. `--financial-provider yfinance` explicitly selects the previous company adapter. See [WSJ mapping/access](docs/wsj.md). Reported tax is used where usable; forward growth, discount rates and fallback model parameters remain assumptions.

Each run gets a new timestamped directory under `output/production/`, including `report.md`, `top10.csv`, all `valuations.csv`, `data-quality.csv`, exclusion reasons and a hashed source manifest. **COMPLETE** means the requested data pipeline completed; models remain **UNREVIEWED_ESTIMATES** and results remain **RESEARCH_ONLY**. Data failures produce PARTIAL/FAILED status and a nonzero exit. See [production usage and coverage](docs/production.md).

```powershell
python -m screenerx.production --tickers BBCA BMRI ANTM ITMG --output output/my-production-run
python -m screenerx.production --universe my-watchlist.csv
```

`my-watchlist.csv` needs a `ticker` column. The default universe is the disclosed15-stock watchlist, not all IDX listings. Use `--assumptions path.json` for your valuation profile and `--as-of YYYY-MM-DD` for an explicit completed price session.

## Generate with available data

```powershell
python -m pip install -r requirements.txt
python -m screenerx.research --output output/research
```

Downloads unadjusted daily OHLCV through yfinance for a disclosed 15-stock IDX watchlist. Use `--tickers BBCA BMRI ANTM` to choose the universe and `--as-of YYYY-MM-DD` for a completed session. The default date is the latest weekday after the 18:00 Jakarta cutoff; an exchange holiday requires an explicit completed session. Missing candles are reported rather than silently replaced.

Generate directly from an existing price CSV without network access:

```powershell
python -m screenerx.research --prices data/prices.csv --output output/saved-research
```

Produces `report.md`, `top10.csv`, `inspection.csv`, resolved configuration and hashed run metadata. Downloaded data and per-ticker errors are retained under `market-data/`. Partial downloads generate results for successful tickers and exit with code 2 to expose the missing coverage.

All candidates are **RESEARCH_ONLY**. Broker flow and reviewed valuations are **ON_HOLD**, with no fabricated values or composite-score renormalization. The research score uses observed trend, momentum and volume with a minimum of 50/100; ties use liquidity then ticker. Entry is above the signal high, stop below the preceding ten-session low, and targets use preceding rolling highs above entry. These mechanically derived levels require analyst review; targets stay blank when no observed overhead resistance exists. Low reward/risk rows remain watchlist entries with explicit warnings. This mode does not assert the full screen's setup, broker, valuation or execution gates have passed.

## Automatic valuation estimates

The valuation estimator calculates **unreviewed** DDM, RIM and EVA from WSJ annual statements by default. Broker flow remains on hold. Generate a combined research report from existing prices:

```powershell
python -m screenerx.research --prices data/prices.csv --estimate-valuations --wsj-pages data/wsj-pages-2026-10-12 --output output/estimated-research
```

Or generate valuations separately, then join them without another download:

```powershell
python -m screenerx.valuation --prices data/prices.csv --as-of 2026-10-09 --wsj-pages data/wsj-pages-2026-10-12 --output output/valuations
python -m screenerx.research --prices data/prices.csv --as-of 2026-10-09 --valuation-estimates output/valuations/estimates.csv --output output/combined
```

Use `--assumptions path.json` for the standalone estimator or `--valuation-assumptions path.json` for research. Copy [valuation-config.json](valuation-config.json) to change discount rates, growth, tax and payout. Saved financial snapshots support offline recalculation via `--snapshots output/valuations/raw` or research's `--valuation-snapshots output/valuations/raw` with `--estimate-valuations`. The declared provider must match the snapshots; old Yahoo snapshots require `--financial-provider yfinance` and cannot be relabeled as WSJ.

Outputs include per-method and scenario prices, descriptive mean, MOS, dispersion, explicit missing-model reasons, hashes, normalized financial snapshots and complete forecast traces. Financials require aligned annual periods; USD monetary inputs are translated to IDR with a validated dated FX snapshot. Other currencies remain unsupported. Live runs fetch FX automatically; offline standalone runs need `--fx-snapshot path/to/USDIDR.json` and research needs `--valuation-fx-snapshot path/to/USDIDR.json`. Missing data stays unavailable. A90-day reporting lag is a conservative heuristic, not proof of historical publication. Statements may be restated. Estimates remain `validated=false`; they do not pass the full screen's reviewed-valuation gate or change technical ranking. See [model formulas and limitations](docs/valuation.md).

## Public API prices

```bash
python -m screenerx.fetch --tickers BBCA BMRI ANTM \
  --as-of 2026-10-08 --output data/yahoo-2026-10-08
```

The default adapter uses yfinance and maps IDX symbols to `.JK`, explicitly disabling automatic OHLC adjustment. `--provider chart` retains the previous direct chart adapter. The adapter saves prices, normalized payloads/hashes, errors and a derived profile explicitly accepting Yahoo prices. It does not supply reviewed valuations or broker flows. Turnover is explicitly estimated; quotes are absent; corporate actions must be reviewed. See [coverage and usage](docs/public-api.md). These inputs alone cannot establish a verified composite screen.

## Ajaib public snapshots

Ajaib's website exposes working public ticker/info/detail endpoints. Capture its universe and current stock ratios without login:

```bash
python -m screenerx.ajaib --tickers BBCA BMRI ANTM \
  --output data/ajaib-snapshots
```

This adapter saves source JSON and hashes. It does not claim that current ratios are reviewed valuations or that broker history is available. Ajaib Terminal's free Broker Summary UI is confirmed; a usable broker export/API remains unverified. See [Ajaib findings and coverage](docs/ajaib.md).

## Quick start

For local Ajaib login and broker-response capture, see [local browser setup](docs/local-browser.md).

From the existing `/workspace/screenerX` checkout:

```bash
python examples/generate_demo.py /tmp/screenerx-demo
python -m screenerx \
  --prices /tmp/screenerx-demo/prices.csv \
  --valuations /tmp/screenerx-demo/valuations.csv \
  --brokers /tmp/screenerx-demo/brokers.csv \
  --config /tmp/screenerx-demo/config.json \
  --as-of 2026-07-15 \
  --output output/demo
```

The demo uses **synthetic DEMO tickers**, not real securities, quotes or recommendations. It creates14 tickers:12 qualify,2 fail; the best10 are selected. The generator's weekdays are only a synthetic calendar, not the IDX holiday calendar.

For real inputs, use your own filenames, actual decision trading date, and `config.json`. Every run must use a new output directory so prior evidence is retained. Private data can live in ignored `data/`.

```bash
python -m screenerx --prices data/prices.csv --valuations data/valuations.csv \
  --brokers data/brokers.csv --as-of YYYY-MM-DD --output output/my-run
python -m unittest discover -s tests -v
```

## What it calculates

- Mean of applicable, reviewed EVA/DDM/RIM values; dispersion, valuation verdict, margin of safety and MOS grid. Bank/financial EVA is rejected. Invalid/critical-flagged valuations are excluded.
- Full favored-cohort net flows over configurable5/20-session windows, persistence, buying breadth and turnover-normalized strength. Favored/avoided/mixed flows stay visible. CC defaults to mixed because the supplied reports disagree.
- Wilder ATR and RSI, Stochastic RSI14/14/3/3, MACD12/26/9, volume ratios, confirmed historical support tests, and support reversal/breakout/reclaim signals.
- Tick-rounded entry above signal-candle high, stop below analyst's frozen structural anchor, targets at frozen resistance, estimated cost-adjusted reward/risk and conditional order metadata. Stop basis is explicit. This tool does not simulate fills or submit orders.
- Normalized0–100 component scores weighted35/30/25/10 by default. All reliable fundamental verdicts may compete: expensive names remain visibly OVERVALUED and lack MOS credit. The default TP is technical resistance, not a valuation guarantee. Gates for positive/persistent flow, confirmed technical structure, liquidity and reward/risk apply before ranking, even with a zero component weight.

## What it imports

The MVP imports your team's **reviewed valuation method outputs** and **structural levels identified before the signal date**. Its optional public-API importer fetches daily prices only. It does not parse financial statements, compute EVA/DDM/RIM from raw filings, infer beneficial ownership, automatically discover resistance targets, backtest or validate the edge statistically. `validated=true` is an analyst attestation that method applicability, reconciliation, assumptions and financial provenance have been reviewed; it is not a claim that this program audited the source statements.

If you have no reviewed method values or complete broker records, the full three-perspective screen is not available yet. See [data options](docs/data-options.md) for a practical collection workflow. An OHLC-only feed cannot supply the broker edge.

## Files produced

- `top10.csv`: selected ticker plans, component/composite scores, valuation/flow/indicator/execution evidence and warnings.
- `inspection.csv`: excluded/provisional/qualified-but-unselected tickers and concrete reasons. Empty selection is a valid result; the tool never pads ten slots.
- `config.resolved.json`: exact settings used.
- `run.json`: version, decision date, source-file hashes, configuration hash and counts.

Unset fees, order size or bid/ask prevent verified selection. Use `--include-provisional` to include clearly marked candidates with incomplete execution evidence. They sort after eligible candidates; missing cost estimates never become zero fees. Default fees/order size are explicit **assumptions**, not your verified tariff: buy0.15%, sell0.25%, entry/target slippage0.10%, stop slippage0.20%, intended orderRp1m. Configure these before relying on net R/R. Trade size is a capacity assumption, not a rounded share/lot allocation.

## Configuration

[Automatic daily refresh](docs/daily-refresh.md) uses Cloudflare Cron at 18:30 Jakarta, Neon job state, and atomic R2 publication. It refreshes prices, indicators, valuation/MOS, rankings and charts, and the bot loads the latest published report automatically. The cloud pipeline is deployed and its container health check passed with real data. Annual financial captures retain their actual source dates.

The [Telegram bot](docs/telegram-bot.md) returns Indonesian descriptive research, candlestick/valuation PNGs, and single-stock or multi-page PDFs. Preview without a token:

```powershell
.\.venv\Scripts\python.exe -m screenerx.telegram_bot preview --run-dir output/top10-yfinance-latest-2026-10-12/core --prices output/top10-yfinance-latest-2026-10-12/prices.csv --command '/top10'
```

The Cloudflare Worker + Python Container + Neon/Queues/R2 deployment is live. GitHub Actions builds and deploys the image in the cloud. Telegram delivery awaits the BotFather token and allowed user/chat IDs; see the setup guide.

Run company financials across an existing full-universe price collection using Yahoo explicitly:

```powershell
python -m screenerx.yahoo_market --universe output/market-wide-2026-10-12/universe.csv --prices output/market-wide-2026-10-12/prices.csv --as-of 2026-10-09 --output output/yfinance-all
```

This retains per-company raw snapshots and hashes, calculates DDM/RIM/EVA where inputs pass validation, and writes an explainable coverage-qualified ranking. Three workers collect statements; reruns reuse saved snapshots. Broker flow stays on hold. WSJ remains the default elsewhere; `python -m screenerx core screen --financial-provider yfinance --snapshots <raw-directory>` selects Yahoo explicitly for saved-data screening.

Market-wide real-data collection (resumes saved raw responses on rerun):

```powershell
python -m screenerx.market --output output/market-wide --wsj-pages data/wsj-pages-2026-10-12
```

This discovers the Ajaib public stock-code universe rather than using the 15-name watchlist, fetches Yahoo prices with three workers, and assesses every returned ticker. The broker list can contain stale symbols and is not verified as the complete official IDX listing. Every failed price fetch and missing WSJ financial statement remains visible. Saved WSJ statements supply DDM/RIM/EVA; missing statements never fall back to Yahoo financials. The coverage-qualified report is in `core/report.md`, with per-ticker evidence and explanations. Broker flow remains `ON_HOLD`.

Edit or copy [config.json](config.json); pass another complete profile with `--config path.json`. Every supported knob is active. Unknown or missing keys are rejected. This is a compact implementation profile; the earlier research JSON with additional future valuation/backtest parameters is not accepted as a CLI profile.

- `weights`: nonnegative percentages summing100. Components are normalized independently against their configured maximum points before blending.
- `ranking`: result count and minimum score. Score ties use net R/R (gross only for provisional rows), liquidity, then ticker.
- `fundamental`: discount requirement (off by default), entry MOS, conviction/dispersion/fair bands, outlier ratios, age, sources and sensitivity credit. Example: enable `require_discount` for the value-only list. Enable target cap separately for value-led plans.
- `broker`: cohorts, windows, normalized-flow threshold, persistence and buyer count. Mixed codes cannot appear in favored/avoided. Removing a code changes required CSV coverage.
- `technical`: modes, support tests/lookback/pivot confirmation, tolerances, indicator periods/cross requirements, volume and entry distance. MACD fast must be below slow; minimum history must cover all windows.
- `execution`: fees/slippage, intended order size, liquidity/spread/participation, net R/R, tick/ATR buffers, stop basis, target cap, expiry and profit-taking fraction. Target cap uses the mean imported fair value, not a separately modeled conservative valuation.
- `scoring`: component subpoints and fundamental MOS/dispersion bands. MOS awards highest qualifying band; dispersion awards first matching ascending band. No missing-data renormalization.

Percentages are decimal fractions except `weights`:0.20=20%,0.0015=0.15%. Prices are IDR/share, turnover IDR, volume **shares**, windows trading sessions, staleness calendar days. Stoch RSI is0–100. Null is unknown, never zero.

Nonnegotiable validity remains: no future inputs, complete required flow windows, matching valuation/current price and source, critical data flags rejected, positive applicable model values, coherent OHLC/levels, positive stop<entry<target, legal regular-board tick rounding. No ordinary ranking control disables these.

## Data and strategy contracts

See [CSV input schemas](docs/inputs.md), [data options](docs/data-options.md), and [source research specification](docs/research-spec.md). The implementation deliberately uses analyst-reviewed levels and values to keep the first version small and auditable. Reports' historical example prices are not loaded as current plans.
