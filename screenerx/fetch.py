"""Public Yahoo chart endpoint -> auditable daily-price CSV.

This endpoint is not an official supported API contract. No authentication,
cookie extraction, quote-summary scraping or proprietary broker endpoints.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from .engine import InputError, day, number

JAKARTA=ZoneInfo('Asia/Jakarta')
HOST='https://query1.finance.yahoo.com'
FIELDS=['ticker','date','open','high','low','close','volume','traded_value_idr','traded_value_basis','bid','ask','source','corporate_actions_checked','tradable']


def symbol_for(ticker):
    ticker=ticker.strip().upper()
    if ticker.endswith('.JK'): ticker=ticker[:-3]
    if not re.fullmatch(r'[A-Z0-9]{1,12}',ticker):
        raise InputError(f'Invalid IDX ticker: {ticker!r}')
    return ticker,ticker+'.JK'


def chart_url(ticker,asof,lookback_days):
    _,symbol=symbol_for(ticker)
    start=datetime.combine(asof-timedelta(days=lookback_days),datetime.min.time(),JAKARTA)
    end=datetime.combine(asof+timedelta(days=1),datetime.min.time(),JAKARTA)
    query=urlencode({'period1':int(start.timestamp()),'period2':int(end.timestamp()),'interval':'1d','events':'div,splits'})
    return HOST+'/v8/finance/chart/'+symbol+'?'+query


def fetch_json(url,timeout=20,retries=2,opener=urlopen,sleeper=time.sleep,provider='Yahoo'):
    for attempt in range(retries+1):
        try:
            request=Request(url,headers={'User-Agent':'screenerX/0.1 public-market-data','Accept':'application/json'})
            with opener(request,timeout=timeout) as response:
                raw=response.read(20*1024*1024+1)
            if len(raw)>20*1024*1024:
                raise InputError('API response exceeds 20 MiB limit')
            try:
                payload=json.loads(raw)
            except (ValueError,UnicodeDecodeError) as exc:
                raise InputError('API returned invalid JSON') from exc
            return payload,raw
        except HTTPError as exc:
            if exc.code in (429,502,503,504) and attempt<retries:
                sleeper(min(2**attempt,4)); continue
            raise InputError(f'{provider} HTTP {exc.code}; check endpoint availability/access/rate limits') from exc
        except (URLError,TimeoutError) as exc:
            # Policy/authentication failures are not solved by unchanged retries.
            raise InputError(f'{provider} connection failed: {exc.reason if isinstance(exc,URLError) else str(exc)}') from exc


def parse_chart(payload,ticker,asof,actions_reviewed=False):
    ticker,symbol=symbol_for(ticker)
    if not isinstance(payload,dict): raise InputError('Invalid chart payload')
    chart=payload.get('chart')
    if not isinstance(chart,dict) or chart.get('error') or not isinstance(chart.get('result'),list) or len(chart['result'])!=1 or not isinstance(chart['result'][0],dict):
        raise InputError('Yahoo chart unavailable or contains an API error')
    result=chart['result'][0]; meta=result.get('meta',{})
    if not isinstance(meta,dict) or not isinstance(meta.get('symbol'),str):
        raise InputError('Invalid chart metadata')
    if meta.get('symbol','').upper()!=symbol or meta.get('currency')!='IDR' or meta.get('exchangeTimezoneName')!='Asia/Jakarta':
        raise InputError('Unexpected symbol/currency/timezone; expected IDX IDR chart')
    timestamps=result.get('timestamp',[])
    indicator_data=result.get('indicators',{})
    quotes=indicator_data.get('quote',[]) if isinstance(indicator_data,dict) else []
    if not isinstance(timestamps,list) or not timestamps or not isinstance(quotes,list) or len(quotes)!=1 or not isinstance(quotes[0],dict):
        raise InputError('No daily price series')
    quotes=quotes[0]
    if any(not isinstance(quotes.get(k),list) or len(quotes[k])!=len(timestamps) for k in ('open','high','low','close','volume')):
        raise InputError('Mismatched daily-series lengths')
    rows=[]; gaps=[]; seen=set()
    for index,stamp in enumerate(timestamps):
        d=datetime.fromtimestamp(number(stamp,'timestamp'),JAKARTA).date()
        if d>asof: continue
        if d in seen: raise InputError('Duplicate daily API timestamps')
        seen.add(d)
        values={k:quotes[k][index] for k in ('open','high','low','close','volume')}
        if any(v is None for v in values.values()):
            gaps.append(d.isoformat()); continue
        values={k:number(v,k) for k,v in values.items()}
        if any(values[k]<=0 for k in ('open','high','low','close')) or values['volume']<0 or not values['low']<=min(values['open'],values['close'])<=max(values['open'],values['close'])<=values['high']:
            raise InputError(f'Invalid daily candle on {d}')
        rows.append({'ticker':ticker,'date':d.isoformat(),**values,'traded_value_idr':values['close']*values['volume'],'traded_value_basis':'close_times_volume_estimate','bid':'','ask':'','source':'Yahoo Finance','corporate_actions_checked':str(actions_reviewed).lower(),'tradable':'true'})
    rows.sort(key=lambda r:r['date'])
    if not rows or rows[-1]['date']!=asof.isoformat():
        raise InputError('No completed candle for requested date; do not silently substitute an older session')
    return rows,{'symbol':symbol,'currency':'IDR','missing_candle_dates':gaps,'corporate_actions_events':result.get('events',{}),'actions_reviewed':actions_reviewed,'turnover_basis':'close_times_volume_estimate','quotes_available':False}


def fetch_yfinance(ticker,asof,lookback_days,timeout=20):
    """Normalize unadjusted yfinance history into the validated chart contract."""
    try:
        import yfinance as yf
    except ImportError as exc:
        raise InputError('Install market-data dependencies: python -m pip install -r requirements.txt') from exc
    _,symbol=symbol_for(ticker)
    try:
        stock=yf.Ticker(symbol)
        frame=stock.history(start=(asof-timedelta(days=lookback_days)).isoformat(),
                            end=(asof+timedelta(days=1)).isoformat(),interval='1d',
                            auto_adjust=False,actions=True,keepna=True,timeout=timeout)
        if frame.empty:
            raise InputError('yfinance returned no history')
        meta=stock.history_metadata
        quotes={key:[] for key in ('open','high','low','close','volume')}
        stamps=[]; events={'dividends':{},'splits':{}}
        for stamp,row in frame.iterrows():
            stamps.append(int(stamp.timestamp()))
            for key in quotes:
                value=float(row[key.title()])
                quotes[key].append(value if math.isfinite(value) else None)
            for column,kind in [('Dividends','dividends'),('Stock Splits','splits')]:
                value=float(row.get(column,0))
                if value and math.isfinite(value):
                    events[kind][str(stamps[-1])]={'date':stamps[-1],'value':value}
        payload={'chart':{'error':None,'result':[{'meta':{
            'symbol':meta.get('symbol',symbol),'currency':meta.get('currency'),
            'exchangeTimezoneName':meta.get('exchangeTimezoneName')},
            'timestamp':stamps,'indicators':{'quote':[quotes]},'events':events}]}}
        return payload,json.dumps(payload,allow_nan=False).encode('utf-8')
    except InputError:
        raise
    except Exception as exc:
        raise InputError(f'yfinance failed for {symbol}: {exc}') from exc


def main(argv=None):
    parser=argparse.ArgumentParser(description='Fetch public Yahoo IDX daily prices. Fundamentals and broker flow are not provided.')
    parser.add_argument('--tickers',nargs='+',required=True,help='IDX symbols, e.g. BBCA BMRI ANTM; .JK optional')
    parser.add_argument('--provider',choices=['yfinance','chart'],default='yfinance')
    parser.add_argument('--as-of',required=True,help='Completed decision session YYYY-MM-DD')
    parser.add_argument('--lookback-days',type=int,default=400)
    parser.add_argument('--output',required=True,help='New directory; existing data are never overwritten')
    parser.add_argument('--timeout',type=float,default=20)
    parser.add_argument('--retries',type=int,default=2)
    parser.add_argument('--actions-reviewed',action='store_true',help='Attest YOU have reviewed split/corporate-action price consistency; no automatic attestation')
    parser.add_argument('--config',default=str(Path(__file__).parent.parent/'config.json'),help='Base screening profile; derived API profile explicitly adds Yahoo as a price source')
    args=parser.parse_args(argv)
    try:
        from .engine import load_config
        asof=day(args.as_of,'as-of'); now=datetime.now(JAKARTA)
        if asof>now.date() or (asof==now.date() and now.hour<18):
            raise InputError('Choose an already completed session; same-day downloads wait until 18:00 Jakarta')
        if args.lookback_days<1 or args.retries<0 or args.retries>5 or args.timeout<=0 or args.timeout>120:
            raise InputError('Invalid lookback/timeout/retry settings')
        tickers=[symbol_for(x)[0] for x in args.tickers]
        if len(tickers)!=len(set(tickers)):
            raise InputError('Duplicate tickers')
        folder=Path(args.output)
        if folder.exists(): raise InputError('Output directory already exists; choose a new directory')
        config=load_config(args.config)
        folder.mkdir(parents=True); (folder/'raw').mkdir()
        rows=[]; errors=[]; sources=[]
        for ticker in tickers:
            url=chart_url(ticker,asof,args.lookback_days)
            try:
                if args.provider=='yfinance':
                    payload,raw=fetch_yfinance(ticker,asof,args.lookback_days,args.timeout)
                else:
                    payload,raw=fetch_json(url,args.timeout,args.retries)
                (folder/'raw'/f'{ticker}.json').write_bytes(raw)
                parsed,quality=parse_chart(payload,ticker,asof,args.actions_reviewed)
                rows.extend(parsed)
                sources.append({'ticker':ticker,'url':url,'sha256':hashlib.sha256(raw).hexdigest(),'rows':len(parsed),**quality})
                print(f'{ticker}: {len(parsed)} daily candles; turnover estimated, bid/ask absent')
            except (InputError,KeyError,TypeError,IndexError,OverflowError,OSError) as exc:
                errors.append({'ticker':ticker,'reason':str(exc)}); print(f'{ticker}: FAILED: {exc}',file=sys.stderr)
        with (folder/'prices.csv').open('w',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=FIELDS); writer.writeheader(); writer.writerows(rows)
        with (folder/'api-errors.csv').open('w',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=['ticker','reason']); writer.writeheader(); writer.writerows(errors)
        config['profile_name']+='__yahoo_prices'
        if 'Yahoo Finance' not in config['fundamental']['allowed_price_sources']:
            config['fundamental']['allowed_price_sources'].append('Yahoo Finance')
        (folder/'screen-config.json').write_text(json.dumps(config,indent=2)+'\n')
        report={'provider':args.provider,'fetched_at':datetime.now(timezone.utc).isoformat(),'as_of':args.as_of,'lookback_days':args.lookback_days,'sources':sources,'errors':errors,'fundamentals_available':False,'broker_flow_available':False,'broker_flow_status':'ON_HOLD'}
        (folder/'api-run.json').write_text(json.dumps(report,indent=2)+'\n')
        print(f'Prices written: {folder / "prices.csv"}. Full screening still requires reviewed valuations, structural levels and broker flows.')
        return 2 if errors else 0
    except (InputError,OSError) as exc:
        print(f'Error: {exc}',file=sys.stderr); return 2


if __name__=='__main__': sys.exit(main())
