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
from config import STOCK_PRICES_TABLE

TW_STOCK_MONTHS = 120  # 每次抓幾個月的歷史資料（10 年）

_TICKER = "0050.TW"  # 元大台灣50，yfinance 代碼

_YF_MAX_RETRIES = 3
_YF_BACKOFF_SECONDS = (5, 15, 30)


class TwseFetcher:
    """
    0050 元大台灣50 股價資料抓取器，使用 yfinance。

    改用 yfinance（原為 TWSE API）原因：
    TWSE API 回傳的是名目收盤價，不會因股票分拆而回溯調整歷史資料，
    導致分拆前後的價格序列不連續，buy-and-hold 計算產生嚴重偏差。
    yfinance auto_adjust=True（預設）會自動調整分拆與除息，歷史序列一致。

    不繼承 BaseScraper（股價不是文章）。
    """

    def run(self) -> None:
        """主流程：抓取 0050 近 N 個月股價，寫入 DB"""
        logging.info(f"開始抓取 {_TICKER} 股價（近 {TW_STOCK_MONTHS} 個月）")
        rows = self._fetch_price_data()
        if rows:
            self._save(rows)
            logging.info(f"完成：{_TICKER}，共 {len(rows)} 筆")
        else:
            logging.warning(f"{_TICKER} 股價資料為空，略過")

    def _fetch_price_data(self) -> list:
        """
        從 yfinance 抓 0050.TW 歷史日線資料（split/dividend adjusted）。
        回傳 list of dict，每筆對應一個交易日。
        漲跌 change = 當日收盤 - 前一日收盤。

        yfinance 在 rate limit 期間可能回傳 None，加 retry。
        """
        start = (date.today() - relativedelta(months=TW_STOCK_MONTHS)).strftime("%Y-%m-%d")

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
        for idx, row in hist.iterrows():
            rows.append({
                "trade_date": idx.date(),
                "close":      round(float(row["Close"]), 2),
                "change":     float(row["change"]) if not pd.isna(row["change"]) else None,
            })
        return rows

    def _save(self, rows: list) -> None:
        """寫入 stock_prices，重複 trade_date 以新值覆蓋（保持 adjusted price 最新）"""
        with get_pg() as conn:
            with conn.cursor() as cur:
                for row in tqdm(rows, desc=f"{_TICKER} 寫入", file=sys.stderr, leave=False):
                    cur.execute(f"""
                        INSERT INTO {STOCK_PRICES_TABLE}
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
