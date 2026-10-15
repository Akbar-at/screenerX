"""Position arithmetic and comparisons over a dated research snapshot."""
import math


def positive_number(value):
    return type(value) in (int, float) and math.isfinite(value) and value > 0


def position_context(company, average_price, horizon=None):
    if not positive_number(average_price):
        raise ValueError('Average price must be a finite positive IDR price per share')
    if horizon not in (None, 'short_term', 'long_term'):
        raise ValueError('Invalid holding horizon')
    close=company.get('close')
    if not positive_number(close):
        raise ValueError('Stored closing price unavailable for position analysis')
    def compare(value, reference):
        if not positive_number(value) or not positive_number(reference): return 'UNAVAILABLE'
        return 'ABOVE' if value>reference else 'BELOW' if value<reference else 'EQUAL'
    t=company.get('technical') or {};v=company.get('valuation') or {};p=company.get('plan') or {}
    signal=t.get('macd_signal');macd=t.get('macd')
    momentum=('ABOVE' if macd>signal else 'BELOW' if macd<signal else 'EQUAL') if all(
        type(x) in (int,float) and math.isfinite(x) for x in (macd,signal)) else 'UNAVAILABLE'
    return {
        'ticker':company['ticker'],'as_of':company['as_of'],'price_basis':'stored daily close, not a live quote',
        'average_price_idr':average_price,'close_idr':close,
        'unrealized_gross_return_pct':round((close/average_price-1)*100,4),
        'pnl_basis':'Percentage before fees/slippage; average is user-supplied; quantity not supplied, so no total IDR P&L.',
        'horizon':horizon or 'UNSPECIFIED',
        'comparisons':{'close_vs_sma20':compare(close,t.get('sma20')),
                       'close_vs_sma60':compare(close,t.get('sma60')),
                       'macd_vs_signal':momentum,'close_vs_fair_value':compare(close,v.get('fair_value'))},
        'reference_levels_idr':{k:p.get(k) for k in ('support','resistance','stop_loss_price')},
        'valuation_models_idr':{k:v.get(k) for k in ('ddm','rim','eva','fair_value','bear_value','bull_value')},
        'limitations':['Valuations are UNREVIEWED_ESTIMATES; broker net remains ON_HOLD.',
            'Entry-plan stop and R/R describe a hypothetical new entry, not an agreed exit for this existing position.',
            'Average price alone does not determine buy/sell/hold; horizon and risk tolerance matter.'],
    }
