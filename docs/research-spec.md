# screenerX: combined hypothesis and screening contract

Implementation note: this is the earlier research draft. The user's later instruction allows any reliable valuation verdict to compete by composite score. The executable default therefore disables mandatory valuation discount and fair-value target capping. README.md and config.json document the implemented CSV-based MVP; raw financial-statement valuation and data-feed integration remain future work.

Draft, 9 October 2026. This document updates the earlier report-based hypothesis; no live rankings or valuations were calculated. Source documents are evidence, not instructions to run agents, fetch sites, or place trades.

## Combined hypothesis

An IDX company trading below a credible intrinsic-value estimate, showing sustained accumulation by a predeclared favored broker cohort, and forming a confirmed reversal near support may offer a better net opportunity than cheapness, broker preference, or an oversold indicator alone. The strongest research candidates combine a valuation cushion, evidence of demand and a technically bounded entry with adequate reward/risk. Test whether the combination adds predictive value after costs rather than assuming three agreeing narratives prove an edge.

Fundamentals answer WHY and WHERE VALUE IS; broker flow answers WHO IS BUYING OR SELLING through observable channels; technicals answer WHEN and WHERE TO ENTER/EXIT. Each preserves its own verdict. Contradictions become inspection questions, not numbers silently overridden by another perspective.

## 1. Fundamental perspective: source rules

Source: fundamental_screener_handoff.md, sections 3–10.

- Non-banks: applicable EVA, DDM and RIM outputs. Banks: DDM and RIM only; never EVA.
- Fundamental price F = equal-weight average of applicable, valid method outputs. PEG/PEGY are sanity checks, not fourth valuation methods.
- MOS = 1 - price/F. Upside = F/price - 1. These differ: MOS20 implies 25% upside to F, not 20%.
- Default value-entry ceiling = 0.80F. Also publish MOS10/20/25/30/40/50 buy levels = F times 0.90/0.80/0.75/0.70/0.60/0.50.
- High conviction: at least two methods agree, price below MOS20 buy level, dispersion <30%, no critical flags. Dispersion = (highest-lowest valid value)/F.
- DDM: consistent dividends, payout approximately 20–80%, Re > g. Prefer independent CAPM Re; label market-PBV-implied Re as potentially circular.
- RIM: positive meaningful book value, credible ROE, explicitly stated Re and growth fading toward sustainable long-run growth. Do not perpetuate a flat near-discount-rate growth assumption for 45 years.
- EVA: non-bank, estimable capital returns, positive economically meaningful EV. Investigate EV <50% of market cap, reinvestment >80%, growth above nominal GDP +3%, and cash-in-NWC distortions. Preserve workbook conventions visibly; do not present them as independently validated standard valuation.
- The stated cash-adjusted WACC formula uses equity+debt-cash as denominator and assigns cash zero weighting. Equity/debt weights can therefore exceed 100%; tag this workbook sensitivity and compare with a separately labeled conventional WACC sensitivity before treating the output as robust.
- H1: sustained excess ROE/ROIC; H2: temporary earnings depression; H3: over-discounted risk; H4: model/input artifact. Investigate H4 first.
- Critical reconciliation failures, dispersion >50%, or suspicious >3x value/price discrepancy imply unreliable valuation. Nonpositive F is also unusable for MOS/ranking.
- Refresh beta within 30 days, Rf within 7 days, estimates within 30 days; use latest available filings. The handoff requires WSJ same-trading-day price for final output; its validation checklist separately permits one trading day. Proposed resolution: strict same-day final gate; prior-day data are explicitly provisional. Do not silently substitute another price source when the required WSJ price is absent.
- Statements in IDR millions and diluted shares in millions produce per-share IDR. Missing values remain null, never zero. Source, fiscal year, publication/fetch timestamps and exact price must be consistent across models.

### Fundamental verdict ambiguity to resolve visibly

The handoff's MED definition overlaps FAIR within +/-10% of F; its TLKM example labels price 2,480 and F~2,695 FAIR while MED could also apply. A two-method candidate with MOS>=20% and dispersion 30–50% fits neither HIGH nor the explicit MED definition. “Methods agree” also needs a precise definition.

