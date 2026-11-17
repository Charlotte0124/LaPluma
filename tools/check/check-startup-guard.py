# -*- coding: utf-8 -*-
"""判据：启动自保（2026-11-17 「别人机器上双击打不开」之后立的）

    python tools\\check\\check-startup-guard.py

查两件事：
  1 外来目录里出现与包内模块同名的 .py（现场就是 %TEMP%\\clr.py）时，
    server._strip_shadowed() 能把它摘掉；包内资源、site-packages、无关目录不误伤。
  2 启动失败的记录 server._log_write() 真能落盘（写完回查文件在不在、有没有内容）。

全部造坏都在临时目录里做，不动真实课程数据、不动 %TEMP% 里的真实文件。

退出码：0 全绿，1 有红，2 没查成（导入失败等）。
"""
from __future__ import annotations

import io
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
TMP_ROOT = tempfile.mkdtemp(prefix="pluma-guard-")
os.environ["PLUMA_HOME"] = os.path.join(TMP_ROOT, "home")

sys.path.insert(0, os.path.join(ROOT, "ui"))
try:
    import server as srv  # noqa: E402
except Exception as e:  # noqa: BLE001
    print("没查成：导入 ui\\server.py 失败：%r" % (e,))
    raise SystemExit(2)

RESULTS = []


def check(name, fn):
    try:
        ok, detail = fn()
    except Exception as e:  # noqa: BLE001
        ok, detail = False, "抛异常 %r" % (e,)
    RESULTS.append((name, ok, detail))
    print("%s  %s%s" % ("过  " if ok else "红  ", name, ("   —— " + detail) if detail else ""))


def mk(sub, filename, text="x = 1\n"):
    """在临时目录里造一个目录 + 一个文件，返回目录路径。"""
    d = os.path.join(TMP_ROOT, sub)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, filename), "w", encoding="utf-8") as f:
        f.write(text)
    return d


def with_path(entry):
    """临时把 entry 挂到 sys.path 最前面，返回还原函数。"""
    sys.path.insert(0, entry)

    def undo():
        while entry in sys.path:
            sys.path.remove(entry)
    return undo


# ---------- 1 遮蔽目录要摘掉 ----------
def t_temp_clr():
    d = mk("temp-clr", "clr.py")
    undo = with_path(d)
    try:
        hit = srv._strip_shadowed()
        removed = d not in sys.path
        names = [f for (p, f) in hit if os.path.abspath(p) == os.path.abspath(d)]
        return (removed and bool(names) and "clr.py" in names[0],
                "摘掉=%s 命中=%r" % (removed, names))
    finally:
        undo()


def t_exe_side_pythonnet():
    """exe 旁边那种目录：一次放两个同名文件，两个都要报出来。"""
    d = mk("exe-side", "pythonnet.py")
    mk("exe-side", "webview.py")
    undo = with_path(d)
    try:
        hit = srv._strip_shadowed()
        got = [f for (p, f) in hit if os.path.abspath(p) == os.path.abspath(d)]
        return (d not in sys.path and bool(got) and "pythonnet.py" in got[0]
                and "webview.py" in got[0], "命中=%r" % (got,))
    finally:
        undo()


def t_space_and_cjk():
    """目录名带空格与中文（Windows 用户目录常态）也要摘。"""
    d = mk("临时 目录\\带 空格", "clr.py")
    undo = with_path(d)
    try:
        srv._strip_shadowed()
        return d not in sys.path, "目录=%s" % os.path.basename(d)
    finally:
        undo()


# ---------- 2 不许误伤 ----------
def t_unrelated_py():
    """只有无关 .py 的目录不该动（比如用户自己的脚本目录）。"""
    d = mk("unrelated", "my_notes.py")
    undo = with_path(d)
    try:
        srv._strip_shadowed()
        return d in sys.path, "仍在 sys.path=%s" % (d in sys.path)
    finally:
        undo()


def t_site_packages():
    """site-packages 里真有 pythonnet 是正常的，不能摘。"""
    d = mk("venv\\Lib\\site-packages", "clr.py")
    undo = with_path(d)
    try:
        srv._strip_shadowed()
        return d in sys.path, "仍在 sys.path=%s" % (d in sys.path)
    finally:
        undo()


