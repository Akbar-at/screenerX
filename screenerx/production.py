"""Live market-data pipeline. No demo generators or fixture/snapshot inputs."""
from __future__ import annotations

import argparse
import csv
import json
import platform
import shutil
import sys
from datetime import datetime, timedelta, timezone
from importlib.metadata import version
from pathlib import Path

from .engine import InputError, day, file_hash, load_config, load_prices, number, write_csv
from .fetch import JAKARTA, fetch_yfinance, main as fetch_main, parse_chart, symbol_for
from .research import DEFAULT_TICKERS, main as research_main
from .valuation import DEFAULT_CONFIG, generate, load_assumptions


def latest_session(now=None):
    """Discover observed completed IDX session; avoid weekday/holiday guesses."""
    now=now or datetime.now(JAKARTA)
    cutoff=now.date() if now.hour>=18 else now.date()-timedelta(days=1)
    errors=[]
    for ticker in ('BBCA','BMRI'):
        try:
            payload,_=fetch_yfinance(ticker,cutoff,20)
            result=payload['chart']['result'][0]
            dates=sorted({datetime.fromtimestamp(number(stamp,'session timestamp'),JAKARTA).date()
                          for stamp in result.get('timestamp',[])})
            eligible=[d for d in dates if d<=cutoff]
            if not eligible: raise InputError('No observed completed reference session')
            asof=eligible[-1]
            if (cutoff-asof).days>10: raise InputError('Reference session more than 10 calendar days old')
            rows,quality=parse_chart(payload,ticker,asof)
            if rows[-1]['volume']<=0: raise InputError('Reference session has no traded volume')
            return asof,{'reference_ticker':ticker,'cutoff_date':cutoff.isoformat(),
                         'discovered_date':asof.isoformat(),'reference_payload':payload,
                         'prior_reference_errors':errors}
        except (InputError,KeyError,TypeError,ValueError) as exc:
            errors.append({'ticker':ticker,'reason':str(exc)})
    raise InputError('Completed session discovery failed: '+json.dumps(errors))


def read_universe(path):
    with Path(path).open(newline='',encoding='utf-8-sig') as stream:
        reader=csv.DictReader(stream)
        if not reader.fieldnames or 'ticker' not in reader.fieldnames:
            raise InputError('Universe CSV needs a ticker header')
        return [symbol_for(row['ticker'])[0] for row in reader]


