# PhishLite

**轻量级企业钓鱼演练系统** — 零依赖、单文件、可自托管。

```
 ██████╗ ██╗  ██╗██╗██████╗ ███████╗ ██╗██╗     ███████╗
██╔════╝ ██║  ██║██║██╔══██╗██╔════╝██╔╝██║     ╚══███╔╝
██║  ███╗███████║██║██████╔╝█████╗  ██╔╝██║       ███╔╝
██║   ██║██╔══██║██║██╔══██╗██╔══╝  ██╔╝██║      ███╔╝
╚██████╔╝██║  ██║██║██║  ██║███████╗██╔╝███████╗███████╗
 ╚═════╝ ╚═╝  ╚═╝╚═╝╚═╝  ╚═╝╚══════╝╚═╝╚══════╝╚══════╝
```

---

## ⚠️ 使用须知（务必先读）

**本项目仅用于已获书面授权的安全演练。**

1. **书面授权** — 对目标人群发起钓鱼演练，必须有公司/组织的书面授权（安全部门或 HR 联合发起）。无授权使用即违反计算机犯罪相关法律。
2. **合规告知** — 多数司法辖区要求演练前有安全意识培训背景，且不得采集密码等真实凭据。本工具**不采集任何凭据**，只记录"谁/何时打开了邮件、点击了链接 + IP/UA"。
3. **数据最小化** — `track_log.jsonl` 记录了员工行为数据，请按内部数据保管规范存放、演练结束后归档销毁。
4. **勿用于真实攻击** — 伪造发件人功能仅用于测试邮件网关防护效果，用于实际攻击违法。
5. **收尾清理** — 演练结束请关闭服务并收回端口，不要让看板长期暴露公网。

---

## 使用前需要的基础设施

### 1. 目标邮箱必须"匿名可投递"（直连模式的前提）

本工具默认投递方式是**直连收件方 MX、不认证、信封发件人伪造**。这决定了适用边界：

```
你的服务器 ──SMTP──▶ 收件方 ──▶ 收件人邮箱
```

| 收件方环境 | 能否投递 | 说明 |
|---|---|---|
| MX 接受匿名投递（多数企业域） | ✅ | 本工具设计场景 |
| MX 要求 SPF/DMARC 强制（`-all` + `p=reject`） | ⚠️ | 信封 From 用你控制的域即可过 SPF；DMARC 对齐需收件方宽松（`p=none/monitor`） |
| MX 完全封锁外来匿名、必须经中间网关认证 | ✅ 换中继模式 | `smtp.mode=relay` 填认证中继即可（见下方"投递模式"） |
| 收件网关有显示名/关键词过滤（如"人力资源部"+外域） | ⚠️ | 话术避开敏感显示名，或用中性发件人 |

### 投递模式（smtp.mode）

| mode | 行为 | 适用 |
|---|---|---|
| `direct` | 仅直连收件域 MX，匿名投递，From 可伪造 | 目标 MX 开放匿名，VPS 出站 25 未封 |
| `relay` | 仅走 `smtp.host` 指定的认证中继 | VPS 出站 25 被封、或目标封锁匿名投递；可用 587(STARTTLS)/465(SSL)/任意中继端口 |
| `auto`（默认） | 配了 `smtp.host` 则中继优先、失败退回 MX 直连；未配则纯直连 | 拿不准时的默认 |

**端口规则（重要，先搞清楚再配）**：

- **"出站 25 被封"指的是：你的 VPS 主动向外连接对方的 25 端口被云商拦截**——不管你本地监听什么端口、`smtp.port` 填什么，直连模式下最终 TCP 连接都是 `对方IP:25`（MX 几乎只监听 25），这一步被拦就是被拦。
- `smtp.port` 改成别的端口**只在中继模式有意义**（你连中继商的 587/465/2525），改它绕不开出站 25 封锁。
- 判断方法：`telnet mx1.target.com 25` 从 VPS 上执行，连接成功 = 没封；超时 = 被封，改用 `relay` 中继模式（走 587 等任意中继端口，完全不碰出站 25）。

