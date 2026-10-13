"""Auditable, unreviewed annual-statement DDM/RIM/EVA estimates."""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import mean

from .engine import InputError, day, file_hash, load_prices, number, write_csv
from .fetch import JAKARTA, symbol_for
from .fx import fetch_fx, validate_fx

DEFAULT_CONFIG=Path(__file__).parent.parent/'valuation-config.json'
FIELDS=['ticker','price_date','valuation_date','statement_date','status','validated',
        'sector','financial_currency','model_currency','fx_rate','fx_date','tax_rate','tax_rate_source',
        'valuation_price','eva','ddm','rim','fair_value',
        'bear_value','bull_value','method_count','dispersion','current_mos',
        'fundamental_verdict','shares','book_equity','net_income','dividends_paid',
        'payout_ratio','financial_provider','share_count_basis','valuation_source','snapshot_sha256','warnings','method_reasons']


def load_assumptions(path=DEFAULT_CONFIG):
    config=json.loads(Path(path).read_text(encoding='utf-8'))
    return validate_assumptions(config)


def validate_assumptions(config):
    required={'forecast_years','reporting_lag_days','maximum_statement_age_days',
              'tax_rate','default_payout_ratio','maximum_dispersion','fair_price_band','scenarios'}
    if set(config)!=required: raise InputError('Unexpected or missing valuation settings')
    for key in ('forecast_years','reporting_lag_days','maximum_statement_age_days'):
        if type(config[key]) is not int or config[key]<=0: raise InputError(f'Invalid {key}')
    if config['forecast_years']>20: raise InputError('forecast_years must be <=20')
    for key in ('tax_rate','default_payout_ratio','maximum_dispersion','fair_price_band'):
        config[key]=number(config[key],key)
        if not 0<=config[key]<=1: raise InputError(f'Invalid {key}')
    if set(config['scenarios'])!={'bear','base','bull'}: raise InputError('Require bear/base/bull scenarios')
    for scenario,settings in config['scenarios'].items():
        if set(settings)!={'cost_of_equity','wacc','growth','terminal_growth','earnings_multiplier'}:
            raise InputError(f'Invalid {scenario} keys')
        for key in settings: settings[key]=number(settings[key],f'{scenario}.{key}')
        if not 0<settings['cost_of_equity']<=1 or not 0<settings['wacc']<=1:
            raise InputError('Discount rates must be positive and <=1')
        if not -0.5<=settings['growth']<=0.5 or not 0<=settings['terminal_growth']<min(settings['cost_of_equity'],settings['wacc']):
            raise InputError('Require bounded growth and terminal growth below discount rates')
        if not 0<settings['earnings_multiplier']<=2: raise InputError('Invalid earnings multiplier')
    return config


def serialize_statement(frame):
    periods={}
    for column in frame.columns:
        values={}
        for label,value in frame[column].items():
            try: value=float(value)
            except (TypeError,ValueError): continue
            if math.isfinite(value): values[str(label)]=value
        periods[column.date().isoformat()]=values
    return periods


def fetch_snapshot(ticker):
    import yfinance as yf
    _,symbol=symbol_for(ticker)
    stock=yf.Ticker(symbol)
    info=stock.get_info()
    if info.get('symbol')!=symbol:
        raise InputError('Financial metadata symbol does not match requested IDX ticker')
    errors={}; statements={}
    for name,attribute in [('income','income_stmt'),('balance','balance_sheet'),('cashflow','cashflow')]:
        try: statements[name]=serialize_statement(getattr(stock,attribute))
        except Exception as exc:
            statements[name]={}; errors[name]=str(exc)
    return {'ticker':ticker,'symbol':symbol,'provider':'yfinance',
            'fetched_at':datetime.now(timezone.utc).isoformat(),
            'metadata':{k:info.get(k) for k in ('symbol','sector','industry','currency','financialCurrency')},
            'statements':statements,'errors':errors}


def pick(values,*aliases):
    for key in aliases:
        value=values.get(key)
        if value is not None:
            return number(value,key),key
    return None,None


