## import libraries
from web_scraping import scrape_web_page_title,get_previous_page
import requests
from bs4 import BeautifulSoup
import time
from tqdm import tqdm
import logging
import sqlite3
from analysis import clean_article_info,clean_comment_info
from config import MAX_RETRY, SLEEP_INTERVAL, TABLE_ARTICLE, TABLE_COMMENT
from db_helper import get_db
logging.basicConfig(level=logging.INFO,format="%(asctime)s - %(levelname)s - %(message)s")#initialize logging
def web_scraping(url,headers) :
    retry = 0
    while retry < MAX_RETRY:
        try:
            if not scrape_web_page_title(headers,url):
                logging.error("Error: scrape_web_page_title")
                break
            time.sleep(SLEEP_INTERVAL)#delay for 0.5 seconds
            break;#成功後跳出retry
        except requests.exceptions.Timeout:
            logging.error("請求超時，請稍後再試")
        except requests.exceptions.HTTPError as e:
            logging.error(f"HTTP Error: {e}")
        except requests.exceptions.ConnectionError as e:
            logging.error(f"Connection Error: {e}")
        except Exception as e:
            logging.error(f"Error: {e}")
        retry += 1
def analysis():
    tqdm.pandas()
    # create new column if not exists
    with get_db() as conn:
        cursor=conn.cursor()
        for table,col,dtype in [(TABLE_ARTICLE,'Article_Sentiment_Score','INTEGER'),
                               (TABLE_COMMENT,'Comment_Sentiment_Score','INTEGER'),
                               (TABLE_ARTICLE,'Published_Time','TEXT')]:
            try:
                cursor.execute(f"ALTER TABLE {table} ADD COLUMN {col} {dtype}")
            except sqlite3.OperationalError:
                logging.error(f"Column {col} already exist")
    clean_article_info()
    clean_comment_info()
    logging.info("Data cleaning completed")

if __name__=="__main__":
    url = "https://www.ptt.cc/bbs/stock/index.html" #初始url
    tqdm.pandas()
    for i in tqdm(range(900),desc="爬蟲頁數"):#爬蟲頁數
        headers = {"cookie": "over18=1"}
        retry = 0
        while retry < MAX_RETRY:
            try:
                response = requests.get(url, headers=headers)
                response.raise_for_status()
                break
            except requests.exceptions.ConnectionError as e:
                logging.error(f"Connection Error: {e}, retry {retry+1}/{MAX_RETRY}")
            except requests.exceptions.HTTPError as e:
                logging.error(f"HTTP Error: {e}, retry {retry+1}/{MAX_RETRY}")
            retry += 1
        else:
            logging.error(f"超過最大重試次數，跳過此頁：{url}")
            continue
        soup = BeautifulSoup(response.text, "html.parser")
        page_soup=soup.find_all("div",class_="btn-group btn-group-paging")
        web_scraping(url,headers)#scrape data from ptt and store in database
        prev_url=get_previous_page(page_soup)
        if prev_url:
            url="https://www.ptt.cc"+prev_url
        else:
            logging.info("沒有上一頁")
            break
    logging.info("爬蟲完成")
    analysis()#clean data and calculate sentiment score