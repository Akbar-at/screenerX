import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from screenerx.yahoo_market import collect


class YahooMarketTests(unittest.TestCase):
    def test_rate_limit_stops_pending_network_requests(self):
        blocked=threading.Event()
        with tempfile.TemporaryDirectory() as folder:
            with patch('screenerx.yahoo_market.fetch_snapshot',side_effect=ValueError('Too Many Requests. Rate limited.')) as fetch:
                first=collect('BBCA',Path(folder),blocked)
                second=collect('BMRI',Path(folder),blocked)
            self.assertTrue(blocked.is_set())
            self.assertEqual(fetch.call_count,1)
            self.assertIn('Deferred',second['reason'])
            self.assertEqual(first['status'],'UNAVAILABLE')
    def test_saved_wrong_company_is_rejected_without_network(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)
            (path/'BBCA.json').write_text(json.dumps({'provider':'yfinance','ticker':'BMRI','symbol':'BMRI.JK'}))
            with patch('screenerx.yahoo_market.fetch_snapshot') as fetch:
                result=collect('BBCA',path)
                fetch.assert_not_called()
            self.assertEqual(result['status'],'UNAVAILABLE')

    def test_fetch_failure_remains_ticker_specific(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch('screenerx.yahoo_market.fetch_snapshot',side_effect=ValueError('network unavailable')):
                result=collect('BBCA',Path(folder))
            self.assertEqual(result['status'],'UNAVAILABLE')
            self.assertEqual(result['reason'],'network unavailable')
