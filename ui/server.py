# -*- coding: utf-8 -*-
"""E 层 · 本地网页界面（只用标准库，不装任何依赖）。

    python ui\\server.py            # 浏览器打开 http://127.0.0.1:8765

只监听 127.0.0.1；文件读取限制在本仓内。
密钥只写本机配置，永不入仓。
"""
from __future__ import annotations

import base64
import ctypes
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
import urllib.request
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
# 2026-11-22 用户：翻译页签要列「最近 5 条」，本机存 ~/.pluma/translate-history.json。
#   只留 5 条：时间 / 原文前 120 字 / 译文前 400 字（多了会把侧栏撑成另一份正文）。
TRANS_HISTORY_PATH = os.path.join(USER_DIR, "translate-history.json")
TRANS_HISTORY_MAX = 5
USAGE_PATH = os.path.join(LOG_DIR, "usage.jsonl")
HOST, PORT = "127.0.0.1", 8765
# 静态资源 ETag 缓存（2026-11-17）：path -> ((size, mtime), '"hash"')。
# 为什么要有：pdf.js 的 worker 1.33 MB + 主包 328 KB，原来一律 no-store，
#   每次打开/刷新阅读器都全量重传（本机无感，平板走 WiFi 明显）。
#   index.html 必须仍走 no-store（改完界面要能立刻看到新版）。
_STATIC_ETAG = {}
VERSION = "1.9.16"
# v1.9.15 起分发只走文件夹（仓库目录 + 启动羽毛笔.cmd）；单文件 exe 已退役，见 AGENTS.md 六。
APP_NAME = "羽毛笔 La Pluma"

# 2026-11-19：生成进度（一个进程同时只跑一讲；前端轮询 /api/progress）
GEN_PROG = {"on": False, "stage": "", "pct": 0, "t0": 0.0}


def set_prog(stage: str | None = None, pct: int | None = None, on: bool | None = None) -> None:
    if on is not None:
        GEN_PROG["on"] = bool(on)
        if on:
            GEN_PROG["t0"] = time.time()
    if stage is not None:
        GEN_PROG["stage"] = str(stage)
    if pct is not None:
        GEN_PROG["pct"] = max(0, min(100, int(pct)))


def prog_from_log(line: str) -> None:
    """把引擎日志翻译成粗粒度进度（不追求精确，够进度条走）。"""
    s = str(line)
    if "[源文本]" in s:
        set_prog("读课件文字层", 15)
    elif "[生成] 完成" in s:
        set_prog("DeepSeek 写完正文", 45)
    elif "[术语]" in s:
        set_prog("补术语表", 52)
    elif "[落盘]" in s:
        set_prog("正文落盘", 60)
    elif s.startswith("## "):
        set_prog("生成讲义源", 65)
    elif "生成 " in s and "_讲义_源.html" in s:
        set_prog("内容门", 75)
    elif "已写" in s:
        set_prog("打印 PDF", 92)
    elif "OK " in s:
        set_prog("版式门", 96)


def _load_brand():
    """品牌三要素（软件名 / 项目地址 / 免责）的唯一出处：tools\\print\\_brand.py。

    与 PDF 页脚用同一份（PRTS R105），所以界面底部与成品页脚不会有一天对不上。
    按文件路径加载：模块导入时 paths.bootstrap() 还没跑，不靠 sys.path。
    """
    import importlib.util
    cands = [os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools", "print",
                          "_brand.py")]
    try:
        cands.insert(0, paths.res("tools", "print", "_brand.py"))
    except Exception:  # noqa: BLE001
        pass
    for c in cands:
        if os.path.isfile(c):
            try:
                spec = importlib.util.spec_from_file_location("_pluma_brand", c)
                m = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(m)
                return m
            except Exception:  # noqa: BLE001
                continue

    class _Fallback:
        PRODUCT_NAME = "羽毛笔 La Pluma"
        PROJECT_URL = "https://github.com/Charlotte0124/LaPluma"
        PROJECT_URL_TEXT = "github.com/Charlotte0124/LaPluma"
        DISCLAIMER = "本内容由 AI 生成，仅供参考；重要信息请自行核实"
        DISCLAIMER_SHORT = "AI 生成，仅供参考"
        SEP = "·"
    return _Fallback


BRAND = _load_brand()
BOOK_NAME = DEFAULT_COURSE + "_九讲合订本_讲义.pdf"

# ---------- 主机上线（局域网 + 8 位访问码）----------
# 2026-11-16 用户定 A 方案：只在跑服务的这台电脑上线；同一 WiFi 的平板/手机用访问码打开。
# 访问码在启动时生成一次，存 %USERPROFILE%\.pluma\host.json；重启就换新码。
LAN = False            # main() 按 --lan 置 true：只有显式要上线才对外监听
ACCESS_CODE = ""       # 8 位数字；LAN=False 时为空
HOST_PATH = os.path.join(os.path.expanduser("~"), ".pluma", "host.json")
# 2026-11-23 修：笔记目录以前写死 ~\.pluma\notes，绕过了 PLUMA_HOME——自测（PLUMA_HOME=临时目录）
#   造出来的笔记全落进用户真实的笔记目录里（TDEMO 那几十条就是这么来的）。现在跟着 USER_DIR 走。
NOTES_DIR = os.path.join(USER_DIR, "notes")
PDFJS_DIR = paths.res("tools", "print", "pdfjs")

# ---------- 启动自保（2026-11-17 别人机器上「双击打不开」的复盘）----------
# 现场：%TEMP%\clr.py（外来的调试脚本）顶掉了 pythonnet 的 clr，双击 exe 直接崩在
#   pywebview 导入上；弹窗只截到一张图，没有日志可查。
# 为什么会被顶掉：单文件版把解包根目录（%TEMP%）和 exe 所在目录都挂在 sys.path 上，
#   而且排在包内资源之前（实测 sys.path：%TEMP% 在第 5 项，_MEIxxxx 在第 8 项），
#   那两个目录里只要有一个与包内模块同名的 .py，`import clr` 就命中它。
# 做法：启动时先摘掉这类「遮蔽目录」，再把 stdout 兜成可写，最后才碰 webview。
SHADOW_NAMES = ("clr", "clr_loader", "pythonnet", "webview", "fitz", "tkinter")
LOG_DIR_UI = os.path.join(USER_DIR, "logs")


def _inside_res(path: str) -> bool:
    """这个路径是不是包内资源（RES_ROOT）自己或它的子目录。"""
    try:
        p = os.path.abspath(path).lower().rstrip("\\/")
        r = os.path.abspath(paths.RES_ROOT).lower().rstrip("\\/")
    except Exception:  # noqa: BLE001
        return False
    return p == r or p.startswith(r + os.sep)


def _strip_shadowed() -> list:
    """摘掉 sys.path 上「含与包内模块同名 .py」的外来目录，返回 [(目录, 命中文件名)]。

    只动包外的临时目录 / exe 旁边这类地方；包内资源（RES_ROOT）与 site-packages
    一律不碰——真装机器上 pythonnet 本来就该在 site-packages 里。
    """
    hit = []
    for entry in list(sys.path):
        if not entry or _inside_res(entry):
            continue
        low = entry.lower()
        if "site-packages" in low or "dist-packages" in low:
            continue
        try:
            d = os.path.abspath(entry)
            if not os.path.isdir(d):
                continue
            bad = [n for n in SHADOW_NAMES if os.path.isfile(os.path.join(d, n + ".py"))]
        except Exception:  # noqa: BLE001
            continue
        if not bad:
            continue
        while entry in sys.path:
            sys.path.remove(entry)
        hit.append((entry, ", ".join(b + ".py" for b in bad)))
    return hit


def _safe_stdio() -> None:
    """窗口版 exe 的 stdout/stderr 是 nul 流，还可能已被关掉；换成可写的哑流。"""
    for name in ("stdout", "stderr"):
        s = getattr(sys, name, None)
        if s is not None and not getattr(s, "closed", False) and hasattr(s, "write"):
            continue
        try:
            setattr(sys, name, open(os.devnull, "w", encoding="utf-8",
                                    errors="replace", buffering=1))
        except Exception:  # noqa: BLE001
            pass


def _log_write(name: str, text: str) -> str:
    r"""写 %USERPROFILE%\.pluma\logs\<name>，返回路径；写不进去返回空串（不抛）。"""
    try:
        os.makedirs(LOG_DIR_UI, exist_ok=True)
        p = os.path.join(LOG_DIR_UI, name)
        with open(p, "a", encoding="utf-8") as f:
            f.write(text if text.endswith("\n") else text + "\n")
        return p
    except Exception:  # noqa: BLE001
        return ""