**SPF / DMARC 是怎么对待的**（了解即可，多数情况下不用做任何事）：

- **SPF 查的是"信封 From"的域**。只要信封 From 用**你自己控制的域**（`env_from`），并且给这个域加一条 SPF 包含你的 VPS IP，SPF 检查就是**通过**的。永远不要把信封 From 写成收件人自己的域（如 `xxx@target.com`）——那样必被 450 拒收。
- **邮件头里的 From（收件人看到的显示地址）不受 SPF 限制**，可以按演练需要设置成任意内部地址——这是"伪造显示名"的原理，也是 DMARC 不强制（`p=none`）时它能进收件箱的原因。
- DMARC `p=reject` 的严格环境极少；遇到就老老实实信封/头 From 都用自己的域，只靠话术本身诱骗。

`smtp.security`: `plain` / `starttls` / `ssl` 三选一（兼容旧布尔字段 `tls: true` = starttls）。

**发送前先探测**（判断目标环境是否适用）：

```bash
# 1. 查目标域 MX
nslookup -type=mx target.com

# 2. 测试匿名投递是否被接受（不真发，只看握手响应）
#    220 = 接受连接; 450/554 拒绝本地域伪造; 250 继续 = 匿名通道可用
telnet mx1.target.com 25
> EHLO test
> MAIL FROM:<probe@your-own-domain.com>
> RCPT TO:<you@target.com>     # 发给自己验证全链路
#    250 OK → 环境适用；4xx/5xx → 看拒绝原因调整策略

# 3. 查目标域 DMARC 宽严
nslookup -type=txt _dmarc.target.com
#    p=none 或无记录 → 宽松，伪造头 From 大概率进收件箱
#    p=reject → 严格，需要信封/头 From 同为你控制的域
```

### 2. 一台公网 VPS

- **端口**：追踪服务任意对外 TCP 端口（默认 8080，可改），云安全组放行
- **系统**：任意 Linux（systemd 用于常驻；无 systemd 也能 `python3 server.py` 裸跑）
- **配置**：1 核 512MB 足够（纯 stdlib，无数据库）
- **出站 25**：仅在 `direct` 直连模式下需要（云商默认封 25 时，改 `relay` 中继模式即可，任意中继端口都能走）

### 3. 一个你控制的域（用于信封发件人）

- 域名 DNS 加一条 SPF 包含你的 VPS IP（如 `v=spf1 ip4:YOUR_IP -all`），SPF 检查即通过，提高到达率
- 不需要买企业邮箱，只要这个域能解析即可
- **域与 VPS 无需绑定**：换 VPS 时改一下 SPF 里的 IP 就行

### 4. 钓鱼落地页（可选）

点击追踪只负责记录 + 302 跳转，落地页（训练/提示页）自备。没有落地页也可以只统计点击率。

### 环境自查清单

```
□ 目标域 MX 可 telnet 25 且 RCPT TO 返回 250（或改用 relay 中继模式）
□ 目标域 DMARC 为 p=none 或宽松（或你接受进垃圾箱）
□ VPS 有公网 IP，安全组放行服务端口
□ VPS 出站 25 未封（封了就配 smtp.mode=relay 走中继）
□ 有一个可控制 DNS 的域做信封发件人
□ 已拿到书面授权
```

---

## 功能

- 📧 **批量发送** — 直连收件方 MX 投递，或走自定认证 SMTP；自动 DNS 解析 MX，失败换台重试
- 📎 **附件支持** — 模板里声明附件列表即可，自动 `multipart/mixed`（中文文件名正确 RFC2231 编码）
- 👁 **打开追踪** — 1×1 追踪像素，记录谁/何时/何 IP 打开了邮件
- 🖱 **点击追踪** — 跳转链接代理，记录谁/何时点击了钓鱼链接，302 到真实训练页；一封邮件可放多个独立追踪链接
- 📊 **实时看板** — 打开率/点击率卡片 + 明细表格，10 秒自刷新，搜索，明暗主题自适应
- 🔌 **JSON API** — `/api/stats` 一行 JSON 拉全量数据，可接入自有看板
- 🗓 **每日日报** — systemd timer 每天 09:30 生成文本日报
- 🧩 **模板自定义** — 话术/发件人/主题/附件/多链接/自定义变量全部 JSON 配置，零代码
- ✉️ **纯文本双格式** — 模板提供 `body_text` 时自动发 `multipart/alternative`，不渲染 HTML 的老客户端也能看到内容
- 🏗 **常驻运行** — systemd 守护，崩溃 5 秒拉起，服务器重启自启

