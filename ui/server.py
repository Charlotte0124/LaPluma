# -*- coding: utf-8 -*-
"""E 层 · 本地网页界面（只用标准库，不装任何依赖）。

    python ui\\server.py            # 浏览器打开 http://127.0.0.1:8765

只监听 127.0.0.1；文件读取限制在本仓内。
密钥只写本机配置，永不入仓。
"""
from __future__ import annotations

import base64
import io
import json
import hashlib
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
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# 2026-11-17：路径双根（见仓根 paths.py）。本脚本是 `python ui\server.py` 直接跑的，
#   仓根不在 sys.path 上，得自己挂一下；冻结后 __file__ 在解包目录，同样成立。
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import paths  # noqa: E402

ROOT = paths.DATA_ROOT          # 可写数据：课程、生成物、日志（冻结后 = exe 旁边）
RES = paths.RES_ROOT            # 只读资源：ui\ api\ engine\ tools\（冻结后 = 解包目录）
UI_DIR = paths.res("ui")
# 2016-11-17：默认课程不再写死 CS340 —— 原来的「多课程」只是 UI 支持，代码里到处是 CS340，
#   换一门课（示例课程 / 截图演示）就得改代码。现在取 courses.json 的第一个 key，
#   环境变量 PLUMA_COURSE 可覆盖（截图演示仓靠它切到示例课程）。
def _pick_default_course() -> str:
    env = os.environ.get("PLUMA_COURSE")
    if env:
        return env
    try:
        with open(paths.data_or_res("courses.json"), "r", encoding="utf-8-sig") as _f:
            _keys = [k for k in json.load(_f).keys() if not k.startswith("_")]
        # 2026-11-17 打包后真撞到：exe 只带示例课程 DEMO，courses.json 第一个键却是 CS340（真实课程
        #   不入公开仓），于是默认课程指向一个不存在的目录，界面看着像空的。先挑目录真存在的，
        #   都不存在才退回第一个键。
        for k in _keys:
            if os.path.isdir(paths.course_dir(k)):
                return k
        if _keys:
            return _keys[0]
    except Exception:  # noqa: BLE001
        pass
    return "DEMO"


DEFAULT_COURSE = _pick_default_course()
# 2026-11-17：路径双根之后，课程可能在数据根（用户自己的）也可能在资源根（随程序发布的示例课程）；
#   这里保留三个默认值只为了“默认课程”那一门，真正读文件的地方一律走 paths.course_dir()。
NOTES = os.path.join(paths.course_dir(DEFAULT_COURSE), "06_笔记")
PDF_DIR = os.path.join(paths.course_dir(DEFAULT_COURSE), "01_讲义")
# 2026-11-17：用户导入的源课件放这里（每门课一个 00_原件\），与成品 01_讲义 分开
ORIG_DIR = "00_原件"
LESSONS = os.path.join(paths.course_dir(DEFAULT_COURSE), "_lessons")
API_DIR = paths.res("api")
LOG_DIR = paths.data("_logs")
USER_DIR = os.environ.get("PLUMA_HOME") or os.path.join(os.path.expanduser("~"), ".pluma")
CFG_PATH = os.path.join(USER_DIR, "api.json")
FAV_PATH = os.path.join(USER_DIR, "favorites.json")
USAGE_PATH = os.path.join(LOG_DIR, "usage.jsonl")
HOST, PORT = "127.0.0.1", 8765
# 静态资源 ETag 缓存（2026-11-17）：path -> ((size, mtime), '"hash"')。
# 为什么要有：pdf.js 的 worker 1.33 MB + 主包 328 KB，原来一律 no-store，
#   每次打开/刷新阅读器都全量重传（本机无感，平板走 WiFi 明显）。
#   index.html 必须仍走 no-store（改完界面要能立刻看到新版）。
_STATIC_ETAG = {}
VERSION = "1.9.3"
APP_NAME = "羽毛笔 La Pluma"
BOOK_NAME = DEFAULT_COURSE + "_九讲合订本_讲义.pdf"

# ---------- 主机上线（局域网 + 8 位访问码）----------
# 2026-11-16 用户定 A 方案：只在跑服务的这台电脑上线；同一 WiFi 的平板/手机用访问码打开。
# 访问码在启动时生成一次，存 %USERPROFILE%\.pluma\host.json；重启就换新码。
LAN = False            # main() 按 --lan 置 true：只有显式要上线才对外监听
ACCESS_CODE = ""       # 8 位数字；LAN=False 时为空
HOST_PATH = os.path.join(os.path.expanduser("~"), ".pluma", "host.json")
NOTES_DIR = os.path.join(os.path.expanduser("~"), ".pluma", "notes")
PDFJS_DIR = paths.res("tools", "print", "pdfjs")

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
    path = paths.data_or_res(course, "_lessons", no + ".py")
    if not os.path.isfile(path):
        raise FileNotFoundError(path)
    spec = ilu.spec_from_file_location("lesson_%s_%s" % (_safe_code(course), _safe_code(no)), path)
    mod = ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.LESSON


def find_lesson(course: str) -> list[str]:
    """这一门有哪些讲：数据根与资源根合起来看（用户新增的讲与出厂示例课程都能列出来）。"""
    names = set()
    for root in (paths.DATA_ROOT, paths.RES_ROOT):
        d = os.path.join(root, course, "_lessons")
        if os.path.isdir(d):
            names.update(x[:-3] for x in os.listdir(d) if x.endswith(".py"))
    return sorted(names)


def load_ask_module():
    """engine/_ask.py 当模块用（检索 + 提示词）。"""
    import importlib.util as ilu
    path = paths.res("engine", "_ask.py")
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


# ---------- 生成：进程内调用（打包改造 · 第二半）----------
# 2026-11-17：原来 /api/generate 用 subprocess 跑 [sys.executable, engine\_make.py]。
#   源码下能跑；冻结成 exe 后 sys.executable 就是 exe 自己——点一次生成会再开一个软件。
#   现在改成 import + 直接调入口函数（make / main），日志用 emit 收回来。
_ENGINE_MODS = {}


def _engine(modname: str):
    """把 engine 目录下的脚本当模块取过来（只 import 一次）。"""
    if modname in _ENGINE_MODS:
        return _ENGINE_MODS[modname]
    for p in (paths.res("engine"), paths.res("tools", "print")):
        if p not in sys.path:
            sys.path.insert(0, p)
    import importlib
    _ENGINE_MODS[modname] = importlib.import_module(modname)
    return _ENGINE_MODS[modname]


def _inproc(modname: str, args: list, course: str, entry: str):
    """跑 engine 下的入口，收它的日志；返回 (日志, 退出码)。异常也当红项回报。"""
    buf = []
    try:
        mod = _engine(modname)
        rc = getattr(mod, entry)(list(args), course=course, emit=buf.append)
    except Exception as e:  # noqa: BLE001
        buf.append("[异常] 生成器抱错：%r" % (e,))
        return "\n".join(buf), 1
    return "\n".join(buf), int(rc or 0)


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


def dep_state() -> dict:
    """依赖自检，给界面用（用户 2026-11-17：「如果打不开的话 就在向导那检测」）。

    冻结成 exe 时运行环境都在包里，用户什么都不用装；源码版缺 pymupdf 就出不了 PDF
    （能开界面、能看课，但「开始生成」与阅读会失败）。
    """
    st = {"frozen": bool(getattr(sys, "frozen", False)),
          "python": "%d.%d.%d" % sys.version_info[:3], "pymupdf": ""}
    try:
        import pymupdf
        st["pymupdf"] = getattr(pymupdf, "__version__", "ok")
    except Exception:  # noqa: BLE001
        st["pymupdf"] = ""
    return st


