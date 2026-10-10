#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PhishLite — 批量发送器 (zero dependency, stdlib only)
====================================================
用法:
  python3 send.py targets.txt                  # 默认读 config.json
  python3 send.py targets.txt --dry-run        # 只生成邮件不发送(保存到 out/)
  python3 send.py targets.txt --only user@x.cn # 只给名单中某几人发

targets.txt 每行一个邮箱, # 开头为注释。

模板 (templates/*.json) — 全部可自定义:
  字段:
    from_name    显示名
    from_addr    From 头地址
    subject      主题 (支持全部占位符)
    body_html    HTML 正文
    body_text    纯文本正文 (可选; 提供则发 multipart/alternative,
                 不渲染 HTML 的客户端也能看到内容, 兼容性更好)
    links        命名链接表 (可选) {"名称": "https://..."}
    attachments  附件列表 (可选) [{"filename": "发票.pdf", "path": "./files/发票.pdf"}]
    vars         自定义变量 (可选) {"部门": "IT部"} -> 正文里写 {部门}
  占位符 (正文/主题任意位置):
    {link}         默认钓鱼链接(点击追踪)
    {link:名称}    命名链接(各自独立追踪, 事件里记录落地 URL 可区分)
    {pixel}        追踪像素(打开即记录)
    {email}        收件人地址
    {rid}          收件人追踪 ID
    {date}         发送日期 2026-01-01
  合并优先级: 模板 vars > campaign.vars (config.json) > 内置占位符

对每个收件人生成唯一 rid (md5(email)[:8])。
rid -> 邮箱 映射自动合并写入 rid_map.txt (重发不丢旧映射)。
"""
import smtplib, sys, time, datetime, random, hashlib, os, urllib.parse, uuid, json, argparse
import email.policy
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from email.utils import formatdate, formataddr
from email.header import Header

DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.environ.get("CONFIG", os.path.join(DIR, "config.json"))


def load_config(path=None):
    p = path or CONFIG_PATH
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"[!] 未找到 {p}", flush=True)
        print("    请先: cp config.example.json config.json  然后修改其中字段", flush=True)
        raise SystemExit(1)


def resolve_mx(domain: str):
    """DNS 直查 MX (可选依赖 dnspython); 失败返回空, 由调用方用配置兜底"""
    try:
        import dns.resolver
        mxs = sorted(dns.resolver.resolve(domain, "MX"), key=lambda r: r.preference)
        return [str(r.exchange).rstrip(".") for r in mxs]
    except Exception:
        return []


def make_rid(email: str) -> str:
    return hashlib.md5(email.encode()).hexdigest()[:8]


def load_template(cfg) -> dict:
    tp = os.path.join(DIR, "templates", cfg["campaign"]["template"])
    with open(tp, encoding="utf-8") as f:
        return json.load(f)


class Renderer:
    """占位符渲染: 内置 {link}/{link:name}/{pixel}/{email}/{rid}/{date} + 自定义 vars"""

    def __init__(self, cfg: dict, tpl: dict, rid: str, rcpt: str):
        self.cfg, self.tpl, self.rid, self.rcpt = cfg, tpl, rid, rcpt
        base = cfg["server"]["base_url"]

        # 链接表: 命名链接 + 默认链接
        self.links = dict(tpl.get("links", {}))
        self.links[""] = cfg["campaign"]["phish_url"]  # "" 即默认 {link}

        self.pixel = (f'<img src="{base}/px/{rid}.png" width="1" height="1" '
                      f'alt="" style="display:none;">')

        # 自定义变量合并: 模板 vars > campaign.vars
        self.vars = dict(cfg["campaign"].get("vars", {}))
        self.vars.update(tpl.get("vars", {}))

    def track_url(self, name: str) -> str:
        """生成点击追踪 URL: /c/<rid>?url=<enc>"""
        target = self.links.get(name)
        if target is None:
            raise KeyError(f"模板引用了未定义的链接 {{{name}}}")
        return f"{self.cfg['server']['base_url']}/c/{self.rid}?url={urllib.parse.quote(target, safe='')}"

    def render(self, text: str) -> str:
        # 先替换自定义 vars, 再替换内置占位符 (含命名链接)
        for k, v in self.vars.items():
            text = text.replace("{" + k + "}", str(v))
        text = text.replace("{pixel}", self.pixel)
        text = text.replace("{email}", self.rcpt)
        text = text.replace("{rid}", self.rid)
        text = text.replace("{date}", f"{datetime.date.today():%Y-%m-%d}")
        # 命名链接 {link:name} 必须先于裸 {link}, 否则 {link: 会先被裸匹配截断
        out, i = [], 0
        while True:
            j = text.find("{link", i)
            if j < 0:
                out.append(text[i:])
                break
            out.append(text[i:j])
            k = text.find("}", j)
            if k < 0:
                out.append(text[j:])
                break
            token = text[j:k + 1]              # {link} 或 {link:name}
            name = token[6:-1] if token.endswith("}") and token != "{link}" else ""
            out.append(self.track_url(name))
            i = k + 1
        return "".join(out)


def build_message(rcpt: str, cfg: dict, tpl: dict) -> bytes:
    rid = make_rid(rcpt)
    r = Renderer(cfg, tpl, rid, rcpt)

    # 顶层容器: 有附件用 mixed, 否则 alternative(html+纯文本) 或纯 html
    attachments = tpl.get("attachments", [])
    has_text = bool(tpl.get("body_text"))
    if attachments:
        msg = MIMEMultipart("mixed")
        body = MIMEMultipart("alternative" if has_text else "related")
    elif has_text:
        msg = MIMEMultipart("alternative")
        body = msg
    else:
        msg = MIMEMultipart("related")
        body = msg

    if has_text:
        body.attach(MIMEText(r.render(tpl["body_text"]), "plain", "utf-8"))
    body.attach(MIMEText(r.render(tpl["body_html"]), "html", "utf-8"))
    if body is not msg:
        msg.attach(body)

    for att in attachments:
        path = att["path"] if os.path.isabs(att["path"]) else os.path.join(DIR, att["path"])
        with open(path, "rb") as f:
            part = MIMEApplication(f.read())
        part.add_header("Content-Disposition", "attachment",
                        filename=("utf-8", "", att.get("filename", os.path.basename(path))))
        msg.attach(part)

    disp = r.render(tpl.get("from_name", ""))
    # 显示名用 RFC2047 编码词, 地址保持明文 (整串直接赋值会把地址也吞进 base64)
    msg["From"] = formataddr((str(Header(disp, "utf-8")), tpl["from_addr"]))
    msg["To"] = f"<{rcpt}>"
    msg["Subject"] = r.render(tpl["subject"])
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = f"<{uuid.uuid4().hex[:16]}.{int(time.time())}@{cfg['campaign']['env_from'].split('@')[-1]}>"

    # policy.SMTP: 序列化为 CRLF 行尾 (RFC 5321 要求, 裸 LF 会被部分网关判畸形)
    return msg.as_bytes(policy=email.policy.SMTP)


def send_one(rcpt: str, msg: bytes, cfg: dict) -> str:
    """单收件人投递。模式(smtp.mode):
       direct -> 仅直连收件域 MX(可伪造 From, 需 VPS 出站25)
       relay  -> 仅走认证中继 smtp.host(25被封/走587/465 时用)
       auto   -> 配了 smtp.host 则中继优先, 失败再退回 MX 直连; 未配则纯直连
    """
    sm = cfg["smtp"]
    mode = sm.get("mode", "auto")

    if mode == "relay":
        if not sm.get("host"):
            raise RuntimeError("smtp.mode=relay 但未配置 smtp.host")
        hosts = [sm["host"]]
    elif mode == "direct":
        hosts = resolve_mx(rcpt.split("@")[-1]) or list(sm.get("fallback_mx", []))
    else:  # auto
        hosts = resolve_mx(rcpt.split("@")[-1]) or list(sm.get("fallback_mx", []))
        if sm.get("host"):
            hosts.insert(0, sm["host"])   # 配了中继则优先
    hosts = list(dict.fromkeys(hosts))[:3]
    if not hosts:
        raise RuntimeError("无可用 SMTP 主机 (mode=%s, DNS 解析失败且未配置 fallback_mx/smtp.host)" % mode)

    # 加密方式: security=plain|starttls|ssl (兼容旧布尔字段 tls=true=starttls)
    sec = sm.get("security") or ("starttls" if sm.get("tls") else "plain")

    err = None
    for i, host in enumerate(hosts):
        try:
            if sec == "ssl":
                smtp_cls, kwargs = smtplib.SMTP_SSL, {}
            else:
                smtp_cls, kwargs = smtplib.SMTP, {}
            with smtp_cls(host, sm["port"], timeout=sm.get("timeout", 30), **kwargs) as s:
                s.ehlo_or_helo_if_needed()
                if sec == "starttls":
                    s.starttls()
                    s.ehlo()
                if sm.get("user"):
                    s.login(sm["user"], sm.get("password", ""))
                s.sendmail(cfg["campaign"]["env_from"], [rcpt], msg)
            return host
        except Exception as e:
            err = e
            if i < len(hosts) - 1:
                time.sleep(20)
    raise err


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("targets", help="目标邮箱列表文件 (每行一个)")
    ap.add_argument("--dry-run", action="store_true", help="只生成邮件不发送, 保存到 out/")
    ap.add_argument("--only", nargs="*", default=[], help="只发名单中的指定邮箱")
    args = ap.parse_args()

    cfg = load_config()
    tpl = load_template(cfg)
    delay = cfg["campaign"].get("delay", [20, 45])
    log_file = os.path.join(DIR, f"send_{datetime.datetime.now():%Y%m%d_%H%M%S}.log")
    rid_map = os.path.join(DIR, "rid_map.txt")

    with open(args.targets, encoding="utf-8") as f:
        rcpts = [l.strip() for l in f if l.strip() and not l.strip().startswith("#")]
    if args.only:
        rcpts = [r for r in rcpts if r in args.only]
    rcpts = sorted(set(rcpts))
    print(f"[+] targets={len(rcpts)} tracker={cfg['server']['base_url']} template={cfg['campaign']['template']}", flush=True)

    # 累计合并 rid 映射(重发/分批发送不丢旧映射)
    existing = {}
    try:
        for line in open(rid_map, encoding="utf-8"):
            if "\t" in line:
                rid, email = line.split("\t", 1)
                existing[rid.strip()] = email.strip()
    except FileNotFoundError:
        pass
    for r in rcpts:
        existing[make_rid(r)] = r
    with open(rid_map, "w", encoding="utf-8") as f:
        for rid, email in sorted(existing.items()):
            f.write(f"{rid}\t{email}\n")
    print(f"[+] rid 映射(累计 {len(existing)} 人) -> {rid_map}", flush=True)

    if args.dry_run:
        out = os.path.join(DIR, "out")
        os.makedirs(out, exist_ok=True)
        for r in rcpts:
            with open(os.path.join(out, f"{make_rid(r)}.eml"), "wb") as f:
                f.write(build_message(r, cfg, tpl))
        print(f"[+] dry-run: {len(rcpts)} 封已生成到 out/ (未发送)", flush=True)
        return

    ok = fail = 0
    with open(log_file, "a", encoding="utf-8") as log:
        for i, rcpt in enumerate(rcpts, 1):
            try:
                host = send_one(rcpt, build_message(rcpt, cfg, tpl), cfg)
                line = f"[{datetime.datetime.now():%H:%M:%S}] ({i}/{len(rcpts)}) {rcpt} rid={make_rid(rcpt)} -> OK via {host}"
                ok += 1
            except smtplib.SMTPResponseException as e:
                line = f"[{datetime.datetime.now():%H:%M:%S}] ({i}/{len(rcpts)}) {rcpt} -> FAIL SMTP {e.smtp_code}"
                fail += 1
            except Exception as e:
                line = f"[{datetime.datetime.now():%H:%M:%S}] ({i}/{len(rcpts)}) {rcpt} -> FAIL {type(e).__name__}: {e}"
                fail += 1
            print(line, flush=True)
            log.write(line + "\n")
            log.flush()
            if i < len(rcpts):
                time.sleep(random.uniform(*delay))
    print(f"[+] 完成: 成功 {ok} / 失败 {fail}", flush=True)


if __name__ == "__main__":
    main()
