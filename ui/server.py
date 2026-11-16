# -*- coding: utf-8 -*-
"""E 层 · 本地网页界面（只用标准库，不装任何依赖）。

    python ui\\server.py            # 然后浏览器打开 http://127.0.0.1:8765

只监听 127.0.0.1；所有路径都限制在本仓内，防止越权读盘。
"""
from __future__ import annotations

import json
import mimetypes
import os
import shutil
import subprocess
import sys
import threading
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UI_DIR = os.path.join(ROOT, "ui")
NOTES = os.path.join(ROOT, "CS340", "06_笔记")
PDF_DIR = os.path.join(ROOT, "CS340", "01_讲义")
LESSONS = os.path.join(ROOT, "CS340", "_lessons")
API_DIR = os.path.join(ROOT, "api")
HOST, PORT = "127.0.0.1", 8765

sys.path.insert(0, API_DIR)
try:
    import client as api_client  # noqa: E402
except Exception:  # noqa: BLE001
    api_client = None

# 课程表：以后加课只改这里
COURSES = [
    {"code": "CS340", "title": "操作系统", "en": "Operating Systems",
     "desc": "进程、线程、进程间通信、内存管理", "dir": "CS340"},
]


def _pages(pdf_path: str) -> int:
    try:
        import pymupdf
        with pymupdf.open(pdf_path) as doc:
            return doc.page_count
    except Exception:  # noqa: BLE001
        return 0


def course_files(course: dict) -> list[dict]:
    base = os.path.join(ROOT, course["dir"], "01_讲义")
    if not os.path.isdir(base):
        return []
    out = []
    for name in sorted(os.listdir(base)):
        if not name.lower().endswith(".pdf"):
            continue
        full = os.path.join(base, name)
        out.append({
            "name": name,
            "rel": "%s/01_讲义/%s" % (course["dir"], name),
            "size_kb": round(os.path.getsize(full) / 1024),
            "pages": _pages(full),
            "mtime": int(os.path.getmtime(full)),
        })
    return out


def lessons() -> list[str]:
    if not os.path.isdir(LESSONS):
        return []
    return sorted(n[:-3] for n in os.listdir(LESSONS) if n.endswith(".py"))


def safe_join(*parts: str) -> str:
    """拼路径并确认仍在仓内。"""
    p = os.path.abspath(os.path.join(ROOT, *parts))
    if not p.startswith(os.path.abspath(ROOT) + os.sep):
        raise PermissionError("路径越界")
    return p


class Handler(BaseHTTPRequestHandler):
    server_version = "LaPluma/0.3"

    def log_message(self, *a):  # 静音默认访问日志
        pass

    # ---- 工具 ----
    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _file(self, path, inline=True):
        if not os.path.isfile(path):
            return self._json({"ok": False, "error": "文件不存在"}, 404)
        ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
        size = os.path.getsize(path)
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(size))
        self.send_header("Content-Disposition",
                         ('inline' if inline else 'attachment') + '; filename="%s"' %
                         os.path.basename(path).replace('"', ""))
        self.end_headers()
        with open(path, "rb") as f:
            shutil.copyfileobj(f, self.wfile)

    # ---- 路由 ----
    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        try:
            if u.path in ("/", "/index.html"):
                return self._file(os.path.join(UI_DIR, "index.html"))
            if u.path == "/api/courses":
                data = []
                for c in COURSES:
                    d = dict(c)
                    d["files"] = course_files(c)
                    data.append(d)
                return self._json({"ok": True, "courses": data, "lessons": lessons()})
            if u.path == "/api/health":
                info = {"ok": True, "version": "1.0.0", "root": ROOT}
                if api_client is not None:
                    try:
                        info["api"] = api_client.health()
                    except Exception as e:  # noqa: BLE001
                        info["api"] = {"ok": False, "error": str(e)}
                return self._json(info)
            if u.path == "/api/pdf":
                rel = q.get("p", [""])[0]
                return self._file(safe_join(*rel.split("/")))
            if u.path == "/assets/poster.png":
                return self._file(os.path.join(UI_DIR, "poster.png"))
            return self._json({"ok": False, "error": "无此路由"}, 404)
        except PermissionError as e:
            return self._json({"ok": False, "error": str(e)}, 403)
        except Exception as e:  # noqa: BLE001
            return self._json({"ok": False, "error": repr(e)}, 500)

    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        try:
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n).decode("utf-8")) if n else {}
        except Exception:  # noqa: BLE001
            body = {}

        try:
            if u.path == "/api/generate":
                no = str(body.get("lesson", "")).strip()
                if no not in lessons():
                    return self._json({"ok": False, "error": "没有这一讲：%s" % no}, 400)
                p = subprocess.run([sys.executable, os.path.join(ROOT, "engine", "_make.py"), no],
                                   cwd=ROOT, capture_output=True, text=True,
                                   encoding="utf-8", errors="replace", timeout=300)
                return self._json({"ok": p.returncode == 0, "log": (p.stdout or "") + (p.stderr or "")})
            if u.path == "/api/apikey":
                key = str(body.get("key", "")).strip()
                if not key.startswith("sk-"):
                    return self._json({"ok": False, "error": "key 看着不对（应以 sk- 开头）"}, 400)
                cfg = {"provider": "DeepSeek", "base_url": "https://api.deepseek.com",
                       "model": body.get("model") or "deepseek-flash", "api_key": key,
                       "note": "本机配置，勿提交"}
                d = os.path.join(os.path.expanduser("~"), ".pluma")
                os.makedirs(d, exist_ok=True)
                with open(os.path.join(d, "api.json"), "w", encoding="utf-8-sig") as f:
                    json.dump(cfg, f, ensure_ascii=False, indent=2)
                return self._json({"ok": True, "saved": os.path.join(d, "api.json")})
            return self._json({"ok": False, "error": "无此路由"}, 404)
        except subprocess.TimeoutExpired:
            return self._json({"ok": False, "error": "生成超时（>300 s）"}, 504)
        except Exception as e:  # noqa: BLE001
            return self._json({"ok": False, "error": repr(e)}, 500)


def main() -> int:
    srv = ThreadingHTTPServer((HOST, PORT), Handler)
    url = "http://%s:%d/" % (HOST, PORT)
    print("羽毛笔 La Pluma · 界面已启动 %s" % url)
    print("（Ctrl+C 停止；只监听本机，不对外）")
    if "--no-browser" not in sys.argv:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
    return 0


if __name__ == "__main__":
    sys.exit(main())
