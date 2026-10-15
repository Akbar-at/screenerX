# idx-mcp provider

The agent's `get_market_data` gateway calls the real idx-mcp stdio server using
the MCP Python SDK. The Cloudflare Linux container installs upstream v0.3.1
`idx` and `idx-mcp` binaries with pinned SHA-256 hashes. No Windows task or local
MCP registration is needed. `BOT_MCP_ENABLED=false` removes the agent tool and
disables the private diagnostic endpoint.

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

Private diagnostics: authenticated POST `/internal/mcp/check` with
`{"operation":"shareholders","arguments":{"ticker":"PGEO"}}`.
This calls the actual MCP server without invoking an LLM or sending Telegram messages.

Examples in Telegram:

- `/ask Siapa pemegang saham PGEO di atas 1%? Cantumkan tanggal sumber.`
- `/ask Bandingkan perubahan pemegang saham BBCA antara dua laporan KSEI terbaru.`
- `/ask Ambil profil dan earnings PGEO terbaru dari sumber MCP; pisahkan dari valuasi tersimpan.`
