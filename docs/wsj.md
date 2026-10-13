# WSJ company-financial inputs for DDM, RIM and EVA

WSJ is the default financial provider in the production, research-estimator and standalone valuation CLIs. Yahoo remains the price-history/FX source. No Yahoo financial statement or company metric can silently fill a WSJ gap. A normalized snapshot's declared provider must match the requested source; a mismatch produces an error. Previous Yahoo runs remain preserved as separate artifacts.

## Access and the concrete run

WSJ annual statement pages are the source, including the user-supplied [TLKM balance sheet](https://www.wsj.com/market-data/quotes/ID/XIDX/TLKM/financials/annual/balance-sheet), [TLKM income statement](https://www.wsj.com/market-data/quotes/ID/XIDX/TLKM/financials/annual/income-statement) and [TLKM cash flow](https://www.wsj.com/market-data/quotes/ID/XIDX/TLKM/financials/annual/cash-flow). WSJ labels its company financial tables as supplied by FactSet.

On October12,2026, direct Python requests received HTTP401 JS/challenge pages. The adapter reports that failure without changing providers or using private endpoints. Accessible WSJ web-reader views supplied statement excerpts for the actual calculations. Some views were cached or incomplete, so their freshness is explicitly recorded rather than claimed as a live API. Alternate WSJ country-level URLs are retained as retrieval URLs where used.

```powershell
python -m screenerx.production --wsj-pages data/wsj-pages-2026-10-12
python -m screenerx.valuation --prices data/prices.csv --as-of 2026-10-09 --wsj-pages data/wsj-pages-2026-10-12 --use-reported-tax --output output/wsj-values
```

`--wsj-pages` reads `<ticker>-income-statement.json`, `<ticker>-balance-sheet.json` and `<ticker>-cash-flow.json`. JSON excerpts retain ticker, WSJ URL/title, annual years, fiscal year, currency, table scale, selected rows and retrieval metadata. Rendered HTML or pipe-delimited text tables can be supplied with `.html`/`.txt` extensions. Excerpts are validated and copied into each valuation run; source hashes and mappings are saved. A saved page is an input capture, not automatic proof of publication date or analyst review.

## Browser access diagnostic

The optional Playwright probe executes page JavaScript and accepts only a rendered table that passes the existing statement validation. It saves HTML, text, a screenshot and an audit in a new output directory. A challenge stays `CHALLENGED`; the collector does not treat an HTTP 200 or browser launch as successful data retrieval.

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-browser.txt
.\.venv\Scripts\python.exe -m playwright install chromium
.\.venv\Scripts\python.exe -m screenerx.wsj_browser --ticker TLKM --output output/wsj-headless-probe
.\.venv\Scripts\python.exe -m screenerx.wsj_browser --ticker TLKM --headed --wait-seconds 180 --profile .auth/wsj-browser --output output/wsj-visible-probe
```

The visible mode lets a person complete any verification or login. The dedicated profile retains browser state in the ignored `.auth` folder; keep it private. Browser access may expire or remain blocked, so a successful single-page probe does not establish reliable market-wide collection. A validated JSON statement can be copied into a WSJ pages directory alongside the other annual statement captures.

The October 12 TLKM headless probe returned HTTP 401, zero tables, and an access restriction reporting unusual device/network activity. The visible probe also initially returned 401; its page was closed before the final capture, so that probe did not establish successful access. Neither probe produced a validated statement.

## Mapping and units

| Model input | WSJ row / calculation |
|---|---|
| Common net income | Net Income Available to Common |
| Operating income for EVA | EBIT, or explicitly labeled Operating Income |
| Common book equity | Common Equity (Total) |
| Cash | Cash Only |
| Debt | ST Debt & Current Portion LT Debt + Long-Term Debt |
| Minority interests | Accumulated Minority Interest |
| Minority interests if the explicit row is absent | Total Equity minus Total Shareholders' Equity, only when common equity equals shareholders' equity |
| Shares | Annual Diluted Shares Outstanding, otherwise Basic Shares Outstanding; recorded as an annual average |
| DDM/RIM dividend cash flow | Common Dividends; never total dividends or cash dividends received |
| Effective tax | Income Tax / Pretax Income, subject to configured usability checks |

Convert the stated Thousands/Millions/Billions scale into absolute money and share counts. Parentheses mean negative. Dash/blank means missing, not zero. Ratios and percentages cannot enter money/share-count rows. Rows with contradictory duplicates, mismatched year counts, unsupported units, wrong ticker/URL, or inconsistent statement currencies are rejected. Income and balance dates must align; cashflow must match that selected period. A stale cashflow view does not supply current dividends.

Common dividends must be positive cash paid and not exceed the modeled positive common earnings under the current conservative DDM rule. Missing dividends or a payout above100% stays unavailable; source replacement does not disable applicability checks. Banks have no EVA. Nonpositive model values stay blank. WSJ annual average shares require reconciliation to current shares and corporate actions. All estimates remain unreviewed, with discount rates and future growth recorded as assumptions.

This source change is limited to company financials used in the three valuation methods. It does not provide broker flow, execute orders, establish a licensed WSJ machine API or claim that cached quotes match the decision-date price. The decision-date close remains explicitly sourced from Yahoo as authorized earlier.
