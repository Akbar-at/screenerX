"""Create empty input templates without overwriting existing files."""
import csv
import sys
from pathlib import Path

HEADERS={
    'prices.csv':'ticker,date,open,high,low,close,volume,traded_value_idr,bid,ask,source,corporate_actions_checked,tradable',
    'valuations.csv':'ticker,sector,valuation_date,price_date,valuation_price,price_source,valuation_source,validated,critical_flags,eva,ddm,rim,stressed_fair_value,levels_date,support,stop_anchor,breakout_level,resistance1,resistance2,levels_source',
    'brokers.csv':'ticker,date,broker,net_value_idr,market,source'
}
if __name__=='__main__':
    folder=Path(sys.argv[1] if len(sys.argv)>1 else 'data/templates'); folder.mkdir(parents=True,exist_ok=True)
    for name,header in HEADERS.items():
        with (folder/name).open('x',newline='') as stream:
            csv.writer(stream).writerow(header.split(','))
    print(f'Templates: {folder}')
