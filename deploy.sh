#!/bin/bash
# ============================================================
# PhishLite 一键部署 (Linux + systemd)
# 用法: bash deploy.sh          (在项目目录内执行)
#   PORT 环境变量可覆盖端口:  PORT=9000 bash deploy.sh
# ============================================================
set -e

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

# ---------- 依赖检查 ----------
python3 --version >/dev/null 2>&1 || { echo "!! 缺少 python3"; exit 1; }
for f in server.py send.py config.example.json; do
  [ -f "$DIR/$f" ] || { echo "!! 缺 $f"; exit 1; }
done
if [ ! -f "$DIR/config.json" ]; then
  cp "$DIR/config.example.json" "$DIR/config.json"
  echo "[*] 已从 config.example.json 生成 config.json, 记得改成你的服务器信息!"
fi

# 端口: 环境变量 > config.json
PORT="${PORT:-$(python3 -c "import json;print(json.load(open('config.json'))['server']['port'])")}"

# ---------- systemd 常驻服务 ----------
echo "[*] 配置 systemd (端口 $PORT)"
cat > /etc/systemd/system/phishlite.service <<EOF
[Unit]
Description=PhishLite phishing-simulation tracking server
After=network.target

[Service]
Type=simple
WorkingDirectory=$DIR
ExecStart=/usr/bin/python3 $DIR/server.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

cat > /etc/systemd/system/phishlite-report.service <<EOF
[Unit]
Description=PhishLite daily report

[Service]
Type=oneshot
ExecStart=/usr/bin/python3 $DIR/daily_report.py
EOF

cat > /etc/systemd/system/phishlite-report.timer <<'EOF'
[Unit]
Description=Daily 09:30 PhishLite report

[Timer]
OnCalendar=*-*-* 09:30:00
Persistent=true

[Install]
WantedBy=timers.target
EOF

systemctl daemon-reload
systemctl enable --now phishlite.service
systemctl enable --now phishlite-report.timer

# ---------- 防火墙 ----------
echo "[*] 放行 $PORT/tcp"
if command -v firewall-cmd >/dev/null 2>&1; then
    firewall-cmd --permanent --add-port="$PORT/tcp" >/dev/null && firewall-cmd --reload
elif command -v ufw >/dev/null 2>&1; then
    ufw allow "$PORT/tcp"
else
    echo "(无 firewalld/ufw; 请在云控制台安全组放行 $PORT/TCP)"
fi

# ---------- 自检 ----------
sleep 2
echo "[*] 自检"
echo -n "  phishlite 服务: "; systemctl is-active phishlite
echo -n "  health: "; curl -s -o /dev/null -w "%{http_code}\n" "http://127.0.0.1:$PORT/health" || echo "  (health 检查失败)"

IP=$(hostname -I 2>/dev/null | awk '{print $1}')
cat <<DONE

============== PhishLite 部署完成 ==============
[看板]  http://$IP:$PORT/report     (10 秒自动刷新)
[数据]  http://$IP:$PORT/api/stats  (JSON, 可接入自有看板)

[下一步]
1. 编辑 config.json        (服务器地址 / SMTP / 钓鱼链接 / 模板)
2. 编辑 templates/*.json   (发件人 / 主题 / 正文话术)
3. 准备 targets.txt        (每行一个邮箱)
4. 先试 1 人:   echo "you@example.com" > targets.txt
                python3 send.py targets.txt --dry-run   # 先干跑看邮件内容
                python3 send.py targets.txt             # 真实发送
5. 全量发送:    nohup python3 send.py targets.txt > send.out 2>&1 &
[日常] 每天 09:30 自动日报: daily_report.txt
       实时事件: journalctl -u phishlite -f
===============================================
DONE
