import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from examples.generate_demo import generate
from screenerx.engine import InputError, indicators, load_inputs, load_config, next_ticks, rounded, rsi, screen, setups, validate_config


class ScreenerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory(); cls.root=Path(cls.tmp.name)
        cls.asof=generate(cls.root)
        cls.config=load_config(cls.root/'config.json')
        cls.inputs=load_inputs(cls.root/'prices.csv',cls.root/'valuations.csv',cls.root/'brokers.csv')

    @classmethod
    def tearDownClass(cls): cls.tmp.cleanup()

    def run_screen(self,config=None,data=None,provisional=False):
        return screen(*(data or copy.deepcopy(self.inputs)),config or copy.deepcopy(self.config),self.asof,provisional)

    def test_top_ten_has_real_plans_and_explains_exclusions(self):
        rows,issues,summary=self.run_screen()
        self.assertEqual(len(rows),10)
        self.assertEqual(summary['qualifying_count'],12)
        self.assertEqual({r['ticker'] for r in rows}&{'DEMO13','DEMO14'},set())
        for r in rows:
            self.assertGreaterEqual(r['net_rr'],2)
            self.assertLess(r['stop_loss_price'],r['entry_price'])
            self.assertGreater(r['tp1_price'],r['entry_price'])
        self.assertTrue(any('cohort' in r['reason'] for r in issues if r['ticker']=='DEMO13'))
        self.assertTrue(any('critical' in r['reason'] for r in issues if r['ticker']=='DEMO14'))

    def test_weights_change_composite_and_ranking(self):
        c=copy.deepcopy(self.config); c['weights']={'fundamental':100,'broker':0,'technical':0,'execution':0}
        a,_,_=self.run_screen(); b,_,_=self.run_screen(c)
        self.assertNotEqual([r['ticker'] for r in a],[r['ticker'] for r in b])
        self.assertTrue(all(r['composite_score']==r['fundamental_score'] for r in b))
        self.assertNotIn('DEMO13',[r['ticker'] for r in b])  # zero weight does not bypass gate

    def test_invalid_weights_and_overlapping_brokers_rejected(self):
        for mutation in (lambda c:c['weights'].update(fundamental=50), lambda c:c['broker']['favored'].append('CC')):
            c=copy.deepcopy(self.config); mutation(c)
            with self.assertRaises(InputError): validate_config(c)

    def test_missing_broker_is_not_zero(self):
        data=copy.deepcopy(self.inputs); del data[2]['DEMO01'][(self.asof,'AK')]
        rows,issues,_=self.run_screen(data=data)
        self.assertNotIn('DEMO01',[r['ticker'] for r in rows])
        self.assertIn('Incomplete broker',next(r['reason'] for r in issues if r['ticker']=='DEMO01'))

    def test_costs_can_kill_an_apparently_good_trade(self):
        c=copy.deepcopy(self.config); c['execution']['stop_slippage']=0.10
        rows,issues,_=self.run_screen(c)
        self.assertEqual(rows,[])
        self.assertTrue(any('reward/risk' in r['reason'] for r in issues))

    def test_unknown_costs_are_provisional_not_free(self):
        c=copy.deepcopy(self.config); c['execution']['buy_fee']=None
        rows,issues,_=self.run_screen(c)
        self.assertEqual(rows,[])
        self.assertTrue(any(r['state']=='PROVISIONAL' for r in issues))
        rows,_,_=self.run_screen(c,provisional=True)
        self.assertEqual(len(rows),10)
        self.assertTrue(all(r['net_rr'] is None and r['status']=='PROVISIONAL' for r in rows))

    def test_no_candidates_is_valid_and_never_padded(self):
        c=copy.deepcopy(self.config); c['execution']['minimum_net_rr']=100
        rows,_,_=self.run_screen(c)
        self.assertEqual(rows,[])

    def test_future_rows_do_not_change_historical_results(self):
        from datetime import timedelta
        baseline,_,_=self.run_screen(); data=copy.deepcopy(self.inputs)
        for prices in data[0].values():
            r=copy.deepcopy(prices[-1]); r['date']+=timedelta(days=1); r.update(open=2000,high=2100,low=1900,close=2000)
            prices.append(r)
        result,_,_=self.run_screen(data=data)
        self.assertEqual(baseline,result)

    def test_bank_eva_and_same_day_levels_blocked(self):
        data=copy.deepcopy(self.inputs); data[1]['DEMO01']['sector']='bank'; data[1]['DEMO02']['levels_date']=self.asof.isoformat()
        rows,issues,_=self.run_screen(data=data)
        self.assertNotIn('DEMO01',[r['ticker'] for r in rows])
        self.assertNotIn('DEMO02',[r['ticker'] for r in rows])
        self.assertTrue(any('EVA' in r['reason'] for r in issues))
        self.assertTrue(any('frozen' in r['reason'] for r in issues))

    def test_valuation_discount_is_configurable(self):
        data=copy.deepcopy(self.inputs)
        for r in data[1].values():
            r.update(eva='1100',ddm='1100',rim='1100')
        rows,_,_=self.run_screen(data=data)
        self.assertTrue(rows)
        c=copy.deepcopy(self.config); c['fundamental']['require_discount']=True
        rows,_,_=self.run_screen(c,data)
        self.assertEqual(rows,[])

    def test_idx_tick_boundaries(self):
        self.assertEqual(next_ticks(199),200)
        self.assertEqual(next_ticks(200),202)
        self.assertEqual(next_ticks(498),500)
        self.assertEqual(next_ticks(500),505)
        self.assertEqual(next_ticks(1995),2000)
        self.assertEqual(next_ticks(2000),2010)
        self.assertEqual(next_ticks(4990),5000)
        self.assertEqual(next_ticks(5000),5025)
        self.assertEqual(rounded(1999),1995)
        self.assertEqual(next_ticks(1002),1005)

    def test_support_reversal_requires_preserved_low_and_crosses(self):
        from datetime import timedelta
        rows=copy.deepcopy(self.inputs[0]['DEMO01'])
        for j in (-40,-20):
            rows[j]['low']=950 if j==-40 else 952
        rows[-1].update(low=953,close=965,high=970)
        rows[-2].update(close=960,low=955,high=965)
        v={'support':952,'anchor':940,'trigger':None,'levels_date':self.asof-timedelta(days=20)}
        i={'atr':10,'stoch_cross':True,'macd_cross':True,'volume_multiple':2}
        result=setups(rows,v,i,self.config)
        self.assertIn('support_reversal',[r['setup'] for r in result])
        i['macd_cross']=False
        self.assertEqual(setups(rows,v,i,self.config),[])
        i['macd_cross']=True; rows[-1]['low']=940
        self.assertEqual(setups(rows,v,i,self.config),[])

    def test_reclaim_rejects_invalidated_structure(self):
        from datetime import timedelta
        rows=copy.deepcopy(self.inputs[0]['DEMO01'])
        rows[-2].update(close=949,high=953,low=945)
        rows[-1].update(close=955,high=958,low=945)
        v={'support':950,'anchor':940,'trigger':None,'levels_date':self.asof-timedelta(days=20)}
        i={'atr':10,'stoch_cross':False,'macd_cross':False,'volume_multiple':2}
        self.assertIn('failed_breakdown_reclaim',[r['setup'] for r in setups(rows,v,i,self.config)])
        rows[-1]['low']=930
        self.assertEqual(setups(rows,v,i,self.config),[])

    def test_indicator_seed_and_flat_market(self):
        self.assertEqual(rsi(list(range(30)),14)[14],100)
        self.assertEqual(rsi(list(range(30,0,-1)),14)[14],0)
        rows=copy.deepcopy(self.inputs[0]['DEMO01'])
        for r in rows: r.update(open=100,high=101,low=99,close=100,volume=1000)
        i=indicators(rows,self.config)
        self.assertEqual(i['atr'],2)
        self.assertEqual(i['stoch_k'],50)
        self.assertEqual(i['macd'],0)
        self.assertFalse(i['stoch_cross'])
        self.assertFalse(i['macd_cross'])

    def test_quote_missing_and_excessive_participation(self):
        data=copy.deepcopy(self.inputs); data[0]['DEMO01'][-1]['bid']=None
        _,issues,_=self.run_screen(data=data)
        self.assertEqual(next(r['state'] for r in issues if r['ticker']=='DEMO01'),'PROVISIONAL')
        c=copy.deepcopy(self.config); c['execution']['planned_order_idr']=1000000000
        rows,issues,_=self.run_screen(c)
        self.assertFalse(rows)
        self.assertTrue(any('participation' in r['reason'] for r in issues))

    def test_inconsistent_broker_units_rejected(self):
        data=copy.deepcopy(self.inputs); data[2]['DEMO01'][(self.asof,'AK')]=30000000000
        _,issues,_=self.run_screen(data=data)
        self.assertIn('turnover',next(r['reason'] for r in issues if r['ticker']=='DEMO01'))

    def test_cli_writes_csv_metadata_and_preserves_prior_runs(self):
        output=self.root/'cli-output'
        cmd=[sys.executable,'-m','screenerx','--prices',str(self.root/'prices.csv'),'--valuations',str(self.root/'valuations.csv'),'--brokers',str(self.root/'brokers.csv'),'--config',str(self.root/'config.json'),'--as-of',self.asof.isoformat(),'--output',str(output)]
        first=subprocess.run(cmd,capture_output=True,text=True)
        self.assertEqual(first.returncode,0,first.stderr)
        self.assertEqual(json.loads((output/'run.json').read_text())['selected_count'],10)
        self.assertIn('net_rr',(output/'top10.csv').read_text())
        self.assertEqual(subprocess.run(cmd,capture_output=True).returncode,2)


if __name__=='__main__': unittest.main()
