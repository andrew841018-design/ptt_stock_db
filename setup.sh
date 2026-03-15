#!/bin/bash

# PTT Stock Sentiment Analysis - EC2 環境建置腳本

# 1. 安裝系統套件
sudo apt update && sudo apt install python3-pip git python3-full python3-venv -y

# 3. 建立虛擬環境並安裝套件
python3 -m venv venv
source venv/bin/activate
pip install -r dependent_code/require_lib.txt

# 4. 建立資料庫
cd dependent_code
python3 Create_DB.py

# 5. 執行爬蟲 + 資料清洗 + 情緒分析（需要數小時）
echo "開始爬蟲，請耐心等候..."
python3 pipeline.py
echo "爬蟲完成！"

# 6. 清除佔用的 port
kill $(lsof -t -i:8000) 2>/dev/null
kill $(lsof -t -i:8501) 2>/dev/null

# 7. 後台執行 FastAPI
nohup uvicorn api:app --host 0.0.0.0 --port 8000 &

# 8. 後台執行 Streamlit
nohup streamlit run visualization.py --server.port 8501 --server.address 0.0.0.0 &

echo "部署完成！"
echo "API: http://EC2_IP:8000/docs"
echo "Streamlit: http://EC2_IP:8501"
