import csv
import json
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from screenerx.engine import InputError, write_csv
from screenerx.fetch import FIELDS, JAKARTA
from screenerx.production import latest_session, run
from test_fetch import fixture as chart_fixture
from test_valuation import fixture as financial_fixture


class ProductionTests(unittest.TestCase):
    def test_observed_session_skips_holiday_and_intraday_candle(self):
        # A reference chart's latest returned date may be today's incomplete session.
        payload=chart_fixture()
        with patch('screenerx.production.fetch_yfinance',return_value=(payload,b'raw')):
            asof,discovery=latest_session(datetime(2026,7,16,12,tzinfo=JAKARTA))
        self.assertEqual(asof,date(2026,7,15))
        self.assertEqual(discovery['cutoff_date'],'2026-07-15')
        # Friday is missing (an exchange holiday); observed Thursday is chosen.
        with patch('screenerx.production.fetch_yfinance',return_value=(payload,b'raw')):
            asof,_=latest_session(datetime(2026,7,20,10,tzinfo=JAKARTA))
        self.assertEqual(asof,date(2026,7,16))

    def test_stale_reference_session_is_not_accepted(self):
        with patch('screenerx.production.fetch_yfinance',return_value=(chart_fixture(),b'raw')):
            with self.assertRaises(InputError): latest_session(datetime(2026,10,12,10,tzinfo=JAKARTA))

    def fake_prices(self,argv):
        output=Path(argv[argv.index('--output')+1]); output.mkdir()
        dates=[]; current=date(2026,10,9)
        while len(dates)<130:
            if current.weekday()<5: dates.append(current)
            current-=timedelta(days=1)
        rows=[]
        for index,d in enumerate(reversed(dates)):
            close=1000+index*5
            rows.append({'ticker':'BBCA','date':d.isoformat(),'open':close-1,'high':close+5,'low':close-5,
                         'close':close,'volume':10000000,'traded_value_idr':close*10000000,
                         'traded_value_basis':'close_times_volume_estimate','bid':'','ask':'',
                         'source':'Yahoo Finance','corporate_actions_checked':'false','tradable':'true'})
        write_csv(output/'prices.csv',rows,FIELDS)
        (output/'api-run.json').write_text(json.dumps({'provider':'yfinance','errors':self.price_errors}))
        return 2 if self.price_errors else 0

    def test_pipeline_exports_hashes_tax_and_full_requested_coverage(self):
        root_config=Path(__file__).resolve().parent.parent
        for partial in (False,True):
            with self.subTest(partial=partial), tempfile.TemporaryDirectory() as folder:
                output=Path(folder)/'production'
                self.price_errors=[{'ticker':'BMRI','reason':'unavailable'}] if partial else []
                tickers=['BBCA','BMRI'] if partial else ['BBCA']
                snapshot=financial_fixture(); snapshot['statements']['income']['2025-12-31'].update(
                    {'Tax Provision':100,'Pretax Income':1000})
                with (patch('screenerx.production.fetch_main',side_effect=self.fake_prices),
                      patch('screenerx.valuation.fetch_snapshot',return_value=snapshot),
                      patch('screenerx.production.version',return_value='test-version')):
                    report=run(output,tickers,root_config/'config.json',root_config/'valuation-config.json',date(2026,10,9),financial_provider='yfinance')
                self.assertEqual(report['status'],'PARTIAL' if partial else 'COMPLETE')
                self.assertEqual(report['data_mode'],'REAL_MARKET_DATA')
                self.assertEqual(report['broker_flow_status'],'ON_HOLD')
                self.assertIn('report.md',report['artifacts'])
                self.assertIn('valuations/run.json',report['evidence'])
                with (output/'data-quality.csv').open() as stream: quality=list(csv.DictReader(stream))
                self.assertEqual(len(quality),len(tickers))
                self.assertTrue(quality[0]['tax_rate_source'].startswith('reported_effective'))
                if partial: self.assertEqual(quality[1]['price_status'],'UNAVAILABLE')
                self.assertTrue((output/'report.md').exists())
                with self.assertRaises(InputError): run(output,tickers,root_config/'config.json',root_config/'valuation-config.json',date(2026,10,9))

    def test_pipeline_failure_retains_failed_manifest(self):
        root_config=Path(__file__).resolve().parent.parent
        with tempfile.TemporaryDirectory() as folder:
            output=Path(folder)/'failure'
            with (patch('screenerx.production.latest_session',side_effect=InputError('source unavailable')),
                  patch('screenerx.production.version',return_value='test-version')):
                with self.assertRaises(InputError): run(output,['BBCA'],root_config/'config.json',root_config/'valuation-config.json')
            report=json.loads((output/'run.json').read_text())
            self.assertEqual(report['status'],'FAILED')
            self.assertTrue(report['errors'])


if __name__=='__main__': unittest.main()