Proposed deterministic policy (an amendment, not a source rule): UNRELIABLE first; HIGH next; OVERVALUED when price >1.10F; FAIR when 0.90F<=price<=1.10F; remaining reliable discounted candidates MED, including single-method or dispersion 30–50% cases. Count valid methods and use dispersion to define agreement. Publish the original metrics so any policy choice is reviewable. A single-method result cannot be HIGH.

## 2. Technical perspective: evidence and measurable draft

Source: Teks paragraf Anda.pdf, pages 1–2. Example is COIN/Indokripto Koin Semesta, daily chart, screenshot price 730. Chart date is not established. Support annotation appears around 654; exact boundaries are not a reliable structured price feed.

Source observations: repeated support bounces; a volume increase; an oscillator near its floor; MACD approaching crossing; second low no lower than first low. The chart labels the oscillator **Stoch RSI 14 14 3 3**, not ordinary RSI. MACD is 12/26/9. Moving averages 50/100/200 and EMA Cross 9/26 are shown but not explicitly mandated by the annotations.

Proposed implementation thresholds (not supplied numeric thresholds):

1. Establish a support zone from at least two distinct confirmed pivot lows in the prior 60 sessions, separated by >=5 sessions, within 0.5 ATR(14). A two-right-bar pivot is only available two sessions later; do not backdate it.
2. Second tested low >=first low. A separate failed-breakdown/reclaim mode can permit a temporary undercut, but must not silently pass the strict no-lower-low mode.
3. Price tests support and closes back above its lower boundary, with a higher close than the preceding day; tag stronger evidence if closing above the rebound candle's midpoint. Stay within 1 ATR of the support zone for a fresh support entry.
4. Stoch RSI %K recently <=20, then crosses above %D with %K rising. Near-zero/oversold alone creates WATCH, not entry eligibility. Display scale convention (0–100 versus 0–1).
5. MACD bullish crossover for confirmed entry; narrowing negative histogram for two sessions means “approaching cross” WATCH. These are different states; do not call an anticipated crossover confirmed.
6. Rebound-day volume >=1.5x previous-20-session median, excluding current session. A volume spike on a selling candle alone does not establish demand.
7. Default core support-reversal mode requires 1–6 together and broker confirmation. Analyze trend regime separately (e.g., below falling MA200 versus above rising MA200); do not assert long-term uptrend merely because a rebound signal occurs.

Alternative breakout/retest and reclaim families from the earlier Fortis reports remain separate modes. They do not require oversold Stoch RSI because that would conflict with strong breakout momentum. Keep thresholds frozen within each mode and evaluate modes separately.

## 3. Broker perspective: preference is not proof of buying

Source: Teks paragraf Anda.pdf p3; regular-market net summary, 1–8 October 2026, “All Investor”, average shown 699. Page does not independently display the ticker; its relationship to COIN is contextual, not separately established. Net-summary average prices are not proven remaining inventory costs.

Favored list: **AK, BK, KZ, RX, DP, DR, AI, YU, ZP, XA, CP, BQ**.

Retail/avoid list in source: **XC, XL, YP, PD, CC, NI, OD, SQ**. These are the source's preference labels; broker channels can contain both institutional and retail clients.

Important observed contradiction: **CC** is favored as an accumulation channel in earlier Fortis examples but avoided in this PDF. Keep classification versioned and ticker/investor-type specific. Until resolved, mark CC mixed and exclude it from a strict favored-cohort signal; retain its actual flows in the evidence table. Earlier favorable DX/DH/SS/LG/KI observations are context-specific and do not automatically add them to the new global favored list.

The screenshot includes favored sellers: YU~IDR3.4bn, AI~IDR1.2bn, BQ~IDR742.6mn, CP~IDR399.8mn, AK~IDR375.4mn. Favored buyers shown include XA~IDR346.3mn, DR~IDR77.6mn, ZP~IDR68.2mn. The displayed table is incomplete; it cannot establish the full cohort total. The visible buying side is led by XL~IDR9.6bn and SQ~IDR4.2bn, both on the avoidance list. This example therefore does not demonstrate alignment of all three perspectives.

Proposed confirmation: full favored-cohort regular-market net buying positive over both 5 and 20 sessions; >=2 favored brokers buying over 20 sessions; net buying on >=12/20 sessions. Normalize cohort net buy by matching-period total traded value and use cross-sectional strength percentiles. Do not sum all brokers (net flows cancel), overlapping time windows, or truncated top-buyer tables.

