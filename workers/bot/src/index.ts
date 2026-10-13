import { Container } from '@cloudflare/containers';
import { neon } from '@neondatabase/serverless';
import { authorized, sameSecret } from './auth';

interface Env {
  DATABASE_URL: string; TELEGRAM_BOT_TOKEN: string; TELEGRAM_WEBHOOK_SECRET: string; ENGINE_SECRET: string;
  TELEGRAM_ALLOWED_USER_IDS: string; TELEGRAM_ALLOWED_CHAT_IDS: string; INPUT_BUNDLE_URL: string;
  TELEGRAM_OPEN_GROUP_IDS: string;
  BOT_ALLOW_LIVE: string; BOT_AUTO_REFRESH: string;
  BOT_QUEUE: Queue<{update_id: number}>; REPORTS: R2Bucket;
  ENGINE: DurableObjectNamespace<ResearchEngine>;
}

export class ResearchEngine extends Container<Env> {
  defaultPort = 8080;
  sleepAfter = '10m';
  envVars = {
    DATABASE_URL: this.env.DATABASE_URL,
    TELEGRAM_BOT_TOKEN: this.env.TELEGRAM_BOT_TOKEN ?? '',
    TELEGRAM_ALLOWED_USER_IDS: this.env.TELEGRAM_ALLOWED_USER_IDS ?? '',
    TELEGRAM_ALLOWED_CHAT_IDS: this.env.TELEGRAM_ALLOWED_CHAT_IDS ?? '',
    TELEGRAM_OPEN_GROUP_IDS: this.env.TELEGRAM_OPEN_GROUP_IDS ?? '',
    ENGINE_SECRET: this.env.ENGINE_SECRET,
    BOT_ALLOW_LIVE: this.env.BOT_ALLOW_LIVE ?? 'false',
    BOT_AUTO_REFRESH: this.env.BOT_AUTO_REFRESH ?? 'true',
    INPUT_BUNDLE_URL: this.env.INPUT_BUNDLE_URL,
    ARTIFACT_ARCHIVE_URL: this.env.INPUT_BUNDLE_URL.replace(/\/internal\/bundle\/?$/, '/internal/artifacts'),
    BOT_ARTIFACTS: '/tmp/screenerx-artifacts', BOT_DATA: '/tmp/screenerx-input',
    BOT_REFRESH_STATE: '/tmp/screenerx-refresh', BOT_LATEST_POINTER: '/tmp/screenerx-refresh/latest.json',
  };
}

function accessSettings(env: Env) {
  return {users:env.TELEGRAM_ALLOWED_USER_IDS ?? '',chats:env.TELEGRAM_ALLOWED_CHAT_IDS ?? '',
    groups:env.TELEGRAM_OPEN_GROUP_IDS ?? ''};
}

