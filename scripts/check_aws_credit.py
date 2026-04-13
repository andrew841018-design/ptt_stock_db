#!/usr/bin/env python3
"""
每日 AWS credit 燃燒檢查（不依賴 Cost Explorer）

- Cost Explorer / CloudWatch Billing 都要手動在 billing console 開通，這裡直接用
  instance_type × 小時定價粗估，避免 AccessDeniedException
- 每次執行：
  1. 盤點 running EC2 instances 的 instance type
  2. 用硬編碼的 ap-southeast-2 On-Demand 價格，算每月預估花費
  3. 推算到 credit 到期日為止的累計燒量
  4. 超過 WARN_USD 或會燒光，送 macOS 通知

Usage:
  python scripts/check_aws_credit.py
可放進 launchd 每天 08:00 自動跑。
"""
import subprocess
import sys
from datetime import date, datetime
import boto3

# ── 設定 ───────────────────────────────────────────────────────────────
REGION          = "ap-southeast-2"
WARN_USD        = 10.0                  # 剩餘 credit < 此值時警告
CREDIT_EXPIRY   = date(2027, 3, 12)
CREDIT_TOTAL    = 100.0                 # 總 promotional credit
CREDIT_USED_PRIOR = 9.05                # 本 session 開始前已花掉的 credit（手動輸入）

# ap-southeast-2 On-Demand USD/hour（2026 四月價目）
PRICING_USD_PER_HOUR = {
    "t2.micro":  0.0146,
    "t3.micro":  0.0132,
    "t3.small":  0.0264,
    "t3.medium": 0.0528,
}
# EBS gp3 價格：$0.096 per GB-month
EBS_GP3_USD_PER_GB_MONTH = 0.096


def mac_notify(title: str, msg: str) -> None:
    """macOS 原生通知"""
    script = f'display notification "{msg}" with title "{title}"'
    subprocess.run(["osascript", "-e", script], check=False)


def get_running_cost_per_month() -> tuple[float, list[str]]:
    """盤點 running EC2 + EBS，回傳 (月費用, 描述列表)"""
    ec2 = boto3.client("ec2", region_name=REGION)
    desc_lines: list[str] = []
    total = 0.0

    # EC2
    resp = ec2.describe_instances(Filters=[{"Name": "instance-state-name", "Values": ["running"]}])
    for reservation in resp["Reservations"]:
        for inst in reservation["Instances"]:
            itype = inst["InstanceType"]
            hourly = PRICING_USD_PER_HOUR.get(itype, 0.05)  # 未知機型給 $0.05/hr 保守估
            monthly = hourly * 24 * 30
            total += monthly
            desc_lines.append(f"EC2 {inst['InstanceId']} ({itype}): ${monthly:.2f}/月")

    # EBS（只算 in-use）
    vols = ec2.describe_volumes(Filters=[{"Name": "status", "Values": ["in-use"]}])
    for vol in vols["Volumes"]:
        size = vol["Size"]
        monthly = size * EBS_GP3_USD_PER_GB_MONTH
        total += monthly
        desc_lines.append(f"EBS {vol['VolumeId']} ({size}GB): ${monthly:.2f}/月")

    return total, desc_lines


def main() -> int:
    try:
        monthly_cost, lines = get_running_cost_per_month()
    except Exception as e:
        mac_notify("AWS Credit Check 失敗", str(e)[:200])
        print(f"[ERROR] {e}")
        return 1

    today = date.today()
    days_left = (CREDIT_EXPIRY - today).days
    months_left = max(1, days_left / 30)
    projected_burn = monthly_cost * months_left
    projected_total_used = CREDIT_USED_PRIOR + projected_burn
    projected_remaining = CREDIT_TOTAL - projected_total_used

    print(f"[{datetime.now():%Y-%m-%d %H:%M}] 月費用: ${monthly_cost:.2f} | "
          f"到期前預估再燒: ${projected_burn:.2f} | "
          f"到期時剩餘: ${projected_remaining:.2f} | "
          f"剩 {days_left} 天")
    for line in lines:
        print(f"  - {line}")

    if projected_remaining < 0:
        mac_notify("AWS Credit 會燒完！",
                   f"${monthly_cost:.2f}/月 × {months_left:.1f} 月 = ${projected_burn:.2f}，"
                   f"超過剩餘 credit ${CREDIT_TOTAL - CREDIT_USED_PRIOR:.2f}")
    elif projected_remaining < WARN_USD:
        mac_notify("AWS Credit 餘額偏低",
                   f"到期時僅剩 ${projected_remaining:.2f}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
