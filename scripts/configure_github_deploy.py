"""Configure an encrypted, account-scoped Cloudflare deployment secret for CI.

Requires PyNaCl locally. No credentials are printed or written into source.
"""
import base64
import os
import subprocess
from pathlib import Path
import httpx
from dotenv import dotenv_values, set_key
from nacl.public import PublicKey, SealedBox

ACCOUNT='016d4b7a71aa56787dec81605976ffd2'
REPO='Akbar-at/screenerX'


def main():
    config={**dotenv_values('.env'),**dotenv_values('.env.bot')}
    credential=subprocess.run(['git','credential','fill'],input='protocol=https\nhost=github.com\n\n',
        text=True,capture_output=True,timeout=25,
        env=dict(os.environ,GIT_TERMINAL_PROMPT='0',GCM_INTERACTIVE='never'))
    if credential.returncode: raise SystemExit('GitHub credential unavailable')
    github=dict(line.split('=',1) for line in credential.stdout.splitlines() if '=' in line)
    with httpx.Client(timeout=30) as client:
        def cf(method,path,**kwargs):
            r=client.request(method,'https://api.cloudflare.com/client/v4/accounts/'+ACCOUNT+'/'+path,
                headers={'Authorization':'Bearer '+config['CLOUDFLARE_API_KEY']},**kwargs)
            if not r.is_success: raise SystemExit(f'Cloudflare setup HTTP {r.status_code}')
            return r.json()['result']
        token=config.get('CLOUDFLARE_DEPLOY_TOKEN')
        if not token:
            names={'Workers Scripts Write','Workers Containers Write','Queues Write',
                   'Workers R2 Storage Read','Account Settings Read','Workers Observability Write'}
            groups=cf('GET','tokens/permission_groups')
            selected=[{'id':g['id']} for g in groups if g['name'] in names]
            if len(selected)!=len(names): raise SystemExit('Deployment permission groups unavailable')
            result=cf('POST','tokens',json={'name':'screenerx-github-deploy',
                'policies':[{'effect':'allow','resources':{'com.cloudflare.api.account.'+ACCOUNT:'*'},
                             'permission_groups':selected}]})
            token=result['value']
            path=Path('.env.bot');path.touch(exist_ok=True)
            set_key(str(path),'CLOUDFLARE_DEPLOY_TOKEN',token)
            print('Scoped deployment token created and saved in ignored .env.bot',flush=True)
        headers={'Authorization':'Bearer '+github['password'],'Accept':'application/vnd.github+json'}
        url='https://api.github.com/repos/'+REPO+'/actions/secrets/'
        r=client.get(url+'public-key',headers=headers)
        if not r.is_success: raise SystemExit(f'GitHub secret key HTTP {r.status_code}')
        public=r.json()
        encrypted=SealedBox(PublicKey(base64.b64decode(public['key']))).encrypt(token.encode())
        r=client.put(url+'SCREENERX_CLOUDFLARE_DEPLOY_TOKEN',headers=headers,
            json={'key_id':public['key_id'],'encrypted_value':base64.b64encode(encrypted).decode()})
        if not r.is_success: raise SystemExit(f'GitHub secret setup HTTP {r.status_code}')
        print('GitHub encrypted deployment secret configured',flush=True)


if __name__=='__main__': main()
