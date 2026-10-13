"""Private Telegram research bot with stored reports, PNG/PDF delivery and durable retries."""
import argparse
import hashlib
import hmac
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path

from .bot_store import BotStore
from .engine import InputError
from .fetch import symbol_for
from .reporting import ReportRepository,narrative,render_stock,render_top

HELP = ('screenerX - riset saham Indonesia\n\n'
        '/top10 - ranking, gambar ringkasan dan rekomendasi deskriptif\n'
        '/stock BBNI - gambar chart dan kajian lengkap\n'
        '/stock KODE live - lookup yfinance jika fitur live diaktifkan\n'
        '/chart BBNI - gambar laporan\n'
        '/valuation BBNI - DDM/RIM/EVA dan skenario\n'
        '/report - PDF seluruh kandidat\n'
        '/report BBNI - PDF satu saham\n'
        '/coverage - cakupan dan data yang belum tersedia\n'
        '/status - tanggal run dan status pengiriman\n\n'
        'Semua kode di universe dapat diperiksa, termasuk yang tidak masuk shortlist. '
        'Valuasi belum direview. Broker flow ON_HOLD.')


def chunks(text,limit=3800):
    result=[]; buffer=''
    for paragraph in text.split('\n\n'):
        while len(paragraph)>limit:
            if buffer: result.append(buffer); buffer=''
            result.append(paragraph[:limit]); paragraph=paragraph[limit:]
        if len(buffer)+len(paragraph)+2>limit:
            result.append(buffer); buffer=''
        buffer+=( '\n\n' if buffer else '')+paragraph
    if buffer: result.append(buffer)
    return result


def authorized(update,users,chats):
    message=update.get('message')
    return (type(update.get('update_id')) is int and isinstance(message,dict)
            and str(message.get('from',{}).get('id')) in users
            and str(message.get('chat',{}).get('id')) in chats
            and isinstance(message.get('text'),str) and len(message['text'])<=4096)


class DeliveryError(Exception):
    def __init__(self,reason,retry_after=None,uncertain=False):
        super().__init__(reason); self.retry_after=retry_after; self.uncertain=uncertain


class TelegramClient:
    def __init__(self,token):
        import httpx
        if not token: raise InputError('TELEGRAM_BOT_TOKEN is required')
        self.base='https://api.telegram.org/bot'+token
        self.client=httpx.Client(timeout=60)
        self.send_lock=threading.Lock(); self.last_send={}

    def request(self,method,payload,files=None):
        import httpx
        try:
            response=self.client.post(self.base+'/'+method,data=payload,files=files) if files else self.client.post(self.base+'/'+method,json=payload)
            try: body=response.json()
            except ValueError: raise DeliveryError('Telegram returned invalid JSON',uncertain=method.startswith('send'))
            if not response.is_success or not body.get('ok'):
                retry=body.get('parameters',{}).get('retry_after')
                raise DeliveryError(f'Telegram HTTP/API {body.get("error_code",response.status_code)}',retry_after=retry,
                                    uncertain=response.status_code>=500 and method.startswith('send'))
            return body['result']
        except httpx.TransportError:
            raise DeliveryError('Telegram transport error',uncertain=method.startswith('send')) from None

    def send(self,chat_id,message):
        with self.send_lock:
            interval=3.1 if str(chat_id).startswith('-') else 1.1
            delay=max(0,interval-(time.monotonic()-self.last_send.get(str(chat_id),-float('inf'))))
            if delay: time.sleep(delay)
            try: return self._send(chat_id,message)
            finally: self.last_send[str(chat_id)]=time.monotonic()

    def _send(self,chat_id,message):
        kind=message['kind']
        if kind=='text': return self.request('sendMessage',{'chat_id':chat_id,'text':message['text']})
        field='photo' if kind=='photo' else 'document'
        path=Path(message['path'])
        with path.open('rb') as stream:
            return self.request('sendPhoto' if kind=='photo' else 'sendDocument',
                                {'chat_id':str(chat_id),'caption':message.get('caption','')[:1000]},
                                {field:(path.name,stream,'image/png' if kind=='photo' else 'application/pdf')})