def run(output,tickers,config_path,assumptions_path,asof=None,financial_provider='wsj',wsj_pages=None,core_profile=None):
    output=Path(output)
    if output.exists(): raise InputError('Production output already exists; choose a new run directory')
    tickers=[symbol_for(t)[0] for t in tickers]
    if not tickers or len(tickers)!=len(set(tickers)):
        raise InputError('Production universe must contain unique nonempty tickers')
    load_config(config_path); load_assumptions(assumptions_path)
    if financial_provider not in ('wsj','yfinance'): raise InputError('Unknown financial provider')
    if wsj_pages and financial_provider!='wsj': raise InputError('--wsj-pages requires WSJ financial provider')
    now=datetime.now(JAKARTA); cutoff=now.date() if now.hour>=18 else now.date()-timedelta(days=1)
    if asof is not None and asof>cutoff: raise InputError('Price session is still in progress or in the future')
    output.mkdir(parents=True)
    manifest={'data_mode':'REAL_MARKET_DATA','price_provider':'yfinance','financial_provider':financial_provider,
              'financial_retrieval':'saved_wsj_pages' if wsj_pages else 'direct_request',
              'company_data_fallback':False,'status':'RUNNING','started_at':datetime.now(timezone.utc).isoformat(),
              'requested_universe':tickers,'requested_count':len(tickers),'broker_flow_status':'ON_HOLD',
              'review_status':'UNREVIEWED_ESTIMATES','execution_status':'UNVERIFIED',
              'versions':{'python':platform.python_version(),'yfinance':version('yfinance')},
              'stages':{},'errors':[]}
    def save():
        (output/'run.json').write_text(json.dumps(manifest,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    save()
    try:
        if asof is None:
            asof,discovery=latest_session(now)
            path=output/'session-discovery.json'
            path.write_text(json.dumps(discovery,indent=2,allow_nan=False)+'\n',encoding='utf-8')
            manifest['session_discovery']={'path':str(path.resolve()),'sha256':file_hash(path)}
        manifest['as_of']=asof.isoformat()
        manifest['stages']['session']='COMPLETE'; save()
        print(f'Production live-data run: {asof}; {len(tickers)} requested tickers',flush=True)
        price_output=output/'market-data'
        price_rc=fetch_main(['--provider','yfinance','--tickers',*tickers,'--as-of',asof.isoformat(),
                             '--config',str(config_path),'--output',str(price_output)])
        audit_path=price_output/'api-run.json'
        if not audit_path.exists(): raise InputError('Price stage failed before an audit was produced')
        price_audit=json.loads(audit_path.read_text(encoding='utf-8'))
        manifest['errors'].extend({'stage':'prices',**e} for e in price_audit['errors'])
        prices_path=price_output/'prices.csv'; prices=load_prices(prices_path)
        if any(r['source']!='Yahoo Finance' for rows in prices.values() for r in rows):
            raise InputError('Production prices must come from the live Yahoo adapter')
        manifest['price_count']=len(prices)
        manifest['stages']['prices']='COMPLETE' if not price_rc else 'PARTIAL'; save()
        valuation_rows,valuation_audit=generate(prices_path,asof,output/'valuations',assumptions_path,
                                                tickers=sorted(prices),use_reported_tax=True,
                                                provider=financial_provider,wsj_pages=wsj_pages)
        manifest['errors'].extend({'stage':'valuations',**e} for e in valuation_audit['errors'])
        for row in valuation_rows:
            if row['fair_value'] is None:
                manifest['errors'].append({'stage':'valuations','ticker':row['ticker'],
                                           'reason':'No usable positive valuation model'})
        manifest['valuation_count']=valuation_audit['estimated_count']
        manifest['fx_sources']=valuation_audit['fx_sources']
        manifest['stages']['valuations']='COMPLETE' if valuation_audit['estimated_count']==len(prices) and not valuation_audit['errors'] else 'PARTIAL'
        save()
        core_reports={}
        if financial_provider=='wsj':
            from .core_service import build_service
            from .core_cli import export_report
            fx_path=next((s['path'] for s in valuation_audit['fx_sources'] if s['symbol']=='USDIDR=X'),None)
            service=build_service(prices_path,asof,snapshot_dir=output/'valuations'/'raw',fx_path=fx_path,
                                  config_path=config_path,valuation_path=assumptions_path,profile_path=core_profile)
            research_report=service.screen(tickers)
            export_report(research_report,output/'core')
            research_rc=0
            top_path=output/'core'/'top10.csv'; inspection_path=output/'core'/'coverage.csv'
            report_path=output/'core'/'report.md'
            core_reports={r['ticker']:r for r in research_report['companies']}
            manifest.update(top10_mode='CORE_COVERAGE_QUALIFIED_RESEARCH',
                            coverage_complete_count=research_report['coverage_complete_count'],
                            qualifying_count=research_report['qualifying_count'],
                            unfilled_slots=research_report['unfilled_slots'],
                            all_selected_have_full_coverage=research_report['all_selected_have_full_coverage'])
        else:
            research_rc=research_main(['--prices',str(prices_path),'--as-of',asof.isoformat(),
                                       '--config',str(config_path),'--valuation-estimates',str(output/'valuations'/'estimates.csv'),
                                       '--output',str(output/'research')])
            research_report=json.loads((output/'research'/'run.json').read_text(encoding='utf-8'))
            top_path=output/'research'/'top10.csv'; inspection_path=output/'research'/'inspection.csv'
            report_path=output/'research'/'report.md'
            manifest['top10_mode']='LEGACY_RESEARCH_EXPLICIT_ALTERNATE_PROVIDER'
        manifest['selected_count']=research_report['selected_count']
        manifest['stages']['research']='COMPLETE' if research_rc==0 else 'PARTIAL'
        for source,name in [(top_path,'top10.csv'),
                            (inspection_path,'inspection.csv'),
                            (output/'valuations'/'estimates.csv','valuations.csv')]:
            shutil.copyfile(source,output/name)
        checks=[]
        for ticker in tickers:
            valuation=next((r for r in valuation_rows if r['ticker']==ticker),None)
            history=prices.get(ticker,[])
            checks.append({'ticker':ticker,'price_status':'AVAILABLE' if history else 'UNAVAILABLE',
                           'price_date':history[-1]['date'].isoformat() if history else '',
                           'daily_candles':len(history),
                           'valuation_status':valuation['status'] if valuation else 'UNAVAILABLE',
                           'method_count':valuation['method_count'] if valuation else 0,
                           'statement_date':valuation['statement_date'] if valuation else '',
                           'statement_age_days':(asof-day(valuation['statement_date'],'statement date')).days if valuation else '',
                           'financial_currency':valuation['financial_currency'] if valuation else '',
                           'financial_provider':valuation['financial_provider'] if valuation else financial_provider,
                           'share_count_basis':valuation['share_count_basis'] if valuation else '',
                           'fx_rate':valuation['fx_rate'] if valuation else '',
                           'fx_date':valuation['fx_date'] if valuation else '',
                           'tax_rate_source':valuation['tax_rate_source'] if valuation else '',
                           'verdict':valuation['fundamental_verdict'] if valuation else '',
                           'research_coverage_complete':core_reports.get(ticker,{}).get('coverage_complete'),
                           'research_ranking_status':core_reports.get(ticker,{}).get('ranking_status'),
                           'broker_flow_status':'ON_HOLD','execution_status':'UNVERIFIED'})
        write_csv(output/'data-quality.csv',checks,list(checks[0]))
        manifest['status']='COMPLETE' if not manifest['errors'] and not research_rc else 'PARTIAL'
        manifest['completed_at']=datetime.now(timezone.utc).isoformat()
        manifest['artifacts']={name:{'path':str((output/name).resolve()),'sha256':file_hash(output/name)}
                               for name in ('top10.csv','inspection.csv','valuations.csv','data-quality.csv')}
        # Bind all retained source/config/model files into one reproducibility manifest.
        manifest['evidence']={str(path.relative_to(output)).replace('\\','/') : file_hash(path)
                              for path in sorted(output.rglob('*')) if path.is_file() and path!=output/'run.json'}
        manifest['caveats']=['COMPLETE describes data-pipeline coverage, not analyst review or investment eligibility.',
                             'Discount rates/growth remain explicit forward assumptions, not observed financial facts.',
                             'Provider statements may be restated; historical publication timing not verified.',
                             'Turnover estimated; quotes/execution and corporate actions not independently verified.',
                             'Scope is the requested watchlist, not the entire IDX exchange.']
        save()
        research_text=report_path.read_text(encoding='utf-8')
        if financial_provider=='wsj': research_text=research_text.replace('(tickers/','(core/tickers/')
        valuation_text=(output/'valuations'/'report.md').read_text(encoding='utf-8')
        lines=['# Production run using real market data','',
               f"Completed price session: **{asof}**. Pipeline status: **{manifest['status']}**.",
               f"Fresh Yahoo/yfinance prices: **{len(prices)}/{len(tickers)}**. {financial_provider.upper()} valuation estimates: **{manifest['valuation_count']}/{len(tickers)}**.",
               '', 'Broker flow: **ON_HOLD**. Valuation models: **UNREVIEWED_ESTIMATES**.',
               f"Company financials: **{financial_provider.upper()}**, retrieved using **{manifest['financial_retrieval']}**. Price history and FX: Yahoo/yfinance. No company-data fallback.",
               'Forward growth, cost of capital and fallback model parameters remain explicit assumptions.',
               '', 'See [data quality](data-quality.csv), [all valuations](valuations.csv), [shortlist](top10.csv) and [source manifest](run.json).',
               '', research_text, '', valuation_text]
        (output/'report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
        manifest['artifacts']['report.md']={'path':str((output/'report.md').resolve()),'sha256':file_hash(output/'report.md')}
        save()
        print(f"Production {manifest['status']}: {output/'report.md'}",flush=True)
        return manifest
    except Exception as exc:
        manifest['status']='FAILED'; manifest['finished_at']=datetime.now(timezone.utc).isoformat()
        manifest['errors'].append({'stage':'pipeline','reason':str(exc)}); save()
        raise


def main(argv=None):
    parser=argparse.ArgumentParser(description='Refresh real IDX prices, financial statements and FX, then generate auditable research.')
    universe=parser.add_mutually_exclusive_group()
    universe.add_argument('--tickers',nargs='+')
    universe.add_argument('--universe',help='CSV with ticker column; default is the disclosed 15-stock watchlist')
    parser.add_argument('--as-of',help='Optional completed price session; defaults to observed latest session')
    parser.add_argument('--output',help='New run directory; default output/production/<Jakarta timestamp>')
    parser.add_argument('--config',default=str(Path(__file__).parent.parent/'config.json'))
    parser.add_argument('--assumptions',default=str(DEFAULT_CONFIG))
    parser.add_argument('--financial-provider',choices=['wsj','yfinance'],default='wsj')
    parser.add_argument('--wsj-pages',help='Accessible saved WSJ financial pages/excerpts; no Yahoo company-data fallback')
    parser.add_argument('--core-profile',help='Coverage-qualified research scoring profile; default core-config profile')
    args=parser.parse_args(argv)
    try:
        tickers=read_universe(args.universe) if args.universe else args.tickers or DEFAULT_TICKERS
        output=args.output or str(Path('output')/'production'/datetime.now(JAKARTA).strftime('%Y%m%d-%H%M%S-%f'))
        manifest=run(output,tickers,args.config,args.assumptions,day(args.as_of,'as-of') if args.as_of else None,
                     args.financial_provider,args.wsj_pages,args.core_profile)
        return 0 if manifest['status']=='COMPLETE' else 2
    except (InputError,OSError,ValueError,ImportError) as exc:
        print(f'Error: {exc}',file=sys.stderr); return 2


if __name__=='__main__': sys.exit(main())
