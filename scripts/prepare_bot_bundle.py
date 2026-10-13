"""Create a reproducible input bundle for private R2 hosting (no credentials needed)."""
import argparse
import hashlib
import json
import shutil
from pathlib import Path

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir',required=True); parser.add_argument('--prices',required=True)
    parser.add_argument('--output',required=True)
    parser.add_argument('--snapshots'); parser.add_argument('--fx-snapshot')
    args=parser.parse_args(); target=Path(args.output)
    if target.exists(): raise SystemExit('Choose a new bundle directory')
    import sys
    sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
    from screenerx.refresh_bundle import build_bundle
    build_bundle(args.run_dir,args.prices,target,args.snapshots,args.fx_snapshot)
    print(target.resolve())

if __name__=='__main__': main()
