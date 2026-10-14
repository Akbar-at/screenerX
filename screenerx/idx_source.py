"""Dated IDX enrichment, adapted from nichsedge/idx-bei's MIT-licensed client.

Source: afdb5b039b1e437e73cf67a126032523ee0b5770/python/src/idx/core/client.py.
Attribution/license: bundled idx_be_license.txt.
Exchange-wide broker activity is never represented as per-stock broker net flow.
"""
import base64
import hashlib
import json
import math
import os
import threading
import time
from functools import lru_cache
from datetime import datetime
from pathlib import Path

import httpx
from .engine import InputError,day
from .fetch import JAKARTA,symbol_for

BASE='https://www.idx.co.id/primary'
HEADERS={'accept':'application/json, text/plain, */*','accept-language':'en-US,en;q=0.9','referer':'https://www.idx.co.id/'}
PROFILES=('chrome','chrome124','chrome120','safari18_0')
PATHS={'stocks':'/TradingSummary/GetStockSummary','brokers':'/TradingSummary/GetBrokerSummary',
       'profiles':'/ListedCompany/GetCompanyProfiles','ratios':'/DigitalStatistic/GetApiDataPaginated'}


def scalar(value):
    if isinstance(value,bool):return None
    if value is None or value=='': return None
    try: result=float(value)
    except (ValueError,TypeError): return None
    return result if math.isfinite(result) else None


def validate_payload(dataset,payload,asof):
    if not isinstance(payload,dict) or not isinstance(payload.get('data'),list) or not payload['data']:
        raise InputError('IDX response contains no data records')
    records=payload['data'];seen=set()
    identity={'stocks':'StockCode','brokers':'IDFirm','profiles':'KodeEmiten','ratios':'code'}[dataset]
    for row in records:
        if not isinstance(row,dict) or not isinstance(row.get(identity),str) or not row[identity].strip():
            raise InputError('IDX record identity missing')
        code=row[identity].strip().upper()
        if code in seen: raise InputError('IDX duplicate record identity')
        seen.add(code)
        if dataset in ('stocks','brokers'):
            if day(str(row.get('Date','')).split('T')[0],'IDX session')!=asof:
                raise InputError('IDX returned a different trading session')
            fields=('Value','Volume','Frequency')+ (('Close','ForeignBuy','ForeignSell') if dataset=='stocks' else ())
            if any(scalar(row.get(k)) is None or scalar(row[k])<0 for k in fields):
                raise InputError('IDX market field missing, negative or invalid')
    expected=payload.get('recordsTotal')
    if dataset!='ratios' and expected is not None and expected!=len(records):
        raise InputError('IDX dataset is incomplete')
    if dataset=='ratios':
        total=payload.get('meta',{}).get('totalItems')
        if type(total) is not int or total!=len(records): raise InputError('IDX financial pagination is incomplete')
    return records


