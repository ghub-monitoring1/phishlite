#!/bin/bash
# ============================================================
# PhishLite 一键 HTTPS (Let's Encrypt IP 证书, 无需域名)
# ------------------------------------------------------------
# 为什么需要: 网页邮箱(OWA/Gmail 等)是 https 页面, 会按 Mixed Content
#   拦截 http 图片 => http 追踪像素测不到"已读"。
#   Let's Encrypt 2025-02 起支持给裸 IP 签浏览器信任的证书
#   (shortlived profile, 有效期约 6-7 天, 必须自动续期 —— 本脚本已含 cron)。
#
# 用法:  bash setup-https.sh <你的邮箱> [服务器IP]
#   <你的邮箱>   仅用于接收 CA 通知, 任意能收信的邮箱即可
#   [服务器IP]   缺省自动检测本机公网/内网 IP
#
# 效果 (全自动, 无需再手改任何文件):
#   1. 安装 lego (ACME 客户端, 静态二进制零依赖)
#   2. 签发 IP 证书到 /etc/lego/certificates/<IP>.crt|.key   (需 80 端口空闲+安全组放行)
#   3. 自动改写 config.json: base_url -> https://<IP>:<port>, tls 指向证书
#   4. 安装每天自动续期 cron (到期前 2 天才真正续, 续完自动重启服务加载新证书)
#   5. 重启 phishlite 并验证 https 健康检查
# ============================================================
set -e

EMAIL="${1:?用法: bash setup-https.sh <你的邮箱> [服务器IP]}"
IP="${2:-$(hostname -I 2>/dev/null | awk '{print $1}')}"
[ -n "$IP" ] || { echo "!! 无法自动检测 IP, 请显式传入: bash setup-https.sh <邮箱> <IP>"; exit 1; }

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

# ---------- 1. 安装 lego ----------
if ! command -v lego >/dev/null 2>&1; then
  echo "[*] 安装 lego ..."
  LVER=$(curl -s https://api.github.com/repos/go-acme/lego/releases/latest | grep -oP '"tag_name": "\K[^"]+' || true)
  [ -n "$LVER" ] || { echo "!! 获取 lego 最新版本失败, 请手动安装: https://github.com/go-acme/lego/releases"; exit 1; }
  cd /tmp
  curl -fLO "https://github.com/go-acme/lego/releases/download/${LVER}/lego_${LVER#v}_linux_amd64.tar.gz" \
    || curl -fLO "https://github.com/go-acme/lego/releases/download/${LVER}/lego_${LVER}_linux_amd64.tar.gz"
  tar xzf lego_*_linux_amd64.tar.gz
  mv lego /usr/local/bin/
  cd "$DIR"
fi
lego --version

# ---------- 2. 签发 IP 证书 ----------
echo "[*] 签发 IP 证书 ($IP) ... 需 80 端口空闲且安全组放行"
mkdir -p /etc/lego
lego --email "$EMAIL" --http --domains "$IP" --profile shortlived --path /etc/lego run \
  || { echo "!! 签发失败。若提示 profile not offered, 尝试去掉 --profile shortlived 重试(部分 CA 策略不同)"; exit 1; }

CERT="/etc/lego/certificates/${IP}.crt"
KEY="/etc/lego/certificates/${IP}.key"
[ -f "$CERT" ] && [ -f "$KEY" ] || { echo "!! 未找到证书文件 $CERT"; exit 1; }
openssl x509 -in "$CERT" -noout -issuer -dates

# ---------- 3. 自动改写 config.json ----------
echo "[*] 更新 config.json -> https + tls"
python3 - "$CERT" "$KEY" "$IP" <<'PYEOF'
import json, sys
cert, key, ip = sys.argv[1], sys.argv[2], sys.argv[3]
cfg = json.load(open("config.json", encoding="utf-8"))
port = cfg["server"].get("port", 8080)
cfg["server"]["base_url"] = f"https://{ip}:{port}"
cfg["server"]["tls"] = {"cert": cert, "key": key}
json.dump(cfg, open("config.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print(f"    base_url = {cfg['server']['base_url']}")
PYEOF

# ---------- 4. 自动续期 cron ----------
echo "[*] 安装每日续期 cron (到期前 2 天才真正续, 续完自动重启服务)"
cat > /usr/local/bin/lego-renew.sh <<EOF
#!/bin/bash
lego --email "$EMAIL" --http --domains "$IP" --profile shortlived --path /etc/lego \\
     renew --days 2 && systemctl restart phishlite 2>/dev/null || true
EOF
chmod +x /usr/local/bin/lego-renew.sh
( crontab -l 2>/dev/null | grep -v lego-renew.sh
  echo "17 3 * * * /usr/local/bin/lego-renew.sh >> /var/log/lego-renew.log 2>&1" ) | crontab -

# ---------- 5. 重启 + 验证 ----------
PORT=$(python3 -c "import json;print(json.load(open('config.json'))['server']['port'])")
systemctl restart phishlite 2>/dev/null || echo "(phishlite 尚未部署, 之后运行 bash deploy.sh 即可)"
sleep 2
echo "[*] 验证 https ..."
curl -s -o /dev/null -w "  https://$IP:$PORT/health -> HTTP %{http_code} (issuer 已由 openssl 上面确认为 Let's Encrypt)\n" \
     "https://$IP:$PORT/health" || echo "  !! 验证失败, 检查安全组是否放行 $PORT/TCP"

cat <<DONE

============== HTTPS 已启用 ==============
邮件里的追踪像素/链接现在全部走 https://$IP:$PORT
=> 网页邮箱(OWA 等)不再拦截, "已读"可测, 用户全程无感
=> 证书约 6 天有效, 每日 03:17 自动检查续期, 无需人工干预
=========================================
DONE