def _log_error(where: str, e: BaseException) -> None:
    """请求里出事时留一行：服务不崩、用户看到一句话，事后能查是哪条路由。"""
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        with open(os.path.join(LOG_DIR, "error.log"), "a", encoding="utf-8") as f:
            f.write("%s\t%s\t%r\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), where, e))
    except Exception:  # noqa: BLE001
        pass

sys.path.insert(0, API_DIR)
# 2026-11-17 Word / PPT / 纯文本导入：转换器在 engine\_office.py（只用标准库 + PyMuPDF）
sys.path.insert(0, paths.res("engine"))
try:
    import _office  # noqa: E402
except Exception:  # noqa: BLE001
    _office = None
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
# 2026-11-23 修：这里以前写死 ~\.pluma，绕过了 PLUMA_HOME——自测（PLUMA_HOME=临时目录）造的
#   会话会落进用户真实目录，和笔记目录 NOTES_DIR 当年是同一个坑（见 AGENTS.md §十二.4）。
#   现在跟着 USER_DIR 走：PLUMA_HOME 设了就跟着它，没设才是 ~\.pluma。
SESS_DIR = os.path.join(USER_DIR, "sessions")


def _safe_code(code: str) -> str:
    # 2026-11-19：中文课程名不能再被替换成下划线（「药剂学」曾变成「___」，原件目录直接读不到）。
    # 只挡路径分隔符与控制字符；汉字、字母、数字、点、横线、下划线都保留。
    return re.sub(r"[^0-9A-Za-z_.\-\u4e00-\u9fff]", "_", code or "default")


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
            names.update(x[:-3] for x in os.listdir(d)
                         if x.endswith(".py") and not x.endswith(".en.py"))
    return sorted(names)


def lesson_meta(course: str) -> dict:
    """这一门每讲的显示信息（标题 / 语言 / 是否占位 / 有没有英文版）。

    为什么要：2026-11-18 用户「导入的项目不是原本的名字（导入之后就变成了 T02）」——
    界面以前只显示讲号。这里把数据文件里的 zh 标题读出来给界面，讲号仍做内部编号。
    """
    out = {}
    # 2026-11-22 用户：「A1 生成完了之后 应该要在列表里面消失掉（虽然他还在那个课件里面），
    #   除非在课件里面选择重新生成」——判断全用磁盘事实，不另存状态：
    #   ①原件目录里还有它那份源课件 ②01_讲义 里有 <讲号>_…pdf 的成品。
    #   两条都成立才算「已成稿」。只导入未生成（占位）不算，出厂示例课程（没原件）也不算。
    pdf_names = []
    for _root in (paths.DATA_ROOT, paths.RES_ROOT):
        _d = os.path.join(_root, course, "01_讲义")
        if os.path.isdir(_d):
            pdf_names.extend(os.listdir(_d))
    _od = originals_dir(course)
    orig_stems = set()
    if os.path.isdir(_od):
        orig_stems = {os.path.splitext(fn)[0].lower() for fn in os.listdir(_od)}
    for no in find_lesson(course):
        path = paths.data_or_res(course, "_lessons", no + ".py")
        text = ""
        try:
            with open(path, "r", encoding="utf-8") as fh:
                text = fh.read(400000)   # 读全：orig 字段可能写在文件末尾
        except Exception:  # noqa: BLE001
            pass
        m_zh = re.search(r'"zh":\s*"([^"]*)"', text)
        m_en = re.search(r'"en":\s*"([^"]*)"', text)
        m_orig = re.search(r'"orig":\s*"([^"]*)"', text)
        m_lang = re.search(r'"lang":\s*"([^"]*)"', text)
        en_path = paths.data_or_res(course, "_lessons", no + ".en.py")
        _orig = (m_orig.group(1) if m_orig else "")
        _stub = ("stub-from:" in text or "原件导入占位" in text)
        _stem = os.path.splitext(os.path.basename(_orig))[0].lower() if _orig else ""
        _haspdf = any(fn.startswith(no + "_") and fn.lower().endswith(".pdf")
                      for fn in pdf_names)
        # 2026-11-18：导入的讲显示原件名（02.散剂a），不是讲号 T02；AI 标题放 subtitle
        out[no] = {"title": ((m_orig.group(1) if m_orig else "") or (m_zh.group(1) if m_zh else no)),
                   "subtitle": (m_zh.group(1) if m_zh else ""),
                   "en": (m_en.group(1) if m_en else ""),
                   "lang": (m_lang.group(1) if m_lang else "zh"),
                   "stub": _stub,
                   # 已成稿：原件还在 + 成品已出（两条都要，见函数头注释）
                   "done": bool(_stem and not _stub and _stem in orig_stems and _haspdf),
                   "has_en": os.path.isfile(en_path)}
    return out


def ensure_body(course: str, no: str, lang: str, emit) -> int:
    """点「开始生成」前补齐正文：占位讲次用 DeepSeek 写；全英档没有英文版就生成英文版。

    返回 0 = 可以继续生成；非 0 = 停（日志已经写进 emit）。
    """
    lang = "en" if str(lang).lower().startswith("en") else "zh"
    en_path = paths.data_or_res(course, "_lessons", no + ".en.py")
    zh_path = paths.data_or_res(course, "_lessons", no + ".py")
    text = ""
    try:
        with open(zh_path, "r", encoding="utf-8") as fh:
            text = fh.read(6000)
    except Exception:  # noqa: BLE001
        pass
    need = (lang == "en" and not os.path.isfile(en_path)) or \
           (lang == "zh" and ("stub-from:" in text or "原件导入占位" in text))
    if not need:
        return 0
    try:
        mod = _engine("_draft")
        info = mod.draft(course, no, lang, emit=emit, model=load_cfg().get("model"))
        log_usage(info.get("model") or load_cfg().get("model") or "",
                  info.get("usage") or {})
        return 0
    except Exception as e:  # noqa: BLE001
        # 2026-11-21：用户「中文和英文都没办法生成」。实测这一讲的正文是空的（导入占位），
        #   补正文要先调模型；本机 key 找不到时，报的是一句技术味很重的 RuntimeError，
        #   界面看着就像「生成坏了」。这里换成一句能照做的话，并指出查过哪些位置。
        msg = str(e)
        if "找不到 API key" in msg:
            tried = ""
            try:
                import client as _ac
                hit = [p for p in _ac.config_candidates()]
                tried = "（查过 %d 处：%s）" % (len(hit), "；".join(hit[:3]))
            except Exception:  # noqa: BLE001
                pass
            emit("[停] 这一讲是导入的占位，正文要由模型补，但本机没配置 API 钥匙。")
            emit("     到「设置」里填一次（只存本机 %s），再点开始生成。%s"
                 % (USER_DIR, tried))
        else:
            emit("[停] 补正文失败：%r" % (e,))
        return 1


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


def _inproc(modname: str, args: list, course: str, entry: str, **kw):
    """跑 engine 下的入口，收它的日志；返回 (日志, 退出码)。异常也当红项回报。"""
    buf = []
    try:
        mod = _engine(modname)
        rc = getattr(mod, entry)(list(args), course=course, emit=buf.append, **kw)
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
        # 2026-11-21：界面偏好（主题 / 形态 / 语言 / 上次的课程）跟着配置一起读出来。
        #   注意这里是个白名单字典——不在这里列出来的键读一次就没了。
        "ui": cfg.get("ui") if isinstance(cfg.get("ui"), dict) else {},
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
    # 2026-11-21 用户：「保存目录预设是软件的那个文件夹」——默认值 `out` 就是**软件目录下的 out**，
    #   但界面上只看到两个字「out」，看不出它落在哪儿（截图里显示成 F:/test 那种更是莫名其妙）。
    #   这里把解析出来的绝对路径一起给界面，「当前指向」那一行就能直接写成
    #   `out（相对软件目录）→ F:\…\dist\out`，用户一眼知道预设就是软件自己的文件夹。
    try:
        _abs = out["save_dir"]
        out["save_dir_abs"] = _abs if os.path.isabs(_abs) else os.path.abspath(
            os.path.join(paths.DATA_ROOT, _abs))
    except Exception:  # noqa: BLE001
        out["save_dir_abs"] = out["save_dir"]
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
def courses_meta() -> dict:
    """课程标题/说明：仓里的 courses.json 打底，数据根里的 courses.local.json 覆盖。

    2026-11-22 用户：「那些算后台维护」「只可以保留源代码在仓库里面」——真实课程名不能进公开仓，
    但本机界面上还得显示「操作系统」这种标题。所以把「真实标题」放到**不进 git** 的
    courses.local.json（.gitignore 已忽略），仓里那份只留 DEMO。
    """
    meta = _read_json(paths.data_or_res("courses.json"), {})
    local = _read_json(paths.data("courses.local.json"), {})
    if isinstance(local, dict) and local:
        for k, v in local.items():
            if str(k).startswith("_"):
                continue
            if isinstance(v, dict):
                meta.setdefault(k, {}).update(v)
            else:
                meta[k] = v
    return meta


def discover_courses():
    """扫两根：含 01_讲义 或 _lessons 的目录就是一「门课」。

    2026-11-17：数据根先扫（用户自己的课件），资源根后扫（随程序发布的示例课程）；
    同名时数据根优先——用户把示例课程拷到 exe 旁边改，就看改过的那份。
    """
    meta = courses_meta()
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
        lessons = sorted(x[:-3] for x in os.listdir(les)
                         if x.endswith(".py") and not x.endswith(".en.py")) if os.path.isdir(les) else []
        out.append({"code": name, "title": m.get("title", name), "en": m.get("en", ""),
                    "desc": m.get("desc", "（未填说明，可在 courses.json 里补）"),
                    "files": files, "lessons": lessons, "fav": name in favs,
                    "originals": list_originals(name),
                    "lesson_meta": lesson_meta(name)})
    return out


def pdf_text_chars(pdf_path: str) -> int:
    """PDF 文字层的字符数（去空白）。0 = 扫描件/图片，自动写正文不可用。

    2026-11-19：导入预检与检查器共用这一条；不要再各写一份判断。
    """
    try:
        import pymupdf
        with pymupdf.open(pdf_path) as doc:
            return sum(len((pg.get_text("text") or "").strip()) for pg in doc)
    except Exception:  # noqa: BLE001
        return -1


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
            ext = os.path.splitext(fn)[1].lower()
            kind = (_office.SUFFIX_LABEL.get(ext) if _office else None) or "其他"
            out.append({"name": fn, "size_kb": max(1, round(os.path.getsize(p) / 1024)),
                        "kind": kind, "converted": "（转换）" in fn,
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


def lesson_of_doc(course: str, doc: str) -> str:
    """这份讲义 PDF 属于哪一讲：从文件名前缀 <讲号>_ 认（'L01_进程' → L01，'T02-2_…' → T02-2）。

    为什么要从文件名反推：阅读页手里只有 RD.rel（<课程>/01_讲义/<文件名>），
    而「课件 p.N」要跳的是**这一讲的原件**，中间唯一对得上的就是讲号。
    长讲号优先（T02-2 不能被认成 T02），所以要取最长前缀、不能取第一个命中。
    """
    base = os.path.basename((doc or "").replace("\\", "/"))
    low = os.path.splitext(base)[0].lower()
    hit = ""
    for no in find_lesson(course):
        n = no.lower()
        if (low == n or low.startswith(n + "_")) and len(no) > len(hit):
            hit = no
    return hit


def orig_of(course: str, doc: str, no: str = "") -> dict:
    """讲义正文里「课件 p.N」的出处：这一讲的原件是哪一份、在哪、共几页（只读，不写盘）。

    2026-11-23 用户优化项 F：「讲义里的『课件 p.N』现在只是文字，点了不能跳到原件那一页」。
    讲义是按课件生成的，正文/图注里写着（课件 p.27）这类出处，用户核对时应该一点就跳过去。
    这里只回答「对应哪份原件」，翻页由阅读页做（它已有 openReader(rel, name, code, page)）。

    三种情况分开说清，不做「跳不了也当跳了」：
      ① 阅读页本来就在看原件（00_原件 里的文件）→ same:true，就地翻页；
      ② 讲义文件名认得出讲号 → 走 engine\\_draft.source_of()：先认 stub-from 标记，
         再认 meta 的「源课件」行，最后按标题/唯一原件兜底（**只复用这一处实现**，
         不在这里再写一遍「原件怎么找」）；
      ③ 认不出（合订本 / 附页 / 手动拷进来的 PDF）→ ok:false + 原因，界面照实提示。

    2026-11-23 补（阅读侧栏「会话」）：回答里的「课件 p.N」可能来自**别的讲**，而当前开着的
    是另一份讲义——所以允许显式给讲号 no，这条优先，不再从 doc 反推（① 那条也就让位给讲号）。
    """
    code = _safe_code((course or "").strip() or DEFAULT_COURSE)
    want = str(no or "").strip()
    if want:
        avail = find_lesson(code)
        if want not in avail:
            return {"ok": False, "error": "本课程没有这一讲：%s（现有：%s）"
                                          % (want, "、".join(avail) or "无")}
    parts = [p for p in (doc or "").replace("\\", "/").split("/") if p]
    if not parts and not want:
        return {"ok": False, "error": "缺参数：doc（讲义相对路径）"}
    # ① 在看原件本身：就地翻页。只在没指定讲号时走——指定了讲号，要的是那一讲的原件
    if not want and len(parts) >= 3 and _safe_code(parts[0]) == code and parts[1] == ORIG_DIR:
        full = safe_join(*parts)
        if os.path.isfile(full):
            return {"ok": True, "course": code, "no": "", "same": True,
                    "rel": "%s/%s/%s" % (code, ORIG_DIR, parts[-1]),
                    "name": parts[-1], "pages": _pages(full), "how": "原件本身"}
    no = want or lesson_of_doc(code, parts[-1] if parts else "")
    if not no:
        return {"ok": False, "error": "这一份认不出是哪一讲（合订本 / 附页 / 手动放进来的 PDF）：%s"
                                      % (parts[-1] if parts else "")}
    try:
        full, name = _engine("_draft").source_of(code, no)
    except FileNotFoundError as e:
        return {"ok": False, "no": no, "error": str(e)}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "no": no, "error": "找原件失败：%r" % (e,)}
    return {"ok": True, "course": code, "no": no, "same": False,
            "rel": "%s/%s/%s" % (code, ORIG_DIR, name), "name": name,
            "pages": _pages(full), "how": "source_of"}


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
        "    filetypes=[('课件', '*.pdf *.png *.jpg *.jpeg *.docx *.pptx *.txt *.md'), ('所有文件', '*.*')])\n"
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
                filetypes=[("课件", "*.pdf *.png *.jpg *.jpeg *.docx *.pptx *.txt *.md"), ("所有文件", "*.*")])
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
    if v is None:
        return "None"                      # JSON 的 null 不是合法 Python 字面量
    if isinstance(v, bool):
        return "True" if v else "False"
    if isinstance(v, (int, float)):
        return json.dumps(v)
    return repr(v)


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
        "orig": title, "lang": "zh", "stub": True,
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
# 2026-11-23 用户：右键笔记能选颜色，颜色同时决定 PDF 里那段引用的高亮色。
NOTE_COLORS = ("green", "amber", "blue", "purple", "red")
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


# ---------- 翻译历史（最近 5 条）----------
# 2026-11-22 用户：「翻译历史 5 条」——每次成功翻译记一条，最新在前，最多 5 条；
#   只截前 120 / 400 字，界面用来一键回填，不承担全文归档（全文在侧栏译文里）。
def load_translate_history() -> list:
    data = _read_json(TRANS_HISTORY_PATH, [])
    if not isinstance(data, list):
        return []
    return [x for x in data if isinstance(x, dict)][:TRANS_HISTORY_MAX]


def push_translate_history(src: str, dst: str, to: str, page: int) -> list:
    try:
        page_n = max(1, int(page or 1))
    except Exception:  # noqa: BLE001
        page_n = 1
    item = {
        "at": time.strftime("%Y-%m-%d %H:%M"),
        "src": str(src or "")[:120],
        "dst": str(dst or "")[:400],
        "to": "en" if str(to or "").lower().startswith("en") else "zh",
        "page": page_n,
    }
    items = ([item] + load_translate_history())[:TRANS_HISTORY_MAX]
    _write_json(TRANS_HISTORY_PATH, items)
    return items


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
    # 页脚：与正本一致的口径（文案与地址只从 tools\print\_brand.py 取，见 PRTS R105）
    foot = "%s %s %s ｜ %s" % (BRAND.PRODUCT_NAME, BRAND.SEP, BRAND.PROJECT_URL_TEXT,
                                 BRAND.DISCLAIMER)
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
    def log_message(self, fmt, *args):
        """2026-11-17：http.server 默认把请求行原样写成 ASCII 日志，中文文件名会直接
        抛 UnicodeEncodeError 把连接断掉（实测：带中文名的课件请求直接断开）。
        这里统一转 ASCII，非 ASCII 字符替换掉——日志肉一点，但连接不断。"""
        try:
            line = "%s - %s" % (self.address_string(), fmt % args)
            sys.stderr.write(line.encode("ascii", "replace").decode("ascii") + "\n")
        except Exception:  # noqa: BLE001
            pass

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
            if u.path == "/api/progress":
                d = dict(GEN_PROG)
                d["elapsed"] = round(time.time() - d.pop("t0", time.time()), 1) if d.get("on") else 0
                return self._json(dict(ok=True, **d))
            if u.path == "/api/orig-of":
                # 2026-11-23 用户优化项 F：讲义正文里的「课件 p.N」点了要能打开原件那一页。
                # 只读：不解析 PDF 内容、不写盘，只回答「这一讲的原件是哪一份」。
                # 2026-11-23：第三个数是可选讲号（侧栏「会话」的出处可能属于别的讲）
                return self._json(orig_of(q.get("code", [DEFAULT_COURSE])[0],
                                          q.get("doc", [""])[0],
                                          q.get("no", [""])[0]))
            if u.path == "/api/notes":
                return self._json(dict(ok=True, **load_notes(q.get("code", [DEFAULT_COURSE])[0],
                                                             q.get("doc", [""])[0])))
            if u.path == "/api/translate/history":
                # 2026-11-22：阅读页翻译页签顶部「最近 5 条」只读这里；写入在 /api/translate 成功时。
                return self._json({"ok": True, "items": load_translate_history(),
                                   "max": TRANS_HISTORY_MAX})
            if u.path == "/favicon.ico":
                # 2026-11-17：以前回 204（空图标）——用户「软件图标还没有整上去」。
                # 现在直接给 exe 那张 assets\lapluma.ico，标签页与书签都用它。
                ico = paths.data_or_res("assets", "lapluma.ico")
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
                    # 界面偏好（主题 / 成品形态 / 讲义语言 …）：存本机配置，换端口也不丢。
                    "ui": cfg.get("ui") or {},
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
            if u.path == "/api/update":
                # 2026-11-17 用户：想知道有没有新版、修了什么（给用户看，不写技术细节）
                ch = str(q.get("channel", ["auto"])[0] or "auto").lower()
                return self._json(check_update(bool(q.get("force", [""])[0]),
                                               ch if ch in ("auto", "feed", "github") else "auto"))
            if u.path == "/api/update/progress":
                # 下载进度（前端轮询）：只回状态，不做事
                return self._json(dict(ok=True, **UPD))
            if u.path == "/doc":
                # 向导里的「怎么拿到密钥」「支持哪些格式」直接打开本机文档（新标签可读）
                p = _doc_path(q.get("p", [""])[0])
                if not p:
                    return self._json({"ok": False, "error": "没有这篇文档"}, 404)
                return self._bytes(_render_md(p), os.path.basename(p) + ".html",
                                   "text/html; charset=utf-8")
            return self._json({"ok": False, "error": "无此路由"}, 404)
        except PermissionError as e:
            return self._json({"ok": False, "error": str(e)}, 403)
        except Exception as e:  # noqa: BLE001
            _log_error("GET %s" % u.path, e)
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
            if u.path in ("/api/update/download", "/api/update/apply"):
                # 下载装置与自替换只接本机：局域网里的设备不能替这台电脑换程序
                if self.client_address[0] not in ("127.0.0.1", "::1"):
                    return self._json({"ok": False, "error": "只能在这台电脑上更新"}, 403)
                asset = str(body.get("asset") or "exe")
                if asset not in ("exe", "res"):
                    return self._json({"ok": False, "error": "只会下 exe 或 res"}, 400)
                if u.path.endswith("/download"):
                    return self._json(start_download(asset))
                return self._json(apply_update(asset))
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
                    kind = "trans" if str(note.get("kind") or "") == "trans" else "self"
                    color = str(note.get("c") or "").strip().lower()
                    if color not in NOTE_COLORS:
                        color = "amber" if kind == "trans" else "green"
                    cur.append({"p": int(note.get("p") or 1), "text": text[:2000],
                                # 2026-11-22 用户：记笔记的框里要带一段「引用的原文」（灰、不可改）。
                                #   引用跟着笔记一起存，列表里也能看出这条是拿哪段话起的。
                                "q": str(note.get("q") or "")[:600],
                                # 引用译文时的原文：PDF 上能高亮的是原句，译文在 PDF 里没有
                                "qs": str(note.get("qs") or "")[:600],
                                # self = 自己写的；trans = 引用译文（列表里用不同颜色区分）
                                "kind": kind,
                                # 颜色键（green/amber/blue/purple/red）：标签与 PDF 高亮同色
                                "c": color,
                                "at": time.strftime("%Y-%m-%d %H:%M"),
                                "hhmm": time.strftime("%H:%M")})
                elif act == "color":
                    # 2026-11-23 用户：右键笔记换颜色
                    i = int(body.get("index", -1))
                    color = str(body.get("color") or "").strip().lower()
                    if not (0 <= i < len(cur)):
                        return self._json({"ok": False, "error": "没有这一条"}, 400)
                    if color not in NOTE_COLORS:
                        return self._json({"ok": False, "error": "没有这个颜色：%s" % color}, 400)
                    cur[i]["c"] = color
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
            if u.path == "/api/classify":
                # 2026-11-19：导入后按「文件名 + 首页文字」判断更像哪门课；不自动搬，先问
                cur = _safe_code(str(body.get("course") or DEFAULT_COURSE))
                names = [os.path.basename(str(x)) for x in (body.get("files") or []) if str(x).strip()]
                if not names:
                    return self._json({"ok": False, "error": "没有要分类的文件"}, 400)
                cfg = load_cfg()
                if api_client is None or not cfg.get("api_key"):
                    return self._json({"ok": False, "need_key": True, "error": "没配置 API 钥匙，不能自动分类"})
                courses = [{"code": c["code"], "title": c["title"], "desc": c.get("desc", "")}
                           for c in discover_courses()]
                items = []
                for nm in names:
                    p = os.path.join(originals_dir(cur), nm)
                    text = ""
                    try:
                        if nm.lower().endswith(".pdf"):
                            import pymupdf
                            with pymupdf.open(p) as doc:
                                for i in range(min(2, len(doc))):
                                    text += (doc[i].get_text("text") or "") + "\n"
                    except Exception:  # noqa: BLE001
                        pass
                    items.append({"name": nm, "text": text.strip()[:1200]})
                sysmsg = ("你是课程资料管理员。根据「文件名 + 首页文字」，把每份新导入的课件归到最匹配的已有课程；"
                          "都明显不匹配时，给一个简短的新课程名（中文，如 药剂学）。只输出 JSON 数组，不要解释。")
                user = ("已有课程：\n" + json.dumps(courses, ensure_ascii=False) +
                        "\n\n新导入的原件：\n" + json.dumps(items, ensure_ascii=False) +
                        "\n\n输出格式：[{\"name\":\"…\",\"course\":\"已有课程code或空\","
                        "\"new_title\":\"新课程名或空\",\"confidence\":0.0-1.0,\"reason\":\"一句中文\"}]")
                try:
                    out = api_client.chat([{"role": "system", "content": sysmsg},
                                           {"role": "user", "content": user}],
                                          model=cfg["model"], temperature=0.1, max_tokens=2000)
                except Exception as e:  # noqa: BLE001
                    return self._json({"ok": False, "error": "分类失败：%s" % e}, 502)
                log_usage(out.get("model") or cfg["model"], out.get("usage") or {})
                txt = (out.get("text") or "").strip()
                if txt.startswith(chr(96) * 3):
                    txt = txt.strip(chr(96)).replace("json", "", 1).strip()
                try:
                    arr = json.loads(txt)
                except Exception:  # noqa: BLE001
                    a, b = txt.find("["), txt.rfind("]")
                    arr = json.loads(txt[a:b + 1]) if a >= 0 and b > a else []
                if not isinstance(arr, list):
                    arr = []
                return self._json({"ok": True, "suggestions": arr, "courses": courses})

            if u.path == "/api/move-originals":
                # 用户确认后：原件 + 它的占位讲次一起移到目标课程；不删不改内容
                src = _safe_code(str(body.get("from") or ""))
                dst = _safe_code(str(body.get("to") or ""))
                names = [os.path.basename(str(x)) for x in (body.get("files") or []) if str(x).strip()]
                if not src or not dst or src == dst or not names:
                    return self._json({"ok": False, "error": "参数不完整或源/目标相同"}, 400)
                if not os.path.isdir(paths.course_dir(dst)):
                    return self._json({"ok": False, "error": "目标课程不存在：%s" % dst}, 400)
                moved, skipped = [], []
                s_orig = originals_dir(src)
                d_orig = originals_dir(dst)
                os.makedirs(d_orig, exist_ok=True)
                for nm in names:
                    sp = os.path.join(s_orig, nm)
                    if not os.path.isfile(sp):
                        skipped.append("%s：原件不在" % nm)
                        continue
                    dp = _unique_path(d_orig, nm)
                    try:
                        shutil.move(sp, dp)
                    except Exception as e:  # noqa: BLE001
                        skipped.append("%s：%s" % (nm, e))
                        continue
                    new_nm = os.path.basename(dp)
                    moved.append(new_nm)
                    # 找到对应占位讲次，改 code 后一起搬
                    s_les = paths.data(src, "_lessons")
                    d_les = paths.data(dst, "_lessons")
                    os.makedirs(d_les, exist_ok=True)
                    for py in (os.listdir(s_les) if os.path.isdir(s_les) else []):
                        if not py.endswith(".py") or py.endswith(".en.py"):
                            continue
                        pp = os.path.join(s_les, py)
                        try:
                            txt = open(pp, encoding="utf-8").read()
                        except Exception:  # noqa: BLE001
                            continue
                        if ("stub-from: %s/%s" % (ORIG_DIR, nm)) not in txt:
                            continue
                        txt = txt.replace('"code": "%s"' % src, '"code": "%s"' % dst)
                        txt = txt.replace("stub-from: %s/%s" % (ORIG_DIR, nm),
                                          "stub-from: %s/%s" % (ORIG_DIR, new_nm))
                        tgt = _unique_path(d_les, py)
                        with open(tgt, "w", encoding="utf-8") as fh:
                            fh.write(txt)
                        os.remove(pp)
                return self._json({"ok": bool(moved), "from": src, "to": dst,
                                   "moved": moved, "skipped": skipped})

            if u.path == "/api/course/new":
                # 2026-11-19：以前界面没有「新建课程」，用户只能把原件都导进 DEMO。
                code = _safe_code(str(body.get("code") or "").strip())
                title = str(body.get("title") or "").strip() or code
                if not code or code in ("_", "__"):
                    return self._json({"ok": False, "error": "课程代号不能为空"}, 400)
                if any(c["code"] == code for c in discover_courses()):
                    return self._json({"ok": False, "error": "课程已存在：%s" % code}, 400)
                d = paths.data(code)
                try:
                    for sub in ("_lessons", "01_讲义", "06_笔记", "00_原件"):
                        os.makedirs(os.path.join(d, sub), exist_ok=True)
                    # 2026-11-22：新建课程写进**不进 git** 的 courses.local.json，
                    #   仓里的 courses.json 只留 DEMO（真实课程名不进公开仓）。
                    local_path = paths.data("courses.local.json")
                    local = _read_json(local_path, {})
                    if not isinstance(local, dict):
                        local = {}
                    local[code] = {"title": title, "en": "", "desc": str(body.get("desc") or ""),
                                   "reader": "大学"}
                    _write_json(local_path, local)
                except Exception as e:  # noqa: BLE001
                    return self._json({"ok": False, "error": "新建课程失败：%r" % (e,)}, 500)
                return self._json({"ok": True, "code": code, "title": title})

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
                # 2026-11-17 Word / PPT / 纯文本：导入当场就排成分页 PDF，
                #   后面的阅读页、页码定位（「课件 p.N」）、三道门一行代码都不用改。
                converted = []
                for nm in list(added):
                    try:
                        r = _office.ensure_pdf(os.path.join(d, nm)) if _office else None
                        if r:
                            converted.append("%s → %s（%d 页）" % (nm, os.path.basename(r["pdf"]), r["pages"]))
                    except Exception as e:  # noqa: BLE001
                        _log_error("import/转换 %s" % nm, e)
                        skipped.append("%s：转成分页 PDF 失败（%s）；原件已存下" % (nm, e))
                # 2026-11-17：导入同时建一讲骨架——用户要的是「导进来就能在要生成的批次里看到」
                stubs, warnings = [], []
                for nm in added:
                    try:
                        st = make_stub_lesson(code, nm)
                        if st and st.get("made"):
                            stubs.append(st["no"])
                    except Exception as e:  # noqa: BLE001
                        skipped.append("建讲次失败（%s）：%s" % (nm, e))
                # 2026-11-19：扫描件没有文字层，模型写不了正文——导入当场就说明，别等生成才失败
                for nm in added:
                    pdf = os.path.join(d, os.path.splitext(nm)[0] + ".pdf")
                    if not os.path.isfile(pdf):
                        continue
                    chars = pdf_text_chars(pdf)
                    if 0 <= chars < 50:
                        warnings.append("%s 没有文字层（扫描件/图片），自动写正文不可用；需要先 OCR 或手工补正文。" % nm)
                    elif chars < 0:
                        warnings.append("%s 文字层没查成（读不了 PDF）" % nm)
                return self._json({"ok": bool(added), "course": code, "dir": d,
                                   "added": added, "converted": converted, "skipped": skipped,
                                   "stubs": stubs, "warnings": warnings,
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
                # 2026-11-21 用户：「软件要保留用户的设定（例如我是夜间关闭了软件的 打开也是要
                #   黑夜模式的）」。界面偏好原来只存 localStorage，而 localStorage 是按
                #   http://127.0.0.1:<端口> 分家的——端口一变（上一个实例还占着 8765）就全丢。
                #   现在跟模型/保存目录一起存进本机配置，端口换了一样在。
                if isinstance(body.get("ui"), dict):
                    ui = dict(cfg.get("ui") or {})
                    for k, v in body["ui"].items():
                        k = str(k)[:40]
                        if v is None or isinstance(v, (str, int, float, bool)):
                            ui[k] = v[:400] if isinstance(v, str) else v
                    cfg["ui"] = ui
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
            if u.path == "/api/reveal":
                # 生成完成后「打开本地」：只允许数据根内的路径；打开所在文件夹
                p = os.path.abspath(str(body.get("path") or ""))
                if not p or not p.startswith(os.path.abspath(ROOT) + os.sep):
                    return self._json({"ok": False, "error": "路径不在软件目录内"}, 403)
                if os.path.isfile(p):
                    target = os.path.dirname(p)
                elif os.path.isdir(p):
                    target = p
                else:
                    return self._json({"ok": False, "error": "文件不存在：%s" % p}, 404)
                try:
                    os.startfile(target)  # noqa: S606  Windows 专用
                except Exception as e:  # noqa: BLE001
                    return self._json({"ok": False, "error": "打不开文件夹：%r" % (e,)}, 500)
                return self._json({"ok": True, "opened": target})

            if u.path == "/api/translate":
                # 阅读器「译」按钮：把当前页 PDF 文字翻成中文/英文（一次调用，会花钱）
                rel = str(body.get("rel") or "").strip()
                try:
                    page = int(body.get("page") or 1)
                except Exception:  # noqa: BLE001
                    page = 1
                to = "en" if str(body.get("to") or "zh").lower().startswith("en") else "zh"
                # 2026-11-22 用户：「要一个复制文字进去的内置翻译器（参考 Word）」，以及选中一段
                #   文字右键就能译。带了 text 就译这段，不再读整页。
                src = str(body.get("text") or "").strip()[:6000]
                if not src:
                    if not rel:
                        return self._json({"ok": False, "error": "缺 rel（PDF 相对路径）"}, 400)
                    try:
                        path = safe_join(*[x for x in rel.replace("\\", "/").split("/") if x])
                        import pymupdf
                        with pymupdf.open(path) as doc:
                            if page < 1 or page > len(doc):
                                return self._json({"ok": False, "error": "页码超出范围：%s" % page}, 400)
                            src = (doc[page - 1].get_text("text") or "").strip()
                    except Exception as e:  # noqa: BLE001
                        return self._json({"ok": False, "error": "读不到这一页：%r" % (e,)}, 500)
                if len(src) < 2:
                    return self._json({"ok": False, "error": "这一页没有文字层（扫描件/图片）"}, 400)
                cfg = load_cfg()
                if api_client is None or not cfg.get("api_key"):
                    return self._json({"ok": False, "need_key": True, "error": "没配置 API 钥匙，不能翻译"}, 400)
                sysmsg = ("你是专业译者。把给定 PDF 页文本翻译成英文，保留中文专有名称（药名/方剂名）原样。"
                          "只输出译文，不要解释。" if to == "en" else
                          "你是专业译者。把给定 PDF 页文本翻译成简体中文，专业术语首次出现时在括号里保留英文。"
                          "只输出译文，不要解释。")
                try:
                    out = api_client.chat([{"role": "system", "content": sysmsg},
                                           {"role": "user", "content": src[:6000]}],
                                          model=cfg["model"], temperature=0.2, max_tokens=2400)
                except Exception as e:  # noqa: BLE001
                    return self._json({"ok": False, "error": "翻译失败：%s" % e}, 502)
                log_usage(out.get("model") or cfg["model"], out.get("usage") or {})
                text = out.get("text", "")
                # 2026-11-22：成功一次记一条历史（最多 5 条），随响应回给界面直接重画列表。
                history = push_translate_history(src, text, to, page)
                return self._json({"ok": True, "text": text, "page": page,
                                   "to": to, "chars": len(src), "seconds": out.get("seconds"),
                                   "history": history})

            if u.path == "/api/generate":
                no = str(body.get("lesson", "")).strip()
                course = str(body.get("course", DEFAULT_COURSE)).strip()
                form = str(body.get("form", "single")).strip() or "single"
                # 2026-11-18：输出模式（语言档）。全中 = 中文 + 专业术语英文；全英 = 英文 + 专有名称中文。
                lang = "en" if str(body.get("lang") or "zh").lower().startswith("en") else "zh"
                t0 = time.time()
                set_prog("准备", 5, on=True)
                if form == "book":
                    if lang == "en":
                        return self._json({"ok": False,
                                           "error": "合订本暂只出全中；要英文版请用「单本」逐讲生成"}, 400)
                    # 合订本：默认全部讲，按讲号顺序（B 口径：去掉各讲封面与目录）
                    log, rc = _inproc("_book", [], course, "main")
                    copied = ""
                    if rc == 0:
                        copied = self._copy_out(course, "%s_九讲合订本" % course,
                                                str(body.get("save_dir") or ""))
                    return self._json({"ok": rc == 0, "log": log, "form": "book",
                                       "seconds": round(time.time() - t0, 1), "copied": copied})
                avail = sorted(x[:-3] for x in os.listdir(os.path.join(paths.course_dir(course), "_lessons"))
                               if x.endswith(".py") and not x.endswith(".en.py")) \
                    if os.path.isdir(os.path.join(paths.course_dir(course), "_lessons")) else []
                if no not in avail:
                    return self._json({"ok": False, "error": "没有这一讲：%s" % no}, 400)
                pre = []
                def emit_pre(s):
                    pre.append(s)
                    prog_from_log(s)
                if ensure_body(course, no, lang, emit_pre) != 0:
                    set_prog("补正文失败", 100, on=False)
                    return self._json({"ok": False, "log": "\n".join(pre), "form": "single",
                                       "lang": lang, "seconds": round(time.time() - t0, 1)})
                set_prog("生成讲义源", 65)
                log, rc = _inproc("_make", [no], course, "make", lang=lang)
                for line in str(log).splitlines():
                    prog_from_log(line)
                log = "\n".join([x for x in pre + [log] if x])
                copied = ""
                if rc == 0 and body.get("save_dir"):
                    copied = self._copy_out(course, no, str(body["save_dir"]), lang=lang)
                set_prog("完成" if rc == 0 else "有红项", 100, on=False)
                return self._json({"ok": rc == 0, "log": log, "form": "single", "lang": lang,
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
                # 2026-11-23：阅读侧栏「会话」没有右侧讲次勾选，只带「当前这份讲义」。
                # 讲号由 lesson_of_doc 认（只复用那一处映射）；认不出（合订本/附页/原件）就整门课。
                if not only and not no and body.get("doc"):
                    one = lesson_of_doc(code, str(body.get("doc")))
                    if one:
                        only = [one]
                question = str(body.get("question") or "").strip()
                history = body.get("history") or []
                if not (2 <= len(question) <= 500):
                    return self._json({"ok": False, "error": "问题长度要在 2-500 字之间"}, 400)
                mod = load_ask_module()
                if mod is None:
                    return self._json({"ok": False, "error": "缺少 engine/_ask.py"}, 500)
                avail_all = find_lesson(code)
                # 2026-11-23 用户：在 L03 里问「L01 在说什么」拿不到 L01 的片段。
                #   问题里点了讲号就按讲号走，而不是死守当前这份讲义。
                if not no and question:
                    named = [x for x in avail_all
                             if re.search(r'(?<![0-9A-Za-z])' + re.escape(x) + r'(?![0-9A-Za-z-])',
                                          question, re.I)]
                    if named:
                        only = named
                targets = [(code, no)] if no else [(code, x) for x in avail_all]
                if only and not no:
                    avail = set(avail_all)
                    hit = [(code, x) for x in only if x in avail]
                    if hit:
                        targets = hit
                    elif len(only) == 1:
                        return self._json({"ok": False, "error": "这一讲还没有可检索的数据：%s" % only[0]}, 400)
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
            _log_error("POST %s" % u.path, e)
            return self._json({"ok": False, "error": repr(e)}, 500)

    def _copy_out(self, course, no, dest, lang="zh"):
        """成功后把成品复制到用户选的目录（dest 可在仓内，也可绝对路径）。"""
        if not dest:
            return ""
        # 生成物一律写在数据根（paths.data），自带示例课程也一样——不从资源根拷
        src_dir = os.path.join(ROOT, course, "01_讲义")
        hit = [f for f in os.listdir(src_dir) if f.startswith(no + "_") and f.endswith(".pdf")]
        # 同一讲可能有中文版与英文版：全英档只取 _EN.pdf，别把中文那份复制过去
        if lang == "en":
            hit = [f for f in hit if f.endswith("_EN.pdf")] or hit
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


# ---------- 文档打开与更新检查（2026-11-17）----------
# 2026-11-17：先看数据根——资源包（LaPluma-res.zip）解压到程序目录后就能覆盖内嵌文档
DOC_ROOT = paths.data_or_res("docs")
UPDATE_API = (os.environ.get("PLUMA_UPDATE_URL")
              or "https://api.github.com/repos/Charlotte0124/LaPluma/releases/latest")
UPDATE_CACHE = os.path.join(USER_DIR, "update.json")
UPDATE_TTL = 6 * 3600        # 6 小时内不重复问 GitHub（人家有限流，也不该一直转）


def _doc_path(rel: str) -> str:
    r"""把 /doc?p=使用/08-…md 限在 docs\ 里（绕不出去）。"""
    rel = str(rel or "").replace("\\", "/").lstrip("/")
    root = os.path.abspath(DOC_ROOT)
    p = os.path.abspath(os.path.join(root, rel))
    if not p.startswith(root + os.sep) or not p.lower().endswith(".md") or not os.path.isfile(p):
        return ""
    return p


def _render_md(path: str) -> bytes:
    """极简 Markdown → 网页（不引第三方库：只认标题 / 列表 / 表格 / 代码块 / 行内码）。"""
    txt = open(path, encoding="utf-8").read()
    out, i, lines = [], 0, txt.splitlines()

    def inline(s: str) -> str:
        s = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
        s = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", s)
        s = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', s)
        return s

    while i < len(lines):
        ln = lines[i]
        s = ln.strip()
        if s.startswith("```"):
            i += 1
            buf = []
            while i < len(lines) and not lines[i].strip().startswith("```"):
                buf.append(lines[i])
                i += 1
            i += 1
            out.append("<pre>%s</pre>" % ("\n".join(buf).replace("<", "&lt;").replace(">", "&gt;")))
            continue
        m = re.match(r"^(#{1,6})\s+(.*)$", s)
        if m:
            n = len(m.group(1))
            out.append("<h%d>%s</h%d>" % (n, inline(m.group(2)), n))
            i += 1
            continue
        if s.startswith("|") and i + 1 < len(lines) and re.match(r"^\|[\s:\-|]+\|$", lines[i + 1].strip()):
            head = [c.strip() for c in s.strip("|").split("|")]
            i += 2
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                i += 1
            out.append("<table><tr>%s</tr>%s</table>" % (
                "".join("<th>%s</th>" % inline(c) for c in head),
                "".join("<tr>%s</tr>" % "".join("<td>%s</td>" % inline(c) for c in r) for r in rows)))
            continue
        if re.match(r"^[-*]\s+", s):
            out.append("<ul>")
            while i < len(lines) and re.match(r"^[-*]\s+", lines[i].strip()):
                out.append("<li>%s</li>" % inline(re.sub(r"^[-*]\s+", "", lines[i].strip())))
                i += 1
            out.append("</ul>")
            continue
        if re.match(r"^\d+\.\s+", s):
            out.append("<ol>")
            while i < len(lines) and re.match(r"^\d+\.\s+", lines[i].strip()):
                out.append("<li>%s</li>" % inline(re.sub(r"^\d+\.\s+", "", lines[i].strip())))
                i += 1
            out.append("</ol>")
            continue
        if s in ("---", "***"):
            out.append("<hr>")
            i += 1
            continue
        if not s:
            i += 1
            continue
        out.append("<p>%s</p>" % inline(s))
        i += 1
    body = "\n".join(out)
    html = ("<!doctype html><meta charset='utf-8'><title>%s</title>"
            "<style>body{max-width:820px;margin:36px auto;padding:0 20px;font:15px/1.85 "
            "'Microsoft YaHei',system-ui;color:#1b1a17;background:#F7F5EF}"
            "h1{font-size:26px}h2{font-size:20px;margin-top:34px}h3{font-size:17px}"
            "code{background:#ece8de;padding:1px 5px;border-radius:4px;font-size:13px}"
            "pre{background:#1d1c19;color:#e9e6dd;padding:14px 16px;border-radius:8px;overflow:auto}"
            "table{border-collapse:collapse;margin:14px 0}th,td{border:1px solid #d9d4c6;padding:6px 10px;"
            "text-align:left;vertical-align:top}th{background:#efece2}a{color:#2F7D4F}"
            "</style>[PAGE]" % os.path.basename(path))
    return (html.replace("[PAGE]", body)).encode("utf-8")


def _ver_num(s: str) -> tuple:
    parts = re.findall(r"\d+", str(s))[:3]
    return tuple(int(x) for x in parts) + (0,) * (3 - len(parts))


# ---------- 更新：两条渠道（2026-11-17 用户定）----------
#   feed    自建静态清单 feed\latest.json（随仓库发布）：带 exe / 资源包的大小与 sha256，
#           于是可以「应用内下载 + 自动替换」，全程不打开浏览器。
#   github  Release API：拿标题、正文、页面地址，给「去看看」用；feed 不通时兜底。
# 用户原话：「看看有没有在线更新的方法 而不用跳转到 github（…直接一步跳转通过 CMD 下载）」
#   「以后更新是要分资源包和 exe 本体了」——所以清单里 assets 分 exe / res 两类。
FEED_SCHEMA = "lapluma-feed-v1"
# 2026-11-17：四个源。实测 raw 发版后能拿旧值十几分钟（CDN 缓存），而 githack / statically
#   立刻就是新的——多源取高版本正好治这个。顺序只影响延迟，不影响正确性。
FEED_URLS = [u.strip() for u in (
    os.environ.get("PLUMA_FEED_URLS") or os.environ.get("PLUMA_FEED_URL") or
    "https://raw.githubusercontent.com/Charlotte0124/LaPluma/main/feed/latest.json,"
    "https://raw.githack.com/Charlotte0124/LaPluma/main/feed/latest.json,"
    "https://cdn.statically.io/gh/Charlotte0124/LaPluma/main/feed/latest.json,"
    "https://cdn.jsdelivr.net/gh/Charlotte0124/LaPluma@main/feed/latest.json"
).split(",") if u.strip()]
UPDATE_DIR = os.path.join(USER_DIR, "update")
MAX_ASSET = 300 * 1024 * 1024        # 300 MB 上限：再大就不是更新包了
UPD = {"busy": False, "asset": "", "ver": "", "got": 0, "total": 0, "pct": 0,
       "state": "idle", "error": "", "path": "", "sha256": "", "at": ""}
# 本体与资源包各记一条（2026-11-17 真机整程抳出的 bug：共用一个 UPD 时，
#   先下 exe 再下 res，UPD["path"] 被 res 覆盖 → apply 把 zip 当成 exe 换上去了）
UPD_EXE = {"path": "", "ver": ""}
UPD_RES = {"path": "", "ver": ""}


def _parse_notes(text: str) -> tuple:
    """release 正文 → (一句摘要, 条目列表)。只看 - / * / • 开头的行，取第一句。"""
    summary, notes = "", []
    for ln in str(text or "").splitlines():
        t = ln.strip()
        if not t:
            continue
        m = re.match(r"^<!--\s*摘要[:：]\s*(.*?)\s*-->$", t)
        if m:
            summary = m.group(1)
            continue
        if t.startswith(("-", "*", "•")):
            s = re.sub(r"\*\*|`", "", t.lstrip("-*• ").strip())
            s = re.split(r"[。；;]", s)[0][:100]      # 用户看的是「改了什么」，不是实现
            if s:
                notes.append(s)
    return summary, notes


def _norm_assets(raw) -> dict:
    """清单里的 assets → {exe: {url,size,sha256,name}, res: {...}}；没给的就不出现。"""
    out = {}
    if not isinstance(raw, dict):
        return out
    for key in ("exe", "res"):
        a = raw.get(key)
        if not isinstance(a, dict) or not a.get("url"):
            continue
        url = str(a["url"])
        out[key] = {"url": url, "size": int(a.get("size") or 0),
                    "sha256": str(a.get("sha256") or "").lower(),
                    "name": str(a.get("name") or
                                os.path.basename(urllib.parse.urlparse(url).path) or key)}
    return out


def _try_feed(url: str) -> dict:
    """读单个源；成功返回候选字典，失败抛异常（调用方收集）。"""
    req = urllib.request.Request(url, headers={
        "User-Agent": "LaPluma/%s" % VERSION, "Cache-Control": "no-cache"})
    with urllib.request.urlopen(req, timeout=6) as r:
        body = json.loads(r.read().decode("utf-8-sig"))
    if str(body.get("schema") or "") != FEED_SCHEMA:
        raise ValueError("清单格式不对（schema=%r）" % body.get("schema"))
    latest = str(body.get("latest") or "").lstrip("vV")
    if not latest:
        raise ValueError("清单缺 latest")
    return {"ok": True, "channel": "feed", "current": VERSION, "latest": latest,
            "newer": _ver_num(latest) > _ver_num(VERSION),
            "title": str(body.get("title") or ("v" + latest)),
            "summary": str(body.get("summary") or ""),
            "notes": [str(x) for x in (body.get("notes") or []) if str(x).strip()][:6],
            "url": str(body.get("page") or ""), "assets": _norm_assets(body.get("assets")),
            "checked": time.strftime("%Y-%m-%d %H:%M"), "source": url}


def _fetch_feed() -> dict:
    """读自建清单（多源**并发**读），取版本号最高的那个。

    为什么不是「第一个成功就返回」：CDN 会缓存旧清单（2026-11-17 实测：raw 还给 1.9.7、
    jsDelivr 还给 1.9.5，而 githack / statically 已经是 1.9.8）——谁先到用谁，就可能把用户降级。
    为什么并发：四个源串行最坏 24 秒；并发也就一次往返（实测 ~0.6 s）。
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FTimeout

    best, errs = None, []
    with ThreadPoolExecutor(max_workers=min(4, max(1, len(FEED_URLS)))) as ex:
        futs = {ex.submit(_try_feed, u): u for u in FEED_URLS}
        try:
            for fut in as_completed(futs, timeout=10):   # 按完成先后取，总等待封顶 10 s
                url = futs[fut]
                try:
                    cand = fut.result()
                except Exception as e:  # noqa: BLE001
                    errs.append("%s（%s）" % (e.__class__.__name__, url.split("/")[2]))
                    continue
                if best is None or _ver_num(cand["latest"]) > _ver_num(best["latest"]):
                    if best is not None:
                        cand.setdefault("stale_sources", []).append(best["source"])
                    best = cand
                else:
                    best.setdefault("stale_sources", []).append(url)
        except FTimeout:
            errs.append("总超时")
    if best is None:
        raise RuntimeError("清单都不通（%s）" % ("; ".join(errs) or "没配源"))
    return best


def _fetch_github() -> dict:
    """Release API：标题 / 正文 / 页面地址；顺手把 LaPluma.exe 资产也认出来。"""
    req = urllib.request.Request(UPDATE_API, headers={
        "User-Agent": "LaPluma/%s" % VERSION, "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=4) as r:
        body = json.loads(r.read().decode("utf-8-sig"))
    latest = str(body.get("tag_name") or "").lstrip("vV")
    summary, notes = _parse_notes(body.get("body") or "")
    assets = {}
    for a in body.get("assets") or []:
        nm = str(a.get("name") or "")
        if nm.lower() == "lapluma.exe" and a.get("browser_download_url"):
            assets["exe"] = {"url": str(a["browser_download_url"]),
                             "size": int(a.get("size") or 0), "sha256": "", "name": nm}
    return {"ok": True, "channel": "github", "current": VERSION, "latest": latest,
            "newer": _ver_num(latest) > _ver_num(VERSION),
            "title": str(body.get("name") or ("v" + latest)),
            "summary": summary, "notes": notes[:6],
            "url": str(body.get("html_url") or ""), "assets": assets,
            "checked": time.strftime("%Y-%m-%d %H:%M"), "source": UPDATE_API}


def check_update(force: bool = False, channel: str = "auto") -> dict:
    """看有没有新版。

    2026-11-21 用户：「项目版本那要检测现在本地是什么版本、仓库是什么版本」。
    原来 auto 只问 feed，**feed 一成功就不再问 GitHub**——而 feed 是随仓库发布的清单，
    发版时忘了重跑 make-feed.py 它就一直是旧版本（本机实测：仓里已 1.9.14、GitHub
    Release 也已 1.9.14，清单还停在 1.9.9），于是「检查更新」永远说没有新版。
    现在 auto 两边都问，按版本号取高的那个；同版本时优先用 feed（它带 sha256，能一键换程序），
    并把两边各自报的版本号留在 sources 里，界面可以直说「本地 / 仓库」两个数。

    断网 / 超时 / 限流一律回 ok:False，界面就静默（不打扰用户）。失败不写缓存。
    """
    now = time.time()
    cached = _read_json(UPDATE_CACHE, {})
    data = cached.get("data") if isinstance(cached, dict) else None
    if (not force and isinstance(data, dict) and data.get("ok")
            and now - float(cached.get("ts") or 0) < UPDATE_TTL
            and channel in ("auto", data.get("channel"))):
        # 2026-11-17：缓存里存的是「当时算出来的 newer」。升完版新进程读缓存会继续报有新版，
        # 所以按当前 VERSION 重算一次，不信缓存里的布尔值。
        data = dict(data, cached=True, current=VERSION,
                    newer=_ver_num(data.get("latest")) > _ver_num(VERSION))
        return data

    errs, got = [], {}
    if channel in ("auto", "feed"):
        try:
            got["feed"] = _fetch_feed()
        except Exception as e:  # noqa: BLE001
            errs.append("清单：%s" % e)
    if channel in ("auto", "github"):
        try:
            got["github"] = _fetch_github()
        except Exception as e:  # noqa: BLE001
            errs.append("GitHub：%s" % e.__class__.__name__)
    if not got:
        return {"ok": False, "current": VERSION, "channel": channel,
                "error": "没连上更新源（%s），不影响使用" % "；".join(errs)}

    feed, gh = got.get("feed"), got.get("github")
    # 取版本号最高的那条；同版本优先 feed（有 sha256，能一键更新）
    if feed and (not gh or _ver_num(feed["latest"]) >= _ver_num(gh["latest"])):
        data = dict(feed)
    else:
        data = dict(gh)
    data["sources"] = {k: v["latest"] for k, v in got.items()}
    data["newer"] = _ver_num(data.get("latest")) > _ver_num(VERSION)
    data["current"] = VERSION
    # 2026-11-21：缓存写不进去不能把「检查更新」弄死——实测 update.json 被占用/只读时，
    #   _write_json 抛 PermissionError，整个 /api/update 回 403，界面只看到「读不到仓库版本」。
    #   缓存只是省一次网络往返，写不了就跳过。
    try:
        _write_json(UPDATE_CACHE, {"ts": now, "data": data})
    except Exception as e:  # noqa: BLE001
        _log_error("update cache", e)
    return data


# ---------- 应用内下载与自替换（feed 渠道）----------
def _safe_url(url: str) -> bool:
    """只许 https；本机 http 放行（端到端测试用）。别人改了清单也拿不到 file:// 或内网地址。"""
    p = urllib.parse.urlparse(str(url or ""))
    if p.scheme == "https" and p.hostname:
        return True
    return p.scheme == "http" and p.hostname in ("127.0.0.1", "localhost", "::1")


def _download_worker(url: str, dst: str, size_hint: int, sha: str, asset: str, ver: str) -> None:
    tmp = dst + ".part"
    got = 0
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "LaPluma/%s" % VERSION,
                                                   "Accept": "*/*"})
        with urllib.request.urlopen(req, timeout=15) as r, open(tmp, "wb") as f:
            total = int(r.headers.get("Content-Length") or 0) or size_hint
            h = hashlib.sha256()
            while True:
                chunk = r.read(262144)
                if not chunk:
                    break
                got += len(chunk)
                if got > MAX_ASSET:
                    raise RuntimeError("包超过 300 MB 上限，中止")
                f.write(chunk)
                h.update(chunk)
                UPD.update(got=got, total=total, pct=int(got * 100 / total) if total else 0)
        if size_hint and got != size_hint:
            raise RuntimeError("大小不对：收到 %d，清单写 %d" % (got, size_hint))
        digest = h.hexdigest()
        if sha and digest != sha:
            raise RuntimeError("校验值不对（sha256 %s…）" % digest[:12])
        os.replace(tmp, dst)
        UPD.update(state="done", path=dst, sha256=digest, pct=100, got=got,
                   total=size_hint or got, busy=False)
        if asset == "res":
            UPD_RES.update(path=dst, ver=ver)
        else:
            UPD_EXE.update(path=dst, ver=ver)
    except Exception as e:  # noqa: BLE001
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass
        UPD.update(state="error", error=str(e), busy=False)


def start_download(asset: str = "exe") -> dict:
    """开一个后台线程下包；进度靠 /api/update/progress 轮询（断点续传不做，重下更省事）。"""
    if UPD.get("busy"):
        return {"ok": False, "error": "上一份还在下，等它完成"}
    data = check_update()
    if not data.get("ok"):
        return {"ok": False, "error": data.get("error") or "拿不到更新信息"}
    a = (data.get("assets") or {}).get(asset)
    if not a:
        return {"ok": False, "error": "这一版没有可下载的 %s（去 GitHub 看）" % asset}
    if not _safe_url(a["url"]):
        return {"ok": False, "error": "下载地址不是 https，已拒绝"}
    ver = data.get("latest") or "0"
    d = os.path.join(UPDATE_DIR, "v" + _ver_num_str(ver))
    os.makedirs(d, exist_ok=True)
    dst = os.path.join(d, a["name"])
    UPD.update(busy=True, asset=asset, ver=ver, got=0, total=int(a.get("size") or 0), pct=0,
               state="downloading", error="", path="", sha256="",
               at=time.strftime("%H:%M:%S"))
    threading.Thread(target=_download_worker,
                     args=(a["url"], dst, int(a.get("size") or 0), a.get("sha256") or "",
                           asset, ver), daemon=True).start()
    return {"ok": True, "started": True, "ver": ver, "asset": asset,
            "size": int(a.get("size") or 0)}


def _ver_num_str(ver: str) -> str:
    return re.sub(r"[^0-9A-Za-z.\-_]", "", str(ver or "0")) or "0"


def app_exe() -> str:
    """要被换掉的那个文件：打包版是自己；源码版是 dist\\LaPluma.exe。

    PLUMA_APPLY_TARGET 只给判据和端到端测试用（指到临时副本，不许动真实 dist）。
    """
    if os.environ.get("PLUMA_APPLY_TARGET"):
        return os.path.abspath(os.environ["PLUMA_APPLY_TARGET"])
    if getattr(sys, "frozen", False):
        return os.path.abspath(sys.executable)
    return os.path.abspath(os.path.join(paths.DATA_ROOT, "dist", "LaPluma.exe"))


def write_apply_bat(new_path: str, target: str, res_zip: str = "",
                    relaunch: bool = True, pid: int | None = None) -> str:
    """写 apply.bat：等本进程退出 → 备份 .bak → 覆盖 →（解资源包）→ 重启 → 自删。

    为什么要绕一道 bat：Windows 不允许覆盖正在运行的 exe，只能让本进程先退、
    由外部脚本接手。bat 里不写中文（cmd 的码页与文件编码会在半路换），日志写 update.log。
    pid 默认为本进程；判据里传一个不存在的 PID 才能单独验证替换动作（否则自己等自己）。
    等不到就 120 秒后放手，不能永远挂着（判据里踩过：bat 自己等自己 → 卡死）。
    """
    os.makedirs(UPDATE_DIR, exist_ok=True)
    bat = os.path.join(UPDATE_DIR, "apply.bat")
    log = os.path.join(UPDATE_DIR, "update.log")
    appdir = os.path.dirname(os.path.abspath(target))
    lines = [
        "@echo off",
        # 路径里可能有中文（用户的目录常在中文盘/中文文件夹）。cmd 逐行按当前码页读 bat，
        # 不先切到 65001 的话，下面的 set "TGT=F:\文件\..." 会被当 GBK 读成乱码。
        # （真机整程在 %TEMP% 英文路径下跑，不会暴露这一条）
        "chcp 65001 >nul 2>&1",
        "setlocal",
        'set "PID=%d"' % (os.getpid() if pid is None else int(pid)),
        'set "NEW=%s"' % new_path,
        'set "TGT=%s"' % target,
        'set "RES=%s"' % res_zip,
        'set "APPDIR=%s"' % appdir,
        'set "LOG=%s"' % log,
        'echo [apply] %date% %time% start >> "%LOG%"',
        'if not exist "%NEW%" (echo [apply] new file missing >> "%LOG%" & exit /b 2)',
        "set /a n=0",
        ":wait",
        'if "%PID%"=="0" goto ready',
        'tasklist /FI "PID eq %PID%" /NH 2>nul | find "%PID%" >nul',
        "if errorlevel 1 goto ready",
        "set /a n+=1",
        'if %n% gtr 120 (echo [apply] wait timeout >> "%LOG%" & goto ready)',
        "ping -n 2 127.0.0.1 >nul",
        "goto wait",
        ":ready",
        'if exist "%TGT%" copy /y "%TGT%" "%TGT%.bak" >nul',
        'move /y "%NEW%" "%TGT%" >nul',
        'if errorlevel 1 (echo [apply] replace failed >> "%LOG%" & exit /b 3)',
        'echo [apply] %date% %time% replaced ok >> "%LOG%"',
        'if not "%RES%"=="" if exist "%RES%" powershell -NoProfile -ExecutionPolicy Bypass '
        '-Command "Expand-Archive -LiteralPath $env:RES -DestinationPath $env:APPDIR -Force" '
        '>> "%LOG%" 2>&1',
    ]
    if relaunch:
        lines.append('start "" "%TGT%"')
    lines += ["ping -n 2 127.0.0.1 >nul", '(goto) 2>nul & del "%~f0"']
    with open(bat, "w", encoding="utf-8", newline="") as f:
        f.write("\r\n".join(lines) + "\r\n")
    return bat


def _quit_self() -> None:
    """先关窗口（pywebview 要主线程收尾），再硬退：bat 里正等这个 PID 消失。"""
    try:
        import webview
        for w in list(webview.windows):
            try:
                w.destroy()
            except Exception:  # noqa: BLE001
                pass
    except Exception:  # noqa: BLE001
        pass
    time.sleep(0.6)
    os._exit(0)


def apply_update(asset: str = "exe") -> dict:
    """把下好的包换上并重启。只接本机请求（局域网里的人不能替你重启程序）。"""
    exe_path = UPD_EXE.get("path") or ""
    if not exe_path or not os.path.isfile(exe_path):
        return {"ok": False, "error": "还没下好程序本体（当前状态：%s）" % UPD.get("state")}
    # 防呆：换上去的必须是本体。真机整程揭过一个 bug——资源包（zip）被当成 exe 换了。
    if os.path.getsize(exe_path) < 64 * 1024:
        return {"ok": False, "error": "下到的本体只有 %d 字节，不是程序，已拒绝" % os.path.getsize(exe_path)}
    if not exe_path.lower().endswith(".exe"):
        return {"ok": False, "error": "要换上去的不是 .exe（%s），已拒绝" % os.path.basename(exe_path)}
    target = app_exe()
    if not os.path.isfile(target):
        return {"ok": False, "error": "找不到要替换的程序：%s" % target}
    ver = UPD_EXE.get("ver") or UPD.get("ver")
    res = UPD_RES["path"] if (UPD_RES.get("path") and UPD_RES.get("ver") == ver
                               and os.path.isfile(UPD_RES["path"])) else ""
    bat = write_apply_bat(exe_path, target, res,
                         relaunch=os.environ.get("PLUMA_NO_RELAUNCH") != "1")
    # 不能用 DETACHED_PROCESS：doteached 进程没有控制台，cmd 里的 tasklist | find 会挂死
    # （实测：日志只写到 start 就不动，等满两分钟也不换文件）。CREATE_NO_WINDOW 有控制台但隐藏。
    subprocess.Popen(["cmd", "/c", bat], cwd=UPDATE_DIR, close_fds=True,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, creationflags=0x08000000)
    threading.Timer(1.2, _quit_self).start()
    return {"ok": True, "restart": True, "target": target, "bat": bat,
            "from": exe_path, "ver": ver, "res": res}



class _WinApi:
    """自绘标题栏的窗口控制（JS 侧 pywebview.api.minimize() / close() 等）。"""

    def __init__(self):
        self.maxed = False
        self._bounds = None
        # relayout 会「把窗口加 1px 再改回来」逼 WebView2 重算表面；两个线程同时做会互相
        # 踩出 1~2px 的漂移（真窗口量测见过 842 → 844），所以串起来。
        self._relock = threading.Lock()
        # 2026-11-23 用户：「一直闪烁、指针都在闪」。成因是 relayout 的 +1px 触发了页面 resize，
        # 页面又回头调 relayout，成了自激循环。页面侧已吞掉自己那 1px 的回声；这里再加一道闸：
        # 冷却期内重复调用直接跳过（返回 skip 字段，不假装做了），任何调用方都掀不起风暴。
        self._last_relayout = 0.0
        self.REL_COOLDOWN = 0.45

    def keep_bounds(self):
        """记下进入全屏前的窗口矩形。

        2026-11-22 用户：「从全屏退出之后会占据整个屏幕，没办法缩小」——退出时原来只把
        .fs 那个 class 去掉，窗口本身还是全屏尺寸。进全屏前存一次，退出时照原样设回去。
        """
        try:
            import ctypes
            import ctypes.wintypes as wt
            h = _find_hwnd()
            if not h:
                return {"ok": False}
            r = wt.RECT()
            ctypes.windll.user32.GetWindowRect(wt.HWND(h), ctypes.byref(r))
            self._bounds = (int(r.left), int(r.top), int(r.right - r.left), int(r.bottom - r.top))
            return {"ok": True, "rect": list(self._bounds)}
        except Exception as e:  # noqa: BLE001
            _log_error("keep_bounds", e)
            return {"ok": False}

    def restore_bounds(self):
        """退出全屏：把 keep_bounds() 记下的矩形设回去，并让系统重算边框。

        2026-11-22 用户：「从全屏退出之后会占据整个屏幕，没办法缩小」。只设一次
        SetWindowPos(SWP_SHOWWINDOW) 在 WebView2 里会被「退出 HTML 全屏后浏览器再撑一次」
        盖回去；这里补 SWP_FRAMECHANGED（重算非客户区/边框）并连设两次（间隔 80ms），
        第二次把浏览器退出全屏后的尺寸盖回记下的矩形。最大化状态先 SW_RESTORE，
        否则 SetWindowPos 改不动一个最大化窗口。
        """
        try:
            import ctypes
            import ctypes.wintypes as wt
            u = ctypes.windll.user32
            h = _find_hwnd()
            b = self._bounds
            if not h or not b:
                return {"ok": False}
            x, y, w, hh = b
            if u.IsZoomed(wt.HWND(h)):
                u.ShowWindow(wt.HWND(h), 9)  # SW_RESTORE
            # SWP_SHOWWINDOW(0x0040) | SWP_FRAMECHANGED(0x0020)
            flags = 0x0040 | 0x0020
            for _ in range(2):
                u.SetWindowPos(wt.HWND(h), None, int(x), int(y),
                               int(w), int(hh), flags)
                time.sleep(0.08)
            r = wt.RECT()
            u.GetWindowRect(wt.HWND(h), ctypes.byref(r))
            # 尺寸变完让 WebView2 的子窗口跟上（否则窗口下半截是黑的，见 relayout 的注释）
            self._relayout_later(0.16)
            return {"ok": True, "rect": list(b),
                    "after": [int(r.left), int(r.top), int(r.right - r.left), int(r.bottom - r.top)]}
        except Exception as e:  # noqa: BLE001
            _log_error("restore_bounds", e)
            return {"ok": False}

    def _win(self):
        try:
            import webview
            return webview.windows[0] if webview.windows else None
        except Exception:  # noqa: BLE001
            return None

    def minimize(self):
        w = self._win()
        if w:
            w.minimize()
        return {"ok": bool(w)}

    def relayout(self):
        """窗口尺寸变过之后，逼 WebView2 重算一次绘制表面。

        2026-11-22 用户：「全屏打开记笔记 → 回课程 → 打开课程文件夹 → 再在软件里读，
        变成一大片黑」。**诚实地说：这个现象在本机没能复现**（同样的路径跑了三遍，画面都正常），
        所以这里是按已知的 WebView2 失效模式做的兜底，不是「已定位的修复」：
          ① 窗口模式下 WebView2 的宿主是个子窗口，父窗口变大它不会自己跟上——有子窗口就按
             父客户区重设一次（EnumChildWindows；这台机器上只有一个 0×0 的 Chrome_WidgetWin_0，
             说明是**无窗口/合成模式**，这一步走了个空）。
          ② 合成模式下没有可改的子窗口，只能「把窗口高度 +1px 再改回来」逼它收一次 WM_SIZE，
             这是 WebView2 合成表面没跟上时的常规解法。
          ③ RedrawWindow 强制重画一遍。
        另外界面底色铺成不透明（html/body 背景），就算表面还是没跟上，露出来的也是界面底色
        而不是纯黑。能钉住的部分见 tools/check/check-window-real.py 的 W7/W8。
        """
        try:
            import ctypes
            import ctypes.wintypes as wt
            u = ctypes.windll.user32
            hwnd = _find_hwnd()
            if not hwnd:
                return {"ok": False, "error": "找不到窗口句柄"}
            if not self._relock.acquire(blocking=False):
                return {"ok": True, "busy": True}      # 另一个 relayout 正在做，跳过就好
            try:
                if time.time() - self._last_relayout < self.REL_COOLDOWN:
                    # 冷却中：不重设窗口（重设就是那 1px 抖动本身），如实说跳过了
                    return {"ok": True, "skipped": "cooldown",
                            "since": round(time.time() - self._last_relayout, 3)}
                return self._relayout_locked(hwnd, ctypes, wt, u)
            finally:
                self._relock.release()
        except Exception as e:  # noqa: BLE001
            _log_error("relayout", e)
            return {"ok": False, "error": str(e)}

    def _relayout_locked(self, hwnd, ctypes, wt, u):
        try:
            u.SetWindowPos.argtypes = [wt.HWND, wt.HWND, ctypes.c_int, ctypes.c_int,
                                       ctypes.c_int, ctypes.c_int, ctypes.c_uint]
            flags = 0x0002 | 0x0004 | 0x0010 | 0x0020   # NOMOVE|NOZORDER|NOACTIVATE|FRAMECHANGED
            n = []

            def cb(child, _l):
                parent = u.GetParent(child) or hwnd
                pr = wt.RECT()
                u.GetClientRect(wt.HWND(parent), ctypes.byref(pr))
                if pr.right > 0 and pr.bottom > 0:
                    u.SetWindowPos(wt.HWND(child), None, 0, 0, pr.right, pr.bottom, flags)
                    n.append((pr.right, pr.bottom))
                return True

            CB = ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
            u.EnumChildWindows(wt.HWND(hwnd), CB(cb), 0)
            # 实测这台机器上 WebView2 是**无窗口（合成）模式**：EnumChildWindows 只有一个
            # 0×0 的 Chrome_WidgetWin_0，没有可重设尺寸的子窗口。合成表面没跟上时，
            # 只能靠「把窗口高度改 1px 再改回来」逼它收一次 WM_SIZE 重算表面。
            r = wt.RECT()
            u.GetWindowRect(wt.HWND(hwnd), ctypes.byref(r))
            x, y = int(r.left), int(r.top)
            w0, h0 = int(r.right - r.left), int(r.bottom - r.top)
            # SWP_NOREDRAW(0x0008)：这一下是「暗改尺寸」，不让它重画，否则那 1px 会上屏闪一下
            away = 0x0002 | 0x0004 | 0x0010 | 0x0008   # NOMOVE|NOZORDER|NOACTIVATE|NOREDRAW
            u.SetWindowPos(wt.HWND(hwnd), None, x, y, w0, h0 + 1, away)
            time.sleep(0.05)
            u.SetWindowPos(wt.HWND(hwnd), None, x, y, w0, h0, away)
            # 收尾再设一次原矩形并等它落地：不留 1px 的漂移（真窗口量测要求 ±2px 内）
            time.sleep(0.06)
            u.SetWindowPos(wt.HWND(hwnd), None, x, y, w0, h0, away)
            # RDW_INVALIDATE|RDW_ALLCHILDREN|RDW_UPDATENOW|RDW_FRAME
            u.RedrawWindow(wt.HWND(hwnd), None, None, 0x0001 | 0x0080 | 0x0100 | 0x0400)
            self._last_relayout = time.time()
            return {"ok": True, "children": len(n)}
        except Exception as e:  # noqa: BLE001
            _log_error("relayout", e)
            return {"ok": False, "error": str(e)}

    def _relayout_later(self, delay: float = 0.12) -> None:
        """窗口尺寸刚变完别立刻抢着改子窗口（系统还在跑那套动画）。"""
        def run():
            time.sleep(delay)
            self.relayout()
        threading.Thread(target=run, daemon=True).start()

    def toggle_max(self):
        """最大化 / 还原：状态以窗口真实状态（IsZoomed）为准，不靠自己的布尔变量。

        2026-11-22 实测：窗口先被系统最大化（双击标题条 / Aero Snap）之后，这里记的
        maxed 还是 False，于是点一次「最大化」只会再最大化一次，永远还原不了。
        """
        try:
            import ctypes
            import ctypes.wintypes as wt
            u = ctypes.windll.user32
            hwnd = _find_hwnd()
            if not hwnd:
                return {"ok": False}
            h = wt.HWND(hwnd)
            if u.IsZoomed(h):
                u.ShowWindow(h, 9)      # SW_RESTORE
                maxed = False
            else:
                u.ShowWindow(h, 3)      # SW_MAXIMIZE
                maxed = True
            self._relayout_later()
            return {"ok": True, "maxed": maxed}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e)}

    def close(self):
        w = self._win()
        if w:
            w.destroy()
        return {"ok": bool(w)}

    def drag_window(self):
        """标题条按住 → 跟着鼠标挪窗口（自己实现拖动循环）。

        2026-11-22 的两次弯路都记在这里，免得再走回去：
          ① 最早是 JS pointermove + move_by：每一小步都过一次 JS→Python 桥，动一下就卡，
             指针离开标题条还丢事件，用户看到的是「拖不动」。
          ② 改成 ReleaseCapture + SendMessage(WM_NCLBUTTONDOWN, HTCAPTION) 交给系统：
             实测**无效**（本窗口是 pywebview 的无边框 WinForms 窗口，WinForms 的 WndProc
             不把 WM_NCLBUTTONDOWN 交给 DefWindowProc，所以系统拖动循环根本不启动；
             SendMessage 立刻返回 0，窗口纹丝不动，见 tools/check/check-window-real.py --drag）。
          现在：在本线程里跑一个拖动循环——一直读系统光标位置（GetCursorPos，不依赖浏览器
          事件，所以指针甩出窗口也不丢），窗口左上角 = 按下时的左上角 + 光标位移，
          鼠标键松开（GetAsyncKeyState）就退出。这是自己实现，但用的是系统光标，跟手。
        """
        try:
            import ctypes
            import ctypes.wintypes as wt
            u = ctypes.windll.user32
            hwnd = _find_hwnd()
            if not hwnd:
                return {"ok": False, "error": "找不到窗口句柄"}
            h = wt.HWND(hwnd)
            if u.IsZoomed(h):
                # 最大化的窗口先还原（与系统行为一致：拖一个最大化窗口 = 还原）
                u.ShowWindow(h, 9)          # SW_RESTORE
                return {"ok": True, "restored": True}
            # 12.2：SetWindowPos 参数类型显式写清，64 位下不写会按 int 截断句柄
            u.SetWindowPos.argtypes = [wt.HWND, wt.HWND, ctypes.c_int, ctypes.c_int,
                                       ctypes.c_int, ctypes.c_int, ctypes.c_uint]
            r = wt.RECT()
            u.GetWindowRect(h, ctypes.byref(r))
            x0, y0 = int(r.left), int(r.top)
            p = wt.POINT()
            u.GetCursorPos(ctypes.byref(p))
            cx0, cy0 = int(p.x), int(p.y)
            # SWP_NOSIZE(0x1) | SWP_NOZORDER(0x4) | SWP_NOACTIVATE(0x10)
            flags = 0x0001 | 0x0004 | 0x0010
            moved = 0
            deadline = time.time() + 60.0
            while time.time() < deadline:
                time.sleep(0.008)
                if not (u.GetAsyncKeyState(0x01) & 0x8000):   # VK_LBUTTON 已松开
                    break
                u.GetCursorPos(ctypes.byref(p))
                dx, dy = int(p.x) - cx0, int(p.y) - cy0
                if dx or dy:
                    u.SetWindowPos(h, None, x0 + dx, y0 + dy, 0, 0, flags)
                    moved += 1
            self._relayout_later()
            return {"ok": True, "moved": moved}
        except Exception as e:  # noqa: BLE001
            _log_error("drag_window", e)
            return {"ok": False, "error": str(e)}

    def start_drag(self):
        """旧名保留（老页面可能还在调）；行为与 drag_window 相同。"""
        return self.drag_window()

    def get_box(self):
        """窗口位置与大小（拉边缩放用）。"""
        try:
            import ctypes
            import ctypes.wintypes as wt
            u = ctypes.windll.user32
            hwnd = _find_hwnd()
            if not hwnd:
                return {"ok": False}
            r = wt.RECT()
            u.GetWindowRect(hwnd, ctypes.byref(r))
            return {"ok": True, "x": r.left, "y": r.top,
                    "w": r.right - r.left, "h": r.bottom - r.top,
                    "maxed": bool(u.IsZoomed(hwnd))}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e)}

    def set_box(self, x: int, y: int, w: int, h: int):
        """移动到 (x,y) 并改成 w×h（拉边缩放用；最大化时拒绝）。"""
        try:
            import ctypes
            import ctypes.wintypes as wt
            u = ctypes.windll.user32
            hwnd = _find_hwnd()
            if not hwnd or u.IsZoomed(hwnd):
                return {"ok": False}
            w = max(640, int(w)); h = max(480, int(h))
            # SWP_NOZORDER(0x4) | SWP_NOACTIVATE(0x10)
            u.SetWindowPos(hwnd, 0, int(x), int(y), w, h, 0x0014)
            self._relayout_later()
            return {"ok": True, "x": int(x), "y": int(y), "w": w, "h": h}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e)}

    def move_by(self, dx: int, dy: int):
        """拖标题栏的旧方案（保留作非 Windows / 原生拖拽不可用时的回退）。"""
        w = self._win()
        if not w or self.maxed:
            return {"ok": False}
        try:
            w.move(int(w.x + int(dx)), int(w.y + int(dy)))
        except Exception:  # noqa: BLE001
            return {"ok": False}
        return {"ok": True}


