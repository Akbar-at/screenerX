import copy
import unittest
from unittest.mock import Mock
from screenerx.idx_screening import enrich_report

class IDXScreeningTests(unittest.TestCase):
    def test_all_companies_enriched_and_rank_weights_preserved(self):
        companies=[{'ticker':ticker,'ranking_status':'SELECTED' if i==0 else 'EXCLUDED','score':{'total':80-i}}
                   for i,ticker in enumerate(('BMRI','BBCA','PTSN'))]
        report={'as_of':'2026-10-13','companies':companies,'top10':[copy.deepcopy(companies[0])]}
        original=copy.deepcopy(report['top10'])
        def metrics(ticker,asof,reference):
            net={'BMRI':-30,'BBCA':20,'PTSN':0}[ticker]
            return {'ticker':ticker,'as_of':asof,'stocks':{'Volume':100},'net_foreign_volume':net,
                    'datasets':{'stocks':{'status':'AVAILABLE','records':963}},'errors':{},'evidence':{}}
        source=Mock();source.stock_metrics.side_effect=metrics
        summary=enrich_report(report,source)
        self.assertEqual(source.stock_metrics.call_count,3)
        self.assertEqual(summary['counts'],{'available':3,'net_buy':1,'net_sell':1,'flat':1,'unavailable':0})
        self.assertEqual(summary['net_buy_leaders'][0]['ticker'],'BBCA')
        self.assertEqual(summary['net_sell_leaders'][0]['ticker'],'BMRI')
        self.assertEqual(report['top10'][0]['score'],original[0]['score'])
        self.assertEqual(report['top10'][0]['idx_screening']['net_share_of_volume'],-.3)
        self.assertEqual(report['top10'][0]['idx_screening']['score_contribution'],0)
        self.assertEqual(report['top10'][0]['_idx_data']['ticker'],'BMRI')

    def test_partial_source_never_invents_net_or_coverage(self):
        company={'ticker':'PTSN','ranking_status':'EXCLUDED'}
        report={'as_of':'2026-10-13','companies':[company],'top10':[]}
        source=Mock();source.stock_metrics.return_value={'datasets':{'stocks':{'status':'UNAVAILABLE'}},
                         'errors':{'stocks':'Source unavailable'},'evidence':{}}
        summary=enrich_report(report,source)
        self.assertEqual(summary['counts']['unavailable'],1)
        self.assertEqual(summary['net_buy_leaders'],[])
        self.assertIsNone(company['idx_screening']['net_foreign_volume'])
        self.assertEqual(company['idx_screening']['broker_net_status'],'ON_HOLD')

    def test_zero_volume_has_no_division_or_percentage(self):
        report={'as_of':'2026-10-13','companies':[{'ticker':'BBCA','ranking_status':'SELECTED'}],'top10':[]}
        source=Mock();source.stock_metrics.return_value={'stocks':{'Volume':0},'net_foreign_volume':0,
                                                       'datasets':{},'errors':{},'evidence':{}}
        enrich_report(report,source)
        self.assertIsNone(report['companies'][0]['idx_screening']['net_share_of_volume'])

