#!/bin/bash
# EC2 modernization setup script
# Run on EC2 as ubuntu user: bash ec2_setup.sh
set -e
export DEBIAN_FRONTEND=noninteractive

log() { echo "[$(date +%H:%M:%S)] $*"; }

log "=== Phase 1: Expand root filesystem to full EBS size ==="
sudo growpart /dev/nvme0n1 1 || log "  growpart already expanded (OK)"
sudo resize2fs /dev/nvme0n1p1
df -h /

log "=== Phase 2: apt update + install deps ==="
sudo apt-get update -qq
sudo apt-get install -y -qq \
    docker.io \
    python3.12-venv \
    python3-pip \
    postgresql-client \
    git \
    fonts-noto-cjk \
    fonts-noto-cjk-extra
# 清掉舊的 matplotlib 字型 cache，讓下次 import 重建並收錄 Noto CJK
rm -f /home/ubuntu/.cache/matplotlib/fontlist-*.json 2>/dev/null || true

log "=== Phase 3: Enable Docker service ==="
sudo systemctl start docker
sudo systemctl enable docker
sudo usermod -aG docker ubuntu || true

log "=== Phase 4: Pull images ==="
sudo docker pull postgres:16
sudo docker pull redis:7

log "=== Phase 5: Start Redis container ==="
sudo docker rm -f redis_cache 2>/dev/null || true
sudo docker run -d \
    --name redis_cache \
    --restart=always \
    -p 6379:6379 \
    redis:7

log "=== Phase 6: Start PostgreSQL container ==="
mkdir -p /home/ubuntu/pgdata
sudo docker rm -f ptt_stock_db 2>/dev/null || true
sudo docker run -d \
    --name ptt_stock_db \
    --restart=always \
    -e POSTGRES_PASSWORD=pw \
    -e POSTGRES_DB=stock_analysis_db \
    -p 5432:5432 \
    -v /home/ubuntu/pgdata:/var/lib/postgresql/data \
    postgres:16

log "  Waiting for PG to accept connections..."
for i in $(seq 1 30); do
    if sudo docker exec ptt_stock_db pg_isready -U postgres 2>/dev/null | grep -q "accepting"; then
        log "  PG ready."
        break
    fi
    sleep 2
done

log "=== Phase 7: git reset --hard origin/main (drop SQLite-era commits) ==="
cd /home/ubuntu/ptt_stock_db
git fetch origin
OLD_HEAD=$(git rev-parse HEAD)
git reset --hard origin/main
NEW_HEAD=$(git rev-parse HEAD)
log "  HEAD: $OLD_HEAD -> $NEW_HEAD"
git log --oneline -3

log "=== Phase 8: Create venv + install requirements ==="
if [ ! -d /home/ubuntu/venv ]; then
    python3 -m venv /home/ubuntu/venv
fi
/home/ubuntu/venv/bin/pip install --quiet --upgrade pip
log "  Installing requirements.txt (this will take a few minutes)..."
/home/ubuntu/venv/bin/pip install --quiet -r /home/ubuntu/ptt_stock_db/dependent_code/requirements.txt

log "=== Phase 9: Disk check ==="
df -h /

log "=== DONE ==="
