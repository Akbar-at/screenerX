"""Attach dated IDX evidence to every screened company without inventing score weights."""
from .idx_source import get_idx_source


def enrich_report(report,source=None):
    source=source or get_idx_source()
    counts={'available':0,'net_buy':0,'net_sell':0,'flat':0,'unavailable':0}
    datasets={};errors={};leaders=[]
    for company in report['companies']:
        data=source.stock_metrics(company['ticker'],report['as_of'],reference=True)
        company['_idx_data']=data
        datasets.update({k:{**v,'status':'AVAILABLE' if v['status']=='TICKER_NOT_FOUND' else v['status']} for k,v in data['datasets'].items()});errors.update(data['errors'])
        row=data.get('stocks');net=data.get('net_foreign_volume')
        if row and net is not None:
            status='NET_BUY' if net>0 else 'NET_SELL' if net<0 else 'FLAT'
            fraction=net/row['Volume'] if row['Volume']>0 else None
            counts['available']+=1
            counts[{'NET_BUY':'net_buy','NET_SELL':'net_sell','FLAT':'flat'}[status]]+=1
            leaders.append({'ticker':company['ticker'],'net_foreign_volume':net,'net_share_of_volume':fraction,
                            'core_selected':company['ranking_status']=='SELECTED'})
        else:
            status='UNAVAILABLE';fraction=None;counts['unavailable']+=1
        company['idx_screening']={'as_of':report['as_of'],'foreign_activity':status,
            'net_foreign_volume':net,'net_share_of_volume':fraction,'unit':'shares',
            'score_contribution':0,'broker_net_status':'ON_HOLD'}
    # Some callers deserialize top10 independently from companies.
    by_ticker={c['ticker']:c for c in report['companies']}
    for selected in report['top10']:
        full=by_ticker[selected['ticker']]
        selected['_idx_data']=full['_idx_data'];selected['idx_screening']=full['idx_screening']
    report['idx_screening']={'as_of':report['as_of'],'counts':counts,'datasets':datasets,'errors':errors,
        'policy':'IDX foreign activity is separate dated screening evidence; core score weights unchanged. Broker net remains ON_HOLD.',
        'net_buy_leaders':sorted((r for r in leaders if r['net_foreign_volume']>0),key=lambda r:(-r['net_foreign_volume'],r['ticker']))[:10],
        'net_sell_leaders':sorted((r for r in leaders if r['net_foreign_volume']<0),key=lambda r:(r['net_foreign_volume'],r['ticker']))[:10]}
    return report['idx_screening']
