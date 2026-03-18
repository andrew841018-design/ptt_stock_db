from tqdm import tqdm
import pandas as pd
import re
from config import TABLE_ARTICLE, TABLE_COMMENT
def numberic_push_count(push_count):
    if push_count=="爆":
        return 100
    elif push_count=="XX":
        return -100
    elif push_count.startswith("X"):
        return int(push_count.strip("X"))*-10
    else:
        return int(push_count)
def clean_all(df,table=TABLE_ARTICLE):#default table is ptt_stock_article_info
    if(table==TABLE_ARTICLE):
        df=df.drop_duplicates(subset='Url')#去除重複
        df['Push_count']=df['Push_count'].progress_apply(numberic_push_count)
        df['Push_count']=df['Push_count'].astype(int)
        df['Published_Time']=df['Url'].progress_apply(lambda url:pd.to_datetime(int(re.search(r'M\.(\d+)\.',url).group(1)),unit="s"))+pd.Timedelta(hours=8)
        df['Date']=df['Published_Time'].dt.date
        df['Published_Time']=df['Published_Time'].astype(str)
    elif(table==TABLE_COMMENT):
        df['Message']=df['Message'].str.lstrip(":")
    return df