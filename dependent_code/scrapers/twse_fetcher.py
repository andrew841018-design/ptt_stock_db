import time
import logging
import requests
from datetime import date
from dateutil.relativedelta import relativedelta  # 方便做「往前推 N 個月」
from tqdm import tqdm
from pg_helper import get_pg
from config import TWSE_STOCK_NO, TWSE_MONTHS, TWSE_SLEEP_INTERVAL, TWSE_TIMEOUT, STOCK_PRICES_TABLE

# TWSE 公開 API（不需要 API key）
# 2024 起官方將 exchangeReport 改為 rwd/zh/afterTrading
_API_URL = "https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY"


class TwseFetcher:
    """
    台灣證交所（TWSE）股價資料抓取器。

    和 BaseScraper 不同：
      - TWSE 抓的是「股價時序資料」，不是文章/留言
      - 寫入獨立的 stock_prices 表，不走 articles/comments 流程
      - 因此不繼承 BaseScraper，是獨立的 class

    資料來源：TWSE 公開 API
      GET https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY
          ?response=json&date=YYYYMMDD&stockNo=2330
      每次回傳「該股票當月」所有交易日資料。
    """

    def run(self) -> None:
        """主流程：逐月抓 0050 股價，寫入 DB"""
        months = self._build_month_list()
        for yyyymmdd in tqdm(months, desc="0050 月份"):
            try:
                rows = self._fetch_row_data(yyyymmdd)
                if rows:
                    self._save(rows)
                time.sleep(TWSE_SLEEP_INTERVAL)
            except requests.RequestException as e:
                logging.warning(f"TWSE 0050 {yyyymmdd} 請求失敗：{e}，略過")

    # ── helper ──────────────────────────────────────────────────────────

    def _build_month_list(self) -> list:
        """
        產生從「TWSE_MONTHS 個月前」到「本月」的月份清單。
        格式：['20240101', '20240201', ..., '20250101']
        TWSE API 的 date 參數只要該月任意一天，固定填 01 就好。
        """
        months = []
        current = date.today().replace(day=1)# 強制設定為該月1號
        for i in range(TWSE_MONTHS):
            #relativedelta(months=i) 往前推 i 個月,format成YYYYMMDD
            months.append((current - relativedelta(months=i)).strftime("%Y%m%d"))
        return list(reversed(months))  # 從舊到新

    def _fetch_row_data(self, yyyymmdd: str) -> list:
        """
        呼叫 TWSE API，回傳當月所有交易日的原始 row list。
        API 回傳格式：
          {
            "stat": "OK",
            "data": [
              ["113/01/02", "...", "...", "開盤價", "最高價", "最低價", "收盤價", "漲跌價差", "..."],
              ...
            ]
          }
        取用 index 0（日期）、3（開盤）、4（最高）、5（最低）、6（收盤）、7（漲跌價差）。
        每個欄位都是字串，數字含逗號（"1,234.56"），需要清洗。
        """
        params = {"response": "json", "date": yyyymmdd, "stockNo": TWSE_STOCK_NO}
        response = requests.get(_API_URL, params=params, timeout=TWSE_TIMEOUT)
        response.raise_for_status()
        data = response.json()

        if data.get("stat") != "OK":
            logging.warning(f"TWSE 0050 {yyyymmdd} stat={data.get('stat')}，略過")
            return []

        return data.get("data", [])

    def _save(self, rows: list) -> None:
        """將一個月的交易資料寫入 stock_prices 表，重複的 trade_date 自動略過"""
        with get_pg() as conn:
            with conn.cursor() as cur:
                for row in rows:
                    trade_date = self._parse_date(row[0])
                    if not trade_date:
                        continue
                    cur.execute(f"""
                        INSERT INTO {STOCK_PRICES_TABLE}
                            (trade_date, open, high, low, close, change)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        ON CONFLICT (trade_date) DO NOTHING
                    """, (
                        trade_date,
                        self._to_float(row[3]),  # 開盤價
                        self._to_float(row[4]),  # 最高價
                        self._to_float(row[5]),  # 最低價
                        self._to_float(row[6]),  # 收盤價
                        self._to_float(row[7]),  # 漲跌價差
                    ))

    @staticmethod # 表示不需要用到self
    def _parse_date(roc_date: str):
        """
        民國年轉西元 datetime.date。
        TWSE 日期格式是民國年：'113/01/02' → 2024-01-02
        """
        try:
            y, m, d = roc_date.split("/")
            return date(int(y) + 1911, int(m), int(d))
        except Exception:
            return None

    @staticmethod
    def _to_float(text: str):
        """'1,234.56' → 1234.56，無法解析回傳 None"""
        try:
            return float(text.replace(",", ""))
        except (ValueError, AttributeError):
            return None

