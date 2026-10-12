#!/bin/bash
# ============================================================
# PhishLite 一键部署 (Linux + systemd) — 自适应, 零手工配置
# 用法: bash deploy.sh          (在项目目录内执行)
#   PORT 环境变量可覆盖端口:  PORT=9000 bash deploy.sh
# 自适应:
#   - 端口: PORT 环境变量 > config.json (自动同步到 systemd/防火墙/自检/看板地址)
#   - HTTPS: config.json 里 tls.cert/tls.key 存在时自动用 https 自检与提示,
#            还配置了 tls 但证书未签发时会指到 setup-https.sh
#   - 防火墙: firewalld / ufw / 都没有则提示云安全组
#   - 配置: 没有 config.json 自动从样例生成
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

# 端口: 环境变量 > config.json (写回 config.json 保持一致, 邮件里的链接也同步)
PORT="${PORT:-$(python3 -c "import json;print(json.load(open('config.json'))['server']['port'])")}"
if [ "$PORT" != "$(python3 -c "import json;print(json.load(open('config.json'))['server'].get('port'))")" ]; then
  PORT="$PORT" python3 - <<'PYEOF'
import json, os
cfg = json.load(open("config.json", encoding="utf-8"))
cfg["server"]["port"] = int(os.environ["PORT"])
json.dump(cfg, open("config.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
PYEOF
  echo "[*] PORT=$PORT 已写回 config.json"
fi

# TLS 状态: 证书两字段都填了即视为 https 模式
TLS=$(python3 - <<'PYEOF'
import json
cfg = json.load(open("config.json", encoding="utf-8"))
t = cfg["server"].get("tls", {})
print("1" if t.get("cert") and t.get("key") else "")
PYEOF
)
if [ -n "$TLS" ]; then
  CERT=$(python3 -c "import json;print(json.load(open('config.json'))['server']['tls']['cert'])")
  if [ ! -f "$CERT" ]; then
    echo "[!] config.json 已配置 tls 但证书不存在: $CERT"
    echo "    先运行: bash setup-https.sh <你的邮箱>   (签发 Let's Encrypt IP 证书, 无需域名)"
  else
    PROTO=https
  fi
fi
PROTO="${PROTO:-http}"

# ---------- systemd 常驻服务 ----------
echo "[*] 配置 systemd (端口 $PORT, $PROTO)"
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
    ufw allow "$PORT/tcp" || true
else
    echo "(无 firewalld/ufw; 请在云控制台安全组放行 $PORT/TCP)"
fi

# ---------- 自检 ----------
sleep 2
echo "[*] 自检"
echo -n "  phishlite 服务: "; systemctl is-active phishlite
echo -n "  health($PROTO): "; curl -sk -o /dev/null -w "%{http_code}\n" "$PROTO://127.0.0.1:$PORT/health" || echo "  (health 检查失败)"

IP=$(hostname -I 2>/dev/null | awk '{print $1}')
cat <<DONE

============== PhishLite 部署完成 ==============
[看板]  $PROTO://$IP:$PORT/report     (10 秒自动刷新)
[数据]  $PROTO://$IP:$PORT/api/stats  (JSON, 可接入自有看板)

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
[HTTPS] 要让网页邮箱(OWA 等)能测"已读"(不被 Mixed Content 拦截):
       bash setup-https.sh <你的邮箱>    (Let's Encrypt IP 证书, 免域名, 全自动续期)
===============================================
DONE
