#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PhishLite 每日日报: 已读/点击汇总 + 服务健康, 写 daily_report.txt"""
import json, datetime, urllib.request, os

DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.environ.get("CONFIG", os.path.join(DIR, "config.json"))
now = datetime.datetime.now()
report = [f"===== PhishLite 演练日报 {now:%Y-%m-%d %H:%M} ====="]

try:
    port = json.load(open(CONFIG_PATH, encoding="utf-8"))["server"]["port"]
except Exception:
    port = 8080

try:
    r = urllib.request.urlopen(f"http://127.0.0.1:{port}/api/stats", timeout=5)
    s = json.loads(r.read())
    report.append(f"[服务] 追踪服务运行正常")
    report.append(f"[发送] 目标总数: {s['total']}")
    report.append(f"[已读] {s['opened']}/{s['total']} ({s['open_rate']})")
    report.append(f"[点击] {s['clicked']}/{s['total']} ({s['click_rate']})")
    report.append("")
    report.append("邮箱\t打开次数\t首次查阅\t最近查阅\t点击次数")
    for row in s["rows"]:
        report.append(f"{row['email']}\t{row['open_count']}\t{row['first']}\t{row['last']}\t{row['clicks']}")
except Exception as e:
    report.append(f"[服务] !!! 追踪服务异常: {e} !!!  修复: systemctl restart phishlite")

out = "\n".join(report)
print(out)
with open(os.path.join(DIR, "daily_report.txt"), "w", encoding="utf-8") as f:
    f.write(out + "\n")
