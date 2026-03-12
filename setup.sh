#!/bin/bash

# PTT Stock Sentiment Analysis - EC2 環境建置腳本

# 1. 安裝系統套件
sudo apt update && sudo apt install python3-pip git python3-full python3-venv -y

# 2. clone repo
git clone https://github.com/andrew841018/Data_base_side_project.git
cd Data_base_side_project

# 3. 建立虛擬環境並安裝套件
python3 -m venv venv
source venv/bin/activate
pip install -r require_lib.txt

# 4. 清除佔用的 port
kill $(lsof -t -i:8000) 2>/dev/null
kill $(lsof -t -i:8501) 2>/dev/null

# 5. 後台執行 FastAPI
nohup uvicorn api:app --host 0.0.0.0 --port 8000 &

# 6. 後台執行 Streamlit
nohup streamlit run visualization.py --server.port 8501 --server.address 0.0.0.0 &

echo "部署完成！"
echo "API: http://EC2_IP:8000/docs"
echo "Streamlit: http://EC2_IP:8501"
