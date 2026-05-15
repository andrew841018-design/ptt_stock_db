
from prometheus_client import Counter, Gauge, Histogram, start_http_server



articles_scraped_total = Counter(
    "articles_scraped_total",
    "Total articles scraped",
    ["source"],
)

etl_runs_total = Counter(
    "etl_runs_total",
    "Total ETL pipeline runs",
    ["status"],
)



current_article_count = Gauge(
    "current_article_count",
    "Current total articles in DB",
)

current_sentiment_avg = Gauge(
    "current_sentiment_avg",
    "Current average sentiment score",
    ["market"],
)

active_scrapers = Gauge(
    "active_scrapers",
    "Number of currently running scrapers",
)



scraper_duration_seconds = Histogram(
    "scraper_duration_seconds",
    "Time spent scraping",
    ["source"],
)

etl_step_duration_seconds = Histogram(
    "etl_step_duration_seconds",
    "Time per ETL step",
    ["step"],
)

api_request_duration_seconds = Histogram(
    "api_request_duration_seconds",
    "API request latency",
    ["endpoint"],
)


def start_metrics_server(port: int = 8001) -> None:
    start_http_server(port)