def t_res_root():
    """包内资源（RES_ROOT 及其子目录）一律不碰。"""
    import paths
    r = paths.RES_ROOT
    inside_root = srv._inside_res(r)
    inside_sub = srv._inside_res(os.path.join(r, "engine"))
    outside = srv._inside_res(TMP_ROOT)
    return (inside_root and inside_sub and not outside,
            "根=%s 子=%s 临时目录=%s" % (inside_root, inside_sub, outside))


def t_stale_entry():
    """sys.path 上留着已经不存在的路径（卸载后常见）不能抛。"""
    ghost = os.path.join(TMP_ROOT, "已经删掉的目录")
    undo = with_path(ghost)
    try:
        hit = srv._strip_shadowed()
        return all(os.path.abspath(p) != os.path.abspath(ghost) for (p, _f) in hit), "命中条数=%d" % len(hit)
    finally:
        undo()


# ---------- 3 stdout 兜底 ----------
def t_stdio_none():
    old = sys.stdout
    try:
        sys.stdout = None
        srv._safe_stdio()
        ok = hasattr(sys.stdout, "write") and not getattr(sys.stdout, "closed", True)
        sys.stdout.write("")          # 能写才算通
        return ok, "替换成 %r" % (sys.stdout,)
    finally:
        sys.stdout = old


def t_stdio_closed():
    old = sys.stdout
    try:
        buf = io.StringIO()
        buf.close()
        sys.stdout = buf
        srv._safe_stdio()
        return (not getattr(sys.stdout, "closed", True)) and hasattr(sys.stdout, "write"), \
            "替换成 %r" % (sys.stdout,)
    finally:
        sys.stdout = old


# ---------- 4 失败记录要落盘 ----------
def t_log_write():
    p = srv._log_write("startup-test.log", "写一行试试")
    if not p or not os.path.isfile(p):
        return False, "返回=%r 文件不存在" % (p,)
    size = os.path.getsize(p)
    with open(p, encoding="utf-8") as f:
        body = f.read()
    return (size > 0 and "写一行试试" in body, "路径=%s 大小=%d" % (p, size))


def t_log_area():
    """日志目录必须落在用户配置目录下（%USERPROFILE%\\.pluma\\logs），不是临时解包目录。"""
    p = srv.LOG_DIR_UI
    home = os.path.abspath(os.environ["PLUMA_HOME"])
    return (os.path.abspath(p).startswith(home), "LOG_DIR_UI=%s" % p)


def main() -> int:
    print("临时根：%s" % TMP_ROOT)
    print("--- 1 遮蔽目录要摘掉 ---")
    check("临时目录里的 clr.py 被摘掉", t_temp_clr)
    check("exe 旁边的 pythonnet.py / webview.py 被摘掉", t_exe_side_pythonnet)
    check("带空格与中文的目录也摘", t_space_and_cjk)
    print("--- 2 不许误伤 ---")
    check("无关 .py 的目录不动", t_unrelated_py)
    check("site-packages 里的 clr.py 不动", t_site_packages)
    check("包内资源 RES_ROOT 判定", t_res_root)
    check("不存在的 sys.path 条目不抛", t_stale_entry)
    print("--- 3 stdout 兜底 ---")
    check("sys.stdout=None 时换成可写哑流", t_stdio_none)
    check("sys.stdout 已关闭时换成可写哑流", t_stdio_closed)
    print("--- 4 失败记录落盘 ---")
    check("_log_write 真写出文件", t_log_write)
    check("日志目录在用户配置目录下", t_log_area)

    bad = [r for r in RESULTS if not r[1]]
    print("\n%d 项通过，%d 项红" % (len(RESULTS) - len(bad), len(bad)))
    if bad:
        for name, _ok, detail in bad:
            print("  红：%s%s" % (name, ("   —— " + detail) if detail else ""))
        return 1
    return 0


if __name__ == "__main__":
    try:
        rc = main()
    finally:
        shutil.rmtree(TMP_ROOT, ignore_errors=True)
    raise SystemExit(rc)
