import base64
import hashlib
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock,patch
from screenerx.engine import InputError
from screenerx.idx_source import IDXSource,validate_payload
from screenerx.idx_reporting import idx_tables,idx_text,render_idx

ASOF=date(2026,10,13)


def stock():
    return {'StockCode':'BMRI','Date':'2026-10-13T00:00:00','Close':3990,'OpenPrice':4000,'High':4010,'Low':3950,
            'Volume':110238300,'Value':437643021000,'Frequency':1000,'ForeignBuy':31820100,'ForeignSell':62064900,
            'Bid':3990,'Offer':4000,'NonRegularVolume':100,'NonRegularValue':1076480,'NonRegularFrequency':1}


def broker():
    return {'IDFirm':'AK','FirmName':'Example broker','Date':'2026-10-13T00:00:00','Value':1000000,'Volume':200,'Frequency':2}


def response(payload,status=200):
    return MagicMock(status_code=status,content=json.dumps(payload).encode())


class IDXSourceTests(unittest.TestCase):
    def setUp(self):self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
    def tearDown(self):self.temp.cleanup()

    def source(self,transport):return IDXSource(self.root,transport=transport,sleep=lambda n:None)

    def test_repo_headers_and_rotation_then_cache_replay(self):
        transport=MagicMock(side_effect=[response({},403),response({'recordsTotal':1,'data':[stock()]})])
        source=self.source(transport);loaded=source.fetch('stocks',ASOF)
        self.assertEqual(loaded['records'][0]['Close'],3990)
        self.assertEqual([c.kwargs['impersonate'] for c in transport.call_args_list],['chrome','chrome124'])
        self.assertIn('accept-language',transport.call_args.kwargs['headers'])
        fresh=self.source(transport);fresh.fetch('stocks',ASOF);self.assertEqual(transport.call_count,2)

    def test_wrong_date_duplicates_partial_and_missing_numeric_fail_closed(self):
        for records,total in [([{**stock(),'Date':'2026-10-12'}],1),([stock(),stock()],2),([stock()],2),([{**stock(),'ForeignBuy':None}],1),([{**stock(),'Value':float('inf')}],1)]:
            with self.assertRaises(InputError):validate_payload('stocks',{'data':records,'recordsTotal':total},ASOF)

    def test_all_rows_validated_not_only_first(self):
        bad={**stock(),'StockCode':'PTSN','Value':-1}
        with self.assertRaises(InputError):validate_payload('stocks',{'data':[stock(),bad]},ASOF)

    def test_pagination_fetches_remaining_records_and_rejects_unknown_total(self):
        pages=[{'data':[{'code':'BMRI','fsDate':'2025-10-31'}],'meta':{'totalItems':2}},
               {'data':[{'code':'BBCA','fsDate':'2025-10-31'}],'meta':{'totalItems':2}}]
        transport=MagicMock(side_effect=[response(p) for p in pages]);loaded=self.source(transport).fetch('ratios',ASOF)
        self.assertEqual(len(loaded['records']),2);self.assertEqual(transport.call_args.kwargs['params']['pageNumber'],2)
        self.assertEqual(transport.call_args.kwargs['params']['periodYear'],2025)
        with self.assertRaises(InputError):validate_payload('ratios',{'data':[{'code':'BMRI'}]},ASOF)

    def test_failure_has_bounded_attempts_and_cooldown(self):
        transport=MagicMock(return_value=response({},403));source=self.source(transport)
        for _ in range(2):
            with self.assertRaises(InputError):source.fetch('stocks',ASOF)
        self.assertEqual(transport.call_count,4)

    def test_cache_hash_and_identity_checked(self):
        source=self.source(MagicMock())
        raw=json.dumps({'recordsTotal':1,'data':[stock()]}).encode()
        envelope={'dataset':'stocks','as_of':ASOF.isoformat(),'raw_base64':base64.b64encode(raw).decode(),'sha256':'bad'}
        with self.assertRaises(InputError):source._decode(envelope,'stocks',ASOF)
        envelope['sha256']=hashlib.sha256(raw).hexdigest();envelope['as_of']='2026-10-12'
        with self.assertRaises(InputError):source._decode(envelope,'stocks',ASOF)

    def test_durable_cache_restores_after_container_restart_without_provider_call(self):
        raw=json.dumps({'data':[stock()]}).encode()
        envelope={'dataset':'stocks','as_of':ASOF.isoformat(),'raw_base64':base64.b64encode(raw).decode(),
                  'sha256':hashlib.sha256(raw).hexdigest()}
        client=MagicMock();client.get.return_value.status_code=200;client.get.return_value.json.return_value=envelope
        transport=MagicMock();source=IDXSource(self.root,archive_url='https://example.invalid/internal/idx-cache',secret='test',transport=transport)
        with patch('screenerx.idx_source.httpx.Client') as factory:
            factory.return_value.__enter__.return_value=client
            loaded=source.fetch('stocks',ASOF)
        self.assertEqual(loaded['records'][0]['Close'],3990);transport.assert_not_called()

    def test_source_evidence_archived_before_success_and_archive_failure_is_explicit(self):
        client=MagicMock();client.get.return_value.status_code=404;client.put.return_value.is_success=False
        source=IDXSource(self.root,archive_url='https://example.invalid/internal/idx-cache',secret='test',
                         transport=MagicMock(return_value=response({'data':[stock()]})),sleep=lambda n:None)
        with patch('screenerx.idx_source.httpx.Client') as factory:
            factory.return_value.__enter__.return_value=client
            with self.assertRaises(InputError):source.fetch('stocks',ASOF)
        client.put.assert_called_once();self.assertFalse((self.root/ASOF.isoformat()/'stocks.json').exists())

    def test_market_broker_totals_never_become_stock_net_flow(self):
        transport=MagicMock(side_effect=[response({'data':[stock()]}),response({'data':[broker()]})])
        data=self.source(transport).stock_metrics('BMRI',ASOF,reference=False)
        self.assertEqual(data['net_foreign_volume'],-30244800)
        self.assertEqual(data['broker_net_status'],'ON_HOLD')
        self.assertNotIn('broker_net_value',data);self.assertAlmostEqual(data['snapshot_spread'],10/3995)
        tables=str(idx_tables(data));self.assertIn('437.643.021.000',tables);self.assertIn('Seluruh bursa',tables)
        self.assertIn('bukan quote live',idx_text(data))

    def test_broker_failure_does_not_hide_valid_stock_metrics(self):
        transport=MagicMock(side_effect=[response({'data':[stock()]})]+[response({},403)]*4)
        data=self.source(transport).stock_metrics('BMRI',ASOF,reference=False)
        self.assertEqual(data['datasets']['stocks']['status'],'AVAILABLE')
        self.assertEqual(data['datasets']['brokers']['status'],'UNAVAILABLE')
        self.assertEqual(data['net_foreign_volume'],-30244800)

    def test_unknown_ticker_never_receives_another_tickers_metrics(self):
        transport=MagicMock(side_effect=[response({'data':[stock()]}),response({'data':[broker()]})])
        data=self.source(transport).stock_metrics('PTSN',ASOF,reference=False)
        self.assertEqual(data['datasets']['stocks']['status'],'TICKER_NOT_FOUND');self.assertIsNone(data['stocks'])
        self.assertNotIn('net_foreign_volume',data)

    def test_numeric_dashboard_contains_real_data_and_generates_files(self):
        transport=MagicMock(side_effect=[response({'data':[stock()]}),response({'data':[broker()]})])
        data=self.source(transport).stock_metrics('BMRI',ASOF,reference=False)
        files=render_idx(data,self.root/'images')
        self.assertGreater(files['chart'].stat().st_size,10000);self.assertTrue(files['pdf'].exists())
        self.assertIn('-30.244.800',files['text']);self.assertIn('ON_HOLD',files['text'])

    def test_telegram_idx_command_uses_source_and_attaches_dashboard(self):
        from screenerx.telegram_bot import ResearchBot
        repository=MagicMock();repository.report={'as_of':ASOF.isoformat(),'input_files':{},'config_sha256':'test'}
        bot=ResearchBot(repository,None,None,set(),set(),self.root/'bot',delivery_enabled=False)
        source=self.source(MagicMock(side_effect=[response({'data':[stock()]}),response({'data':[broker()]})]))
        with patch.dict('os.environ',{'BOT_IDX_ENABLED':'true'}),patch('screenerx.idx_source.get_idx_source',return_value=source):
            parts=bot.prepare('/foreign BMRI')
        self.assertEqual(parts[0]['kind'],'photo');self.assertIn('30.244.800',' '.join(p.get('text','') for p in parts))

