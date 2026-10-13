"""Source/storage adapters and a small API facade around the pure core engine."""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

from .core import CoreEngine, DEFAULT_PROFILE
from .engine import InputError, file_hash, load_config, load_prices, parse_prices
from .fetch import JAKARTA, fetch_yfinance, parse_chart, symbol_for
from .fx import fetch_fx, validate_fx
from .valuation import load_assumptions
from .wsj import fetch_snapshot as fetch_wsj


class DirectoryRepository:
    """The facade only needs these methods; Neon/R2 can implement the same contract."""
    def __init__(self,prices_path=None,snapshot_dir=None,wsj_pages=None,fx_path=None,financial_provider='wsj'):
        if financial_provider not in ('wsj','yfinance'): raise InputError('Unsupported financial provider')
        if wsj_pages and financial_provider!='wsj': raise InputError('WSJ pages require WSJ provider')
        self.financial_provider=financial_provider
        if snapshot_dir and wsj_pages: raise InputError('Choose normalized snapshots or WSJ pages, not both')
        self.prices=load_prices(prices_path) if prices_path else {}
        self.snapshot_dir=Path(snapshot_dir) if snapshot_dir else None
        self.wsj_pages=Path(wsj_pages) if wsj_pages else None
        self.fx={}
        self.input_files=[]
        if prices_path: self.input_files.append(Path(prices_path))
        if fx_path:
            snapshot=json.loads(Path(fx_path).read_text(encoding='utf-8'))
            self.fx[snapshot['base_currency']]=snapshot; self.input_files.append(Path(fx_path))

    def get_prices(self,ticker): return self.prices.get(ticker,[])

    def get_snapshot(self,ticker):
        if self.snapshot_dir:
            path=self.snapshot_dir/f'{ticker}.json'
            if not path.exists(): raise InputError(f'No saved {self.financial_provider} company snapshot for {ticker}')
            snapshot=json.loads(path.read_text(encoding='utf-8')); self.input_files.append(path)
            if not isinstance(snapshot,dict) or not isinstance(snapshot.get('metadata'),dict):
                raise InputError('Malformed saved financial snapshot')
            if snapshot.get('provider')!=self.financial_provider: raise InputError('Company provider differs from configured provider; fallback forbidden')
            if self.financial_provider=='yfinance':
                snapshot['source_evidence']={'provider':'yfinance','symbol':ticker+'.JK','sha256':file_hash(path),'path':str(path.resolve())}
            for source in snapshot.get('source_pages',[]):
                if source.get('path'):
                    evidence=Path(source['path'])
                    if not evidence.exists(): raise InputError('Referenced WSJ evidence file missing')
                    if file_hash(evidence)!=source.get('sha256'): raise InputError('WSJ source evidence hash mismatch')
                    self.input_files.append(evidence)
            return snapshot
        if self.wsj_pages:
            snapshot=fetch_wsj(ticker,self.wsj_pages)
            self.input_files.extend(self.wsj_pages.glob(f'{ticker}-*'))
            return snapshot
        raise InputError('WSJ financial snapshot not supplied; use live lookup to request public WSJ pages')

    def get_fx(self,currency,asof):
        if currency=='IDR': return None
        snapshot=self.fx.get(currency)
        if snapshot is None: raise InputError(f'No saved {currency}/IDR FX snapshot')
        validate_fx(snapshot,currency,asof)
        return snapshot


class CoreService:
    def __init__(self,engine,repository,asof):
        self.engine=engine; self.repository=repository; self.asof=asof

    def lookup(self,ticker,live=False):
        ticker,_=symbol_for(ticker)
        errors=[]; snapshot=None; fx=None
        prices=self.repository.get_prices(ticker)
        if live:
            try:
                payload,_=fetch_yfinance(ticker,self.asof,400)
                raw,quality=parse_chart(payload,ticker,self.asof)
                prices=parse_prices(raw)[ticker]
                self.repository.prices[ticker]=prices
            except (InputError,OSError,ValueError) as exc: errors.append({'source':'prices','reason':str(exc)})
            try:
                # Prefer an explicitly provided WSJ capture; otherwise request WSJ directly.
                try: snapshot=self.repository.get_snapshot(ticker)
                except (InputError,OSError,ValueError):
                    if self.engine.financial_provider=='yfinance':
                        from .valuation import fetch_snapshot
                        snapshot=fetch_snapshot(ticker)
                        from .core import digest
                        snapshot['source_evidence']={'provider':'yfinance','symbol':ticker+'.JK','sha256':digest(snapshot)}
                    else: snapshot=fetch_wsj(ticker)
            except (InputError,OSError,ValueError) as exc: errors.append({'source':self.engine.financial_provider,'reason':str(exc)})
        else:
            try: snapshot=self.repository.get_snapshot(ticker)
            except (InputError,OSError,ValueError) as exc: errors.append({'source':self.engine.financial_provider,'reason':str(exc)})
        if snapshot:
            currency=snapshot.get('metadata',{}).get('financialCurrency')
            try:
                if currency!='IDR': fx=fetch_fx(currency,self.asof) if live else self.repository.get_fx(currency,self.asof)
            except (InputError,OSError,ValueError) as exc: errors.append({'source':'fx','reason':str(exc)})
        report=self.engine.inspect_ticker(ticker,prices,self.asof,snapshot,fx,source_errors=errors)
        report['lookup_status']='AVAILABLE' if report['coverage_complete'] else 'PARTIAL' if prices or snapshot else 'SOURCE_UNAVAILABLE' if live else 'NOT_CACHED'
        report['lookup_mode']='LIVE_REQUEST' if live else 'SAVED_DATA'
        report['in_top10']=None  # Membership needs an explicit ranked universe/run.
        report['ranking_context']='UNRANKED_SINGLE_TICKER'
        report['lookup_note']='Lookup is independent of shortlist membership; available evidence is returned even when coverage fails.'
        return report

    def screen(self,universe):
        snapshots={}; fx={}; errors={}; prices={}
        for ticker in universe:
            ticker,_=symbol_for(ticker); prices[ticker]=self.repository.get_prices(ticker)
            try:
                snapshots[ticker]=self.repository.get_snapshot(ticker)
                currency=snapshots[ticker].get('metadata',{}).get('financialCurrency')
                if currency!='IDR': fx[currency]=self.repository.get_fx(currency,self.asof)
            except (InputError,OSError,ValueError) as exc: errors[ticker]=[{'source':self.engine.financial_provider+'_or_fx','reason':str(exc)}]
        report=self.engine.screen(universe,prices,snapshots,self.asof,fx,source_errors=errors)
        report['input_files']={str(path.resolve()):file_hash(path) for path in set(self.repository.input_files) if path.is_file()}
        return report


def build_service(prices_path,asof,snapshot_dir=None,wsj_pages=None,fx_path=None,
                  config_path=None,valuation_path=None,profile_path=None,financial_provider='wsj'):
    root=Path(__file__).parent.parent
    config=load_config(config_path or root/'config.json')
    valuation=load_assumptions(valuation_path or root/'valuation-config.json')
    profile=json.loads(Path(profile_path or root/'core-config.json').read_text(encoding='utf-8'))
    if financial_provider=='yfinance' and not profile_path:
        profile['profile_name']='yfinance_covered_research_v1'
    return CoreService(CoreEngine(config,valuation,profile,financial_provider),DirectoryRepository(prices_path,snapshot_dir,wsj_pages,fx_path,financial_provider),asof)


def completed_cutoff():
    now=datetime.now(JAKARTA)
    return now.date() if now.hour>=18 else now.date()-timedelta(days=1)
