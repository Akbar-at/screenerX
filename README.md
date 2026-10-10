# screenerX

Minimal Python CLI for an IDX research shortlist: **up to ten qualifying tickers**, ranked by configurable fundamental/broker/technical/execution scores, with conditional entry, TP1, optional TP2 and stop-loss prices. No external Python dependencies. Python3.10+; validated on3.12.

## Public API prices

```bash
python -m screenerx.fetch --tickers BBCA BMRI ANTM \
  --as-of 2026-10-08 --output data/yahoo-2026-10-08
```

Yahoo's unauthenticated daily chart endpoint maps IDX symbols to `.JK`. It is not a supported official API contract. The adapter saves prices, raw payloads/hashes, errors and a derived profile explicitly accepting Yahoo prices. It does not supply valuations or broker flows. Turnover is explicitly estimated; quotes are absent; corporate actions must be reviewed. See [coverage and usage](docs/public-api.md). These inputs alone cannot establish a verified composite screen.

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
