"""Seed a private R2 bucket before the Worker is deployed; verify every byte."""
import argparse
import hashlib
import json
from pathlib import Path
import httpx
from dotenv import dotenv_values


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--account',required=True)
    parser.add_argument('--bundle',required=True)
    args=parser.parse_args()
    config={**dotenv_values('.env'),**dotenv_values('.env.bot')}
    token=config.get('CLOUDFLARE_API_TOKEN') or config['CLOUDFLARE_API_KEY']
    bundle=Path(args.bundle); manifest=json.loads((bundle/'manifest.json').read_text())
    base=f'https://api.cloudflare.com/client/v4/accounts/{args.account}/r2/buckets/screenerx-reports/objects/'
    with httpx.Client(timeout=120,headers={'Authorization':'Bearer '+token}) as client:
        active=client.get(base+'inputs/active/manifest.json')
        if active.status_code==200 and active.json()!=manifest:
            raise SystemExit('Existing active inputs differ; publish updates through the Worker')
        if active.status_code not in (200,404): raise SystemExit(f'Active manifest check HTTP {active.status_code}')
        def upload(key,data):
            existing=client.get(base+key)
            if existing.status_code==200:
                if existing.content!=data: raise SystemExit('Immutable object differs: '+key)
            elif existing.status_code==404:
                response=client.put(base+key,content=data)
                if not response.is_success: raise SystemExit(f'Upload HTTP {response.status_code}: {key}')
            else: raise SystemExit(f'Object check HTTP {existing.status_code}: {key}')
            check=client.get(base+key)
            if check.status_code!=200 or hashlib.sha256(check.content).digest()!=hashlib.sha256(data).digest():
                raise SystemExit('R2 verification failed: '+key)
            print('Verified private R2 object:',key,flush=True)
        for name,metadata in manifest['files'].items():
            if name not in ('core-run.json','prices.csv','financials.json','fx.json'): raise SystemExit('Invalid input name')
            data=(bundle/name).read_bytes()
            if hashlib.sha256(data).hexdigest()!=metadata['sha256'] or len(data)!=metadata['bytes']:
                raise SystemExit('Local bundle hash mismatch: '+name)
            upload('inputs/bundles/'+manifest['version']+'/'+name,data)
        data=(bundle/'manifest.json').read_bytes()
        upload('inputs/bundles/'+manifest['version']+'/manifest.json',data)
        upload('inputs/active/manifest.json',data)
        print('Cloud inputs ready:',manifest['as_of'],manifest['version'])


if __name__=='__main__': main()