def model_values(inputs,scenario,years):
    """Return IDR/share models plus explicit applicability reasons."""
    ke=scenario['cost_of_equity']; wacc=scenario['wacc']
    growth=scenario['growth']; terminal=scenario['terminal_growth']
    multiplier=scenario['earnings_multiplier']; shares=inputs['shares']
    equity=inputs['equity']; income=inputs['income']; dividends=inputs['dividends']
    values={'ddm':None,'rim':None,'eva':None}; reasons={}; paths={}
    if dividends is None or dividends<=0:
        reasons['ddm']='No positive aligned annual common dividends'
    elif income is None or income<=0 or dividends>income:
        reasons['ddm']='Dividend payout exceeds positive common earnings; sustainable DDM not established'
    else:
        div=dividends*multiplier; pv=0; path=[]
        for year in range(1,years+1):
            div*=1+growth; pv+=div/(1+ke)**year
            path.append({'year':year,'dividend':div})
        tv=div*(1+terminal)/(ke-terminal)
        values['ddm']=(pv+tv/(1+ke)**years)/shares
        paths['ddm']={'forecast':path,'terminal_value':tv}
    if income is None or income<=0 or equity is None or equity<=0:
        reasons['rim']='Positive common earnings and book equity required'
    else:
        initial_roe=income*multiplier/equity; book=equity; pv=0; path=[]
        for year in range(1,years+1):
            # Excess ROE fades linearly to zero after the explicit forecast.
            roe=ke+(initial_roe-ke)*(1-(year-1)/years)
            earnings=book*roe; residual=earnings-ke*book
            pv+=residual/(1+ke)**year
            ending=book+earnings*(1-inputs['payout'])
            path.append({'year':year,'beginning_book':book,'roe':roe,'earnings':earnings,
                         'residual_income':residual,'ending_book':ending})
            book=ending
        values['rim']=(equity+pv)/shares
        paths['rim']={'forecast':path,'terminal_residual_income':0}
    if inputs['financial']:
        reasons['eva']='EVA excluded for financial companies; debt is operating funding'
    elif any(inputs[k] is None for k in ('operating_income','debt','cash','equity','minority')):
        reasons['eva']='Require aligned operating income, equity, minority interests, debt and cash'
    else:
        invested=equity+inputs['minority']+inputs['debt']-inputs['cash']
        if invested<=0 or inputs['operating_income']<=0:
            reasons['eva']='Positive invested capital and operating income required'
        else:
            nopat=inputs['operating_income']*(1-inputs['tax_rate'])*multiplier
            roic=nopat/invested; capital=invested; pv=0; path=[]
            for year in range(1,years+1):
                eva=(roic-wacc)*capital
                pv+=eva/(1+wacc)**year
                path.append({'year':year,'beginning_capital':capital,'nopat':roic*capital,'eva':eva})
                capital*=1+growth
            # Stable excess ROIC retained in perpetuity; visibly assumption-sensitive.
            terminal_eva=path[-1]['eva']*(1+terminal)
            tv=terminal_eva/(wacc-terminal)
            enterprise=invested+pv+tv/(1+wacc)**years
            equity_value=enterprise-inputs['debt']+inputs['cash']-inputs['minority']
            values['eva']=equity_value/shares
            paths['eva']={'forecast':path,'terminal_value':tv,'enterprise_value':enterprise}
    for method,value in values.items():
        if value is not None and (not math.isfinite(value) or value<=0):
            reasons[method]='Nonpositive or nonfinite modeled equity value; omitted'
            values[method]=None
    return values,reasons,paths