def load_cfg():
    cfg = _read_json(CFG_PATH)
    # 2026-11-17 用户定：「删除 CS340 的字眼，那是课件」——真实课件名不该出现在界面上（截图、默认值）。
    #   默认保存目录改成中性的 out\（软件目录下），生成物仍然写在 <课程>\01_讲义，这里只是多复制一份。
    default_dir = "out"
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
    # 2026-11-17：换课程（示例课程 / 别人自己的课件）后，配置里存的旧课程目录会失效——
    #   以前会把 PDF 写到一个不存在的目录。现在目录不存在就退回当前课程的默认目录。
    # 2026-11-17 补：绝对路径也要能用（用户「也可以填绝对路径」）。
    #   旧逻辑直接拿 normpath 的第一段当相对目录首段，`F:\某处` 被当成 `F:` 去 ROOT 下找 → 永远
    #   判不存在 → 退回默认，于是「选了目录 / 填了绝对路径」都不生效。绝对路径只看它自己存不存在。
    _sd = out["save_dir"]
    # 旧默认值（<当前默认课>/01_讲义）视为未定制，直接换成 out；用户自己填的绝对路径不动
    if os.path.normcase(os.path.normpath(_sd)) == os.path.normcase(os.path.normpath(os.path.join(DEFAULT_COURSE, "01_讲义"))):
        out["save_dir"] = default_dir
        _sd = default_dir
    if os.path.isabs(_sd):
        if not os.path.isdir(_sd):
            out["save_dir"] = default_dir
            out["save_dir_fixed"] = True
    elif os.path.normcase(os.path.normpath(_sd)) != os.path.normcase(os.path.normpath(default_dir)):
        # out\ 是默认值，允许暂不存在（_copy_out 会建）；其它相对目录不存在就退回默认
        _first = os.path.normpath(_sd).split(os.sep)[0]
        if _first and _first not in (".", "..") and not os.path.isdir(paths.data_or_res(_first)):
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
    """扫两根：含 01_讲义 或 _lessons 的目录就是一「门课」。

    2026-11-17：数据根先扫（用户自己的课件），资源根后扫（随程序发布的示例课程）；
    同名时数据根优先——用户把示例课程拷到 exe 旁边改，就看改过的那份。
    """
    meta = _read_json(paths.data_or_res("courses.json"), {})
    favs = set(_read_json(FAV_PATH, {}).get("codes", []))
    found = {}
    for root in (paths.DATA_ROOT, paths.RES_ROOT):
        if not root or not os.path.isdir(root):
            continue
        for name in sorted(os.listdir(root)):
            d = os.path.join(root, name)
            if name in found or not os.path.isdir(d) or name.startswith((".", "_")):
                continue
            if name in ("ui", "api", "engine", "tools", "docs"):
                continue
            if not (os.path.isdir(os.path.join(d, "01_讲义")) or os.path.isdir(os.path.join(d, "_lessons"))):
                continue
            found[name] = d
    out = []
    for name, d in sorted(found.items()):
        les = os.path.join(d, "_lessons")
        m = meta.get(name, {})
        files, seen = [], set()
        # 成品同样两根合起来看：用户自己的在数据根，出厂的示例成果在资源根
        for root in (paths.DATA_ROOT, paths.RES_ROOT):
            pdfs = os.path.join(root, name, "01_讲义")
            if not os.path.isdir(pdfs):
                continue
            for fn in sorted(os.listdir(pdfs)):
                if not fn.lower().endswith(".pdf") or fn in seen:
                    continue
                seen.add(fn)
                full = os.path.join(pdfs, fn)
                files.append({"name": fn, "rel": "%s/01_讲义/%s" % (name, fn),
                              "size_kb": round(os.path.getsize(full) / 1024),
                              "pages": _pages(full)})
        lessons = sorted(x[:-3] for x in os.listdir(les) if x.endswith(".py")) if os.path.isdir(les) else []
        out.append({"code": name, "title": m.get("title", name), "en": m.get("en", ""),
                    "desc": m.get("desc", "（未填说明，可在 courses.json 里补）"),
                    "files": files, "lessons": lessons, "fav": name in favs,
                    "originals": list_originals(name)})
    return out


def _pages(pdf_path: str) -> int:
    try:
        import pymupdf
        with pymupdf.open(pdf_path) as doc:
            return doc.page_count
    except Exception:  # noqa: BLE001
        return 0


def safe_join(*parts):
    """拼一个可读文件的绝对路径；两根以内才算合法。

    2026-11-17 打包后真撞到：以前只拼数据根（ROOT），exe 里示例课程 DEMO 住在资源根
    （_MEIPASS），于是「读 D02」直接 FileNotFound——阅读页打不开、笔记副本也写不出来。
    现在按「数据根优先、资源根回落」，按**真实存在**选，不按前缀选。
    """
    rel = os.path.join(*parts)
    cands = []
    for root in (paths.DATA_ROOT, paths.RES_ROOT):
        if not root:
            continue
        p = os.path.abspath(os.path.join(root, rel))
        if p.startswith(os.path.abspath(root) + os.sep):
            cands.append(p)
    if not cands:
        raise PermissionError("路径越界")
    for p in cands:
        if os.path.isfile(p):
            return p
    return cands[0]      # 都不存在：回数据根，交给调用方报「文件不存在」


# ---------- 删除（移入回收站）----------
# 2026-11-17 用户要求：讲次（要生成的批次）、成品、原件、整门课程都要能删。
# 删除一律「移进 <数据根>\_trash\<时间戳>\」，不做 unlink：讲次数据是手写的、
# 课程目录里还有导入的原件，误点一次要能拿回来。
TRASH_DIR = "_trash"


def _in_data_root(p: str) -> bool:
    """是否在可写数据根内。资源根是随程序发布的示例课程（exe 里只读），不能删。"""
    return os.path.abspath(p).startswith(os.path.abspath(ROOT) + os.sep)


def trash_move(src: str) -> str:
    """把文件或目录移进回收站，返回新位置。"""
    dst_root = os.path.join(ROOT, TRASH_DIR, time.strftime("%Y%m%d-%H%M%S"))
    os.makedirs(dst_root, exist_ok=True)
    dst = _unique_path(dst_root, os.path.basename(src.rstrip("\\/")))
    shutil.move(src, dst)
    return dst


def originals_dir(code: str) -> str:
    """一「原件」目录：用户自己的源课件就放这儿（2026-11-17 用户：
    「他怎么只有保存的地方，没让我能丢进去的地方」）。"""
    return os.path.join(ROOT, _safe_code(code), ORIG_DIR)


def list_originals(code: str) -> list:
    """只列名字与大小，不开 PDF──每条都开的话，几十份原件会把 bootstrap 拖慢。"""
    d = originals_dir(code)
    if not os.path.isdir(d):
        return []
    out = []
    for fn in os.listdir(d):
        p = os.path.join(d, fn)
        if os.path.isfile(p):
            out.append({"name": fn, "size_kb": max(1, round(os.path.getsize(p) / 1024)),
                        "rel": "%s/%s/%s" % (_safe_code(code), ORIG_DIR, fn)})
    out.sort(key=lambda x: nat_key(x["name"]))
    return out


def _unique_path(d: str, name: str) -> str:
    """重名不覆盖：`a.pdf` 已在就写 `a (2).pdf`。"""
    name = os.path.basename(name) or "未命名"
    base, ext = os.path.splitext(name)
    cand = os.path.join(d, name)
    i = 2
    while os.path.exists(cand):
        cand = os.path.join(d, "%s (%d)%s" % (base, i, ext))
        i += 1
    return cand


