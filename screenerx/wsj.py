"""Strict WSJ annual-statement adapter; never falls back to Yahoo financials."""
from __future__ import annotations

import calendar
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .engine import InputError, number
from .fetch import symbol_for

ROUTES={'income':'income-statement','balance':'balance-sheet','cashflow':'cash-flow'}
LABELS={'Operating Income','EBIT','Pretax Income','Income Tax','Income Taxes',
        'Net Income Available to Common','Basic Shares Outstanding','Diluted Shares Outstanding',
        'Cash Only','Common Equity (Total)','Accumulated Minority Interest',
        'ST Debt & Current Portion LT Debt','Long-Term Debt','Common Dividends',
        'Total Equity',"Total Shareholders' Equity",'Loan Loss Provision','Net Interest Income'}


def page_url(ticker,route):
    ticker,_=symbol_for(ticker)
    if route not in ROUTES.values(): raise InputError('Unknown WSJ statement route')
    return f'https://www.wsj.com/market-data/quotes/ID/XIDX/{ticker}/financials/annual/{route}'


def cell(value):
    text=str(value).strip().replace('\u2212','-')
    if text in ('','-','—','–','N/A','n/a'): return None
    if '%' in text: raise InputError('Unexpected percentage in a monetary/share-count row')
    negative=text.startswith('(') and text.endswith(')')
    text=text.strip('()').replace(',','')
    return number(text,'WSJ table cell')*(-1 if negative else 1)


def parse_text(text,ticker,route,retrieval_method='saved_page'):
    """Read WSJ rendered tables or a web-reader text view into a small excerpt."""
    cleaned=re.sub(r'^L\d+:\s*','',text,flags=re.M)
    header=re.search(r'Fiscal year is ([^.]+)\. All values ([A-Z]{3}) (Millions|Billions|Thousands)\.([^\n]+)',cleaned)
    if not header: raise InputError('WSJ page has no supported fiscal-year/currency/unit header')
    years=re.findall(r'\b(?:19|20)\d{2}\b',header[4])
    if not years: raise InputError('WSJ page has no annual year columns')
    rows=[]
    for line in cleaned.splitlines():
        parts=[v.strip() for v in line.split('|')]
        if parts[0] in LABELS and len(parts)>1:
            rows.append({'label':parts[0],'values':parts[1:len(years)+1]})
    title=next((line for line in cleaned.splitlines() if ticker in line and ('Indonesia:' in line or ' - WSJ' in line)),'')
    return {'format':'wsj-table-excerpt-v1','ticker':ticker,'statement':route,'url':page_url(ticker,route),
            'title':title,'financial_currency':header[2],'scale':header[3],'fiscal_year':header[1],
            'years':years,'rows':rows,'bank_statement':any(r['label']=='Loan Loss Provision' for r in rows),
            'retrieval_method':retrieval_method,'retrieved_at':datetime.now(timezone.utc).isoformat() if retrieval_method=='direct_http' else None}


def parse_html(html,ticker,route):
    from bs4 import BeautifulSoup
    soup=BeautifulSoup(html,'html.parser')
    # Scripts/challenge payloads cannot supply a statement table.
    for tag in soup(['script','style']): tag.decompose()
    text=soup.get_text(' ',strip=True)
    fiscal=re.search(r'Fiscal year is [^.]+\.',text)
    units=re.search(r'All values [A-Z]{3} (?:Millions|Billions|Thousands)\.',text)
    if not fiscal or not units: raise InputError('WSJ page is not a financial statement (login/challenge or layout change)')
    table=soup.find('table')
    if table is None: raise InputError('WSJ financial table missing')
    rows=[]; years=[]
    for tr in table.find_all('tr'):
        cells=[td.get_text(' ',strip=True) for td in tr.find_all(['td','th'])]
        if not cells: continue
        if not years: years=[v for v in cells if re.fullmatch(r'(?:19|20)\d{2}',v)]
        if cells[0] in LABELS: rows.append(' | '.join(cells))
    title=soup.find('h1')
    rendered=(title.get_text(' ',strip=True) if title else '')+'\n'+fiscal[0]+' '+units[0]+' | '+' | '.join(years)+'\n'+'\n'.join(rows)
    return parse_text(rendered,ticker,route,'direct_http')


