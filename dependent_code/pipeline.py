import sys
import logging
from tqdm import tqdm

from scrapers.ptt_scraper import PttScraper
from scrapers.cnyes_scraper import CnyesScraper
from scrapers.tw_stock_fetcher import TwseFetcher
from scrapers.reddit_scraper import RedditScraper
from scrapers.us_stock_fetcher import UsStockFetcher
from QA import QA_checks
from ge_validation import ge_validate

# stream=sys.stdout：logging 寫 stdout，tqdm 保持 stderr，redirect 時乾淨分離
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    stream=sys.stdout,
)


def scraping():
    """執行所有文章類爬蟲，新增來源只需在這裡加一行"""
    scrapers = [PttScraper(), CnyesScraper(), RedditScraper()]
    for scraper in tqdm(scrapers, desc="爬蟲來源", file=sys.stderr):
        scraper.run()


if __name__ == "__main__":
    scraping()
    TwseFetcher().run()   # 股價類，不繼承 BaseScraper，單獨呼叫
    UsStockFetcher().run()
    QA_checks()
    try:
        ge_validate()
    except Exception as e:
        logging.warning(f"GE 驗證失敗：{e}")