def course_pdfs(code: str) -> list:
    """一门课的全部成品 PDF（数据根 + 资源根各执一份，同名取先出现的）。

    只给「导出」用：只挂文件名、不读页数，不碰 discover_courses 那条路（那里每份都开 PDF 读页数，61 门课时冷得能卡）。
    """
    code = _safe_code(code)
    out, seen = [], set()
    for root in (paths.DATA_ROOT, paths.RES_ROOT):
        d = os.path.join(root, code, "01_讲义")
        if not d or not os.path.isdir(d):
            continue
        for fn in sorted(os.listdir(d)):
            if not fn.lower().endswith(".pdf") or fn in seen:
                continue
            seen.add(fn)
            out.append((os.path.join(d, fn), fn))
    out.sort(key=lambda x: nat_key(x[1]))     # 讲号自然序：D2 在 D10 前（合订本拼的顺序靠它）
    return out


def rel_out(path: str) -> str:
    """绝对路径→相对路径（两根都对得上）。

    只按 ROOT 算会在示例课程（成品住在资源根）上算成 ..\\..\\ 开头的怪路径。
    """
    ap = os.path.abspath(path)
    for root in (paths.DATA_ROOT, paths.RES_ROOT):
        if root and ap.startswith(os.path.abspath(root) + os.sep):
            return os.path.relpath(ap, root).replace(os.sep, "/")
    return os.path.basename(ap)


def pick_directory(initial: str = "") -> str:
    """弹一个原生「选择文件夹」对话框，返回选中路径（取消则空串）。

    为什么起子进程：tkinter 的 Tk() 要在主线程建，而请求跑在
    ThreadingHTTPServer 的工作线程，同线程建 Tk 在 Windows 上会偶发卡死。
    冻结成 exe 后 sys.executable 就是 exe 自己，再起它等于又开一个软件，所以那种情况只能本进程内弹。
    """
    code = (
        "import sys, tkinter as tk\n"
        "from tkinter import filedialog\n"
        "r = tk.Tk(); r.withdraw(); r.attributes('-topmost', True)\n"
        "init = sys.argv[1] if len(sys.argv) > 1 else ''\n"
        "p = filedialog.askdirectory(title='选择保存目录', initialdir=init or None, mustexist=True)\n"
        "r.destroy()\n"
        "print('PICK:' + (p or ''))\n"
    )
    try:
        if getattr(sys, "frozen", False):
            import tkinter as tk
            from tkinter import filedialog
            r = tk.Tk()
            r.withdraw()
            r.attributes("-topmost", True)
            p = filedialog.askdirectory(title="选择保存目录", initialdir=initial or None, mustexist=True)
            r.destroy()
            return p or ""
        out = subprocess.run([sys.executable, "-c", code, initial or ""],
                             capture_output=True, text=True, timeout=180)
        for line in (out.stdout or "").splitlines():
            if line.startswith("PICK:"):
                return line[5:].strip()
        return ""
    except Exception as e:  # noqa: BLE001
        raise RuntimeError("弹不出目录选择框：%s" % e) from e


def pick_files(initial: str = "") -> list:
    """弹系统「打开文件」对话框（可多选），返回选中的绝对路径。

    与 pick_directory 同一套理由：tkinter 要在主线程建 Tk，而请求跑在
    ThreadingHTTPServer 的工作线程；冻结成 exe 时 sys.executable 就是自己，只能本进程内弹。
    """
    code = (
        "import sys, tkinter as tk\n"
        "from tkinter import filedialog\n"
        "r = tk.Tk(); r.withdraw(); r.attributes('-topmost', True)\n"
        "init = sys.argv[1] if len(sys.argv) > 1 else ''\n"
        "ps = filedialog.askopenfilenames(title='选择要导入的课件', initialdir=init or None,\n"
        "    filetypes=[('PDF 与图片', '*.pdf *.png *.jpg *.jpeg'), ('所有文件', '*.*')])\n"
        "r.destroy()\n"
        "for p in (ps or ()): print('PICK:' + p)\n"
    )
    try:
        if getattr(sys, "frozen", False):
            import tkinter as tk
            from tkinter import filedialog
            r = tk.Tk()
            r.withdraw()
            r.attributes("-topmost", True)
            ps = filedialog.askopenfilenames(
                title="选择要导入的课件", initialdir=initial or None,
                filetypes=[("PDF 与图片", "*.pdf *.png *.jpg *.jpeg"), ("所有文件", "*.*")])
            r.destroy()
            return [p for p in (ps or ()) if p]
        out = subprocess.run([sys.executable, "-c", code, initial or ""],
                             capture_output=True, text=True, timeout=300)
        return [ln[5:].strip() for ln in (out.stdout or "").splitlines() if ln.startswith("PICK:")]
    except Exception as e:  # noqa: BLE001
        raise RuntimeError("弹不出文件选择框：%s" % e) from e


def _stub_lesson_no(orig_name: str, taken: set) -> str:
    """从原件文件名取讲号：`Tutorial 02 - xxx.pdf` → `T02`；取不到数字就 T01。"""
    m = re.search(r"(\d{1,2})", orig_name)
    n = int(m.group(1)) if m else 0
    base = ("T%02d" % n) if n else "T01"
    no, i = base, 2
    while no in taken:
        no = "%s-%d" % (base, i)
        i += 1
    return no


def _pylit(v, ind: int = 0) -> str:
    """把 dict / list 写成 Python 字面量。

    为什么要自己写而不用 json.dumps：引擎里有 `'…%s…%s…%s…%s…' % row` 这种写法，
    `%` 只对 **tuple** 展开——JSON 写出来是 list，会被当成单个值，报 not enough arguments。
    所以「全标量的一行」统一写成 tuple。
    """
    pad = " " * ind
    if isinstance(v, dict):
        if not v:
            return "{}"
        items = []
        for k, x in v.items():
            items.append('%s    %s: %s' % (pad, json.dumps(str(k), ensure_ascii=False), _pylit(x, ind + 4)))
        return "{\n" + ",\n".join(items) + "\n" + pad + "}"
    if isinstance(v, (list, tuple)):
        if not v:
            return "()" if isinstance(v, tuple) else "[]"
        if all(not isinstance(x, (dict, list, tuple)) for x in v):
            body = ", ".join(_pylit(x, 0) for x in v)
            return "(" + body + ("," if len(v) == 1 else "") + ")"
        inner = ",\n".join(pad + "    " + _pylit(x, ind + 4) for x in v)
        return "[\n" + inner + ",\n" + pad + "]"
    if isinstance(v, str):
        return json.dumps(v, ensure_ascii=False)
    return json.dumps(v)


