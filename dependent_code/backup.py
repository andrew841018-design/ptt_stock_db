import boto3
import logging
import subprocess
import os
from datetime import datetime
from config import PG_CONFIG


s3     = boto3.client('s3')
BUCKET = 'ptt-sentiment-backup'


def backup_database():
    timestamp = datetime.now().strftime("%Y%m%d%H%M")
    s3_key    = f'backup_{timestamp}.sql'
    dump_path = f'/tmp/backup_{timestamp}.sql'

    # pg_dump 匯出成 SQL 檔
    env = os.environ.copy()
    env['PGPASSWORD'] = PG_CONFIG['password']

    #其實就是和在terminal 下cmd一樣意思
    #pg_dump -h localhost -p 5432 -U postgres -d ptt_stock -f /tmp/backup_202603271000.sql
    try:
        subprocess.run([
            'pg_dump',
            '-h', PG_CONFIG['host'],
            '-p', str(PG_CONFIG['port']),
            '-U', PG_CONFIG['user'],
            '-d', PG_CONFIG['dbname'],
            '-f', dump_path
        ], env=env, check=True)
        s3.upload_file(dump_path, BUCKET, s3_key)
        logging.info(f'Backup completed and uploaded to {s3_key}')
    finally:# 上傳完刪除暫存檔（無論成功失敗都清掉）,finally可以避免上傳失敗而沒刪除暫存檔的情況
        if os.path.exists(dump_path):
            os.remove(dump_path)


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
    backup_database()
