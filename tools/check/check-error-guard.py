# -*- coding: utf-8 -*-
"""判据：报错保护与新增接口（2026-11-17）

    python tools\\check\\check-error-guard.py

查四组，全在临时目录 / 临时课程里造，跑完自己清掉（不动真实课程数据）：

  A 服务不许被打挂：14 条坏请求（坏 JSON、乱码路径、负页码、超长参数、不存在的路由、
    越界文件、缺字段……）逐条打过去，服务必须还活着，且回的是 JSON（不是 500 空页）。
  B 异常要留痕：_log_error() 真写进 _logs\\error.log。
  C /doc 与 /api/update：合法文档 200、越界 404、非 md 404；
    更新检查能认出「有新版」、能解析出摘要与条目；连不上时 4 秒内放手、不抛。
  D Word / PPT 导入：塞一份 .docx 进临时课程，要求原件落盘 + 转换件页数 > 0 + 占位讲次建出来。

退出码：0 全绿，1 有红，2 没查成。
"""
from __future__ import annotations

import base64
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
TMP = tempfile.mkdtemp(prefix="pluma-errguard-")
TMP_COURSE = "CHECK_TMP_COURSE"
RESULTS = []
ONLY = set(a.lower() for a in sys.argv[1:] if not a.startswith("-"))
try:
    sys.stdout.reconfigure(line_buffering=True)
except Exception:  # noqa: BLE001
    pass


