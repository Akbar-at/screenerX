import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from screenerx.engine import InputError
from screenerx.market import collect_one, validate_universe


class MarketTests(unittest.TestCase):
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
