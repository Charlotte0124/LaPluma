# -*- coding: utf-8 -*-
r"""check-repo-clean.py — 产品仓只放能跑的代码（2026-11-22 用户定）

为什么有这条：用户原话「全部项目是不要有外露的后台资源维护的（这些归纳 PRTS 管理）只可以保留
源代码在仓库里面」。规矩正本在 PRTS 的 CONVENTIONS.md §63 与 registry/repo-hygiene.json
（本仓只留指针，不复制正文）。这条判据只管本仓能自己判的两件：

  1 进仓文件必须落在「代码 / 启动脚本 / 说明 / 运行必需资源 / 示例课程」这几类里；
    一次性脚本（_tmp / _probe / dbg-）、真课件、_trash 一旦进仓就红。
  2 courses.json 只许有 DEMO：真实课程名不进公开仓。

用法：python tools/check/check-repo-clean.py
退出码：0 绿；1 红
"""
from __future__ import annotations

import fnmatch
import json
import os
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 能进仓的东西（与 PRTS 白名单同口径，只列本仓会用到的）
ALLOW = [
    "*.py", "*.ps1", "*.cmd", "*.bat", "*.sh", "*.spec", "*.toml", "*.cfg", "*.ini",
    "*.txt", "*.json", "*.yml", "*.yaml", "*.md", "*.html", "*.js", "*.css", "*.mjs",
    "*.gitignore", "*.gitattributes", "*.ico", "*.png", "*.svg", "*.pdf", "*.woff2",
    "LICENSE", "NOTICE", "VERSION", "CHANGELOG.md", "README.md", "AGENTS.md",
    # 运行必需：pdf.js / KaTeX 字体 / 示例课程 / 文档与截图 / 提交钩子
    "tools/print/pdfjs/*", "tools/print/katex/fonts/*", "DEMO/*", "docs/*",
    "assets/*.ico", ".githooks/*", "*/.gitkeep",
]
# 一次性脚本与真课件：进仓就红（目录名兜底拦真课程数据）
# 注：tools/check/shot-*.py 是「抓真窗口截图」的脚本，属代码，不在这条拦的范围里。
DENY_HINT = ["_tmp", "_probe", "dbg-", "seq-", ".png.py", "/00_原件/", "/_trash/"]


def tracked():
    r = subprocess.run(["git", "-c", "core.quotepath=false", "-C", ROOT, "ls-files"],
                       capture_output=True, text=True, encoding="utf-8")
    if r.returncode != 0:
        return None
    return [x for x in (r.stdout or "").splitlines() if x.strip()]


def matches(path, pats):
    for p in pats:
        if fnmatch.fnmatch(path, p) or fnmatch.fnmatch(path, p.replace("*/", "")):
            return True
    return False


def main() -> int:
    files = tracked()
    if files is None:
        print("[没查] git 不可用或这不是仓库")
        return 0
    red = []
    for f in files:
        if any(h in f for h in DENY_HINT):
            red.append("一次性脚本/真课件混进仓：%s" % f)
        elif fnmatch.fnmatch(f, "tools/check/shot-*.py"):
            red.append("截图脚本算后台维护，归 PRTS（projects/课程/ops/lapluma/截图脚本-20261122）：%s" % f)
        elif f == "courses.local.json":
            red.append("courses.local.json 是本机真实课程名，绝不能进仓：%s" % f)
        elif not matches(f, ALLOW):
            red.append("不在「只放代码」白名单里：%s" % f)
    try:
        cfg = json.load(open(os.path.join(ROOT, "courses.json"), encoding="utf-8"))
        keys = sorted(k for k in cfg if not k.startswith("_"))
        if keys != ["DEMO"]:
            red.append("courses.json 只有 DEMO 才允许进公开仓，实际是 %r" % (keys,))
    except Exception as e:  # noqa: BLE001
        red.append("courses.json 读不了：%r" % (e,))
    for r in red[:10]:
        print("[红] " + r)
    print("结论：%d 个进仓文件 · %s" % (len(files), "红 %d" % len(red) if red else "全在代码白名单内"))
    return 1 if red else 0


if __name__ == "__main__":
    raise SystemExit(main())