def _find_hwnd() -> int:
    """找本进程的可见顶层窗口句柄（pywebview 6.x 的 window.native 是 None）。

    2026-11-19：标题栏拖拽改用 Windows 原生的 WM_NCLBUTTONDOWN，需要真句柄；
    与 _enable_resize 同一套 EnumWindows 逻辑，抽出来共用。
    """
    try:
        import ctypes
        import ctypes.wintypes as wt
        u = ctypes.windll.user32
        GWL_STYLE, WS_VISIBLE = -16, 0x10000000
        hits = []
        CB = ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)

        def cb(hwnd, _l):
            pid = wt.DWORD()
            u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value == os.getpid():
                st = u.GetWindowLongW(hwnd, GWL_STYLE)
                if st & WS_VISIBLE:
                    hits.append(hwnd)
            return True

        u.EnumWindows(CB(cb), 0)
        return int(hits[0]) if hits else 0
    except Exception:  # noqa: BLE001
        return 0


def _force_foreground(hwnd: int) -> None:
    """把刚起的窗口拉到最前。

    2026-11-21 用户：「启动羽毛笔.cmd 也没有用 打不开」——实测窗口是起来了，
    但双击时前台是别的全屏程序（BlueStacks），窗口开在它后面，用户就当没打开。
    Windows 的前台锁会让 SetForegroundWindow 直接失败，所以补两手：
    先 SW_RESTORE + BringWindowToTop，再用 SwitchToThisWindow（任务栏点击走的就是它）。
    """
    try:
        import ctypes
        u = ctypes.windll.user32
        import ctypes.wintypes as wt
        before = int(u.GetForegroundWindow() or 0)
        bits = 8 * ctypes.sizeof(ctypes.c_void_p)
        topmost = ctypes.c_void_p((1 << bits) - 1)      # HWND_TOPMOST
        notop = ctypes.c_void_p((1 << bits) - 2)        # HWND_NOTOPMOST
        SWP = 0x0001 | 0x0002 | 0x0040                  # NOSIZE | NOMOVE | SHOWWINDOW
        u.SetWindowPos.argtypes = [wt.HWND, wt.HWND, ctypes.c_int, ctypes.c_int,
                                   ctypes.c_int, ctypes.c_int, ctypes.c_uint]
        u.SetWindowPos(wt.HWND(hwnd), topmost, 0, 0, 0, 0, SWP)
        u.ShowWindow(hwnd, 9)               # SW_RESTORE
        u.BringWindowToTop(hwnd)
        u.SetForegroundWindow(hwnd)
        if int(u.GetForegroundWindow() or 0) != hwnd:
            try:
                u.SwitchToThisWindow(hwnd, True)
            except Exception:  # noqa: BLE001
                pass
        after = int(u.GetForegroundWindow() or 0)

        # 置顶只留 2.5 秒：够用户看见「打开了」，又不会一直压在所有程序上面。
        #   全屏游戏（BlueStacks）会把前台抢回去，所以必须靠这 2.5 秒让人看见。
        def _drop_topmost():
            time.sleep(2.5)
            try:
                u.SetWindowPos(wt.HWND(hwnd), notop, 0, 0, 0, 0, 0x0001 | 0x0002)
            except Exception:  # noqa: BLE001
                pass

        threading.Thread(target=_drop_topmost, daemon=True).start()
        _log_write("startup.log", "%s 前置窗口 0x%X：前台 0x%X → 0x%X（置顶 2.5 秒）"
                   % (time.strftime("%Y-%m-%d %H:%M:%S"), hwnd, before, after))
    except Exception as e:  # noqa: BLE001
        _log_error("force_foreground", e)