def make_stub_lesson(course: str, orig_name: str) -> dict:
    """导入原件后顺手建一讲**骨架**，让它立即出现在「要生成的讲次」里。

    2026-11-17 用户：「是导入课件 和 拖动之后 要生成的批次 都没有自动更新」——
    讲次原本只来自手写的 _lessons/<讲号>.py，所以导进来的 PDF 永远看不到。现在导入时补一份骨架：
    结构齐全、能过三道门、能出 PDF，但正文只有提示，要真内容得自己（或让模型）补。

    重复导入同一份原件不会再造一讲（按文件里的 stub-from 标记认）。
    """
    course = _safe_code(course)
    les_dir = os.path.join(ROOT, course, "_lessons")
    os.makedirs(les_dir, exist_ok=True)
    tag = "stub-from: %s/%s" % (ORIG_DIR, orig_name)
    taken = set()
    for fn in os.listdir(les_dir):
        if not fn.endswith(".py"):
            continue
        taken.add(fn[:-3])
        try:
            with open(os.path.join(les_dir, fn), "r", encoding="utf-8") as f:
                if tag in f.read():
                    return {"no": fn[:-3], "made": False, "reason": "already"}
        except Exception:  # noqa: BLE001
            pass
    no = _stub_lesson_no(orig_name, taken)
    title = os.path.splitext(orig_name)[0]
    out_pdf = "%s_%s_讲义.pdf" % (no, title)
    data = {
        "code": course, "no": no, "zh": title, "en": "",
        "out": out_pdf,
        "sub": "原件导入占位 · 正文待补",
        "meta": [["源课件", "%s/%s" % (ORIG_DIR, orig_name)], ["状态", "占位：正文未补"]],
        "sections": [{
            "no": "0", "zh": "本讲导读", "en": "Read Me First",
            "lec": "这一讲是从原件自动建的占位：结构齐全、能过三道门、能出 PDF；正文内容还没补。",
            "body": [
                ["p", "<b>这一讲是什么。</b>原件 <code>%s</code> 已导入本课，这个文件是它的讲义骨架。" % orig_name],
                ["p", "<b>怎么补。</b>改本文件的 <code>sections</code>，把课件内容整理成节；改完重跑 <code>python engine\\_make.py %s</code>。" % no],
                ["p", "<b>引用怎么写。</b>每条引文都要标原件页码，形如 <code>课件 p.1</code>（本句就是格式示例，版式门会查）。"],
                ["code", "text",
                 "原件：%s\\%s\\%s\n数据：%s\\_lessons\\%s.py\n生成：python engine\\_make.py %s" % (course, ORIG_DIR, orig_name, course, no, no),
                 "一条命令就能出 PDF"],
            ],
        }],
        "tail": [],
        "summary": {
            "no": "1", "zh": "本讲小结", "en": "Takeaways",
            "lec": "占位讲次：先把流水线跑通，再往里填内容。",
            "head": ["要做什么", "在哪做", "怎么验"],
            "head_widths": ["30%", "42%", "28%"],
            "rows": [
                ["读完原件", "把 PDF 里的一节读一遍", "能复述这一节讲什么"],
                ["写成节", "改本文件的 sections", "节数 ≥ 1，每节有 code 或 eg"],
                ["重跑", "python engine\\_make.py %s" % no, "输出里是 OK 不是 FAIL"],
            ],
            "tail": "这一讲目前是骨架：结构齐、能过门、能出 PDF，但正文是提示语。",
        },
        "glossary": {
            "no": "2", "zh": "术语表", "en": "Glossary",
            "lec": "占位讲次的术语表：先把流水线自己的词列全（回看 §0），补内容时把课件里的词加进来。",
            "rows": [
                ["占位讲次", "stub lesson", "本讲 §0", "导入原件时自动建的骨架，正文待补"],
                ["原件", "original", "本讲 §0", "导入到 00_原件 的源课件 PDF"],
                ["讲义数据", "lesson data", "本讲 §0", "_lessons\\<讲号>.py 里的 LESSON"],
                ["讲号", "lesson code", "本讲 §0", "如 T05；由原件文件名里的数字推出来"],
                ["课程代码", "course code", "本讲 §0", "仓根下的目录名，如 CS340"],
                ["节", "section", "本讲 §0", "sections 里的一项，一页一节"],
                ["块", "block", "本讲 §0", "body 里的一条（p / code / eg / table / svg / q）"],
                ["内容门", "content gate", "本讲 §1", "逐节查代码 / 例题 / 术语 / 定位标注"],
                ["版式门", "layout gate", "本讲 §1", "逐页查首行是不是标题 / 表格 / 图"],
                ["定位标注", "citation anchor", "本讲 §1", "页码 / §号 / 时间戳 / 行号，用来回查"],
                ["术语附英", "term with English", "本讲 §2", "术语首次出现时带括号英文"],
                ["自测", "self-check", "本讲 §4", "3–8 题，答案带「回看 §x」"],
                ["附录", "appendix", "本讲 §3", "符号表与常见误解"],
                ["渲染", "render", "本讲 §1", "数据 → HTML 的过程"],
                ["讲义源", "source html", "本讲 §1", "渲染出来、交给无头浏览器打 PDF 的那个 HTML"],
                ["无头浏览器", "headless browser", "本讲 §1", "不弹窗口的 Chrome/Edge"],
                ["成品", "artifact", "本讲 §1", "跑完之后生成的 HTML / PDF"],
                ["重跑", "rebuild", "本讲 §1", "同一份数据再跑一次"],
                ["导入", "import", "本讲 §0", "把课件 PDF 放进 00_原件 并建下这一讲"],
                ["骨架", "skeleton", "本讲 §0", "结构齐全、内容未补的数据文件"],
                ["三道门", "three gates", "本讲 §1", "源 / 内容 / 版式，任一红即停"],
            ],
        },
        "appendix": {
            "no": "3", "zh": "附录", "en": "Appendix",
            "lec": "本讲要补的常见误解放这里（回看 §0 的数据文件）。",
            "symbols": [],
            "myths_title": "常见误解",
            "myths": [
                "以为导入原件就等于写好了讲义：原件只是资料，讲义要自己（或让模型）把内容整理成节（本讲 §0）。",
                "以为改 HTML 能成事：下次重跑就被盖掉，改的是 _lessons 里的数据（本讲 §1）。",
            ],
        },
        "quiz": {
            "no": "4", "zh": "自测", "en": "Self-check",
            "lec": "三题都是「这一讲的东西在哪、怎么补」（回看 §0 与 §1）。",
            "items": [
                ["这一讲的正文在哪个文件里？",
                 "答：<课程>\\_lessons\\%s.py 的 sections；原件在同课 00_原件。回看 §0。" % no],
                ["补完内容后怎么出 PDF？",
                 "答：python engine\\_make.py %s；红项不出货。回看 §1。" % no],
                ["导入后为什么讲次列表里多了这一讲？",
                 "答：导入原件时会同时建一份骨架数据，它只是占位，不写内容就只是这一页。回看 §0。"],
            ],
        },
    }
    head = (
        "# -*- coding: utf-8 -*-\n"
        '"""%s · %s（导入原件时自动建的骨架）\n\n'
        "%s\n"
        "正文只有提示；补内容就改下面 sections，然后 python engine\\_make.py %s\n"
        '"""\n\n' % (no, title, tag, no)
    )
    path = os.path.join(les_dir, no + ".py")
    with open(path, "w", encoding="utf-8") as f:
        f.write(head + "LESSON = " + _pylit(data, 0) + "\n")
    return {"no": no, "made": True, "file": path, "title": title}


def nat_key(name: str):
    """自然序（D2 在 D10 前）——与前端 sortFiles 同一口径，否则导出顺序会不一致。"""
    m = re.match(r"^([A-Za-z]*)(\d+)", name or "")
    if m:
        return (m.group(1).upper(), int(m.group(2)), name)
    return ((name or "").upper(), 0, name or "")


def merge_pdfs(files: list) -> bytes:
    """把几份 PDF 按给定顺序拼成一本（每讲自己的封面页保留，不猜内部结构）。"""
    import pymupdf
    out = pymupdf.open()
    try:
        for full, _fn in files:
            with pymupdf.open(full) as doc:
                out.insert_pdf(doc)
        return out.tobytes(garbage=4, deflate=True)
    finally:
        out.close()


# ---------- 笔记（按「课程 + 具体文档」落盘）----------
# 2026-11-16 冒烟真撞到：原来只按课程存，结果打开 L02 能看到挂在 L05 的笔记，
# 页码对不上、导出的附页也会跟错文档。现在一格文档一个文件：
#   %USERPROFILE%\.pluma\notes\<课程>\<文档名>.json；没传 doc 时才退回按课程存（兼容旧调用）。
def _notes_path(code: str, doc: str = "") -> str:
    base = os.path.join(NOTES_DIR, _safe_code(code))
    if doc:
        return os.path.join(base, _safe_code(os.path.splitext(os.path.basename(doc))[0]) + ".json")
    return base + ".json"