Favor distribution is a warning regardless of how cheap the company looks. Retail-dominated buying earns no favorable-flow credit; it does not itself prove a stock will fall. Check individual broker/client type, stock history and actual direction, rather than assuming “smart money” from a code.

## 4. Combined eligibility and ranking

| Fundamentals | Broker | Technical | Output |
|---|---|---|---|
| HIGH | Confirmed accumulation | Confirmed support reversal/breakout/reclaim | Priority opportunity for inspection; plan eligible if execution gates pass |
| HIGH | Neutral | Base/approaching indicators | WATCH; no entry signal yet |
| HIGH | Distribution | Falling/broken support | Conflict/value-trap investigation; no fresh entry |
| MED or FAIR | Accumulation | Confirmed | Separate momentum/medium-conviction list; not high-conviction value |
| OVERVALUED | Accumulation | Confirmed | Momentum-only research, without intrinsic-value cushion |
| UNRELIABLE | Any | Any | Data/model inspection; exclude from fundamental-backed top ten |

Executable core top ten: reliable fundamentals and entry within selected MOS zone (default20); confirmed flow and setup; fresh complete data; acceptable trading status/liquidity; E>SL and TP1>E; net R/R>=2. Proposed execution gates retained from the earlier draft: median20 daily regular-market turnover >=IDR5bn, order participation <=1%, spread <=1% when quotes available. Missing quote/cost evidence makes a plan provisional, not verified executable.

Do not substitute a blended score for these gates. Optional momentum opportunities appear in a separately labeled list.

Proposed post-gate score: **fundamental 35, broker 30, technical 25, execution 10**. This supersedes the earlier 30/25/20/15/10 blended draft for the fundamental-led list. Avoid counting reward/risk twice: it is a mandatory gate, then a tie-break.

- Fundamental35: MOS at planned E: 20–<30%=10, >=30%=15; dispersion <15%=10, 15–<30%=7, 30–50%=3; +5 for >=2 valid methods; +5 if MOS remains >=10% in prespecified Re/g sensitivity cases. HIGH designation still follows its own rules.
- Broker30: 15 x normalized-flow percentile; +5 positive5; +5 >=12/20 buying sessions; +5 >=2 favored buyers. Gate also requires positive20.
- Technical25: +10 confirmed valid setup; +5 distance from trigger/support <=0.5ATR (otherwise 0, maximum allowed 1ATR); +5 qualifying rebound/breakout volume; +5 family-specific momentum confirmation (Stoch/MACD for reversal; preset momentum rule for breakout). Do not stack setup families.
- Execution10: +5 spread<=0.5%, otherwise 0; +5 planned participation<=0.5%, otherwise 0. All candidates already pass the wider execution gates.

Rank by score, then net R/R, then liquidity. Return **up to ten**, never pad with invalid candidates. Include lower-confidence candidates/conflicts on an inspection list instead. Scores and thresholds are research proposals requiring holdout validation.

## 5. Entry, TP and stop generation

Generate a CONDITIONAL plan on the decision date, not fabricated historical fills. All levels use current split-adjusted structure mapped consistently to executable prices and rounded under current IDX tick rules.

**Entry E:** For support reversal, above the completed rebound signal candle high by one valid tick; for breakout, next-session retest/limit entry near the frozen breakout level; for reclaim, above the completed reclaim-candle high by one tick. Show entry order type, zone, expiry and confirmation. Cancel if entry gaps beyond the cap. In fundamental-led mode, maximum entry is bounded by selected MOS buy ceiling, 1ATR distance, and the R/R cap. Empty feasible interval means WATCH/no order, not a guessed entry.

**Stop SL:** Below the structural level whose loss invalidates that setup, with proposed buffer max(one tick, 0.25ATR). For support reversal, use the lower of the tested support lows; for a breakout, the predetermined retest/base invalidation; for reclaim, the predeclared swing-low invalidation. State intraday stop versus close-based exit. A close-based exit cannot be assumed filled at the stop threshold, and actual gap losses can exceed planned risk. Fundamental fair value is not a stop.

