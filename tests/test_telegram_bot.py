import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import MagicMock,patch
from http.server import ThreadingHTTPServer
from urllib.request import Request,urlopen
from urllib.error import HTTPError

from screenerx.bot_store import BotStore
from screenerx.reporting import narrative,recommendation
from screenerx.telegram_bot import ResearchBot,TelegramClient,DeliveryError,authorized,chunks,handler


def update(uid=1,text='/help',user=7,chat=-8):
    return {'update_id':uid,'message':{'text':text,'from':{'id':user},'chat':{'id':chat}}}


class TelegramTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.store=BotStore(Path(self.temp.name)/'state.sqlite')
        self.client=MagicMock(); self.client.send.return_value={'message_id':123}
        self.bot=ResearchBot(MagicMock(),self.store,self.client,{'7'},{'-8'},self.temp.name)
        self.bot.prepare=lambda text:[{'kind':'text','text':'First'},{'kind':'text','text':'Second'}]
    def tearDown(self): self.temp.cleanup()

    def test_private_access_requires_both_user_and_chat(self):
        self.assertTrue(authorized(update(),{'7'},{'-8'}))
        for item in (update(user=9),update(chat=9),{}, {'update_id':True},update(uid='1')):
            self.assertFalse(authorized(item,{'7'},{'-8'}))
        self.assertFalse(self.bot.accept(update(user=9)))
        self.assertEqual(self.store.counts(),{})

    def test_open_group_allows_members_only_in_configured_group(self):
        group=update(user=99,chat=-100777000123)
        group['message']['chat']['type']='supergroup'
        groups={'-100777000123'}
        self.assertTrue(authorized(group,{'7'},{'-8'},groups))
        self.assertFalse(authorized(update(user=99,chat=-100777000123),{'7'},{'-8'},groups))
        group['message']['chat']['id']=-100111
        self.assertFalse(authorized(group,{'7'},{'-8'},groups))
        self.assertFalse(authorized(update(user=99,chat=99),{'7'},{'-8'},groups))

    def test_authenticated_access_reload_preserves_private_access(self):
        group=update(user=99,chat=-100777000123)
        group['message']['chat']['type']='supergroup'
        self.assertFalse(self.bot.accept(group))
        server=ThreadingHTTPServer(('127.0.0.1',0),handler(self.bot,'engine-secret','webhook-secret'))
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        url=f'http://127.0.0.1:{server.server_port}/internal/access'
        settings={'users':'7','chats':'-8','groups':'-100777000123'}
        try:
            with self.assertRaises(HTTPError) as error:
                urlopen(Request(url,data=json.dumps(settings).encode()))
            self.assertEqual(error.exception.code,403)
            self.assertEqual(self.bot.open_groups,set())
            response=urlopen(Request(url,data=json.dumps(settings).encode(),headers={'Authorization':'Bearer engine-secret'}))
            self.assertEqual(json.load(response)['open_group_count'],1)
            self.assertTrue(self.bot.accept(group))
            self.assertTrue(authorized(update(),self.bot.users,self.bot.chats,self.bot.open_groups))
            self.assertFalse(authorized(update(user=99,chat=99),self.bot.users,self.bot.chats,self.bot.open_groups))
            self.client.send.assert_not_called()
        finally: server.shutdown();server.server_close();thread.join()

    def test_forum_replies_keep_topic_in_durable_outbox_and_all_media(self):
        item=update(user=99,chat=-100777000123)
        item['message']['chat']['type']='supergroup';item['message']['message_thread_id']=2
        self.bot.open_groups={'-100777000123'}
        self.assertTrue(self.bot.accept(item));self.assertEqual(self.bot.process(1),'DONE')
        for row in self.store.parts(1):
            self.assertEqual(json.loads(row['payload'])['message_thread_id'],2)
        client=TelegramClient.__new__(TelegramClient);client.request=MagicMock(return_value={})
        for kind in ('text','photo','document'):
            path=Path(self.temp.name)/'test.png';path.write_bytes(b'test')
            client._send(-100777000123,{'kind':kind,'text':'test','path':str(path),'message_thread_id':2})
            self.assertEqual(client.request.call_args.args[1]['message_thread_id'],2)

    def test_ordinary_group_conversation_is_acknowledged_without_bot_replies(self):
        item=update(user=99,chat=-100777000123,text='ordinary conversation')
        item['message']['chat']['type']='supergroup';self.bot.open_groups={'-100777000123'}
        self.assertTrue(self.bot.accept(item));self.assertEqual(self.store.counts(),{})
        self.store.accept(item)
        self.assertEqual(self.bot.process(1),'DONE');self.client.send.assert_not_called()

    def test_duplicate_update_never_resends_sent_parts(self):
        self.assertTrue(self.bot.accept(update()))
        self.assertEqual(self.bot.process(1),'DONE')
        self.bot.accept(update())
        self.assertEqual(self.bot.process(1),'DONE')
        self.assertEqual(self.client.send.call_count,2)
        self.assertEqual(self.store.counts(),{'DONE':1})

    def test_rate_limit_preserves_already_delivered_message(self):
        self.client.send.side_effect=[{'message_id':1},DeliveryError('429',retry_after=30)]
        self.bot.accept(update()); self.assertEqual(self.bot.process(1),'RETRY')
        self.assertEqual([r['status'] for r in self.store.parts(1)],['SENT','PENDING'])
        self.assertIsNone(self.store.claim(1))
        self.store.query('UPDATE sx_bot_updates SET next_at=0 WHERE update_id=1')
        self.client.send.side_effect=None
        self.assertEqual(self.bot.process(1),'DONE')
        self.assertEqual(self.client.send.call_count,3)

    def test_ambiguous_delivery_is_not_automatically_resent(self):
        self.client.send.side_effect=DeliveryError('timeout',uncertain=True)
        self.bot.accept(update()); self.assertEqual(self.bot.process(1),'UNCERTAIN')
        self.assertEqual(self.bot.process(1),'UNCERTAIN')
        self.assertEqual(self.client.send.call_count,2)

    def test_crash_during_send_retains_uncertain_state(self):
        self.bot.accept(update()); self.store.claim(1)
        self.store.stage(1,[{'kind':'text','text':'test'}]); self.store.begin_send(1,0)
        self.store.query('UPDATE sx_bot_updates SET lease_until=0 WHERE update_id=1')
        self.assertEqual(self.bot.process(1),'UNCERTAIN')
        self.assertEqual(self.store.parts(1)[0]['status'],'UNCERTAIN')

    def test_chunks_respect_telegram_message_limit(self):
        for text in ('x'*9000, 'a\n\n'+'b'*3800+'\n\nccc'):
            self.assertTrue(all(0<len(part)<=3800 for part in chunks(text)))

    def test_retry_limit_preserves_completed_jobs(self):
        self.bot.accept(update())
        self.store.query("UPDATE sx_bot_updates SET attempts=8,status='DONE' WHERE update_id=1")
        self.assertIsNone(self.store.claim(1))
        self.assertEqual(self.store.counts(),{'DONE':1})
        self.bot.accept(update(uid=2))
        self.store.query("UPDATE sx_bot_updates SET attempts=8,status='RETRY' WHERE update_id=2")
        self.assertIsNone(self.store.claim(2))
        self.assertEqual(self.store.counts(),{'DONE':1,'FAILED':1})

    def test_webhook_requires_secret_and_persists_before_ack(self):
        server=ThreadingHTTPServer(('127.0.0.1',0),handler(self.bot,'engine-secret','webhook-secret'))
        thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
        url=f'http://127.0.0.1:{server.server_port}/telegram/webhook'
        try:
            with self.assertRaises(HTTPError) as error:
                urlopen(Request(url,data=json.dumps(update()).encode(),method='POST'))
            self.assertEqual(error.exception.code,403)
            response=urlopen(Request(url,data=json.dumps(update()).encode(),headers={'X-Telegram-Bot-Api-Secret-Token':'webhook-secret'}))
            self.assertEqual(response.status,200)
            self.assertEqual(self.store.counts(),{'PENDING':1})
            self.client.send.assert_not_called()
        finally: server.shutdown(); server.server_close(); thread.join()

    def test_recommendation_obeys_coverage_and_execution_checks(self):
        base={'ticker':'TEST','as_of':'2026-10-12','coverage_complete':False,'technical':{'rsi':None}}
        self.assertEqual(recommendation(base)[0],'DATA BELUM LENGKAP')
        self.assertIn('ON_HOLD',narrative(base)['text'])
        base.update(coverage_complete=True,quality_passed=True,plan={'net_rr':2.5},execution_readiness={'reward_risk_passed':False})
        self.assertEqual(recommendation(base)[0],'TUNGGU SETUP BARU')

    def test_each_analysis_command_attaches_standalone_chart(self):
        company={'ticker':'TEST','as_of':'2026-10-12','coverage_complete':False,'technical':None}
        repository=MagicMock()
        repository.report={'input_files':{},'config_sha256':'abc','as_of':'2026-10-12'}
        repository.company.return_value=company
        bot=ResearchBot(repository,self.store,self.client,{'7'},{'-8'},self.temp.name)
        assets={'chart':Path(self.temp.name)/'TEST-chart.png','png':Path(self.temp.name)/'TEST-full.png',
                'pdf':Path(self.temp.name)/'TEST.pdf','text':'analysis'}
        with patch('screenerx.telegram_bot.render_stock',return_value=assets):
            for command in ('/stock TEST','/chart TEST','/valuation TEST','/report TEST'):
                with self.subTest(command=command):
                    result=bot.prepare(command)
                    self.assertEqual(result[0]['kind'],'photo')
                    self.assertEqual(result[0]['path'],str(assets['chart']))

    def test_command_modes_scope_renderer_and_cache(self):
        c={'ticker':'TEST','as_of':'2026-10-12','technical':None}
        repository=MagicMock();repository.report={'input_files':{},'config_sha256':'abc','as_of':'2026-10-12'}
        repository.company.return_value=c
        bot=ResearchBot(repository,self.store,self.client,{'7'},{'-8'},self.temp.name)
        assets={'chart':Path(self.temp.name)/'chart.png','pdf':Path(self.temp.name)/'report.pdf'}
        with patch('screenerx.telegram_bot.render_stock',return_value=assets) as render:
            paths=[]
            for command,modes in [('/technical@ScreenX_idxbot TEST',('technical',)),('/fundamental TEST',('fundamental',)),('/broker TEST',('broker',)),('/stock TEST technical+broker',('technical','broker'))]:
                result=bot.prepare(command)
                self.assertEqual(render.call_args.args[0]['_analysis_modes'],modes)
                self.assertEqual(result[0]['kind'],'photo');self.assertGreater(len(result),1)
                paths.append(render.call_args.args[2])
            self.assertEqual(len(set(paths)),4)
            repository.bars.reset_mock();repository.company.reset_mock()
            bot.prepare('/fundamental TEST');repository.bars.assert_not_called()
            repository.company.reset_mock()
            bot.prepare('/broker TEST');repository.bars.assert_not_called();repository.company.assert_not_called()

    def test_top10_attaches_a_chart_and_narrative_for_every_candidate(self):
        repository=MagicMock()
        repository.report={'input_files':{},'config_sha256':'abc','as_of':'2026-10-12','selected_count':2}
        bot=ResearchBot(repository,self.store,self.client,{'7'},{'-8'},self.temp.name)
        assets={'png':'summary.png','text':'summary','analyses':[
            {'ticker':'BBNI','chart':'BBNI-chart.png','label':'WAIT','text':'BBNI narrative'},
            {'ticker':'ACES','chart':'ACES-chart.png','label':'WAIT','text':'ACES narrative'}]}
        with patch('screenerx.telegram_bot.render_top',return_value=assets):
            result=bot.prepare('/top10')
        self.assertEqual([m['path'] for m in result if m['kind']=='photo'],['summary.png','BBNI-chart.png','ACES-chart.png'])
        self.assertIn('BBNI narrative',[m['text'] for m in result if m['kind']=='text'])
        self.assertIn('ACES narrative',[m['text'] for m in result if m['kind']=='text'])

    def test_engine_without_telegram_rejects_updates_without_claiming_jobs(self):
        store=MagicMock()
        bot=ResearchBot(MagicMock(),store,None,{'7'},{'-8'},self.temp.name,delivery_enabled=False)
        update={'update_id':1,'message':{'from':{'id':7},'chat':{'id':-8},'text':'/top10'}}
        self.assertFalse(bot.accept(update))
        self.assertEqual(bot.process(1),'NOT_CONFIGURED')
        store.accept.assert_not_called()
        store.claim.assert_not_called()
