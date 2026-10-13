"""Collect yfinance company statements across a saved full universe, then value them."""
import argparse
import json
import shutil
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from .engine import InputError, day, file_hash, write_csv
from .production import read_universe
from .valuation import fetch_snapshot, generate


def collect(ticker, folder, rate_blocked=None):
    path = folder / f'{ticker}.json'
    try:
        if path.exists():
            snapshot = json.loads(path.read_text(encoding='utf-8'))
        else:
            if rate_blocked is not None and rate_blocked.is_set():
                return {'ticker':ticker,'status':'UNAVAILABLE','reason':'Deferred after Yahoo rate limit; resume after cooldown'}
            snapshot = fetch_snapshot(ticker)
            temporary = path.with_suffix('.tmp')
            temporary.write_text(json.dumps(snapshot, indent=2, allow_nan=False), encoding='utf-8')
            temporary.replace(path)
        if snapshot.get('provider') != 'yfinance' or snapshot.get('ticker') != ticker or snapshot.get('symbol') != ticker + '.JK':
            raise InputError('Saved Yahoo financial identity mismatch')
        return {'ticker': ticker, 'status': 'CAPTURED', 'sha256': file_hash(path),
                'statement_errors': snapshot.get('errors', {})}
    except Exception as exc:
        if rate_blocked is not None and 'rate limited' in str(exc).lower():
            rate_blocked.set()
        return {'ticker': ticker, 'status': 'UNAVAILABLE', 'reason': str(exc)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--universe', required=True)
    parser.add_argument('--prices', required=True)
    parser.add_argument('--as-of', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--workers', type=int, choices=range(1, 5), default=3)
    args = parser.parse_args(argv)
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    tickers = read_universe(args.universe)
    if not tickers or len(tickers) != len(set(tickers)):
        raise InputError('Universe must contain unique tickers')
    asof = day(args.as_of, 'as_of')
    from .core_service import completed_cutoff
    if asof > completed_cutoff():
        raise InputError('Session is incomplete or in the future')
    path = output / 'collection.json'
    manifest = {'provider': 'yfinance', 'as_of': asof.isoformat(), 'requested_count': len(tickers),
                'universe_sha256': file_hash(args.universe), 'prices_sha256': file_hash(args.prices),
                'broker_flow_status': 'ON_HOLD', 'status': 'COLLECTING', 'companies': {}}
    if path.exists():
        previous = json.loads(path.read_text(encoding='utf-8'))
        if any(previous[k] != manifest[k] for k in ('provider', 'as_of', 'universe_sha256', 'prices_sha256')):
            raise InputError('Resume inputs differ from original collection')
    def save():
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps(manifest, indent=2, allow_nan=False), encoding='utf-8')
        temporary.replace(path)
    raw = output / 'raw'
    raw.mkdir(exist_ok=True)
    save()
    rate_blocked=threading.Event()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        pending = [pool.submit(collect, ticker, raw, rate_blocked) for ticker in tickers]
        for n, future in enumerate(as_completed(pending), 1):
            audit = future.result()
            manifest['companies'][audit['ticker']] = audit
            if n % 25 == 0 or n == len(tickers):
                save()
                print(f'Yahoo financials assessed: {n}/{len(tickers)}', flush=True)
    fx_path = None
    if any(json.loads(p.read_text(encoding='utf-8'))['metadata'].get('financialCurrency') == 'USD' for p in raw.glob('*.json')):
        try:
            from .fx import fetch_fx
            fx = fetch_fx('USD', asof)
            fx_path = output / 'USDIDR.json'
            fx_path.write_text(json.dumps(fx, indent=2, allow_nan=False), encoding='utf-8')
        except Exception as exc:
            manifest['fx_error'] = str(exc)
    values_path = output / 'valuations'
    if values_path.exists():
        values_path = output / ('valuations-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f'))
    rows, valuation_audit = generate(args.prices, asof, values_path, snapshot_dir=raw,
                                    tickers=tickers, fx_snapshot=fx_path, provider='yfinance', use_reported_tax=True)
    manifest.update(status='ASSESSED', captured_count=sum(a['status'] == 'CAPTURED' for a in manifest['companies'].values()),
                    estimated_count=valuation_audit['estimated_count'], valuations_path=str(values_path),
                    completed_at=datetime.now(timezone.utc).isoformat())
    save()
    shutil.copyfile(values_path / 'estimates.csv', output / 'valuations.csv')
    finish(output, args.prices, args.universe)
    return manifest


def finish(output, prices_path, universe_path):
    """Rank only covered Yahoo estimates; preserve previous exports on replay."""
    from .core_service import build_service
    from .core_cli import export_report
    output=Path(output)
    manifest=json.loads((output/'collection.json').read_text(encoding='utf-8'))
    asof=day(manifest['as_of'],'as_of')
    service=build_service(prices_path,asof,snapshot_dir=output/'raw',
                          fx_path=output/'USDIDR.json' if (output/'USDIDR.json').exists() else None,
                          financial_provider='yfinance')
    report=service.screen(read_universe(universe_path))
    folder=output/'core'
    if folder.exists(): folder=output/('core-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f'))
    export_report(report,folder)
    manifest.update(selected_count=report['selected_count'],coverage_complete_count=report['coverage_complete_count'],
                    qualifying_count=report['qualifying_count'],report_path=str(folder/'report.md'),
                    status='PARTIAL' if manifest['estimated_count']<manifest['requested_count'] else 'COMPLETE')
    manifest['rate_limited_count']=sum('rate limit' in a.get('reason','').lower() for a in manifest['companies'].values())
    (output/'collection.json').write_text(json.dumps(manifest,indent=2,allow_nan=False),encoding='utf-8')
    write_csv(output/'financial-fetch-errors.csv',
              [{'ticker':a['ticker'],'reason':a['reason']} for a in manifest['companies'].values() if a['status']=='UNAVAILABLE'],
              ['ticker','reason'])
    lines=['# All-universe yfinance research run','',
           f"Price session: **{asof}**. Requested: **{manifest['requested_count']}** ticker codes from the saved Ajaib universe.",
           f"Financial snapshots captured: **{manifest['captured_count']}**. Positive valuation estimates: **{manifest['estimated_count']}**.",
           f"Yahoo rate-limit gaps: **{manifest['rate_limited_count']}**. These are access failures, not evidence that company statements do not exist.",
           f"Complete research coverage: **{manifest['coverage_complete_count']}**. Qualified candidates: **{manifest['qualifying_count']}**. Selected: **{manifest['selected_count']}**.",
           '',f"[Explainable ranking and all exclusions]({folder.name}/report.md). [Valuations](valuations.csv). [Financial calculation errors]({Path(manifest['valuations_path']).name}/errors.csv). [Financial fetch errors](financial-fetch-errors.csv).",' ',
           'Prices reuse the preserved yfinance collection for this session. Financial statements are newly fetched or replayed from this run’s retained raw snapshots. The universe is not certified against the current official IDX list.',
           'Company financial provider: **yfinance**. No WSJ or Invezgo fallback. Missing fields are unavailable, not zero. Broker flow: **ON_HOLD**. Values: **UNREVIEWED_ESTIMATES**.',
           'Research rankings require all applicable models, scenarios, technical and liquidity inputs. Analyst review and execution verification remain separate.']
    (output/'report.md').write_text('\n\n'.join(lines)+'\n',encoding='utf-8')
    return manifest


if __name__ == '__main__':
    main()
