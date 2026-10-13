"""Independent analysis of stored inputs; missing modules never veto other modules."""
import copy
import re

MODES=('technical','fundamental','broker')
ALIASES={'tech':'technical','teknikal':'technical','fund':'fundamental','valuation':'fundamental','flow':'broker'}


def parse_modes(value):
    if value.lower() in ('all','full'): return MODES
    values=[ALIASES.get(x,x) for x in re.split(r'[+,]',value.lower())]
    if not values or any(x not in MODES for x in values):
        raise ValueError('Mode: technical, fundamental, broker; gabungkan dengan + atau gunakan all.')
    return tuple(x for x in MODES if x in values)


def select_analysis(company,modes):
    modes=parse_modes('+'.join(modes))
    result=copy.deepcopy(company)
    result['_analysis_modes']=modes
    components={}
    if 'technical' in modes:
        t=company.get('technical') or {}; close=company.get('close')
        ready=close is not None and all(t.get(k) is not None for k in ('sma20','sma60','macd','macd_signal','rsi'))
        trend=ready and close>t['sma20']>t['sma60'] and t['macd']>t['macd_signal']
        components['technical']={'status':'AVAILABLE' if ready else 'UNAVAILABLE',
            'assessment':('Tren dan momentum menguat.' if trend else 'Tren/momentum belum terkonfirmasi.') if ready else 'Indikator harga belum lengkap.'}
    if 'fundamental' in modes:
        v=company.get('valuation') or {}; required=company.get('required_models') or []
        available=[m for m in ('ddm','rim','eva') if v.get(m) is not None]
        complete=bool(available) and all(v.get(m) is not None for m in required)
        components['fundamental']={'status':'UNREVIEWED_ESTIMATES' if complete else 'PARTIAL_ESTIMATES' if available else 'UNAVAILABLE',
            'assessment':'Estimasi valuasi belum direview.' if complete else 'Model yang tersedia tetap ditampilkan; cakupan fundamental belum lengkap.'}
    if 'broker' in modes:
        components['broker']={'status':'ON_HOLD','assessment':'Data transaksi broker belum terintegrasi; akumulasi/distribusi belum dapat dikonfirmasi.'}
    result['_analysis_components']=components
    return result