class ResearchBot:
    def __init__(self,repository,store,client,users,chats,output='output/bot-artifacts',delivery_enabled=True):
        if delivery_enabled and (not users or not chats): raise InputError('Explicit allowed user and chat IDs are required')
        self.delivery_enabled=delivery_enabled
        self.repository=repository; self.store=store; self.client=client
        self.users=set(map(str,users)); self.chats=set(map(str,chats)); self.output=Path(output)

    def prepare(self,text):
        args=text.strip().split(); command=args[0].split('@')[0].lower() if args else '/help'
        from .daily_refresh import load_latest
        self.repository=load_latest(self.repository,os.getenv('BOT_LATEST_POINTER','output/daily-refresh/latest.json'))
        repository=self.repository
        signature={'inputs':repository.report['input_files'],'config':repository.report['config_sha256'],
                   'as_of':repository.report['as_of'],'renderer':'ihsf-inspired-chart-v2'}
        run_key=hashlib.sha256(json.dumps(signature,sort_keys=True).encode()).hexdigest()[:16]
        output=self.output/run_key
        def messages(body): return [{'kind':'text','text':part} for part in chunks(body)]
        if command in ('/start','/help'): return messages(HELP)
        if command in ('/top','/top10'):
            assets=render_top(repository,output)
            result=[{'kind':'photo','path':str(assets['png']),'caption':f"Top 10 | {repository.report['as_of']} | {repository.report['selected_count']} kandidat lolos"}]+messages(assets['text'])
            for analysis in assets['analyses']:
                result.append({'kind':'photo','path':analysis['chart'],'caption':analysis['ticker']+' | '+repository.report['as_of']+' | '+analysis['label']})
                result.extend(messages(analysis['text']))
            return result
        if command=='/coverage':
            r=repository.report
            return messages(f"Cakupan {r['as_of']}\nUniverse {r['universe_count']} kode; lengkap {r['coverage_complete_count']}; kandidat lolos {r['qualifying_count']}; terpilih {r['selected_count']}; slot kosong {r['unfilled_slots']}.\n\nDaftar publik Ajaib belum diverifikasi sebagai seluruh saham biasa BEI. Sumber finansial yfinance; broker flow ON_HOLD.")
        if command=='/status':
            return messages(f"Run {repository.report['as_of']} | pengiriman {json.dumps(self.store.counts(),sort_keys=True)}\nValuasi UNREVIEWED_ESTIMATES; broker flow ON_HOLD.")
        if command=='/report' and len(args)==1:
            assets=render_top(repository,output)
            return [{'kind':'document','path':str(assets['pdf']),'caption':'Laporan riset lengkap | '+repository.report['as_of']}]
        if command in ('/stock','/chart','/valuation','/report'):
            if len(args) not in (2,3) or len(args)==3 and args[2].lower()!='live': return messages(f'Gunakan {command} KODE, contoh {command} BBNI.')
            ticker,_=symbol_for(args[1]); bars=repository.bars(ticker)
            if len(args)==3:
                if os.getenv('BOT_ALLOW_LIVE','false').lower()!='true': return messages('Live lookup belum diaktifkan. Gunakan data run tersimpan terlebih dahulu.')
                from .core_service import build_service
                from .engine import day
                service=build_service(repository.prices_path,day(repository.report['as_of'],'as_of'),financial_provider='yfinance')
                company=service.lookup(ticker,live=True); bars=service.repository.get_prices(ticker)
                signature=hashlib.sha256(json.dumps(company,sort_keys=True,allow_nan=False).encode()).hexdigest()[:16]
                output=self.output/signature
            else: company=repository.company(ticker)
            info=narrative(company)
            assets=render_stock(company,bars,output)
            image={'kind':'photo','path':str(assets['chart']),'caption':ticker+' | '+company['as_of']+' | '+info['label']}
            if command=='/valuation':
                sections=[s for s in info['sections'] if s[0] in ('Fundamental & valuasi','Risiko utama')]
                return [image]+messages(f"{ticker} | {company['as_of']}\n\n"+'\n\n'.join(t+'\n'+b for t,b in sections))
            if command=='/report': return [image,{'kind':'document','path':str(assets['pdf']),'caption':ticker+' | '+company['as_of']}]
            return [image]+(messages(info['text']) if command=='/stock' else [])
        return messages('Perintah belum tersedia.\n\n'+HELP)

    def accept(self,update):
        if not self.delivery_enabled: return False
        if not authorized(update,self.users,self.chats): return False
        self.store.accept(update); return True

    def process(self,update_id):
        if not self.delivery_enabled: return 'NOT_CONFIGURED'
        update=self.store.claim(update_id)
        if update is None:
            rows=self.store.query('SELECT status FROM sx_bot_updates WHERE update_id=?',(update_id,),True)
            return rows[0]['status'] if rows and rows[0]['status'] in ('DONE','UNCERTAIN','FAILED','REJECTED') else 'NOT_CLAIMED'
        if not authorized(update,self.users,self.chats):
            self.store.finish(update_id,'REJECTED'); return 'REJECTED'
        try:
            try: messages=self.prepare(update['message']['text'])
            except (InputError,ValueError) as exc: messages=[{'kind':'text','text':str(exc)}]
            if os.getenv('ARTIFACT_ARCHIVE_URL'):
                import httpx
                with httpx.Client(timeout=60) as client:
                    for message in messages:
                        if 'path' not in message: continue
                        path=Path(message['path'])
                        response=client.put(os.environ['ARTIFACT_ARCHIVE_URL'].rstrip('/')+'/'+path.parent.name+'/'+path.name,
                            headers={'Authorization':'Bearer '+os.environ['ENGINE_SECRET']},content=path.read_bytes())
                        response.raise_for_status()
            self.store.stage(update_id,messages)
            for part in self.store.parts(update_id):
                if not self.store.begin_send(update_id,part['part']): continue
                try:
                    response=self.client.send(update['message']['chat']['id'],json.loads(part['payload']))
                    self.store.finish_part(update_id,part['part'],'SENT',response.get('message_id'))
                except DeliveryError as exc:
                    if exc.retry_after is not None:
                        self.store.finish_part(update_id,part['part'],'PENDING',error=str(exc))
                        self.store.finish(update_id,'RETRY',str(exc),max(1,float(exc.retry_after)))
                        return 'RETRY'
                    self.store.finish_part(update_id,part['part'],'UNCERTAIN' if exc.uncertain else 'FAILED',error=str(exc))
            statuses={p['status'] for p in self.store.parts(update_id)}
            result='UNCERTAIN' if 'UNCERTAIN' in statuses else 'FAILED' if 'FAILED' in statuses else 'DONE'
            self.store.finish(update_id,result); return result
        except Exception:
            self.store.finish(update_id,'RETRY','Report preparation failed',30)
            raise


