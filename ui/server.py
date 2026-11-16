# -*- coding: utf-8 -*-
"""E 层 · 本地网页界面（只用标准库，不装任何依赖）。

    python ui\\server.py            # 浏览器打开 http://127.0.0.1:8765

只监听 127.0.0.1；文件读取限制在本仓内。
密钥只写本机配置，永不入仓。
"""
from __future__ import annotations

import json
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UI_DIR = os.path.join(ROOT, "ui")
NOTES = os.path.join(ROOT, "CS340", "06_笔记")
PDF_DIR = os.path.join(ROOT, "CS340", "01_讲义")
LESSONS = os.path.join(ROOT, "CS340", "_lessons")
API_DIR = os.path.join(ROOT, "api")
LOG_DIR = os.path.join(ROOT, "_logs")
USER_DIR = os.path.join(os.path.expanduser("~"), ".pluma")
CFG_PATH = os.path.join(USER_DIR, "api.json")
FAV_PATH = os.path.join(USER_DIR, "favorites.json")
USAGE_PATH = os.path.join(LOG_DIR, "usage.jsonl")
HOST, PORT = "127.0.0.1", 8765
VERSION = "1.5.0"
BOOK_NAME = "CS340_九讲合订本_讲义.pdf"

# ---------- 主机上线（局域网 + 8 位访问码）----------
# 2026-11-16 用户定 A 方案：只在跑服务的这台电脑上线；同一 WiFi 的平板/手机用访问码打开。
# 访问码在启动时生成一次，存 %USERPROFILE%\.pluma\host.json；重启就换新码。
LAN = False            # main() 按 --lan 置 true：只有显式要上线才对外监听
ACCESS_CODE = ""       # 8 位数字；LAN=False 时为空
HOST_PATH = os.path.join(os.path.expanduser("~"), ".pluma", "host.json")
NOTES_DIR = os.path.join(os.path.expanduser("~"), ".pluma", "notes")
PDFJS_DIR = os.path.join(ROOT, "tools", "print", "pdfjs")

sys.path.insert(0, API_DIR)
try:
    import client as api_client  # noqa: E402
except Exception:  # noqa: BLE001
    api_client = None

# 单价（元 / 百万 token）：DeepSeek 公开价，仅用于「估算」，界面标明是估
PRICE = {
    "deepseek-flash": {"in": 0.5, "out": 2.0},
    "deepseek-v4-pro": {"in": 2.0, "out": 8.0},
}
MODELS = [
    # 2026-11-16 用户定：只留这两档（4.1 Flash / 4.1 Pro）。
    # 注意 id 不能改：接口 GET /models 实测只返回 deepseek-flash 与 deepseek-v4-pro
    # （python api\client.py --check 可复验），把 id 换成带 4.1 的写法会让 /chat/completions 直接 400。
    # 「4.1」只是给人看的档名，改的是 name，不改 id。
    {"id": "deepseek-flash", "name": "DeepSeek 4.1 Flash", "note": "快、便宜；日常生成够用"},
    {"id": "deepseek-v4-pro", "name": "DeepSeek 4.1 Pro", "note": "更强；长推导、结构复杂的讲次"},
]


# ---------- 会话（一个课件一个会话） ----------
# 2026-11-16：课程会话按课件隔离，存本机用户目录，不进仓库。
# 存 %USERPROFILE%\.pluma\sessions\<课程代码>.json —— 换课件就是另一个文件，上下文不会串。
SESS_DIR = os.path.join(os.path.expanduser("~"), ".pluma", "sessions")


