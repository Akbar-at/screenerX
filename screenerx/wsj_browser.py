"""Probe WSJ in an ordinary browser; retain evidence and validate rendered tables."""
import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from .engine import InputError, file_hash
from .wsj import page_url, parse_html, validate_page


def probe(ticker, route, output, headed=False, wait_seconds=45, profile=None):
    from playwright.sync_api import sync_playwright
    output = Path(output)
    if output.exists():
        raise InputError('Choose a new probe output directory')
    output.mkdir(parents=True)
    url = page_url(ticker, route)
    audit = {'url': url, 'headed': headed, 'started_at': datetime.now(timezone.utc).isoformat(),
             'status': 'RUNNING', 'navigation_status': None, 'errors': []}
    with sync_playwright() as playwright:
        if profile:
            context = playwright.chromium.launch_persistent_context(
                str(Path(profile).resolve()), headless=not headed)
            browser = None
        else:
            browser = playwright.chromium.launch(headless=not headed)
            context = browser.new_context()
        page = context.new_page()
        try:
            try:
                response = page.goto(url, wait_until='domcontentloaded', timeout=30000)
                audit['navigation_status'] = response.status if response else None
            except Exception as exc:
                audit['errors'].append({'stage': 'navigation', 'reason': str(exc)})
            deadline = time.monotonic() + wait_seconds
            parsed = None
            last_error = ''
            while time.monotonic() < deadline:
                try:
                    html = page.content()
                    candidate = parse_html(html, ticker, route)
                    validate_page(candidate, ticker, route)
                    parsed = candidate
                    break
                except (InputError, ValueError) as exc:
                    last_error = str(exc)
                page.wait_for_timeout(1000)
            html = page.content()
            (output / 'page.html').write_text(html, encoding='utf-8')
            body = page.locator('body').inner_text(timeout=5000)
            (output / 'page.txt').write_text(body, encoding='utf-8')
            page.screenshot(path=str(output / 'page.png'), full_page=True, timeout=15000)
            audit.update(final_url=page.url, title=page.title(), table_count=page.locator('table').count())
            if parsed:
                parsed.update(retrieval_method='playwright_rendered_page',
                              retrieved_at=datetime.now(timezone.utc).isoformat(), actual_retrieval_url=page.url)
                path = output / f'{ticker}-{route}.json'
                path.write_text(json.dumps(parsed, indent=2, allow_nan=False), encoding='utf-8')
                audit.update(status='STATEMENT_VALIDATED', statement_sha256=file_hash(path))
            else:
                lower = (body + html).lower()
                challenge = any(marker in lower for marker in (
                    'captcha-delivery.com', 'please enable js', 'verify you are human',
                    'unusual activity', 'access is temporarily restricted'))
                audit.update(status='CHALLENGED' if challenge else 'STATEMENT_UNAVAILABLE',
                             validation_error=last_error)
        except Exception as exc:
            audit.update(status='BROWSER_ERROR')
            audit['errors'].append({'stage': 'capture', 'reason': str(exc)})
        finally:
            context.close()
            if browser:
                browser.close()
    audit['completed_at'] = datetime.now(timezone.utc).isoformat()
    (output / 'probe.json').write_text(json.dumps(audit, indent=2), encoding='utf-8')
    return audit


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ticker', default='TLKM')
    parser.add_argument('--statement', choices=('balance-sheet', 'income-statement', 'cash-flow'), default='balance-sheet')
    parser.add_argument('--output', required=True)
    parser.add_argument('--headed', action='store_true')
    parser.add_argument('--wait-seconds', type=int, choices=range(1, 301), default=45)
    parser.add_argument('--profile', help='Dedicated browser profile directory; keep private and outside version control')
    args = parser.parse_args(argv)
    from .fetch import symbol_for
    ticker, _ = symbol_for(args.ticker)
    print(f'Opening {ticker} in {"visible" if args.headed else "headless"} Chromium', flush=True)
    audit = probe(ticker, args.statement, args.output, args.headed, args.wait_seconds, args.profile)
    print(json.dumps(audit, indent=2))
    return 0 if audit['status'] == 'STATEMENT_VALIDATED' else 2


if __name__ == '__main__':
    raise SystemExit(main())
