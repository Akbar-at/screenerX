# CSV input schemas

UTF-8 comma-delimited CSV. Numeric fields contain plain decimal numbers without currency symbols or thousands separators. Dates YYYY-MM-DD. Boolean fields true/false. Empty optional fields mean missing. Duplicate primary keys fail the input load; malformed data exits nonzero rather than silently continuing.

The generated demo shows full working inputs. To create header-only templates:

```bash
python examples/make_templates.py data/templates
```

## prices.csv — one row per ticker/session

Required: `ticker,date,open,high,low,close,volume,traded_value_idr,source,corporate_actions_checked`

Optional: `bid,ask,tradable,traded_value_basis` (tradable defaults true; false excludes).

Prices IDR/share; volume shares; traded value IDR, regular market only. Do not put lots in volume or millions of IDR in turnover. Quotes are optional, but absence produces provisional execution status. Bid/ask must be decision-date quotes, not historical or live quotes mixed into another date's screen. A latest valid quote can be carried in that decision session row only with your team's explicit timestamp/quality review.

Default minimum120 sessions, longer if configured indicators require it. Histories should be corporate-action-consistent with current levels and execution prices; `corporate_actions_checked` confirms your review. Do not mix total-return-adjusted historical prices with unadjusted volume/levels. When importing Yahoo adjusted prices, consistently account for splits and dividend adjustment; do not assume every downloaded price basis is appropriate for stop/target analysis.

The tool derives the session calendar from the union of provided price dates. It rejects gaps relative to that calendar but cannot detect a session missing from *every* ticker. Validate your export against the official IDX trading calendar upstream. Zero volume/traded value is permitted as an observed nontrading session, not a placeholder for missing data.

All records after `--as-of` are excluded from calculations. A decision-date row must exist. Source names are explicit: config defaults WSJ, but a separately labeled profile can accept Yahoo/manual/etc. That change is a deliberate source-policy amendment to your WSJ-first handoff.

## valuations.csv — one row per ticker

Required headers:

`ticker,sector,valuation_date,price_date,valuation_price,price_source,valuation_source,validated,critical_flags,eva,ddm,rim,levels_date,support,stop_anchor,resistance1,resistance2,levels_source`

Optional: `stressed_fair_value,breakout_level`.

- `eva/ddm/rim`: IDR/share reviewed method output, empty for unavailable/not applicable. At least one valid method required. For bank/financial sector, EVA must be empty. Your team must run DDM Re>g/dividend applicability, RIM book-value/growth checks and EVA capital checks before attesting validated. The MVP does not reconstruct these models from financial statements.
- `valuation_date`: date the model inputs/results were reviewed; not a substitute for statement publication dates in your retained source workbook. No future/stale valuation accepted. Default maximum age30 calendar days.
- `price_date/valuation_price/price_source`: must exactly match the screen's latest date/close/source. EVA is price-sensitive; refresh outputs rather than editing only the CSV price metadata.
- `valuation_source/levels_source`: meaningful nonempty source or artifact references. Retain detailed model assumptions and original filings externally.
- `validated`:true only after your team's checks; `critical_flags` nonempty excludes the ticker. Missing values are never guessed.
- `levels_date`: frozen prior to signal date. Breakout/reclaim detection must occur after this date. Do not retroactively move resistance to make a trade pass.
- `support`: analyst support. `stop_anchor`: structural invalidation anchor at/below support, positive. Program subtracts configured buffer. `resistance1`: nearest meaningful overhead target, above support; `resistance2`: optional next higher target. Do not skip a nearer resistance to inflate R/R.
- `breakout_level`: frozen price ceiling/pivot needed for breakout mode. An already established breakout can be retested within configured window, but a close back below its level invalidates that event.
- `stressed_fair_value`: optional lowest fair value under predeclared Re/g sensitivities; imported, not recomputed. Missing means no stress credit.

Valuation verdict precedence: unreliable excluded; HIGH when methods>=configured count, current MOS>selected MOS and dispersion below high threshold; OVERVALUED when price>F*(1+fair band); FAIR when price>=F*(1-fair band); other reliable names MED. This resolves the handoff's overlapping FAIR/MED definitions explicitly.

## brokers.csv — one row per ticker/date/broker

Required: `ticker,date,broker,net_value_idr,market,source`.

`market` must be regular. `net_value_idr` signed IDR value, positive buys, negative sells. For every decision-window session provide **every configured favored, avoided and mixed broker**, including explicit0 when the underlying full export confirms no activity. Missing row is missing coverage, never silently zero. Additional brokers are accepted but ignored by cohort scoring.

A top-buyer/top-seller screenshot is generally insufficient. A broker absent from a truncated table is not known to have zero activity. Full underlying summary/export coverage is required. Short/long windows overlap; they are calculated separately, never added. Investor type is not inferred from broker identity; classifications are your versioned research preferences.

## Conditional execution plans

The engine chooses the highest-scoring valid setup per ticker, with R/R then setup name as tie-break. Entry is the first legal tick above signal-day high, with configurable additional ticks. It is a conditional next-session stop-limit reference, not a current fill: if price gaps above this maximum entry or below invalidation, cancel/re-screen. Expire after configured sessions; no order automation exists.

Support reversal uses confirmed historical pivot tests plus current rebound; by default all clustered historical tests must preserve lows, latest low must not break the most recent test, Stoch RSI and MACD must cross, and volume must confirm. MACD “approaching” does not pass. Breakout/retest and failed-breakdown reclaim have separate structure rules and do not require oversold oscillators. Resistance1/2 and stop anchor are analyst inputs for every family.

Net R/R includes estimated buy/sell fees and entry/target/stop slippage. For close stops, the displayed net R/R remains an estimate; actual next-session execution can be much worse. No backtest, lot sizing, automatic partial fill or exchange price-limit simulation is claimed. TP fraction/expiry are exported plan instructions, not executed actions.


Public-API imports may set `traded_value_basis=close_times_volume_estimate`. This is a price-volume proxy, not actual regular-market turnover, and forces PROVISIONAL status for affected windows. Existing files without this column attest `actual_regular` as required by the original schema. Do not remove the estimate label to bypass verification. See public-api.md.
