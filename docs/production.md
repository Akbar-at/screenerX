# Production pipeline using live market data

Run `python -m screenerx.production --wsj-pages data/wsj-pages-2026-10-12` to use captured WSJ financials and fresh Yahoo prices/FX. WSJ is the default company provider; without saved pages the adapter tries direct WSJ access, currently blocked by an HTTP401 challenge in this workspace. It does not fall back to Yahoo company data. The previous company adapter requires `--financial-provider yfinance`. See [WSJ access/mapping](wsj.md). A custom `--tickers` list or `--universe path.csv` (ticker column) controls scope. A new timestamped directory retains every run; `--output` can specify another new directory. Existing directories are never overwritten.

## Completion and data quality

- Discover the latest completed trading session from BBCA's Yahoo history, falling back to BMRI if the reference request fails. Before18:00 Jakarta, exclude today's candle. Use actual returned timestamps, so weekends and missing holiday candles are handled without inventing a trading calendar. Reference data more than10 calendar days behind the cutoff is rejected. An explicit `--as-of` is supported and each ticker must have that exact session.
- Fetch400 calendar days of daily OHLCV; verify IDX symbol, IDR currency, Jakarta timezone, coherent prices and volume. Per-ticker failure remains visible; there is no replacement with synthetic candles or a different date. Turnover is an estimate of close times volume, with its basis retained.
- Read WSJ annual statements from accessible pages or explicit saved captures, validating source URLs, ticker, periods, units and currency. Preserve WSJ row mappings and retrieval metadata. Select an aligned income/balance period meeting the reporting-lag and statement-age rules. Retain the original normalized snapshots and hash every source. Annual average shares, captured-page freshness and possible statement restatements remain limitations, not historical evidence.
- Translate USD-reporting monetary model inputs to IDR with `USDIDR=X`. Use a positive completed daily close at or before the comparison price date, no more than5 calendar days old. Never use today's in-progress FX candle; never convert share counts. Save observations, source, direction, rate and rate date in the run. Future FX is held constant, not forecast. Unsupported currencies fail explicitly.
- Calculate DDM/RIM/EVA with explicit forward assumptions. Use aligned reported effective tax where positive pretax income and a bounded effective rate allow it; retain a labeled configured fallback otherwise. Banks/financial firms have no EVA; missing/unsustainable dividends have no DDM. Missing individual models remain blank. The full valuation CSV covers every successfully estimated ticker, independently of technical shortlist membership.
- Produce the research shortlist, exclusions and quality checks for every requested ticker, including failures. Broker flow remains ON_HOLD. Reviewed valuation attestation and execution/quote verification remain unavailable; this command does not submit orders or label unreviewed estimates as reviewed.

`run.json` records REAL_MARKET_DATA mode, separate price/company providers and saved-page/direct-request retrieval mode, timestamps, software versions, stage status, requested/covered universe, FX evidence and hashes. COMPLETE means no requested price/valuation coverage failure occurred. PARTIAL preserves usable results and errors with exit code2; FAILED preserves the error manifest. The CLI does not silently reuse a previous successful run or treat failed input as zero. Model disagreement, missing methods and unverified execution remain warnings even in a COMPLETE pipeline.

## Artifacts

| Artifact | Purpose |
|---|---|
| `report.md` | Live-data overview, technical shortlist and all valuation estimates |
| `top10.csv` | Up to ten technically qualifying watchlist entries with joined valuation estimates |
| `valuations.csv` | All usable valuations, currency/rate, tax basis, method omissions and warnings |
| `data-quality.csv` | Coverage for each requested ticker, statement age, methods, FX date and status |
| `inspection.csv` | Technical exclusions and qualifying entries below the result limit |
| `run.json` | Stage status, versions, coverage errors and evidence hashes |
| `session-discovery.json` | Reference price series and the selected completed session |
| `market-data/` | Price CSV, normalized source payloads, errors and import audit |
| `valuations/raw/`, `valuations/fx/`, `valuations/models/` | Financial/FX source snapshots and per-year valuation traces |

Live source data is real market data. Intrinsic values, future growth, discount rates and execution costs are estimates or assumptions. The default universe is a watchlist, not complete exchange coverage. yfinance access and financial field availability can change; the run records what was actually retrieved. Annual statements do not replace current interim filings or establish historical publication timing. Analyst review and issuer-filing reconciliation remain necessary to satisfy the full composite screen's existing reviewed-valuation contract.
