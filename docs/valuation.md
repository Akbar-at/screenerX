# Automatic, unreviewed valuation estimates

The estimator defaults to **WSJ annual income statements, balance sheets and cash flows**, with no company-data fallback. See [WSJ mapping/access](wsj.md). Yahoo supplies price history/FX, and company financials only with an explicit `--financial-provider yfinance` selection. It retains normalized source snapshots, hashes and per-year model traces. The financial adapter follows [yfinance's documented statement interfaces](https://ranaroussi.github.io/yfinance/reference/yfinance.financials.html).

## Inputs and timing

Select the latest common annual income/balance date at least90 days before the requested price date, with a maximum age of550 days. Cash flow must match that same annual date. The reporting lag is configurable and is only a publication heuristic. Latest-retrieved statements may be restated; this feed does not establish historical point-in-time availability. The output separates retrieval/valuation date, statement date and comparison price date. Do not use these snapshots to claim a backtested historical valuation.

For WSJ, use aligned common equity, common-stockholder income and common dividends. Annual average diluted/basic shares are retained as that basis, not claimed as period-end shares. The optional Yahoo adapter uses period-end ordinary shares. WSJ gaps are never filled from Yahoo. Current quote-summary EPS, book value and shares are deliberately not substituted for aligned financials. Prices must be IDR. USD monetary inputs are translated at a validated completed `USDIDR=X` daily close at or before the price date, at most5 calendar days old. Shares and ratios are not converted; source financial currency, model currency, FX rate/date and the underlying FX observations are retained. Forward forecasts remain IDR with constant FX; this is a screening translation, not a model of future FX or historical financial-statement translation. Unsupported currencies or missing/stale/wrong-direction FX remain errors. Offline runs require a saved FX snapshot. Missing inputs never become zero.

## Models

- **DDM:** grow observed annual common dividends for the configured forecast horizon, discount each at cost of equity, then add the discounted Gordon terminal value: `D_n * (1+terminal_growth) / (cost_of_equity-terminal_growth)`. Earnings stress applies to initial dividends. No positive dividends or payout above positive common earnings makes DDM unavailable; the model does not silently extrapolate an unsustainable payout.
- **RIM:** common book equity plus discounted residual income. Initial ROE is annual common earnings times the scenario earnings multiplier divided by ending common equity. Excess ROE fades linearly over the forecast horizon to the cost of equity in the following year. Each year's residual income is `earnings - cost_of_equity * beginning_book`. Ending book follows clean surplus: `beginning_book + earnings * (1-payout)`. Terminal residual income is zero. Observed payout is capped at100% with a warning; missing dividends use the explicit default payout assumption.
- **EVA:** invested capital is common equity plus minority interests plus total debt minus cash and cash equivalents. NOPAT is operating income times `(1-assumed_tax_rate)` times the scenario earnings multiplier. Hold initial ROIC constant; forecast invested capital grows at scenario growth. EVA is `NOPAT - WACC * beginning_invested_capital`. Enterprise value is initial invested capital plus discounted EVA plus the discounted terminal EVA perpetuity. Bridge to common equity by subtracting debt and minority interests and adding cash. Divide by the explicitly recorded statement share-count basis. Financial-sector firms and unknown sectors are excluded; missing required bridge inputs prevent EVA.

The RIM structure follows [CFA Institute's residual-income definition](https://www.cfainstitute.org/insights/professional-learning/refresher-readings/2026/residual-income-valuation). The EVA structure follows [Damodaran's economic-value-added valuation framework](https://pages.stern.nyu.edu/~adamodar/New_Home_Page/invfables/eva.htm). This implementation is a screening approximation: ending-equity ROE, clean-surplus accounting, unadjusted accounting capital, assumed tax/WACC, persistent terminal excess ROIC, nonoperating assets and minority-interest market values all require analyst reconciliation.

## Assumptions and output

Default five-year scenarios:

| Scenario | Cost of equity | WACC | Forecast growth | Terminal growth | Earnings multiplier |
|---|---|---|---|---|---|
| Bear |15%|13%|0%|2%|0.80|
| Base |12%|10%|4%|3%|1.00|
| Bull |10%|9%|6%|4%|1.10|

Tax defaults to22%; missing payout to40%. The production command (or the standalone estimator's `--use-reported-tax`) first tries aligned `Tax Provision / Pretax Income`, requiring positive pretax income and a ratio between0% and60%. Missing/abnormal effective tax retains the configured assumption with an explicit warning and source label. Financial-sector EVA stays excluded. Discount rates, growth and fallback parameters remain configurable forward assumptions, not issuer-specific capital-cost measurements, statutory tax verification or issuer guidance. Terminal growth must be below both discount rates. Scenario names are stresses, not guaranteed price bounds; negative economic profit can respond differently to discount changes. Defaults need calibration before investment use.

Only positive finite method values enter the descriptive base mean. Dispersion is `(max-min)/mean`; above50% it is flagged `UNRELIABLE_ESTIMATE`. One-method estimates remain unreviewed and have no independent model corroboration. MOS is `1-price/mean`; it is a model output, not a verified discount. Fair/under/over valuation uses a10% band. Bear/bull means use the same base method set; if a method becomes unavailable under stress, the scenario mean remains blank.

`estimates.csv` includes `validated=false`, missing-model reasons and warnings. `models/` contains selected input row names and every year's forecast and terminal values. `raw/` contains normalized yfinance statement snapshots; these are not audited issuer filings. `errors.csv` retains ticker-level failures. Partial coverage writes all usable estimates and exits nonzero. Existing output directories are preserved.

The research CLI joins estimates only at the matching price/date, with unreviewed status. Technical ranking and targets remain independent. The full composite screen still requires reviewed valuations, analyst-frozen structural levels, broker coverage and execution evidence; automatic estimates do not grant that attestation.
