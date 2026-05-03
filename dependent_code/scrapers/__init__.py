import sys
import os

# scrapers/ 的上一層是 dependent_code/，把它加進搜尋路徑
# 讓 base_scraper、ptt_scraper 等可以直接 import config、pg_helper
# __file__ = .../dependent_code/scrapers/__init__.py
# dirname  = .../dependent_code/scrapers/
# dirname  = .../dependent_code/
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
