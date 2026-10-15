"""Allowlisted idx-mcp bridge. Child processes receive no application secrets."""
import asyncio
import json
import os
import subprocess
import threading
import time
from functools import lru_cache
from pathlib import Path

from .fetch import symbol_for

OPERATIONS={
    'quotes':('get_quotes',{'symbols'}),
    'company':('get_company',{'ticker','sections'}),
    'shareholders':('get_shareholders',{'ticker'}),
    'ownership_changes':('get_ownership_changes',{'ticker','from','to','limit'}),
    'investor_holdings':('get_investor_holdings',{'entity'}),
    'search_investors':('search_investors',{'query','limit'}),
    'ownership_status':('ownership_status',set()),
}
OWNERSHIP={'shareholders','ownership_changes','investor_holdings','search_investors','ownership_status'}
SECTIONS={'profile','financials','earnings','news'}


def reference_only_financials(result):
    """Do not give the LLM mixed-scale raw accounting values as normalized facts."""
    if not isinstance(result,dict) or not isinstance(result.get('financials'),dict):return result
    import copy
    result=copy.deepcopy(result);section=result['financials'];data=section.get('data')
    if not isinstance(data,dict):return result
    statements={}
    for name in ('balance_sheet','income_statement','cash_flow'):
        value=data.get(name)
        if isinstance(value,dict):
            statements[name]={k:value.get(k) for k in ('currency','report_date','end_date')}
    section['data']={'instrument':data.get('instrument'),'statements':statements,
        'status':'UNVALIDATED_STATEMENT_UNITS_AND_PERIODS',
        'reason':'Raw values withheld: upstream mixes monetary scales and does not establish aligned annual periods. Use stored yfinance analysis for numerical fundamentals and valuations.'}
    return result


def arguments(operation,values):
    if operation not in OPERATIONS or not isinstance(values,dict):raise ValueError('Unsupported MCP operation')
    name,allowed=OPERATIONS[operation]
    if set(values)-allowed:raise ValueError('Unexpected MCP arguments')
    result=dict(values)
    if 'ticker' in result:
        if not isinstance(result['ticker'],str):raise ValueError('Ticker must be a string')
        result['ticker']=symbol_for(result['ticker'])[0]
    if operation in ('company','shareholders') and 'ticker' not in result:raise ValueError('Ticker required')
    if operation=='company':
        result['symbol']=result.pop('ticker')
        sections=result.get('sections',['profile','financials'])
        if not isinstance(sections,list) or not sections or any(x not in SECTIONS for x in sections):raise ValueError('Invalid company sections')
        result['sections']=list(dict.fromkeys(sections))
    if operation=='quotes':
        symbols=result.get('symbols')
        if not isinstance(symbols,list) or not 1<=len(symbols)<=20:raise ValueError('Request 1-20 tickers')
        if any(not isinstance(x,str) for x in symbols):raise ValueError('Tickers must be strings')
        result['symbols']=[symbol_for(x)[0] for x in symbols]
    if operation=='ownership_changes':
        from .engine import day
        for key in ('from','to'):day(result.get(key),key)
        if result['from']>=result['to']:raise ValueError('Ownership dates must increase')
    if operation in ('investor_holdings','search_investors'):
        key='entity' if operation=='investor_holdings' else 'query'
        if not isinstance(result.get(key),str) or not 1<=len(result[key].strip())<=120:raise ValueError('Search text required')
    if 'limit' in result and (type(result['limit']) is not int or not 1<=result['limit']<=50):raise ValueError('Limit must be 1-50')
    if operation in ('search_investors','ownership_changes'):result.setdefault('limit',20)
    return name,result


class IDXMCP:
    def __init__(self,root=None,command='idx-mcp',cli='idx',timeout=65,server_args=()):
        self.root=Path(root or os.getenv('BOT_MCP_CACHE','/tmp/screenerx-mcp'))
        self.command=command;self.cli=cli;self.timeout=timeout
        self.server_args=list(server_args)
        self.sync_lock=threading.Lock();self.slots=threading.BoundedSemaphore(2)
        self.last_sync_attempt=0;self.sync_status='NOT_CHECKED'

    def environment(self):
        env={key:os.environ[key] for key in ('PATH','SYSTEMROOT','TEMP','TMP','SSL_CERT_FILE','SSL_CERT_DIR',
            'HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','NO_PROXY','LANG') if key in os.environ}
        env.update(XDG_CONFIG_HOME=str(self.root/'config'),XDG_DATA_HOME=str(self.root/'data'),
                   XDG_CACHE_HOME=str(self.root/'cache'),IDX_PROVIDER='msn',IDX_HISTORY_PROVIDER='yahoo')
        return env

    def sync_ownership(self):
        # This maintenance operation is never exposed to the LLM.
        with self.sync_lock:
            now=time.monotonic()
            cooldown=86400 if self.sync_status=='CURRENT' else 900
            if self.last_sync_attempt and now-self.last_sync_attempt<cooldown:return self.sync_status
            self.last_sync_attempt=now
            try:
                result=subprocess.run([self.cli,'ownership','sync'],env=self.environment(),
                    timeout=45,capture_output=True,check=False)
                self.sync_status='CURRENT' if result.returncode==0 else 'REFRESH_FAILED_USING_EXISTING_IF_AVAILABLE'
            except (OSError,subprocess.SubprocessError):self.sync_status='REFRESH_FAILED_USING_EXISTING_IF_AVAILABLE'
            return self.sync_status

    async def _call(self,name,args):
        from mcp import ClientSession,StdioServerParameters
        from mcp.client.stdio import stdio_client
        # Never inherit DATABASE_URL, Telegram/OpenRouter keys, or engine secrets.
        params=StdioServerParameters(command=self.command,args=self.server_args,env=self.environment())
        async with asyncio.timeout(self.timeout):
            with open(os.devnull,'w') as errors:
                async with stdio_client(params,errlog=errors) as (read,write):
                    async with ClientSession(read,write) as session:
                        await session.initialize()
                        result=await session.call_tool(name,args)
                        if result.isError:raise ValueError('MCP source unavailable or request unsupported')
                        data=result.structuredContent
                        if data is None:
                            texts=[part.text for part in result.content if getattr(part,'type',None)=='text']
                            data=json.loads('\n'.join(texts))
                        if len(json.dumps(data).encode())>60000:raise ValueError('MCP response too large; request fewer sections or rows')
                        return data

    def call(self,operation,values):
        name,args=arguments(operation,values)
        if not self.slots.acquire(timeout=5):raise ValueError('MCP is busy; retry later')
        try:
            if operation in OWNERSHIP:self.sync_ownership()
            try:data=asyncio.run(self._call(name,args))
            except Exception as exc:raise ValueError('IDX MCP data unavailable; stored analysis remains available') from exc
            if operation=='company':data=reference_only_financials(data)
            return {'provider':'idx-mcp','operation':operation,'result':data,
                'ownership_refresh':self.sync_status if operation in OWNERSHIP else None,
                'limitations':['Ownership is monthly holders above 1%, not daily broker flow.',
                    'Ownership *_bps fields are basis points; divide by 100 when formatting percent.',
                    'Quotes may be delayed; do not describe them as a guaranteed real-time executable price.',
                    'Below-1% ownership remainder is not verified regulatory free float.',
                    'MSN data is supplementary; it does not replace reviewed valuation inputs or genuine OHLCV.',
                    'Use source/as-of/fetched_at/stale fields; fetched_at is not the market or statement date.']}
        finally:self.slots.release()


@lru_cache(maxsize=1)
def get_idx_mcp():return IDXMCP()
