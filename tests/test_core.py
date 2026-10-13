import copy
import json
import math
import tempfile
import threading
import unittest
from datetime import date, timedelta
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen
from unittest.mock import patch

from screenerx.core import CoreEngine, DEFAULT_PROFILE
from screenerx.core_cli import main
from screenerx.core_http import make_handler
from screenerx.core_service import CoreService, DirectoryRepository
from screenerx.engine import InputError, load_config, write_csv
from screenerx.fetch import FIELDS
from screenerx.valuation import load_assumptions
from screenerx.wsj import fetch_snapshot
from test_wsj import pages


ASOF=date(2026,10,9)
ROOT=Path(__file__).resolve().parent.parent


def price_history():
    dates=[]; current=ASOF
    while len(dates)<130:
        if current.weekday()<5: dates.append(current)
        current-=timedelta(days=1)
    records=[]
    for index,d in enumerate(reversed(dates)):
        close=80+index*0.1
        records.append({'date':d,'open':close-0.5,'high':close+2,'low':close-2,'close':close,
                        'volume':100000000,'traded_value_idr':close*100000000,'bid':None,'ask':None,
                        'source':'Yahoo Finance','actions_checked':False,'turnover_basis':'close_times_volume_estimate','tradable':True})
    records[-40]['high']+=20  # observed overhead target, frozen before decision candle
    return records


def financial_snapshot(ticker):
    with tempfile.TemporaryDirectory() as folder:
        root=Path(folder)
        for page in pages(ticker):
            if page['statement']=='income-statement':
                next(r for r in page['rows'] if r['label']=='EBIT')['values']=['1,400','1,300']
            (root/f'{ticker}-{page["statement"]}.json').write_text(json.dumps(page))
        return fetch_snapshot(ticker,root)


