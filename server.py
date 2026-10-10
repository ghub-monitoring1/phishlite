#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PhishLite — 轻量级钓鱼演练追踪服务 (zero dependency, stdlib only)
================================================================
端点:
  /px/<rid>.png          1x1 透明像素, 记录"谁/何时/何IP"打开了邮件
  /c/<rid>?url=<enc>     302 跳转, 记录"谁/何时"点击了钓鱼链接
  /report                网页监控看板 (自动刷新/搜索/明暗主题)
  /api/stats             看板数据 JSON (供自定义集成)
  /log                   原始事件 JSONL
  /health                健康检查

数据文件 (自动生成, 无需数据库):
  track_log.jsonl        逐条事件 (append-only)
  rid_map.txt            rid -> 邮箱 映射 (由 send.py 生成)

配置: config.json (复制 config.example.json 修改)
"""
import http.server, socketserver, urllib.parse, json, datetime, base64, os

DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.environ.get("CONFIG", os.path.join(DIR, "config.json"))


def load_config():
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"[!] 未找到 {CONFIG_PATH}", flush=True)
        print("    请先: cp config.example.json config.json  然后修改其中字段", flush=True)
        raise SystemExit(1)


CFG = load_config()
PORT = int(os.environ.get("PORT") or CFG["server"].get("port", 8080))
LOG = os.path.join(DIR, "track_log.jsonl")
RIDMAP = os.path.join(DIR, "rid_map.txt")

PIXEL = base64.b64decode("R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7")


def load_map():
    m = {}
    try:
        for line in open(RIDMAP, encoding="utf-8"):
            if "\t" in line:
                rid, email = line.split("\t", 1)
                m[rid.strip()] = email.strip()
    except FileNotFoundError:
        pass
    return m


def read_events():
    events = []
    try:
        for line in open(LOG, encoding="utf-8"):
            try:
                events.append(json.loads(line))
            except Exception:
                pass
    except FileNotFoundError:
        pass
    return events


def log_event(ev_type, rid, ip, ua, extra=""):
    rec = {"time": f"{datetime.datetime.now():%Y-%m-%d %H:%M:%S}",
           "type": ev_type, "rid": rid, "ip": ip, "ua": ua[:150], "extra": extra}
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    email = load_map().get(rid, "?")
    tag = "OPEN" if ev_type == "open" else "CLICK"
    try:
        print(f"[+] {rec['time']} {email} {tag} ip={ip}", flush=True)
    except Exception:  # stdout 编码不支持时(如 LC_ALL=C)绝不能中断请求线程
        try:
            print(f"[+] {rec['time']} rid={rid} {ev_type} ip={ip}", flush=True)
        except Exception:
            pass


# ---------------- 数据聚合 (供看板/日报/自定义集成) ----------------

def build_stats():
    m = load_map()
    events = read_events()
    opens, clicks = {}, {}
    for e in events:
        if e["type"] == "open":
            opens.setdefault(e["rid"], []).append(e)
        elif e["type"] == "click":
            clicks.setdefault(e["rid"], []).append(e)

    known = list(m)   # 面板显示全部已发送目标: 没打开/没点击的也列出, 方便跟进

    def last_time(rid):
        evs = opens.get(rid) or clicks.get(rid)
        return evs[-1]["time"] if evs else ""   # 无行为排最后

    known.sort(key=last_time, reverse=True)

    rows = []
    for rid in known:
        evs, ces = opens.get(rid, []), clicks.get(rid, [])
        if evs or ces:
            head = (evs[0] if evs else ces[0])
            tail = (evs or ces)[-1]
            first, last, ip, ua = head["time"], tail["time"], tail["ip"], head["ua"]
        else:
            first = last = ip = ua = "-"   # 尚无任何行为
        rows.append({
            "email": m[rid], "rid": rid,
            "opened": bool(evs), "open_count": len(evs),
            "first": first, "last": last, "ip": ip,
            "ua": ua, "clicks": len(ces),
            "last_click": ces[-1]["time"] if ces else "",
        })
    total = len(m)
    n_open = len({r for r in opens if r in m})
    n_click = len({r for r in clicks if r in m})
    return {
        "total": total, "opened": n_open, "clicked": n_click,
        "open_rate": f"{n_open * 100 // total}%" if total else "0%",
        "click_rate": f"{n_click * 100 // total}%" if total else "0%",
        "rows": rows,
        "updated": f"{datetime.datetime.now():%Y-%m-%d %H:%M:%S}",
    }


# ---------------- 看板页面 (原生 HTML/CSS/JS, 无外部依赖) ----------------

PAGE = """<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>PhishLite 演练看板</title>
<style>
:root{
  --bg:#f6f8fa;--card:#ffffff;--text:#1f2328;--muted:#656d76;--border:#d0d7de;
  --accent:#4f6ef7;--accent-weak:#eef1fe;--ok:#1a7f37;--ok-weak:#dafbe1;
  --bad:#cf222e;--bad-weak:#ffebe9;--warn:#9a6700;--warn-weak:#fff8c5;
}
@media (prefers-color-scheme: dark){:root{
  --bg:#0d1117;--card:#161b22;--text:#e6edf3;--muted:#8b949e;--border:#30363d;
  --accent:#7c93ff;--accent-weak:#1c2340;--ok:#3fb950;--ok-weak:#0f2e1a;
  --bad:#f85149;--bad-weak:#3d1418;--warn:#d29922;--warn-weak:#2d2200;
}}
*{box-sizing:border-box}
body{margin:0;padding:28px 4vw 60px;background:var(--bg);color:var(--text);
     font:14px/1.6 "Segoe UI","Microsoft YaHei",system-ui,sans-serif}
