import sys
import time
import logging
from datetime import date
from typing import Optional
from dateutil.relativedelta import relativedelta
from tqdm import tqdm
import pandas as pd
import yfinance as yf

from pg_helper import get_pg
from config import US_STOCK_PRICES_TABLE

US_STOCK_MONTHS = 120

_TICKER = "VOO"

_YF_MAX_RETRIES = 3
_YF_BACKOFF_SECONDS = (5, 15, 30)


class UsStockFetcher:

    def run(self) -> None:
        logging.info(f"開始抓取 {_TICKER} 股價（近 {US_STOCK_MONTHS} 個月）")
        rows = self._fetch_price_data()
        if rows:
            self._save(rows)
            logging.info(f"完成：{_TICKER}，共 {len(rows)} 筆")
        else:
            logging.warning(f"{_TICKER} 股價資料為空，略過")

    def _fetch_price_data(self) -> list:
        start = (date.today() - relativedelta(months=US_STOCK_MONTHS)).strftime("%Y-%m-%d")

        hist = None
        last_err: Optional[Exception] = None
        for attempt in range(_YF_MAX_RETRIES):
            try:
                hist = yf.Ticker(_TICKER).history(start=start)
                break
            except Exception as exc:
                last_err = exc
                if attempt < _YF_MAX_RETRIES - 1:
                    backoff = _YF_BACKOFF_SECONDS[attempt]
                    logging.warning(
                        f"yfinance {_TICKER} 第 {attempt + 1} 次失敗：{exc}；{backoff}s 後重試"
                    )
                    time.sleep(backoff)

        if hist is None:
            logging.warning(f"yfinance {_TICKER} 連續 {_YF_MAX_RETRIES} 次失敗：{last_err}，本輪略過")
            return []

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
        with get_pg() as conn:
            with conn.cursor() as cur:
                for row in tqdm(rows, desc=f"{_TICKER} 寫入", file=sys.stderr, leave=False):
                    cur.execute(f"""
                        INSERT INTO {US_STOCK_PRICES_TABLE}
                            (trade_date, close, change)
                        VALUES (%s, %s, %s)
                        ON CONFLICT (trade_date) DO UPDATE
                            SET close = EXCLUDED.close,
                                change = EXCLUDED.change
                    """, (
                        row["trade_date"],
                        row["close"],
                        row["change"],
                    ))
