import boto3
import os
from datetime import datetime

s3 = boto3.client('s3')
BACKET ='ptt-sentiment-backup'
DB_PATH = 'ptt_sentiment.db'
def backup_database():
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    s3_key = f'backup_{timestamp}.db'
    s3.upload_file(DB_PATH, BACKET, s3_key)
    print(f'Backup completed and uploaded to {s3_key}')

if __name__ == '__main__':
    backup_database()