def estimate(snapshot,price,asof,config,fx=None,use_reported_tax=False):
    ticker=snapshot['ticker']; meta=snapshot['metadata']; statements=snapshot['statements']
    if meta.get('currency')!='IDR': raise InputError('IDX price currency must be IDR')
    financial_currency=meta.get('financialCurrency')
    if financial_currency=='IDR': fx_rate=1.0; fx_date=asof.isoformat()
    elif financial_currency=='USD' and fx is not None:
        fx_rate=validate_fx(fx,'USD',asof); fx_date=fx['rate_date']
    else:
        raise InputError('Financial currency requires a validated FX snapshot (supported: IDR/USD)')
    cutoff=asof-timedelta(days=config['reporting_lag_days'])
    dates=sorted(set(statements.get('income',{}))&set(statements.get('balance',{})),reverse=True)
    eligible=[d for d in dates if day(d,'statement date')<=cutoff
              and (asof-day(d,'statement date')).days<=config['maximum_statement_age_days']]
    if not eligible: raise InputError('No aligned annual income/balance period within lag and age limits')
    period=eligible[0]; inc=statements['income'][period]; balance=statements['balance'][period]
    cashflow=statements.get('cashflow',{}).get(period,{})
    shares,shares_key=pick(balance,'Ordinary Shares Number','Annual Average Shares')
    equity,equity_key=pick(balance,'Common Stock Equity')
    income,income_key=pick(inc,'Net Income Common Stockholders','Diluted NI Availto Com Stockholders')
    op,op_key=pick(inc,'Operating Income')
    debt,debt_key=pick(balance,'Total Debt')
    cash,cash_key=pick(balance,'Cash And Cash Equivalents')
    minority,minority_key=pick(balance,'Minority Interest')
    dividends,div_key=pick(cashflow,'Common Stock Dividend Paid')
    # Only monetary model inputs are translated; share counts and ratios retain their units.
    equity,income,op,debt,cash,minority,dividends=[v*fx_rate if v is not None else None
                                               for v in (equity,income,op,debt,cash,minority,dividends)]
    if shares is None or shares<=0: raise InputError('Positive statement-sourced ordinary/annual average shares required')
    if equity is None or equity<=0: raise InputError('Positive common book equity required')
    if dividends is not None:
        if dividends>0: raise InputError('Unexpected positive dividend cashflow sign')
        dividends=-dividends
    warnings=['Unreviewed model estimates; assumptions are not issuer guidance or calibrated market rates',
              'Latest retrieved statements may contain restatements; reporting lag is a heuristic, not publication-date proof',
              'Statement share count; subsequent splits, buybacks and dilution require review',
              'Annual common earnings are not normalized for one-off items or commodity cycles',
              'Initial ROE uses annual earnings divided by ending common equity; RIM assumes clean-surplus accounting']
    provider=snapshot.get('provider')
    if provider not in ('wsj','yfinance'): raise InputError('Unknown financial-statement provider')
    share_basis=snapshot.get('share_count_basis','annual period-end ordinary shares')
    if shares_key=='Annual Average Shares':
        warnings.append('WSJ annual average share count used; comparison with current/period-end shares requires review')
    if provider=='wsj':
        warnings.append('WSJ financial tables; page retrieval freshness/publication timing is not guaranteed')
        for kind,reason in snapshot.get('errors',{}).items():
            warnings.append(f'WSJ {kind} coverage unavailable: {reason}')
    if financial_currency!='IDR':
        warnings.append(f'USD financial inputs translated to IDR at {fx_rate:g} dated {fx_date}; future FX held constant, FX risk not modeled')
    tax_rate=config['tax_rate']; tax_source='configured_assumption'
    if use_reported_tax:
        tax,tax_key=pick(inc,'Tax Provision'); pretax,pretax_key=pick(inc,'Pretax Income')
        if tax is not None and pretax is not None and pretax>0 and 0<=tax/pretax<=0.6:
            tax_rate=tax/pretax; tax_source=f'reported_effective:{tax_key}/{pretax_key}'
        else: warnings.append('Reported effective tax unavailable/abnormal; configured tax assumption retained')
    if dividends is not None and income is not None and income>0:
        payout=min(dividends/income,1)
        if dividends>income: warnings.append('RIM payout capped at 100%; DDM excluded for unsustainable annual payout')
    else:
        payout=config['default_payout_ratio']
        warnings.append('RIM payout uses configured assumption because aligned dividends/positive earnings are unavailable')
    if income is None or income<=0: warnings.append('Nonpositive or unavailable common earnings; income-based models unavailable')
    if not cashflow: warnings.append('No aligned annual cashflow; DDM unavailable')
    sector=meta.get('sector') or ''
    financial=sector.lower() in ('financial services','financials','financial','bank','banks')
    if not sector: warnings.append('Sector missing; EVA omitted until financial-sector applicability established')
    # Consolidated operating profit requires a minority-interest bridge; do not assume missing minorities are zero.
    inputs={'shares':shares,'equity':equity,'income':income,'dividends':dividends,
            'payout':payout,'operating_income':op,'debt':debt,'cash':cash,'minority':minority,
            'financial':financial or not sector,'tax_rate':tax_rate}
    results={}; audit={}
    for name,scenario in config['scenarios'].items():
        values,reasons,paths=model_values(inputs,scenario,config['forecast_years'])
        results[name]=values; audit[name]={'values':values,'reasons':reasons,'paths':paths}
    base=results['base']; available=[m for m,v in base.items() if v is not None]
    values=[base[m] for m in available]; fair=mean(values) if values else None
    dispersion=(max(values)-min(values))/fair if values else None
    unreliable=dispersion is not None and dispersion>config['maximum_dispersion']
    verdict='UNAVAILABLE' if fair is None else 'UNRELIABLE_ESTIMATE' if unreliable else (
        'UNDERVALUED_ESTIMATE' if price<fair*(1-config['fair_price_band']) else
        'OVERVALUED_ESTIMATE' if price>fair*(1+config['fair_price_band']) else 'FAIR_ESTIMATE')
    if unreliable: warnings.append('Model disagreement exceeds configured dispersion limit; do not treat mean as reliable')
    if len(values)==1: warnings.append('Only one usable model; no independent model corroboration')
    if 'eva' in available: warnings.append('EVA uses unadjusted accounting capital, assumed tax/WACC and persistent terminal excess ROIC; nonoperating assets and minority market value not reconciled')
    def scenario_mean(name):
        # Same base method set; changing coverage must not disguise sensitivity.
        return mean(results[name][m] for m in available) if available and all(results[name][m] is not None for m in available) else None
    row={'ticker':ticker,'price_date':asof.isoformat(),'valuation_date':datetime.now(JAKARTA).date().isoformat(),
         'statement_date':period,'status':'UNREVIEWED_ESTIMATE' if fair is not None else 'UNAVAILABLE',
         'validated':'false','sector':sector,'financial_currency':financial_currency,'model_currency':'IDR',
         'fx_rate':fx_rate,'fx_date':fx_date,'tax_rate':tax_rate,'tax_rate_source':tax_source,
         'valuation_price':price,**base,
         'fair_value':fair,'bear_value':scenario_mean('bear'),'bull_value':scenario_mean('bull'),
         'method_count':len(values),'dispersion':dispersion,'current_mos':1-price/fair if fair is not None else None,
         'fundamental_verdict':verdict,'shares':shares,'book_equity':equity,'net_income':income,
         'dividends_paid':dividends,'payout_ratio':payout,'financial_provider':provider,'share_count_basis':share_basis,
         'valuation_source':('WSJ / FactSet' if provider=='wsj' else 'yfinance')+' annual statements; unreviewed models',
         'warnings':'; '.join(warnings),'method_reasons':json.dumps(audit['base']['reasons'],sort_keys=True)}
    trace={'inputs':inputs,'selected_statement_date':period,
           'currency_translation':{'source_currency':financial_currency,'model_currency':'IDR',
                                   'rate':fx_rate,'date':fx_date,'fx_snapshot':fx if financial_currency!='IDR' else None},
           'financial_provider':provider,'source_pages':snapshot.get('source_pages',[]),
           'source_field_mapping':snapshot.get('field_mapping',{}),'share_count_basis':share_basis,
           'tax_rate_source':tax_source,'input_rows':{
        'shares':shares_key,'equity':equity_key,'income':income_key,'operating_income':op_key,
        'debt':debt_key,'cash':cash_key,'minority':minority_key,'dividends':div_key},
        'scenarios':audit,'point_in_time_verified':False}
    return row,trace


