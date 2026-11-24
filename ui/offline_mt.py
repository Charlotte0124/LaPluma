r"""离线语言包：opus-mt 中英双向，用 CTranslate2 在本机推理。

为什么不用 argostranslate：它 1.11 的依赖里有 stanza + spacy（会拖 torch），
而羽毛笔是「文件夹 + Python」分发，装一个编译链比功能本身还重。这里只依赖
ctranslate2（win cp312 wheel 22 MB）与 sentencepiece（1.6 MB），模型直接用
Argos 发布的 .argosmodel（本质是 zip，里面就是 CTranslate2 模型）。

2026-11-24 实测（本机 CPU）：
  - 包体 71 MB（中→英）+ 67.5 MB（英→中），解包后 model.bin 各 78.88 MB；
  - 英→中 449 字 0.64 s；中→英 395 字 1.24 s；
  - 质量只够「兜底」：术语会错（Biomolecules→生物多分子），不要当主线。

坑（实测）：sentencepiece 的 C++ 层用窄字符路径打开模型，模型放在中文路径下
会报 NOT_FOUND。所以模型目录必须落在 ASCII 路径（%USERPROFILE%\.pluma\models
一般可以；本机 H:\文件\… 不行）。
"""
from __future__ import annotations

import json
import os
import re
import shutil
import threading
import time
import urllib.request
import zipfile

USER_DIR = os.environ.get("PLUMA_HOME") or os.path.join(os.path.expanduser("~"), ".pluma")
MODELS_DIR = os.path.join(USER_DIR, "models")

# 目录名 = 目标/源 的语言对；下载源是 Argos 官方发布页（固定版本 1.9）
PACKS = {
    "en_zh": {
        "name": "英 → 中",
        "dir": "en_zh",
        "zip": "translate-en_zh-1_9.argosmodel",
        "url": "https://argos-net.com/v1/translate-en_zh-1_9.argosmodel",
        "bytes": 70743021,
    },
    "zh_en": {
        "name": "中 → 英",
        "dir": "zh_en",
        "zip": "translate-zh_en-1_9.argosmodel",
        "url": "https://argos-net.com/v1/translate-zh_en-1_9.argosmodel",
        "bytes": 74481402,
    },
}

_lock = threading.Lock()
_cache: dict[str, tuple] = {}          # lang -> (sp, translator)
_dl = {"active": False, "done": 0, "total": 0, "lang": "", "error": "", "started": 0.0,
       "phase": ""}

# 句末切分：中文按句号/问号/叹号/分号，英文按句点 + 空白。
_SENT_RE = re.compile(r"(?<=[。！？!?；;])\s*|(?<=[.])\s+")


def deps_ok() -> tuple[bool, str]:
    try:
        import ctranslate2  # noqa: F401
        import sentencepiece  # noqa: F401
        return True, ""
    except Exception as e:  # noqa: BLE001
        return False, "%s: %s" % (type(e).__name__, e)


def pack_dir(lang: str) -> str:
    return os.path.join(MODELS_DIR, PACKS[lang]["dir"])


def pack_installed(lang: str) -> bool:
    d = pack_dir(lang)
    return os.path.isfile(os.path.join(d, "model", "model.bin")) and os.path.isfile(
        os.path.join(d, "sentencepiece.model"))


def size_on_disk(lang: str) -> int:
    d = pack_dir(lang)
    if not os.path.isdir(d):
        return 0
    n = 0
    for root, _dirs, files in os.walk(d):
        for f in files:
            try:
                n += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return n


def status() -> dict:
    """给界面用的状态：两包各自是否已装、占多少、总下载量、当前下载进度。"""
    ok, why = deps_ok()
    with _lock:
        dl = dict(_dl)
    packs = {}
    for lang, meta in PACKS.items():
        packs[lang] = {
            "name": meta["name"],
            "installed": pack_installed(lang),
            "bytes": size_on_disk(lang) or meta["bytes"],
            "remote_bytes": meta["bytes"],
            "url": meta["url"],
        }
    installed = all(p["installed"] for p in packs.values())
    return {
        "deps_ok": ok,
        "deps_error": why,
        "dir": MODELS_DIR,
        "installed": installed,
        "bytes": sum(p["bytes"] for p in packs.values()) if installed else sum(m["bytes"] for m in PACKS.values()),
        "total_bytes": sum(m["bytes"] for m in PACKS.values()),
        "packs": packs,
        "download": dl,
    }


def _extract_into(zip_path: str, lang: str) -> None:
    """解包 .argosmodel，并把嵌套那一层拍平到 models/<lang>/ 下。"""
    tmp = pack_dir(lang) + ".tmp"
    if os.path.isdir(tmp):
        shutil.rmtree(tmp)
    os.makedirs(tmp, exist_ok=True)
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(tmp)
    # 包里是 <zip 名>/model/model.bin；找含 model/model.bin 的那一层
    root = None
    for dirpath, _dirs, files in os.walk(tmp):
        if "model.bin" in files and os.path.basename(dirpath) == "model":
            root = os.path.dirname(dirpath)
            break
    if not root:
        shutil.rmtree(tmp, ignore_errors=True)
        raise RuntimeError("包里没找到 model/model.bin")
    dst = pack_dir(lang)
    if os.path.isdir(dst):
        shutil.rmtree(dst)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.move(root, dst)
    shutil.rmtree(tmp, ignore_errors=True)


