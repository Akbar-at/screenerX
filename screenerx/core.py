"""Deterministic, explainable research with coverage gates and unrestricted IDX lookup.

No network or filesystem work in CoreEngine. Broker flow is explicitly outside
this profile; this does not relax the original full composite-screen contract.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
from collections import Counter
from datetime import date
from statistics import median

from .engine import (InputError, day, indicators, next_ticks, number, rounded,
                     rsi, tick, validate_config)
from .fetch import symbol_for
from .valuation import estimate, validate_assumptions
from .wsj import page_url

VERSION='1.0'
DEFAULT_PROFILE={'profile_name':'wsj_covered_research_v1',
                 'weights':{'fundamental':50,'technical':40,'liquidity':10},
                 'ranking':{'max_results':10,'minimum_score':0},
                 'minimum_methods':2,'liquidity_full_credit_multiple':5}


def primitive(value):
    if isinstance(value,date): return value.isoformat()
    if isinstance(value,dict): return {str(k):primitive(v) for k,v in value.items()}
    if isinstance(value,(list,tuple)): return [primitive(v) for v in value]
    return value


def digest(value):
    # Hash rejected nonfinite source inputs too; admitted model/output data stays strict JSON.
    return hashlib.sha256(json.dumps(primitive(value),sort_keys=True,allow_nan=True,separators=(',',':')).encode()).hexdigest()


def validate_profile(profile):
    if set(profile)!=set(DEFAULT_PROFILE): raise InputError('Core profile keys do not match supported schema')
    if not isinstance(profile['profile_name'],str) or not profile['profile_name'].strip(): raise InputError('Core profile name required')
    weights=profile['weights']
    if set(weights)!=set(DEFAULT_PROFILE['weights']): raise InputError('Core weights must be fundamental/technical/liquidity')
    if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or v<0 for v in weights.values()) or not math.isclose(sum(weights.values()),100):
        raise InputError('Core weights must be finite nonnegative numbers summing to 100')
    ranking=profile['ranking']
    if set(ranking)!={'max_results','minimum_score'}: raise InputError('Invalid core ranking keys')
    if type(ranking['max_results']) is not int or not 1<=ranking['max_results']<=10: raise InputError('Core result limit must be 1..10')
    if isinstance(ranking['minimum_score'],bool) or not 0<=number(ranking['minimum_score'],'core minimum score')<=100: raise InputError('Core score threshold must be 0..100')
    if type(profile['minimum_methods']) is not int or not 2<=profile['minimum_methods']<=3: raise InputError('Core requires at least two models')
    if isinstance(profile['liquidity_full_credit_multiple'],bool) or number(profile['liquidity_full_credit_multiple'],'liquidity multiplier')<1:
        raise InputError('Liquidity full-credit multiple must be >=1')


def conditional_plan(rows,indicator,config):
    latest=rows[-1]; e=config['execution']; window=rows[-config['technical']['support_lookback']-1:-1]
    anchor=min(r['low'] for r in rows[-11:-1])
    entry=next_ticks(latest['high'],e['entry_buffer_ticks'])
    stop=rounded(anchor-max(e['stop_buffer_atr']*indicator['atr'],e['stop_buffer_ticks']*tick(anchor)))
    highs=sorted({rounded(r['high']) for r in window if rounded(r['high'])>entry})
    tp1=highs[0] if highs else None
    tp2=next((p for p in highs if tp1 is not None and p>=tp1+indicator['atr']),None)
    gross=net=None; reasons=[]
    if not 0<stop<entry: reasons.append('Invalid stop/entry interval')
    elif tp1 is None: reasons.append('No observed overhead target; target and reward/risk unavailable')
    else:
        gross=(tp1-entry)/(entry-stop)
        if all(e[k] is not None for k in ('buy_fee','sell_fee','entry_slippage','target_slippage','stop_slippage')):
            paid=entry*(1+e['entry_slippage'])*(1+e['buy_fee'])
            received=tp1*(1-e['target_slippage'])*(1-e['sell_fee'])
            stopped=stop*(1-e['stop_slippage'])*(1-e['sell_fee'])
            net=(received-paid)/(paid-stopped)
        if net is None: reasons.append('Execution cost assumptions incomplete')
        elif net<e['minimum_net_rr']: reasons.append(f"Estimated net reward/risk below {e['minimum_net_rr']:g}")
    return {'entry_price':entry,'stop_loss_price':stop,'tp1_price':tp1,'tp2_price':tp2,
            'gross_rr':gross,'net_rr':net,'stop_basis':e['stop_basis'],
            'support':min(r['low'] for r in window),'resistance':max(r['high'] for r in window),
            'levels_source':'prior-session rolling OHLC; unreviewed','risk_reasons':reasons,
            'cost_assumptions':{k:e[k] for k in ('buy_fee','sell_fee','entry_slippage','target_slippage','stop_slippage')}}


class CoreEngine:
    def __init__(self,screen_config,valuation_config,profile=None,financial_provider='wsj'):
        if financial_provider not in ('wsj','yfinance'): raise InputError('Unsupported core financial provider')
        self.financial_provider=financial_provider
        validate_config(screen_config)
        profile=profile or DEFAULT_PROFILE; validate_profile(profile)
        self.config=copy.deepcopy(screen_config)
        self.valuation_config=validate_assumptions(copy.deepcopy(valuation_config))
        self.profile=copy.deepcopy(profile)
        self.config_hash=digest({'screen':self.config,'valuation':self.valuation_config,'core':self.profile,'financial_provider':financial_provider})

    def inspect_ticker(self,ticker,prices,asof,snapshot=None,fx=None,sessions=None,source_errors=None):
        ticker,_=symbol_for(ticker)
        if not isinstance(asof,date): raise InputError('Core as-of must be a date')
        report={'ticker':ticker,'as_of':asof.isoformat(),'engine_version':VERSION,
                'status':'INSPECTED','ranking_status':'EXCLUDED','research_only':True,
                'coverage_scope':f'prices, technicals, {self.financial_provider} financials, all applicable valuation models, scenarios, liquidity and conditional levels',
                'financial_provider':self.financial_provider,
                'broker_flow_status':'ON_HOLD','review_status':'UNREVIEWED_ESTIMATES',
                'coverage':{},'quality':{},'valuation':None,'technical':None,'plan':None,
                'score':None,'warnings':[],'source_errors':source_errors or [],'config_sha256':self.config_hash}
        coverage=report['coverage']; quality=report['quality']
        original_snapshot=snapshot
        snapshot_error=None
        if snapshot is not None:
            valid=isinstance(snapshot,dict) and isinstance(snapshot.get('metadata'),dict) and isinstance(snapshot.get('statements'),dict)
            try: json.dumps(primitive(snapshot),allow_nan=False)
            except (ValueError,TypeError): valid=False
            if valid:
                valid=all(isinstance(table,dict) and all(isinstance(values,dict) for values in table.values()) for table in snapshot['statements'].values())
                refs=snapshot.get('source_pages',[])
                valid=valid and isinstance(refs,list) and all(isinstance(ref,dict) for ref in refs)
                valid=valid and (snapshot['metadata'].get('sector') is None or isinstance(snapshot['metadata']['sector'],str))
            if not valid: snapshot_error='Malformed financial snapshot structure or nonfinite data'; snapshot=None
        def check(group,key,passed,reason,evidence=None):
            group[key]={'status':'PASS' if passed else 'FAIL','reason':reason,'evidence':evidence}
        rows=[]; malformed=None
        try:
            for raw in prices or []:
                d=raw['date'] if isinstance(raw['date'],date) else day(raw['date'],'price date')
                if d>asof: continue
                row={**raw,'date':d}
                for key in ('open','high','low','close','volume','traded_value_idr'):
                    row[key]=number(row.get(key),key)
                if any(row[k]<=0 for k in ('open','high','low','close')) or row['volume']<0 or row['traded_value_idr']<0 or not row['low']<=min(row['open'],row['close'])<=max(row['open'],row['close'])<=row['high']:
                    raise InputError('Invalid OHLC/volume/turnover')
                if not isinstance(row.get('source'),str) or not row['source'].strip(): raise InputError('Price source missing/invalid')
                rows.append(row)
            rows.sort(key=lambda r:r['date'])
            if len(rows)!=len({r['date'] for r in rows}): raise InputError('Duplicate price dates')
        except (InputError,KeyError,TypeError) as exc: malformed=str(exc); rows=[]
        latest=rows[-1] if rows else None
        history=self.config['technical']['minimum_history']
        current=latest is not None and latest['date']==asof
        enough=len(rows)>=history
        check(coverage,'current_price',current,malformed or ('Decision-session candle available' if current else 'No candle for requested session'),
              {'last_date':latest['date'].isoformat(),'source':latest['source'],'close':latest['close']} if latest else None)
        check(coverage,'price_history',enough,f'{len(rows)} candles; at least {history} required',{'actual':len(rows),'required':history})
        expected=sorted(set(d for d in sessions or [] if d<=asof))
        aligned=not expected or enough and len(expected)>=history and [r['date'] for r in rows[-history:]]==expected[-history:]
        check(coverage,'session_alignment',aligned,'Aligned to supplied/observed session calendar' if expected else 'Calendar not independently supplied; ticker-local continuity only',
              {'calendar_basis':'supplied_or_universe_observed' if expected else 'ticker_local','missing_dates':[d.isoformat() for d in expected[-history:] if d not in {r['date'] for r in rows}]})
        if not expected: report['warnings'].append('No independent market calendar; exchange-wide missing sessions cannot be detected')
        tradable=bool(latest and latest.get('tradable',True) is True and latest['volume']>0)
        check(quality,'tradable',tradable,'Positive decision-session volume and tradable flag' if tradable else 'No tradable positive-volume decision candle')
        evidence_ok=False; identity_ok=False
        if snapshot is not None:
            identity_ok=snapshot.get('ticker')==ticker and snapshot.get('symbol')==ticker+'.JK' and snapshot.get('provider')==self.financial_provider
            refs=snapshot.get('source_pages',[])
            routes={'income-statement','balance-sheet','cash-flow'}
            valid_refs={ref.get('statement') for ref in refs if ref.get('statement') in routes and
                        ref.get('url')==page_url(ticker,ref['statement']) and
                        isinstance(ref.get('sha256'),str) and len(ref['sha256'])==64 and
                        all(c in '0123456789abcdef' for c in ref['sha256'])}
            evidence_ok=routes<=valid_refs
            if self.financial_provider=='yfinance':
                source=snapshot.get('source_evidence',{})
                sha=source.get('sha256','')
                evidence_ok=(isinstance(sha,str) and len(sha)==64 and all(c in '0123456789abcdef' for c in sha)
                             and source.get('provider')=='yfinance' and source.get('symbol')==ticker+'.JK')
                report['financial_snapshot_evidence']=source
            report['financial_source_pages']=refs
        check(coverage,'wsj_source' if self.financial_provider=='wsj' else 'yfinance_source',identity_ok,
              f'{self.financial_provider} snapshot identity/source matched' if identity_ok else snapshot_error or f'Missing or mismatched {self.financial_provider} company snapshot')
        check(coverage,'financial_evidence',evidence_ok,'Financial source evidence retained' if evidence_ok else 'Financial source references and hashes required')
        valuation=None; trace=None; valuation_error=None
        if identity_ok and current:
            try:
                valuation,trace=estimate(snapshot,latest['close'],asof,self.valuation_config,fx,use_reported_tax=True)
                report['valuation']=valuation; report['valuation_trace']=trace
                report['warnings'].extend(valuation['warnings'].split('; '))
            except (InputError,KeyError,TypeError,ValueError) as exc: valuation_error=str(exc)
        check(coverage,'aligned_financials',valuation is not None,valuation_error or ('Fresh aligned income/balance inputs and valid currency' if valuation else 'Financial calculation requires matching provider inputs and a matching price'),
              {'statement_date':valuation['statement_date'],'shares':valuation['shares'],'currency':valuation['financial_currency']} if valuation else None)
        models={}; required=[]
        sector=(snapshot.get('metadata',{}).get('sector') or '').lower() if snapshot else ''
        financial=sector in ('financial services','financials','financial','bank','banks')
        for method in ('ddm','rim','eva'):
            value=valuation.get(method) if valuation else None
            if method=='eva' and financial:
                models[method]={'status':'NOT_APPLICABLE','value':None,'reason':'EVA is excluded for financial companies'}
            elif method=='ddm' and trace and trace['inputs']['dividends']==0:
                models[method]={'status':'NOT_APPLICABLE','value':None,'reason':'Aligned annual common dividends explicitly equal zero'}
            else:
                required.append(method)
                reason=trace['scenarios']['base']['reasons'].get(method,'Available') if trace else 'Financial inputs unavailable'
                if method=='eva' and snapshot and not sector: reason='Sector applicability unknown; EVA cannot be certified'
                models[method]={'status':'AVAILABLE' if value is not None else 'UNAVAILABLE','value':value,'reason':reason}
        report['models']=models; report['required_models']=required
        all_models=bool(valuation) and all(models[m]['status']=='AVAILABLE' for m in required)
        count=sum(m['status']=='AVAILABLE' for m in models.values())
        check(coverage,'applicable_models',all_models,'Every applicable model available' if all_models else 'Missing an applicable valuation model',models)
        check(coverage,'model_corroboration',count>=self.profile['minimum_methods'],f'{count} models; at least {self.profile["minimum_methods"]} required')
        scenario_ok=bool(trace) and all(trace['scenarios'][s]['values'][m] is not None for s in ('bear','base','bull') for m in required)
        check(coverage,'scenarios',scenario_ok,'Applicable models have complete bear/base/bull sensitivity' if scenario_ok else 'Incomplete sensitivity for applicable models')
        reliable=valuation is not None and valuation['dispersion'] is not None and valuation['dispersion']<=self.valuation_config['maximum_dispersion']
        check(quality,'valuation_agreement',reliable,'Model dispersion within limit' if reliable else 'Missing or excessive model dispersion',
              {'dispersion':valuation['dispersion'] if valuation else None,'maximum':self.valuation_config['maximum_dispersion']})
        ratio=valuation['fair_value']/latest['close'] if valuation and valuation['fair_value'] is not None else None
        f=self.config['fundamental']
        ratio_ok=ratio is not None and f['minimum_value_price_ratio']<=ratio<=f['maximum_value_price_ratio']
        check(quality,'value_price_ratio',ratio_ok,'Value/price ratio within configured bounds' if ratio_ok else 'Missing or implausible modeled value/price ratio',{'ratio':ratio,'minimum':f['minimum_value_price_ratio'],'maximum':f['maximum_value_price_ratio']})
        technical=None; plan=None; technical_error=None; turnover=None
        if enough and current:
            try:
                technical=indicators(rows,self.config)
                technical.update({'rsi':rsi([r['close'] for r in rows],self.config['technical']['rsi_period'])[-1],
                                  'sma20':sum(r['close'] for r in rows[-20:])/20,
                                  'sma60':sum(r['close'] for r in rows[-60:])/60,
                                  'return20':latest['close']/rows[-21]['close']-1})
                if any(v is None or not math.isfinite(v) for k,v in technical.items() if k not in ('stoch_cross','macd_cross')) or technical['atr']<=0:
                    raise InputError('Technical indicators unavailable or invalid')
                plan=conditional_plan(rows,technical,self.config)
                turnover=median(r['traded_value_idr'] for r in rows[-self.config['execution']['turnover_sessions']:])
                report.update(technical=technical,plan=plan,median_turnover_idr=turnover,
                              price_source=latest['source'],close=latest['close'])
            except (InputError,KeyError,TypeError,ZeroDivisionError) as exc: technical_error=str(exc)
        check(coverage,'technical_indicators',technical is not None and technical_error is None,technical_error or ('All configured indicators available' if technical else 'Insufficient current price history for indicators'))
        levels_ok=bool(plan and 0<plan['stop_loss_price']<plan['entry_price'] and plan['tp1_price'] is not None and plan['entry_price']<plan['tp1_price'])
        check(coverage,'conditional_levels',levels_ok,'Observed conditional entry/stop/target interval available' if levels_ok else 'Cannot derive a valid observed stop/entry/target interval')
        costs_ok=bool(plan and plan['net_rr'] is not None)
        check(coverage,'cost_estimate',costs_ok,'Configured fee/slippage assumptions support estimated reward/risk' if costs_ok else 'Estimated reward/risk unavailable')
        entry_mos=1-plan['entry_price']/valuation['fair_value'] if plan and valuation and valuation['fair_value'] else None
        discount_pass=not f['require_discount'] or entry_mos is not None and entry_mos>=f['entry_mos']
        check(quality,'discount_filter',discount_pass,'Discount filter disabled' if not f['require_discount'] else 'Entry MOS meets threshold' if discount_pass else 'Entry MOS below required discount',
              {'required':f['require_discount'],'entry_mos':entry_mos,'threshold':f['entry_mos']})
        min_turnover=self.config['execution']['minimum_turnover_idr']
        check(coverage,'liquidity_data',turnover is not None,'Turnover window available' if turnover is not None else 'Turnover unavailable')
        check(quality,'liquidity_floor',turnover is not None and turnover>=min_turnover,'Liquidity floor met' if turnover is not None and turnover>=min_turnover else 'Liquidity below threshold or missing',{'median_turnover_idr':turnover,'minimum':min_turnover,'basis':'price_feed_turnover; estimates remain estimates'})
        if rows and any(not r.get('actions_checked',False) for r in rows): report['warnings'].append('Corporate actions not reviewed')
        if rows and any(r.get('turnover_basis')!='actual_regular' for r in rows[-self.config['execution']['turnover_sessions']:]): report['warnings'].append('Turnover estimated; execution/liquidity is not independently verified')
        if plan: report['warnings'].extend(plan['risk_reasons'])
        report['warnings'].extend(['Broker flow ON_HOLD','Unreviewed valuations and rolling levels; this is research, not trade qualification'])
        if valuation and valuation['current_mos'] is not None and valuation['current_mos']<0:
            report['warnings'].append('Price exceeds modeled mean fair value; no margin-of-safety credit')
        if technical and sum((latest['close']>technical['sma20'],technical['sma20']>technical['sma60'],technical['macd']>technical['macd_signal']))==0:
            report['warnings'].append('Weak trend: close below SMA20, SMA20 below SMA60 and MACD below signal')
        report['coverage_complete']=all(v['status']=='PASS' for v in coverage.values())
        report['quality_passed']=all(v['status']=='PASS' for v in quality.values())
        if report['coverage_complete'] and technical and valuation and turnover is not None:
            report['score']=self._score(latest,valuation,technical,turnover)
        report['eligible_for_ranking']=report['coverage_complete'] and report['quality_passed'] and report['score'] is not None and report['score']['total']>=self.profile['ranking']['minimum_score']
        report['ranking_status']='ELIGIBLE_UNRANKED' if report['eligible_for_ranking'] else 'EXCLUDED'
        report['missing_inputs']=[{'check':k,'reason':v['reason']} for k,v in coverage.items() if v['status']=='FAIL']
        report['failed_quality_checks']=[{'check':k,'reason':v['reason']} for k,v in quality.items() if v['status']=='FAIL']
        quotes_valid=False
        if latest:
            try: quotes_valid=0<number(latest.get('bid'),'bid')<=number(latest.get('ask'),'ask')
            except InputError: pass
        execution={'quotes_available':quotes_valid,
                   'corporate_actions_reviewed':bool(rows and all(r.get('actions_checked',False) for r in rows)),
                   'reward_risk_passed':bool(plan and plan['net_rr'] is not None and plan['net_rr']>=self.config['execution']['minimum_net_rr']),
                   'valuation_reviewed':False,'broker_flow_available':False,'trade_qualified':False}
        report['execution_readiness']=execution
        report['input_sha256']=digest({'prices':rows,'snapshot':original_snapshot,'fx':fx,'sessions':expected})
        report['warnings']=list(dict.fromkeys(report['warnings']))
        report['explanation']=self._explain(report)
        return primitive(report)

    def _score(self,latest,v,t,turnover):
        mos=v['current_mos']; dispersion=v['dispersion']; stress=1-latest['close']/v['bear_value'] if v['bear_value'] else None
        facts=[('Margin of safety',50 if mos>=self.config['fundamental']['entry_mos'] else 25 if mos>0 else 0,
                {'mos':mos,'full_credit_threshold':self.config['fundamental']['entry_mos']},'50 if MOS meets configured threshold; 25 if positive; otherwise 0'),
               ('Model agreement',30 if dispersion<=0.15 else 20 if dispersion<=0.3 else 10,
                {'dispersion':dispersion},'30 at dispersion<=15%; 20 at <=30%; otherwise 10 (quality gate still applies)'),
               ('Bear-case MOS',20 if stress is not None and stress>=self.config['fundamental']['stressed_mos_threshold'] else 0,
                {'bear_mos':stress,'threshold':self.config['fundamental']['stressed_mos_threshold']},'20 if bear-case MOS meets threshold; otherwise 0')]
        signals=[('Close above SMA20',latest['close']>t['sma20'],25,{'close':latest['close'],'sma20':t['sma20']}),
                 ('SMA20 above SMA60',t['sma20']>t['sma60'],25,{'sma20':t['sma20'],'sma60':t['sma60']}),
                 ('MACD above signal',t['macd']>t['macd_signal'],20,{'macd':t['macd'],'signal':t['macd_signal']}),
                 ('Stochastic K above D',t['stoch_k']>t['stoch_d'],15,{'k':t['stoch_k'],'d':t['stoch_d']}),
                 ('Volume confirmation',t['volume_multiple']>=self.config['technical']['volume_multiple'],15,
                  {'multiple':t['volume_multiple'],'threshold':self.config['technical']['volume_multiple']})]
        maximum=self.config['execution']['minimum_turnover_idr']*self.profile['liquidity_full_credit_multiple']
        components={'fundamental':{'raw_score':sum(x[1] for x in facts),'factors':[{'name':name,'points':points,'evidence':evidence,'rule':rule} for name,points,evidence,rule in facts]},
                    'technical':{'raw_score':sum(points for _,passed,points,_ in signals if passed),
                                 'factors':[{'name':name,'points':points if passed else 0,'passed':passed,'evidence':evidence} for name,passed,points,evidence in signals]},
                    'liquidity':{'raw_score':min(100,100*turnover/maximum),'factors':[{'name':'Median turnover','evidence':{'median':turnover,'full_credit_turnover':maximum},'rule':'min(100, 100 * median_turnover / full_credit_turnover)'}]}}
        for key,component in components.items():
            component['weight_percent']=self.profile['weights'][key]
            component['contribution']=component['raw_score']*component['weight_percent']/100
        return {'total':sum(c['contribution'] for c in components.values()),'components':components,
                'formula':' + '.join(f'{key} * {weight:g}%' for key,weight in self.profile['weights'].items()),
                'broker_score':None,'missing_data_renormalized':False,'profile':self.profile['profile_name']}

    def _explain(self,report):
        if not report['eligible_for_ranking']:
            reasons=[r['reason'] for r in report['missing_inputs']+report['failed_quality_checks']]
            if not reasons: reasons=['Research score below configured minimum']
            return 'Excluded from top 10: '+ '; '.join(reasons)+'. Available evidence remains inspectable.'
        score=report['score']; parts=score['components']; v=report['valuation']
        methods=', '.join(f"{key.upper()} {value['value']:,.0f}" if value['status']=='AVAILABLE' else f"{key.upper()} N/A ({value['reason']})" for key,value in report['models'].items())
        return (f"Coverage-qualified research score {score['total']:.2f}/100: "
                f"fundamental contributes {parts['fundamental']['contribution']:.2f}, technical {parts['technical']['contribution']:.2f}, liquidity {parts['liquidity']['contribution']:.2f}. "
                f"{self.financial_provider.upper()} models: {methods}. Mean {v['fair_value']:,.0f} versus close {report['close']:,.0f}; MOS {v['current_mos']:.1%}; dispersion {v['dispersion']:.1%}. "
                'All applicable models and required research inputs passed coverage checks; trade qualification remains unverified.')

    def screen(self,universe,prices,snapshots,asof,fx_by_currency=None,sessions=None,source_errors=None):
        tickers=[symbol_for(t)[0] for t in universe]
        if not tickers or len(tickers)!=len(set(tickers)): raise InputError('Explicit unique nonempty universe required')
        calendar=sessions
        if calendar is None:
            dates=set()
            for ticker in tickers:
                for row in prices.get(ticker,[]) or []:
                    try:
                        d=row['date'] if isinstance(row['date'],date) else day(row['date'],'price date')
                        if d<=asof: dates.add(d)
                    except (InputError,KeyError,TypeError): pass
            calendar=sorted(dates)
        reports=[]
        for ticker in sorted(tickers):
            snapshot=snapshots.get(ticker)
            metadata=snapshot.get('metadata',{}) if isinstance(snapshot,dict) else {}
            currency=metadata.get('financialCurrency') if isinstance(metadata,dict) else None
            reports.append(self.inspect_ticker(ticker,prices.get(ticker,[]),asof,snapshot,
                           (fx_by_currency or {}).get(currency),calendar,(source_errors or {}).get(ticker,[])))
        ranked=[r for r in reports if r['eligible_for_ranking']]
        ranked.sort(key=lambda r:(-r['score']['total'],-r['valuation']['current_mos'],-r['median_turnover_idr'],r['ticker']))
        limit=self.profile['ranking']['max_results']; selected=ranked[:limit]
        for index,row in enumerate(ranked):
            row['ranking_status']='SELECTED' if index<limit else 'QUALIFIED_NOT_SELECTED'
            row['rank']=index+1
            row['selection_reason']='Within configured result limit' if index<limit else f'Rank {index+1} exceeds result limit {limit}'
            if index+1<len(ranked):
                next_row=ranked[index+1]
                differences={k:row['score']['components'][k]['contribution']-next_row['score']['components'][k]['contribution'] for k in self.profile['weights']}
                lead=max(differences,key=differences.get)
                row['rank_comparison']={'next_ticker':next_row['ticker'],'score_difference':row['score']['total']-next_row['score']['total'],
                                        'component_differences':differences,
                                        'reason':f"Largest positive contribution difference: {lead}" if row['score']['total']!=next_row['score']['total'] else 'Score tie resolved by MOS, liquidity, then ticker'}
            row['explanation']=f"Rank {index+1}. "+row['explanation']
            if index>=limit: row['explanation']+=' Not selected: '+row['selection_reason']+'.'
        failures=Counter(check['check'] for r in reports for check in r['missing_inputs']+r['failed_quality_checks'])
        return {'engine_version':VERSION,'as_of':asof.isoformat(),'profile':self.profile,
                'config_sha256':self.config_hash,'universe_sha256':digest(sorted(tickers)),
                'universe':sorted(tickers),'universe_count':len(tickers),'coverage_complete_count':sum(r['coverage_complete'] for r in reports),
                'qualifying_count':len(ranked),'selected_count':len(selected),'requested_slots':limit,
                'unfilled_slots':limit-len(selected),'all_selected_have_full_coverage':all(r['coverage_complete'] and r['quality_passed'] for r in selected),
                'broker_flow_status':'ON_HOLD','review_status':'UNREVIEWED_ESTIMATES',
                'failure_counts':dict(failures),'selection_policy':'No missing-input score renormalization or padding; EVA N/A for financial firms; zero-dividend DDM N/A only with observed zero.',
                'top10':selected,'companies':reports}
