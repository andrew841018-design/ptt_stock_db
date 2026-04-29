"""
Prometheus 指標定義模組

集中管理所有 Prometheus metrics，供 api.py / pipeline.py / scrapers 匯入使用。
metrics server 預設在 port 8001 啟動，Prometheus 從此 port 抓取指標。

指標分三類：
  - Counter：只增不減的計數器（累計爬取文章數、ETL 執行次數）
  - Gauge：可升可降的即時值（目前文章總數、平均情緒分數、活躍爬蟲數）
  - Histogram：分佈統計（爬蟲耗時、ETL 步驟耗時、API 延遲）
"""

from prometheus_client import Counter, Gauge, Histogram, start_http_server


# ── Counters（累計計數器）────────────────────────────────────────────────────
# 只增不減，重啟歸零。適合統計「總共發生幾次」。

# 爬取文章總數，依來源分（ptt / cnyes / reddit / cnn / wsj / marketwatch）
articles_scraped_total = Counter(
    "articles_scraped_total",
    "Total articles scraped",
    ["source"],
)

# ETL pipeline 執行次數，依結果分（success / failure）
etl_runs_total = Counter(
    "etl_runs_total",
    "Total ETL pipeline runs",
    ["status"],
)


# ── Gauges（即時量測值）──────────────────────────────────────────────────────
# 可升可降，反映當下狀態。

# 資料庫中的文章總數
current_article_count = Gauge(
    "current_article_count",
    "Current total articles in DB",
)

# 目前平均情緒分數，依市場分（tw / us）
current_sentiment_avg = Gauge(
    "current_sentiment_avg",
    "Current average sentiment score",
    ["market"],
)

# 正在執行中的爬蟲數量
active_scrapers = Gauge(
    "active_scrapers",
    "Number of currently running scrapers",
)


# ── Histograms（分佈統計）────────────────────────────────────────────────────
# 自動計算 count / sum / bucket 分位數。適合量測「花多久時間」。

# 單一來源爬蟲耗時（秒），依來源分
scraper_duration_seconds = Histogram(
    "scraper_duration_seconds",
    "Time spent scraping",
    ["source"],
)

# ETL 各步驟耗時（秒），依步驟名稱分
# 步驟名稱對應 pipeline.py 的 Step 0~7：
#   schema / extract / transform / pii / bert / dw_etl / backup / ai_predict
etl_step_duration_seconds = Histogram(
    "etl_step_duration_seconds",
    "Time per ETL step",
    ["step"],
)

# API 端點回應延遲（秒），依 endpoint 路徑分
api_request_duration_seconds = Histogram(
    "api_request_duration_seconds",
    "API request latency",
    ["endpoint"],
)


def start_metrics_server(port: int = 8001) -> None:
    """啟動獨立的 metrics HTTP server

    Prometheus 會定期從 http://<host>:<port>/metrics 抓取指標。
    與 FastAPI 的 port 8000 分離，避免混雜業務流量。
    """
    start_http_server(port)
