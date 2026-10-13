"""Price-only research shortlist; never substitutes invented broker/valuation data."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median

from .engine import (InputError, day, file_hash, indicators, load_config,
                     load_prices, next_ticks, number, rounded, tick, write_csv)
from .fetch import JAKARTA, main as fetch_main, symbol_for

DEFAULT_TICKERS = ['BBCA','BBRI','BMRI','BBNI','ASII','TLKM','ANTM','INCO',
                   'PTBA','ADRO','ITMG','UNTR','ICBP','INDF','KLBF']
FIELDS = ['rank','ticker','as_of','status','setup','research_score','close',
          'entry_price','tp1_price','tp2_price','stop_loss_price','gross_rr','net_rr',
          'support','resistance','atr','stoch_k','stoch_d','macd','macd_signal',
          'volume_multiple','sma20','sma60','return20','median_turnover_idr',
          'broker_flow_status','fundamental_status','ddm','rim','eva','fair_value',
          'bear_value','bull_value','current_mos','dispersion','fundamental_verdict',
          'statement_date','valuation_source','levels_source','price_source','warnings']


def attach_valuations(rows,path,asof):
    estimates={}
    with Path(path).open(newline='',encoding='utf-8-sig') as stream:
        reader=csv.DictReader(stream)
        required={'ticker','price_date','valuation_price','validated','status','fair_value'}
        if not reader.fieldnames or len(reader.fieldnames)!=len(set(reader.fieldnames)) or not required<=set(reader.fieldnames):
            raise InputError('Invalid valuation estimate CSV headers')
        records=list(reader)
    for estimate in records:
        if None in estimate: raise InputError('Extra valuation CSV columns')
        ticker=estimate['ticker']
        if ticker in estimates: raise InputError('Duplicate valuation estimate ticker')
        if estimate['price_date']!=asof.isoformat(): raise InputError('Valuation estimate price date mismatch')
        if estimate['validated']!='false': raise InputError('Research estimator inputs must remain unreviewed')
        estimates[ticker]=estimate
    for row in rows:
        estimate=estimates.get(row['ticker'])
        row['warnings']=row['warnings'].replace('reviewed valuations ON_HOLD','valuations unreviewed')
        if estimate is None:
            row['fundamental_status']='UNAVAILABLE'
            row['warnings']+='; No usable valuation estimate for this ticker; see valuation errors'
            continue
        if number(estimate['valuation_price'],'valuation price')!=row['close']:
            raise InputError('Valuation estimate price mismatch')
        row['fundamental_status']=estimate['status']
        for key in ('ddm','rim','eva','fair_value','bear_value','bull_value','current_mos','dispersion'):
            row[key]=number(estimate.get(key),key,True)
        for key in ('fundamental_verdict','statement_date','valuation_source'):
            row[key]=estimate.get(key,'')
        row['warnings']+='; '+estimate.get('warnings','')
    return estimates


def research_screen(prices, config, asof):
    """Rank observable trend/momentum. Do not reuse the full composite score."""
    candidates=[]; issues=[]
    for ticker, history in sorted(prices.items()):
        try:
            rows=[r for r in history if r['date']<=asof]
            if len(rows)<config['technical']['minimum_history']:
                raise InputError('Insufficient price history')
            latest=rows[-1]
            if latest['date']!=asof:
                raise InputError('No candle for requested decision session')
            if not latest['tradable'] or latest['volume']<=0:
                raise InputError('Not tradable or no volume on decision session')
            i=indicators(rows,config)
            if i['atr']<=0:
                raise InputError('ATR must be positive')
            e=config['execution']; t=config['technical']
            turnover=median(r['traded_value_idr'] for r in rows[-e['turnover_sessions']:])
            if turnover<e['minimum_turnover_idr']:
                raise InputError('Below configured liquidity threshold (turnover may be estimated)')
            sma20=sum(r['close'] for r in rows[-20:])/20
            sma60=sum(r['close'] for r in rows[-60:])/60
            ret=latest['close']/rows[-21]['close']-1
            # Freeze rolling levels before the signal candle; no future inputs.
            window=rows[-t['support_lookback']-1:-1]
            support=min(r['low'] for r in window)
            resistance=max(r['high'] for r in window)
            breakout=latest['close']>resistance
            setup='rolling_breakout' if breakout else 'trend_watch' if latest['close']>sma20>sma60 else 'momentum_watch'
            score=(25*(latest['close']>sma20)+25*(sma20>sma60)
                   +20*(i['macd']>i['macd_signal'])
                   +15*(i['stoch_k']>i['stoch_d'])
                   +15*(i['volume_multiple']>=t['volume_multiple']))
            if score<50:
                raise InputError('Research momentum score below 50/100')
            entry=next_ticks(latest['high'],e['entry_buffer_ticks'])
            anchor=min(r['low'] for r in rows[-11:-1])
            stop=rounded(anchor-max(e['stop_buffer_atr']*i['atr'],e['stop_buffer_ticks']*tick(anchor)))
            # Targets are observed overhead highs only; breakouts have no invented targets.
            overhead=sorted({rounded(r['high']) for r in window if rounded(r['high'])>entry})
            tp1=overhead[0] if overhead else None
            tp2=next((p for p in overhead if tp1 is not None and p>=tp1+i['atr']),None)
            gross=net=None
            if not 0<stop<entry:
                raise InputError('Invalid derived stop/entry interval')
            if tp1 is not None:
                gross=(tp1-entry)/(entry-stop)
                if all(e[k] is not None for k in ('buy_fee','sell_fee','entry_slippage','target_slippage','stop_slippage')):
                    paid=entry*(1+e['entry_slippage'])*(1+e['buy_fee'])
                    received=tp1*(1-e['target_slippage'])*(1-e['sell_fee'])
                    stopped=stop*(1-e['stop_slippage'])*(1-e['sell_fee'])
                    net=(received-paid)/(paid-stopped)
            warnings=['Research only; levels derived from rolling OHLC, pending analyst review',
                      'Broker flow ON_HOLD; reviewed valuations ON_HOLD; no composite score',
                      'Bid/ask and executable spread not verified; fees/slippage are configured assumptions']
            if not latest['actions_checked']:
                warnings.append('Corporate actions not reviewed')
            if any(r['turnover_basis']!='actual_regular' for r in rows[-e['turnover_sessions']:]):
                warnings.append('Turnover estimated as close times volume')
            if tp1 is None:
                warnings.append('No observed overhead resistance; targets and reward/risk unavailable')
            elif net is None or net<e['minimum_net_rr']:
                warnings.append('Reward/risk unverified or below full-screen threshold; watch only')
            candidates.append({'ticker':ticker,'as_of':asof.isoformat(),'status':'RESEARCH_ONLY',
                'setup':setup,'research_score':score,'close':latest['close'],**i,
                'entry_price':entry,'stop_loss_price':stop,'tp1_price':tp1,'tp2_price':tp2,
                'gross_rr':gross,'net_rr':net,'support':support,'resistance':resistance,
                'sma20':sma20,'sma60':sma60,'return20':ret,'median_turnover_idr':turnover,
                'broker_flow_status':'ON_HOLD','fundamental_status':'ON_HOLD',
                'levels_source':'prior-session rolling OHLC; unreviewed',
                'price_source':latest['source'],'warnings':'; '.join(warnings)})
        except InputError as exc:
            issues.append({'ticker':ticker,'state':'EXCLUDED','reason':str(exc)})
    candidates.sort(key=lambda r:(-r['research_score'],-r['median_turnover_idr'],r['ticker']))
    selected=candidates[:config['ranking']['max_results']]
    for rank,row in enumerate(selected,1): row['rank']=rank
    issues.extend({'ticker':r['ticker'],'state':'QUALIFIED_NOT_SELECTED','reason':'Below result limit'}
                  for r in candidates[len(selected):])
    return selected,issues


def main(argv=None):
    parser=argparse.ArgumentParser(description='Generate a price-only IDX research shortlist with broker flow on hold.')
    parser.add_argument('--prices',help='Existing screenerX price CSV; skip network when supplied')
    parser.add_argument('--tickers',nargs='+',help='Download universe; default is a disclosed 15-stock watchlist')
    parser.add_argument('--as-of',help='Completed decision date; saved CSV defaults to latest date')
    parser.add_argument('--config',default=str(Path(__file__).parent.parent/'config.json'))
    parser.add_argument('--output',required=True,help='New output directory')
    parser.add_argument('--lookback-days',type=int,default=400)
    valuations=parser.add_mutually_exclusive_group()
    valuations.add_argument('--estimate-valuations',action='store_true',help='Calculate unreviewed valuations from yfinance statements')
    valuations.add_argument('--valuation-estimates',help='Existing estimates.csv to join without fetching financials')
    parser.add_argument('--valuation-assumptions',default=str(Path(__file__).parent.parent/'valuation-config.json'))
    parser.add_argument('--valuation-snapshots',help='Saved financial snapshots for --estimate-valuations; skips financial network calls')
    parser.add_argument('--valuation-fx-snapshot',help='Saved USDIDR JSON for offline financial recalculation')
    parser.add_argument('--use-reported-tax',action='store_true',help='Use aligned reported effective tax where usable')
    parser.add_argument('--financial-provider',choices=['wsj','yfinance'],default='wsj')
    parser.add_argument('--wsj-pages',help='Saved WSJ financial statement pages for --estimate-valuations')
    args=parser.parse_args(argv)
    if args.valuation_snapshots and not args.estimate_valuations:
        parser.error('--valuation-snapshots requires --estimate-valuations')
    if args.valuation_fx_snapshot and not args.estimate_valuations:
        parser.error('--valuation-fx-snapshot requires --estimate-valuations')
    if args.wsj_pages and not args.estimate_valuations:
        parser.error('--wsj-pages requires --estimate-valuations')
    try:
        output=Path(args.output)
        if output.exists(): raise InputError('Output directory already exists; choose a new directory')
        config=load_config(args.config)
        now=datetime.now(JAKARTA)
        cutoff=now.date() if now.hour>=18 else now.date()-timedelta(days=1)
        if args.prices:
            prices_path=Path(args.prices); prices=load_prices(prices_path)
            asof=day(args.as_of,'as-of') if args.as_of else max(r['date'] for rows in prices.values() for r in rows if r['date']<=cutoff)
            if args.tickers:
                wanted={symbol_for(t)[0] for t in args.tickers}
                prices={t:rows for t,rows in prices.items() if t in wanted}
                if not prices: raise InputError('Requested tickers absent from existing prices')
        else:
            asof=day(args.as_of,'as-of') if args.as_of else cutoff
            if not args.as_of:
                while asof.weekday()>=5: asof-=timedelta(days=1)
            if asof>cutoff: raise InputError('Choose an already completed session')
            tickers=args.tickers or DEFAULT_TICKERS
            output.mkdir(parents=True)
            rc=fetch_main(['--tickers',*tickers,'--as-of',asof.isoformat(),
                           '--lookback-days',str(args.lookback_days),'--config',args.config,
                           '--output',str(output/'market-data')])
            prices_path=output/'market-data'/'prices.csv'
            if not prices_path.exists(): raise InputError('Download did not produce prices')
            prices=load_prices(prices_path)
        if asof>cutoff: raise InputError('Choose an already completed session')
        rows,issues=research_screen(prices,config,asof)
        output.mkdir(parents=True,exist_ok=True)
        valuation_path=args.valuation_estimates
        valuation_report=None
        estimated_count=0
        if args.estimate_valuations:
            from .valuation import generate
            _,valuation_report=generate(prices_path,asof,output/'valuations',args.valuation_assumptions,
                                        args.valuation_snapshots,sorted(prices),args.valuation_fx_snapshot,args.use_reported_tax,
                                        args.financial_provider,args.wsj_pages)
            valuation_path=output/'valuations'/'estimates.csv'
        if valuation_path:
            estimates=attach_valuations(rows,valuation_path,asof)
            estimated_count=sum(number(r.get('fair_value'),'fair value',True) is not None for r in estimates.values())
        write_csv(output/'top10.csv',rows,FIELDS)
        write_csv(output/'inspection.csv',issues,['ticker','state','reason'])
        resolved=json.dumps(config,indent=2,sort_keys=True)
        (output/'config.resolved.json').write_text(resolved+'\n',encoding='utf-8')
        report={'mode':'price_only_research','created_at':datetime.now(timezone.utc).isoformat(),
                'as_of':asof.isoformat(),'broker_flow_status':'ON_HOLD','fundamental_status':'ON_HOLD',
                'universe':sorted(prices),'universe_count':len(prices),'selected_count':len(rows),
                'config_sha256':hashlib.sha256(resolved.encode()).hexdigest(),
                'prices':{'path':str(prices_path.resolve()),'sha256':file_hash(prices_path)},
                'ranking':'25 close>SMA20 + 25 SMA20>SMA60 + 20 MACD>signal + 15 StochK>D + 15 volume confirmation; minimum 50',
                'limitations':'Price-only research; no reviewed fair values, broker flow, execution verification or full composite score.'}
        if valuation_path:
            report.update(mode='technical_and_estimated_valuation_research',
                          fundamental_status='UNREVIEWED_ESTIMATES' if estimated_count else 'UNAVAILABLE',
                          valuation_estimated_count=estimated_count,
                          valuations={'path':str(Path(valuation_path).resolve()),'sha256':file_hash(valuation_path)},
                          limitations='Research with unreviewed valuation estimates; broker flow, execution and historical point-in-time financials are not verified. Ranking remains technical; no full composite score.')
            if valuation_report is not None:
                report['valuation_errors']=valuation_report['errors']
                report['valuation_estimated_count']=valuation_report['estimated_count']
        api_report=output/'market-data'/'api-run.json'
        if api_report.exists():
            report['download_errors']=json.loads(api_report.read_text())['errors']
        (output/'run.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
        lines=[f'# IDX research shortlist — {asof}', '',report['limitations'],
               '', f"Broker flow: **ON_HOLD**. Valuations: **{report['fundamental_status']}**." if valuation_path else
               'Broker flow: **ON_HOLD**. Reviewed valuations: **ON_HOLD**.',
               '',f'Universe: {", ".join(sorted(prices))}. Selected: {len(rows)}.',
               '', '| Rank | Ticker | Score | Close | Conditional entry | TP1 | Stop | Estimated net R/R |',
               '|---|---|---|---|---|---|---|---|']
        for r in rows:
            rr=f"{r['net_rr']:.2f}" if r['net_rr'] is not None else 'pending'
            lines.append(f"| {r['rank']} | {r['ticker']} | {r['research_score']} | {r['close']:g} | {r['entry_price']} | {r['tp1_price'] or 'pending'} | {r['stop_loss_price']} | {rr} |")
        lines+=['','Targets use observed prior-session highs; missing targets stay blank. All levels require review.',
                f"These are watchlist candidates. Full-screen estimated net reward/risk must be at least {config['execution']['minimum_net_rr']:g}; rows below this threshold are not trade-qualified.",
                'See top10.csv for warnings, indicator evidence and estimated reward/risk; inspection.csv explains exclusions.']
        if valuation_path:
            lines+=['','Valuation estimates (IDR/share):',
                    '', '| Ticker | DDM | RIM | EVA | Base mean | Bear | Bull | Verdict |',
                    '|---|---|---|---|---|---|---|---|']
            for row in rows:
                cells=[row['ticker']]+[f"{row[k]:,.0f}" if row.get(k) is not None else 'unavailable'
                                     for k in ('ddm','rim','eva','fair_value','bear_value','bull_value')]
                cells.append(row.get('fundamental_verdict','UNAVAILABLE'))
                lines.append('| '+' | '.join(cells)+' |')
            lines+=['','Estimates are unreviewed. High model dispersion makes the mean unreliable. Missing models stay blank.',
                    'Valuation assumptions, annual reporting lag, share counts and accounting inputs require review; no historical publication-date verification.']
        (output/'report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
        print(f'Generated {len(rows)} research candidates from {len(prices)} tickers: {output / "report.md"}')
        print(f"Broker flow ON_HOLD; valuations {report['fundamental_status']}; all results RESEARCH_ONLY.")
        return 2 if report.get('download_errors') or report.get('valuation_errors') or (valuation_path and not estimated_count) else 0
    except (InputError,OSError,ValueError) as exc:
        print(f'Error: {exc}',file=sys.stderr); return 2


if __name__=='__main__': sys.exit(main())
