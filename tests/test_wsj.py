import copy
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

from screenerx.engine import InputError, write_csv
from screenerx.valuation import estimate, generate, load_assumptions
from screenerx.wsj import cell, fetch_page, fetch_snapshot, page_url, validate_page


def page(ticker,route,rows,bank=False):
    return {'format':'wsj-table-excerpt-v1','ticker':ticker,'statement':route,'url':page_url(ticker,route),
            'title':f'Company {ticker} (Indonesia: Jakarta)','financial_currency':'IDR','scale':'Millions',
            'fiscal_year':'January-December','years':['2025','2024'],
            'rows':[{'label':k,'values':v} for k,v in rows.items()],'bank_statement':bank,
            'retrieval_method':'saved_page','retrieved_at':'2026-10-12T00:00:00Z'}


def pages(ticker='ASII'):
    return [page(ticker,'income-statement',{'Net Income Available to Common':['1,200','1,100'],
                 'EBIT':['1,500','1,400'],'Income Tax':['300','250'],'Pretax Income':['1,500','1,400'],
                 'Diluted Shares Outstanding':['100','100']}),
            page(ticker,'balance-sheet',{'Common Equity (Total)':['10,000','9,000'],'Cash Only':['1,000','900'],
                 'ST Debt & Current Portion LT Debt':['500','400'],'Long-Term Debt':['1,500','1,400'],
                 'Accumulated Minority Interest':['-','-'],"Total Shareholders' Equity":['10,000','9,000'],
                 'Total Equity':['10,000','9,000']}),
            page(ticker,'cash-flow',{'Common Dividends':['(600)','(500)']})]


class WSJTests(unittest.TestCase):
    def save_pages(self,folder,ticker='ASII'):
        for p in pages(ticker):
            (folder/f'{ticker}-{p["statement"]}.json').write_text(json.dumps(p))

    def test_cell_units_missing_and_parentheses(self):
        self.assertEqual(cell('(1,200.5)'),-1200.5)
        self.assertEqual(cell('0'),0)
        self.assertIsNone(cell('-'))
        with self.assertRaises(InputError): cell('10%')
        with self.assertRaises(InputError): cell('NaN')

    def test_strict_table_identity_and_column_validation(self):
        p=pages()[0]
        for key,value in [('ticker','BBCA'),('url','https://example.com'),('financial_currency','EUR'),
                          ('scale','Units'),('years',['2025','2025']),('title','Other company')]:
            with self.assertRaises(InputError): validate_page({**p,key:value},'ASII','income-statement')
        p=copy.deepcopy(p); p['rows'][0]['values']=['100']
        with self.assertRaises(InputError): validate_page(p,'ASII','income-statement')

    def test_normalized_wsj_models_preserve_millions_and_source_rows(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); self.save_pages(root)
            with patch('screenerx.wsj.fetch_page',side_effect=AssertionError('unexpected network')):
                snapshot=fetch_snapshot('ASII',root,root/'evidence')
            balance=snapshot['statements']['balance']['2025-12-31']
            self.assertEqual(balance['Total Debt'],2e9)
            self.assertEqual(balance['Annual Average Shares'],1e8)
            self.assertEqual(balance['Minority Interest'],0)  # derived from observed equity reconciliation
            row,trace=estimate(snapshot,100,date(2026,10,9),load_assumptions(),use_reported_tax=True)
            self.assertEqual(row['financial_provider'],'wsj')
            self.assertTrue(row['valuation_source'].startswith('WSJ'))
            self.assertAlmostEqual(row['tax_rate'],0.2)
            self.assertIsNotNone(row['ddm']); self.assertIsNotNone(row['rim']); self.assertIsNotNone(row['eva'])
            self.assertEqual(trace['source_field_mapping']['2025-12-31']['cashflow']['Common Stock Dividend Paid'],'Common Dividends')
            self.assertEqual(len(trace['source_pages']),3)

    def test_unavailable_cashflow_stays_missing_without_yahoo_fallback(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); self.save_pages(root)
            (root/'ASII-cash-flow.json').unlink()
            with patch('screenerx.valuation.fetch_snapshot',side_effect=AssertionError('Yahoo financial fallback')):
                snapshot=fetch_snapshot('ASII',root)
                row,_=estimate(snapshot,100,date(2026,10,9),load_assumptions())
            self.assertIsNone(row['ddm'])
            self.assertIn('WSJ cashflow coverage unavailable',row['warnings'])

    def test_saved_capture_reprocessing_preserves_source_retrieval_time(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); self.save_pages(root)
            first=fetch_snapshot('ASII',root); second=fetch_snapshot('ASII',root)
            self.assertEqual(first,second)
            self.assertEqual(first['fetched_at'],'2026-10-12T00:00:00Z')

    def test_http_401_is_reported_not_bypassed_or_retried(self):
        with patch('screenerx.wsj.urlopen',side_effect=HTTPError(page_url('ASII','income-statement'),401,'challenge',None,None)) as opener:
            with self.assertRaisesRegex(InputError,'WSJ HTTP 401'): fetch_page('ASII','income-statement')
            self.assertEqual(opener.call_count,1)

    def test_selected_provider_rejects_mislabeled_snapshot(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); self.save_pages(root)
            snapshot=fetch_snapshot('ASII',root); snapshot['provider']='yfinance'
            snapshots=root/'snapshots'; snapshots.mkdir()
            (snapshots/'ASII.json').write_text(json.dumps(snapshot))
            candle={'ticker':'ASII','date':'2026-10-09','open':100,'high':101,'low':99,'close':100,
                    'volume':1000,'traded_value_idr':100000,'source':'Yahoo Finance','corporate_actions_checked':'false'}
            prices=root/'prices.csv'; write_csv(prices,[candle],list(candle))
            rows,report=generate(prices,date(2026,10,9),root/'results',snapshot_dir=snapshots,provider='wsj')
            self.assertEqual(rows,[])
            self.assertFalse(report['company_data_fallback'])
            self.assertIn('source does not match',report['errors'][0]['reason'])


if __name__=='__main__': unittest.main()
