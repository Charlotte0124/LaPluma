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
VERSION = "1.4.0"
BOOK_NAME = "CS340_九讲合订本_讲义.pdf"

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
        self.end_headers()
        self.wfile.write(body)

    def _file(self, path, inline=True):
        if not os.path.isfile(path):
            return self._json({"ok": False, "error": "文件不存在"}, 404)
        ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(os.path.getsize(path)))
        self.send_header("Content-Disposition",
                         ('inline' if inline else 'attachment') + '; filename="%s"' %
                         os.path.basename(path).replace('"', ""))
        self.end_headers()
        with open(path, "rb") as f:
            shutil.copyfileobj(f, self.wfile)

    # ---- GET ----
    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        try:
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
                # 问课件：只在这一讲的内容数据里找片段（不联网、不跨讲），再交给模型回答
                import importlib.util as _ilu
                no = str(body.get("lesson", "")).strip()
                course = str(body.get("course", "CS340")).strip()
                question = str(body.get("question", "")).strip()
                if not (2 <= len(question) <= 500):
                    return self._json({"ok": False, "error": "问题长度要在 2–500 字之间"}, 400)
                path = os.path.join(ROOT, "engine", "_ask.py")
                if not os.path.isfile(path):
                    return self._json({"ok": False, "error": "缺少 engine/_ask.py"}, 500)
                cfg = load_cfg()
                spec = _ilu.spec_from_file_location("pluma_ask", path)
                mod = _ilu.module_from_spec(spec)
                spec.loader.exec_module(mod)
                try:
                    lesson = mod.builder.load(no)
                except Exception as e:  # noqa: BLE001
                    return self._json({"ok": False, "error": "读不到这一讲的数据：%r" % e}, 400)
                picked = mod.search(lesson, question)
                refs = [{"sec": r["sec"], "title": r["title"], "kind": r["kind"],
                         "pages": r["pages"], "text": r["text"][:160]} for r in picked]
                if api_client is None or not cfg["api_key"]:
                    return self._json({"ok": False, "need_key": True, "refs": refs,
                                       "error": "没配置 API 钥匙，不能真问。上方设置里填 sk- 开头的 key；"
                                                "已检索到的片段在下面可以直接看。"})
                t0 = time.time()
                try:
                    out = mod.answer(lesson, question, model=cfg["model"])
                except Exception as e:  # noqa: BLE001
                    return self._json({"ok": False, "error": "模型调用失败：%s" % e, "refs": refs}, 502)
                log_usage(out.get("model", cfg["model"]), out.get("usage", {}))
                return self._json({"ok": True, "answer": out["text"], "model": out["model"],
                                   "seconds": round(time.time() - t0, 1), "refs": refs})
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
    srv = ThreadingHTTPServer((HOST, PORT), Handler)
    url = "http://%s:%d/" % (HOST, PORT)
    print("羽毛笔 La Pluma v%s · 界面已启动 %s" % (VERSION, url))
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