class IDXSource:
    def __init__(self,cache='output/idx-cache',archive_url=None,secret=None,transport=None,sleep=time.sleep):
        self.root=Path(cache);self.root.mkdir(parents=True,exist_ok=True)
        self.archive_url=archive_url;self.secret=secret;self.transport=transport;self.sleep=sleep
        self.lock=threading.RLock();self.memory={};self.failures={}

    @classmethod
    def from_env(cls):
        bundle=os.getenv('INPUT_BUNDLE_URL','')
        return cls(os.getenv('BOT_IDX_CACHE','output/idx-cache'),
                   bundle.rstrip('/').removesuffix('/internal/bundle')+'/internal/idx-cache' if bundle else None,
                   os.getenv('ENGINE_SECRET'))

    def _request(self,path,params):
        from curl_cffi import requests
        get=self.transport or requests.get
        for attempt,profile in enumerate(PROFILES):
            try:
                response=get(BASE+path,params=params,headers=HEADERS,impersonate=profile,timeout=20)
                if response.status_code==200:
                    if len(response.content)>8*1024*1024: raise InputError('IDX response too large')
                    self.sleep(1)
                    return response.content
                if response.status_code not in (403,429,500,502,503,504):
                    raise InputError(f'IDX source HTTP {response.status_code}')
            except InputError: raise
            except Exception:
                pass
            if attempt<len(PROFILES)-1: self.sleep(min(2**attempt+attempt*.5,8))
        raise InputError('IDX browser-compatible requests failed; source unavailable')

    def _decode(self,envelope,dataset,asof):
        if envelope.get('dataset')!=dataset or envelope.get('as_of')!=asof.isoformat():
            raise InputError('IDX cache identity mismatch')
        raw=base64.b64decode(envelope['raw_base64'],validate=True)
        if hashlib.sha256(raw).hexdigest()!=envelope['sha256']: raise InputError('IDX cache checksum mismatch')
        payload=json.loads(raw);records=validate_payload(dataset,payload,asof)
        if dataset in ('stocks','brokers'):
            for row in records:
                for key in ('Value','Volume','Frequency','Close','ForeignBuy','ForeignSell'):
                    if key in row: row[key]=scalar(row[key])
        return {'records':records,'evidence':{k:v for k,v in envelope.items() if k!='raw_base64'}}

    def fetch(self,dataset,asof,force=False):
        if dataset not in PATHS: raise InputError('Unknown IDX dataset')
        asof=day(str(asof),'IDX requested date')
        from .core_service import completed_cutoff
        if asof>completed_cutoff(): raise InputError('Incomplete or future IDX session forbidden')
        key=(dataset,asof.isoformat())
        with self.lock:
            if not force and key in self.memory: return self.memory[key]
            if not force and self.failures.get(key,0)>time.monotonic():
                raise InputError('IDX source cooling down after a failure; try again later')
            path=self.root/asof.isoformat()/(dataset+'.json')
            try:
                if not force and path.exists():
                    value=self._decode(json.loads(path.read_text(encoding='utf-8')),dataset,asof)
                    self.memory[key]=value;return value
                if not force and self.archive_url:
                    with httpx.Client(timeout=20) as client:
                        response=client.get(self.archive_url+'/'+asof.isoformat()+'/'+dataset+'.json',headers={'Authorization':'Bearer '+str(self.secret or '')})
                    if response.status_code==200:
                        envelope=response.json();value=self._decode(envelope,dataset,asof)
                        self._save(path,envelope);self.memory[key]=value;return value
                    if response.status_code!=404: raise InputError('IDX durable cache unavailable')
                params={'date':asof.strftime('%Y%m%d'),'start':0,'length':9999}
                if dataset=='profiles': params={'start':0,'length':9999}
                if dataset=='ratios':
                    params={'urlName':'LINK_FINANCIAL_DATA_RATIO','periodQuarter':4,'periodYear':asof.year-1,
                            'type':'yearly','isPrint':'false','cumulative':'false','pageSize':1000,'orderBy':'','search':'','pageNumber':1}
                raw=self._request(PATHS[dataset],params)
                response_hashes=[hashlib.sha256(raw).hexdigest()]
                # Follow provider pagination explicitly; never accept a first page as a full universe.
                if dataset=='ratios':
                    payload=json.loads(raw);records=payload.get('data',[]);total=payload.get('meta',{}).get('totalItems')
                    pages=1
                    while isinstance(total,int) and len(records)<total:
                        pages+=1
                        if pages>20: raise InputError('IDX ratio pagination exceeds bound')
                        page_raw=self._request(PATHS[dataset],{**params,'pageNumber':pages})
                        response_hashes.append(hashlib.sha256(page_raw).hexdigest());chunk=json.loads(page_raw)
                        extra=chunk.get('data',[])
                        if not extra or chunk.get('meta',{}).get('totalItems')!=total:
                            raise InputError('IDX ratio pagination changed or stopped')
                        records.extend(extra)
                    if pages>1: payload['data']=records;raw=json.dumps(payload,allow_nan=False).encode('utf-8')
                envelope={'dataset':dataset,'as_of':asof.isoformat(),'captured_at':datetime.now(JAKARTA).isoformat(),
                          'source_url':BASE+PATHS[dataset],'params':params,'sha256':hashlib.sha256(raw).hexdigest(),
                          'response_sha256s':response_hashes,
                          'raw_base64':base64.b64encode(raw).decode('ascii')}
                value=self._decode(envelope,dataset,asof)
                if self.archive_url:
                    with httpx.Client(timeout=30) as client:
                        response=client.put(self.archive_url+'/'+asof.isoformat()+'/'+dataset+'.json',
                                            headers={'Authorization':'Bearer '+str(self.secret or '')},json=envelope)
                    if not response.is_success: raise InputError('IDX evidence could not be archived')
                self._save(path,envelope);self.memory[key]=value;self.failures.pop(key,None)
                return value
            except Exception as error:
                self.failures[key]=time.monotonic()+300
                if isinstance(error,InputError): raise
                raise InputError('IDX source or cache validation failed') from None

    @staticmethod
    def _save(path,envelope):
        path.parent.mkdir(parents=True,exist_ok=True);temporary=path.with_suffix('.tmp')
        temporary.write_text(json.dumps(envelope,allow_nan=False),encoding='utf-8');temporary.replace(path)

    def stock_metrics(self,ticker,asof,reference=True,force=False):
        ticker,_=symbol_for(ticker);asof=day(str(asof),'as_of')
        result={'ticker':ticker,'as_of':asof.isoformat(),'source':'IDX daily summaries',
                'broker_net_status':'ON_HOLD','datasets':{},'errors':{},'evidence':{}}
        names=['stocks','brokers']+(['profiles','ratios'] if reference else [])
        for name in names:
            try:
                data=self.fetch(name,asof,force=force);result['evidence'][name]=data['evidence']
                result['datasets'][name]={'status':'AVAILABLE','records':len(data['records'])}
                field={'stocks':'StockCode','profiles':'KodeEmiten','ratios':'code'}.get(name)
                if field:
                    row=next((r for r in data['records'] if r[field].strip().upper()==ticker),None)
                    if row is None: result['datasets'][name]['status']='TICKER_NOT_FOUND'
                    result[name]=row
                else:
                    result['brokers']=sorted(data['records'],key=lambda r:r['Value'],reverse=True)[:5]
                    result['broker_total_value']=sum(r['Value'] for r in data['records'])
            except InputError as error:
                result['datasets'][name]={'status':'UNAVAILABLE'};result['errors'][name]=str(error)
        row=result.get('stocks')
        if row:
            result['net_foreign_volume']=row['ForeignBuy']-row['ForeignSell']
            bid=scalar(row.get('Bid'));offer=scalar(row.get('Offer'))
            result['snapshot_spread']=(offer-bid)/((offer+bid)/2) if bid and offer and 0<bid<=offer else None
        return result


@lru_cache(maxsize=1)
def get_idx_source():
    return IDXSource.from_env()
