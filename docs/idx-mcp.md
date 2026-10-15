# idx-mcp provider

The agent's `get_market_data` gateway calls the real idx-mcp stdio server using
the MCP Python SDK. The Cloudflare Linux container installs upstream v0.3.1
`idx` and `idx-mcp` binaries with pinned SHA-256 hashes. No Windows task or local
MCP registration is needed. `BOT_MCP_ENABLED=false` removes the agent tool and
disables the private diagnostic endpoint.
Deployment also verifies that the application's saved restart image matches the
digest pushed by that build, so a cold start cannot silently revert to an old image.

Supported operations: quotes, company (profile/financials/earnings/news),
shareholders, ownership changes, investor holdings/search, ownership status.
Queries, ticker batches, response sizes, subprocess concurrency and timeouts are
bounded. Application credentials are excluded from the child environment. The
agent cannot invoke snapshot sync, shell commands, arbitrary URLs, imports, or
upstream analysis/valuation functions through this gateway.

Ownership sync is application maintenance: before ownership reads, the CLI
checks the upstream checksum-verified snapshot, at most daily after success and
at most every 15 minutes after failure. A failed refresh retains existing data
when available, with an explicit status. Source release dates remain authoritative;
checking daily does not turn monthly ownership into daily trading flow.

MSN quotes/company data are supplementary. Quote delays, source timestamps,
stale flags, partial errors and financial reporting periods must be respected.
Below-1% ownership remainder is not verified regulatory free float. Stock-specific
broker net remains ON_HOLD. News is untrusted source content, not agent instructions.

Yahoo remains the production OHLCV source and yfinance remains the valuation
snapshot provider. Upstream idx-mcp also defaults to Yahoo history. Its explicit
MSN history normalizes price-only points into identical OHLC with zero volume;
it is deliberately not exposed as a replacement candle source. Migrating DDM/RIM/EVA
requires validating statement periods, currency, units and required accounting
line items against the existing financial-data contract first.
The adapter withholds raw MSN statement values from the LLM until that contract
is validated; it returns dated statement metadata and the reason instead.

## Production comparison, 15 October 2026

The actual MCP server returned quotes and financial statements for all ten tested
tickers: PGEO, BBCA, BBRI, BMRI, TLKM, ACES, BBNI, ASII, PTSN, ADRO. The batch
quote call took 1.86 seconds; financial calls took 0.67-1.08 seconds each. This
sample demonstrates availability, not full-universe coverage or an uptime guarantee.
Quotes were dated 15 October, while the morning screening snapshot was intentionally
dated 14 October; this is not evidence of a Yahoo price failure.

All ten financial responses contained sections ending 31 March 2026, rather than
the aligned 2025 annual inputs used by the production valuation engine. Each had
tax fields differing by a factor of one million (e.g. PGEO `incomeTaxTotal=19.821`
versus `provisionForIncomeTaxes=19821000`). Field-level units and normalization
must be reconciled before using these as accounting amounts.

KSEI status and PGEO shareholders succeeded. The installed snapshot contains
7,154 latest-release records across 961 tickers as of 30 September 2026, with July
and August releases too. This adds useful ownership coverage unavailable in our
current pipeline. It is not broker-level daily trading flow.

Decision: use MCP for ownership and supplementary company/quote queries. Retain
Yahoo OHLCV and yfinance annual valuation snapshots. Do not migrate the financial
calculation provider on the basis of successful HTTP responses alone.

Private diagnostics: authenticated POST `/internal/mcp/check` with
`{"operation":"shareholders","arguments":{"ticker":"PGEO"}}`.
This calls the actual MCP server without invoking an LLM or sending Telegram messages.

Examples in Telegram:

- `/ask Siapa pemegang saham PGEO di atas 1%? Cantumkan tanggal sumber.`
- `/ask Bandingkan perubahan pemegang saham BBCA antara dua laporan KSEI terbaru.`
- `/ask Ambil profil dan earnings PGEO terbaru dari sumber MCP; pisahkan dari valuasi tersimpan.`