def load_notes(code: str, doc: str = "") -> dict:
    p = _notes_path(code, doc)
    d = _read_json(p, {})
    notes = d.get("notes") if isinstance(d, dict) else None
    return {"code": code, "doc": doc, "notes": notes if isinstance(notes, list) else []}


def save_notes(code: str, notes: list, doc: str = "") -> int:
    p = _notes_path(code, doc)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    keep = [n for n in notes if isinstance(n, dict) and str(n.get("text") or "").strip()][-500:]
    _write_json(p, {"code": code, "doc": doc,
                    "updated": time.strftime("%Y-%m-%d %H:%M"), "notes": keep})
    return len(keep)


# ---------- 主机上线 ----------
def lan_ip() -> str:
    """拿本机在局域网里的地址（不发包：连一个不可达地址只为读路由表）。

    2026-11-17：探测用的不可达地址从内网网段改成 RFC 5737 的 TEST-NET-1（192.0.2.1）——
    两者都不可路由，语义一模一样；区别是内网地址会被公开仓的敏感扫描当成泄露
    （public-scan / R98 红线），换掉之后历史与当前文件都不再带内网串。
    """
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


# ---------- 运行时开关上线（2026-11-17 用户定：不许敲命令重开软件）----------
# 做法的取舍：本机那个 socket 一直只绑 127.0.0.1（不动它，本机永远用最短路径）；
#   点「一键上线」时在**局域网地址**上再起一个监听，关掉时就 shutdown。
#   为什么不直接绑 0.0.0.0：那会让 Windows 防火墙在**每次启动**都问一次；
#   而现在只在用户真的点「一键上线」时才碰外部网络，提示出现在该出现的时刻。
_LAN_SRV = None
_LAN_LOCK = threading.Lock()


def start_lan() -> dict:
    """开上线：在局域网 IP 上起第二个监听。已开则幂等返回。"""
    global _LAN_SRV, LAN, ACCESS_CODE
    with _LAN_LOCK:
        if _LAN_SRV is not None:
            return host_state()
        ip = lan_ip()
        if not ip or ip.startswith("127."):
            raise RuntimeError("这台电脑没有局域网地址（没连 WiFi / 网线？）")
        ACCESS_CODE = new_access_code()
        srv = ThreadingHTTPServer((ip, PORT), Handler)
        LAN = True
        _LAN_SRV = srv
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            _write_json(HOST_PATH, {"code": ACCESS_CODE, "at": time.strftime("%Y-%m-%d %H:%M"),
                                   "port": PORT, "ip": ip})
        except Exception:  # noqa: BLE001
            pass
    return host_state()


