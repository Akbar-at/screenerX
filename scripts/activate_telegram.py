"""Enroll the private Telegram owner using a one-time Start code.

Configuration stays in ignored .env.bot and Cloudflare secrets. This helper
never sends a Telegram message or acknowledges pending updates itself.
"""
import sys
from pathlib import Path
import httpx
from dotenv import dotenv_values, set_key

ACCOUNT='016d4b7a71aa56787dec81605976ffd2'
WORKER='screenerx-telegram'


def main():
    config={**dotenv_values('.env'),**dotenv_values('.env.bot')}
    token=config.get('TELEGRAM_BOT_TOKEN')
    if not token: raise SystemExit('TELEGRAM_BOT_TOKEN required')
    with httpx.Client(timeout=30) as client:
        def telegram(method,payload=None):
            r=client.post('https://api.telegram.org/bot'+token+'/'+method,json=payload or {})
            data=r.json()
            if not data.get('ok'): raise SystemExit(f'Telegram {method} failed: HTTP {r.status_code}')
            return data['result']
        me=telegram('getMe')
        users=config.get('TELEGRAM_ALLOWED_USER_IDS');chats=config.get('TELEGRAM_ALLOWED_CHAT_IDS')
        if not users or not chats:
            code=config.get('TELEGRAM_ENROLLMENT_CODE')
            if not code: raise SystemExit('One-time enrollment code required')
            if telegram('getWebhookInfo').get('url'):
                raise SystemExit('An existing webhook must be inspected before enrollment')
            updates=telegram('getUpdates',{'timeout':0,'limit':100})
            matches=[]
            for update in updates:
                message=update.get('message',{});sender=message.get('from',{});chat=message.get('chat',{})
                if (message.get('text')=='/start '+code and chat.get('type')=='private'
                    and sender.get('id')==chat.get('id') and not sender.get('is_bot',True)):
                    matches.append(message)
            identities={m['from']['id'] for m in matches}
            if not identities: print('AWAITING_OWNER_START');return
            if len(identities)!=1: raise SystemExit('Enrollment is ambiguous; regenerate the code')
            users=chats=str(identities.pop())
            path=Path('.env.bot');path.touch(exist_ok=True)
            set_key(str(path),'TELEGRAM_ALLOWED_USER_IDS',users)
            set_key(str(path),'TELEGRAM_ALLOWED_CHAT_IDS',chats)
            set_key(str(path),'TELEGRAM_ENROLLMENT_CODE','')
            print('Private owner enrolled; IDs saved in ignored .env.bot',flush=True)
        base=f'https://api.cloudflare.com/client/v4/accounts/{ACCOUNT}/workers/scripts/{WORKER}/secrets'
        for name,value in [('TELEGRAM_BOT_TOKEN',token),('TELEGRAM_ALLOWED_USER_IDS',users),
                           ('TELEGRAM_ALLOWED_CHAT_IDS',chats),('TELEGRAM_WEBHOOK_SECRET',config['TELEGRAM_WEBHOOK_SECRET'])]:
            r=client.put(base,headers={'Authorization':'Bearer '+config['CLOUDFLARE_API_KEY']},
                json={'name':name,'text':value,'type':'secret_text'})
            if not r.is_success: raise SystemExit(f'Cloudflare secret {name}: HTTP {r.status_code}')
            print('Cloud secret configured:',name,flush=True)
        print('Bot credentials ready for @'+me['username']+'; verify fresh engine health before registering webhook',flush=True)


if __name__=='__main__':
    try: main()
    except httpx.HTTPError as error:
        print('Network operation failed:',type(error).__name__,file=sys.stderr)
        raise SystemExit(1)
