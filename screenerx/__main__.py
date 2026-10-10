"""python -m screenerx --help"""
import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import __version__
from .engine import InputError, OUTPUT_FIELDS, day, file_hash, load_config, load_inputs, screen, write_csv


def main(argv=None):
    parser=argparse.ArgumentParser(description='Rank IDX opportunities from prices, broker flows and reviewed valuations. No network calls or trade execution.')
    parser.add_argument('--prices', required=True, help='Daily regular-market OHLCV CSV')
    parser.add_argument('--valuations', required=True, help='Reviewed method values and frozen structural levels CSV')
    parser.add_argument('--brokers', required=True, help='Daily regular-market net flow CSV')
    parser.add_argument('--as-of', required=True, help='Decision trading date YYYY-MM-DD')
    parser.add_argument('--config', default=str(Path(__file__).parent.parent/'config.json'))
    parser.add_argument('--output', default='output', help='New output directory (existing directory is never overwritten)')
    parser.add_argument('--include-provisional', action='store_true', help='Also rank candidates missing quotes or execution cost/size evidence; labeled PROVISIONAL')
    args=parser.parse_args(argv)
    try:
        config=load_config(args.config); asof=day(args.as_of,'as-of')
        output=Path(args.output)
        if output.exists():
            raise InputError('Output directory already exists; choose a new directory to preserve prior runs')
        data=load_inputs(args.prices,args.valuations,args.brokers)
        rows,issues,summary=screen(*data,config,asof,args.include_provisional)
        resolved=json.dumps(config,sort_keys=True,indent=2,allow_nan=False)
        metadata={'version':__version__,'created_at':datetime.now(timezone.utc).isoformat(),'as_of':args.as_of,'profile':config['profile_name'],'include_provisional':args.include_provisional,'config_sha256':hashlib.sha256(resolved.encode()).hexdigest(),'inputs':{name:{'path':str(Path(path).resolve()),'sha256':file_hash(path)} for name,path in [('prices',args.prices),('valuations',args.valuations),('brokers',args.brokers)]},**summary}
        output.mkdir(parents=True)
        write_csv(output/'top10.csv',rows,OUTPUT_FIELDS)
        write_csv(output/'inspection.csv',issues,['ticker','state','reason'])
        (output/'config.resolved.json').write_text(resolved+'\n')
        (output/'run.json').write_text(json.dumps(metadata,indent=2)+'\n')
        print(f"Selected {len(rows)} of {summary['universe_count']} tickers: {summary['verified_count']} eligible, {summary['provisional_count']} provisional.")
        print('Rank  Ticker       Score   Entry    TP1     Stop   Net R/R  State')
        for row in rows:
            rr=f"{row['net_rr']:.2f}" if row['net_rr'] is not None else 'n/a'
            print(f"{row['rank']:>4}  {row['ticker']:<10}  {row['composite_score']:>5.1f}  {row['entry_price']:>6}  {row['tp1_price']:>6}  {row['stop_loss_price']:>6}  {rr:>7}  {row['status']}")
        print(f'Results: {output / "top10.csv"}; exclusions: {output / "inspection.csv"}')
        if not rows:
            print('No qualifying opportunities. Inspect failed gates; no filler tickers were added.')
        return 0
    except (InputError,OSError,TypeError,KeyError) as exc:
        print(f'Error: {exc}',file=sys.stderr)
        return 2


if __name__=='__main__':
    sys.exit(main())