def fetch_page(ticker,route):
    url=page_url(ticker,route)
    try:
        with urlopen(Request(url,headers={'User-Agent':'screenerX/0.3 financial-research','Accept':'text/html'}),timeout=20) as response:
            raw=response.read(10*1024*1024+1)
            if len(raw)>10*1024*1024: raise InputError('WSJ page exceeds size limit')
    except HTTPError as exc:
        raise InputError(f'WSJ HTTP {exc.code}; provide accessible saved WSJ pages via --wsj-pages; no Yahoo financial fallback') from exc
    except (URLError,TimeoutError) as exc:
        raise InputError(f'WSJ connection failed: {exc}') from exc
    return parse_html(raw.decode('utf-8'),ticker,route)


def validate_page(page,ticker,route):
    if page.get('format')!='wsj-table-excerpt-v1' or page.get('ticker')!=ticker or page.get('statement')!=route:
        raise InputError('WSJ statement identity/format mismatch')
    if page.get('url')!=page_url(ticker,route): raise InputError('WSJ source URL mismatch')
    if not re.search(r'\b'+re.escape(ticker)+r'\b',page.get('title','')):
        raise InputError('WSJ page title must identify the requested ticker')
    multiplier={'Thousands':1e3,'Millions':1e6,'Billions':1e9}.get(page.get('scale'))
    if multiplier is None or page.get('financial_currency') not in ('IDR','USD'):
        raise InputError('Unsupported WSJ financial units/currency')
    years=page.get('years',[])
    if not years or len(years)!=len(set(years)) or any(not re.fullmatch(r'(?:19|20)\d{2}',str(y)) for y in years):
        raise InputError('Invalid WSJ annual year columns')
    end_month=page.get('fiscal_year','').split('-')[-1].strip()
    month_names={name:i for i,name in enumerate(calendar.month_name) if name}
    if end_month not in month_names: raise InputError('WSJ fiscal-year end month missing/unsupported')
    month=month_names[end_month]
    periods={f'{year}-{month:02d}-{calendar.monthrange(int(year),month)[1]:02d}':{} for year in years}
    for row in page.get('rows',[]):
        label=row.get('label')
        if label not in LABELS: raise InputError('Unexpected WSJ row in normalized excerpt')
        if len(row.get('values',[]))!=len(years): raise InputError('WSJ row/year column mismatch')
        for period,value in zip(periods,row['values']):
            parsed=cell(value)
            if parsed is None: continue
            parsed*=multiplier
            if label in periods[period] and periods[period][label]!=parsed:
                raise InputError('Conflicting duplicate WSJ rows')
            periods[period][label]=parsed
    return periods


