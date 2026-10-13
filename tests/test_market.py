import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from screenerx.engine import InputError
from screenerx.market import collect_one, validate_universe,merge_history


class MarketTests(unittest.TestCase):
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