header{display:flex;flex-wrap:wrap;align-items:baseline;gap:12px;margin-bottom:22px}
h1{font-size:22px;margin:0}
h1 .logo{color:var(--accent)}
.sub{color:var(--muted);font-size:12px}
.refresh{margin-left:auto;font-size:12px;color:var(--muted)}
.dot{display:inline-block;width:8px;height:8px;border-radius:50%;background:var(--ok);
     margin-right:5px;animation:pulse 2s infinite}
@keyframes pulse{50%{opacity:.35}}

.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:14px;margin-bottom:26px}
.card{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:16px 18px}
.card .k{color:var(--muted);font-size:12px}
.card .v{font-size:30px;font-weight:700;margin-top:2px}
.card .r{font-size:11px;color:var(--muted)}
.v.ok{color:var(--ok)} .v.bad{color:var(--bad)}
.bar{height:5px;border-radius:3px;background:var(--border);margin-top:10px;overflow:hidden}
.bar>i{display:block;height:100%;border-radius:3px;background:var(--accent)}

.toolbar{display:flex;flex-wrap:wrap;gap:10px;margin-bottom:12px;align-items:center}
#q{flex:1;min-width:220px;max-width:420px;padding:8px 14px;border:1px solid var(--border);
   border-radius:8px;background:var(--card);color:var(--text);font-size:13px;outline:none}
#q:focus{border-color:var(--accent)}
.legend{font-size:12px;color:var(--muted)}
.legend b{color:var(--text)}

.tablewrap{background:var(--card);border:1px solid var(--border);border-radius:12px;overflow:auto}
table{border-collapse:collapse;width:100%;min-width:860px}
th,td{padding:10px 14px;text-align:left;font-size:13px;border-bottom:1px solid var(--border);white-space:nowrap}
th{color:var(--muted);font-weight:600;font-size:12px;background:var(--bg)}
tr:last-child td{border-bottom:none}
tr.new td{background:var(--accent-weak)}
.badge{display:inline-block;padding:2px 10px;border-radius:99px;font-size:12px;font-weight:600}
.badge.on{background:var(--ok-weak);color:var(--ok)}
.badge.off{background:var(--bg);color:var(--muted);border:1px solid var(--border)}
.badge.click{background:var(--bad-weak);color:var(--bad)}
.mono{font-family:ui-monospace,Consolas,monospace;font-size:12px;color:var(--muted)}
td .maxw{display:block;max-width:220px;overflow:hidden;text-overflow:ellipsis}
.empty{padding:40px;text-align:center;color:var(--muted)}
footer{margin-top:16px;color:var(--muted);font-size:12px}
</style></head><body>

<header>
  <h1><span class="logo">&#127916;</span> PhishLite 演练看板</h1>
  <span class="sub">邮件打开 / 链接点击 实时监控</span>
  <span class="refresh"><span class="dot"></span>10s 自动刷新 · <span id="updated">-</span></span>
</header>

<div class="cards">
  <div class="card"><div class="k">发送目标</div><div class="v" id="c-total">-</div><div class="r">rid_map 映射总数</div></div>
  <div class="card"><div class="k">已打开邮件</div><div class="v ok" id="c-open">-</div>
    <div class="r" id="c-openrate">-</div><div class="bar"><i id="b-open" style="width:0%"></i></div></div>
  <div class="card"><div class="k">点击钓鱼链接</div><div class="v bad" id="c-click">-</div>
    <div class="r" id="c-clickrate">-</div><div class="bar"><i id="b-click" style="width:0%"></i></div></div>
  <div class="card"><div class="k">尚未打开</div><div class="v" id="c-unopen">-  </div><div class="r">可跟进安全提醒</div></div>
</div>

<div class="toolbar">
  <input id="q" type="search" placeholder="搜索邮箱 / IP …">
  <span class="legend">共 <b id="n-shown">0</b> 个目标(含未打开) · 按最近活动排序</span>
</div>

<div class="tablewrap"><table>
<thead><tr>
  <th>邮箱</th><th>状态</th><th>打开次数</th><th>首次查阅</th><th>最近查阅</th>
  <th>查阅 IP</th><th>点击</th><th>最近点击</th><th>User-Agent</th>
