import boto3
import logging
import subprocess
import os
from datetime import datetime
from config import PG_CONFIG, S3_BUCKET, DOCKER_PATH, DB_CONTAINER


s3 = boto3.client('s3')


def backup_database():
    timestamp = datetime.now().strftime("%Y%m%d%H%M")
    s3_key    = f'backup_{timestamp}.sql'
    dump_path = f'/tmp/backup_{timestamp}.sql'

    try:
        with open(dump_path, 'w') as f:
            subprocess.run([
                DOCKER_PATH, 'exec',
                '-e', f'PGPASSWORD={PG_CONFIG["password"]}',
                DB_CONTAINER,
                'pg_dump',
                '-h', PG_CONFIG['host'],
                '-p', str(PG_CONFIG['port']),
                '-U', PG_CONFIG['user'],
                '-d', PG_CONFIG['dbname'],
            ], stdout=f, check=True)
        s3.upload_file(dump_path, S3_BUCKET, s3_key)
        logging.info(f'Backup completed and uploaded to {s3_key}')
    finally:# 上傳完刪除暫存檔（無論成功失敗都清掉）,finally可以避免上傳失敗而沒刪除暫存檔的情況
        if os.path.exists(dump_path):
            os.remove(dump_path)


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
    backup_database()
