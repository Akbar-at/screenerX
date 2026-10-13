import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock,patch

import httpx

from screenerx.agent import OpenRouterAgent,ResearchTools,AgentError,prepare_agent
from screenerx.telegram_bot import ResearchBot
from tests.test_reporting_tables import company


def response(message): return {'choices':[{'message':{'role':'assistant',**message}}]}
def call(name='get_coverage',arguments='{}'):
    return {'id':'call1','type':'function','function':{'name':name,'arguments':arguments}}


class AgentTests(unittest.TestCase):
    def test_production_configuration_enforces_low_cost_provider_ceiling(self):
        with patch.dict(os.environ,{'OPENROUTER_API_KEY':'key','OPENROUTER_MODEL':'z-ai/glm-4.7-flash','AGENT_REASONING_ENABLED':'false'}):
            agent=OpenRouterAgent.from_env()
        self.assertEqual(agent.max_price,{'prompt':.10,'completion':.50,'request':0})
        self.assertFalse(agent.reasoning)
        def transport(request):
            self.assertEqual(json.loads(request.content)['provider']['max_price'],agent.max_price)
            return httpx.Response(200,json=response({'content':'Ready.'}))
        agent.client.close();agent.owns_client=False
        with httpx.Client(transport=httpx.MockTransport(transport)) as client:
            agent.client=client;self.assertEqual(agent.run('hello',MagicMock()),'Ready.')

    def test_reasoning_can_be_disabled_for_compatible_models(self):
        def transport(request):
            self.assertEqual(json.loads(request.content)['reasoning'],{'enabled':False})
            return httpx.Response(200,json=response({'content':'Done.'}))
        with httpx.Client(transport=httpx.MockTransport(transport)) as client:
            self.assertEqual(OpenRouterAgent('key','model',client=client,reasoning=False).run('Hello',MagicMock()),'Done.')

    def test_truncated_output_is_not_accepted_as_a_complete_answer(self):
        data=response({'content':'Incomplete sentence'});data['choices'][0]['finish_reason']='length'
        with httpx.Client(transport=httpx.MockTransport(lambda req:httpx.Response(200,json=data))) as client:
            with self.assertRaises(AgentError):OpenRouterAgent('key','model',client=client).run('Hello',MagicMock())

    def test_tool_round_trip_preserves_id_and_request_schema(self):
        requests=[]
        def transport(request):
            payload=json.loads(request.content);requests.append(payload)
            self.assertEqual(request.headers['Authorization'],'Bearer test-secret')
            if len(requests)==1: return httpx.Response(200,json=response({'content':None,'tool_calls':[call()],
                'reasoning_details':[{'type':'reasoning.encrypted','data':'opaque-provider-context'}]}))
            self.assertEqual(payload['messages'][-1]['role'],'tool')
            self.assertEqual(payload['messages'][-1]['tool_call_id'],'call1')
            self.assertEqual(payload['messages'][-2]['reasoning_details'][0]['data'],'opaque-provider-context')
            self.assertEqual(json.loads(payload['messages'][-1]['content']),{'as_of':'2026-10-12'})
            return httpx.Response(200,json=response({'content':'Coverage from stored data.'}))
        tools=MagicMock();tools.call.return_value={'as_of':'2026-10-12'}
        with httpx.Client(transport=httpx.MockTransport(transport)) as client:
            result=OpenRouterAgent('test-secret','test/model',client=client).run('Check coverage',tools)
        self.assertEqual(result,'Coverage from stored data.')
        tools.call.assert_called_once_with('get_coverage',{})
        self.assertTrue(requests[0]['tools']);self.assertNotIn('parallel_tool_calls',requests[0])
        self.assertNotIn('test-secret',json.dumps(requests))

    def test_provider_errors_are_sanitized_and_not_retried(self):
        for status,body in [(401,{'error':'test-secret'}),(200,{'choices':[]})]:
            requests=[]
            def transport(request):requests.append(request);return httpx.Response(status,json=body)
            with httpx.Client(transport=httpx.MockTransport(transport)) as client:
                with self.assertRaises(AgentError) as error:
                    OpenRouterAgent('test-secret','test/model',client=client).run('hello',MagicMock())
            self.assertNotIn('test-secret',str(error.exception));self.assertEqual(len(requests),1)

    def test_tool_and_round_limits_stop_runaway_model(self):
        with httpx.Client(transport=httpx.MockTransport(lambda req:httpx.Response(200,json=response({'tool_calls':[call()]})))) as client:
            tools=MagicMock();tools.call.return_value={}
            with self.assertRaises(AgentError):OpenRouterAgent('key','model',client=client,max_rounds=2,max_calls=1).run('hello',tools)
            self.assertEqual(tools.call.call_count,1)

    def test_bad_arguments_return_tool_error_for_model_to_recover(self):
        steps=[]
        def transport(request):
            data=json.loads(request.content);steps.append(data)
            if len(steps)==1:return httpx.Response(200,json=response({'tool_calls':[call(arguments='not-json')]}))
            self.assertIn('error',json.loads(data['messages'][-1]['content']))
            return httpx.Response(200,json=response({'content':'Please specify a ticker.'}))
        with httpx.Client(transport=httpx.MockTransport(transport)) as client:
            tools=MagicMock();OpenRouterAgent('key','model',client=client).run('hi',tools);tools.call.assert_not_called()

    def test_tools_allow_only_research_and_preserve_original_reports(self):
        bot=MagicMock();c=company();bot.repository.company.return_value=c
        bot.repository.report={'as_of':c['as_of'],'top10':[c],'unfilled_slots':9}
        bot.prepare.return_value=[{'kind':'photo','path':'original-chart.png'},{'kind':'text','text':'original facts'}]
        host=ResearchTools(bot)
        result=host.call('analyze_stock',{'ticker':'TEST','modes':['technical'],'output':'analysis'})
        self.assertEqual(result['components']['technical']['status'],'AVAILABLE')
        self.assertNotIn('DDM',str(result['tables']));self.assertEqual(host.attachments,bot.prepare.return_value)
        host.call('analyze_stock',{'ticker':'TEST','modes':['technical']});self.assertEqual(bot.prepare.call_count,1)
        for name,args in [('execute_trade',{}),('get_status',{'key':'secret'}),('analyze_stock',{'ticker':'TEST; /report','modes':['technical']}),('analyze_stock',{'ticker':'TEST','modes':['unknown']})]:
            with self.assertRaises(ValueError):host.call(name,args)
        self.assertEqual(host.call('get_status',{})['broker_flow'],'ON_HOLD')

    def test_broker_tool_needs_no_financial_or_price_data(self):
        bot=MagicMock();bot.repository.report={'as_of':'2026-10-12'};bot.prepare.return_value=[{'kind':'photo','path':'broker.png'}]
        result=ResearchTools(bot).call('analyze_stock',{'ticker':'TEST','modes':['broker']})
        self.assertEqual(result['components']['broker']['status'],'ON_HOLD');bot.repository.company.assert_not_called()

    def test_tool_snapshot_is_stable_across_refresh(self):
        from types import SimpleNamespace
        bot=SimpleNamespace(repository=SimpleNamespace(report={'as_of':'2026-10-12'}))
        host=ResearchTools(bot);bot.repository=SimpleNamespace(report={'as_of':'2026-10-13'})
        self.assertEqual(host.call('get_status',{})['as_of'],'2026-10-12')

    def test_partial_reports_survive_provider_failure(self):
        bot=MagicMock()
        def run(prompt,tools):tools.attachments.append({'kind':'photo','path':'chart.png'});raise AgentError('Provider unavailable')
        with patch('screenerx.agent.OpenRouterAgent.from_env') as build:
            build.return_value.run.side_effect=run
            parts=prepare_agent(bot,'Analyze TEST')
        self.assertEqual(parts[0]['kind'],'photo');self.assertIn('Provider unavailable',parts[-1]['text'])

    def test_agent_is_opt_in_and_deterministic_commands_do_not_call_model(self):
        repository=MagicMock();repository.report={'input_files':{},'config_sha256':'abc','as_of':'2026-10-12'}
        with tempfile.TemporaryDirectory() as directory:
            bot=ResearchBot(repository,MagicMock(),MagicMock(),{'7'},{'8'},directory)
            with patch.dict(os.environ,{'BOT_AGENT_ENABLED':'false'}),patch('screenerx.agent.prepare_agent') as run:
                self.assertIn('belum diaktifkan',bot.prepare('/ask Test')[0]['text']);run.assert_not_called()
            with patch.dict(os.environ,{'BOT_AGENT_ENABLED':'true'}),patch('screenerx.agent.prepare_agent',return_value=[{'kind':'text','text':'agent'}]) as run:
                self.assertEqual(bot.prepare('/ask@ScreenX_idxbot Compare BBCA BMRI')[0]['text'],'agent')
                run.assert_called_once_with(bot,'Compare BBCA BMRI');run.reset_mock()
                bot.prepare('/help');run.assert_not_called()
                bot.prepare('Explain dividends');run.assert_called_once_with(bot,'Explain dividends')