## 快速开始

```bash
git clone <this-repo>
cd phishlite

# 1. 配置 (改 server.base_url 为你的服务器地址)
cp config.example.json config.json
vi config.json

# 2. 部署 (需要 root: 写 systemd)
sudo bash deploy.sh

# 3. 试用 1 人
echo "you@yourcompany.com" > targets.txt
python3 send.py targets.txt --dry-run   # 先干跑, 邮件生成到 out/ 可检查
python3 send.py targets.txt             # 真实发送

# 4. 打开看板
open http://YOUR_SERVER:8080/report
```

> 防火墙记得放行端口 (默认 8080): 云控制台安全组 + `ufw allow 8080/tcp`。

## 目录结构

```
phishlite/
├── server.py            # 追踪服务 + 看板 (单文件)
├── send.py              # 批量发送器 (单文件)
├── daily_report.py      # 每日日报 (timer 调用)
├── deploy.sh            # 一键部署 (systemd + 防火墙 + 自检)
├── config.example.json  # 配置样例 (复制为 config.json)
├── targets.example.txt  # 目标名单样例
└── templates/           # 话术模板 (JSON, 自由扩展)
    ├── example.json     # 通用示例 (纯文本+HTML 双格式)
    ├── hr-attendance.json  # 考勤类话术 (多链接+附件+自定义变量)
    └── files/           # 模板附件目录
```

## 全部可配置项

`config.json`:

```jsonc
{
  "server": {
    "port": 8080,                              // 看板+追踪服务端口
    "base_url": "http://YOUR_IP:8080"          // 写进邮件里的追踪地址 (须从收件人网络可达)
  },
  "smtp": {
    "mode": "auto",                            // direct=仅MX直连 | relay=仅认证中继 | auto=中继优先+MX兜底
    "host": "",                                // 中继地址 (relay/auto 模式用; 直连模式留空自动解析 MX)
    "port": 25,                                // 任意端口: 直连对准对方MX(通常25); 中继用 587/465/2525 均可
    "security": "plain",                       // plain | starttls | ssl (465用ssl)
    "user": "", "password": "",                // 认证中继才填
    "timeout": 30,
    "fallback_mx": ["mx1.example.com"]         // DNS 解析失败时的兜底 MX
  },
  "campaign": {
    "template": "example.json",                // templates/ 下的模板名
    "phish_url": "https://training.example.com/login",  // 点击后最终跳转的训练页
    "env_from": "noreply@example.com",         // 信封发件人 (必须是你能控制的域)
    "delay": [20, 45],                         // 每封邮件随机间隔 (秒), 防限速
    "vars": {"公司": "示例公司"}                // 可选: 全局自定义变量 (被模板内 vars 覆盖)
  }
}
```

`templates/*.json` (每个文件一套话术):

```jsonc
{
  "from_name": "显示名",
  "from_addr": "spoofed@example.com",   // From 头地址 (伪造测试用)
  "subject": "主题 (支持占位符)",
  "body_text": "纯文本正文 (可选, 老客户端兼容)",
  "body_html": "HTML 正文",
  "links": {                            // 可选: 命名链接, 每个独立追踪
    "ehr":  "https://ehr.example.com/attendance",
    "help": "https://help.example.com/faq"
  },
  "attachments": [                      // 可选: 附件
    { "filename": "补录指引.pdf", "path": "templates/files/sample.pdf" }
  ],
  "vars": { "部门": "人力资源部", "截止日": "本周五 17:00" }   // 可选: 自定义变量
}
```

