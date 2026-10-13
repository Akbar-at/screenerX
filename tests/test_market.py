import json
import tempfile
import unittest
from datetime import date,timedelta
from pathlib import Path
from unittest.mock import patch

from screenerx.engine import InputError
from screenerx.market import collect_one, validate_universe,merge_history,run


class MarketTests(unittest.TestCase):
    def test_market_pipeline_repairs_missing_yesterday_before_actual_core_screen(self):
        from screenerx.engine import write_csv
        from screenerx.fetch import FIELDS
        asof=date(2026,10,13)
        dates=[];current=asof
        while len(dates)<130:
            if current.weekday()<5: dates.append(current)
            current-=timedelta(days=1)
        rows=[{'ticker':'BBCA','date':d.isoformat(),'open':100,'high':110,'low':90,
               'close':105,'volume':100000000,'source':'Yahoo Finance',
               'corporate_actions_checked':'false','tradable':'true',
               'traded_value_basis':'close_times_volume_estimate','traded_value_idr':10500000000}
              for d in sorted(dates)]
        fresh=[r for r in rows if r['date']!='2026-10-12']
        payload={'err_code':'EC0000000','result':{'codes':['BBCA','BMRI'],'count':2}}
        def collected(ticker,*args):
            data=fresh if ticker=='BBCA' else rows
            return [dict(r,ticker=ticker) for r in data],{'ticker':ticker,'status':'AVAILABLE','current_session':True}
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);previous=root/'previous.csv'
            write_csv(previous,[r for r in rows if r['date']<asof.isoformat()],FIELDS)
            with patch('screenerx.market.fetch_json',return_value=(payload,json.dumps(payload).encode())), \
                 patch('screenerx.market.probe_sources'),patch('screenerx.market.collect_one',side_effect=collected), \
                 patch('screenerx.core_service.completed_cutoff',return_value=asof):
                broken=run(root/'broken',asof=asof,financial_provider='yfinance')
                recovered=run(root/'recovered',asof=asof,financial_provider='yfinance',previous_prices=previous,retry_failed=True)
            def company(result):
                report=json.loads((Path(result['report_path']).parent/'core-run.json').read_text())
                return next(c for c in report['companies'] if c['ticker']=='BBCA')
            self.assertEqual(company(broken)['coverage']['session_alignment']['status'],'FAIL')
            self.assertEqual(company(recovered)['coverage']['session_alignment']['status'],'PASS')
            self.assertEqual(company(recovered)['close'],105)
            self.assertEqual(recovered['retained_history']['rows'],1)
            self.assertEqual(recovered['current_price_count'],2)

    def test_normalized_history_roundtrips_without_losing_source_quality_flags(self):
        from screenerx.engine import parse_prices,load_prices,write_csv
        from screenerx.fetch import FIELDS
        raw={'ticker':'BBCA','date':'2026-10-12','open':100,'high':110,'low':90,'close':105,'volume':1000,
             'traded_value_idr':105000,'traded_value_basis':'close_times_volume_estimate',
             'source':'Yahoo','corporate_actions_checked':'false','tradable':'true'}
        rows,_=merge_history([],parse_prices([raw]),date(2026,10,13))
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'prices.csv';write_csv(path,rows,FIELDS);loaded=load_prices(path)['BBCA'][0]
        self.assertFalse(loaded['actions_checked'])
        self.assertEqual(loaded['turnover_basis'],'close_times_volume_estimate')
        self.assertEqual(loaded['close'],105)
    def test_history_merge_retains_gaps_prefers_new_and_never_fills_current_session(self):
        previous={'BBCA':[{'date':date(2026,10,9),'close':1},{'date':date(2026,10,12),'close':2}],
                  'MISSING':[{'date':date(2026,10,12),'close':3},{'date':date(2026,10,13),'close':99}]}
        fresh=[{'ticker':'BBCA','date':'2026-10-09','close':4},{'ticker':'BBCA','date':'2026-10-13','close':5}]
        rows,count=merge_history(fresh,previous,date(2026,10,13))
        prices={(r['ticker'],str(r['date'])):r['close'] for r in rows}
        self.assertEqual(prices[('BBCA','2026-10-09')],4)
        self.assertEqual(prices[('BBCA','2026-10-12')],2)
        self.assertEqual(prices[('BBCA','2026-10-13')],5)
        self.assertNotIn(('MISSING','2026-10-13'),prices);self.assertEqual(count,2)
    def test_universe_count_and_duplicates_are_rejected(self):
        def payload(codes, count):
            return {'err_code': 'EC0000000', 'result': {'codes': codes, 'count': count}}
        self.assertEqual(validate_universe(payload(['TLKM', 'BBCA'], 2)), ['BBCA', 'TLKM'])
        for item in (payload(['BBCA', 'BBCA.JK'], 2), payload(['BBCA'], 2), payload([], 0)):
            with self.assertRaises(InputError):
                validate_universe(item)

    def test_saved_raw_replays_without_network_and_reports_parse_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / 'BBCA.json').write_text(json.dumps({'chart': {}}))
            with patch('screenerx.market.fetch_yfinance') as fetch:
                rows, audit = collect_one('BBCA', date(2026, 10, 9), folder)
                fetch.assert_not_called()
            self.assertEqual(rows, [])
            self.assertEqual(audit['status'], 'UNAVAILABLE')
            self.assertTrue(audit['reason'])

    def test_network_failure_is_an_explicit_ticker_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch('screenerx.market.fetch_yfinance', side_effect=InputError('Unavailable')):
                rows, audit = collect_one('XYZ', date(2026, 10, 9), Path(directory))
            self.assertEqual(rows, [])
            self.assertEqual(audit, {'ticker': 'XYZ', 'status': 'UNAVAILABLE', 'reason': 'Unavailable'})

    def test_retry_replaces_bad_cached_response_and_records_current_session(self):
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory); path=folder/'BBCA.json'
            path.write_text('{"chart":{}}')
            with patch('screenerx.market.fetch_yfinance',return_value=({'recovered':True},b'{"recovered":true}')) as fetch, \
                 patch('screenerx.market.parse_chart',return_value=([{'date':'2026-10-13'}],{})):
                rows,audit=collect_one('BBCA',date(2026,10,13),folder,refresh=True)
            fetch.assert_called_once();self.assertTrue(audit['current_session'])
            self.assertEqual(json.loads(path.read_text()),{'recovered':True})

    def test_saved_history_without_today_is_not_counted_as_current(self):
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory);(folder/'BBCA.json').write_text('{}')
            with patch('screenerx.market.parse_chart',return_value=([{'date':'2026-10-12'}],{})):
                _,audit=collect_one('BBCA',date(2026,10,13),folder)
            self.assertEqual(audit['status'],'AVAILABLE');self.assertFalse(audit['current_session'])
