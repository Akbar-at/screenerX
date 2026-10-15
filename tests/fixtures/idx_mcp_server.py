"""Offline stdio protocol fixture, never used as a market-data provider."""
from mcp.server.fastmcp import FastMCP

server=FastMCP('idx-bridge-test')

@server.tool()
def get_quotes(symbols:list[str])->dict:
    return {'data':{'symbols':symbols,'fixture':True},'source':'test-only','fetched_at':'2026-10-15','stale':True}

@server.tool()
def get_company(symbol:str,sections:list[str])->dict:
    raise ValueError('Private provider error must not be exposed')

if __name__=='__main__':server.run(transport='stdio')
