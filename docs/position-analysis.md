# Existing-position questions

`/ask PGEO dengan average 855, buy or sell or hold?` routes to OpenRouter with the
whole question. The agent must call `analyze_position` for average-cost arithmetic
and `analyze_stock` for supporting research. It answers the holding question first;
supporting charts and tables follow.

`analyze_position` uses the stored, dated daily close, not a live quote. Returns are
gross percentages before fees and slippage. No total rupiah P&L is calculated
without a quantity. Exact comparison directions and valuation model values come
from the tool. Missing prices produce an unavailable-data error.

The existing-position answer must state a provisional conditional stance, separate
adding from holding, explain evidence and invalidation, and ask about the horizon
when unspecified. New-entry reward/risk and hypothetical entry stops do not
automatically determine exits for existing holdings. Valuations remain unreviewed;
broker net remains on hold.

Average-cost questions that skip the position tool or omit an opening action are
given one repair attempt within existing round/time/token limits. Continued failure
is reported explicitly instead of accepting a generic summary. This guard does
not certify the correctness of every sentence produced by the LLM.
