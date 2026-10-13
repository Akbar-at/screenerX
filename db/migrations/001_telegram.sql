-- Durable Telegram jobs and outbox shared by Worker and Python engine.
CREATE TABLE IF NOT EXISTS sx_bot_updates (
 update_id BIGINT PRIMARY KEY, payload TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'PENDING',
 attempts INTEGER NOT NULL DEFAULT 0, next_at DOUBLE PRECISION NOT NULL DEFAULT 0,
 lease_until DOUBLE PRECISION NOT NULL DEFAULT 0, last_error TEXT
);
CREATE TABLE IF NOT EXISTS sx_bot_outbox (
 update_id BIGINT NOT NULL, part INTEGER NOT NULL, payload TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'PENDING', message_id BIGINT, last_error TEXT,
 PRIMARY KEY (update_id, part)
);
CREATE INDEX IF NOT EXISTS sx_bot_due ON sx_bot_updates(status,next_at);
CREATE TABLE IF NOT EXISTS sx_bot_artifacts (
 object_key TEXT PRIMARY KEY, sha256 TEXT NOT NULL, bytes BIGINT NOT NULL
);
