import copy
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from screenerx.engine import InputError, write_csv
from screenerx.research import attach_valuations
from screenerx.valuation import estimate, generate, load_assumptions, model_values
from screenerx.fx import validate_fx


def fixture(ticker='BBCA'):
    return {'ticker':ticker,'symbol':ticker+'.JK','provider':'yfinance','fetched_at':'2026-10-12T00:00:00Z',
            'metadata':{'sector':'Industrials','currency':'IDR','financialCurrency':'IDR'},
            'statements':{'income':{'2025-12-31':{'Net Income Common Stockholders':1200,'Operating Income':1500}},
                          'balance':{'2025-12-31':{'Common Stock Equity':10000,'Ordinary Shares Number':100,
                                                  'Total Debt':2000,'Cash And Cash Equivalents':1000,'Minority Interest':0}},
                          'cashflow':{'2025-12-31':{'Common Stock Dividend Paid':-600}}},'errors':{}}


class ValuationTests(unittest.TestCase):
    def setUp(self):
        self.config=load_assumptions()
        self.asof=date(2026,10,9)

    def test_steady_state_ddm_matches_gordon_value(self):
        inputs={'shares':100,'equity':10000,'income':1200,'dividends':600,'payout':0.5,
                'operating_income':1500,'debt':2000,'cash':1000,'minority':0,'financial':False,'tax_rate':0.2}
        scenario={'cost_of_equity':0.12,'wacc':0.1,'growth':0.03,'terminal_growth':0.03,'earnings_multiplier':1}
        values,_,_=model_values(inputs,scenario,5)
        self.assertAlmostEqual(values['ddm'],6*1.03/(0.12-0.03))
        self.assertAlmostEqual(values['rim'],100)  # ROE equals cost of equity

    def test_zero_growth_eva_reconciles_enterprise_equity_bridge(self):
        inputs={'shares':100,'equity':10000,'income':1200,'dividends':600,'payout':0.5,
                'operating_income':1500,'debt':2000,'cash':1000,'minority':500,'financial':False,'tax_rate':0.2}
        scenario={'cost_of_equity':0.12,'wacc':0.1,'growth':0,'terminal_growth':0,'earnings_multiplier':1}
        values,_,_=model_values(inputs,scenario,5)
        expected=(1500*0.8/0.1-2000+1000-500)/100
        self.assertAlmostEqual(values['eva'],expected)

    def test_bank_eva_is_excluded_and_validation_never_attested(self):
        snapshot=fixture(); snapshot['metadata']['sector']='Financial Services'
        row,trace=estimate(snapshot,100,self.asof,self.config)
        self.assertIsNone(row['eva'])
        self.assertIsNotNone(row['ddm'])
        self.assertIsNotNone(row['rim'])
        self.assertEqual(row['validated'],'false')
        self.assertFalse(trace['point_in_time_verified'])

    def test_unsustainable_dividends_not_extrapolated(self):
        snapshot=fixture(); snapshot['statements']['cashflow']['2025-12-31']['Common Stock Dividend Paid']=-2000
        row,_=estimate(snapshot,100,self.asof,self.config)
        self.assertIsNone(row['ddm'])
        self.assertEqual(row['payout_ratio'],1)
        self.assertIn('payout exceeds',row['method_reasons'])

    def test_zero_missing_and_loss_inputs_remain_distinct(self):
        snapshot=fixture(); snapshot['statements']['cashflow']['2025-12-31']['Common Stock Dividend Paid']=0
        row,_=estimate(snapshot,100,self.asof,self.config)
        self.assertEqual(row['payout_ratio'],0)
        self.assertIsNone(row['ddm'])
        snapshot['statements']['cashflow']={}
        row,_=estimate(snapshot,100,self.asof,self.config)
        self.assertEqual(row['payout_ratio'],self.config['default_payout_ratio'])
        snapshot['statements']['income']['2025-12-31']['Net Income Common Stockholders']=-100
        row,_=estimate(snapshot,100,self.asof,self.config)
        self.assertIsNone(row['rim'])
        self.assertIsNone(row['ddm'])

    def test_currency_share_and_statement_alignment_gates(self):
        snapshot=fixture(); snapshot['metadata']['financialCurrency']='USD'
        with self.assertRaises(InputError): estimate(snapshot,100,self.asof,self.config)
        snapshot=fixture(); snapshot['statements']['balance']['2025-12-31']['Ordinary Shares Number']=0
        with self.assertRaises(InputError): estimate(snapshot,100,self.asof,self.config)
        snapshot=fixture(); snapshot['statements']['balance']={'2024-12-31':{}}
        with self.assertRaises(InputError): estimate(snapshot,100,self.asof,self.config)

    def test_future_recent_and_stale_statements_not_used(self):
        snapshot=fixture()
        for table in snapshot['statements'].values():
            table['2026-12-31']=copy.deepcopy(table['2025-12-31'])
            table['2026-09-30']=copy.deepcopy(table['2025-12-31'])
        row,_=estimate(snapshot,100,self.asof,self.config)
        self.assertEqual(row['statement_date'],'2025-12-31')
        with self.assertRaises(InputError): estimate(fixture(),100,date(2025,12,31),self.config)
        with self.assertRaises(InputError): estimate(fixture(),100,date(2028,12,31),self.config)

    def test_missing_debt_not_assumed_zero_for_eva(self):
        snapshot=fixture(); del snapshot['statements']['balance']['2025-12-31']['Total Debt']
        row,_=estimate(snapshot,100,self.asof,self.config)
        self.assertIsNone(row['eva'])
        self.assertIsNotNone(row['rim'])

    def test_usd_translation_scales_money_and_preserves_shares_and_ratios(self):
        base=fixture()
        original,_=estimate(base,100,self.asof,self.config)
        foreign=copy.deepcopy(base); foreign['metadata']['financialCurrency']='USD'
        fx={'provider':'yfinance','symbol':'USDIDR=X','base_currency':'USD','quote_currency':'IDR',
            'rate':16000,'rate_date':'2026-10-09'}
        translated,trace=estimate(foreign,100,self.asof,self.config,fx)
        for key in ('ddm','rim','eva','fair_value','book_equity','net_income'):
            self.assertAlmostEqual(translated[key],original[key]*16000)
        self.assertEqual(translated['shares'],original['shares'])
        self.assertEqual(translated['payout_ratio'],original['payout_ratio'])
        self.assertEqual(translated['financial_currency'],'USD')
        self.assertEqual(trace['currency_translation']['model_currency'],'IDR')

    def test_fx_direction_future_staleness_and_invalid_rate_rejected(self):
        fx={'provider':'yfinance','symbol':'USDIDR=X','base_currency':'USD','quote_currency':'IDR',
            'rate':16000,'rate_date':'2026-10-09'}
        for key,value in [('base_currency','IDR'),('quote_currency','USD'),('symbol','IDRUSD=X'),
                          ('rate_date','2026-10-10'),('rate_date','2026-10-01'),('rate',0),('rate',float('nan'))]:
            bad={**fx,key:value}
            with self.assertRaises(InputError): validate_fx(bad,'USD',self.asof)

    def test_reported_effective_tax_or_explicit_fallback(self):
        snapshot=fixture(); inc=snapshot['statements']['income']['2025-12-31']
        inc.update({'Tax Provision':100,'Pretax Income':1000})
        row,trace=estimate(snapshot,100,self.asof,self.config,use_reported_tax=True)
        self.assertEqual(row['tax_rate'],0.1)
        self.assertTrue(row['tax_rate_source'].startswith('reported_effective:'))
        inc['Tax Provision']=900
        row,_=estimate(snapshot,100,self.asof,self.config,use_reported_tax=True)
        self.assertEqual(row['tax_rate'],self.config['tax_rate'])
        self.assertEqual(row['tax_rate_source'],'configured_assumption')

    def test_saved_fx_supports_offline_usd_generation(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); snapshots=root/'snapshots'; snapshots.mkdir()
            snapshot=fixture(); snapshot['metadata']['financialCurrency']='USD'
            (snapshots/'BBCA.json').write_text(json.dumps(snapshot))
            fx=root/'fx.json'; fx.write_text(json.dumps({'provider':'yfinance','symbol':'USDIDR=X',
                'base_currency':'USD','quote_currency':'IDR','rate':16000,'rate_date':'2026-10-09'}))
            prices=root/'prices.csv'; candle={'ticker':'BBCA','date':'2026-10-09','open':100,'high':101,'low':99,
                'close':100,'volume':1000,'traded_value_idr':100000,'source':'Yahoo Finance','corporate_actions_checked':'false'}
            write_csv(prices,[candle],list(candle))
            with (patch('screenerx.valuation.fetch_snapshot',side_effect=AssertionError('network')),
                  patch('screenerx.valuation.fetch_fx',side_effect=AssertionError('FX network'))):
                rows,report=generate(prices,self.asof,root/'results',snapshot_dir=snapshots,fx_snapshot=fx,provider='yfinance')
            self.assertEqual(report['estimated_count'],1)
            self.assertEqual(rows[0]['shares'],100)
            self.assertTrue((root/'results'/'fx'/'USDIDR.json').exists())

    def test_config_rejects_terminal_singularity_and_nonfinite(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'config.json'
            for value in (0.12,float('nan')):
                config=copy.deepcopy(self.config); config['scenarios']['base']['terminal_growth']=value
                path.write_text(json.dumps(config))
                with self.assertRaises(InputError): load_assumptions(path)

    def test_offline_generation_partial_coverage_and_safe_join(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); snapshots=root/'snapshots'; snapshots.mkdir()
            snapshot=fixture(); (snapshots/'BBCA.json').write_text(json.dumps(snapshot))
            bad=fixture('INCO'); bad['metadata']['financialCurrency']='USD'
            (snapshots/'INCO.json').write_text(json.dumps(bad))
            prices=root/'prices.csv'
            candles=[{'ticker':t,'date':'2026-10-09','open':100,'high':101,'low':99,'close':100,
                      'volume':1000,'traded_value_idr':100000,'source':'Yahoo Finance','corporate_actions_checked':'false'}
                     for t in ('BBCA','INCO')]
            write_csv(prices,candles,list(candles[0]))
            output=root/'valuations'
            with patch('screenerx.valuation.fetch_snapshot',side_effect=AssertionError('network')):
                estimates,report=generate(prices,self.asof,output,snapshot_dir=snapshots,provider='yfinance')
            self.assertEqual(report['estimated_count'],1)
            self.assertEqual(report['errors'][0]['ticker'],'INCO')
            rows=[{'ticker':'BBCA','close':100,'warnings':''},{'ticker':'INCO','close':100,'warnings':''}]
            attach_valuations(rows,output/'estimates.csv',self.asof)
            self.assertEqual(rows[0]['fundamental_status'],'UNREVIEWED_ESTIMATE')
            self.assertEqual(rows[1]['fundamental_status'],'UNAVAILABLE')
            rows[0]['close']=101
            with self.assertRaises(InputError): attach_valuations(rows,output/'estimates.csv',self.asof)
            with self.assertRaises(InputError): generate(prices,self.asof,output,snapshot_dir=snapshots,provider='yfinance')


if __name__=='__main__': unittest.main()
