"""Resumable, bounded market-wide collection and coverage-qualified ranking."""
import argparse
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from .ajaib import BASE, result_of
from .engine import InputError, day, file_hash, write_csv,load_prices
from .fetch import FIELDS, fetch_json, fetch_yfinance, parse_chart, symbol_for
from .production import latest_session
from .core_service import build_service
from .core_cli import export_report


def validate_universe(payload):
    result = result_of(payload)
    codes = result.get('codes')
    if not isinstance(codes, list) or not codes:
        raise InputError('Universe contains no ticker list')
    tickers = [symbol_for(code)[0] for code in codes]
    if len(set(tickers)) != len(tickers) or result.get('count') != len(tickers):
        raise InputError('Universe count or uniqueness failed')
    return sorted(tickers)


def probe_sources(output,financial_provider='wsj'):
    """One public access check per source, with no authentication bypass."""
    from .wsj import fetch_page
    checks = []
    requests=[
        ('IDX official listing', lambda: fetch_json(
            'https://www.idx.co.id/primary/ListedCompany/GetStockSearch',
            provider='IDX', timeout=10, retries=0)),
    ]
    if financial_provider=='wsj': requests.append(('WSJ direct financials',lambda:fetch_page('TLKM','balance-sheet')))
    for name, request in requests:
        try:
            request()
            checks.append({'source': name, 'status': 'AVAILABLE'})
        except Exception as exc:
            checks.append({'source': name, 'status': 'UNAVAILABLE', 'reason': str(exc)})
    evidence = {'checked_at': datetime.now(timezone.utc).isoformat(), 'checks': checks}
    (Path(output) / 'source-access.json').write_text(json.dumps(evidence, indent=2), encoding='utf-8')
    return evidence


def collect_one(ticker, asof, folder, refresh=False):
    """Persist successful raw responses before parsing; replay without refetching."""
    raw_path = folder / (ticker + '.json')
    try:
        if raw_path.exists() and not refresh:
            payload = json.loads(raw_path.read_text(encoding='utf-8'))
        else:
            payload, raw = fetch_yfinance(ticker, asof, 400)
            temporary = raw_path.with_suffix('.tmp')
            temporary.write_bytes(raw)
            temporary.replace(raw_path)
        rows, quality = parse_chart(payload, ticker, asof)
        return rows, {'ticker': ticker, 'status': 'AVAILABLE', 'candles': len(rows),
                      'current_session':any(day(str(row['date']),'date')==asof for row in rows),
                      'raw_sha256': file_hash(raw_path), 'quality': quality}
    except Exception as exc:
        return [], {'ticker': ticker, 'status': 'UNAVAILABLE', 'reason': str(exc)}


def merge_history(fresh,previous,asof):
    """Retain real missing historical candles; fresh observations win on overlap."""
    merged={}
    def csv_row(bar,ticker,date):
        return {**bar,'ticker':ticker,'date':date.isoformat(),
                'corporate_actions_checked':str(bar.get('corporate_actions_checked',bar.get('actions_checked',False))).lower(),
                'traded_value_basis':bar.get('traded_value_basis',bar.get('turnover_basis','actual_regular')),
                'tradable':str(bar.get('tradable',True)).lower()}
    for ticker,bars in previous.items():
        for bar in bars:
            date=bar['date'] if hasattr(bar['date'],'isoformat') else day(bar['date'],'date')
            if date<asof: merged[(ticker,date)]=csv_row(bar,ticker,date)
    retained=set(merged)
    for bar in fresh:
        date=bar['date'] if hasattr(bar['date'],'isoformat') else day(bar['date'],'date')
        if date<=asof:
            key=(bar['ticker'],date);merged[key]=csv_row(bar,bar['ticker'],date);retained.discard(key)
    return [merged[key] for key in sorted(merged)],len(retained)