</tr></thead>
<tbody id="rows"><tr><td colspan="9" class="empty">加载中…</td></tr></tbody>
</table></div>

<footer>
  注: “打开”= 邮件客户端渲染了追踪像素; “点击”= 点击了跳转链接。
  安全网关预取产生的未知 rid 事件已自动过滤, 不计入统计。
</footer>

<script>
const esc = s => String(s||'').replace(/[&<>"']/g,
  c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

async function refresh(){
  try{
    const d = await (await fetch('/api/stats')).json();
    document.getElementById('c-total').textContent  = d.total;
    document.getElementById('c-open').textContent   = d.opened;
    document.getElementById('c-click').textContent  = d.clicked;
    document.getElementById('c-unopen').textContent = d.total - d.opened;
    document.getElementById('c-openrate').textContent  = '打开率 ' + d.open_rate;
    document.getElementById('c-clickrate').textContent = '点击率 ' + d.click_rate;
    document.getElementById('b-open').style.width  = d.open_rate;
    document.getElementById('b-click').style.width = d.click_rate;
    document.getElementById('updated').textContent = d.updated;

    const q = document.getElementById('q').value.trim().toLowerCase();
    const rows = d.rows.filter(r => !q || r.email.toLowerCase().includes(q) || r.ip.includes(q));
    document.getElementById('n-shown').textContent = rows.length;

    const tb = document.getElementById('rows');
    tb.innerHTML = rows.length ? rows.map(r => `
      <tr class="${r.opened?'':'new'}">
        <td><span class="maxw" title="${esc(r.email)}">${esc(r.email)}</span></td>
        <td>${r.opened?'<span class="badge on">已打开</span>':'<span class="badge off">未打开</span>'}</td>
        <td>${r.open_count}</td>
        <td class="mono">${r.first}</td>
        <td class="mono">${r.last}</td>
        <td class="mono">${esc(r.ip)}</td>
        <td>${r.clicks?'<span class="badge click">已点击 ×'+r.clicks+'</span>':'<span class="badge off">未点击</span>'}</td>
        <td class="mono">${r.last_click||'-'}</td>
        <td class="mono"><span class="maxw" title="${esc(r.ua)}">${esc(r.ua)}</span></td>
      </tr>`).join('')
      : '<tr><td colspan="9" class="empty">暂无目标 — rid_map.txt 为空或 send.py 未运行</td></tr>';
  }catch(e){
    document.getElementById('updated').textContent = '获取失败: ' + e;
  }
}
document.getElementById('q').addEventListener('input', refresh);
refresh();
setInterval(refresh, 10000);
</script>
</body></html>"""


class Handler(http.server.BaseHTTPRequestHandler):

    def do_GET(self):
        try:
            self._route()
        except BrokenPipeError:
            pass  # 客户端提前断开(网关预取常见), 无需处理
        except Exception as e:
            try:
                self.send_error(500, "internal")
            except Exception:
                pass

    def _route(self):
        parsed = urllib.parse.urlparse(self.path)
        parts = parsed.path.strip("/").split("/")

        if len(parts) == 2 and parts[0] == "px":
            rid = parts[1].rsplit(".", 1)[0]
            log_event("open", rid, self.client_address[0], self.headers.get("User-Agent", ""))
            self.send_response(200)
            self.send_header("Content-Type", "image/gif")
            self.send_header("Content-Length", str(len(PIXEL)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(PIXEL)

        elif len(parts) == 2 and parts[0] == "c":
            rid = parts[1]
            target = urllib.parse.parse_qs(parsed.query).get("url", [""])[0]
            log_event("click", rid, self.client_address[0],
                      self.headers.get("User-Agent", ""), target)
            if target:
                self.send_response(302)
                self.send_header("Location", target)
                self.send_header("Content-Length", "0")
                self.end_headers()
            else:
                self.send_response(404)
                self.send_header("Content-Length", "0")
                self.end_headers()

        elif parts and parts[0] == "api" and len(parts) == 2 and parts[1] == "stats":
            body = json.dumps(build_stats(), ensure_ascii=False).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        elif parts and parts[0] in ("report", ""):
            body = PAGE.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        elif parts and parts[0] == "log":
            try:
                body = open(LOG, encoding="utf-8").read().encode()
            except FileNotFoundError:
                body = b"(empty)"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        elif parts and parts[0] == "health":
            self.send_response(200)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"OK")

        else:
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()

    def log_message(self, *a):
        pass


class TS(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


if __name__ == "__main__":
    import sys, io
    try:  # systemd LANG=C 时 stdout=ascii, 强制 utf-8 并忽略不可编码字符
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    print(f"[*] PhishLite 追踪服务启动 0.0.0.0:{PORT}", flush=True)
    print(f"[*] 看板: http://<本机IP>:{PORT}/report   数据: /api/stats   健康: /health", flush=True)
    with TS(("0.0.0.0", PORT), Handler) as httpd:
        httpd.serve_forever()
