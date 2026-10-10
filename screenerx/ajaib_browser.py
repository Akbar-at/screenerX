"""Capture broker JSON from the user's normal local browser session."""
import argparse
import asyncio
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse


def is_broker_response(url):
    parsed = urlparse(url)
    return (parsed.scheme == 'https' and parsed.hostname == 'ht2.ajaib.co.id'
            and parsed.path.startswith('/api/v1/stock/data/stock/')
            and parsed.path.endswith('/broker-summary/'))


async def capture(args):
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        raise SystemExit('Install: python -m pip install -r requirements-browser.txt')
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=False)
    profile = Path(args.profile)
    profile.mkdir(parents=True, exist_ok=True)
    pending = set()

    async def save(response):
        if not is_broker_response(response.url):
            return
        if response.status != 200:
            print(f'Broker request returned HTTP {response.status}; no capture saved.')
            return
        try:
            body = await response.body()
            json.loads(body)  # Reject HTML block pages.
        except Exception:
            print('Broker response was not readable JSON; no capture saved.')
            return
        digest = hashlib.sha256(body).hexdigest()
        filename = f'broker-{digest}.json'
        (output / filename).write_bytes(body)
        record = {'captured_at': datetime.now(timezone.utc).isoformat(),
                  'url': response.url, 'status': response.status,
                  'file': filename, 'sha256': digest}
        with (output / 'captures.jsonl').open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(record) + '\n')
        print(f'Saved {filename}')

    def on_response(response):
        task = asyncio.create_task(save(response))
        pending.add(task)
        task.add_done_callback(pending.discard)

    async with async_playwright() as playwright:
        context = await playwright.chromium.launch_persistent_context(
            str(profile.resolve()), headless=False)
        context.on('response', on_response)
        page = context.pages[0] if context.pages else await context.new_page()
        try:
            await page.goto(args.url, wait_until='domcontentloaded')
            print('Log in yourself, open Broker Summary and select dates/tickers.')
            print('Close the browser when finished. Headers, passwords and tokens are not exported.')
            closed = asyncio.Event()
            context.on('close', lambda *_: closed.set())
            await closed.wait()
        finally:
            if pending:
                await asyncio.gather(*list(pending), return_exceptions=True)
            await context.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='https://ajaib.co.id/terminal',
                        help='Official Ajaib web login/interface URL; terminal page is informational.')
    parser.add_argument('--profile', default='.auth/ajaib-browser')
    parser.add_argument('--output', required=True, help='New directory under ignored data/.')
    args = parser.parse_args()
    parsed = urlparse(args.url)
    if parsed.scheme != 'https' or not (parsed.hostname == 'ajaib.co.id'
            or (parsed.hostname or '').endswith('.ajaib.co.id')):
        parser.error('--url must be an HTTPS Ajaib URL')
    try:
        asyncio.run(capture(args))
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
