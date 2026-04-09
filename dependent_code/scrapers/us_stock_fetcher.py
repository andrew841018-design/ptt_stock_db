import sys
import logging
from datetime import date
from dateutil.relativedelta import relativedelta
from tqdm import tqdm
import pandas as pd
import yfinance as yf

from pg_helper import get_pg
from config import US_STOCK_PRICES_TABLE

US_STOCK_MONTHS = 120  # 每次抓幾個月的歷史資料

_TICKER = "VOO"  # 固定追蹤單一標的


class UsStockFetcher:
    """
    美股 ETF 股價資料抓取器，使用 yfinance。

    不繼承 BaseScraper（股價不是文章）。
    固定追蹤 VOO，寫入 us_stock_prices 表。
    資料來源：Yahoo Finance（yfinance，不需 API key）
    """

    def run(self) -> None:
        """主流程：抓取 VOO 近 N 個月股價，寫入 DB"""
        logging.info(f"開始抓取 {_TICKER} 股價（近 {US_STOCK_MONTHS} 個月）")
        rows = self._fetch_price_data()
        if rows:
            self._save(rows)
            logging.info(f"完成：{_TICKER}，共 {len(rows)} 筆")
        else:
            logging.warning(f"{_TICKER} 股價資料為空，略過")

    def _fetch_price_data(self) -> list:
        """
        從 yfinance 抓 VOO 歷史日線資料。
        回傳 list of dict，每筆對應一個交易日。
        漲跌 change = 當日收盤 - 前一日收盤。
        """
        start = (date.today() - relativedelta(months=US_STOCK_MONTHS)).strftime("%Y-%m-%d")
        hist = yf.Ticker(_TICKER).history(start=start)

        if hist.empty:
            logging.warning(f"yfinance 回傳空資料：{_TICKER}")
            return []

        hist["change"] = (hist["Close"] - hist["Close"].shift(1)).round(2)

        rows = []
        """
          hist是一個df,iterrows()遍歷df的每一行，但每一個迴圈，都能存取到任一個column的值
          idx固定不動，row涵蓋由左到右所有column的值，想成一個陣列
          所以你可以如下面這種方式去取值
        """
        for idx, row in hist.iterrows():
            rows.append({
                "trade_date": idx.date(),
                "close":      round(float(row["Close"]), 2),
                "change":     float(row["change"]) if not pd.isna(row["change"]) else None,
            })
        return rows

    def _save(self, rows: list) -> None:
        """寫入 us_stock_prices，重複 trade_date 自動略過"""
        with get_pg() as conn:
            with conn.cursor() as cur:
                for row in tqdm(rows, desc=f"{_TICKER} 寫入", file=sys.stderr, leave=False):
                    cur.execute(f"""
                        INSERT INTO {US_STOCK_PRICES_TABLE}
                            (trade_date, close, change)
                        VALUES (%s, %s, %s)
                        ON CONFLICT (trade_date) DO NOTHING
                    """, (
                        row["trade_date"],
                        row["close"],
                        row["change"],
                    ))