def _fetch(url: str, dst: str, total: int) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "LaPluma/offline-mt"})
    with urllib.request.urlopen(req, timeout=60) as r, open(dst, "wb") as f:
        done = 0
        while True:
            chunk = r.read(1 << 16)
            if not chunk:
                break
            f.write(chunk)
            done += len(chunk)
            with _lock:
                _dl["done"] = done
                _dl["total"] = total or int(r.headers.get("Content-Length") or 0)


def _download_worker(langs: list[str]) -> None:
    try:
        ok, why = ensure_deps()
        if not ok:
            raise RuntimeError(why)
        os.makedirs(MODELS_DIR, exist_ok=True)
        for lang in langs:
            meta = PACKS[lang]
            with _lock:
                _dl.update({"lang": lang, "done": 0, "total": meta["bytes"], "phase": "download"})
            zpath = os.path.join(MODELS_DIR, meta["zip"])
            if not (os.path.isfile(zpath) and os.path.getsize(zpath) == meta["bytes"]):
                _fetch(meta["url"], zpath, meta["bytes"])
            _extract_into(zpath, lang)
            try:
                os.remove(zpath)
            except OSError:
                pass
        with _lock:
            _dl.update({"active": False, "done": _dl["total"], "error": ""})
    except Exception as e:  # noqa: BLE001
        with _lock:
            _dl.update({"active": False, "error": "%s: %s" % (type(e).__name__, e)})


def ensure_deps() -> tuple[bool, str]:
    """首次下载时把 ctranslate2 / sentencepiece 装上（只装这两个，不碰 argostranslate）。"""
    ok, why = deps_ok()
    if ok:
        return True, ""
    import subprocess
    import sys
    with _lock:
        _dl["phase"] = "deps"
    cmd = [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "--quiet",
           "-i", "https://pypi.tuna.tsinghua.edu.cn/simple", "ctranslate2", "sentencepiece"]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    except Exception as e:  # noqa: BLE001
        return False, "装依赖失败：%s: %s" % (type(e).__name__, e)
    ok, why = deps_ok()
    if not ok:
        tail = ((p.stderr or p.stdout or "").strip().splitlines() or [""])[-1]
        return False, "装依赖失败（pip 返回 %s）：%s" % (p.returncode, tail or why)
    return True, ""


def start_download(langs: list[str] | None = None) -> dict:
    langs = [x for x in (langs or list(PACKS)) if x in PACKS]
    if not langs:
        return {"ok": False, "error": "没有可下载的语言包"}
    with _lock:
        if _dl["active"]:
            return {"ok": False, "error": "已经在下载了", "download": dict(_dl)}
        _dl.update({"active": True, "done": 0, "total": sum(PACKS[x]["bytes"] for x in langs),
                    "lang": langs[0], "error": "", "started": time.time(), "phase": "download"})
    t = threading.Thread(target=_download_worker, args=(langs,), daemon=True)
    t.start()
    return {"ok": True, "langs": langs}


def remove_packs() -> dict:
    """只删自己装的那两个包（以及下载残留），不动 models 目录里的其它东西。"""
    for lang in PACKS:
        d = pack_dir(lang)
        if os.path.isdir(d):
            shutil.rmtree(d, ignore_errors=True)
        z = os.path.join(MODELS_DIR, PACKS[lang]["zip"])
        if os.path.isfile(z):
            try:
                os.remove(z)
            except OSError:
                pass
    with _lock:
        _cache.clear()
    return {"ok": True}


def _load(lang: str):
    key = lang
    with _lock:
        got = _cache.get(key)
    if got:
        return got
    import ctranslate2
    import sentencepiece as spm
    d = pack_dir(lang)
    sp = spm.SentencePieceProcessor(model_file=os.path.join(d, "sentencepiece.model"))
    tr = ctranslate2.Translator(os.path.join(d, "model"), device="cpu", compute_type="int8")
    with _lock:
        _cache[key] = (sp, tr)
    return sp, tr


def _chunks(text: str, max_len: int = 400) -> list[str]:
    out, cur = [], ""
    for s in _SENT_RE.split(text):
        s = (s or "").strip()
        if not s:
            continue
        if cur and len(cur) + len(s) > max_len:
            out.append(cur)
            cur = s
        else:
            cur = (cur + " " + s).strip()
    if cur:
        out.append(cur)
    return out


def translate(text: str, to: str) -> dict:
    """to='zh' 用英→中包；to='en' 用中→英包。返回 {text, engine, seconds, chars}。"""
    text = (text or "").strip()
    if not text:
        raise ValueError("空文本")
    lang = "en_zh" if to == "zh" else "zh_en"
    if not pack_installed(lang):
        raise RuntimeError("没有装离线语言包（%s）" % PACKS[lang]["name"])
    ok, why = deps_ok()
    if not ok:
        raise RuntimeError("缺离线推理依赖：%s" % why)
    sp, tr = _load(lang)
    t0 = time.time()
    pieces = []
    for chunk in _chunks(text):
        toks = sp.encode(chunk, out_type=str)
        res = tr.translate_batch([toks], beam_size=2, max_decoding_length=256)
        pieces.append(sp.decode(res[0].hypotheses[0]))
    out = " ".join(pieces).replace("▁", " ").strip()
    if not out:
        raise RuntimeError("离线模型没有给出译文")
    return {"text": out, "engine": "offline", "chars": len(text),
            "seconds": round(time.time() - t0, 2)}