def handler(bot,engine_secret,webhook_secret,refresh=None):
    class Handler(BaseHTTPRequestHandler):
        def respond(self,code,payload):
            data=json.dumps(payload).encode(); self.send_response(code)
            self.send_header('Content-Type','application/json'); self.send_header('Content-Length',str(len(data)))
            self.end_headers(); self.wfile.write(data)
        def do_GET(self):
            if self.path=='/health': return self.respond(200,{'status':'ok',
                'as_of':bot.repository.report.get('as_of'),
                'telegram_enabled':bot.delivery_enabled,'refresh_enabled':refresh is not None})
            self.respond(404,{'error':'Unknown route'})
        def do_POST(self):
            internal=self.path in ('/internal/process','/internal/refresh')
            secret=self.headers.get('Authorization','') if internal else self.headers.get('X-Telegram-Bot-Api-Secret-Token','')
            expected='Bearer '+engine_secret if internal else webhook_secret
            if not expected or expected=='Bearer ' or not hmac.compare_digest(secret,expected): return self.respond(403,{'error':'Forbidden'})
            if self.path not in ('/internal/process','/internal/refresh','/telegram/webhook'): return self.respond(404,{'error':'Unknown route'})
            try:
                length=int(self.headers.get('Content-Length','0'))
                if not 0<length<=32768: return self.respond(413,{'error':'Invalid payload size'})
                payload=json.loads(self.rfile.read(length))
                if self.path=='/internal/refresh':
                    if refresh is None: return self.respond(503,{'error':'Refresh not configured'})
                    return self.respond(202,{'status':refresh.start(payload.get('request_date'))})
                if internal:
                    result=bot.process(int(payload['update_id']))
                    return self.respond(503 if result in ('RETRY','NOT_CLAIMED','NOT_CONFIGURED') else 200,{'status':result})
                if not bot.accept(payload): return self.respond(403,{'error':'Unauthorized sender'})
                self.respond(200,{'ok':True}) # processing is done by durable background/poll loop
            except (ValueError,KeyError,TypeError): self.respond(400,{'error':'Invalid update'})
            except Exception: self.respond(503,{'error':'Processing failed; safe to retry'})
        def log_message(self,*args): pass
    return Handler


