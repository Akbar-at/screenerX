"""CLI/API adapters for covered screening and any IDX ticker inspection."""
import argparse
import csv
import json
import sys
from pathlib import Path

from .core import VERSION, digest
from .core_service import build_service, completed_cutoff
from .engine import InputError, day, write_csv
from .fetch import symbol_for

TOP_FIELDS=['rank','ticker','as_of','coverage_complete','score','fundamental_contribution','technical_contribution',
            'liquidity_contribution','close','ddm','rim','eva','fair_value','current_mos','dispersion',
            'entry_price','tp1_price','stop_loss_price','net_rr','trade_qualified','broker_flow_status',
            'idx_foreign_activity','idx_net_foreign_volume','idx_net_share_of_volume','explanation','warnings']


def factor_sentence(factor):
    name=factor['name']; e=factor['evidence']; points=factor.get('points')
    credit=f" -> {points:g} points" if points is not None else ''
    if name=='Margin of safety':
        return f"Margin of safety {e['mos']:.1%}; full-credit threshold {e['full_credit_threshold']:.0%}"+credit
    if name=='Model agreement': return f"Model dispersion {e['dispersion']:.1%}; lower disagreement earns more credit"+credit
    if name=='Bear-case MOS':
        value=f"{e['bear_mos']:.1%}" if e['bear_mos'] is not None else 'unavailable'
        return f"Bear-case margin of safety {value}; threshold {e['threshold']:.0%}"+credit
    if name=='Close above SMA20':
        return f"Close Rp{e['close']:,.0f} is {'above' if factor['passed'] else 'at/below'} the 20-session average Rp{e['sma20']:,.0f}"+credit
    if name=='SMA20 above SMA60':
        return f"20-session average Rp{e['sma20']:,.0f} is {'above' if factor['passed'] else 'at/below'} the 60-session average Rp{e['sma60']:,.0f}"+credit
    if name=='MACD above signal':
        return f"MACD {e['macd']:.2f} is {'above' if factor['passed'] else 'at/below'} its signal {e['signal']:.2f}"+credit
    if name=='Stochastic K above D':
        return f"Stochastic K {e['k']:.1f} is {'above' if factor['passed'] else 'at/below'} D {e['d']:.1f}"+credit
    if name=='Volume confirmation':
        return f"Volume is {e['multiple']:.2f}x the prior median; confirmation threshold {e['threshold']:.2f}x"+credit
    if name=='Median turnover':
        return f"Median daily turnover Rp{e['median']:,.0f}; full-credit level Rp{e['full_credit_turnover']:,.0f} (estimated turnover stays labeled)"
    return name+': '+json.dumps(e,sort_keys=True)+credit


def flat(row):
    score=row.get('score'); v=row.get('valuation') or {}; plan=row.get('plan') or {}
    return {'rank':row.get('rank'),'ticker':row['ticker'],'as_of':row['as_of'],
            'coverage_complete':row['coverage_complete'],'score':score['total'] if score else None,
            **{key+'_contribution':score['components'][key]['contribution'] if score else None for key in ('fundamental','technical','liquidity')},
            'close':row.get('close'),**{key:v.get(key) for key in ('ddm','rim','eva','fair_value','current_mos','dispersion')},
            **{key:plan.get(key) for key in ('entry_price','tp1_price','stop_loss_price','net_rr')},
            'trade_qualified':row['execution_readiness']['trade_qualified'],'broker_flow_status':row['broker_flow_status'],
            'idx_foreign_activity':row.get('idx_screening',{}).get('foreign_activity'),
            'idx_net_foreign_volume':row.get('idx_screening',{}).get('net_foreign_volume'),
            'idx_net_share_of_volume':row.get('idx_screening',{}).get('net_share_of_volume'),
            'explanation':row['explanation'],'warnings':'; '.join(row['warnings'])}