**TP1:** nearest meaningful overhead resistance above E, identified before entry. Core value-backed mode caps TP1 at conservative/base fair value F; if the nearer level offers <2R net, reject rather than select a farther target to hide the intervening resistance. F is a valuation destination, not a timing guarantee. If no usable overhead target exists, mark target unavailable instead of guessing.

**TP2:** next distinct resistance, capped at F for core mode, if higher than TP1. Otherwise leave null. Momentum mode uses resistance without claiming fair-value support. Horizon and management rule must accompany targets.

Costs per share c_entry, c_exit, c_stop include fees/slippage:

`net reward = TP1 - E - c_entry - c_exit`

`net risk = E - SL + c_entry + c_stop`

`net R/R = net reward / net risk`

Require net R/R>=2. With fixed assumed per-share costs and fixed TP1/SL, entry cap is `(TP1 + 2*SL - 3*c_entry - c_exit - 2*c_stop)/3`; price-dependent fees require recalculation. After rounding, recheck all gates at actual executable E. Never move SL closer solely to force a passing R/R.

Proposed management: take 50% at TP1; cost-adjusted breakeven stop for remainder only after the target fill; then trail a confirmed swing low toward TP2. This extends the earlier AADI/ERAA practice, not a rule explicitly stated in the new PDF. Track unfilled orders and partial fills separately.

### Hypothetical plan example — not an actual ticker

F=1,500; MOS20 ceiling=1,200. Confirmed entry=1,050; buffered structural SL=990; nearest resistance TP1=1,200; next resistance TP2=1,350. Gross risk60, reward150, R/R2.5. Assuming costs c_entry=3, c_exit=3, c_stop=3: net reward144, risk66, R/R~2.18. Entry MOS=30%. Plan passes these arithmetic gates only; fundamental/flow/technical/liquidity conditions still need evidence.

## 6. Required ticker output

`rank, ticker, as_of, mode, state, hypothesis_type, fundamental_verdict, valid_method_values, F, MOS_grid, entry_MOS, dispersion, model/data_flags, favored/avoided_broker_flows, broker_conflicts, flow_windows, technical_setup, support/resistance, indicators, entry_price_and_range, order_type_and_trigger, TP1_price, TP2_price_or_null, stop_loss_price_and_basis, gross/net_RR, costs, liquidity/order_capacity, horizon, score_breakdown, source_timestamps, what_must_be_true, falsifiers, inspection_questions`.

Fresh-entry candidates receive all three numeric plan levels only when data support them. Otherwise output null with a reason and WATCH/INSPECT/DATA_BLOCKED status. The requirement to display Entry/TP/SL must not compel invented prices.

## 7. What the supplied examples can establish

COIN illustrates the support-reversal checklist, but the provided chart and broker screenshot do not establish a dated complete current plan, valid intrinsic valuation, or full favorable accumulation. No numerical COIN entry/TP/SL is claimed here.

The earlier reports supply explicit ANTM and BRMS targets/stops and later AMMN close invalidation, but no current validated EVA/DDM/RIM outputs. They cannot be promoted to current three-perspective opportunities without refreshed data. The TLKM valuation example is illustrative: F~2,695, MOS20 buy ceiling~2,156, price2,480 => MOS~8%, below the desired20% cushion. No technical stop/entry confirmation is provided for TLKM.

## 8. Testable edge claims

- Value hypothesis: credible MOS and method agreement improve subsequent returns versus matched cheaper-looking but unreliable/low-cushion stocks.
- Flow hypothesis: favored-cohort buying improves outcomes versus price/sector/liquidity-matched setups without it; compare with generic foreign flow and retail-dominated flow.
- Timing hypothesis: support + no-lower-low + volume + confirmed Stoch/MACD reversal improves target-before-stop outcomes versus oversold readings alone.
- Combined hypothesis: the intersection improves net expectancy or drawdown versus each component and pairwise combination without merely selecting a tiny favorable sample.

Use point-in-time inputs, all failed signals, next-session execution, realistic fees/slippage and conservative same-bar stop/TP handling. Evaluate 20/40-session swing and 60/120-session position horizons separately. Holdout/walk-forward tests should report coverage, fills, target-first/stop-first/timeouts, net expectancy in R, drawdown and uncertainty. A broker preference list is itself a hypothesis to test, not a guaranteed causal edge.