def _enable_resize() -> None:
    """无边框窗口默认丢了拉边缩放与贴边；把 WS_THICKFRAME / 最大最小化位补回去。

    2026-11-17：pywebview 6.2.1 的 window.native 是 None（拿不到句柄），改用
    EnumWindows 找本进程的可见顶层窗口。webview.start(func=) 里调一次，
    窗体可能还没显示，所以再延时重试一次。
    """
    def apply(tag: str = "") -> bool:
        try:
            import ctypes
            import ctypes.wintypes as wt
            u = ctypes.windll.user32
            GWL_STYLE, WS_VISIBLE = -16, 0x10000000
            add = 0x00040000 | 0x00010000 | 0x00020000       # THICKFRAME | MAXIMIZEBOX | MINIMIZEBOX
            hits = []
            CB = ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)

            def cb(hwnd, _l):
                pid = wt.DWORD()
                u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                if pid.value == os.getpid():
                    st = u.GetWindowLongW(hwnd, GWL_STYLE)
                    if st & WS_VISIBLE:
                        u.SetWindowLongW(hwnd, GWL_STYLE, st | add)
                        u.SetWindowPos(hwnd, 0, 0, 0, 0, 0, 0x0027)
                        hits.append((hwnd, st, u.GetWindowLongW(hwnd, GWL_STYLE)))
                return True

            u.EnumWindows(CB(cb), 0)
            if hits:
                _log_write("startup.log", "%s 补回窗口可缩放样式%s：%d 个窗口，首个 0x%X → 0x%X"
                           % (time.strftime("%Y-%m-%d %H:%M:%S"), tag, len(hits),
                              hits[0][1] & 0xFFFFFFFF, hits[0][2] & 0xFFFFFFFF))
                _force_foreground(hits[0][0])
                return True
            _log_write("startup.log", "%s 没找到可用的顶层窗口（可缩放未补）%s"
                       % (time.strftime("%Y-%m-%d %H:%M:%S"), tag))
        except Exception as e:  # noqa: BLE001
            _log_error("enable_resize", e)
        return False

    def later():
        time.sleep(1.2)
        apply("（重试）")

    if not apply():
        threading.Thread(target=later, daemon=True).start()