def bootstrap(url,secret,directory):
    """Load a hashed private R2 input bundle through the authenticated Worker route."""
    import httpx
    directory=Path(directory); directory.mkdir(parents=True,exist_ok=True)
    headers={'Authorization':'Bearer '+secret}
    with httpx.Client(timeout=60) as client:
        response=client.get(url+'/manifest.json',headers=headers); response.raise_for_status(); manifest=response.json()
        for name in manifest['files']:
            if name not in ('core-run.json','prices.csv','financials.json','fx.json'): raise InputError('Unknown bundle file')
            version='?version='+manifest['version'] if manifest.get('version') else ''
            response=client.get(url+'/'+name+version,headers=headers); response.raise_for_status()
            raw=response.content
            if hashlib.sha256(raw).hexdigest()!=manifest['files'][name]['sha256']: raise InputError('Input bundle hash mismatch')
            (directory/name).write_bytes(raw)
        if 'financials.json' in manifest['files']:
            snapshots=directory/'raw'; snapshots.mkdir(exist_ok=True)
            for ticker,capture in json.loads((directory/'financials.json').read_text(encoding='utf-8')).items():
                ticker,_=symbol_for(ticker)
                if isinstance(capture,dict):
                    import base64
                    if capture.get('encoding')!='base64': raise InputError('Unsupported capture encoding')
                    source=base64.b64decode(capture['data'],validate=True)
                    if hashlib.sha256(source).hexdigest()!=capture['sha256']: raise InputError('Financial capture hash mismatch')
                else: source=capture.encode('utf-8') # older text-only imported bundles
                snapshot=json.loads(source)
                if snapshot.get('provider')!='yfinance' or snapshot.get('ticker')!=ticker or snapshot.get('symbol')!=ticker+'.JK':
                    raise InputError('Imported financial capture identity mismatch')
                (snapshots/(ticker+'.json')).write_bytes(source)
            os.environ['BOT_FINANCIAL_SNAPSHOTS']=str(snapshots)
        if 'fx.json' in manifest['files']: os.environ['BOT_FX_SNAPSHOT']=str(directory/'fx.json')
    return directory


