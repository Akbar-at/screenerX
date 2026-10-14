"""Daily closing-session refresh with durable leases and atomic report activation."""
import argparse
import json
import os
import threading
import time
from datetime import datetime,time as clock_time
from pathlib import Path

from .bot_store import BotStore
from .engine import InputError,file_hash
from .fetch import JAKARTA


def due(now=None):
    now=(now or datetime.now(JAKARTA)).astimezone(JAKARTA)
    return now.weekday()<5 and (now.hour,now.minute)>=(7,30)


def atomic_json(path,value):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value,indent=2,allow_nan=False),encoding='utf-8')
    temporary.replace(path)


def publication_checks(previous,fresh,result,session):
    """Validate data coverage, never require a minimum number of buy candidates."""
    universe=result.get('universe_count',0)
    current=result.get('current_price_count',0)
    before=previous.get('coverage_complete_count',0)
    after=fresh.get('coverage_complete_count',0)
    checks={'expected_session':session.isoformat(),'observed_session':fresh.get('as_of'),
            'current_prices':current,'universe_count':universe,
            'previous_complete':before,'candidate_complete':after,
            'minimum_current_price_ratio':.80,'minimum_complete_retention_ratio':.50}
    reasons=[]
    if fresh.get('as_of')!=session.isoformat(): reasons.append('Report session differs from observed completed session')
    if not universe or current/universe<.80: reasons.append('Current-session price coverage below 80%')
    if before>0 and (after==0 or after/before<.50): reasons.append('Complete research coverage fell below 50% of previous healthy run')
    checks.update(passed=not reasons,reasons=reasons)
    return checks


class DailyRefresh:
    def __init__(self,repository,store,state_dir='output/daily-refresh',snapshots=None,fx_snapshot=None,
                 pointer='output/daily-refresh/latest.json',on_publish=None,publish_url=None,secret=None,on_daily_report=None):
        self.repository=repository; self.store=store; self.root=Path(state_dir)
        self.root.mkdir(parents=True,exist_ok=True)
        self.snapshots=Path(snapshots) if snapshots else self.discover_snapshots()
        self.fx=Path(fx_snapshot) if fx_snapshot else None
        self.pointer=Path(pointer); self.on_publish=on_publish
        self.on_daily_report=on_daily_report
        self.publish_url=publish_url; self.secret=secret; self.thread=None; self.lock=threading.Lock()

    def discover_snapshots(self):
        # Existing manifests reference the actual captured financial files.
        for name in self.repository.report.get('input_files',{}):
            path=Path(name)
            if path.parent.name=='raw' and path.suffix=='.json' and path.exists(): return path.parent
        return None

    def start(self,request_date=None):
        with self.lock:
            if self.thread and self.thread.is_alive():
                self.store.query("UPDATE sx_refresh_jobs SET lease_until=? WHERE status='RUNNING' AND request_date=?",(time.time()+300,self.running_date))
                return 'RUNNING'
            date=request_date or datetime.now(JAKARTA).date().isoformat()
            # Validation keeps job keys and paths date-only.
            datetime.strptime(date,'%Y-%m-%d')
            self.running_date=date
            self.thread=threading.Thread(target=self.run,args=(date,),daemon=True)
            self.thread.start(); return 'ACCEPTED'

    def run(self,request_date=None,now=None):
        from .production import latest_session
        from .market import run as market_run
        from .reporting import ReportRepository
        now=(now or datetime.now(JAKARTA)).astimezone(JAKARTA)
        date=request_date or now.date().isoformat()
        requested=datetime.strptime(date,'%Y-%m-%d').date()
        if requested>now.date() or requested==now.date() and not due(now): return {'status':'NOT_DUE'}
        self.store.query('INSERT INTO sx_refresh_jobs(request_date,status) VALUES (?,?) ON CONFLICT(request_date) DO NOTHING',(date,'PENDING'))
        timestamp=time.time()
        rows=self.store.query("UPDATE sx_refresh_jobs SET status='RUNNING',attempts=attempts+1,lease_until=? WHERE request_date=? AND attempts<3 AND ((status IN ('PENDING','RETRY') AND next_at<=?) OR (status='RUNNING' AND lease_until<?)) RETURNING request_date",(timestamp+300,date,timestamp,timestamp),True)
        if not rows: return {'status':'ALREADY_HANDLED'}
        # Renew independently of Worker dispatch, including slow collection/rendering.
        stopped=threading.Event()
        def heartbeat():
            while not stopped.wait(60):
                try:
                    self.store.query("UPDATE sx_refresh_jobs SET lease_until=? WHERE request_date=? AND status='RUNNING'",(time.time()+300,date))
                except Exception:
                    pass  # A transient DB outage must not kill the provider work.
        threading.Thread(target=heartbeat,daemon=True).start()
        checks=None
        try:
            # A delayed/retried morning job must retain its premarket cutoff.
            session,discovery=latest_session(datetime.combine(requested,clock_time(7,30),JAKARTA))
            if session.isoformat()<=self.repository.report['as_of']:
                result={'status':'SKIPPED','reason':'No newer observed completed session','as_of':session.isoformat()}
                if self.on_daily_report: result['telegram_delivery']=self.on_daily_report(self.repository,date)
                self.finish(date,'SKIPPED',result); return result
            if not self.snapshots or not self.snapshots.exists(): raise InputError('Financial snapshots required for daily valuation recalculation')
            folder=self.root/session.isoformat(); folder.mkdir(parents=True,exist_ok=True)
            atomic_json(folder/'session-discovery.json',discovery)
            fx_path=self.fx
            try:
                from .fx import fetch_fx
                fx=fetch_fx('USD',session)
                fx_path=folder/'USDIDR.json'; atomic_json(fx_path,fx)
            except Exception:
                # Cached FX still has to pass the engine's date/age/currency checks.
                pass
            result=market_run(folder/'market',asof=session,workers=2,snapshots=self.snapshots,
                              financial_provider='yfinance',fx_snapshot=fx_path,previous_prices=self.repository.prices_path,retry_failed=True)
            run_dir=Path(result['report_path']).parent; prices=folder/'market/prices.csv'
            fresh=ReportRepository(run_dir,prices)
            checks=publication_checks(self.repository.report,fresh.report,result,session)
            atomic_json(folder/'publication-checks.json',checks)
            if not checks['passed']:
                raise InputError('; '.join(checks['reasons'])+'; previous published run retained')
            from .reporting import render_top
            render_top(fresh,folder/'images')
            if self.publish_url:
                from .refresh_bundle import build_bundle,publish_bundle
                bundle=build_bundle(run_dir,prices,folder/'bundle',self.snapshots,fx_path)
                publish_bundle(bundle,self.publish_url,self.secret)
            pointer={'as_of':session.isoformat(),'run_dir':str(run_dir.resolve()),'prices':str(prices.resolve()),
                     'report_sha256':file_hash(run_dir/'core-run.json'),'prices_sha256':file_hash(prices),
                     'financial_snapshots':str(self.snapshots.resolve()),'fx_snapshot':str(fx_path.resolve()) if fx_path else None}
            atomic_json(self.pointer,pointer)
            self.repository=fresh; self.fx=fx_path
            if self.on_publish: self.on_publish(fresh)
            if self.on_daily_report: result['telegram_delivery']=self.on_daily_report(fresh,date)
            result.update(status='PUBLISHED',latest_pointer=str(self.pointer),publication_checks=checks)
            self.finish(date,'DONE',result); return result
        except Exception as exc:
            attempts=self.store.query('SELECT attempts FROM sx_refresh_jobs WHERE request_date=?',(date,),True)[0]['attempts']
            result={'status':'RETRY' if attempts<3 else 'FAILED','reason':str(exc),
                    'serving_as_of':self.repository.report['as_of'],'publication_checks':checks}
            self.finish(date,result['status'],result,delay=900); return result
        finally:
            stopped.set()

    def finish(self,date,status,result,delay=0):
        self.store.query('UPDATE sx_refresh_jobs SET status=?,lease_until=0,next_at=?,result=? WHERE request_date=?',
                         (status,time.time()+delay,json.dumps(result,allow_nan=False),date))
        atomic_json(self.root/'last-refresh.json',{'request_date':date,**result})


