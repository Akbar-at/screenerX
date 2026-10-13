"""Apply the bot schema using a database role authorized to perform migrations."""
import os
from pathlib import Path
import psycopg
from dotenv import load_dotenv

load_dotenv('.env'); load_dotenv('.env.bot')
url=os.getenv('DATABASE_URL')
if not url: raise SystemExit('DATABASE_URL required')
with psycopg.connect(url,connect_timeout=10) as connection:
    for migration in sorted((Path(__file__).resolve().parent.parent/'db/migrations').glob('*.sql')):
        for statement in migration.read_text().split(';'):
            if statement.strip(): connection.execute(statement)
print('Bot schema ready')
