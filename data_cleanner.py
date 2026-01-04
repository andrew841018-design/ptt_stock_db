import pandas as pd
import datetime
import re
from analysis import numberic_push_count
def clean_all(df,table='ptt_stock_article_info'):#default table is ptt_stock_article_info
    if(table=='ptt_stock_article_info'):
        df['Push_count']=df['Push_count'].apply(numberic_push_count)
    elif(table=='ptt_stock_comment_info'):
        ###TODO: ptt_stock_comment_info related format operations
        pass
    return df