def generate(prices_path,asof,output,config_path=DEFAULT_CONFIG,snapshot_dir=None,tickers=None,
             fx_snapshot=None,use_reported_tax=False,provider='wsj',wsj_pages=None):
    output=Path(output)
    if output.exists(): raise InputError('Valuation output already exists; choose a new directory')
    config=load_assumptions(config_path); prices=load_prices(prices_path)
    if provider not in ('wsj','yfinance'): raise InputError('Unknown financial provider')
    if wsj_pages and (provider!='wsj' or snapshot_dir): raise InputError('--wsj-pages requires WSJ provider and cannot mix with normalized snapshots')
    universe=sorted({symbol_for(t)[0] for t in tickers}) if tickers else sorted(prices)
    output.mkdir(parents=True); (output/'raw').mkdir(); (output/'models').mkdir(); (output/'fx').mkdir()
    rows=[]; errors=[]; sources=[]
    fx_cache={}; fx_errors={}; fx_sources=[]
    if fx_snapshot:
        supplied=json.loads(Path(fx_snapshot).read_text(encoding='utf-8'))
        validate_fx(supplied,supplied.get('base_currency'),asof)
        fx_cache[supplied['base_currency']]=supplied
    for ticker in universe:
        try:
            candles=[r for r in prices.get(ticker,[]) if r['date']==asof]
            if not candles: raise InputError('No matching decision-date price')
            if snapshot_dir:
                snapshot=json.loads((Path(snapshot_dir)/f'{ticker}.json').read_text(encoding='utf-8'))
            elif provider=='wsj':
                from .wsj import fetch_snapshot as fetch_wsj
                snapshot=fetch_wsj(ticker,wsj_pages,output/'wsj-pages')
            else: snapshot=fetch_snapshot(ticker)
            if snapshot['ticker']!=ticker or snapshot['symbol']!=ticker+'.JK': raise InputError('Snapshot symbol mismatch')
            if snapshot.get('provider')!=provider: raise InputError('Financial snapshot source does not match requested provider; fallback forbidden')
            raw_path=output/'raw'/f'{ticker}.json'
            raw_path.write_text(json.dumps(snapshot,indent=2,allow_nan=False)+'\n',encoding='utf-8')
            source={'ticker':ticker,'path':str(raw_path.resolve()),'sha256':file_hash(raw_path)}
            sources.append(source)
            currency=snapshot['metadata'].get('financialCurrency')
            if currency not in ('IDR',None) and currency not in fx_cache:
                if currency in fx_errors: raise InputError(fx_errors[currency])
                if snapshot_dir: raise InputError('Offline foreign-currency financials require --fx-snapshot')
                try: fx_cache[currency]=fetch_fx(currency,asof)
                except Exception as exc:
                    fx_errors[currency]=str(exc); raise
            row,trace=estimate(snapshot,candles[0]['close'],asof,config,fx_cache.get(currency),use_reported_tax)
            row['snapshot_sha256']=source['sha256']; rows.append(row)
            (output/'models'/f'{ticker}.json').write_text(json.dumps(trace,indent=2,allow_nan=False)+'\n',encoding='utf-8')
            print(f"{ticker}: {row['method_count']} models; {row['fundamental_verdict']}",flush=True)
        except Exception as exc:
            errors.append({'ticker':ticker,'reason':str(exc)})
            print(f'{ticker}: valuation unavailable: {exc}',file=sys.stderr,flush=True)
    write_csv(output/'estimates.csv',rows,FIELDS)
    write_csv(output/'errors.csv',errors,['ticker','reason'])
    for currency,fx in fx_cache.items():
        path=output/'fx'/f'{currency}IDR.json'
        path.write_text(json.dumps(fx,indent=2,allow_nan=False)+'\n',encoding='utf-8')
        fx_sources.append({'symbol':fx['symbol'],'path':str(path.resolve()),'sha256':file_hash(path),
                           'rate':fx['rate'],'rate_date':fx['rate_date']})
    (output/'assumptions.resolved.json').write_text(json.dumps(config,indent=2)+'\n',encoding='utf-8')
    report={'estimator_version':'0.3','financial_provider':provider,'company_data_fallback':False,
            'created_at':datetime.now(timezone.utc).isoformat(),'price_date':asof.isoformat(),
            'status':'UNREVIEWED_ESTIMATES','point_in_time_verified':False,'broker_flow_status':'ON_HOLD',
            'prices_sha256':file_hash(prices_path),'assumptions_sha256':file_hash(output/'assumptions.resolved.json'),
            'requested_count':len(universe),'estimated_count':sum(r['fair_value'] is not None for r in rows),
            'sources':sources,'fx_sources':fx_sources,'use_reported_tax':use_reported_tax,'errors':errors}
    (output/'run.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    lines=['# Unreviewed valuation estimates','',f'Price date: {asof}. Broker flow: ON_HOLD.',
           f'Company financial source: **{provider.upper()}**. No company-data fallback.',
           '', 'Latest retrieved annual statements with a reporting-lag heuristic; not a historical point-in-time valuation.',
           '', '| Ticker | DDM | RIM | EVA | Base mean | Bear | Bull | Verdict |',
           '|---|---|---|---|---|---|---|---|']
    for row in rows:
        cells=[row['ticker']]+[f"{row[k]:,.0f}" if row[k] is not None else 'unavailable'
                             for k in ('ddm','rim','eva','fair_value','bear_value','bull_value')]+[row['fundamental_verdict']]
        lines.append('| '+' | '.join(cells)+' |')
    lines+=['','All values are IDR per share. The mean is descriptive; high model dispersion is flagged as unreliable.',
            'See estimates.csv for missing-model reasons, MOS and warnings; models/ for every forecast and raw/ for source data.',
            'No output is analyst-validated. See assumptions.resolved.json for discount rates, growth, tax and payout assumptions.']
    if errors:
        lines+=['','Unavailable tickers:']+[f"- {e['ticker']}: {e['reason']}" for e in errors]
    (output/'report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    return rows,report


def main(argv=None):
    parser=argparse.ArgumentParser(description='Estimate unreviewed DDM/RIM/EVA from WSJ annual financials; company-data source enforced.')
    parser.add_argument('--prices',required=True)
    parser.add_argument('--as-of',required=True)
    parser.add_argument('--output',required=True)
    parser.add_argument('--assumptions',default=str(DEFAULT_CONFIG))
    parser.add_argument('--snapshots',help='Existing raw snapshot directory; no network when supplied')
    parser.add_argument('--tickers',nargs='+')
    parser.add_argument('--fx-snapshot',help='Saved USDIDR FX JSON; required for offline USD statements')
    parser.add_argument('--use-reported-tax',action='store_true',help='Use aligned reported effective tax when usable; otherwise explicit configured fallback')
    parser.add_argument('--financial-provider',choices=['wsj','yfinance'],default='wsj')
    parser.add_argument('--wsj-pages',help='Directory containing saved WSJ statement pages/excerpts')
    args=parser.parse_args(argv)
    try:
        asof=day(args.as_of,'as-of'); now=datetime.now(JAKARTA)
        cutoff=now.date() if now.hour>=18 else now.date()-timedelta(days=1)
        if asof>cutoff: raise InputError('Choose a completed price session')
        rows,report=generate(args.prices,asof,args.output,args.assumptions,args.snapshots,args.tickers,
                             args.fx_snapshot,args.use_reported_tax,args.financial_provider,args.wsj_pages)
        print(f"Estimated {report['estimated_count']}/{report['requested_count']} tickers: {Path(args.output)/'report.md'}")
        return 2 if report['errors'] or report['estimated_count']==0 else 0
    except (InputError,OSError,ValueError) as exc:
        print(f'Error: {exc}',file=sys.stderr); return 2


if __name__=='__main__': sys.exit(main())
