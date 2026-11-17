# -*- coding: utf-8 -*-
"""打资源包 LaPluma-res.zip（2026-11-17 用户：「以后更新是要分资源包和 exe 本体了」）。

    python tools\\build\\make-res.py                 # 打到 dist\\LaPluma-res.zip
    python tools\\build\\make-res.py -o out\\x.zip

里面放**不常变**的东西：docs\\（使用文档）、DEMO\\（示例课程）、assets\\（图标）、courses.json。
解压到程序所在目录即可生效——`docs` 与 `assets` 的读取已改成「数据根优先」
（`ui\\server.py` 的 `DOC_ROOT` / 图标），`DEMO` 与 `courses.json` 本来就走 `data_or_res`。

为什么值得单独发：exe 一百多 MB，绝大部分是这些资源；只改文档或示例时，
让用户下几 MB 的资源包比重下本体合理。exe 本体照旧自带一份，没下资源包也能用。
"""
from __future__ import annotations

import argparse
import os
import sys
import time
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))

# 相对程序根的路径（解压即落位）
INCLUDE_DIRS = ["docs", "DEMO", "assets"]
INCLUDE_FILES = ["courses.json"]
# 这些不进包：回收站、日志、缓存、打包中间物、本机笔记与讲次数据（属于用户，不该被覆盖）
EXCLUDE_PARTS = {"_trash", "_logs", ".build", "__pycache__", ".git", "01_讲义", "06_笔记",
                 "_lessons", "out"}


def iter_files(base: str) -> list:
    out = []
    for i, d in enumerate(INCLUDE_DIRS):
        top = os.path.join(ROOT, d)
        if not os.path.isdir(top):
            continue
        for cur, dirs, files in os.walk(top):
            dirs[:] = [x for x in dirs if x not in EXCLUDE_PARTS]
            for f in files:
                p = os.path.join(cur, f)
                out.append(p)
    for f in INCLUDE_FILES:
        p = os.path.join(ROOT, f)
        if os.path.isfile(p):
            out.append(p)
    return sorted(set(out))


def main(argv: list | None = None) -> int:
    for s in (sys.stdout, sys.stderr):
        if hasattr(s, "reconfigure"):
            s.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="打资源包（docs / DEMO / assets / courses.json）")
    ap.add_argument("-o", "--out", default=os.path.join(ROOT, "dist", "LaPluma-res.zip"))
    a = ap.parse_args(argv)

    files = iter_files(ROOT)
    if not files:
        print("没有可打包的文件，先确认仓结构", file=sys.stderr)
        return 2
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with zipfile.ZipFile(a.out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for p in files:
            rel = os.path.relpath(p, ROOT).replace(os.sep, "/")
            z.write(p, rel)
    size = os.path.getsize(a.out)
    # 回查：包能打开、条目数与文件数一致
    with zipfile.ZipFile(a.out) as z:
        n = len(z.namelist())
        bad = z.testzip()
    if bad or n != len(files):
        print("打包结果不对：条目 %d / 文件 %d · 坏条目 %s" % (n, len(files), bad), file=sys.stderr)
        return 3
    print("已写 %s（%.1f MB · %d 个文件）" % (a.out, size / 1048576, n))
    print("  目录：%s ／ 单文件：%s" % ("、".join(INCLUDE_DIRS), "、".join(INCLUDE_FILES)))
    print("  生成时间：%s" % time.strftime("%Y-%m-%d %H:%M:%S"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
