import logging
from tqdm import tqdm

from scrapers.ptt_scraper import PttScraper
from scrapers.cnyes_scraper import CnyesScraper
from scrapers.twse_fetcher import TwseFetcher
from QA import QA_checks

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


def scraping():
    """執行所有來源的爬蟲，新增來源只需在這裡加一行"""
    scrapers = [
        PttScraper(),
        CnyesScraper(),
    ]
    for scraper in tqdm(scrapers, desc="爬蟲來源"):
        scraper.run()


if __name__ == "__main__":
    scraping()
    TwseFetcher().run()
    QA_checks()
