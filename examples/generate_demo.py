"""Generate a reproducible synthetic dataset. These are NOT real stock recommendations."""
import csv
import json
import math
import sys
from datetime import date, timedelta
from pathlib import Path


def generate(folder):
    folder=Path(folder); folder.mkdir(parents=True,exist_ok=True)
    config=json.loads((Path(__file__).parent.parent/'config.json').read_text())
    dates=[]; current=date(2026,1,1)
    while len(dates)<140:
        if current.weekday()<5: dates.append(current)
        current+=timedelta(days=1)
    prices=[]; valuations=[]; brokers=[]
    codes=config['broker']['favored']+config['broker']['avoided']+config['broker']['mixed']
    for index in range(14):
        ticker=f'DEMO{index+1:02}'; offset=index*10
        for j,d in enumerate(dates):
            close=980+offset+10*math.sin(j/4)
            if j==138: close=995+offset
            if j==139: close=1001+offset
            prices.append({'ticker':ticker,'date':d.isoformat(),'open':close-2,'high':close+(1 if j==139 else 3),'low':close-5,'close':round(close,4),'volume':30000000 if j==139 else 15000000,'traded_value_idr':20000000000,'bid':1000+offset if j==139 else '', 'ask':1005+offset if j==139 else '', 'source':'SYNTHETIC','corporate_actions_checked':'true','tradable':'true'})
            if j>=len(dates)-config['broker']['long_sessions']:
                for code in codes:
                    net=(50000000+index*2000000) if code in config['broker']['favored'] else -60000000
                    if index==12 and code in config['broker']['favored']: net=-net
                    brokers.append({'ticker':ticker,'date':d.isoformat(),'broker':code,'net_value_idr':net,'market':'regular','source':'SYNTHETIC'})
        valuations.append({'ticker':ticker,'sector':'non-bank','valuation_date':dates[-2].isoformat(),'price_date':dates[-1].isoformat(),'valuation_price':1001+offset,'price_source':'SYNTHETIC','valuation_source':'synthetic reviewed model fixture','validated':'true','critical_flags':'intentional demo critical flag' if index==13 else '', 'eva':1450+offset+index*2,'ddm':1500+offset,'rim':1550+offset,'stressed_fair_value':1400+offset,'levels_date':dates[-5].isoformat(),'support':950+offset,'stop_anchor':940+offset,'breakout_level':1000+offset,'resistance1':1250+offset,'resistance2':1400+offset,'levels_source':'synthetic pre-signal levels'})
    def write(name,rows):
        with (folder/name).open('w',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
    write('prices.csv',prices); write('valuations.csv',valuations); write('brokers.csv',brokers)
    config['profile_name']='SYNTHETIC_DEMO_ONLY'; config['fundamental']['allowed_price_sources']=['SYNTHETIC']
    (folder/'config.json').write_text(json.dumps(config,indent=2)+'\n')
    print(f'Synthetic data only. Decision date: {dates[-1].isoformat()}')
    return dates[-1]


if __name__=='__main__':
    generate(sys.argv[1] if len(sys.argv)>1 else Path(__file__).parent/'demo')
