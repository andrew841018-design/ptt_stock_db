import boto3
import logging
import subprocess
import os
from datetime import datetime
from dotenv import load_dotenv

_base = os.path.dirname(__file__)
load_dotenv(os.path.join(_base, '.env')) or load_dotenv(os.path.join(_base, '..', '.env'))

S3_BUCKET    = "ptt-sentiment-backup"
DOCKER_PATH  = "/usr/local/bin/docker"
DB_CONTAINER = "ptt_stock_db"


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
        pg_dbname   = os.environ.get("PG_DBNAME",   "stock_analysis_db")

        with open(dump_path, 'w') as f:
            subprocess.run([
                DOCKER_PATH, 'exec',
                '-e', f'PGPASSWORD={pg_password}',
                DB_CONTAINER,
                'pg_dump',
                '-h', pg_host,
                '-p', pg_port,
                '-U', pg_user,
                '-d', pg_dbname,
            ], stdout=f, check=True)
        s3.upload_file(dump_path, S3_BUCKET, s3_key)
        logging.info(f'Backup completed and uploaded to {s3_key}')
    finally:# 上傳完刪除暫存檔（無論成功失敗都清掉）,finally可以避免上傳失敗而沒刪除暫存檔的情況
        if os.path.exists(dump_path):
            os.remove(dump_path)
