"""Versioned private R2 bundles used to restart and publish daily research safely."""
import hashlib
import base64
import json
import shutil
from pathlib import Path

from .engine import InputError,file_hash
from .fetch import symbol_for

NAMES=('core-run.json','prices.csv','financials.json','fx.json','daily-overview.png','daily-report.pdf')


def build_bundle(run_dir,prices,output,snapshots=None,fx=None,daily_assets=None):
    output=Path(output); output.mkdir(parents=True,exist_ok=True)
    report_path=Path(run_dir)/'core-run.json'
    report=json.loads(report_path.read_text(encoding='utf-8'))
    for name,source in [('core-run.json',report_path),('prices.csv',Path(prices))]:
        shutil.copyfile(source,output/name)
    files={name:{'sha256':file_hash(output/name),'bytes':(output/name).stat().st_size} for name in NAMES[:2]}
    raw={}
    candidates=list(Path(snapshots).glob('*.json')) if snapshots else [Path(p) for p in report.get('input_files',{}) if Path(p).parent.name=='raw' and Path(p).suffix=='.json']
    for path in candidates:
        if not path.exists(): continue
        source=path.read_bytes(); snapshot=json.loads(source)
        if snapshot.get('provider')!='yfinance': continue
        ticker,_=symbol_for(snapshot['ticker'])
        if snapshot.get('symbol')!=ticker+'.JK': raise InputError('Bundle financial identity mismatch')
        raw[ticker]={'encoding':'base64','data':base64.b64encode(source).decode('ascii'),'sha256':hashlib.sha256(source).hexdigest()}
    if raw:
        (output/'financials.json').write_text(json.dumps(raw,allow_nan=False),encoding='utf-8')
        files['financials.json']={'sha256':file_hash(output/'financials.json'),'bytes':(output/'financials.json').stat().st_size}
    fx_path=Path(fx) if fx else next((Path(p) for p in report.get('input_files',{}) if Path(p).name=='USDIDR.json' and Path(p).exists()),None)
    if fx_path and fx_path.exists():
        shutil.copyfile(fx_path,output/'fx.json')
        files['fx.json']={'sha256':file_hash(output/'fx.json'),'bytes':(output/'fx.json').stat().st_size}
    if daily_assets:
        for name,part in zip(NAMES[4:],daily_assets):
            shutil.copyfile(part['path'],output/name)
            files[name]={'sha256':file_hash(output/name),'bytes':(output/name).stat().st_size}
    version=hashlib.sha256(json.dumps(files,sort_keys=True).encode()).hexdigest()[:16]
    manifest={'version':version,'as_of':report['as_of'],'files':files}
    (output/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    return output


def publish_bundle(bundle,url,secret):
    import httpx
    bundle=Path(bundle); manifest=json.loads((bundle/'manifest.json').read_text())
    if not secret: raise InputError('Engine secret required for private publication')
    with httpx.Client(timeout=120) as client:
        for name in list(manifest['files'])+['manifest.json']:
            response=client.put(url.rstrip('/')+'/'+manifest['version']+'/'+name,
                                headers={'Authorization':'Bearer '+secret},content=(bundle/name).read_bytes())
            response.raise_for_status()


def main(argv=None):
    import argparse,os
    from dotenv import load_dotenv
    load_dotenv('.env'); load_dotenv('.env.bot')
    parser=argparse.ArgumentParser(description='Publish a hashed input bundle through the private Worker endpoint.')
    parser.add_argument('--bundle',required=True); parser.add_argument('--url',default=os.getenv('INPUT_BUNDLE_URL'))
    args=parser.parse_args(argv)
    if not args.url: raise InputError('INPUT_BUNDLE_URL or --url required')
    publish_bundle(args.bundle,args.url,os.getenv('ENGINE_SECRET'))
    print('Input bundle published')


if __name__=='__main__': main()