class CoreTests(unittest.TestCase):
    def test_yfinance_requires_explicit_provider_and_source_evidence(self):
        snapshot=financial_snapshot('ASII')
        snapshot['provider']='yfinance'
        snapshot['source_pages']=[]
        engine=CoreEngine(load_config(ROOT/'config.json'),load_assumptions(),financial_provider='yfinance')
        missing=engine.inspect_ticker('ASII',price_history(),ASOF,snapshot)
        self.assertEqual(missing['coverage']['yfinance_source']['status'],'PASS')
        self.assertEqual(missing['coverage']['financial_evidence']['status'],'FAIL')
        snapshot['source_evidence']={'provider':'yfinance','symbol':'ASII.JK','sha256':'a'*64}
        accepted=engine.inspect_ticker('ASII',price_history(),ASOF,snapshot)
        self.assertEqual(accepted['coverage']['financial_evidence']['status'],'PASS')
        self.assertEqual(accepted['coverage']['aligned_financials']['status'],'PASS')
        default=CoreEngine(load_config(ROOT/'config.json'),load_assumptions()).inspect_ticker('ASII',price_history(),ASOF,snapshot)
        self.assertEqual(default['coverage']['wsj_source']['status'],'FAIL')
        self.assertIsNone(default['valuation'])

    def setUp(self):
        self.engine=CoreEngine(load_config(ROOT/'config.json'),load_assumptions())
        self.history=price_history(); self.snapshot=financial_snapshot('ASII')
        self.sessions=[r['date'] for r in self.history]

    def inspect(self,history=None,snapshot=None,ticker='ASII'):
        return self.engine.inspect_ticker(ticker,self.history if history is None else history,ASOF,
                                         self.snapshot if snapshot is None else snapshot,sessions=self.sessions)

    def test_full_coverage_and_weight_contributions_are_reconciled(self):
        report=self.inspect()
        self.assertTrue(report['coverage_complete'],report['missing_inputs'])
        self.assertTrue(report['eligible_for_ranking'],report['failed_quality_checks'])
        score=report['score']
        self.assertAlmostEqual(score['total'],sum(c['contribution'] for c in score['components'].values()))
        for component in score['components'].values():
            self.assertAlmostEqual(component['contribution'],component['raw_score']*component['weight_percent']/100)
        self.assertFalse(report['execution_readiness']['trade_qualified'])
        self.assertEqual(report['broker_flow_status'],'ON_HOLD')
        self.assertIn('WSJ models',report['explanation'])
        self.assertEqual(report['ranking_status'],'ELIGIBLE_UNRANKED')

    def test_missing_applicable_model_never_gets_an_aggregate_score(self):
        snapshot=copy.deepcopy(self.snapshot); snapshot['statements']['cashflow']={}
        report=self.inspect(snapshot=snapshot)
        self.assertFalse(report['coverage_complete'])
        self.assertIsNone(report['score'])
        self.assertIsNotNone(report['technical'])
        self.assertEqual(report['models']['ddm']['status'],'UNAVAILABLE')
        self.assertIn('Missing an applicable',report['explanation'])

    def test_financial_eva_and_observed_zero_dividends_have_explicit_applicability(self):
        snapshot=copy.deepcopy(self.snapshot); snapshot['metadata']['sector']='Financial Services'
        report=self.inspect(snapshot=snapshot)
        self.assertEqual(report['models']['eva']['status'],'NOT_APPLICABLE')
        self.assertTrue(report['coverage_complete'])
        snapshot=copy.deepcopy(self.snapshot)
        for row in snapshot['statements']['cashflow'].values(): row['Common Stock Dividend Paid']=0
        report=self.inspect(snapshot=snapshot)
        self.assertEqual(report['models']['ddm']['status'],'NOT_APPLICABLE')
        self.assertTrue(report['coverage_complete'])

    def test_unsustainable_payout_is_unavailable_not_not_applicable(self):
        snapshot=copy.deepcopy(self.snapshot)
        snapshot['statements']['cashflow']['2025-12-31']['Common Stock Dividend Paid']=-2e9
        report=self.inspect(snapshot=snapshot)
        self.assertEqual(report['models']['ddm']['status'],'UNAVAILABLE')
        self.assertFalse(report['eligible_for_ranking'])

    def test_price_gap_staleness_invalid_candle_and_source_mismatch_excluded(self):
        missing=copy.deepcopy(self.history); missing.pop(-40)
        self.assertEqual(self.inspect(history=missing)['coverage']['session_alignment']['status'],'FAIL')
        stale=copy.deepcopy(self.history); stale.pop()
        self.assertFalse(self.inspect(history=stale)['eligible_for_ranking'])
        invalid=copy.deepcopy(self.history); invalid[-1]['close']=float('nan')
        self.assertFalse(self.inspect(history=invalid)['eligible_for_ranking'])
        snapshot=copy.deepcopy(self.snapshot); snapshot['provider']='yfinance'
        self.assertFalse(self.inspect(snapshot=snapshot)['eligible_for_ranking'])

    def test_missing_statement_evidence_blocks_even_positive_models(self):
        snapshot=copy.deepcopy(self.snapshot); snapshot['source_pages'].pop()
        report=self.inspect(snapshot=snapshot)
        self.assertEqual(report['coverage']['financial_evidence']['status'],'FAIL')
        self.assertIsNone(report['score'])

    def test_unknown_sector_is_not_financial_eva_nonapplicability(self):
        snapshot=copy.deepcopy(self.snapshot); snapshot['metadata']['sector']=None
        report=self.inspect(snapshot=snapshot)
        self.assertEqual(report['models']['eva']['status'],'UNAVAILABLE')
        self.assertFalse(report['eligible_for_ranking'])

    def test_malformed_company_snapshot_does_not_abort_other_companies(self):
        report=self.engine.screen(['ASII','BAD'],{'ASII':self.history,'BAD':self.history},
                                  {'ASII':self.snapshot,'BAD':{'metadata':[],'statements':None}},ASOF)
        self.assertEqual(report['selected_count'],1)
        bad=next(r for r in report['companies'] if r['ticker']=='BAD')
        self.assertFalse(bad['eligible_for_ranking'])
        self.assertIn('Malformed',bad['coverage']['wsj_source']['reason'])
        snapshot=copy.deepcopy(self.snapshot)
        snapshot['statements']['income']['2025-12-31']['Net Income Common Stockholders']=float('nan')
        report=self.inspect(snapshot=snapshot)
        self.assertFalse(report['eligible_for_ranking'])
        json.dumps(report,allow_nan=False)

    def test_future_prices_are_ignored_without_mutating_inputs(self):
        before=copy.deepcopy(self.history)
        baseline=self.inspect()
        future={**self.history[-1],'date':ASOF+timedelta(days=1),'close':float('nan')}
        changed=self.history+[future]
        self.assertEqual(baseline,self.inspect(history=changed))
        self.assertEqual(self.history,before)

    def test_rank_limit_tie_breaks_and_missing_universe_members_are_explicit(self):
        universe=[f'T{i:03d}' for i in range(14)]+['MISS']
        prices={t:copy.deepcopy(self.history) for t in universe[:-1]}
        snapshots={t:financial_snapshot(t) for t in universe[:-1]}
        report=self.engine.screen(universe,prices,snapshots,ASOF)
        self.assertEqual(report['selected_count'],10)
        self.assertEqual(report['universe_count'],15)
        self.assertEqual(report['qualifying_count'],14)
        self.assertEqual([r['ticker'] for r in report['top10']],sorted(universe[:-1])[:10])
        self.assertTrue(report['all_selected_have_full_coverage'])
        missing=next(r for r in report['companies'] if r['ticker']=='MISS')
        self.assertFalse(missing['eligible_for_ranking'])
        self.assertIsNone(missing['score'])
        self.assertIn('Score tie',report['top10'][0]['rank_comparison']['reason'])

    def test_fewer_candidates_are_not_padded_and_zero_weights_cannot_bypass_gates(self):
        profile=copy.deepcopy(DEFAULT_PROFILE); profile['weights']={'fundamental':0,'technical':100,'liquidity':0}
        engine=CoreEngine(load_config(ROOT/'config.json'),load_assumptions(),profile)
        report=engine.screen(['ASII','MISS'],{'ASII':self.history},{'ASII':self.snapshot},ASOF)
        self.assertEqual(report['selected_count'],1)
        self.assertEqual(report['unfilled_slots'],9)
        self.assertEqual(report['top10'][0]['score']['total'],report['top10'][0]['score']['components']['technical']['raw_score'])
        self.assertIn('fundamental * 0%',report['top10'][0]['score']['formula'])

    def test_invalid_profile_and_discount_assumptions_rejected(self):
        profile=copy.deepcopy(DEFAULT_PROFILE); profile['weights']['fundamental']=100
        with self.assertRaises(InputError): CoreEngine(load_config(ROOT/'config.json'),load_assumptions(),profile)
        valuation=load_assumptions(); valuation['scenarios']['base']['terminal_growth']=0.12
        with self.assertRaises(InputError): CoreEngine(load_config(ROOT/'config.json'),valuation)

    def test_discount_filter_is_separate_from_coverage(self):
        config=load_config(ROOT/'config.json'); config['fundamental']['require_discount']=True
        engine=CoreEngine(config,load_assumptions())
        report=engine.inspect_ticker('ASII',self.history,ASOF,self.snapshot,sessions=self.sessions)
        self.assertTrue(report['coverage_complete'])
        self.assertFalse(report['eligible_for_ranking'])
        self.assertEqual(report['quality']['discount_filter']['status'],'FAIL')

    def test_cli_exports_explanations_lookup_and_preserves_outputs(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); prices=root/'prices.csv'; snapshots=root/'snapshots'; snapshots.mkdir()
            records=[]
            for row in self.history:
                records.append({'ticker':'ASII','date':row['date'].isoformat(),**{k:row[k] for k in ('open','high','low','close','volume','traded_value_idr','source')},
                                'corporate_actions_checked':'false','traded_value_basis':'close_times_volume_estimate','tradable':'true'})
            write_csv(prices,records,FIELDS)
            (snapshots/'ASII.json').write_text(json.dumps(self.snapshot))
            args=['screen','--prices',str(prices),'--snapshots',str(snapshots),'--as-of',ASOF.isoformat(),
                  '--tickers','ASII','MISS','--output',str(root/'result')]
            self.assertEqual(main(args),0)
            saved=json.loads((root/'result'/'core-run.json').read_text())
            self.assertEqual(saved['selected_count'],1)
            self.assertIn('Score formula',(root/'result'/'report.md').read_text())
            self.assertTrue((root/'result'/'tickers'/'MISS.json').exists())
            self.assertEqual(main(args),2)
            self.assertEqual(main(['inspect','--prices',str(prices),'--snapshots',str(snapshots),'--ticker','MISS',
                                   '--as-of',ASOF.isoformat(),'--output',str(root/'lookup.json')]),0)
            result=json.loads((root/'lookup.json').read_text())
            self.assertEqual(result['lookup_status'],'NOT_CACHED')
            self.assertIsNone(result['in_top10'])

    def test_http_any_ticker_lookup_and_invalid_symbol(self):
        repository=DirectoryRepository(); repository.prices={'ASII':self.history}
        service=CoreService(self.engine,repository,ASOF)
        server=ThreadingHTTPServer(('127.0.0.1',0),make_handler(service,['ASII']))
        thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
        try:
            base=f'http://127.0.0.1:{server.server_port}'
            with urlopen(base+'/v1/tickers/MISS',timeout=3) as response: result=json.load(response)
            self.assertEqual(result['lookup_status'],'NOT_CACHED')
            with urlopen(base+'/v1/top10',timeout=3) as response: result=json.load(response)
            self.assertEqual(result['selected_count'],0)
            self.assertNotIn('companies',result)
            with urlopen(base+'/v1/coverage',timeout=3) as response: result=json.load(response)
            self.assertEqual(result['universe_count'],1)
            with self.assertRaises(HTTPError) as failure: urlopen(base+'/v1/tickers/%2E%2E%2Fbad',timeout=3)
            self.assertEqual(failure.exception.code,400)
            with self.assertRaises(HTTPError) as failure: urlopen(base+'/v1/tickers/ASII?live=true',timeout=3)
            self.assertEqual(failure.exception.code,403)
        finally:
            server.shutdown(); server.server_close(); thread.join(timeout=3)

    def test_live_lookup_of_nonshortlisted_ticker_uses_wsj_only(self):
        service=CoreService(self.engine,DirectoryRepository(),ASOF)
        with (patch('screenerx.core_service.fetch_yfinance',side_effect=InputError('price source unavailable')),
              patch('screenerx.core_service.fetch_wsj',side_effect=InputError('WSJ HTTP 401'))):
            result=service.lookup('UNLISTED',live=True)
        self.assertEqual(result['lookup_status'],'SOURCE_UNAVAILABLE')
        self.assertEqual(len(result['source_errors']),2)
        self.assertIsNone(result['score'])
        self.assertFalse(result['coverage_complete'])


if __name__=='__main__': unittest.main()
