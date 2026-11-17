# -*- coding: utf-8 -*-
"""把已有讲义源补上「图 N · 」编号（一次性迁移，2026-11-17）。

    python tools\\build\\renumber-sources.py            # 只报会改几份
    python tools\\build\\renumber-sources.py --write    # 真改

为什么要有：图注自动编号是 2026-11-17 才加进渲染链的（`engine\\_build_讲义.py` 的
`number_figures()`），在那之前生成的源里图注没有编号。重新生成当然会有编号，但
真实课程的 `_lessons\\` 不一定还在本机（CS340 就是这种情况：源在、讲次数据不在），
所以给已有源做一次原地补号，判据才不会指着一堆历史产物红。

只补编号，不动别的：已有「图 N」开头的 figcaption 原样保留；合订本与回收站跳过
（合订本按讲重置编号，重排会打乱正文引用）。
"""
from __future__ import annotations

import glob
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "engine"))

FIGCAP_RE = re.compile(r'(<figcaption[^>]*>)(\s*)(.*?)(</figcaption>)', re.S)


def number(html: str) -> str:
    state = {"n": 0}

    def fig(m):
        text = m.group(3).strip()
        if not text or re.match(r"^图\s*\d+", text):
            return m.group(0)
        state["n"] += 1
        return "%s%s图 %d · %s%s" % (m.group(1), m.group(2), state["n"], text, m.group(4))

    return FIGCAP_RE.sub(fig, html)


def targets() -> list:
    out = []
    for pat in (os.path.join(ROOT, "*", "06_笔记", "*_源.html"),
                os.path.join(ROOT, "**", "06_笔记", "*_源.html")):
        out.extend(glob.glob(pat, recursive=True))
    keep = []
    for p in sorted(set(out)):
        rel = os.path.relpath(p, ROOT)
        if "_trash" in rel or "_归档" in rel or "合订本" in rel:
            continue
        keep.append(p)
    return keep


def main(argv: list) -> int:
    for s in (sys.stdout, sys.stderr):
        if hasattr(s, "reconfigure"):
            s.reconfigure(encoding="utf-8")
    write = "--write" in argv
    changed = 0
    for p in targets():
        old = open(p, encoding="utf-8").read()
        new = number(old)
        if new == old:
            continue
        n = len(FIGCAP_RE.findall(new)) - len(FIGCAP_RE.findall(old)) if False else None
        changed += 1
        rel = os.path.relpath(p, ROOT)
        added = sum(1 for m in FIGCAP_RE.finditer(new) if re.match(r"^\s*图\s*\d+", m.group(3).strip())) \
            - sum(1 for m in FIGCAP_RE.finditer(old) if re.match(r"^\s*图\s*\d+", m.group(3).strip()))
        print(("已改  " if write else "待改  ") + rel + "（补 %d 处图号）" % added)
        if write:
            with open(p, "w", encoding="utf-8", newline="\n") as f:
                f.write(new)
    print(("共改 %d 份" if write else "共 %d 份待改（加 --write 才写）") % changed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