def _safe_code(code: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", code or "default")


def load_lesson(course: str, no: str) -> dict:
    """按 <课程>/_lessons/<讲>.py 读数据（引擎的 builder.load 写死了 CS340，这里按课程走）。"""
    import importlib.util as ilu
    path = os.path.join(ROOT, course, "_lessons", no + ".py")
    if not os.path.isfile(path):
        raise FileNotFoundError(path)
    spec = ilu.spec_from_file_location("lesson_%s_%s" % (_safe_code(course), _safe_code(no)), path)
    mod = ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.LESSON


def find_lesson(course: str) -> list[str]:
    d = os.path.join(ROOT, course, "_lessons")
    if not os.path.isdir(d):
        return []
    return sorted(x[:-3] for x in os.listdir(d) if x.endswith(".py"))


def load_ask_module():
    """engine/_ask.py 当模块用（检索 + 提示词）。"""
    import importlib.util as ilu
    path = os.path.join(ROOT, "engine", "_ask.py")
    if not os.path.isfile(path):
        return None
    spec = ilu.spec_from_file_location("pluma_ask", path)
    mod = ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_session(code: str) -> dict:
    d = _read_json(os.path.join(SESS_DIR, _safe_code(code) + ".json"), {})
    if not isinstance(d, dict):
        d = {}
    msgs = d.get("messages")
    return {"code": code, "messages": msgs if isinstance(msgs, list) else [],
            "updated": d.get("updated", "")}


def save_session(code: str, sess: dict) -> int:
    os.makedirs(SESS_DIR, exist_ok=True)
    sess["code"] = code
    sess["updated"] = time.strftime("%Y-%m-%d %H:%M")
    sess["messages"] = (sess.get("messages") or [])[-200:]  # 只留最近 200 条，防文件无限长
    _write_json(os.path.join(SESS_DIR, _safe_code(code) + ".json"), sess)
    return len(sess["messages"])


# ---------- 配置 ----------
def _read_json(path, default=None):
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return {} if default is None else default


def _write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def load_cfg():
    cfg = _read_json(CFG_PATH)
    default_dir = os.path.join("CS340", "01_讲义")
    out = {
        "provider": cfg.get("provider", "DeepSeek"),
        "base_url": cfg.get("base_url", "https://api.deepseek.com"),
        "model": cfg.get("model", "deepseek-flash"),
        "api_key": cfg.get("api_key", ""),
        "save_dir": cfg.get("save_dir") or default_dir,
        "wizard_done": bool(cfg.get("wizard_done", False)),
        "save_dir_fixed": False,
    }
    # 2026-11-16 实际撞到：某个写入环节把「讲义」写成了 ??，之后每次生成都往 CS340/01_?? 里放。
    # 路径里出现问号就认为被编码破坏，退回默认目录并在界面上说明。
    if "?" in out["save_dir"] or "\ufffd" in out["save_dir"]:
        out["save_dir"] = default_dir
        out["save_dir_fixed"] = True
    # 本机没填 key 时，走 D 层的三级回退（环境变量 / PRTS secrets）
    if not out["api_key"] and api_client is not None:
        try:
            c = api_client.load_config()
            out["api_key"] = c.get("api_key", "")
            out["base_url"] = c.get("base_url", out["base_url"])
            out["provider"] = c.get("provider", out["provider"])
            if not cfg.get("model"):
                out["model"] = c.get("model", out["model"])
        except Exception:  # noqa: BLE001
            pass
    return out


def save_cfg(cfg):
    _write_json(CFG_PATH, cfg)


# ---------- 用量 ----------
def log_usage(model, usage):
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        rec = {"ts": int(time.time()), "model": model,
               "in": int(usage.get("prompt_tokens", 0)),
               "out": int(usage.get("completion_tokens", 0))}
        with open(USAGE_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001
        pass


def usage_summary():
    tin = tout = calls = 0
    cost = 0.0
    if os.path.isfile(USAGE_PATH):
        for line in open(USAGE_PATH, encoding="utf-8"):
            try:
                r = json.loads(line)
            except Exception:  # noqa: BLE001
                continue
            calls += 1
            tin += r.get("in", 0)
            tout += r.get("out", 0)
            p = PRICE.get(r.get("model", ""), {"in": 0.5, "out": 2.0})
            cost += r.get("in", 0) / 1e6 * p["in"] + r.get("out", 0) / 1e6 * p["out"]
    return {"calls": calls, "in": tin, "out": tout, "cost_est": round(cost, 4)}


# ---------- 课程（自动分类 + 收藏） ----------
def discover_courses():
    """扫仓根：含 01_讲义 或 _lessons 的目录就是一「门课」。"""
    meta = _read_json(os.path.join(ROOT, "courses.json"), {})
    favs = set(_read_json(FAV_PATH, {}).get("codes", []))
    out = []
    for name in sorted(os.listdir(ROOT)):
        d = os.path.join(ROOT, name)
        if not os.path.isdir(d) or name.startswith((".", "_")) or name in ("ui", "api", "engine", "tools", "docs"):
            continue
        pdfs = os.path.join(d, "01_讲义")
        les = os.path.join(d, "_lessons")
        if not (os.path.isdir(pdfs) or os.path.isdir(les)):
            continue
        m = meta.get(name, {})
        files = []
        if os.path.isdir(pdfs):
            for fn in sorted(os.listdir(pdfs)):
                if fn.lower().endswith(".pdf"):
                    full = os.path.join(pdfs, fn)
                    files.append({"name": fn, "rel": "%s/01_讲义/%s" % (name, fn),
                                  "size_kb": round(os.path.getsize(full) / 1024),
                                  "pages": _pages(full)})
        lessons = sorted(x[:-3] for x in os.listdir(les) if x.endswith(".py")) if os.path.isdir(les) else []
        out.append({"code": name, "title": m.get("title", name), "en": m.get("en", ""),
                    "desc": m.get("desc", "（未填说明，可在 courses.json 里补）"),
                    "files": files, "lessons": lessons, "fav": name in favs})
    return out


def _pages(pdf_path: str) -> int:
    try:
        import pymupdf
        with pymupdf.open(pdf_path) as doc:
            return doc.page_count
    except Exception:  # noqa: BLE001
        return 0


def safe_join(*parts):
    p = os.path.abspath(os.path.join(ROOT, *parts))
    if not p.startswith(os.path.abspath(ROOT) + os.sep):
        raise PermissionError("路径越界")
    return p


# ---------- 笔记（本机落盘，一个课件一个文件）----------
def load_notes(code: str) -> dict:
    d = _read_json(os.path.join(NOTES_DIR, _safe_code(code) + ".json"), {})
    notes = d.get("notes") if isinstance(d, dict) else None
    return {"code": code, "notes": notes if isinstance(notes, list) else []}


def save_notes(code: str, notes: list) -> int:
    os.makedirs(NOTES_DIR, exist_ok=True)
    keep = [n for n in notes if isinstance(n, dict) and str(n.get("text") or "").strip()][-500:]
    _write_json(os.path.join(NOTES_DIR, _safe_code(code) + ".json"),
                {"code": code, "updated": time.strftime("%Y-%m-%d %H:%M"), "notes": keep})
    return len(keep)


# ---------- 主机上线 ----------
def lan_ip() -> str:
    """拿本机在局域网里的地址（不发包：连一个不可达地址只为读路由表）。"""
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("192.0.2.1", 1))
        return s.getsockname()[0]
    except Exception:  # noqa: BLE001
        try:
            return socket.gethostbyname(socket.gethostname())
        except Exception:  # noqa: BLE001
            return "127.0.0.1"
    finally:
        s.close()


def new_access_code() -> str:
    """8 位数字访问码（避开首 0 以外的麻烦，直接用 8 位随机）。"""
    import secrets
    return "".join(secrets.choice("0123456789") for _ in range(8))


def host_state() -> dict:
    return {"lan": LAN, "ip": lan_ip() if LAN else "127.0.0.1", "port": PORT,
            "code": ACCESS_CODE, "url_local": "http://127.0.0.1:%d/" % PORT,
            "url_lan": ("http://%s:%d/" % (lan_ip(), PORT)) if LAN else "",
            "pdfjs": os.path.isdir(PDFJS_DIR)}


FONT_CANDIDATES = [
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\msyh.ttf",
    r"C:\Windows\Fonts\simhei.ttf",
    r"C:\Windows\Fonts\simsun.ttc",
]


def _cjk_font() -> str:
    for f in FONT_CANDIDATES:
        if os.path.isfile(f):
            return f
    return ""


def build_note_pdf(target_rel: str, title: str, blocks: list) -> dict:
    """把笔记页追加到指定 PDF 末尾，另存为 <原名>_附笔记.pdf（不动原件）。

    blocks: [{"h": "问题", "body": "..."}] —— 按顺序排，长段自动折行、放不下就开新页。
    """
    import pymupdf
    src = safe_join(*target_rel.split("/"))
    if not os.path.isfile(src):
        raise FileNotFoundError(src)
    out = os.path.join(os.path.dirname(src),
                       os.path.splitext(os.path.basename(src))[0] + "_附笔记.pdf")
    doc = pymupdf.open(src)
    before = doc.page_count
    w, h = doc[0].rect.width, doc[0].rect.height
    font = _cjk_font()
    margin, lh, fs = 56.0, 17.0, 10.5
    page = doc.new_page(width=w, height=h)
    y = margin
    stamp = time.strftime("%Y-%m-%d %H:%M")
    fontobj = None
    if font:
        try:
            fontobj = pymupdf.Font(fontfile=font)
        except Exception:  # noqa: BLE001
            fontobj = None

    def measure(s, size):
        """真实字体量宽（之前用 helv × 1.9 估算，中文长行会溢出右边距）。"""
        if fontobj is not None:
            return fontobj.text_length(s, size)
        return pymupdf.get_text_length(s, fontname="helv", fontsize=size)

    def newpage():
        nonlocal page, y
        page = doc.new_page(width=w, height=h)
        y = margin

    def put(text, size=fs, gap=6.0, color=(0, 0, 0)):
        """写一段，按真实字宽折行；本页放不下就翻页。"""
        nonlocal y
        if not font:
            raise RuntimeError("没找到中文字体（msyh.ttc），不能写笔记页")
        width = w - margin * 2
        for raw in str(text).split("\n"):
            line = raw
            while line:
                if measure(line, size) <= width:
                    chunk, line = line, ""
                else:
                    lo, hi = 1, len(line)
                    while lo < hi:                      # 二分找最长能放下的一段
                        mid = (lo + hi + 1) // 2
                        if measure(line[:mid], size) <= width:
                            lo = mid
                        else:
                            hi = mid - 1
                    chunk, line = line[:lo], line[lo:]
                if y > h - margin - lh:
                    newpage()
                page.insert_text((margin, y), chunk, fontsize=size, fontfile=font,
                                 fontname="cjk", color=color)
                y += lh * (size / fs)
        y += gap

    put(title, size=16, gap=4, color=(0.09, 0.09, 0.08))
    put("追加于 %s ｜ 原讲义 %d 页 ｜ 本页起为附页" % (stamp, before),
        size=8.5, gap=10, color=(0.42, 0.41, 0.38))
    if font:
        page.draw_line(pymupdf.Point(margin, y - 4), pymupdf.Point(w - margin, y - 4),
                       color=(0.85, 0.84, 0.81), width=0.6)
    for b in blocks:
        if not str(b.get("body") or "").strip():
            continue
        if b.get("h"):
            put(str(b["h"]), size=10.5, gap=3, color=(0.09, 0.09, 0.08))
        body = str(b["body"])
        if body.startswith("出处："):
            put(body, size=8.5, gap=9, color=(0.48, 0.47, 0.44))
        else:
            put(body, size=9.5, gap=9, color=(0.25, 0.24, 0.22))
    # 页脚：与正本一致的口径
    foot = "本内容由 AI 生成，请自行核实重要信息"
    page.insert_text((margin, h - 26), foot, fontsize=7.5, fontfile=font, fontname="cjk",
                     color=(0.62, 0.61, 0.58))
    doc.save(out, deflate=True, garbage=3)
    after = doc.page_count
    doc.close()
    return {"out": out, "name": os.path.basename(out), "pages_before": before, "pages_after": after}


class Handler(BaseHTTPRequestHandler):
    server_version = "LaPluma/1.2"

    def log_message(self, *a):
        pass

    # ---- 回应工具 ----
    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")  # 2026-11-16：上一次改完界面，用户刷新看到的还是旧页
        self.end_headers()
        self.wfile.write(body)

    def _file(self, path, inline=True):
        if not os.path.isfile(path):
            return self._json({"ok": False, "error": "文件不存在"}, 404)
        ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
        fn = os.path.basename(path)
        # 2026-11-16 真撞到：中文文件名直接拼进 Content-Disposition，http.server 按 latin-1 编码报错，
        # 结果同一个 socket 上先写 200 再写 500（响应头里夹了第二条状态行）——
        # pdf.js 报 Failed to fetch，看着像「文件不存在」。所以 ASCII 回退 + RFC 5987 双写。
        ascii_fn = fn.encode("ascii", "ignore").decode() or "file"
        disp = '%s; filename="%s"; filename*=UTF-8\'\'%s' % (
            "inline" if inline else "attachment", ascii_fn.replace('"', ""),
            urllib.parse.quote(fn))
        self.send_response(200)
        self.send_header("Cache-Control", "no-store")  # 理由同上：本地工具不需要缓存
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(os.path.getsize(path)))
        self.send_header("Content-Disposition", disp)
        self.send_header("Accept-Ranges", "none")
        self.end_headers()
        with open(path, "rb") as f:
            shutil.copyfileobj(f, self.wfile)

    # ---- 访问码（只在 --lan 时生效）----
    def _authed(self):
        if not LAN:
            return True
        if self.client_address[0] in ("127.0.0.1", "::1"):
            return True
        if not ACCESS_CODE:
            return True
        raw = self.headers.get("Cookie") or ""
        for part in raw.split(";"):
            k, _, v = part.strip().partition("=")
            if k == "pluma_access" and v == ACCESS_CODE:
                return True
        return False

    def _set_access_cookie(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Set-Cookie", "pluma_access=%s; Path=/; Max-Age=43200; SameSite=Lax" % ACCESS_CODE)
        self.send_header("Cache-Control", "no-store")
        body = json.dumps({"ok": True}, ensure_ascii=False).encode("utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # ---- GET ----
    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        try:
            if not self._authed():
                if u.path.startswith("/api/"):
                    return self._json({"ok": False, "need_access": True,
                                       "error": "需要访问码：在平板输一次就行"}, 401)
                return self._file(os.path.join(UI_DIR, "access.html"))
            if u.path in ("/access", "/access.html"):
                return self._file(os.path.join(UI_DIR, "access.html"))
            if u.path == "/pdfjs" or u.path.startswith("/pdfjs/"):
                fn = os.path.basename(u.path)
                if not fn:
                    return self._json({"ok": False, "error": "缺文件名"}, 400)
                return self._file(os.path.join(PDFJS_DIR, fn))
            if u.path == "/api/host":
                return self._json(dict(ok=True, **host_state()))
            if u.path == "/api/notes":
                return self._json(dict(ok=True, **load_notes(q.get("code", ["CS340"])[0])))
            if u.path == "/favicon.ico":
                self.send_response(204)
                self.send_header("Cache-Control", "max-age=86400")
                self.end_headers()
                return None
            if u.path in ("/", "/index.html"):
                return self._file(os.path.join(UI_DIR, "index.html"))
            if u.path == "/api/bootstrap":
                cfg = load_cfg()
                return self._json({
                    "ok": True, "version": VERSION,
                    "configured": bool(cfg["api_key"]), "wizard_done": cfg["wizard_done"],
                    "model": cfg["model"], "models": MODELS,
                    "save_dir": cfg["save_dir"], "save_dir_abs": os.path.abspath(os.path.join(ROOT, cfg["save_dir"])),
                    "save_dir_fixed": cfg.get("save_dir_fixed", False),
                    "courses": discover_courses(), "usage": usage_summary(),
                })
            if u.path == "/api/balance":
                cfg = load_cfg()
                if api_client is None or not cfg["api_key"]:
                    return self._json({"ok": False, "error": "未配置 key"})
                try:
                    body = api_client._get(cfg["base_url"].rstrip("/") + "/user/balance", cfg["api_key"])
                    infos = body.get("balance_infos", [])
                    cny = next((x for x in infos if x.get("currency") == "CNY"), None)
                    return self._json({"ok": True, "available": body.get("is_available"),
                                       "currency": (cny or {}).get("currency", "CNY"),
                                       "balance": (cny or {}).get("total_balance", "0.00")})
                except Exception as e:  # noqa: BLE001
                    return self._json({"ok": False, "error": str(e)})
            if u.path == "/api/session":
                # 会话读取：一个课件一个会话，文件在 %USERPROFILE%\.pluma\sessions
                return self._json(dict(ok=True, **load_session(q.get("code", ["CS340"])[0])))
            if u.path == "/api/pdf":
                rel = q.get("p", [""])[0]
                return self._file(safe_join(*rel.split("/")))
            return self._json({"ok": False, "error": "无此路由"}, 404)
        except PermissionError as e:
            return self._json({"ok": False, "error": str(e)}, 403)
        except Exception as e:  # noqa: BLE001
            return self._json({"ok": False, "error": repr(e)}, 500)

    # ---- POST ----
    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        try:
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n).decode("utf-8")) if n else {}
        except Exception:  # noqa: BLE001
            body = {}
        try:
            if u.path == "/api/access":
                # 平板输码：对一次就给 12 小时的 cookie；码本身只在本机打印
                if not LAN:
                    return self._json({"ok": False, "error": "这台电脑没开上线模式（要用 --lan 启动）"}, 400)
                if str(body.get("code") or "").strip() == ACCESS_CODE and ACCESS_CODE:
                    return self._set_access_cookie()
                return self._json({"ok": False, "error": "访问码不对"}, 403)
            if not self._authed():
                return self._json({"ok": False, "need_access": True, "error": "需要访问码"}, 401)
            if u.path == "/api/notes":
                code = str(body.get("code") or "CS340")
                cur = load_notes(code)["notes"]
                act = str(body.get("action") or "add")
                if act == "add":
                    note = body.get("note") or {}
                    text = str(note.get("text") or "").strip()
                    if not text:
                        return self._json({"ok": False, "error": "空笔记"}, 400)
                    cur.append({"p": int(note.get("p") or 1), "text": text[:2000],
                                "at": time.strftime("%Y-%m-%d %H:%M"),
                                "hhmm": time.strftime("%H:%M")})
                elif act == "del":
                    i = int(body.get("index", -1))
                    if not (0 <= i < len(cur)):
                        return self._json({"ok": False, "error": "没有这一条"}, 400)
                    cur.pop(i)
                elif act == "clear":
                    cur = []
                else:
                    return self._json({"ok": False, "error": "未知动作：%s" % act}, 400)
                n = save_notes(code, cur)
                return self._json({"ok": True, "notes": cur, "count": n})
            if u.path == "/api/note/export":
                # 07：选中对话 / 侧栏笔记 → 整理成笔记页 → 追加到指定 PDF 末尾（另存副本）
                code = str(body.get("code") or "CS340")
                target = str(body.get("target") or "").strip()
                if not target:
                    return self._json({"ok": False, "error": "要选一份 PDF 作为追加目标"}, 400)
                items = [x for x in (body.get("items") or []) if isinstance(x, dict)]
                notes = [x for x in (body.get("notes") or []) if isinstance(x, dict)]
                if not items and not notes:
                    return self._json({"ok": False, "error": "没选对话，也没有笔记"}, 400)
                title = str(body.get("title") or "附页：我的笔记").strip()[:80]
                blocks = []

                def _clean(t):
                    # PDF 页上是纯文本：模型回的 **粗体** 与反引号要去掉
                    return str(t or "").replace("```", "").replace("**", "").replace("`", "").strip()
                if notes:
                    for n in notes:
                        blocks.append({"h": "p.%s · %s" % (n.get("p"), n.get("hhmm") or n.get("at") or ""),
                                       "body": _clean(n.get("text"))})
                if items:
                    q = ""
                    k = 0
                    for it in items:
                        txt = _clean(it.get("text"))
                        if not txt:
                            continue
                        if str(it.get("role")) == "user":
                            q = txt[:200]
                            continue
                        k += 1
                        head = "问答 %d" % k + ("：" + q[:36] + ("…" if len(q) > 36 else "") if q else "")
                        blocks.append({"h": head, "body": txt})
                        meta = str(it.get("meta") or "")
                        if meta:
                            blocks.append({"body": "出处：" + meta})
                        q = ""
                if body.get("use_model"):
                    cfg = load_cfg()
                    if api_client is not None and cfg["api_key"]:
                        try:
                            raw = "\n\n".join((b.get("h") + "\n" if b.get("h") else "") + str(b.get("body"))
                                               for b in blocks)
                            msgs = [{"role": "system", "content": (
                                "把下面的问答与笔记整理成一份学习笔记：保留结论、关键步骤与出处，"
                                "不分客套话，用短段与分条，不超过 900 字。")},
                                    {"role": "user", "content": raw[:8000]}]
                            out = api_client.chat(msgs, model=cfg["model"])
                            log_usage(out.get("model", cfg["model"]), out.get("usage", {}))
                            blocks = [{"h": "整理稿（%s）" % cfg["model"], "body": out["text"]}] + blocks
                        except Exception as e:  # noqa: BLE001
                            blocks.insert(0, {"body": "（模型整理失败，下面保留原摘录：%s）" % e})
                res = build_note_pdf(target, title, blocks)
                rel = os.path.relpath(res["out"], ROOT).replace(os.sep, "/")
                return self._json({"ok": True, "file": res["name"], "rel": rel,
                                   "pages_before": res["pages_before"],
                                   "pages_after": res["pages_after"], "out": res["out"]})
            if u.path == "/api/config":
                cfg = load_cfg()
                for k in ("model", "save_dir", "base_url", "provider"):
                    if body.get(k):
                        v = str(body[k])
                        if k == "save_dir" and ("?" in v or "\ufffd" in v):
                            return self._json({"ok": False,
                                               "error": "保存目录里有 ? 或乱码字符，像是编码坏了；请重填"}, 400)
                        cfg[k] = v
                if body.get("api_key"):
                    key = str(body["api_key"]).strip()
                    if not key.startswith("sk-"):
                        return self._json({"ok": False, "error": "key 应以 sk- 开头"}, 400)
                    cfg["api_key"] = key
                if body.get("wizard_done") is not None:
                    cfg["wizard_done"] = bool(body["wizard_done"])
                save_cfg(cfg)
                return self._json({"ok": True, "configured": bool(cfg["api_key"])})
            if u.path == "/api/session":
                # 追加 / 清空：前端提问成功后把问答两边都落盘，关掉再开还在
                code = str(body.get("code") or "CS340")
                act = str(body.get("action") or "append")
                sess = load_session(code)
                if act == "clear":
                    sess["messages"] = []
                    return self._json({"ok": True, "cleared": True, "count": save_session(code, sess)})
                msg = body.get("message") or {}
                text = str(msg.get("text") or "").strip()
                if not text:
                    return self._json({"ok": False, "error": "空消息"}, 400)
                sess["messages"].append({
                    "role": str(msg.get("role") or "user"),
                    "text": text[:4000],
                    "refs": msg.get("refs") or [],
                    "meta": str(msg.get("meta") or ""),
                    "at": time.strftime("%H:%M"),
                })
                return self._json({"ok": True, "count": save_session(code, sess)})
            if u.path == "/api/favorites":
                code = str(body.get("code", ""))
                fav = _read_json(FAV_PATH, {"codes": []})
                codes = set(fav.get("codes", []))
                if not code:
                    return self._json({"ok": False, "error": "缺 code"}, 400)
                codes.symmetric_difference_update({code})
                _write_json(FAV_PATH, {"codes": sorted(codes)})
                return self._json({"ok": True, "fav": code in codes})
            if u.path == "/api/generate":
                no = str(body.get("lesson", "")).strip()
                course = str(body.get("course", "CS340")).strip()
                form = str(body.get("form", "single")).strip() or "single"
                t0 = time.time()
                if form == "book":
                    # 合订本：默认全部讲，按讲号顺序（B 口径：去掉各讲封面与目录）
                    p = subprocess.run([sys.executable, os.path.join(ROOT, "engine", "_book.py")],
                                       cwd=ROOT, capture_output=True, text=True,
                                       encoding="utf-8", errors="replace", timeout=600)
                    log = (p.stdout or "") + (p.stderr or "")
                    copied = ""
                    if p.returncode == 0:
                        copied = self._copy_out(course, "CS340_九讲合订本", str(body.get("save_dir") or ""))
                    return self._json({"ok": p.returncode == 0, "log": log, "form": "book",
                                       "seconds": round(time.time() - t0, 1), "copied": copied})
                avail = sorted(x[:-3] for x in os.listdir(os.path.join(ROOT, course, "_lessons"))
                               if x.endswith(".py")) if os.path.isdir(os.path.join(ROOT, course, "_lessons")) else []
                if no not in avail:
                    return self._json({"ok": False, "error": "没有这一讲：%s" % no}, 400)
                p = subprocess.run([sys.executable, os.path.join(ROOT, "engine", "_make.py"), no],
                                   cwd=ROOT, capture_output=True, text=True,
                                   encoding="utf-8", errors="replace", timeout=300)
                log = (p.stdout or "") + (p.stderr or "")
                copied = ""
                if p.returncode == 0 and body.get("save_dir"):
                    copied = self._copy_out(course, no, str(body["save_dir"]))
                return self._json({"ok": p.returncode == 0, "log": log, "form": "single",
                                   "seconds": round(time.time() - t0, 1), "copied": copied})
            if u.path == "/api/ask":
                # 问课件：先检索，再由模型回答。
                # 2026-11-16：改成「一个课件一个会话」——不传 lesson 就搜整门课；
                # 跨课件必须显式 allow_cross=true，否则永远只在当前这门里找。
                code = str(body.get("course") or "CS340").strip()
                no = str(body.get("lesson") or "").strip()
                allow_cross = bool(body.get("allow_cross"))
                # 2026-11-16：讲次改成勾选多选（05），前端传 lessons 列表；空 = 整门课
                only = [str(x).strip() for x in (body.get("lessons") or []) if str(x).strip()]
                question = str(body.get("question") or "").strip()
                history = body.get("history") or []
                if not (2 <= len(question) <= 500):
                    return self._json({"ok": False, "error": "问题长度要在 2-500 字之间"}, 400)
                mod = load_ask_module()
                if mod is None:
                    return self._json({"ok": False, "error": "缺少 engine/_ask.py"}, 500)
                targets = [(code, no)] if no else [(code, x) for x in find_lesson(code)]
                if only and not no:
                    avail = set(find_lesson(code))
                    targets = [(code, x) for x in only if x in avail] or targets
                if allow_cross:
                    for c in discover_courses():
                        if c["code"] != code:
                            targets.extend((c["code"], x) for x in c["lessons"])
                if not targets:
                    return self._json({"ok": False, "error": "这一门还没有可提问的讲次"}, 400)
                picked, first = [], None
                for (c, n) in targets:
                    try:
                        lesson = load_lesson(c, n)
                    except Exception as e:  # noqa: BLE001
                        if len(targets) == 1:
                            return self._json({"ok": False, "error": "读不到 %s/%s 的数据：%r" % (c, n, e)}, 400)
                        continue
                    if first is None:
                        first = lesson
                    for r in mod.search(lesson, question, top_k=3):
                        r = dict(r)
                        r["course"], r["lesson"] = c, n
                        picked.append(r)
                picked.sort(key=lambda r: -r.get("score", 0))
                picked = picked[:6]
                refs = [{"course": r["course"], "lesson": r["lesson"], "sec": r["sec"],
                         "title": r["title"], "kind": r["kind"], "pages": r["pages"],
                         "text": r["text"][:160]} for r in picked]
                cfg = load_cfg()
                if api_client is None or not cfg["api_key"]:
                    return self._json({"ok": False, "need_key": True, "refs": refs,
                                       "error": "没配置 API 钥匙，不能真问。已检索到的片段在下面可以直接看。"})
                bare = {"code": code, "no": no or "全课",
                        "zh": "（跨讲检索）" if not no else str((first or {}).get("zh", ""))}
                msgs = mod.build_prompt(bare, question, picked)
                hist = [{"role": ("user" if m.get("role") == "user" else "assistant"),
                         "content": str(m.get("text") or "")[:600]}
                        for m in history[-4:] if m.get("text")]
                if hist:
                    msgs = [msgs[0]] + hist + msgs[1:]
                t0 = time.time()
                try:
                    out = api_client.chat(msgs, model=cfg["model"])
                except Exception as e:  # noqa: BLE001
                    return self._json({"ok": False, "error": "模型调用失败：%s" % e, "refs": refs}, 502)
                log_usage(out.get("model", cfg["model"]), out.get("usage", {}))
                return self._json({"ok": True, "answer": out["text"], "model": out["model"],
                                   "seconds": round(time.time() - t0, 1), "refs": refs,
                                   "scope": {"course": code, "lesson": no or "全课",
                                             "cross": allow_cross}})
            return self._json({"ok": False, "error": "无此路由"}, 404)
        except subprocess.TimeoutExpired:
            return self._json({"ok": False, "error": "生成超时（>300 s）"}, 504)
        except Exception as e:  # noqa: BLE001
            return self._json({"ok": False, "error": repr(e)}, 500)

    def _copy_out(self, course, no, dest):
        """成功后把成品复制到用户选的目录（dest 可在仓内，也可绝对路径）。"""
        if not dest:
            return ""
        src_dir = os.path.join(ROOT, course, "01_讲义")
        hit = [f for f in os.listdir(src_dir) if f.startswith(no + "_") and f.endswith(".pdf")]
        if not hit:
            return ""
        dst = dest if os.path.isabs(dest) else os.path.join(ROOT, dest)
        src = os.path.join(src_dir, hit[0])
        target = os.path.join(dst, hit[0])
        # 保存目录就是仓内默认目录时，源就是目标：再 copy2 一次会报「文件被占用」
        if os.path.abspath(src) == os.path.abspath(target):
            return target
        os.makedirs(dst, exist_ok=True)
        shutil.copy2(src, target)
        return target