def main(argv=None):
    from dotenv import load_dotenv
    load_dotenv('.env'); load_dotenv('.env.bot')
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode',choices=('poll','serve','preview','set-webhook'))
    parser.add_argument('--run-dir',default=os.getenv('BOT_RUN_DIR'))
    parser.add_argument('--prices',default=os.getenv('BOT_PRICES'))
    parser.add_argument('--output',default=os.getenv('BOT_ARTIFACTS','output/bot-artifacts'))
    parser.add_argument('--state',default=os.getenv('BOT_STATE','output/bot-state.sqlite'))
    parser.add_argument('--host',default='127.0.0.1'); parser.add_argument('--port',type=int,default=8080)
    parser.add_argument('--command',default='/top10'); parser.add_argument('--url')
    args=parser.parse_args(argv)
    if args.mode=='set-webhook':
        if not args.url or not args.url.startswith('https://'): raise InputError('HTTPS webhook URL required')
        secret=os.getenv('TELEGRAM_WEBHOOK_SECRET')
        if not secret: raise InputError('TELEGRAM_WEBHOOK_SECRET required')
        TelegramClient(os.getenv('TELEGRAM_BOT_TOKEN')).request('setWebhook',{'url':args.url,'secret_token':secret,'allowed_updates':['message']})
        print('Webhook registered'); return
    if os.getenv('INPUT_BUNDLE_URL'):
        bundle=bootstrap(os.environ['INPUT_BUNDLE_URL'],os.environ['ENGINE_SECRET'],os.getenv('BOT_DATA','output/bot-input'))
        args.run_dir=str(bundle); args.prices=str(bundle/'prices.csv')
    if not args.run_dir or not args.prices: raise InputError('BOT_RUN_DIR and BOT_PRICES (or input bundle URL) required')
    repository=ReportRepository(args.run_dir,args.prices)
    users={x.strip() for x in os.getenv('TELEGRAM_ALLOWED_USER_IDS','').split(',') if x.strip()}
    chats={x.strip() for x in os.getenv('TELEGRAM_ALLOWED_CHAT_IDS','').split(',') if x.strip()}
    if args.mode=='preview':
        bot=ResearchBot(repository,BotStore(args.state),None,users or {'preview'},chats or {'preview'},args.output)
        messages=bot.prepare(args.command)
        print(json.dumps(messages,indent=2,ensure_ascii=True)); return
    store=BotStore(args.state,os.getenv('DATABASE_URL'))
    delivery_enabled=bool(os.getenv('TELEGRAM_BOT_TOKEN') and users and chats)
    if not delivery_enabled and args.mode != 'serve':
        raise InputError('Telegram token and allowed user/chat IDs are required for polling')
    client=TelegramClient(os.getenv('TELEGRAM_BOT_TOKEN')) if delivery_enabled else None
    bot=ResearchBot(repository,store,client,users,chats,args.output,delivery_enabled=delivery_enabled)
    if not delivery_enabled: print('Research engine active; Telegram delivery awaits configuration',flush=True)
    refresh=None
    if os.getenv('BOT_AUTO_REFRESH','false').lower()=='true':
        if args.mode != 'serve' or not os.getenv('DATABASE_URL') or not os.getenv('INPUT_BUNDLE_URL'):
            raise InputError('Automatic refresh requires the cloud service with Neon DATABASE_URL and INPUT_BUNDLE_URL')
        from .daily_refresh import DailyRefresh
        state_dir=os.getenv('BOT_REFRESH_STATE','output/daily-refresh')
        refresh=DailyRefresh(repository,BotStore(Path(state_dir)/'state.sqlite',os.getenv('DATABASE_URL')),
            state_dir,os.getenv('BOT_FINANCIAL_SNAPSHOTS'),os.getenv('BOT_FX_SNAPSHOT'),
            os.getenv('BOT_LATEST_POINTER','output/daily-refresh/latest.json'),
            on_publish=lambda fresh:setattr(bot,'repository',fresh),
            publish_url=os.getenv('INPUT_BUNDLE_URL'),secret=os.getenv('ENGINE_SECRET'))
    server=None
    if args.mode=='serve':
        import threading
        engine_secret=os.getenv('ENGINE_SECRET',''); webhook_secret=os.getenv('TELEGRAM_WEBHOOK_SECRET','')
        if not engine_secret and not webhook_secret: raise InputError('An engine or webhook secret is required')
        server=ThreadingHTTPServer((args.host,args.port),handler(bot,engine_secret,webhook_secret,refresh))
        threading.Thread(target=server.serve_forever,daemon=True).start()
        print(f'Bot service listening on {args.host}:{args.port}',flush=True)
    offset=0
    try:
        while True:
            if args.mode=='poll':
                updates=bot.client.request('getUpdates',{'offset':offset,'timeout':25,'allowed_updates':['message']})
                for update in updates:
                    bot.accept(update); offset=max(offset,update['update_id']+1)
            if args.mode=='poll' or not os.getenv('DATABASE_URL'):
                for row in store.due():
                    try: bot.process(row['update_id'])
                    except Exception: pass # durable retry record remains available
            if args.mode=='serve': time.sleep(1)
    except KeyboardInterrupt:
        if server: server.shutdown(); server.server_close()


if __name__=='__main__': main()