def stop_lan() -> dict:
    """关上线：停掉第二个监听，访问码作废（已发出去的 cookie 下次就没用了）。"""
    global _LAN_SRV, LAN, ACCESS_CODE
    with _LAN_LOCK:
        srv = _LAN_SRV
        _LAN_SRV = None
        LAN = False
        ACCESS_CODE = ""
        if srv is not None:
            threading.Thread(target=srv.shutdown, daemon=True).start()
            threading.Thread(target=srv.server_close, daemon=True).start()
    return host_state()



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
    # 2026-11-17：源在资源根（exe 里的示例课程，只读）时，副本必须写到数据根，
    #   否则要么写不进去，要么写到临时目录一关就没了。
    if paths.RES_ROOT and os.path.abspath(src).startswith(os.path.abspath(paths.RES_ROOT) + os.sep):
        out_dir = os.path.join(ROOT, os.path.dirname(rel_out(src)))
        os.makedirs(out_dir, exist_ok=True)
        out = os.path.join(out_dir, os.path.splitext(os.path.basename(src))[0] + "_附笔记.pdf")
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
    # 2026-11-17：笔记页用 fontfile 嵌字，PyMuPDF 会把整个微软雅黑（msyh.ttc）塞进 PDF，
    #   实际只用到几百个字形 → 附笔记版本比原讲义大 6–8 倍（实测 L01 1.62 MB → 12.44 MB，
    #   单个字体流对象 11.80 MB）。subset_fonts() 只保留实际用到的字形；再配 garbage=4 + deflate_fonts
    #   把无用对象与流收干净。实测：合订本 16.78 → 5.04 MB、L01 12.44 → 0.82 MB、L03 13.15 → 1.42 MB，
    #   页数与全文文本哈希均不变（画面也逐页比对过）。失败时不影响出件（passthrough）。
    try:
        doc.subset_fonts(verbose=False)
    except Exception:  # noqa: BLE001
        pass
    doc.save(out, deflate=True, garbage=4, deflate_fonts=True)
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

    def _static(self, path):
        """静态资源（pdf.js 等）：内容哈希做 ETag，命中 If-None-Match 就回 304。

        行为与 _file 一致（同样的 200 + 字节），只是多了缓存协商；
        内容一改（size/mtime 变）就重算哈希，缓存自动失效。
        不用 _file 的原因：那条路统一 no-store，是给 index.html 与 PDF 下载的。
        """
        if not os.path.isfile(path):
            return self._json({"ok": False, "error": "文件不存在"}, 404)
        st = os.stat(path)
        stamp = (st.st_size, int(st.st_mtime))
        got = _STATIC_ETAG.get(path)
        if got is None or got[0] != stamp:
            h = hashlib.sha256()
            with open(path, "rb") as f:
                for chunk in iter(lambda: f.read(262144), b""):
                    h.update(chunk)
            got = (stamp, '"%s"' % h.hexdigest()[:32])
            _STATIC_ETAG[path] = got
        tag = got[1]
        if self.headers.get("If-None-Match") == tag:
            self.send_response(304)
            self.send_header("ETag", tag)
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            return None
        ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Cache-Control", "no-cache")
        self.send_header("ETag", tag)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(st.st_size))
        self.end_headers()
        with open(path, "rb") as f:
            shutil.copyfileobj(f, self.wfile)

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

    def _bytes(self, data: bytes, filename: str, ctype: str = "application/octet-stream"):
        """内存里的字节直接当附件下发（导出打包用）。

        中文文件名同样要 ASCII 回退 + RFC 5987 双写，理由见 _file。
        """
        ascii_fn = filename.encode("ascii", "ignore").decode() or "export"
        disp = 'attachment; filename="%s"; filename*=UTF-8\'\'%s' % (
            ascii_fn.replace('"', ""), urllib.parse.quote(filename))
        self.send_response(200)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Content-Disposition", disp)
        self.end_headers()
        self.wfile.write(data)

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
                                       "error": "需要访问码：请在平板端输入一次"}, 401)
                return self._file(os.path.join(UI_DIR, "access.html"))
            if u.path in ("/access", "/access.html"):
                return self._file(os.path.join(UI_DIR, "access.html"))
            if u.path == "/pdfjs" or u.path.startswith("/pdfjs/"):
                fn = os.path.basename(u.path)
                if not fn:
                    return self._json({"ok": False, "error": "缺文件名"}, 400)
                return self._static(os.path.join(PDFJS_DIR, fn))
            if u.path == "/api/host":
                return self._json(dict(ok=True, **host_state()))
            if u.path == "/api/notes":
                return self._json(dict(ok=True, **load_notes(q.get("code", [DEFAULT_COURSE])[0],
                                                             q.get("doc", [""])[0])))
            if u.path == "/favicon.ico":
                # 2026-11-17：以前回 204（空图标）——用户「软件图标还没有整上去」。
                # 现在直接给 exe 那张 assets\lapluma.ico，标签页与书签都用它。
                ico = paths.res("assets", "lapluma.ico")
                if os.path.isfile(ico):
                    return self._static(ico)
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
                    "model": cfg["model"], "models": MODELS, "default": DEFAULT_COURSE,
                    "save_dir": cfg["save_dir"], "save_dir_abs": os.path.abspath(os.path.join(ROOT, cfg["save_dir"])),
                    "save_dir_fixed": cfg.get("save_dir_fixed", False),
                    "data_root": paths.DATA_ROOT,
                    "deps": dep_state(),
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
                return self._json(dict(ok=True, **load_session(q.get("code", [DEFAULT_COURSE])[0])))
            if u.path == "/api/export":
                # 导出成品到本机下载目录（浏览器下载夹）：
                #   ?p=<相对路径>              → 单份（等同于 /api/pdf?dl=1）
                #   ?course=<课程>              → 整门全部成品，打成一个 zip
                #   ?course=<课程>&sel=<rel>…   → 只打包选中的几份（sel 可重复；只选 1 份就直接给 PDF）
                # 为什么走下载而不是「拷到某个目录」：桌面上有下载夹，平板上也拿得到；
                # 拷到一个用户还得先去找的目录，反而多一道。
                rel = q.get("p", [""])[0]
                if rel:
                    return self._file(safe_join(*rel.split("/")), inline=False)
                code = q.get("course", [""])[0]
                if not code:
                    return self._json({"ok": False, "error": "缺参数：p 或 course"}, 400)
                files = course_pdfs(code)
                if not files:
                    return self._json({"ok": False, "error": "这一门还没有成品，先去生成页出一份"}, 404)
                sel = [x for x in (q.get("sel") or []) if x]
                if sel:
                    # 只认这一门 01_讲义 下的文件：按文件名比对，路径绕不出去
                    by_name = {fn: full for full, fn in files}
                    picked = []
                    for r in sel:
                        base = os.path.basename(str(r).replace("\\", "/"))
                        if base in by_name and base not in [fn for _, fn in picked]:
                            picked.append((by_name[base], base))
                    if not picked:
                        return self._json({"ok": False, "error": "选中的文件不在这门课的成品里"}, 400)
                else:
                    picked = list(files)
                # 合订本：把选中的几份按讲号拼成一本（2026-11-17 用户要「合订本导出也支持」）
                if str(q.get("form", [""])[0]) == "book":
                    try:
                        data = merge_pdfs(picked)
                    except Exception as e:  # noqa: BLE001
                        return self._json({"ok": False, "error": "拼合订本失败：%s" % e}, 500)
                    return self._bytes(data, "%s_合订本_%d讲.pdf" % (_safe_code(code), len(picked)),
                                       "application/pdf")
                if len(picked) == 1:
                    return self._file(picked[0][0], inline=False)
                buf = io.BytesIO()
                with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
                    for full, fn in picked:
                        z.write(full, fn)
                return self._bytes(buf.getvalue(),
                                   "%s_讲义_选%d份.zip" % (_safe_code(code), len(picked)),
                                   "application/zip")
            if u.path == "/api/pdf":
                rel = q.get("p", [""])[0]
                # dl=1 → 当附件下载（导出用）；默认 inline 给 pdf.js 读
                dl = str(q.get("dl", [""])[0]).lower() in ("1", "true", "yes")
                return self._file(safe_join(*rel.split("/")), inline=not dl)
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
            if u.path == "/api/lan":
                # 2026-11-17：界面上的「一键上线 / 关闭上线」走这里。
                # 只接本机：上线开关本身就是个对外暴露的动作，不能让局域网里的人帮你开。
                if self.client_address[0] not in ("127.0.0.1", "::1"):
                    return self._json({"ok": False, "error": "只能在这台电脑上开关上线"}, 403)
                try:
                    st = start_lan() if body.get("on") else stop_lan()
                except Exception as e:  # noqa: BLE001
                    return self._json({"ok": False, "error": str(e)}, 400)
                return self._json(dict(ok=True, **st))
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
                code = str(body.get("code") or DEFAULT_COURSE)
                doc = str(body.get("doc") or "")
                cur = load_notes(code, doc)["notes"]
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
                n = save_notes(code, cur, doc)
                return self._json({"ok": True, "notes": cur, "count": n})
            if u.path == "/api/note/export":
                # 07：选中对话 / 侧栏笔记 → 整理成笔记页 → 追加到指定 PDF 末尾（另存副本）
                # 2026-11-17：改成可多选（targets）。用户原话「添加笔记可以选多个」——
                #   以前一次只能选一份讲义，一门课 120 份时要导十几次。现在一次跑多份，
                #   模型整理（use_model）只跑一次，结果共用；每份各存自己的 _附笔记.pdf。
                code = str(body.get("code") or DEFAULT_COURSE)
                raw_t = body.get("targets")
                if not isinstance(raw_t, list):
                    raw_t = [body.get("target")]
                targets = []
                for t in raw_t:
                    t = str(t or "").strip()
                    if t and t not in targets:
                        targets.append(t)
                targets = targets[:20]      # 一次最多 20 份，再多就是误操作
                if not targets:
                    return self._json({"ok": False, "error": "要选至少一份 PDF 作为追加目标"}, 400)
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
                results = []
                for target in targets:
                    try:
                        res = build_note_pdf(target, title, blocks)
                        results.append({"ok": True, "target": target, "file": res["name"],
                                        "rel": rel_out(res["out"]),
                                        "pages_before": res["pages_before"],
                                        "pages_after": res["pages_after"], "out": res["out"]})
                    except Exception as e:  # noqa: BLE001
                        results.append({"ok": False, "target": target, "error": str(e)})
                done = [r for r in results if r.get("ok")]
                tip = {"ok": bool(done), "count": len(done), "failed": len(results) - len(done),
                       "results": results}
                if len(results) == 1 and done:
                    tip.update(done[0])                 # 单份时保留旧字段，老前端不用改
                elif not done:
                    tip["error"] = "；".join(r.get("error", "") for r in results)[:300]
                return self._json(tip)
            if u.path == "/api/import":
                # 2026-11-17 用户：「他怎么只有保存的地方，没让我能丢进去的地方」
                #   两种入口：mode=pick（本机弹文件对话框，不走浏览器上传，大 PDF 也快）
                #   不传 mode 则按 files=[{name,b64}] 处理（网页拖拽进来的）
                code = _safe_code(str(body.get("course") or DEFAULT_COURSE))
                d = originals_dir(code)
                try:
                    os.makedirs(d, exist_ok=True)
                except Exception as e:  # noqa: BLE001
                    return self._json({"ok": False, "error": "建目录失败：%s" % e}, 500)
                added, skipped = [], []
                if str(body.get("mode") or "") == "pick":
                    if self.client_address[0] not in ("127.0.0.1", "::1"):
                        return self._json({"ok": False,
                                           "error": "只能在运行软件的那台电脑上选文件；远程请把文件拖进窗口"}, 403)
                    try:
                        picked = pick_files(d)
                    except Exception as e:  # noqa: BLE001
                        return self._json({"ok": False, "error": str(e)}, 500)
                    if not picked:
                        return self._json({"ok": False, "canceled": True})
                    for src in picked:
                        try:
                            dst = _unique_path(d, os.path.basename(src))
                            shutil.copy2(src, dst)
                            added.append(os.path.basename(dst))
                        except Exception as e:  # noqa: BLE001
                            skipped.append("%s：%s" % (os.path.basename(src), e))
                else:
                    for it in (body.get("files") or []):
                        if not isinstance(it, dict):
                            continue
                        name = os.path.basename(str(it.get("name") or "").strip())
                        b64 = str(it.get("b64") or "")
                        if not name or not b64:
                            continue
                        if "." not in name:
                            skipped.append(name + "：没有扩展名")
                            continue
                        if len(b64) > 70 * 1024 * 1024:
                            skipped.append(name + "：超过 50 MB，请用「选择文件」")
                            continue
                        try:
                            raw = base64.b64decode(b64.split(",")[-1], validate=False)
                            dst = _unique_path(d, name)
                            with open(dst, "wb") as fh:
                                fh.write(raw)
                            added.append(os.path.basename(dst))
                        except Exception as e:  # noqa: BLE001
                            skipped.append(name + "：%s" % e)
                # 2026-11-17：导入同时建一讲骨架——用户要的是「导进来就能在要生成的批次里看到」
                stubs = []
                for nm in added:
                    try:
                        st = make_stub_lesson(code, nm)
                        if st and st.get("made"):
                            stubs.append(st["no"])
                    except Exception as e:  # noqa: BLE001
                        skipped.append("建讲次失败（%s）：%s" % (nm, e))
                return self._json({"ok": bool(added), "course": code, "dir": d,
                                   "added": added, "skipped": skipped, "stubs": stubs,
                                   "files": list_originals(code)})
            if u.path == "/api/pick-dir":
                # 选保存目录（原生文件夹对话框）。只接本机：平板端弹不出这台电脑的对话框，
                # 那边只能到「设置」里手填；请求会一直挂着直到用户选完或取消。
                if self.client_address[0] not in ("127.0.0.1", "::1"):
                    return self._json({"ok": False,
                                       "error": "只能在运行软件的那台电脑上选目录；远程请到「设置」里手填路径"}, 403)
                cfg0 = load_cfg()
                # 2026-11-17 用户定「默认是在羽毛笔在的地方」：对话框从软件数据根打开
                # （源码 = 仓根，exe = exe 旁边），不再从当前课程的 01_讲义 打开。
                initial = str(body.get("initial") or "").strip() or paths.DATA_ROOT
                if not os.path.isdir(initial):
                    initial = paths.DATA_ROOT
                try:
                    p = pick_directory(initial)
                except Exception as e:  # noqa: BLE001
                    return self._json({"ok": False, "error": str(e)}, 500)
                if not p:
                    return self._json({"ok": False, "canceled": True})
                return self._json({"ok": True, "path": p})
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
                code = str(body.get("code") or DEFAULT_COURSE)
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
            if u.path == "/api/delete":
                # 2026-11-17：讲次 / 成品 / 原件 / 整门课 四种删除。全部移入 _trash，不真删。
                kind = str(body.get("kind") or "").strip()
                code = _safe_code(str(body.get("course") or "").strip())
                cdir = os.path.abspath(paths.course_dir(code))
                if not code or not os.path.isdir(cdir):
                    return self._json({"ok": False, "error": "没有这门课：%s" % (code or "（空）")}, 404)
                if not _in_data_root(cdir):
                    return self._json({"ok": False,
                                       "error": "这是随程序发布的示例课程（只读），不能删除；要改先复制到软件目录"}, 403)
                moved = []
                if kind == "lesson":
                    no = re.sub(r"[^A-Za-z0-9_.-]", "_", str(body.get("no") or "").strip())
                    src = os.path.join(cdir, "_lessons", no + ".py")
                    if not no or not os.path.isfile(src):
                        return self._json({"ok": False, "error": "没有这一讲：%s" % (no or "（空）")}, 404)
                    moved.append(trash_move(src))
                elif kind == "file":
                    # 只认这门课自己的 01_讲义（成品）与 00_原件（导入的原件），路径绕不出去
                    rel = str(body.get("rel") or "").replace("\\", "/")
                    parts = [x for x in rel.split("/") if x]
                    if (len(parts) != 3 or _safe_code(parts[0]) != code
                            or parts[1] not in ("01_讲义", ORIG_DIR)):
                        return self._json({"ok": False, "error": "只能删这门课的成品或原件：%s" % rel}, 400)
                    name = os.path.basename(parts[2])
                    src = os.path.join(cdir, parts[1], name)
                    if not os.path.isfile(src):
                        return self._json({"ok": False, "error": "文件不存在：%s" % rel}, 404)
                    moved.append(trash_move(src))
                elif kind == "course":
                    if str(body.get("confirm") or "").strip() != code:
                        return self._json({"ok": False,
                                           "error": "确认字串不一致：请照抄课程代号 %s" % code}, 400)
                    moved.append(trash_move(cdir))
                    # 课程没了，收藏夹里不能留空壳
                    fav = _read_json(FAV_PATH, {"codes": []})
                    _write_json(FAV_PATH, {"codes": [x for x in fav.get("codes", []) if x != code]})
                else:
                    return self._json({"ok": False, "error": "未知删除类型：%s" % (kind or "（空）")}, 400)
                # 2026-11-17：删除必须留痕。之前没有日志，本轮到过一次「课程目录不见了」，
                #   却无法从软件侧确认是谁删的（只能靠 git 恢复）；现在每次删除写一行。
                try:
                    os.makedirs(LOG_DIR, exist_ok=True)
                    with open(os.path.join(LOG_DIR, "delete.log"), "a", encoding="utf-8") as _fh:
                        _fh.write("%s\t%s\t%s\t%s\t%s\n" % (
                            time.strftime("%Y-%m-%d %H:%M:%S"), kind, code,
                            str(body.get("no") or body.get("rel") or code), moved[0] if moved else ""))
                except Exception:  # noqa: BLE001
                    pass
                return self._json({"ok": True, "kind": kind, "count": len(moved),
                                   "trash": moved[0] if moved else "",
                                   "trash_dir": os.path.join(ROOT, TRASH_DIR)})
            if u.path == "/api/generate":
                no = str(body.get("lesson", "")).strip()
                course = str(body.get("course", DEFAULT_COURSE)).strip()
                form = str(body.get("form", "single")).strip() or "single"
                t0 = time.time()
                if form == "book":
                    # 合订本：默认全部讲，按讲号顺序（B 口径：去掉各讲封面与目录）
                    log, rc = _inproc("_book", [], course, "main")
                    copied = ""
                    if rc == 0:
                        copied = self._copy_out(course, "%s_九讲合订本" % course,
                                                str(body.get("save_dir") or ""))
                    return self._json({"ok": rc == 0, "log": log, "form": "book",
                                       "seconds": round(time.time() - t0, 1), "copied": copied})
                avail = sorted(x[:-3] for x in os.listdir(os.path.join(paths.course_dir(course), "_lessons"))
                               if x.endswith(".py")) if os.path.isdir(os.path.join(paths.course_dir(course), "_lessons")) else []
                if no not in avail:
                    return self._json({"ok": False, "error": "没有这一讲：%s" % no}, 400)
                log, rc = _inproc("_make", [no], course, "make")
                copied = ""
                if rc == 0 and body.get("save_dir"):
                    copied = self._copy_out(course, no, str(body["save_dir"]))
                return self._json({"ok": rc == 0, "log": log, "form": "single",
                                   "seconds": round(time.time() - t0, 1), "copied": copied})
            if u.path == "/api/ask":
                # 问课件：先检索，再由模型回答。
                # 2026-11-16：改成「一个课件一个会话」——不传 lesson 就搜整门课；
                # 跨课件必须显式 allow_cross=true，否则永远只在当前这门里找。
                code = str(body.get("course") or DEFAULT_COURSE).strip()
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
                bare = {"code": code, "no": no or ("/".join(only) if only else "全课"),
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
                    # 2026-11-17：余额不足不能再混成一条普通失败。
                    #   实测：余额 0 时原来界面只看到「模型调用失败：HTTP Error 402: Payment Required」，
                    #   用户既不知道是钱的问题，也不知道去那里充。现在单独返回 need_money + 余额真数。
                    if api_client is not None and isinstance(e, getattr(api_client, "BalanceError", ())):
                        return self._json({"ok": False, "need_money": True,
                                           "error": "余额不足，这一问没法答",
                                           "balance": _balance_now(cfg), "model": cfg["model"],
                                           "cost_est": "约 ¥0.02",
                                           "topup": "https://platform.deepseek.com/top_up",
                                           "refs": refs})
                    return self._json({"ok": False, "error": "模型调用失败：%s" % e, "refs": refs}, 502)
                log_usage(out.get("model", cfg["model"]), out.get("usage", {}))
                return self._json({"ok": True, "answer": out["text"], "model": out["model"],
                                   "seconds": round(time.time() - t0, 1), "refs": refs,
                                   "scope": {"course": code,
                                             "lesson": no or ("/".join(only) if only else "全课"),
                                             "cross": allow_cross}})
            return self._json({"ok": False, "error": "无此路由"}, 404)
        except Exception as e:  # noqa: BLE001
            return self._json({"ok": False, "error": repr(e)}, 500)

    def _copy_out(self, course, no, dest):
        """成功后把成品复制到用户选的目录（dest 可在仓内，也可绝对路径）。"""
        if not dest:
            return ""
        # 生成物一律写在数据根（paths.data），自带示例课程也一样——不从资源根拷
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


def _balance_now(cfg) -> dict:
    """读一次真实余额；读不到就明说读不到，不编数字。"""
    if api_client is None or not cfg.get("api_key"):
        return {"ok": False, "error": "未配置 key"}
    try:
        body = api_client._get(cfg["base_url"].rstrip("/") + "/user/balance", cfg["api_key"])
        infos = body.get("balance_infos", [])
        cny = next((x for x in infos if x.get("currency") == "CNY"), None)
        return {"ok": True, "available": body.get("is_available"),
                "balance": (cny or {}).get("total_balance", "0.00")}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}