def run_window(url: str) -> int:
    """把界面放进一个原生窗口（Windows 上走 WebView2 / Edge）。

    2026-11-17 用户问「为什么都是网页版，不应该是一个软件吗」——以前是本地服务 + 浏览器页，
    看着像网页。现在双击/启动直接是一个自己的窗口，带图标与标题，关窗口就退出。
    想要回浏览器（例如平板、远程调试）用 --no-window。
    """
    import webview
    # 2026-11-21 用户：「我指的是这种方式测试（浏览器打开 127.0.0.1）有很多 BUG 都找不到，
    #   打包的时候就一大堆 BUG 出来——直接用打包 APP 去测试」。
    #   要驱动**真窗口里的页面**，只能走 WebView2 的远程调试端口：设了 PLUMA_TEST_CDP=<端口>
    #   才开（只在自测里用，正常启动完全不受影响）。tools\check\check-fresh-install.py 用它
    #   连上来真点按钮——顶栏挡 UI 这类 bug 只有真窗口里点得出来，走接口是看不见的。
    _cdp = (os.environ.get("PLUMA_TEST_CDP") or "").strip()
    if _cdp.isdigit():
        try:
            webview.settings["REMOTE_DEBUGGING_PORT"] = int(_cdp)
            print("  自测模式：WebView2 远程调试端口 %s" % _cdp, flush=True)
        except Exception:  # noqa: BLE001
            pass
    # 2026-11-17 用户：「exe 顶栏能不能和软件 UI 融为一体，系统那个太突出了」——
    #   改成无边框窗口（frameless），标题栏由界面自己画（拖拽 / 最小化 / 最大化 / 关闭都走 _WinApi）。
    #   缩放与贴边靠 _enable_resize() 把 WS_THICKFRAME 补回去，不让用户丢掉拉边与 Win+←→。
    api = _WinApi()
    win_url = url + ("&" if "?" in url else "?") + "win=1"   # 页面靠它判断「该不该画自绘标题栏」
    # 2026-11-17：默认 1280×880 在 1366×768 的笔记本上比屏幕还高，窗口底部与右下角的提示卡
    #   会跑到屏幕外面（实测截图只看到卡片的上边缘）。按屏幕工作区的 86% 收一下，但不小于最小值。
    def _workarea() -> tuple:
        """主屏工作区（去掉任务栏），窗口按它居中；不再让窗口停到屏幕左上/外面。"""
        try:
            import ctypes.wintypes as wt
            u = ctypes.windll.user32
            r = wt.RECT()
            if u.SystemParametersInfoW(0x0030, 0, ctypes.byref(r), 0):  # SPI_GETWORKAREA
                return (r.left, r.top, r.right - r.left, r.bottom - r.top)
        except Exception:  # noqa: BLE001
            pass
        return (0, 0, 1280, 880)

    wa_x, wa_y, wa_w, wa_h = _workarea()
    w0 = min(1280, max(640, int(wa_w * 0.86)))
    h0 = min(880, max(480, int(wa_h * 0.86)))
    x0 = wa_x + max(0, (wa_w - w0) // 2)
    y0 = wa_y + max(0, (wa_h - h0) // 2)
    webview.create_window("%s v%s" % (APP_NAME, VERSION), win_url,
                          width=w0, height=h0, x=x0, y=y0, min_size=(980, 640),
                          frameless=True, easy_drag=False, js_api=api,
                          background_color="#F7F5EF")
    # 2026-11-17 用户：「为什么我本地的软件的图标还是一样的」——
    #   pywebview 的 winforms 后端只有在 start(icon=...) 传了图标时才用自定义图标，
    #   不传就取 sys.executable 的图标 → 从源码跑时窗口与任务栏一直是 python.exe 的蓝黄头像。
    #   这里显式指定 assets\lapluma.ico（源码时在仓根，exe 时在 _MEIPASS）。
    ico = paths.data_or_res("assets", "lapluma.ico")
    if os.path.isfile(ico):
        webview.start(func=_enable_resize, icon=ico)
    else:
        webview.start(func=_enable_resize)
    return 0


def main() -> int:
    global PORT
    argv = sys.argv[1:]
    # 输出重定向到文件（或 double-click 的控制台）时行缓冲更靠谱：不然启动提示一个字都看不到
    _safe_stdio()
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:  # noqa: BLE001
        pass
    # 冻结后（exe）先把两根与 engine\ tools\print\ api\ 挂上 sys.path；源码下是幂等的
    paths.bootstrap()
    # 2026-11-17 见文件上方「启动自保」：先摘遮蔽目录，再碰 webview（webview 后面才导入）
    for _d, _f in _strip_shadowed():
        _log_write("startup.log", "%s 摘掉遮蔽目录 %s（含 %s）"
                   % (time.strftime("%Y-%m-%d %H:%M:%S"), _d, _f))
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
            # 2026-11-21 用户：「启动羽毛笔.cmd 打开的为什么是那个网页版的 不是视窗版本的」——
            #   pythonw 没有控制台，这句 print 等于没写，出了事只能靠猜。落盘一份带堆栈的。
            import traceback as _tb
            _log_write("startup.log", "%s 窗口开不了，改用浏览器：%r\n%s"
                       % (time.strftime("%Y-%m-%d %H:%M:%S"), e, _tb.format_exc()))
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
        # 2026-11-17 别人机器上只有一张截图，没法查；全量记录落盘，弹窗里给路径。
        _logp = _log_write(
            time.strftime("startup-%Y%m%d-%H%M%S.log"),
            "LaPluma v%s\n启动时间 %s\nexe %s\ncwd %s\nsys.path %r\n\n%s"
            % (VERSION, time.strftime("%Y-%m-%d %H:%M:%S"), sys.executable,
               os.getcwd(), sys.path, msg))
        try:
            sys.stderr.write(msg)
        except Exception:  # noqa: BLE001
            pass
        try:
            import tkinter as _tk
            from tkinter import messagebox as _mb
            _r = _tk.Tk()
            _r.withdraw()
            _tail = msg[-1200:]
            if _logp:
                _tail += "\n\n完整记录已写到：\n" + _logp
            else:
                _tail += "\n\n（日志没写进去，请把这段截图发我）"
            _mb.showerror("羽毛笔 La Pluma · 启动失败", _tail)
            _r.destroy()
        except Exception:  # noqa: BLE001
            pass
        sys.exit(1)
