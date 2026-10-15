import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch,MagicMock
from screenerx.idx_mcp import IDXMCP,arguments
from screenerx.agent import ResearchTools,active_tools


class IDXMCPTests(unittest.TestCase):
    def test_only_allowlisted_read_operations_and_bounded_arguments(self):
        self.assertEqual(arguments('quotes',{'symbols':['pgeo','BBCA.JK']})[1]['symbols'],['PGEO','BBCA'])
        self.assertEqual(arguments('company',{'ticker':'PGEO','sections':['earnings']})[1],{'symbol':'PGEO','sections':['earnings']})
        for op,args in [('ownership_sync',{}),('quotes',{'symbols':['../secret']}),('quotes',{'symbols':[None]}),
            ('company',{'ticker':'PGEO','url':'https://elsewhere'}),('company',{'ticker':'PGEO','sections':['insights']}),
            ('ownership_changes',{'from':'2026-09-30','to':'2026-08-31'}),('search_investors',{'query':'test','limit':2000})]:
            with self.assertRaises(ValueError):arguments(op,args)

    def test_stdio_handshake_real_sdk_and_stale_metadata_preserved(self):
        fixture=str(Path('tests/fixtures/idx_mcp_server.py').resolve())
        with tempfile.TemporaryDirectory() as root:
            source=IDXMCP(root,command=sys.executable,server_args=[fixture],timeout=60)
            result=source.call('quotes',{'symbols':['PGEO']})
        self.assertTrue(result['result']['stale']);self.assertEqual(result['result']['source'],'test-only')
        self.assertEqual(result['result']['data']['symbols'],['PGEO'])
        self.assertIn('not daily broker flow',' '.join(result['limitations']))

    def test_upstream_tool_errors_are_sanitized(self):
        fixture=str(Path('tests/fixtures/idx_mcp_server.py').resolve())
        with tempfile.TemporaryDirectory() as root:
            source=IDXMCP(root,command=sys.executable,server_args=[fixture],timeout=60)
            with self.assertRaisesRegex(ValueError,'IDX MCP data unavailable') as error:source.call('company',{'ticker':'PGEO'})
        self.assertNotIn('Private provider',str(error.exception))

    def test_child_environment_excludes_application_credentials(self):
        with patch.dict(os.environ,{'OPENROUTER_API_KEY':'hidden','DATABASE_URL':'hidden','ENGINE_SECRET':'hidden','TELEGRAM_BOT_TOKEN':'hidden'}):
            env=IDXMCP().environment()
        self.assertTrue(all(k not in env for k in ('OPENROUTER_API_KEY','DATABASE_URL','ENGINE_SECRET','TELEGRAM_BOT_TOKEN')))
        self.assertEqual(env['IDX_HISTORY_PROVIDER'],'yahoo')

    def test_failed_snapshot_refresh_retains_existing_data_and_backs_off(self):
        source=IDXMCP()
        with patch('screenerx.idx_mcp.subprocess.run',return_value=MagicMock(returncode=4)) as run:
            self.assertEqual(source.sync_ownership(),'REFRESH_FAILED_USING_EXISTING_IF_AVAILABLE')
            source.sync_ownership();self.assertEqual(run.call_count,1)

    def test_agent_gateway_is_feature_gated_and_uses_actual_bridge(self):
        tools=ResearchTools(MagicMock())
        with patch.dict(os.environ,{'BOT_MCP_ENABLED':'false'}):
            self.assertNotIn('get_market_data',[t['function']['name'] for t in active_tools()])
            with self.assertRaises(ValueError):tools.call('get_market_data',{'operation':'quotes','symbols':['PGEO']})
        with patch.dict(os.environ,{'BOT_MCP_ENABLED':'true'}),patch('screenerx.idx_mcp.get_idx_mcp') as source:
            source.return_value.call.return_value={'provider':'idx-mcp'}
            self.assertEqual(tools.call('get_market_data',{'operation':'quotes','symbols':['PGEO']})['provider'],'idx-mcp')
            source.return_value.call.assert_called_once_with('quotes',{'symbols':['PGEO']})
