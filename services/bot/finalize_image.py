"""Keep the application's restart image consistent with its latest rollout."""
import os
import re
import time
from pathlib import Path
import httpx


def finalize(client,account,application,image):
    base=f'https://api.cloudflare.com/client/v4/accounts/{account}/containers/applications/{application}'
    response=client.get(base);response.raise_for_status();app=response.json()['result']
    if not image.startswith(f"registry.cloudflare.com/{account}/{app['name']}@sha256:"):
        raise RuntimeError('Unexpected rollout image registry or application')
    if app['configuration']['image']==image:return 'Application restart image matches rollout'
    response=client.patch(base,json={'configuration':{'image':image}});response.raise_for_status()
    # PATCH can return the previous configuration while the update is applied.
    for attempt in range(120):
        response=client.get(base);response.raise_for_status()
        if response.json()['result']['configuration']['image']==image:return 'Application restart image updated to deployed image'
        if attempt%6==0:print('Waiting for application image update',flush=True)
        time.sleep(5)
    raise RuntimeError('Container restart image did not update')


if __name__=='__main__':
    with httpx.Client(timeout=30,headers={'Authorization':'Bearer '+os.environ['CLOUDFLARE_API_TOKEN']}) as client:
        # The build's own pushed digest is authoritative; an older rollout may
        # remain in the API after a deployment that modifies the app directly.
        log=Path(os.environ['SCREENERX_DEPLOY_LOG']).read_text()
        digests=re.findall(r'digest: (sha256:[a-f0-9]{64})',log)
        if not digests:raise RuntimeError('Deployed image digest missing from build log')
        account=os.environ['CLOUDFLARE_ACCOUNT_ID']
        image=f'registry.cloudflare.com/{account}/screenerx-telegram-researchengine@{digests[-1]}'
        print(finalize(client,account,'a03c7be3-1e53-4544-9970-a40d36afd738',image))
