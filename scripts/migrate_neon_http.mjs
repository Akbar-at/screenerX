// HTTPS migrations for environments that cannot reach PostgreSQL port 5432.
import { neon } from '../workers/bot/node_modules/@neondatabase/serverless/index.mjs';
import { readdirSync, readFileSync } from 'node:fs';
let input = '';
for await (const chunk of process.stdin) input += chunk;
try {
  const { uri, runtimePassword } = JSON.parse(input);
  const sql = neon(uri);
  const queries = [];
  // SQL-created roles do not inherit Neon console administrative membership.
  if (!/^[A-Za-z0-9_-]{32,}$/.test(runtimePassword)) throw new Error('Invalid generated password');
  queries.push(sql.query("DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='screenerx_engine') THEN CREATE ROLE screenerx_engine LOGIN PASSWORD '" + runtimePassword + "'; END IF; END $$"));
  for (const name of readdirSync('db/migrations').filter(x=>x.endsWith('.sql')).sort()) {
    for (const statement of readFileSync('db/migrations/' + name, 'utf8').split(';')) {
      if (statement.trim()) queries.push(sql.query(statement));
    }
  }
  queries.push(sql.query('GRANT USAGE ON SCHEMA public TO screenerx_engine'));
  for (const table of ['sx_bot_updates','sx_bot_outbox','sx_bot_artifacts','sx_refresh_jobs']) {
    queries.push(sql.query('GRANT SELECT, INSERT, UPDATE ON ' + table + ' TO screenerx_engine'));
  }
  await sql.transaction(queries);
  const tables = await sql`SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename LIKE 'sx_%'`;
  console.log(JSON.stringify({tables: tables.map(x=>x.tablename)}));
} catch {
  console.error('Neon HTTPS migration failed; credentials omitted from diagnostics');
  process.exitCode = 1;
}
