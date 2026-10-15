"""Keep the application's restart image consistent with its latest rollout."""
import os
import httpx


def finalize(client,account,application):
    base=f'https://api.cloudflare.com/client/v4/accounts/{account}/containers/applications/{application}'
    response=client.get(base);response.raise_for_status();app=response.json()['result']
    response=client.get(base+'/rollouts');response.raise_for_status();rollouts=response.json()['result']
    if not rollouts:return 'No rollout to finalize'
    rollout=max(rollouts,key=lambda item:item['created_at'])
    if rollout['status'] in ('reverted','replaced'):raise RuntimeError('Latest container rollout is not active')
    image=rollout['target_configuration']['image']
    if not image.startswith(f"registry.cloudflare.com/{account}/{app['name']}@sha256:"):
        raise RuntimeError('Unexpected rollout image registry or application')
    if app['configuration']['image']==image:return 'Application restart image matches rollout'
    response=client.patch(base,json={'configuration':{'image':image}});response.raise_for_status()
    if response.json()['result']['configuration']['image']!=image:raise RuntimeError('Container restart image did not update')
    return 'Application restart image updated to deployed rollout'


if __name__=='__main__':
    with httpx.Client(timeout=30,headers={'Authorization':'Bearer '+os.environ['CLOUDFLARE_API_TOKEN']}) as client:
        print(finalize(client,os.environ['CLOUDFLARE_ACCOUNT_ID'],'a03c7be3-1e53-4544-9970-a40d36afd738'))
