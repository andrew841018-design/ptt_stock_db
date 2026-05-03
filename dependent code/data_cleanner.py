from analysis import numberic_push_count
from tqdm import tqdm
def clean_all(df,table='ptt_stock_article_info'):#default table is ptt_stock_article_info
    tqdm.pandas()
    if(table=='ptt_stock_article_info'):
        df=df.drop_duplicates(subset='Url')#去除重複
        df['Push_count']=df['Push_count'].progress_apply(numberic_push_count)
    elif(table=='ptt_stock_comment_info'):
        ###TODO: ptt_stock_comment_info related format operations
        pass
    return df