def load_latest(repository,pointer):
    from .reporting import ReportRepository
    path=Path(pointer)
    if not path.exists(): return repository
    data=json.loads(path.read_text(encoding='utf-8'))
    if data['as_of']<=repository.report['as_of']: return repository
    if file_hash(Path(data['run_dir'])/'core-run.json')!=data['report_sha256'] or file_hash(data['prices'])!=data['prices_sha256']:
        raise InputError('Published report checksum mismatch')
    return ReportRepository(data['run_dir'],data['prices'])


def main(argv=None):
    from dotenv import load_dotenv
    from .reporting import ReportRepository
    load_dotenv('.env'); load_dotenv('.env.bot')
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir',default=os.getenv('BOT_RUN_DIR','output/top10-yfinance-latest-2026-10-12/core'))
    parser.add_argument('--prices',default=os.getenv('BOT_PRICES','output/top10-yfinance-latest-2026-10-12/prices.csv'))
    parser.add_argument('--snapshots',default=os.getenv('BOT_FINANCIAL_SNAPSHOTS','output/yfinance-all-2026-10-12/raw'))
    parser.add_argument('--fx-snapshot',default=os.getenv('BOT_FX_SNAPSHOT','output/yfinance-all-2026-10-12/USDIDR.json'))
    parser.add_argument('--state-dir',default='output/daily-refresh'); parser.add_argument('--check',action='store_true')
    args=parser.parse_args(argv)
    if args.check:
        print(json.dumps({'schedule':'07:30 Asia/Jakarta, Monday-Friday','due_now':due(),
                          'snapshots_available':Path(args.snapshots).is_dir(),'prices_available':Path(args.prices).is_file()},indent=2))
        return
    if not due():
        print(json.dumps({'status':'NOT_DUE','schedule':'07:30 Asia/Jakarta, Monday-Friday'}))
        return
    store=BotStore(Path(args.state_dir)/'state.sqlite',os.getenv('DATABASE_URL'))
    pointer=os.getenv('BOT_LATEST_POINTER',str(Path(args.state_dir)/'latest.json'))
    repository=load_latest(ReportRepository(args.run_dir,args.prices),pointer)
    manager=DailyRefresh(repository,store,args.state_dir,args.snapshots,args.fx_snapshot,pointer)
    result=manager.run(); print(json.dumps(result,indent=2))
    if result['status'] in ('RETRY','FAILED'): raise SystemExit(2)


if __name__=='__main__': main()
