"""Provision screenerX state/storage without printing credentials or starting Cron."""
import argparse
import secrets
import json
import subprocess
from urllib.parse import urlsplit, urlunsplit, quote, unquote
from pathlib import Path

import httpx
from dotenv import dotenv_values, set_key


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', required=True)
    parser.add_argument('--account', required=True)
    args = parser.parse_args()
    config = {**dotenv_values('.env'), **dotenv_values('.env.bot')}
    with httpx.Client(timeout=40) as client:
        def neon(method, path, **kwargs):
            response = client.request(method, 'https://console.neon.tech/api/v2/' + path,
                headers={'Authorization': 'Bearer ' + config['NEON_API_KEY']}, **kwargs)
            if not response.is_success:
                raise SystemExit(f'Neon {method} {path}: HTTP {response.status_code}')
            return response.json()

        base = 'projects/' + args.project
        project = neon('GET', base)['project']
        if project['name'].lower() not in ('screenerx', 'screenx'):
            raise SystemExit('Target project must be named screenx or screenerx')
        branches = neon('GET', base + '/branches')['branches']
        branch = next((b for b in branches if b.get('default')), None)
        if branch is None:
            if len(branches) != 1: raise SystemExit('Cannot determine production branch')
            branch = branches[0]
        branch_base = base + '/branches/' + branch['id']
        databases = neon('GET', branch_base + '/databases')['databases']
        database = next(d for d in databases if d['name'] == 'neondb')
        params = {'branch_id': branch['id'], 'database_name': database['name'],
                  'role_name': database['owner_name'], 'pooled': 'false'}
        owner_uri = neon('GET', base + '/connection_uri', params=params)['uri']
        previous_uri=urlsplit(config.get('DATABASE_URL') or '')
        runtime_password=unquote(previous_uri.password) if previous_uri.username=='screenerx_engine' else secrets.token_urlsafe(32)
        path = Path('.env.bot'); path.touch(exist_ok=True)
        # Save the generated credential before migration, so retries reuse it.
        parts=urlsplit(owner_uri)
        runtime_uri=urlunsplit(parts._replace(netloc='screenerx_engine:'+quote(runtime_password,safe='')+'@'+parts.hostname.replace('.', '-pooler.',1)))
        set_key(str(path), 'DATABASE_URL', runtime_uri)
        migration = subprocess.run(['node', 'scripts/migrate_neon_http.mjs'],
            input=json.dumps({'uri': owner_uri,'runtimePassword':runtime_password}), text=True, capture_output=True, timeout=90)
        if migration.returncode: raise SystemExit('Neon HTTPS migration failed; credentials omitted')
        tables = json.loads(migration.stdout)['tables']
        for name in ('ENGINE_SECRET', 'TELEGRAM_WEBHOOK_SECRET'):
            if not config.get(name): set_key(str(path), name, secrets.token_urlsafe(32))
        print('Neon ready:', project['name'], branch['name'], len(tables), 'tables; runtime credentials saved to ignored .env.bot', flush=True)

        token = config.get('CLOUDFLARE_API_TOKEN') or config['CLOUDFLARE_API_KEY']
        def cloudflare(method, path, **kwargs):
            response = client.request(method, 'https://api.cloudflare.com/client/v4/accounts/' + args.account + '/' + path,
                headers={'Authorization': 'Bearer ' + token}, **kwargs)
            result = response.json()
            if not response.is_success or not result.get('success'):
                raise SystemExit(f'Cloudflare {method} {path}: HTTP {response.status_code}; ' +
                    '; '.join(e.get('message', '') for e in result.get('errors', [])))
            return result['result']
        buckets = cloudflare('GET', 'r2/buckets').get('buckets', [])
        if not any(b['name'] == 'screenerx-reports' for b in buckets):
            cloudflare('POST', 'r2/buckets', json={'name': 'screenerx-reports'})
        print('Private R2 bucket ready: screenerx-reports')
        queues = cloudflare('GET', 'queues')
        for name in ('screenerx-bot', 'screenerx-bot-dead'):
            if not any(q['queue_name'] == name for q in queues):
                cloudflare('POST', 'queues', json={'queue_name': name})
            print('Queue ready:', name)


if __name__ == '__main__': main()
