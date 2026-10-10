import csv
import io
import json
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

from examples.generate_demo import generate
from screenerx.engine import InputError, load_config, load_inputs, screen
from screenerx.fetch import JAKARTA, chart_url, fetch_json, main, parse_chart, symbol_for


def fixture():
    dates=['2026-07-14','2026-07-15','2026-07-16']
    return {'chart':{'error':None,'result':[{'meta':{'symbol':'BBCA.JK','currency':'IDR','exchangeTimezoneName':'Asia/Jakarta'},'timestamp':[int(datetime.fromisoformat(d+'T09:00:00').replace(tzinfo=JAKARTA).timestamp()) for d in dates],'indicators':{'quote':[{'open':[100,101,102],'high':[103,104,105],'low':[99,100,101],'close':[102,103,104],'volume':[1000,2000,3000]}]},'events':{'splits':{}}}]}}


class FetchTests(unittest.TestCase):
    def test_ticker_mapping_and_url(self):
        self.assertEqual(symbol_for('bbca.jk'),('BBCA','BBCA.JK'))
        self.assertIn('/BBCA.JK?',chart_url('BBCA',date(2026,7,15),400))
        with self.assertRaises(InputError): symbol_for('../bad')

    def test_dates_and_quality_are_explicit(self):
        rows,quality=parse_chart(fixture(),'BBCA',date(2026,7,15))
        self.assertEqual(len(rows),2)
        self.assertEqual(rows[-1]['traded_value_idr'],206000)
        self.assertEqual(rows[-1]['traded_value_basis'],'close_times_volume_estimate')
        self.assertEqual(rows[-1]['corporate_actions_checked'],'false')
        self.assertEqual(rows[-1]['bid'],'')
        self.assertFalse(quality['quotes_available'])

    def test_null_candle_never_becomes_zero(self):
        p=fixture(); p['chart']['result'][0]['indicators']['quote'][0]['close'][0]=None
        rows,q=parse_chart(p,'BBCA',date(2026,7,15),True)
        self.assertEqual(len(rows),1)
        self.assertEqual(q['missing_candle_dates'],['2026-07-14'])
        self.assertEqual(rows[0]['corporate_actions_checked'],'true')

    def test_wrong_currency_lengths_and_stale_candle_rejected(self):
        p=fixture(); p['chart']['result'][0]['meta']['currency']='USD'
        with self.assertRaises(InputError): parse_chart(p,'BBCA',date(2026,7,15))
        p=fixture(); p['chart']['result'][0]['indicators']['quote'][0]['close']=[]
        with self.assertRaises(InputError): parse_chart(p,'BBCA',date(2026,7,15))
        with self.assertRaises(InputError): parse_chart(fixture(),'BBCA',date(2026,7,17))

    def test_403_is_not_retried(self):
        calls=[]
        def opener(request,timeout):
            calls.append(request.full_url)
            raise HTTPError(request.full_url,403,'Forbidden',None,io.BytesIO())
        with self.assertRaises(InputError): fetch_json('https://query1.finance.yahoo.com/test',opener=opener,sleeper=lambda _:None)
        self.assertEqual(len(calls),1)

    def test_rate_limit_retries_are_bounded(self):
        calls=[]
        def opener(request,timeout):
            calls.append(1)
            raise HTTPError(request.full_url,429,'Too many',None,io.BytesIO())
        with self.assertRaises(InputError): fetch_json('https://query1.finance.yahoo.com/test',retries=2,opener=opener,sleeper=lambda _:None)
        self.assertEqual(len(calls),3)

    def test_download_creates_prices_profile_and_audit(self):
        with tempfile.TemporaryDirectory() as folder:
            output=Path(folder)/'api'
            with patch('screenerx.fetch.fetch_json',return_value=(fixture(),json.dumps(fixture()).encode())):
                rc=main(['--tickers','BBCA','--as-of','2026-07-15','--output',str(output)])
            self.assertEqual(rc,0)
            with (output/'prices.csv').open() as f: rows=list(csv.DictReader(f))
            self.assertEqual(rows[0]['source'],'Yahoo Finance')
            report=json.loads((output/'api-run.json').read_text())
            self.assertFalse(report['broker_flow_available'])
            self.assertFalse(report['fundamentals_available'])
            self.assertIn('Yahoo Finance',load_config(output/'screen-config.json')['fundamental']['allowed_price_sources'])
            self.assertTrue((output/'raw'/'BBCA.json').exists())

    def test_network_failure_is_nonzero_and_audited(self):
        with tempfile.TemporaryDirectory() as folder:
            output=Path(folder)/'api'
            with patch('screenerx.fetch.fetch_json',side_effect=InputError('network denied')):
                rc=main(['--tickers','BBCA','--as-of','2026-07-15','--output',str(output)])
            self.assertEqual(rc,2)
            report=json.loads((output/'api-run.json').read_text())
            self.assertEqual(report['sources'],[])
            self.assertEqual(report['errors'][0]['ticker'],'BBCA')
            with (output/'prices.csv').open() as f: self.assertEqual(list(csv.DictReader(f)),[])

    def test_turnover_estimate_never_claims_verified_screen(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); asof=generate(root)
            data=load_inputs(root/'prices.csv',root/'valuations.csv',root/'brokers.csv')
            for rows in data[0].values():
                for r in rows: r['turnover_basis']='close_times_volume_estimate'
            c=load_config(root/'config.json')
            winners,issues,_=screen(*data,c,asof)
            self.assertEqual(winners,[])
            self.assertTrue(any('turnover estimated' in r['reason'] for r in issues))
            winners,_,_=screen(*data,c,asof,True)
            self.assertEqual(len(winners),10)
            self.assertTrue(all(r['status']=='PROVISIONAL' for r in winners))


if __name__=='__main__': unittest.main()
