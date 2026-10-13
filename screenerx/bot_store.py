"""Durable inbound jobs and delivery outbox: SQLite locally, PostgreSQL/Neon in cloud."""
import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path

SCHEMA = '''
CREATE TABLE IF NOT EXISTS sx_bot_updates (
 update_id BIGINT PRIMARY KEY, payload TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'PENDING',
 attempts INTEGER NOT NULL DEFAULT 0, next_at DOUBLE PRECISION NOT NULL DEFAULT 0,
 lease_until DOUBLE PRECISION NOT NULL DEFAULT 0, last_error TEXT
);
CREATE TABLE IF NOT EXISTS sx_bot_outbox (
 update_id BIGINT NOT NULL, part INTEGER NOT NULL, payload TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'PENDING', message_id BIGINT, last_error TEXT,
 PRIMARY KEY (update_id,part)
);
CREATE INDEX IF NOT EXISTS sx_bot_due ON sx_bot_updates(status,next_at);
CREATE TABLE IF NOT EXISTS sx_refresh_jobs (
 request_date TEXT PRIMARY KEY, status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
 next_at DOUBLE PRECISION NOT NULL DEFAULT 0, lease_until DOUBLE PRECISION NOT NULL DEFAULT 0, result TEXT
);
'''


class BotStore:
    def __init__(self,path='output/bot-state.sqlite',database_url=None):
        self.url=database_url; self.path=str(path); self.lock=threading.RLock()
        if not database_url: Path(path).parent.mkdir(parents=True,exist_ok=True)
        if not database_url:
            with self.connection() as connection:
                for statement in SCHEMA.split(';'):
                    if statement.strip(): connection.execute(statement)

    @contextmanager
    def connection(self):
        if self.url:
            import psycopg
            from psycopg.rows import dict_row
            with psycopg.connect(self.url,row_factory=dict_row,connect_timeout=10) as connection:
                yield connection
        else:
            with self.lock:
                connection=sqlite3.connect(self.path,timeout=20)
                connection.row_factory=sqlite3.Row
                try:
                    yield connection; connection.commit()
                finally: connection.close()

    def query(self,sql,params=(),fetch=False):
        if self.url: sql=sql.replace('?','%s')
        with self.connection() as connection:
            cursor=connection.execute(sql,params)
            return [dict(row) for row in cursor.fetchall()] if fetch else cursor.rowcount

    def accept(self,update):
        return self.query('INSERT INTO sx_bot_updates(update_id,payload) VALUES (?,?) ON CONFLICT(update_id) DO NOTHING',
                          (update['update_id'],json.dumps(update,allow_nan=False)))==1

    def claim(self,update_id):
        now=time.time()
        self.query("UPDATE sx_bot_updates SET status='FAILED',last_error='Retry limit reached' WHERE update_id=? AND status IN ('PENDING','RETRY','PROCESSING') AND attempts>=8 AND lease_until<?",(update_id,now))
        rows=self.query("UPDATE sx_bot_updates SET status='PROCESSING',lease_until=?,attempts=attempts+1 WHERE update_id=? AND ((status IN ('PENDING','RETRY') AND next_at<=?) OR (status='PROCESSING' AND lease_until<?)) RETURNING payload",
                        (now+600,update_id,now,now),True)
        return json.loads(rows[0]['payload']) if rows else None

    def stage(self,update_id,messages):
        for n,message in enumerate(messages):
            self.query('INSERT INTO sx_bot_outbox(update_id,part,payload) VALUES (?,?,?) ON CONFLICT(update_id,part) DO NOTHING',
                       (update_id,n,json.dumps(message)))
        # A previous process may have died after Telegram accepted a send.
        self.query("UPDATE sx_bot_outbox SET status='UNCERTAIN',last_error='Interrupted during delivery; manual check required' WHERE update_id=? AND status='SENDING'",(update_id,))

    def parts(self,update_id):
        return self.query('SELECT * FROM sx_bot_outbox WHERE update_id=? ORDER BY part',(update_id,),True)

    def begin_send(self,update_id,part):
        return self.query("UPDATE sx_bot_outbox SET status='SENDING' WHERE update_id=? AND part=? AND status='PENDING'",(update_id,part))==1

    def finish_part(self,update_id,part,status,message_id=None,error=None):
        self.query('UPDATE sx_bot_outbox SET status=?,message_id=?,last_error=? WHERE update_id=? AND part=?',
                   (status,message_id,error,update_id,part))

    def finish(self,update_id,status='DONE',error=None,delay=0):
        self.query('UPDATE sx_bot_updates SET status=?,lease_until=0,last_error=?,next_at=? WHERE update_id=?',
                   (status,error,time.time()+delay,update_id))

    def due(self):
        now=time.time()
        return self.query("SELECT update_id FROM sx_bot_updates WHERE (status IN ('PENDING','RETRY') AND next_at<=?) OR (status='PROCESSING' AND lease_until<?) ORDER BY update_id LIMIT 20",(now,now),True)

    def counts(self):
        return {r['status']:r['count'] for r in self.query('SELECT status,COUNT(*) AS count FROM sx_bot_updates GROUP BY status',fetch=True)}
