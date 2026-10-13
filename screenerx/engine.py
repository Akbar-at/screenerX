"""Deterministic screening from explicit, point-in-time CSV inputs.

Valuation method results and structural levels are supplied by the analyst.
Indicators, cohort flow, execution plans and composite ranks are calculated here.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
from collections import defaultdict
from datetime import date
from pathlib import Path
from statistics import mean, median


class InputError(ValueError):
    pass


def number(value, label, optional=False):
    if value is None or str(value).strip() == "":
        if optional:
            return None
        raise InputError(f"Missing {label}")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise InputError(f"Invalid number: {label}") from exc
    if not math.isfinite(result):
        raise InputError(f"Non-finite number: {label}")
    return result


def day(value, label):
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise InputError(f"Invalid ISO date: {label}") from exc


def truth(value, label):
    if str(value).lower() not in ("true", "false"):
        raise InputError(f"{label} must be true or false")
    return str(value).lower() == "true"


def load_config(path):
    try:
        config = json.loads(Path(path).read_text())
    except (ValueError, OSError) as exc:
        raise InputError(f"Cannot load config: {exc}") from exc
    validate_config(config)
    return config


def validate_config(c):
    # Reject unsupported settings instead of silently pretending they work.
    default = json.loads((Path(__file__).parent.parent / "config.json").read_text())
    def shape(actual, expected, prefix=""):
        if not isinstance(actual, dict) or set(actual) != set(expected):
            raise InputError(f"Config keys do not match supported schema at {prefix or 'root'}")
        for key, value in expected.items():
            if isinstance(value, dict):
                shape(actual[key], value, prefix + key + ".")
            elif isinstance(value, bool) and not isinstance(actual[key], bool):
                raise InputError(f"{prefix}{key} must be boolean")
            elif isinstance(value, list) and not isinstance(actual[key], list):
                raise InputError(f"{prefix}{key} must be a list")
    shape(c, default)
    if not isinstance(c['profile_name'], str) or not c['profile_name'].strip():
        raise InputError("profile_name must be nonempty")
    def bounded(v, label, low=0, high=None, integer=False):
        if isinstance(v, bool):
            raise InputError(f"{label} must be numeric")
        n = number(v, label)
        if n < low or (high is not None and n > high) or (integer and (not isinstance(v, int))):
            raise InputError(f"Out-of-range {label}")
    for k,v in c['weights'].items():
        bounded(v, 'weight '+k, high=100)
    if not math.isclose(sum(c['weights'].values()), 100, abs_tol=1e-8):
        raise InputError("Weights must sum to 100")
    bounded(c['ranking']['max_results'], 'max_results', 1, integer=True)
    bounded(c['ranking']['minimum_score'], 'minimum_score', high=100)
    f,b,t,e,s = (c[k] for k in ('fundamental','broker','technical','execution','scoring'))
    for k in ('entry_mos','high_maximum_dispersion','unreliable_maximum_dispersion','fair_price_band','stressed_mos_threshold'):
        bounded(f[k], k, high=1)
    if f['entry_mos'] >= 1 or f['fair_price_band'] >= 1:
        raise InputError('MOS and fair band must be below 1')
    bounded(f['high_minimum_methods'], 'high_minimum_methods', 1, 3, integer=True)
    bounded(f['valuation_max_age_days'], 'valuation_max_age_days', integer=True)
    if not f['high_maximum_dispersion'] < f['unreliable_maximum_dispersion']:
        raise InputError('High dispersion threshold must be below unreliable threshold')
    bounded(f['maximum_value_price_ratio'], 'maximum_value_price_ratio', 1)
    bounded(f['minimum_value_price_ratio'], 'minimum_value_price_ratio', 0, 1)
    if not f['mos_grid'] or f['mos_grid'] != sorted(set(f['mos_grid'])):
        raise InputError('MOS grid must be nonempty, unique and sorted')
    for v in f['mos_grid']:
        bounded(v, 'MOS grid', high=0.999999)
    if not f['allowed_price_sources'] or not all(isinstance(v,str) and v.strip() for v in f['allowed_price_sources']):
        raise InputError('At least one named price source required')
    lists = [b[k] for k in ('favored','avoided','mixed')]
    codes = sum(lists, [])
    if not lists[0] or any(not isinstance(x,str) or not x.isalpha() or x != x.upper() for x in codes) or len(codes) != len(set(codes)):
        raise InputError('Broker classifications must be disjoint uppercase codes; favored cannot be empty')
    for k in ('short_sessions','long_sessions','minimum_buyers'):
        bounded(b[k], k, 1, integer=True)
    bounded(b['minimum_buying_fraction'], 'minimum_buying_fraction', high=1)
    bounded(b['minimum_normalized_flow'], 'minimum_normalized_flow', high=1)
    if b['short_sessions'] > b['long_sessions'] or b['minimum_buyers'] > len(b['favored']):
        raise InputError('Invalid broker windows or minimum buyers')
    positive_ints = ('minimum_history','atr_period','support_lookback','minimum_support_tests','test_separation','pivot_left','pivot_right','rsi_period','stoch_period','stoch_k','stoch_d','stoch_recent_sessions','macd_fast','macd_slow','macd_signal','volume_sessions','retest_sessions','reclaim_sessions')
    for k in positive_ints:
        bounded(t[k], k, 1, integer=True)
    for k in ('support_tolerance_atr','volume_multiple','maximum_entry_distance_atr','full_credit_distance_atr'):
        bounded(t[k], k, 0.000001)
    bounded(t['stoch_oversold'], 'stoch_oversold', high=100)
    modes = {'support_reversal','breakout_retest','failed_breakdown_reclaim'}
    if not t['enabled_modes'] or not set(t['enabled_modes']) <= modes or len(set(t['enabled_modes'])) != len(t['enabled_modes']):
        raise InputError('Unsupported or duplicate technical mode')
    if t['macd_fast'] >= t['macd_slow'] or t['full_credit_distance_atr'] > t['maximum_entry_distance_atr']:
        raise InputError('Invalid MACD periods or proximity thresholds')
    required = max(t['support_lookback'] + t['pivot_right'] + 1, t['macd_slow'] + t['macd_signal'] + 2, t['rsi_period'] + t['stoch_period'] + t['stoch_k'] + t['stoch_d'] + t['stoch_recent_sessions'], t['volume_sessions']+1, t['atr_period']+1, b['long_sessions'], e['turnover_sessions'], t['retest_sessions']+2, t['reclaim_sessions']+2)
    if t['minimum_history'] < required:
        raise InputError(f'minimum_history must be >= {required} for configured windows')
    bounded(e['turnover_sessions'], 'turnover_sessions', 1, integer=True)
    for k in ('minimum_net_rr','minimum_turnover_idr'):
        bounded(e[k], k, 0.000001)
    for k in ('maximum_spread','full_credit_spread','maximum_participation','full_credit_participation','take_profit_fraction'):
        bounded(e[k], k, high=1)
    for k in ('buy_fee','sell_fee','entry_slippage','target_slippage','stop_slippage'):
        if e[k] is not None:
            bounded(e[k], k, high=0.99)
    if e['planned_order_idr'] is not None:
        bounded(e['planned_order_idr'], 'planned_order_idr', 0.000001)
    bounded(e['stop_buffer_atr'], 'stop_buffer_atr')
    for k in ('stop_buffer_ticks','entry_buffer_ticks','order_expiry_sessions'):
        bounded(e[k], k, 1, integer=True)
    if e['stop_basis'] not in ('intraday','close'):
        raise InputError('stop_basis must be intraday or close')
    if e['full_credit_spread'] > e['maximum_spread'] or e['full_credit_participation'] > e['maximum_participation']:
        raise InputError('Full-credit execution thresholds exceed gates')
    for k,v in s.items():
        for name,points in v.items():
            if isinstance(points,list):
                if not points:
                    raise InputError('Scoring lists must be nonempty')
                for p in points:
                    bounded(p, k+'.'+name)
            else:
                bounded(points, k+'.'+name)
        if k=='fundamental':
            for stem in ('mos','dispersion'):
                thresholds=v[stem+'_thresholds']; points=v[stem+'_points']
                if len(thresholds)!=len(points) or thresholds!=sorted(set(thresholds)) or any(x>1 for x in thresholds):
                    raise InputError('Invalid scoring bands')
    for k, maximum in score_maxima(c).items():
        if maximum <= 0:
            raise InputError(f'{k} scoring maximum must be positive')


def score_maxima(c):
    s=c['scoring']; f=s['fundamental']
    return {'fundamental':max(f['mos_points'])+max(f['dispersion_points'])+f['multiple_methods_points']+f['stress_points'], **{k:sum(s[k].values()) for k in ('broker','technical','execution')}}


def read_csv(path, required):
    with Path(path).open(newline='', encoding='utf-8-sig') as stream:
        reader=csv.DictReader(stream)
        if not reader.fieldnames or len(reader.fieldnames)!=len(set(reader.fieldnames)) or not set(required)<=set(reader.fieldnames):
            raise InputError(f'{path}: required headers {", ".join(required)}')
        rows=list(reader)
    if not rows:
        raise InputError(f'{path}: no records')
    if any(None in r for r in rows):
        raise InputError(f'{path}: extra columns; check CSV quoting')
    return rows


def load_prices(prices_path):
    return parse_prices(read_csv(prices_path, ['ticker','date','open','high','low','close','volume','traded_value_idr','source','corporate_actions_checked']))


def parse_prices(records):
    """Shared price normalization for CSV and in-memory source adapters."""
    prices=defaultdict(list)
    seen=set()
    for row in records:
        ticker=row['ticker'].strip().upper(); d=day(row['date'],'price date')
        if not ticker or (ticker,d) in seen:
            raise InputError('Empty ticker or duplicate price row')
        seen.add((ticker,d)); parsed={'date':d,'source':row['source'].strip()}
        for k in ('open','high','low','close','volume','traded_value_idr','bid','ask'):
            parsed[k]=number(row.get(k),f'{ticker} {d} {k}', k in ('bid','ask'))
        if any(parsed[k]<=0 for k in ('open','high','low','close')) or parsed['volume']<0 or parsed['traded_value_idr']<0 or not parsed['low']<=min(parsed['open'],parsed['close'])<=max(parsed['open'],parsed['close'])<=parsed['high']:
            raise InputError(f'{ticker} {d}: invalid OHLC/volume/turnover')
        if not parsed['source']:
            raise InputError('Price source required')
        parsed['actions_checked']=truth(row['corporate_actions_checked'],'corporate_actions_checked')
        parsed['turnover_basis']=row.get('traded_value_basis','actual_regular').strip()
        if parsed['turnover_basis'] not in ('actual_regular','close_times_volume_estimate'):
            raise InputError('Unknown traded_value_basis')
        parsed['tradable']=truth(row.get('tradable','true'),'tradable')
        prices[ticker].append(parsed)
    for rows in prices.values():
        rows.sort(key=lambda r:r['date'])
    return prices


def load_inputs(prices_path, valuations_path, brokers_path):
    prices=load_prices(prices_path); vals={}; brokers=defaultdict(dict)
    for row in read_csv(valuations_path, ['ticker','sector','valuation_date','price_date','valuation_price','price_source','valuation_source','validated','critical_flags','eva','ddm','rim','levels_date','support','stop_anchor','resistance1','resistance2','levels_source']):
        ticker=row['ticker'].strip().upper()
        if not ticker or ticker in vals:
            raise InputError('Empty ticker or duplicate valuation row')
        vals[ticker]=row
    for row in read_csv(brokers_path,['ticker','date','broker','net_value_idr','market','source']):
        ticker=row['ticker'].strip().upper(); d=day(row['date'],'broker date'); code=row['broker'].strip().upper()
        key=(d,code)
        if not ticker or not code or key in brokers[ticker]:
            raise InputError('Empty ticker/broker or duplicate broker row')
        if row['market']!='regular' or not row['source'].strip():
            raise InputError('Broker rows require regular market and a source')
        brokers[ticker][key]=number(row['net_value_idr'],'net_value_idr')
    return prices,vals,brokers


def ema(values, period):
    output=[]; value=None; seed=[]; alpha=2/(period+1)
    for current in values:
        if current is None:
            output.append(None); continue
        if value is None:
            seed.append(current)
            if len(seed)<period:
                output.append(None); continue
            value=mean(seed)
        else:
            value=alpha*current+(1-alpha)*value
        output.append(value)
    return output


def sma(values, period):
    result=[]
    for i in range(len(values)):
        part=values[max(0,i-period+1):i+1]
        result.append(mean(part) if len(part)==period and all(x is not None for x in part) else None)
    return result


def rsi(closes, period):
    out=[None]*len(closes)
    if len(closes)<=period:
        return out
    changes=[b-a for a,b in zip(closes,closes[1:])]
    gain=mean(max(x,0) for x in changes[:period]); loss=mean(max(-x,0) for x in changes[:period])
    for i in range(period,len(closes)):
        if i>period:
            change=changes[i-1]; gain=((period-1)*gain+max(change,0))/period; loss=((period-1)*loss+max(-change,0))/period
        out[i]=50 if gain==loss==0 else 100 if loss==0 else 100-100/(1+gain/loss)
    return out


def indicators(rows,c):
    t=c['technical']; closes=[r['close'] for r in rows]
    ranges=[max(r['high']-r['low'], abs(r['high']-rows[i-1]['close']),abs(r['low']-rows[i-1]['close'])) if i else r['high']-r['low'] for i,r in enumerate(rows)]
    n=t['atr_period']; atr=mean(ranges[:n])
    for v in ranges[n:]:
        atr=((n-1)*atr+v)/n
    rsis=rsi(closes,t['rsi_period']); raw=[]
    for i in range(len(rows)):
        part=rsis[max(0,i-t['stoch_period']+1):i+1]
        raw.append(None if len(part)<t['stoch_period'] or any(x is None for x in part) else 50 if max(part)==min(part) else 100*(part[-1]-min(part))/(max(part)-min(part)))
    k=sma(raw,t['stoch_k']); d=sma(k,t['stoch_d'])
    fast=ema(closes,t['macd_fast']); slow=ema(closes,t['macd_slow'])
    macd=[a-b if a is not None and b is not None else None for a,b in zip(fast,slow)]
    signal=ema(macd,t['macd_signal'])
    def cross(a,b):
        return all(x is not None for x in (a[-2],a[-1],b[-2],b[-1])) and a[-2]<=b[-2] and a[-1]>b[-1]
    recent=[x for x in k[-t['stoch_recent_sessions']-1:-1] if x is not None]
    base=median(r['volume'] for r in rows[-t['volume_sessions']-1:-1])
    return {'atr':atr,'stoch_k':k[-1],'stoch_d':d[-1],'stoch_cross':cross(k,d) and bool(recent) and min(recent)<=t['stoch_oversold'], 'macd':macd[-1],'macd_signal':signal[-1],'macd_cross':cross(macd,signal),'volume_multiple':rows[-1]['volume']/base if base>0 else 0}


def tick(price):
    # Regular IDX price fractions; inputs must be on the regular board.
    return 1 if price<200 else 2 if price<500 else 5 if price<2000 else 10 if price<5000 else 25


def rounded(price, up=False):
    if price<=0:
        return 0
    step=tick(price); result=(math.ceil(price/step-1e-10) if up else math.floor(price/step+1e-10))*step
    # Thresholds are multiples of the adjacent fractions, so boundary rounding is legal.
    return int(result)


def next_ticks(price,count=1):
    value=rounded(price)
    for _ in range(count):
        value+=tick(value)
    return value


def fundamental(row, latest,c,asof):
    if not row:
        raise InputError('No valuation/structural-level row')
    f=c['fundamental']; vd=day(row['valuation_date'],'valuation_date')
    if vd>asof or (asof-vd).days>f['valuation_max_age_days']:
        raise InputError('Future or stale valuation')
    if day(row['price_date'],'price_date')!=asof or number(row['valuation_price'],'valuation_price')!=latest['close']:
        raise InputError('Valuation price/date does not match as-of close')
    if row['price_source']!=latest['source'] or latest['source'] not in f['allowed_price_sources']:
        raise InputError('Price source mismatch or unapproved source')
    if not truth(row['validated'],'validated') or row['critical_flags'].strip():
        raise InputError('Unvalidated valuation or critical data flags')
    if not row['valuation_source'].strip() or not row['levels_source'].strip():
        raise InputError('Valuation and levels provenance required')
    values=[]
    for method in ('eva','ddm','rim'):
        value=number(row[method], method, True)
        if value is not None:
            if method=='eva' and row['sector'].strip().lower() in ('bank','financial','financials'):
                raise InputError('EVA not applicable to banks/financials')
            if value<=0:
                raise InputError('Nonpositive method value')
            values.append(value)
    if not values:
        raise InputError('No applicable valuation methods')
    fair=mean(values); dispersion=(max(values)-min(values))/fair; ratio=fair/latest['close']
    if dispersion>f['unreliable_maximum_dispersion'] or not f['minimum_value_price_ratio']<=ratio<=f['maximum_value_price_ratio']:
        raise InputError('UNRELIABLE: dispersion or value/price outlier')
    mos=1-latest['close']/fair
    verdict='UNDERVALUED_HIGH' if len(values)>=f['high_minimum_methods'] and mos>f['entry_mos'] and dispersion<f['high_maximum_dispersion'] else 'OVERVALUED' if latest['close']>fair*(1+f['fair_price_band']) else 'FAIR' if latest['close']>=fair*(1-f['fair_price_band']) else 'UNDERVALUED_MED'
    levels_date=day(row['levels_date'],'levels_date')
    if levels_date>=asof:
        raise InputError('Structural levels must be frozen before the signal date')
    support=number(row['support'],'support'); anchor=number(row['stop_anchor'],'stop_anchor'); r1=number(row['resistance1'],'resistance1'); r2=number(row['resistance2'],'resistance2',True)
    trigger=number(row.get('breakout_level'),'breakout_level',True)
    if not 0<anchor<=support<r1 or (r2 is not None and r2<=r1):
        raise InputError('Invalid support, stop anchor or resistance ordering')
    return {'fair_value':fair,'dispersion':dispersion,'method_count':len(values),'fundamental_verdict':verdict,'current_mos':mos,'support':support,'anchor':anchor,'r1':r1,'r2':r2,'trigger':trigger,'levels_date':levels_date,'stress_value':number(row.get('stressed_fair_value'),'stressed_fair_value',True)}


def broker_flow(rows,data,c):
    b=c['broker']; recent=rows[-b['long_sessions']:]; codes=b['favored']+b['avoided']+b['mixed']
    for r in recent:
        for code in codes:
            if (r['date'],code) not in data:
                raise InputError(f'Incomplete broker window: {r["date"]} {code} missing (explicit zero required)')
        observed=[value for (d,_),value in data.items() if d==r['date']]
        if r.get('turnover_basis','actual_regular')=='actual_regular' and (sum(max(v,0) for v in observed)>r['traded_value_idr']+1 or sum(max(-v,0) for v in observed)>r['traded_value_idr']+1):
            raise InputError('Broker net values exceed session turnover; check units/market scope')
    daily=[sum(data[(r['date'],code)] for code in b['favored']) for r in recent]
    denominator=sum(r['traded_value_idr'] for r in recent)
    if denominator<=0:
        raise InputError('No regular-market turnover for flow normalization')
    flow=sum(daily); short=sum(daily[-b['short_sessions']:]); fraction=sum(v>0 for v in daily)/len(daily)
    totals={code:sum(data[(r['date'],code)] for r in recent) for code in codes}
    return {'favored_net_long':flow,'favored_net_short':short,'normalized_flow':flow/denominator,'buying_fraction':fraction,'favored_buyers':sum(totals[x]>0 for x in b['favored']), 'avoided_net_long':sum(totals[x] for x in b['avoided']),'mixed_net_long':sum(totals[x] for x in b['mixed'])}


def setups(rows,v,i,c):
    t=c['technical']; latest=rows[-1]; prev=rows[-2]; atr=i['atr']; tolerance=t['support_tolerance_atr']*atr
    if atr<=0:
        return []
    modes=[]; support=v['support']
    volume=i['volume_multiple']>=t['volume_multiple']
    pivots=[]
    for index in range(max(t['pivot_left'],len(rows)-t['support_lookback']),len(rows)-t['pivot_right']):
        candidate=rows[index]['low']; neighborhood=rows[index-t['pivot_left']:index+t['pivot_right']+1]
        if candidate==min(r['low'] for r in neighborhood) and any(candidate<r['low'] for r in neighborhood) and abs(candidate-support)<=tolerance and (not pivots or index-pivots[-1]>=t['test_separation']):
            pivots.append(index)
    lows=[rows[index]['low'] for index in pivots]
    preserved=bool(lows) and latest['low']>=lows[-1] and all(b>=a for a,b in zip(lows,lows[1:]))
    near=abs(latest['low']-support)<=tolerance
    if 'support_reversal' in t['enabled_modes'] and len(pivots)>=t['minimum_support_tests'] and near and latest['close']>support and latest['close']>prev['close'] and (not t['require_no_lower_low'] or preserved) and (not t['require_stoch_cross'] or i['stoch_cross']) and (not t['require_macd_cross'] or i['macd_cross']) and (not t['require_reversal_volume'] or volume):
        modes.append({'setup':'support_reversal','level':support,'momentum':i['stoch_cross'] and i['macd_cross'],'order_type':'buy_stop_limit_above_signal_high'})
    trigger=v['trigger']
    if 'breakout_retest' in t['enabled_modes'] and trigger is not None and trigger>0:
        # Frozen analyst level, no post-event resistance fitting.
        for j in range(max(1,len(rows)-t['retest_sessions']-1),len(rows)):
            if rows[j]['date']<=v['levels_date']:
                continue
            if rows[j]['close']>trigger>=rows[j-1]['close'] and all(r['close']>=trigger for r in rows[j:]):
                if j==len(rows)-1 or abs(latest['low']-trigger)<=tolerance:
                    modes.append({'setup':'breakout_retest','level':trigger,'momentum':latest['close']>max(r['high'] for r in rows[-t['volume_sessions']-1:-1]),'order_type':'buy_stop_limit_above_signal_high'})
                    break
    if 'failed_breakdown_reclaim' in t['enabled_modes'] and latest['close']>support>=prev['close']:
        start=len(rows)-2
        while start>0 and rows[start-1]['close']<support:
            start-=1
        if len(rows)-1-start<=t['reclaim_sessions'] and rows[start]['date']>v['levels_date'] and min(r['low'] for r in rows[start:])>=v['anchor']:
            modes.append({'setup':'failed_breakdown_reclaim','level':support,'momentum':latest['close']>prev['high'],'order_type':'buy_stop_limit_above_signal_high'})
    return modes


def price_plan(latest,v,i,setup,c):
    e=c['execution']; f=c['fundamental']; atr=i['atr']
    entry=next_ticks(latest['high'],e['entry_buffer_ticks'])
    distance=max(0,entry-setup['level'])/atr
    if distance>c['technical']['maximum_entry_distance_atr']:
        raise InputError('Entry too far from structural level')
    if f['require_discount'] and entry>v['fair_value']*(1-f['entry_mos']):
        raise InputError('Entry exceeds configured MOS ceiling')
    buffer=max(e['stop_buffer_atr']*atr,e['stop_buffer_ticks']*tick(v['anchor']))
    stop=rounded(v['anchor']-buffer)
    cap=v['fair_value'] if e['cap_targets_at_value'] else math.inf
    tp1=rounded(min(v['r1'],cap)); tp2=rounded(min(v['r2'],cap)) if v['r2'] is not None else None
    if not 0<stop<entry<tp1:
        raise InputError('No valid entry/stop/nearest-target price interval')
    if tp2 is not None and tp2<=tp1:
        tp2=None
    gross=(tp1-entry)/(entry-stop)
    cost_keys=('buy_fee','sell_fee','entry_slippage','target_slippage','stop_slippage')
    known=all(e[k] is not None for k in cost_keys)
    net=None
    if known:
        paid=entry*(1+e['entry_slippage'])*(1+e['buy_fee'])
        target_received=tp1*(1-e['target_slippage'])*(1-e['sell_fee'])
        stop_received=stop*(1-e['stop_slippage'])*(1-e['sell_fee'])
        net=(target_received-paid)/(paid-stop_received)
        if net<e['minimum_net_rr']:
            raise InputError('Net reward/risk below threshold at nearest target')
    elif gross<e['minimum_net_rr']:
        raise InputError('Gross reward/risk already below net minimum')
    return {'entry_price':entry,'tp1_price':tp1,'tp2_price':tp2,'stop_loss_price':stop,'stop_basis':e['stop_basis'],'order_type':setup['order_type'],'gross_rr':gross,'net_rr':net,'entry_mos':1-entry/v['fair_value'],'entry_distance_atr':distance,'costs_known':known}


def points(row,c,percentile):
    s=c['scoring']; sf=s['fundamental']; t=c['technical']; e=c['execution']; b=c['broker']
    mos=max((p for boundary,p in zip(sf['mos_thresholds'],sf['mos_points']) if row['entry_mos']>=boundary),default=0)
    disp=next((p for boundary,p in zip(sf['dispersion_thresholds'],sf['dispersion_points']) if row['dispersion']<boundary or (boundary==sf['dispersion_thresholds'][-1] and row['dispersion']==boundary)),0)
    fundamental_points=mos+disp+(sf['multiple_methods_points'] if row['method_count']>=c['fundamental']['high_minimum_methods'] else 0)+(sf['stress_points'] if row['stress_value'] is not None and row['stress_value']>0 and 1-row['entry_price']/row['stress_value']>=c['fundamental']['stressed_mos_threshold'] else 0)
    sb=s['broker']; st=s['technical']; se=s['execution']
    raw={'fundamental':fundamental_points,'broker':sb['strength_points']*percentile+(sb['short_flow_points'] if row['favored_net_short']>0 else 0)+(sb['persistence_points'] if row['buying_fraction']>=b['minimum_buying_fraction'] else 0)+(sb['breadth_points'] if row['favored_buyers']>=b['minimum_buyers'] else 0), 'technical':st['setup_points']+(st['proximity_points'] if row['entry_distance_atr']<=t['full_credit_distance_atr'] else 0)+(st['volume_points'] if row['volume_multiple']>=t['volume_multiple'] else 0)+(st['momentum_points'] if row['momentum'] else 0), 'execution':(se['spread_points'] if row['spread'] is not None and row['spread']<=e['full_credit_spread'] else 0)+(se['participation_points'] if row['participation'] is not None and row['participation']<=e['full_credit_participation'] else 0)}
    maxima=score_maxima(c); scores={k:100*value/maxima[k] for k,value in raw.items()}
    return {**{k+'_score':value for k,value in scores.items()},'composite_score':sum(scores[k]*c['weights'][k]/100 for k in scores),'flow_percentile':percentile}


def screen(prices,vals,brokers,c,asof,include_provisional=False):
    validate_config(c)
    universe=sorted(set(prices)|set(vals)|set(brokers)); candidates=[]; issues=[]
    calendar=sorted({r['date'] for rows in prices.values() for r in rows if r['date']<=asof})
    if not calendar or calendar[-1]!=asof:
        raise InputError('No price rows for requested as-of trading date')
    normalized={'actual':[],'estimated':[]}
    # Percentile universe is all tickers with complete valid flow windows, before entry gates.
    for ticker in universe:
        rows=[r for r in prices.get(ticker,[]) if r['date']<=asof]
        try:
            n=c['broker']['long_sessions']
            if len(rows)>=n and [r['date'] for r in rows[-n:]]==calendar[-n:]:
                basis='estimated' if any(r.get('turnover_basis','actual_regular')!='actual_regular' for r in rows[-n:]) else 'actual'
                normalized[basis].append(broker_flow(rows,brokers.get(ticker,{}),c)['normalized_flow'])
        except InputError:
            pass
    for ticker in universe:
        try:
            rows=[r for r in prices.get(ticker,[]) if r['date']<=asof]
            if len(rows)<c['technical']['minimum_history']:
                raise InputError('Insufficient price history')
            latest=rows[-1]
            if latest['date']!=asof:
                raise InputError('Stale price history')
            if not latest['tradable']:
                raise InputError('Ticker not tradable')
            history=c['technical']['minimum_history']
            if [r['date'] for r in rows[-history:]]!=calendar[-history:]:
                raise InputError('Missing price sessions relative to supplied universe calendar')
            if not all(r['actions_checked'] for r in rows):
                raise InputError('Corporate actions not checked')
            v=fundamental(vals.get(ticker),latest,c,asof); flow=broker_flow(rows,brokers.get(ticker,{}),c); b=c['broker']; e=c['execution']
            if flow['favored_net_long']<=0 or flow['normalized_flow']<=b['minimum_normalized_flow']:
                raise InputError('Favored cohort not accumulating above flow threshold')
            if b['require_positive_short'] and flow['favored_net_short']<=0:
                raise InputError('Favored cohort distributing in short window')
            if flow['buying_fraction']<b['minimum_buying_fraction'] or flow['favored_buyers']<b['minimum_buyers']:
                raise InputError('Insufficient flow persistence or buyer breadth')
            turnover=median(r['traded_value_idr'] for r in rows[-e['turnover_sessions']:])
            if turnover<e['minimum_turnover_idr']:
                raise InputError('Insufficient liquidity')
            spread=None
            if latest['bid'] is not None and latest['ask'] is not None:
                if not 0<latest['bid']<=latest['ask']:
                    raise InputError('Invalid bid/ask')
                spread=(latest['ask']-latest['bid'])/((latest['ask']+latest['bid'])/2)
                if spread>e['maximum_spread']:
                    raise InputError('Spread exceeds limit')
            participation=e['planned_order_idr']/turnover if e['planned_order_idr'] is not None else None
            if participation is not None and participation>e['maximum_participation']:
                raise InputError('Order participation exceeds limit')
            i=indicators(rows,c); detected=setups(rows,v,i,c)
            if not detected:
                raise InputError('No confirmed technical setup')
            valid=[]; reasons=[]
            for setup in detected:
                try:
                    plan=price_plan(latest,v,i,setup,c)
                    warnings=[]
                    estimated_turnover=any(r.get('turnover_basis','actual_regular')!='actual_regular' for r in rows[-max(e['turnover_sessions'],b['long_sessions']):])
                    if estimated_turnover: warnings.append('turnover estimated: flow strength/liquidity/capacity not regular-market verified')
                    if not plan['costs_known']: warnings.append('fees/slippage unset; net RR unavailable')
                    if spread is None: warnings.append('bid/ask missing')
                    if participation is None: warnings.append('planned order size unset')
                    if e['stop_basis']=='close': warnings.append('close-based stop exits next session; gap risk unbounded')
                    status='PROVISIONAL' if estimated_turnover or not plan['costs_known'] or spread is None or participation is None else 'ELIGIBLE'
                    row={'ticker':ticker,'as_of':asof.isoformat(),'status':status,'setup':setup['setup'],**v,**flow,**i,**plan,'momentum':setup['momentum'],'median_turnover_idr':turnover,'spread':spread,'participation':participation,'warnings':'; '.join(warnings),'price_source':latest['source'],'valuation_source':vals[ticker]['valuation_source'],'levels_source':vals[ticker]['levels_source'],'order_expiry_sessions':e['order_expiry_sessions'],'take_profit_fraction':e['take_profit_fraction']}
                    flow_basis='estimated' if any(r.get('turnover_basis','actual_regular')!='actual_regular' for r in rows[-b['long_sessions']:]) else 'actual'
                    peer_flows=normalized[flow_basis]
                    percentile=sum(x<=flow['normalized_flow'] for x in peer_flows)/len(peer_flows) if peer_flows else 0
                    row.update(points(row,c,percentile))
                    row['mos_grid']=json.dumps({str(m):rounded(v['fair_value']*(1-m)) for m in c['fundamental']['mos_grid']},sort_keys=True)
                    valid.append(row)
                except InputError as exc:
                    reasons.append(f'{setup["setup"]}: {exc}')
            if not valid:
                raise InputError('; '.join(reasons))
            row=max(valid,key=lambda r:(r['composite_score'],r['net_rr'] if r['net_rr'] is not None else r['gross_rr'],r['setup']))
            if row['composite_score']<c['ranking']['minimum_score']:
                raise InputError('Composite score below minimum')
            if row['status']=='PROVISIONAL' and not include_provisional:
                issues.append({'ticker':ticker,'state':'PROVISIONAL','reason':row['warnings']})
            else:
                candidates.append(row)
        except InputError as exc:
            issues.append({'ticker':ticker,'state':'EXCLUDED','reason':str(exc)})
    # Verified candidates always precede provisional ones; missing costs never win a net-RR tie.
    candidates.sort(key=lambda r:(r['status']!='ELIGIBLE',-r['composite_score'],-(r['net_rr'] if r['net_rr'] is not None else r['gross_rr']),-r['median_turnover_idr'],r['ticker']))
    winners=candidates[:c['ranking']['max_results']]
    for rank,row in enumerate(winners,1): row['rank']=rank
    for row in candidates[c['ranking']['max_results']:]:
        issues.append({'ticker':row['ticker'],'state':'QUALIFIED_NOT_SELECTED','reason':'Below configured result limit'})
    return winners,issues,{'universe_count':len(universe),'qualifying_count':len(candidates),'selected_count':len(winners),'verified_count':sum(r['status']=='ELIGIBLE' for r in winners),'provisional_count':sum(r['status']=='PROVISIONAL' for r in winners)}


OUTPUT_FIELDS=['rank','ticker','as_of','status','setup','composite_score','fundamental_score','broker_score','technical_score','execution_score','entry_price','tp1_price','tp2_price','stop_loss_price','stop_basis','order_type','order_expiry_sessions','take_profit_fraction','gross_rr','net_rr','fair_value','fundamental_verdict','entry_mos','current_mos','dispersion','method_count','mos_grid','favored_net_long','favored_net_short','normalized_flow','flow_percentile','buying_fraction','favored_buyers','avoided_net_long','mixed_net_long','support','anchor','r1','r2','atr','stoch_k','stoch_d','macd','macd_signal','volume_multiple','entry_distance_atr','median_turnover_idr','spread','participation','price_source','valuation_source','levels_source','warnings']


def write_csv(path,rows,fields):
    with Path(path).open('w',newline='',encoding='utf-8') as stream:
        writer=csv.DictWriter(stream,fieldnames=fields,extrasaction='ignore'); writer.writeheader()
        for row in rows:
            writer.writerow({k:round(v,8) if isinstance(v,float) else v for k,v in row.items() if k in fields})


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()
