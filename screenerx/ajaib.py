"""Capture the public endpoints observed in Ajaib's website client.

Snapshots only: no login, private broker requests, historical backfills or orders.
"""
import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

from .engine import InputError
from .fetch import fetch_json, symbol_for

BASE='https://external-api.ajaib.co.id/api/v1/public/investment-experience/'


def result_of(payload):
    if not isinstance(payload,dict) or payload.get('err_code')!='EC0000000' or not isinstance(payload.get('result'),dict):
        raise InputError('Ajaib returned an unsuccessful or malformed response')
    return payload['result']


def main(argv=None):
    parser=argparse.ArgumentParser(description='Fetch Ajaib public ticker universe and current info/detail snapshots. No broker history or EVA/DDM/RIM outputs.')
    parser.add_argument('--tickers',nargs='+',required=True)
    parser.add_argument('--output',required=True,help='New directory to preserve source snapshots')
    args=parser.parse_args(argv)
    try:
        tickers=[symbol_for(t)[0] for t in args.tickers]
        if len(tickers)!=len(set(tickers)): raise InputError('Duplicate ticker')
        folder=Path(args.output)
        if folder.exists(): raise InputError('Output directory already exists')
        folder.mkdir(parents=True); (folder/'raw').mkdir()
        sources=[]; failures=[]; snapshots={}
        def capture(route,params,name):
            url=BASE+route+'?'+urlencode(params)
            payload,raw=fetch_json(url,provider='Ajaib')
            (folder/'raw'/name).write_bytes(raw)
            result=result_of(payload)
            sources.append({'url':url,'raw_file':name,'sha256':hashlib.sha256(raw).hexdigest()})
            return result
        universe=capture('asset/codes',{'asset_type':'STOCK'},'universe.json')
        codes=universe.get('codes')
        if not isinstance(codes,list) or not codes or not all(isinstance(x,str) for x in codes):
            raise InputError('Invalid stock universe')
        (folder/'tickers.json').write_text(json.dumps(codes,indent=2)+'\n')
        for ticker in tickers:
            try:
                if ticker not in codes: raise InputError('Ticker absent from returned universe')
                info=capture('asset/info',{'asset_type':'STOCK','code':ticker},ticker+'-info.json')
                if info.get('code')!=ticker: raise InputError('Wrong ticker in info response')
                detail=capture('asset/detail',{'asset_type':'STOCK','code':ticker},ticker+'-detail.json')
                snapshots[ticker]={'info':info,'detail':detail}
                print(f'{ticker}: captured current info and detail; no broker flow')
            except (InputError,ValueError,TypeError,OSError) as exc:
                failures.append({'ticker':ticker,'reason':str(exc)})
                print(f'{ticker}: FAILED: {exc}',file=sys.stderr)
        (folder/'snapshots.json').write_text(json.dumps(snapshots,indent=2)+'\n')
        report={'provider':'Ajaib public website endpoints; no published API support contract verified','fetched_at':datetime.now(timezone.utc).isoformat(),'universe_count':len(codes),'snapshot_count':len(snapshots),'sources':sources,'failures':failures,'broker_flow_available':False,'valuation_models_available':False,'historical_daily_series_available':False,'notes':['Current snapshots must not be assigned to a historical Yahoo decision date.','Ratios and per-share metrics are not audited EVA/DDM/RIM valuations.','Traded-value market scope and detail timestamp are not established.','Universe may include securities not eligible for trading; it is not an eligibility declaration.']}
        (folder/'api-run.json').write_text(json.dumps(report,indent=2)+'\n')
        print(f'Universe: {len(codes)} codes. Snapshots: {len(snapshots)}. Saved to {folder}')
        return 2 if failures else 0
    except (InputError,OSError,TypeError) as exc:
        print(f'Error: {exc}',file=sys.stderr);return 2


if __name__=='__main__':sys.exit(main())