def fetch_snapshot(ticker,pages_dir=None,evidence_dir=None):
    ticker,symbol=symbol_for(ticker); pages={}; sources=[]; errors={}; tables={}
    for kind,route in ROUTES.items():
        try:
            if pages_dir:
                base=Path(pages_dir)/f'{ticker}-{route}'
                if base.with_suffix('.json').exists(): page=json.loads(base.with_suffix('.json').read_text(encoding='utf-8'))
                elif base.with_suffix('.txt').exists(): page=parse_text(base.with_suffix('.txt').read_text(encoding='utf-8'),ticker,route)
                elif base.with_suffix('.html').exists(): page=parse_html(base.with_suffix('.html').read_text(encoding='utf-8'),ticker,route)
                else: raise InputError(f'Missing saved WSJ {route} page for {ticker}')
            else: page=fetch_page(ticker,route)
            periods=validate_page(page,ticker,route); pages[kind]=page; tables[kind]=periods
            encoded=(json.dumps(page,indent=2,allow_nan=False)+'\n').encode('utf-8')
            source={'url':page['url'],'statement':route,'sha256':hashlib.sha256(encoded).hexdigest(),
                    'retrieval_url':page.get('retrieval_url',page['url']),
                    'retrieval_method':page.get('retrieval_method','saved_page'),
                    'retrieved_at':page.get('retrieved_at'),'freshness_note':page.get('freshness_note','not established')}
            if evidence_dir:
                folder=Path(evidence_dir); folder.mkdir(parents=True,exist_ok=True)
                path=folder/f'{ticker}-{route}.json'; path.write_bytes(encoded); source['path']=str(path.resolve())
            sources.append(source)
        except (InputError,OSError,ValueError) as exc:
            errors[kind]=str(exc); tables[kind]={}
    if not tables['income'] or not tables['balance']:
        raise InputError('WSJ income/balance unavailable: '+json.dumps(errors))
    currencies={page['financial_currency'] for page in pages.values()}
    if len(currencies)!=1: raise InputError('WSJ statements have inconsistent currencies')
    statements={'income':{},'balance':{},'cashflow':{}}; mapping={}
    for period,values in tables['income'].items():
        income={}; origins={}
        for key,aliases in {'Net Income Common Stockholders':['Net Income Available to Common'],
                            'Operating Income':['EBIT','Operating Income'],
                            'Pretax Income':['Pretax Income'],'Tax Provision':['Income Tax','Income Taxes']}.items():
            label=next((x for x in aliases if x in values),None)
            if label: income[key]=values[label]; origins[key]=label
        statements['income'][period]=income; mapping[period]={'income':origins}
    for period,values in tables['balance'].items():
        balance={}; origins={}
        for key,label in [('Common Stock Equity','Common Equity (Total)'),('Cash And Cash Equivalents','Cash Only'),
                          ('Minority Interest','Accumulated Minority Interest')]:
            if label in values: balance[key]=values[label]; origins[key]=label
        if all(key in values for key in ('ST Debt & Current Portion LT Debt','Long-Term Debt')):
            balance['Total Debt']=values['ST Debt & Current Portion LT Debt']+values['Long-Term Debt']
            origins['Total Debt']='ST Debt & Current Portion LT Debt + Long-Term Debt'
        if 'Minority Interest' not in balance and all(key in values for key in ('Total Equity',"Total Shareholders' Equity",'Common Equity (Total)')):
            if values["Total Shareholders' Equity"]==values['Common Equity (Total)']:
                difference=values['Total Equity']-values["Total Shareholders' Equity"]
                if difference>=0: balance['Minority Interest']=difference; origins['Minority Interest']='Total Equity - Total Shareholders\' Equity (common equals shareholders equity)'
        share_values=tables['income'].get(period,{})
        share_label=next((x for x in ('Diluted Shares Outstanding','Basic Shares Outstanding') if x in share_values),None)
        if share_label:
            balance['Annual Average Shares']=share_values[share_label]; origins['Annual Average Shares']='income:'+share_label
        statements['balance'][period]=balance; mapping.setdefault(period,{})['balance']=origins
    for period,values in tables['cashflow'].items():
        if 'Common Dividends' in values:
            statements['cashflow'][period]={'Common Stock Dividend Paid':values['Common Dividends']}
            mapping.setdefault(period,{})['cashflow']={'Common Stock Dividend Paid':'Common Dividends'}
    financial=bool(pages['income'].get('bank_statement'))
    source_times=[source['retrieved_at'] for source in sources if isinstance(source.get('retrieved_at'),str)]
    fetched_at=max(source_times) if pages_dir and source_times else None if pages_dir else datetime.now(timezone.utc).isoformat()
    return {'ticker':ticker,'symbol':symbol,'provider':'wsj','fetched_at':fetched_at,
            'metadata':{'symbol':symbol,'sector':'Financial Services' if financial else 'Nonfinancial (WSJ statement classification)',
                        'currency':'IDR','financialCurrency':next(iter(currencies))},
            'statements':statements,'errors':errors,'source_pages':sources,'field_mapping':mapping,
            'share_count_basis':'WSJ annual average diluted/basic shares; period-end share count not supplied',
            'retrieval_mode':'saved_wsj_pages' if pages_dir else 'direct_http'}
