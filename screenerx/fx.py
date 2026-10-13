"""Validated daily FX snapshots; rates are target-currency units per source unit."""
from datetime import datetime, timedelta, timezone

from .engine import InputError, day, number


def validate_fx(snapshot,currency,asof,max_age_days=5):
    if snapshot.get('base_currency')!=currency or snapshot.get('quote_currency')!='IDR':
        raise InputError('FX currency pair/direction mismatch')
    if snapshot.get('symbol')!=currency+'IDR=X' or snapshot.get('provider')!='yfinance':
        raise InputError('Unexpected FX source/symbol')
    rate=number(snapshot.get('rate'),'FX rate')
    rate_date=day(snapshot.get('rate_date'),'FX date')
    if rate<=0 or rate_date>asof or (asof-rate_date).days>max_age_days:
        raise InputError('FX rate must be positive, nonfuture and no more than 5 days old')
    return rate


def fetch_fx(currency,asof,timeout=20):
    if currency!='USD': raise InputError(f'Unsupported financial currency: {currency}')
    import yfinance as yf
    symbol=currency+'IDR=X'; stock=yf.Ticker(symbol)
    # FX trades beyond the IDX close; today's daily bar is still in progress.
    cutoff=min(asof,datetime.now(timezone.utc).date()-timedelta(days=1))
    frame=stock.history(start=(cutoff-timedelta(days=10)).isoformat(),
                        end=(cutoff+timedelta(days=1)).isoformat(),interval='1d',
                        auto_adjust=False,actions=False,keepna=True,timeout=timeout)
    meta=stock.history_metadata
    if meta.get('symbol')!=symbol or meta.get('currency')!='IDR':
        raise InputError('Unexpected FX history metadata')
    observations=[]
    for stamp,row in frame.iterrows():
        if stamp.date()>cutoff: continue
        try: rate=number(row['Close'],'FX close')
        except InputError: continue
        if rate>0: observations.append({'date':stamp.date().isoformat(),'close':rate})
    if not observations: raise InputError('No completed FX observations')
    observations.sort(key=lambda r:r['date']); latest=observations[-1]
    snapshot={'provider':'yfinance','symbol':symbol,'base_currency':currency,'quote_currency':'IDR',
              'rate':latest['close'],'rate_date':latest['date'],
              'fetched_at':datetime.now(timezone.utc).isoformat(),'observations':observations,
              'basis':'completed daily close; constant-FX translation for IDR forecasts'}
    validate_fx(snapshot,currency,asof)
    return snapshot
