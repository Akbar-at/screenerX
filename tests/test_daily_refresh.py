import json
import tempfile
import unittest
from datetime import datetime,date
from pathlib import Path
from unittest.mock import MagicMock,patch

from screenerx.bot_store import BotStore
from screenerx.daily_refresh import DailyRefresh,due,atomic_json,load_latest,publication_checks
from screenerx.engine import InputError
from screenerx.fetch import JAKARTA


NOW=datetime(2026,10,13,18,30,tzinfo=JAKARTA)


class DailyRefreshTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.root=Path(self.temp.name)
        self.store=BotStore(self.root/'state.sqlite')
        self.repository=MagicMock(); self.repository.report={'as_of':'2026-10-12','input_files':{}}
        (self.root/'snapshots').mkdir()
        self.callback=MagicMock()
        self.manager=DailyRefresh(self.repository,self.store,self.root/'refresh',self.root/'snapshots',
                                  pointer=self.root/'latest.json',on_publish=self.callback)
    def tearDown(self): self.temp.cleanup()

    def fake_market(self,folder,**kwargs):
        folder=Path(folder); (folder/'core').mkdir(parents=True,exist_ok=True)
        (folder/'core/core-run.json').write_text(json.dumps({'as_of':'2026-10-13'}))
        (folder/'prices.csv').write_text('ticker,date\nBBCA,2026-10-13\n')
        return {'report_path':str(folder/'core/report.md'),'price_count':90,'current_price_count':90,'universe_count':100}

    def providers(self):
        return (patch('screenerx.production.latest_session',return_value=(date(2026,10,13),{'observed':'2026-10-13'})),
                patch('screenerx.market.run',side_effect=self.fake_market),
                patch('screenerx.fx.fetch_fx',side_effect=InputError('Temporary FX failure')),
                patch('screenerx.reporting.render_top'),patch('screenerx.reporting.ReportRepository',return_value=MagicMock(report={'as_of':'2026-10-13','coverage_complete_count':100})))

    def test_schedule_is_jakarta_weekdays_after_0730(self):
        self.assertFalse(due(datetime(2026,10,13,7,29,tzinfo=JAKARTA)))
        self.assertTrue(due(datetime(2026,10,13,7,30,tzinfo=JAKARTA)))
        self.assertTrue(due(NOW))
        self.assertFalse(due(datetime(2026,10,17,19,0,tzinfo=JAKARTA)))
        self.assertTrue(due(datetime(2026,10,13,12,0,tzinfo=__import__('datetime').timezone.utc)))

    def test_preclose_run_creates_no_jobs(self):
        self.assertEqual(self.manager.run(now=NOW.replace(hour=7,minute=29))['status'],'NOT_DUE')
        self.assertEqual(self.store.query('SELECT * FROM sx_refresh_jobs',fetch=True),[])

    def test_delayed_job_discovers_the_morning_completed_session(self):
        with patch('screenerx.production.latest_session',return_value=(date(2026,10,12),{})) as discovery:
            self.assertEqual(self.manager.run(now=NOW)['status'],'SKIPPED')
            discovery.assert_called_once_with(datetime(2026,10,13,7,30,tzinfo=JAKARTA))
        self.assertTrue(due(datetime(2026,10,13,0,30,tzinfo=__import__('datetime').timezone.utc)))
        self.assertFalse(due(datetime(2026,10,13,0,29,tzinfo=__import__('datetime').timezone.utc)))

    def test_publish_is_atomic_and_same_day_is_not_rerun(self):
        a,b,c,d,e=self.providers()
        with a,b as market,c,d,e as repository:
            repository.return_value.report={'as_of':'2026-10-13','coverage_complete_count':100}
            result=self.manager.run(now=NOW)
            self.assertEqual(result['status'],'PUBLISHED')
            pointer=json.loads((self.root/'latest.json').read_text())
            self.assertEqual(pointer['as_of'],'2026-10-13')
            self.assertTrue(Path(pointer['prices']).exists())
            self.assertEqual(self.manager.run(now=NOW)['status'],'ALREADY_HANDLED')
            self.assertEqual(market.call_count,1)
            self.assertTrue(market.call_args.kwargs['retry_failed'])
            self.assertEqual(market.call_args.kwargs['previous_prices'],self.repository.prices_path)
            self.callback.assert_called_once_with(repository.return_value)

    def test_low_price_coverage_retains_previous_report(self):
        atomic_json(self.root/'latest.json',{'as_of':'2026-10-12','marker':'previous'})
        a,b,c,d,e=self.providers()
        with a,b as market,c,d,e:
            market.side_effect=None; market.return_value={'report_path':'unused','price_count':20,'universe_count':100}
            result=self.manager.run(now=NOW)
        self.assertEqual(result['status'],'RETRY')
        self.assertEqual(json.loads((self.root/'latest.json').read_text())['marker'],'previous')
        self.callback.assert_not_called()

    def test_zero_complete_coverage_cannot_replace_a_healthy_run(self):
        self.repository.report['coverage_complete_count']=100
        atomic_json(self.root/'latest.json',{'as_of':'2026-10-12','marker':'previous'})
        a,b,c,d,e=self.providers()
        with a,b,c,d as render,e as repository:
            repository.return_value.report={'coverage_complete_count':0}
            result=self.manager.run(now=NOW)
            self.assertEqual(result['status'],'RETRY');render.assert_not_called()
        self.assertEqual(json.loads((self.root/'latest.json').read_text())['marker'],'previous')

    def test_holiday_uses_observed_session_and_skips_same_report(self):
        with patch('screenerx.production.latest_session',return_value=(date(2026,10,12),{})),patch('screenerx.market.run') as market:
            self.assertEqual(self.manager.run(now=NOW)['status'],'SKIPPED')
            market.assert_not_called()
        self.assertFalse((self.root/'latest.json').exists())

    def test_failed_cloud_publication_does_not_switch_bot(self):
        self.manager.publish_url='https://example.invalid/internal/bundle'; self.manager.secret='test'
        a,b,c,d,e=self.providers()
        with a,b,c,d,e,patch('screenerx.refresh_bundle.build_bundle'),patch('screenerx.refresh_bundle.publish_bundle',side_effect=ValueError('Cloud unavailable')):
            self.assertEqual(self.manager.run(now=NOW)['status'],'RETRY')
        self.assertFalse((self.root/'latest.json').exists()); self.callback.assert_not_called()

    def test_live_lease_prevents_duplicate_provider_calls(self):
        import time
        self.store.query('INSERT INTO sx_refresh_jobs(request_date,status,lease_until) VALUES (?,?,?)',('2026-10-13','RUNNING',time.time()+300))
        with patch('screenerx.production.latest_session') as session:
            self.assertEqual(self.manager.run(now=NOW)['status'],'ALREADY_HANDLED')
            session.assert_not_called()

    def test_corrupt_latest_pointer_is_not_loaded(self):
        (self.root/'report.json').write_text('bad'); (self.root/'prices.csv').write_text('bad')
        (self.root/'core-run.json').write_text('bad')
        atomic_json(self.root/'latest.json',{'as_of':'2026-10-13','run_dir':str(self.root),'prices':str(self.root/'prices.csv'),
                    'report_sha256':'wrong','prices_sha256':'wrong'})
        with self.assertRaises(InputError): load_latest(self.repository,self.root/'latest.json')

    def test_publication_rejects_stale_prices_wrong_date_and_partial_coverage_collapse(self):
        previous={'coverage_complete_count':100}
        good={'as_of':'2026-10-13','coverage_complete_count':101,'selected_count':0}
        prices={'universe_count':100,'current_price_count':90,'price_count':100}
        session=date(2026,10,13)
        self.assertTrue(publication_checks(previous,good,prices,session)['passed'])
        for report,counts in [({**good,'as_of':'2026-10-12'},prices),
                              ({**good,'coverage_complete_count':49},prices),
                              (good,{**prices,'current_price_count':79})]:
            self.assertFalse(publication_checks(previous,report,counts,session)['passed'])

    def test_rejected_candidate_retries_then_publishes_without_manual_rebuild(self):
        self.repository.report['coverage_complete_count']=100
        a,b,c,d,e=self.providers()
        with a,b as market,c,d,e as repository:
            repository.return_value.report={'as_of':'2026-10-13','coverage_complete_count':1}
            self.assertEqual(self.manager.run(now=NOW)['status'],'RETRY')
            self.assertFalse(self.manager.pointer.exists())
            self.store.query('UPDATE sx_refresh_jobs SET next_at=0')
            repository.return_value.report={'as_of':'2026-10-13','coverage_complete_count':101}
            result=self.manager.run(now=NOW)
            self.assertEqual(result['status'],'PUBLISHED')
            self.assertEqual(market.call_count,2)
            self.assertEqual(self.store.query('SELECT attempts FROM sx_refresh_jobs',fetch=True)[0]['attempts'],2)

    def test_three_bad_attempts_stop_and_preserve_healthy_publication(self):
        atomic_json(self.manager.pointer,{'as_of':'2026-10-12'})
        a,b,c,d,e=self.providers()
        with a,b,c,d,e as repository:
            repository.return_value.report={'as_of':'2026-10-13','coverage_complete_count':0}
            self.repository.report['coverage_complete_count']=100
            for expected in ['RETRY','RETRY','FAILED']:
                self.assertEqual(self.manager.run(now=NOW)['status'],expected)
                self.store.query('UPDATE sx_refresh_jobs SET next_at=0')
            self.assertEqual(self.manager.run(now=NOW)['status'],'ALREADY_HANDLED')
        self.assertEqual(json.loads(self.manager.pointer.read_text())['as_of'],'2026-10-12')
        self.callback.assert_not_called()
