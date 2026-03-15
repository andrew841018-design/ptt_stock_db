## import libraries
from web_scraping import scrape_web_page_title,get_previous_page
import requests
from bs4 import BeautifulSoup
import time
from tqdm import tqdm
import logging
import sqlite3
from analysis import clean_article_info,clean_comment_info
logging.basicConfig(level=logging.INFO,format="%(asctime)s - %(levelname)s - %(message)s")#initialize logging
## global variable
MAX_RETRY=5
def web_scraping(): 
    #init    
    url = "https://www.ptt.cc/bbs/stock/index.html" #初始url
    conn=sqlite3.connect("ptt_stock.db")
    for i in tqdm(range(900),desc="爬蟲頁數"):#爬蟲頁數
        retry = 0
        while retry < MAX_RETRY:
            try:
                headers = {"cookie": "over18=1"}
                response = requests.get(url, headers=headers)
                response.raise_for_status()
                soup = BeautifulSoup(response.text, "html.parser")
                if not scrape_web_page_title(headers,url):
                    print("Error: scrape_web_page_title")
                    break
                time.sleep(0.5)#delay for 0.5 seconds
                page_soup=soup.find_all("div",class_="btn-group btn-group-paging")
                prev_url=get_previous_page(page_soup)
                if prev_url:
                    url="https://www.ptt.cc"+prev_url
                else:
                    logging.info("沒有上一頁")
                    break
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
    logging.info("爬蟲完成")
    conn.close()
def analysis():
    conn=sqlite3.connect('ptt_stock.db')
    cursor=conn.cursor()
    tqdm.pandas()
    # create new column
    for sql in ["ALTER TABLE ptt_stock_article_info ADD COLUMN Article_Sentiment_Score INTEGER",
                "ALTER TABLE ptt_stock_comment_info ADD COLUMN Comment_Sentiment_Score INTEGER",
                "ALTER TABLE ptt_stock_article_info ADD COLUMN Published_Time INTEGER"]:
        try:
            cursor.execute(sql)
            conn.commit()
        except sqlite3.OperationalError:
            print(f"Column {sql} already exist")
    conn.close()
    clean_article_info()
    clean_comment_info()
    print("Data cleaning completed")

if __name__=="__main__":
    web_scraping()#scrape data from ptt and store in database
    analysis()#clean data and calculate sentiment score