def run_window(url: str) -> int:
    """把界面放进一个原生窗口（Windows 上走 WebView2 / Edge）。

    2026-11-17 用户问「为什么都是网页版，不应该是一个软件吗」——以前是本地服务 + 浏览器页，
    看着像网页。现在双击/启动直接是一个自己的窗口，带图标与标题，关窗口就退出。
    想要回浏览器（例如平板、远程调试）用 --no-window。
    """
    import webview
    webview.create_window("%s v%s" % (APP_NAME, VERSION), url,
                          width=1280, height=880, min_size=(980, 640))
    # 2026-11-17 用户：「为什么我本地的软件的图标还是一样的」——
    #   pywebview 的 winforms 后端只有在 start(icon=...) 传了图标时才用自定义图标，
    #   不传就取 sys.executable 的图标 → 从源码跑时窗口与任务栏一直是 python.exe 的蓝黄头像。
    #   这里显式指定 assets\lapluma.ico（源码时在仓根，exe 时在 _MEIPASS）。
    ico = paths.res("assets", "lapluma.ico")
    if os.path.isfile(ico):
        webview.start(icon=ico)
    else:
        webview.start()
    return 0


def main() -> int:
    global PORT
    argv = sys.argv[1:]
    # 输出重定向到文件（或 double-click 的控制台）时行缓冲更靠谱：不然启动提示一个字都看不到
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:  # noqa: BLE001
        pass
    # 冻结后（exe）先把两根与 engine\ tools\print\ api\ 挂上 sys.path；源码下是幂等的
    paths.bootstrap()
    # 2026-11-17：--lan 不再自己绑 0.0.0.0，改成与「一键上线」走同一条路（start_lan），
    #   这样启动就上线与点按钮上线行为一致，关闭按钮也不会只能对一半有效。
    want_lan = ("--lan" in argv) or ("-lan" in argv)
    for i, a in enumerate(argv):
        if a == "--port" and i + 1 < len(argv):
            PORT = int(argv[i + 1])
    # 2026-11-17：原来是「端口占用就打印提示然后退出」——双击 exe 时窗口一闪就没了，
    #   用户看到的就是「打不开」。现在自动顺延 10 个端口。
    #   注意必须**先探测再绑定**：Windows 允许两个进程同时绑 8765 且不报错（先启的那个偷偷应答），
    #   光靠「bind 抛 OSError 就换」永远不会触发。
    import socket as _sock

    def _busy(p: int) -> bool:
        s = _sock.socket(_sock.AF_INET, _sock.SOCK_STREAM)
        try:
            s.settimeout(0.35)
            return s.connect_ex(("127.0.0.1", p)) == 0
        except Exception:  # noqa: BLE001
            return False
        finally:
            s.close()

    srv = None
    want = PORT
    for cand in range(want, want + 10):
        if _busy(cand):
            continue
        try:
            srv = ThreadingHTTPServer(("127.0.0.1", cand), Handler)
        except OSError:
            continue
        if cand != want:
            print("端口 %d 被占用（可能是另一个 LaPluma 或上次没关的服务），已改用 %d。" % (want, cand), flush=True)
        PORT = cand
        break
    if srv is None:
        print("端口 %d–%d 都被占用，开不了。先查：Get-NetTCPConnection -LocalPort %d -State Listen" % (want, want + 9, want), flush=True)
        print("\n回车关掉这个窗口。", flush=True)
        try:
            input()
        except Exception:  # noqa: BLE001
            pass
        return 4

    # 默认开窗口（像桌面软件）；--no-window 回浏览器页
    use_window = "--no-window" not in argv
    if use_window:
        try:
            import webview  # noqa: F401
        except Exception:  # noqa: BLE001
            use_window = False
    local = "http://127.0.0.1:%d/" % PORT
    print("羽毛笔 La Pluma v%s · 界面已启动" % VERSION)
    print("  本机    %s" % local)
    if want_lan:
        try:
            st = start_lan()
            print("  局域网  %s   ← 平板 / 手机用这个" % st["url_lan"])
            print("  访问码  %s %s   ← 只给对一次（12 小时）" % (st["code"][:4], st["code"][4:]))
            print("  （本机自己打开不用输码；关掉这个窗口就断，不是云端）")
        except Exception as e:  # noqa: BLE001
            print("  上线没开成：%s；继续只在本机。" % e)
    else:
        print("  （Ctrl+C 停止；现在只监听本机。要给平板用：界面「上线」页点「一键上线」，或加 --lan）")
    if use_window:
        # 应用窗口（WebView2）：关窗口就退出。用户原话「为什么都是网页版，它不应该是一个软件吗」。
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        print("  窗口模式：关掉窗口就退出（想用浏览器：加 --no-window）", flush=True)
        try:
            rc = run_window(local)
        except Exception as e:  # noqa: BLE001
            print("  窗口开不了（%s），改用浏览器。" % e, flush=True)
            if "--no-browser" not in argv:
                webbrowser.open(local)
            try:
                srv.serve_forever()
            except KeyboardInterrupt:
                pass
            srv.server_close()
            return 1
        srv.server_close()
        print("窗口已关闭，服务停止", flush=True)
        return rc

    # 浏览器模式（--no-window）：本地服务 + 系统浏览器
    if "--no-browser" not in argv:
        threading.Timer(0.6, lambda: webbrowser.open(local)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
    return 0

if __name__ == "__main__":
    # 双击 exe 时窗口一闪就没，用户只会看到「打不开」。无控制台的打包里没有地方看报错，
    # 所以用系统对话框把原因显式弹出来。
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception:
        import traceback
        msg = traceback.format_exc()
        try:
            sys.stderr.write(msg)
        except Exception:  # noqa: BLE001
            pass
        try:
            import tkinter as _tk
            from tkinter import messagebox as _mb
            _r = _tk.Tk()
            _r.withdraw()
            _mb.showerror("羽毛笔 La Pluma · 启动失败", msg[-1500:])
            _r.destroy()
        except Exception:  # noqa: BLE001
            pass
        sys.exit(1)
