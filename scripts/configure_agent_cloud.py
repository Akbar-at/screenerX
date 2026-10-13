"""Install the configured OpenRouter key as cloud/CI secrets without printing it."""
import base64
import os
import subprocess

import httpx
from dotenv import dotenv_values
from nacl.public import PublicKey,SealedBox


def main():
    config={**dotenv_values('.env'),**dotenv_values('.env.bot')}
    key=config.get('OPENROUTER_API_KEY')
    if not key: raise SystemExit('OPENROUTER_API_KEY is missing from ignored environment files')
    with httpx.Client(timeout=45) as client:
        response=client.put('https://api.cloudflare.com/client/v4/accounts/016d4b7a71aa56787dec81605976ffd2/workers/scripts/screenerx-telegram/secrets',
            headers={'Authorization':'Bearer '+config['CLOUDFLARE_DEPLOY_TOKEN']},
            json={'name':'OPENROUTER_API_KEY','type':'secret_text','text':key})
        if not response.is_success or not response.json().get('success'):
            raise SystemExit(f'Cloudflare secret setup failed (HTTP {response.status_code})')
        print('Cloudflare OpenRouter secret configured',flush=True)
        credential=subprocess.run(['git','credential','fill'],input='protocol=https\nhost=github.com\n\n',
            text=True,capture_output=True,timeout=30,
            env=dict(os.environ,GIT_TERMINAL_PROMPT='0',GCM_INTERACTIVE='never'))
        if credential.returncode: raise SystemExit('GitHub credentials unavailable')
        github=dict(line.split('=',1) for line in credential.stdout.splitlines() if '=' in line)
        headers={'Authorization':'Bearer '+github['password'],'Accept':'application/vnd.github+json'}
        url='https://api.github.com/repos/Akbar-at/screenerX/actions/secrets/'
        response=client.get(url+'public-key',headers=headers)
        if not response.is_success: raise SystemExit(f'GitHub public key failed (HTTP {response.status_code})')
        public=response.json()
        encrypted=SealedBox(PublicKey(base64.b64decode(public['key']))).encrypt(key.encode())
        response=client.put(url+'SCREENERX_OPENROUTER_API_KEY',headers=headers,
            json={'key_id':public['key_id'],'encrypted_value':base64.b64encode(encrypted).decode()})
        if not response.is_success: raise SystemExit(f'GitHub secret setup failed (HTTP {response.status_code})')
        print('GitHub encrypted OpenRouter secret configured',flush=True)


if __name__=='__main__': main()
