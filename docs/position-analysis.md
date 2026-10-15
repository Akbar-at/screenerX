# Existing-position questions

`/ask PGEO dengan average 855, buy or sell or hold?` routes to OpenRouter with the
whole question. The agent calls `analyze_position` for average-cost arithmetic;
that tool attaches a technical/fundamental chart unless research for the ticker
was already attached. It answers the holding question first; supporting media follow.

`analyze_position` uses the stored, dated daily close, not a live quote. Returns are
gross percentages before fees and slippage. No total rupiah P&L is calculated
without a quantity. Exact comparison directions and valuation model values come
from the tool. Missing prices produce an unavailable-data error.

The existing-position answer must state a provisional conditional stance, separate
adding from holding, explain evidence and invalidation, and ask about the horizon
when unspecified. New-entry reward/risk and hypothetical entry stops do not
automatically determine exits for existing holdings. Valuations remain unreviewed;
broker net remains on hold.

After position data is available, the model supplies a structured assessment with
a stance (HOLD, REDUCE, SELL, BUY), condition, selected evidence codes and change
conditions. The server renders exact comparisons, cost, close, gross return, and a
separate adding assessment from tool data. It rejects invented evidence codes and
BUY when the stored entry has not qualified. An unspecified horizon triggers a follow-up question.
Average-cost questions that skip the tool or return an invalid assessment get one
repair attempt within existing limits. Continued failure is reported explicitly.
The LLM chooses the conditional stance and relevant evidence; it does not rewrite
numbers or comparison directions. A conditional stance is still an interpretation,
not a guarantee about future prices.