def run(output, asof=None, workers=3, snapshots=None, wsj_pages=None, financial_provider='wsj', fx_snapshot=None,previous_prices=None,retry_failed=False):
    if financial_provider not in ('wsj','yfinance'):
        raise InputError('Unsupported financial provider')
    if wsj_pages and financial_provider!='wsj':
        raise InputError('WSJ pages require WSJ provider')
    from .core_service import completed_cutoff
    if workers not in range(1, 5):
        raise InputError('Workers must be between 1 and 4')
    if asof and asof > completed_cutoff():
        raise InputError('Requested session is incomplete or in the future')
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    state_path = output / 'collection.json'
    if state_path.exists():
        state = json.loads(state_path.read_text(encoding='utf-8'))
        if state.get('financial_provider','wsj')!=financial_provider:
            raise InputError('Resume financial provider differs from original collection')
        if asof and state['as_of'] != asof.isoformat():
            raise InputError('Resume date differs from original collection')
        asof = day(state['as_of'], 'as_of')
        payload = json.loads((output / 'universe-raw.json').read_text(encoding='utf-8'))
        tickers = validate_universe(payload)
    else:
        if asof is None:
            asof, _ = latest_session()
        payload, raw = fetch_json(BASE + 'asset/codes?asset_type=STOCK', provider='Ajaib')
        tickers = validate_universe(payload)
        (output / 'universe-raw.json').write_bytes(raw)
        probe_sources(output,financial_provider)
        state = {'as_of': asof.isoformat(), 'status': 'COLLECTING', 'source': 'Ajaib public stock codes',
                 'universe_count': len(tickers), 'official_idx_completeness_verified': False,
                 'universe_sha256': file_hash(output / 'universe-raw.json'),
                 'retrieved_at': datetime.now(timezone.utc).isoformat(), 'prices': {}}
    state['financial_provider']=financial_provider
    write_csv(output / 'universe.csv', [{'ticker': t} for t in tickers], ['ticker'])
    raw_folder = output / 'raw'
    raw_folder.mkdir(exist_ok=True)
    def save():
        temporary = state_path.with_suffix('.tmp')
        temporary.write_text(json.dumps(state, indent=2, allow_nan=False), encoding='utf-8')
        temporary.replace(state_path)
    save()
    rows = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        # Retry incomplete/corrupt captures rather than replaying the same bad
        # response on all three durable job attempts. Healthy captures stay cached.
        pending = {pool.submit(collect_one, t, asof, raw_folder,
                    retry_failed and (state['prices'].get(t,{}).get('status')!='AVAILABLE'
                                      or not state['prices'].get(t,{}).get('current_session',False))): t for t in tickers}
        for n, future in enumerate(as_completed(pending), 1):
            candles, audit = future.result()
            rows.extend(candles)
            state['prices'][audit['ticker']] = audit
            if n % 25 == 0 or n == len(tickers):
                save()
                print(f'Prices assessed: {n}/{len(tickers)}', flush=True)
    rows.sort(key=lambda r: (r['ticker'], str(r['date'])))
    if previous_prices:
        rows,retained=merge_history(rows,load_prices(previous_prices),asof)
        state['retained_history']={'rows':retained,'source_sha256':file_hash(previous_prices)}
    del pending
    write_csv(output / 'prices.csv', rows, FIELDS)
    del rows
    # Saved financial evidence is replayed; absent files remain explicit source gaps.
    # Do not send hundreds of requests to the known authentication barrier.
    service = build_service(output / 'prices.csv', asof, snapshot_dir=snapshots, wsj_pages=wsj_pages,
                            financial_provider=financial_provider,fx_path=fx_snapshot)
    report = service.screen(tickers)
    if previous_prices: report['input_files'][str(Path(previous_prices).resolve())]=file_hash(previous_prices)
    report['universe_source'] = state['source']
    report['official_idx_completeness_verified'] = False
    report_folder = output / 'core'
    if report_folder.exists():
        report_folder = output / ('core-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f'))
    export_report(report, report_folder)
    state.update(status='PARTIAL' if report['coverage_complete_count'] < len(tickers) else 'COMPLETE',
                 price_count=sum(a['status'] == 'AVAILABLE' for a in state['prices'].values()),
                 current_price_count=sum(a.get('current_session',False) for a in state['prices'].values()),
                 coverage_complete_count=report['coverage_complete_count'],
                 selected_count=report['selected_count'], broker_flow_status='ON_HOLD',
                 company_data_fallback=False, report_path=str(report_folder / 'report.md'))
    save()
    write_summary(output, state, report_folder)
    return state


def write_summary(output, state, report_folder):
    output = Path(output)
    failures = [a for a in state['prices'].values() if a['status'] != 'AVAILABLE']
    write_csv(output / 'price-errors.csv', failures, ['ticker', 'status', 'reason'])
    relative = Path(report_folder).relative_to(output).as_posix()
    text = (
        '# Market-wide real-data run\n\n'
        f"Price session: {state['as_of']}. Assessed {state['universe_count']} public Ajaib stock codes.\n\n"
        f"Usable Yahoo/yfinance price histories: **{state['price_count']}**. "
        f"Price failures: **{len(failures)}**. Complete research coverage: "
        f"**{state['coverage_complete_count']}**. Qualified selections: **{state['selected_count']}**.\n\n"
        f'[Ranking, explanations and every exclusion]({relative}/report.md). '
        f'[Per-ticker coverage]({relative}/coverage.csv). '
        '[Price failures](price-errors.csv). [Source access checks](source-access.json).\n\n'
        f"Financial provider: **{state.get('financial_provider','wsj')}**. Existing financial captures are replayed; missing financials remain unavailable. No company-data fallback. "
        'The official IDX endpoint is blocked (HTTP 403), so completeness of the broker universe '
        'against current official listings is unverified. Stale and unavailable symbols remain visible.\n\n'
        'Broker flow: **ON_HOLD**. Valuations: **UNREVIEWED_ESTIMATES**. '
        'Selections are research results with explicit assumptions; trade readiness is not established.\n'
    )
    (output / 'report.md').write_text(text, encoding='utf-8')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    parser.add_argument('--as-of', type=lambda v: day(v, 'as_of'))
    parser.add_argument('--workers', type=int, choices=range(1, 5), default=3)
    sources = parser.add_mutually_exclusive_group()
    sources.add_argument('--snapshots')
    sources.add_argument('--wsj-pages')
    parser.add_argument('--financial-provider',choices=('wsj','yfinance'),default='wsj')
    parser.add_argument('--fx-snapshot')
    args = parser.parse_args(argv)
    state = run(args.output, args.as_of, args.workers, args.snapshots, args.wsj_pages,args.financial_provider,args.fx_snapshot)
    print(json.dumps({k: v for k, v in state.items() if k != 'prices'}, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
