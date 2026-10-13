import copy
import json
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from examples.generate_demo import generate
from screenerx.engine import load_config, load_prices
from screenerx.research import main, research_screen


class ResearchTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.asof=generate(self.root)
        self.config=load_config(self.root/'config.json')
        self.prices=load_prices(self.root/'prices.csv')

    def test_missing_broker_and_valuations_do_not_block_price_research(self):
        rows,issues=research_screen(self.prices,self.config,self.asof)
        self.assertTrue(rows)
        self.assertLessEqual(len(rows),10)
        for row in rows:
            self.assertEqual(row['status'],'RESEARCH_ONLY')
            self.assertEqual(row['broker_flow_status'],'ON_HOLD')
            self.assertNotIn('composite_score',row)
            self.assertLess(row['stop_loss_price'],row['entry_price'])

    def test_future_candles_do_not_change_results(self):
        before=research_screen(self.prices,self.config,self.asof)
        changed=copy.deepcopy(self.prices)
        for history in changed.values():
            row=copy.deepcopy(history[-1]); row['date']+=timedelta(days=1)
            row.update(open=10000,high=12000,low=9000,close=11000)
            history.append(row)
        self.assertEqual(before,research_screen(changed,self.config,self.asof))

    def test_breakout_does_not_invent_target(self):
        history=self.prices['DEMO01']
        previous=max(r['high'] for r in history[:-1])
        history[-1].update(open=previous+100,high=previous+200,low=previous+50,close=previous+150)
        rows,_=research_screen({'DEMO01':history},self.config,self.asof)
        self.assertEqual(len(rows),1)
        self.assertIsNone(rows[0]['tp1_price'])
        self.assertIsNone(rows[0]['net_rr'])

    def test_stale_prices_excluded(self):
        self.prices['DEMO01'].pop()
        rows,issues=research_screen(self.prices,self.config,self.asof)
        self.assertNotIn('DEMO01',[r['ticker'] for r in rows])
        self.assertIn('No candle',next(r['reason'] for r in issues if r['ticker']=='DEMO01'))

    def test_offline_cli_writes_report_and_preserves_existing_output(self):
        output=self.root/'results'
        args=['--prices',str(self.root/'prices.csv'),'--config',str(self.root/'config.json'),
              '--as-of',self.asof.isoformat(),'--output',str(output)]
        with patch('screenerx.research.fetch_main',side_effect=AssertionError('unexpected network')):
            self.assertEqual(main(args),0)
        report=json.loads((output/'run.json').read_text())
        self.assertEqual(report['broker_flow_status'],'ON_HOLD')
        self.assertTrue((output/'report.md').exists())
        self.assertEqual(main(args),2)


if __name__=='__main__': unittest.main()