def main() -> int:
    global HOST, PORT, LAN, ACCESS_CODE
    argv = sys.argv[1:]
    for i, a in enumerate(argv):
        if a == "--lan" or a == "-lan":
            LAN = True
        if a == "--port" and i + 1 < len(argv):
            PORT = int(argv[i + 1])
    # 2026-11-16 真撞到：Windows 允许两个进程同时绑 8765，先启的那个偷偷接着应答，
    # 改完代码看着「没生效」/看到旧界面。启动前先探一下，占用就明说并用别的端口。
    import socket as _sock
    probe = _sock.socket(_sock.AF_INET, _sock.SOCK_STREAM)
    busy = False
    try:
        probe.settimeout(0.4)
        busy = probe.connect_ex(("127.0.0.1", PORT)) == 0
    except Exception:  # noqa: BLE001
        busy = False
    finally:
        probe.close()
    if busy:
        print("端口 %d 已经被占用（可能是上次没关掉的旧服务）。" % PORT)
        print("  先查：Get-NetTCPConnection -LocalPort %d -State Listen" % PORT)
        print("  或换端口：python ui\\server.py --port %d" % (PORT + 1))
        return 4
    if LAN:
        HOST = "0.0.0.0"
        ACCESS_CODE = new_access_code()
        try:
            _write_json(HOST_PATH, {"code": ACCESS_CODE, "at": time.strftime("%Y-%m-%d %H:%M"),
                                   "port": PORT, "ip": lan_ip()})
        except Exception:  # noqa: BLE001
            pass
    srv = ThreadingHTTPServer((HOST, PORT), Handler)
    local = "http://127.0.0.1:%d/" % PORT
    print("羽毛笔 La Pluma v%s · 界面已启动" % VERSION)
    print("  本机    %s" % local)
    if LAN:
        print("  局域网  http://%s:%d/   ← 平板 / 手机用这个" % (lan_ip(), PORT))
        print("  访问码  %s %s   ← 只给对一次（12 小时）" % (ACCESS_CODE[:4], ACCESS_CODE[4:]))
        print("  （本机自己打开不用输码；关掉这个窗口就断，不是云端）")
    else:
        print("  （Ctrl+C 停止；只监听本机，不对外。要让平板打开：加 --lan 重跑）")
    if "--no-browser" not in argv:
        threading.Timer(0.6, lambda: webbrowser.open(local)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
    return 0


if __name__ == "__main__":
    sys.exit(main())
