"""Install pinned, checksum-verified upstream release binaries in the Linux image."""
import hashlib
import os
import platform
import subprocess
from pathlib import Path
import httpx

VERSION='v0.3.1'
HASHES={
    'x86_64':{'idx':'e4add45e9e50ba17b034c4c1bba430f25249b7a45a81837da4f2dc37ea11627a',
              'idx-mcp':'7a93fdf4265cdaf5719dbfd8d64e4af4835b8e1c9f0130999c46cab682b9eda5'},
    'aarch64':{'idx':'d3c558c65241b1f13c51399c2cbec04256edeb0b5c8c1a75b95c7a9c4bb90fef',
               'idx-mcp':'b500f579c5eef01d9f8bc0902334654825a8e0ddd2f5c440afe30d903012971a'}}
machine=platform.machine()
if platform.system()!='Linux' or machine not in HASHES:raise RuntimeError('Unsupported idx-mcp image platform')
suffix='x64' if machine=='x86_64' else 'arm64'
with httpx.Client(timeout=90,follow_redirects=True) as client:
    for binary,digest in HASHES[machine].items():
        response=client.get(f'https://github.com/0xrsydn/idx-cli/releases/download/{VERSION}/{binary}-linux-{suffix}')
        response.raise_for_status();raw=response.content
        if hashlib.sha256(raw).hexdigest()!=digest:raise RuntimeError('idx binary checksum mismatch')
        path=Path('/usr/local/bin')/binary;path.write_bytes(raw);os.chmod(path,0o755)
subprocess.run(['idx','version'],check=True)
subprocess.run(['idx-mcp','--version'],check=True)
