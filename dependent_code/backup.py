import boto3
import logging
import shutil
import subprocess
import os
from datetime import datetime
from dotenv import load_dotenv

_base = os.path.dirname(__file__)
load_dotenv(os.path.join(_base, '.env')) or load_dotenv(os.path.join(_base, '..', '.env'))

S3_BUCKET = os.environ.get("S3_BUCKET", "ptt-sentiment-backup")

# pg_dump on host (Homebrew install location; shutil.which fallback for other envs)
_PG_DUMP_CANDIDATES = ['/opt/homebrew/bin/pg_dump', '/usr/local/bin/pg_dump']


def _find_pg_dump() -> str:
    for path in _PG_DUMP_CANDIDATES:
        if os.path.isfile(path):
            return path
    found = shutil.which('pg_dump')
    if found:
        return found
    raise FileNotFoundError("pg_dump not found; install PostgreSQL client tools")


s3 = boto3.client('s3')


def backup_database():
    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    s3_key    = f'backup_{timestamp}.sql'
    dump_path = f'/tmp/backup_{timestamp}.sql'

    try:
        pg_host     = os.environ.get("PG_HOST",     "localhost")
        pg_port     = os.environ.get("PG_PORT",     "5432")
        pg_user     = os.environ.get("PG_USER",     "postgres")
        pg_password = os.environ.get("PG_PASSWORD",  "")
        pg_dbname   = os.environ.get("PG_DBNAME",   "ptt_stock")

        pg_dump = _find_pg_dump()
        env = {**os.environ, 'PGPASSWORD': pg_password}

        with open(dump_path, 'w') as f:
            subprocess.run([
                pg_dump,
                '-h', pg_host,
                '-p', pg_port,
                '-U', pg_user,
                '-d', pg_dbname,
            ], stdout=f, check=True, env=env)
        s3.upload_file(dump_path, S3_BUCKET, s3_key)
        logging.info(f'Backup completed and uploaded to {s3_key}')
    finally:
        if os.path.exists(dump_path):
            os.remove(dump_path)