### 占位符

| 占位符 | 替换为 |
|---|---|
| `{link}` | 默认钓鱼链接 (config `phish_url`) 的点击追踪跳转 |
| `{link:ehr}` | 命名链接 `links.ehr` 的独立点击追踪跳转 (事件里可区分点了哪个) |
| `{pixel}` | 1×1 追踪像素 `<img>` |
| `{email}` / `{rid}` | 收件人地址 / 追踪 ID |
| `{date}` | 发送日期 |
| `{部门}` 等自定义 | `vars` 里定义的任意变量 |

- 同一封邮件可放**多个追踪链接**，事件日志按落地 URL 区分点了哪个
- **附件**存在时邮件自动升级为 `multipart/mixed`；`body_text` 存在时为 `multipart/alternative`
- `vars` 两层合并: `config.json` 的 `campaign.vars`（全局）被模板内 `vars`（单模板）覆盖
- 新增一套话术 = `templates/` 放一个新 JSON + `config.json` 改 `template` 字段，不用改代码

### 发送控制

```bash
python3 send.py targets.txt --dry-run          # 干跑: 邮件生成到 out/, 可用邮件客户端打开检查
python3 send.py targets.txt --only a@x.com     # 补发/单发指定人
```

## 追踪原理

```
send.py ──SMTP──▶ 收件人邮箱
                     │
        打开邮件 ────┤──▶ GET /px/<rid>.png    ──▶ 记录 open 事件 (rid→邮箱, 时间, IP, UA)
                     │
        点击链接 ────┤──▶ GET /c/<rid>?url=... ──▶ 记录 click 事件 ──▶ 302 → 训练页
                     │
看板 /report ◀── /api/stats ◀── track_log.jsonl + rid_map.txt
```

- `rid = md5(邮箱)[:8]`, 同一邮箱 rid 恒定, 重发不产生重复用户
- 安全网关预取产生的未知 rid 事件自动过滤, 不污染统计
- 所有数据纯本地文件, 无外部依赖、无上报

## API

| 端点 | 说明 |
|---|---|
| `GET /report` | 网页看板 (自动刷新) |
| `GET /api/stats` | 全量统计 JSON |
| `GET /px/<rid>.png` | 追踪像素 (返回 1×1 GIF) |
| `GET /c/<rid>?url=<enc>` | 点击跳转 (302) |
| `GET /log` | 原始事件流 JSONL |
| `GET /health` | 健康检查 |

`/api/stats` 返回示例:

```json
{
  "total": 100, "opened": 37, "clicked": 12,
  "open_rate": "37%", "click_rate": "12%",
  "rows": [
    {"email": "a@x.com", "opened": true, "open_count": 2,
     "first": "2026-01-01 09:00:00", "last": "2026-01-01 10:00:00",
     "ip": "1.2.3.4", "ua": "Mozilla/5.0 ...", "clicks": 1, "last_click": "2026-01-01 10:01:00"}
  ],
  "updated": "2026-01-01 12:00:00"
}
```

## 运维

```bash
systemctl status phishlite        # 服务状态
journalctl -u phishlite -f        # 实时事件流
cat daily_report.txt              # 最新日报 (每天 09:30 自动生成)
python3 daily_report.py           # 手动生成日报
systemctl restart phishlite       # 重启
```

演练结束收尾:

```bash
sudo systemctl disable --now phishlite phishlite-report.timer
tar czf result.tar.gz track_log.jsonl rid_map.txt send_*.log daily_report.txt
```

## 兼容性

| 组件 | 要求 |
|---|---|
| Python | ≥ 3.6（纯标准库，零第三方包） |
| 系统 | Linux / macOS / Windows 均可跑（systemd 部署仅 Linux） |
| CPU/内存 | 1 核 512MB 起步 |
| 可选加速 | `pip3 install dnspython` 后 MX 解析更准（不装也能跑，用 fallback） |
| 浏览器 | 任意现代浏览器（看板原生 HTML/CSS/JS，无 CDN 依赖） |
