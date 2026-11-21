# -*- coding: utf-8 -*-
r"""内联脚本语法检查：把 ui/index.html 里每段 <script> 抽出来过一遍 node --check。

为什么有这一条：界面是单文件，JS 全内联；一个引号或反引号写错，页面起来就是白屏或半个界面，
而「服务器返回 200、接口全绿」看着还是好的。2026-11-22 改文字层与拖动时就差点把反引号
留在模板串里（node 一跑就报，浏览器里只会静默不执行）。

用法：
    python tools/check/check-inline-js.py
退出码：0 全过；1 有语法错；2 没查（本机没有 node）
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
IDX = os.path.join(ROOT, "ui", "index.html")


def main() -> int:
    try:
        subprocess.run(["node", "--version"], capture_output=True, check=True)
    except Exception:  # noqa: BLE001
        print("[未验] 本机没有 node，没法查内联脚本")
        return 2
    with open(IDX, encoding="utf-8") as f:
        html = f.read()
    blocks = re.findall(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", html, re.S)
    if not blocks:
        print("[红] ui/index.html 里没抽到任何内联 <script>（抽法过时了？）")
        return 1
    bad = 0
    for i, js in enumerate(blocks):
        tmp = tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8")
        tmp.write(js)
        tmp.close()
        try:
            r = subprocess.run(["node", "--check", tmp.name], capture_output=True, text=True,
                               encoding="utf-8", errors="replace")
            if r.returncode != 0:
                bad += 1
                print("[红] 第 %d 段内联脚本语法错：\n%s" % (i + 1, (r.stderr or "").strip()[:600]))
            else:
                print("[绿] 第 %d 段内联脚本（%d 字符）node --check 通过" % (i + 1, len(js)))
        finally:
            os.unlink(tmp.name)
    print("结论：%d 段 · %s" % (len(blocks), "有 %d 段语法错" % bad if bad else "全部通过"))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
