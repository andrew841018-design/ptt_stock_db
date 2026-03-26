import boto3
from datetime import datetime
import os
try:
    from dependent_code.config import DB_PATH
except ImportError:
    from config import DB_PATH

s3 = boto3.client('s3')
BACKET = 'ptt-sentiment-backup'
def backup_database():
    timestamp = datetime.now().strftime("%Y%m%d%H%M")
    s3_key = f'backup_{timestamp}.db'
    s3.upload_file(DB_PATH, BACKET, s3_key)
    print(f'Backup completed and uploaded to {s3_key}')

if __name__ == '__main__':
    backup_database()