async function dispatch(env: Env) {
  const sql = neon(env.DATABASE_URL);
  const now = Date.now() / 1000;
  // The inbound table doubles as a durable dispatch outbox. A failed queue send is recovered by Cron.
  const due = await sql`SELECT update_id FROM sx_bot_updates WHERE
    (status IN ('PENDING','RETRY') AND next_at <= ${now}) OR
    (status='PROCESSING' AND lease_until < ${now}) ORDER BY update_id LIMIT 20`;
  for (const row of due) await env.BOT_QUEUE.send({update_id: Number(row.update_id)});
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const parsed = new URL(request.url); const path = parsed.pathname;
    if (path === '/health') return Response.json({status: 'ok'});
    if (path === '/internal/engine/restart' && request.method === 'POST') {
      if (!env.ENGINE_SECRET || !sameSecret(request.headers.get('Authorization') ?? '', 'Bearer ' + env.ENGINE_SECRET))
        return new Response('Forbidden', {status: 403});
      const sql=neon(env.DATABASE_URL); const now=Date.now()/1000;
      const busy=await sql`SELECT 1 FROM sx_refresh_jobs WHERE status='RUNNING' AND lease_until>${now}
        UNION ALL SELECT 1 FROM sx_bot_updates WHERE status='PROCESSING' AND lease_until>${now} LIMIT 1`;
      if (busy.length) return Response.json({error:'Research engine is processing work'}, {status:409});
      await env.ENGINE.getByName('research-bot-v2').stop();
      return Response.json({status:'stopped',message:'The next request starts the engine with current cloud secrets'});
    }
    if (path === '/internal/engine/configure' && request.method === 'POST') {
      if (!env.ENGINE_SECRET || !sameSecret(request.headers.get('Authorization') ?? '', 'Bearer ' + env.ENGINE_SECRET))
        return new Response('Forbidden', {status:403});
      return env.ENGINE.getByName('research-bot-v2').fetch(new Request('http://engine/internal/access',{
        method:'POST',headers:{'Authorization':'Bearer '+env.ENGINE_SECRET,'Content-Type':'application/json'},
        body:JSON.stringify(accessSettings(env)),
      }));
    }
    if ((path === '/internal/engine/health' && request.method === 'GET') ||
        (path === '/internal/refresh' && request.method === 'POST')) {
      if (!env.ENGINE_SECRET || !sameSecret(request.headers.get('Authorization') ?? '', 'Bearer ' + env.ENGINE_SECRET))
        return new Response('Forbidden', {status: 403});
      try {
        const target=path === '/internal/engine/health' ? '/health' : '/internal/refresh';
        return await env.ENGINE.getByName('research-bot-v2').fetch(new Request('http://engine'+target,request));
      } catch { return Response.json({error:'Research engine unavailable'}, {status:503}); }
    }
    if (path.startsWith('/internal/artifacts/') && request.method === 'PUT') {
      if (!env.ENGINE_SECRET || !sameSecret(request.headers.get('Authorization') ?? '', 'Bearer ' + env.ENGINE_SECRET))
        return new Response('Forbidden', {status: 403});
      const key = path.substring('/internal/artifacts/'.length);
      if (!/^[a-f0-9]{16}\/(?:[A-Z0-9]{1,12}|top10)-\d{4}-\d{2}-\d{2}(?:-chart)?\.(?:png|pdf)$/.test(key))
        return new Response('Invalid artifact key', {status: 400});
      const raw = await request.arrayBuffer();
      if (raw.byteLength > 50 * 1024 * 1024) return new Response('Too large', {status: 413});
      const hash = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', raw))).map(x=>x.toString(16).padStart(2,'0')).join('');
      const objectKey = 'reports/' + key;
      await env.REPORTS.put(objectKey, raw, {customMetadata: {sha256: hash}});
      const sql = neon(env.DATABASE_URL);
      await sql`INSERT INTO sx_bot_artifacts(object_key,sha256,bytes) VALUES (${objectKey},${hash},${raw.byteLength})
        ON CONFLICT(object_key) DO UPDATE SET sha256=EXCLUDED.sha256,bytes=EXCLUDED.bytes`;
      return Response.json({ok:true,sha256:hash});
    }
    if (path.startsWith('/internal/bundle/')) {
      if (!sameSecret(request.headers.get('Authorization') ?? '', 'Bearer ' + env.ENGINE_SECRET) || !env.ENGINE_SECRET)
        return new Response('Forbidden', {status: 403});
      const suffix = path.substring('/internal/bundle/'.length);
      const names = ['core-run.json','prices.csv','financials.json','fx.json'];
      if (request.method === 'PUT') {
        const [version,name,...extra] = suffix.split('/');
        if (extra.length || !/^[a-f0-9]{16}$/.test(version) || ![...names,'manifest.json'].includes(name))
          return new Response('Invalid bundle key', {status:400});
        const raw=await request.arrayBuffer();
        if (raw.byteLength>64*1024*1024) return new Response('Too large',{status:413});
        if (name === 'manifest.json') {
          let manifest: any;
          try { manifest=JSON.parse(new TextDecoder().decode(raw)); } catch { return new Response('Invalid manifest',{status:400}); }
          if (manifest.version !== version || !/^\d{4}-\d{2}-\d{2}$/.test(manifest.as_of) ||
              !manifest.files?.['core-run.json'] || !manifest.files?.['prices.csv']) return new Response('Invalid manifest',{status:400});
          for (const file of Object.keys(manifest.files)) {
            if (!names.includes(file)) return new Response('Unknown file',{status:400});
            const stored=await env.REPORTS.head(`inputs/bundles/${version}/${file}`);
            if (!stored || stored.customMetadata?.sha256 !== manifest.files[file].sha256) return new Response('Incomplete bundle',{status:409});
          }
          const active=await env.REPORTS.get('inputs/active/manifest.json');
          if (active && ((await active.json()) as any).as_of>manifest.as_of) return new Response('Older report rejected',{status:409});
          await env.REPORTS.put(`inputs/bundles/${version}/manifest.json`,raw);
          await env.REPORTS.put('inputs/active/manifest.json',raw); // atomic active pointer, written last
        } else {
          const hash=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',raw))).map(x=>x.toString(16).padStart(2,'0')).join('');
          const existing=await env.REPORTS.head(`inputs/bundles/${version}/${name}`);
          if (existing) {
            let storedHash=existing.customMetadata?.sha256;
            // Initial account-API seeds have no custom metadata; verify their bytes before adopting them.
            if (!storedHash) {
              const seeded=await env.REPORTS.get(`inputs/bundles/${version}/${name}`);
              if (!seeded) return new Response('Seed missing',{status:409});
              storedHash=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',await seeded.arrayBuffer()))).map(x=>x.toString(16).padStart(2,'0')).join('');
            }
            if (storedHash !== hash) return new Response('Immutable file mismatch',{status:409});
          }
          await env.REPORTS.put(`inputs/bundles/${version}/${name}`,raw,{customMetadata:{sha256:hash}});
        }
        return Response.json({ok:true});
      }
      const name=suffix;
      if (![...names,'manifest.json'].includes(name)) return new Response('Not found',{status:404});
      const version=parsed.searchParams.get('version');
      if (version && !/^[a-f0-9]{16}$/.test(version)) return new Response('Invalid version',{status:400});
      let key='inputs/active/'+name;
      if (version) key=`inputs/bundles/${version}/${name}`;
      else if (name !== 'manifest.json') {
        const active=await env.REPORTS.get('inputs/active/manifest.json');
        if (active) { const manifest=await active.json() as any; if (manifest.version) key=`inputs/bundles/${manifest.version}/${name}`; }
      }
      const object = await env.REPORTS.get(key);
      return object ? new Response(object.body, {headers: {'Content-Type': name.endsWith('.json') ? 'application/json' : 'text/csv'}})
        : new Response('Bundle missing', {status: 503});
    }
    if (path !== '/telegram/webhook' || request.method !== 'POST') return new Response('Not found', {status: 404});
    if (!sameSecret(request.headers.get('X-Telegram-Bot-Api-Secret-Token') ?? '', env.TELEGRAM_WEBHOOK_SECRET))
      return new Response('Forbidden', {status: 403});
    const body = await request.text();
    if (new TextEncoder().encode(body).byteLength > 32768) return new Response('Too large', {status: 413});
    let update: unknown;
    try { update = JSON.parse(body); } catch { return new Response('Bad JSON', {status: 400}); }
    // Telegram retries non-2xx responses, including service events and disallowed senders.
    // Once the webhook secret is verified, acknowledge ignored updates without storing or processing them.
    if (!authorized(update, env.TELEGRAM_ALLOWED_USER_IDS, env.TELEGRAM_ALLOWED_CHAT_IDS, env.TELEGRAM_OPEN_GROUP_IDS))
      return Response.json({ok:true,ignored:true});
    if (['group','supergroup'].includes((update as any).message.chat?.type) && !update.message.text.trimStart().startsWith('/'))
      return Response.json({ok:true,ignored:true});
    const sql = neon(env.DATABASE_URL);
    await sql`INSERT INTO sx_bot_updates(update_id,payload) VALUES (${update.update_id},${JSON.stringify(update)}) ON CONFLICT(update_id) DO NOTHING`;
    // Return success once durable storage accepts the update; Cron also repairs dispatch failures.
    try { await env.BOT_QUEUE.send({update_id: update.update_id}); } catch { /* durable PENDING record survives */ }
    return Response.json({ok: true});
  },
  async queue(batch: MessageBatch<{update_id: number}>, env: Env) {
    for (const message of batch.messages) {
      try {
        const engine = env.ENGINE.getByName('research-bot-v2');
        const response = await engine.fetch(new Request('http://engine/internal/process', {
          method: 'POST', headers: {'Authorization': 'Bearer ' + env.ENGINE_SECRET, 'Content-Type': 'application/json'},
          body: JSON.stringify({...message.body,access:accessSettings(env)}),
        }));
        if (response.ok) message.ack(); else message.retry({delaySeconds: 60});
      } catch { message.retry({delaySeconds: 60}); }
    }
  },
  async scheduled(event: ScheduledEvent, env: Env, context: ExecutionContext) {
    context.waitUntil((async()=>{
      await dispatch(env);
      if (env.BOT_AUTO_REFRESH !== 'true') return;
      const sql=neon(env.DATABASE_URL); const now=Date.now()/1000;
      if (event.cron === '30 11 * * 1-5') {
        const date=new Date(event.scheduledTime+7*3600*1000).toISOString().slice(0,10);
        await sql`INSERT INTO sx_refresh_jobs(request_date,status) VALUES (${date},'PENDING') ON CONFLICT(request_date) DO NOTHING`;
      }
      const pending=await sql`SELECT request_date FROM sx_refresh_jobs WHERE status IN ('PENDING','RUNNING') OR (status='RETRY' AND next_at<=${now} AND attempts<3) ORDER BY request_date LIMIT 1`;
      if (event.cron !== '30 11 * * 1-5' && !pending.length) return;
      const date=pending.length ? pending[0].request_date : new Date(event.scheduledTime+7*3600*1000).toISOString().slice(0,10);
      const engine=env.ENGINE.getByName('research-bot-v2');
      const response=await engine.fetch(new Request('http://engine/internal/refresh',{
        method:'POST',headers:{'Authorization':'Bearer '+env.ENGINE_SECRET,'Content-Type':'application/json'},
        body:JSON.stringify({request_date:date}),
      }));
      if (!response.ok) throw new Error('Daily refresh dispatch failed');
    })());
  },
};