def export_report(report,output):
    output=Path(output)
    if output.exists(): raise InputError('Core output already exists; preserve existing reports with a new directory')
    output.mkdir(parents=True); (output/'tickers').mkdir()
    (output/'core-run.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    write_csv(output/'top10.csv',[flat(r) for r in report['top10']],TOP_FIELDS)
    write_csv(output/'coverage.csv',[{'ticker':r['ticker'],'ranking_status':r['ranking_status'],
        'coverage_complete':r['coverage_complete'],'quality_passed':r['quality_passed'],
        'missing_inputs':'; '.join(x['check']+': '+x['reason'] for x in r['missing_inputs']),
        'quality_failures':'; '.join(x['check']+': '+x['reason'] for x in r['failed_quality_checks'])}
        for r in report['companies']],['ticker','ranking_status','coverage_complete','quality_passed','missing_inputs','quality_failures'])
    for row in report['companies']:
        (output/'tickers'/f'{row["ticker"]}.json').write_text(json.dumps(row,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    if report.get('idx_screening'):
        write_csv(output/'idx-screening.csv',[{'ticker':r['ticker'],**r['idx_screening']} for r in report['companies']],
                  ['ticker','as_of','foreign_activity','net_foreign_volume','net_share_of_volume','unit','score_contribution','broker_net_status'])
    lines=['# Coverage-qualified, explainable research','',f"Price session: {report['as_of']}. Selected {report['selected_count']}/{report['requested_slots']} slots from {report['universe_count']} explicitly supplied companies.",
           '', 'Required research inputs must be complete before ranking. Broker flow remains ON_HOLD; analyst review, quotes and execution verification are separate. This report is not trade qualification.',
           '',f"Unfilled slots: {report['unfilled_slots']}. Missing-input scores are not renormalized; results are never padded.",
           '', '| Rank | Ticker | Research score | Fundamental | Technical | Liquidity |', '|---|---|---|---|---|---|']
    for row in report['top10']:
        s=row['score']; c=s['components']
        lines.append(f"| {row['rank']} | {row['ticker']} | {s['total']:.2f} | {c['fundamental']['contribution']:.2f} | {c['technical']['contribution']:.2f} | {c['liquidity']['contribution']:.2f} |")
    for row in report['top10']:
        lines+=['',f"## {row['rank']}. {row['ticker']}", '',row['explanation'],
                '', 'Score formula: '+row['score']['formula']+'.']
        for component,part in row['score']['components'].items():
            lines+=['',f"{component.capitalize()}: {part['raw_score']:.2f}/100 × {part['weight_percent']:g}% = {part['contribution']:.2f} points."]
            for factor in part['factors']:
                lines.append('- '+factor_sentence(factor))
        if row.get('rank_comparison'): lines+=['', 'Compared with '+row['rank_comparison']['next_ticker']+': '+row['rank_comparison']['reason']+'.']
        plan=row['plan']
        lines+=['',f"Conditional reference levels: entry Rp{plan['entry_price']:,.0f}, first target Rp{plan['tp1_price']:,.0f}, stop Rp{plan['stop_loss_price']:,.0f}. Estimated net reward/risk {plan['net_rr']:.2f}. Levels require review.",
                '', 'Main cautions:']
        key_warnings=[w for w in row['warnings'] if any(key in w for key in ('reward/risk','Weak trend','Price exceeds','Corporate actions','Turnover estimated','Broker flow'))]
        lines.extend('- '+warning for warning in key_warnings)
        lines+=['- Models and structural levels are unreviewed; this entry is not trade-qualified.',
                '',f"[Full evidence, assumptions and all warnings](tickers/{row['ticker']}.json)"]
        for source in row.get('financial_source_pages',[]):
            lines.append(f"- [WSJ {source['statement']}]({source['url']})")
        if row.get('financial_snapshot_evidence'):
            source=row['financial_snapshot_evidence']
            lines.append(f"- yfinance financial snapshot: `{source['sha256']}`; symbol `{source['symbol']}`.")
    if report.get('idx_screening'):
        lines+=['','## Dated IDX screening evidence','',report['idx_screening']['policy'],
                '', '[All-company foreign activity and coverage](idx-screening.csv). Volumes are shares; daily snapshots are not live quotes.',
                '', '| Ticker | Foreign activity | Net foreign volume (shares) | Net / session volume |', '|---|---|---|---|']
        for row in report['top10']:
            idx=row['idx_screening'];net=idx['net_foreign_volume'];fraction=idx['net_share_of_volume']
            lines.append(f"| {row['ticker']} | {idx['foreign_activity']} | {net if net is not None else 'UNAVAILABLE'} | {format(fraction,'.1%') if fraction is not None else 'UNAVAILABLE'} |")
    lines+=['','## All-company coverage','', '| Ticker | State | Missing inputs / quality reasons |', '|---|---|---|']
    for row in report['companies']:
        reasons='; '.join(x['reason'] for x in row['missing_inputs']+row['failed_quality_checks']) or 'All required research checks passed'
        lines.append(f"| {row['ticker']} | {row['ranking_status']} | {reasons.replace('|','/')} |")
    lines+=['','Coverage is scoped to the supplied universe. This is not proof that every IDX listing was imported.',
            'Conditional levels come from observed rolling OHLC; fees/slippage are explicit assumptions. See core-run.json for source/input hashes and per-model traces.']
    (output/'report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')


def universe_from_csv(path):
    with Path(path).open(newline='',encoding='utf-8-sig') as stream:
        reader=csv.DictReader(stream)
        if not reader.fieldnames or 'ticker' not in reader.fieldnames: raise InputError('Universe CSV requires ticker column')
        return [symbol_for(r['ticker'])[0] for r in reader]


def main(argv=None):
    parser=argparse.ArgumentParser(description='Coverage-qualified WSJ research and explainable lookup of any IDX ticker')
    sub=parser.add_subparsers(dest='command',required=True)
    for command in ('screen','inspect','serve'):
        p=sub.add_parser(command)
        p.add_argument('--prices',help='Saved price CSV; required for screening and saved lookup')
        p.add_argument('--as-of',help='Completed price date; saved data defaults to latest nonfuture date')
        source=p.add_mutually_exclusive_group()
        source.add_argument('--snapshots',help='Normalized WSJ snapshot directory')
        source.add_argument('--wsj-pages',help='Saved WSJ statement page directory')
        p.add_argument('--fx-snapshot'); p.add_argument('--config'); p.add_argument('--valuation-config'); p.add_argument('--profile')
        p.add_argument('--financial-provider',choices=('wsj','yfinance'),default='wsj')
        if command=='screen':
            scope=p.add_mutually_exclusive_group(required=True)
            scope.add_argument('--universe',help='Explicit company universe CSV (ticker column)')
            scope.add_argument('--tickers',nargs='+')
            p.add_argument('--output',required=True)
        elif command=='inspect':
            p.add_argument('--ticker',required=True); p.add_argument('--live',action='store_true')
            p.add_argument('--output',help='Optional new JSON file; otherwise print JSON')
        else:
            p.add_argument('--universe',required=True)
            p.add_argument('--host',default='127.0.0.1'); p.add_argument('--port',type=int,default=8000)
            p.add_argument('--allow-live',action='store_true',help='Enable explicit ?live=true lookups; default API is saved-data only')
    args=parser.parse_args(argv)
    try:
        cutoff=completed_cutoff()
        asof=day(args.as_of,'as-of') if args.as_of else cutoff
        if asof>cutoff: raise InputError('Choose a completed price session')
        service=build_service(args.prices,asof,args.snapshots,args.wsj_pages,args.fx_snapshot,args.config,args.valuation_config,args.profile,args.financial_provider)
        if not args.as_of and service.repository.prices:
            dates=[r['date'] for rows in service.repository.prices.values() for r in rows if r['date']<=cutoff]
            if not dates: raise InputError('No completed nonfuture saved price data')
            service.asof=max(dates)
        elif not args.as_of and (args.command=='inspect' and args.live or args.command=='serve' and args.allow_live):
            from .production import latest_session
            service.asof=latest_session()[0]
        if args.command=='screen':
            if not args.prices: raise InputError('Screening requires saved prices')
            output=Path(args.output)
            if output.exists(): raise InputError('Core output exists; choose a new directory')
            universe=universe_from_csv(args.universe) if args.universe else args.tickers
            report=service.screen(universe); export_report(report,output)
            print(f"Selected {report['selected_count']} fully covered research entries from {report['universe_count']}; {report['unfilled_slots']} slots unfilled. {output/'report.md'}")
            return 0
        if args.command=='inspect':
            if not args.prices and not args.live: raise InputError('Lookup needs --prices or --live')
            result=service.lookup(args.ticker,args.live); text=json.dumps(result,indent=2,allow_nan=False)+'\n'
            if args.output:
                path=Path(args.output); path.parent.mkdir(parents=True,exist_ok=True)
                with path.open('x',encoding='utf-8') as stream: stream.write(text)
                print(f"{result['ticker']}: {result['lookup_status']}; full coverage={result['coverage_complete']}. {path}")
            else: print(text)
            return 0
        from .core_http import serve
        serve(service,universe_from_csv(args.universe),args.host,args.port,args.allow_live)
        return 0
    except (InputError,OSError,ValueError,KeyError) as exc:
        print(f'Error: {exc}',file=sys.stderr); return 2


if __name__=='__main__': sys.exit(main())