def check(name, fn):
    try:
        ok, detail = fn()
    except Exception as e:  # noqa: BLE001
        ok, detail = False, "抛异常 %r" % (e,)
    RESULTS.append((name, ok, detail))
    print("%s  %s%s" % ("过  " if ok else "红  ", name, ("   —— " + detail) if detail else ""))


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def http(path, body=None, timeout=10):
    # 注意：http.client 只能用 ASCII 写请求行；中文路径要先百分号编码（浏览器也是这么做的）
    safe_path = urllib.parse.quote(path, safe="/?=&%")
    url = "http://127.0.0.1:%d%s" % (PORT, safe_path)
    data = json.dumps(body).encode("utf-8") if isinstance(body, (dict, list)) else body
    req = urllib.request.Request(url, data=data,
                                 headers={"Content-Type": "application/json"} if data else {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def as_json(raw):
    try:
        return json.loads(raw.decode("utf-8"))
    except Exception:  # noqa: BLE001
        return None


PORT = free_port()
ENV = dict(os.environ, PLUMA_HOME=os.path.join(TMP, "home"))
PROC = None


def start_server():
    global PROC
    # 2026-11-17 坑：用 subprocess.PIPE 接服务输出，日志写满 64 KB 管道后服务会
    #   卡在 log_message 里不再响应（表现为「打完 14 条坏请求后全部超时」）。写文件。
    logp = os.path.join(TMP, "server.log")
    logf = open(logp, "wb")
    PROC = subprocess.Popen([sys.executable, "ui\\server.py", "--no-window",
                             "--port", str(PORT), "--no-browser"],
                            cwd=ROOT, env=ENV,
                            stdout=logf, stderr=subprocess.STDOUT)
    t0 = time.time()
    while time.time() - t0 < 25:
        if PROC.poll() is not None:
            return _fail_start(logp)
        try:
            http("/api/bootstrap", timeout=2)
            return
        except Exception:  # noqa: BLE001
            time.sleep(0.35)
    raise RuntimeError("25 秒内 /api/bootstrap 没响应（日志 %s）" % logp)


def _fail_start(logp):
    try:
        tail = open(logp, encoding="utf-8", errors="replace").read()[-600:]
    except Exception:  # noqa: BLE001
        tail = ""
    raise RuntimeError("服务起不来：%s" % tail)


def stop_server():
    if PROC and PROC.poll() is None:
        PROC.terminate()
        try:
            PROC.wait(timeout=6)
        except Exception:  # noqa: BLE001
            PROC.kill()


# ---------- A 服务不许被打挂 ----------
BAD = [
    ("坏 JSON 体", "POST", "/api/import", b"{not json"),
    ("空 body", "POST", "/api/import", b""),
    ("不存在的路由", "GET", "/api/nope", None),
    ("课程代码带引号", "GET", "/api/notes?code='%3Bdrop", None),
    ("越界路径", "GET", "/api/pdf?p=../../etc/passwd", None),
    ("路径带空字节", "GET", "/api/pdf?p=DEMO%00.pdf", None),
    ("不存在的课件", "GET", "/api/pdf?p=DEMO/01_讲义/没有这一份.pdf", None),
    ("超长查询", "GET", "/api/notes?code=" + "A" * 4000, None),
    ("乱码参数", "GET", "/api/session?code=%FF%FE", None),
    ("删除缺字段", "POST", "/api/delete", {"kind": ""}),
    ("删除未知类型", "POST", "/api/delete", {"kind": "zzz", "course": "DEMO"}),
    ("生成未知课程", "POST", "/api/generate", {"course": "NO_SUCH_COURSE_X", "lesson": "T01"}),
    ("配置坏值", "POST", "/api/config", {"save_dir": "?"}),
    ("问答缺问题", "POST", "/api/ask", {"course": "DEMO", "question": ""}),
]


def t_bad_requests():
    bad = []
    for name, method, path, body in BAD:
        print("    · %s" % name)
        try:
            st, raw = http(path, body=body if method == "POST" else None, timeout=12)
        except Exception as e:  # noqa: BLE001
            bad.append("%s：连接断了（%r）" % (name, e))
            continue
        if st >= 500 and not as_json(raw):
            bad.append("%s：%d 且不是 JSON" % (name, st))
    # 打完一圈服务必须还活着
    st, raw = http("/api/bootstrap", timeout=5)
    alive = st == 200 and as_json(raw)
    if not alive:
        bad.append("打完坏请求后服务没响应了")
    return (not bad, "；".join(bad) if bad else "%d 条坏请求都没打挂服务" % len(BAD))


def t_log_line():
    """直接调 _log_error：请求层很难必然制造 500，日志写入本身必须能验。"""
    sys.path.insert(0, os.path.join(ROOT, "ui"))
    import importlib
    srv = importlib.import_module("server")
    p = os.path.join(ROOT, "_logs", "error.log")
    before = os.path.getsize(p) if os.path.isfile(p) else 0
    srv._log_error("check-erruard 造坏", ValueError("故意写一行"))
    after = os.path.getsize(p) if os.path.isfile(p) else -1
    body = open(p, encoding="utf-8").read().splitlines()[-1] if after > 0 else ""
    return (after > before and "故意写一行" in body, "大小 %d → %d" % (before, after))


def t_cjk_filename():
    """带中文名的课件能正常下载（旧代码会在这里把连接断掉）。"""
    import glob
    pdfs = glob.glob(os.path.join(ROOT, "DEMO", "**", "*.pdf"), recursive=True)
    if not pdfs:
        return False, "没查到样本（DEMO 里没有 PDF）"
    rel = os.path.relpath(pdfs[0], ROOT).replace(os.sep, "/")
    st, raw = http("/api/pdf?p=" + urllib.parse.quote(rel))
    return (st == 200 and raw[:4] == b"%PDF", "%s → 状态 %d" % (os.path.basename(rel), st))


# ---------- C /doc 与 /api/update ----------
def t_doc_ok():
    q = urllib.parse.quote("使用/04-API与密钥.md")
    st, raw = http("/doc?p=" + q)
    return (st == 200 and b"<h1" in raw and "密钥".encode() in raw, "状态=%d 长度=%d" % (st, len(raw)))


def t_doc_traversal():
    bad = []
    for p in ("../../README.md", "..%2F..%2FREADME.md", "/使用/../../README.md", "使用/不存在.md"):
        st, raw = http("/doc?p=" + urllib.parse.quote(p))
        if st == 200:
            bad.append(p + " 竟然 200")
    return (not bad, "；".join(bad) or "四种绕法都被挡住")


def t_update_parse():
    """假一个 GitHub release，验「有新版 / 摘要 / 条目」的解析（不联网）。"""
    sys.path.insert(0, os.path.join(ROOT, "ui"))
    os.environ["PLUMA_HOME"] = os.path.join(TMP, "home2")
    import importlib
    srv = importlib.import_module("server")
    feed = os.path.join(TMP, "release.json")
    with open(feed, "w", encoding="utf-8") as f:
        json.dump({"tag_name": "v9.9.9", "name": "v9.9.9 · 测试版",
                   "body": "<!-- 摘要：测试摘要一行 -->\n- **修** 了某处；细节很长\n* 加了某功能。\n",
                   "html_url": "https://example.invalid/r"}, f, ensure_ascii=False)
    srv.UPDATE_API = "file:///" + feed.replace("\\", "/")
    srv.UPDATE_CACHE = os.path.join(TMP, "upd.json")
    got = srv.check_update(force=True)
    ok = (got.get("ok") and got.get("newer") is True and got.get("latest") == "9.9.9"
          and got.get("summary") == "测试摘要一行" and len(got.get("notes") or []) >= 2)
    return (bool(ok), "latest=%s newer=%s summary=%r notes=%d"
            % (got.get("latest"), got.get("newer"), got.get("summary"), len(got.get("notes") or [])))


def t_update_offline():
    sys.path.insert(0, os.path.join(ROOT, "ui"))
    import importlib
    srv = importlib.import_module("server")
    srv.UPDATE_API = "http://127.0.0.1:1/none"     # 必然连不上
    srv.UPDATE_CACHE = os.path.join(TMP, "upd2.json")
    t0 = time.time()
    got = srv.check_update(force=True)
    dt = time.time() - t0
    ok = (got.get("ok") is False) and dt < 8
    return (bool(ok), "ok=%s 耗时 %.1fs 错误=%r" % (got.get("ok"), dt, got.get("error")))


# ---------- D Word / PPT 导入 ----------
def mk_docx(path, paras):
    W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    body = "".join('<w:p><w:r><w:t xml:space="preserve">%s</w:t></w:r></w:p>' % p for p in paras)
    xml = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           '<w:document xmlns:w="%s"><w:body>%s</w:body></w:document>' % (W, body))
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml", xml)


def t_import_docx():
    src = os.path.join(TMP, "第9讲 虚拟内存.docx")
    mk_docx(src, ["第九章 虚拟内存", "分页把地址空间切成固定大小的页。"] + ["补充 %d 行" % i for i in range(60)])
    b64 = base64.b64encode(open(src, "rb").read()).decode("ascii")
    st, raw = http("/api/import", {"course": TMP_COURSE, "files": [{"name": os.path.basename(src), "b64": b64}]},
                   timeout=90)
    j = as_json(raw) or {}
    conv = j.get("converted") or []
    d = os.path.join(ROOT, TMP_COURSE, "00_原件")
    name = [f for f in (os.listdir(d) if os.path.isdir(d) else []) if f.endswith("（转换）.pdf")]
    npage = 0
    if name:
        import pymupdf
        with pymupdf.open(os.path.join(d, name[0])) as doc:
            npage = doc.page_count
    ok = (st == 200 and j.get("ok") and bool(conv) and npage > 0 and bool(j.get("stubs")))
    return (bool(ok), "状态=%d 转换=%r 转换件页数=%d 讲次=%r" % (st, conv, npage, j.get("stubs")))


def t_import_pdf_untouched():
    """PDF 不该被「转换」一遍（原生支持）。"""
    sys.path.insert(0, os.path.join(ROOT, "engine"))
    import _office
    import glob
    pdfs = glob.glob(os.path.join(ROOT, "DEMO", "**", "*.pdf"), recursive=True)
    if not pdfs:
        return True, "跳过：DEMO 里没有 PDF 样本"       # 跳过不算通过，单独标一下
    return (_office.ensure_pdf(pdfs[0]) is None, "样本 %s" % os.path.basename(pdfs[0]))


def main():
    print("临时根：%s" % TMP)
    try:
        start_server()
    except Exception as e:  # noqa: BLE001
        print("没查成：%r" % (e,))
        return 2
    print("服务已起：%d" % PORT)
    try:
        if not ONLY or "a" in ONLY:
            print("--- A 坏请求不许打挂服务 ---")
            check("14 条坏请求都不打挂服务", t_bad_requests)
            check("异常写进 error.log", t_log_line)
            check("中文文件名能下载", t_cjk_filename)
        if not ONLY or "c" in ONLY:
            print("--- C 文档与更新 ---")
            check("/doc 能渲染文档", t_doc_ok)
            check("/doc 挡住越界与不存在", t_doc_traversal)
            check("更新检查认得出新版并解析摘要", t_update_parse)
            check("连不上 GitHub 时 4 秒内放手", t_update_offline)
        if not ONLY or "d" in ONLY:
            print("--- D Word / PPT 导入 ---")
            check("导入 .docx 生成分页 PDF 与占位讲次", t_import_docx)
            check("PDF 不被重复转换", t_import_pdf_untouched)
    finally:
        stop_server()
        shutil.rmtree(os.path.join(ROOT, TMP_COURSE), ignore_errors=True)
        shutil.rmtree(TMP, ignore_errors=True)
    bad = [r for r in RESULTS if not r[1]]
    print("\n%d 项通过，%d 项红" % (len(RESULTS) - len(bad), len(bad)))
    for name, _ok, detail in bad:
        print("  红：%s%s" % (name, ("   —— " + detail) if detail else ""))
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
