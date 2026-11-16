# -*- coding: utf-8 -*-
"""从 CHANGELOG 生成 README 的「最近更新」表（只改标记之间的内容）。

    python tools\\sync-readme.py            # 写回 README
    python tools\\sync-readme.py --check    # 只比对，不一致退出 1

为什么要有它：主页上的版本表靠人记得改，迟早会旧。让它生成，`--check` 放进推送前检查。
"""
from __future__ import annotations

import io
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import paths  # noqa: E402  路径双根：CHANGELOG / README 属于随程序发布的东西（资源根）
ROOT = paths.RES_ROOT
CHANGELOG = os.path.join(ROOT, "CHANGELOG.md")
README = os.path.join(ROOT, "README.md")
BEGIN = "<!-- 最近更新:begin（由 tools/sync-readme.py 生成，别手改） -->"
END = "<!-- 最近更新:end -->"
LIMIT = 5


def parse(path: str) -> list[tuple[str, str, str]]:
    rows = []
    cur = None
    for line in io.open(path, encoding="utf-8"):
        m = re.match(r"^##\s+(v[\d.]+)\s*·\s*(\d{4}-\d{2}-\d{2})\s*$", line.strip())
        if m:
            cur = [m.group(1), m.group(2), []]
            rows.append(cur)
            continue
        if cur and line.strip().startswith("- "):
            cur[2].append(line.strip()[2:].strip())
    return [(v, d, "；".join(items[:2]) + ("…" if len(items) > 2 else "")) for v, d, items in rows]


def render(rows) -> str:
    head = "| 版本 | 日期 | 这一版做了什么 |\n|:--|:--|:--|"
    body = "\n".join("| **%s** | %s | %s |" % (v, d[5:], t) for v, d, t in rows[:LIMIT])
    return BEGIN + "\n" + head + "\n" + body + "\n" + END


def main(argv: list[str]) -> int:
    rows = parse(CHANGELOG)
    if not rows:
        print("CHANGELOG 里没有符合 `## vX.Y.Z · YYYY-MM-DD` 的条目")
        return 2
    block = render(rows)
    src = io.open(README, encoding="utf-8").read()
    if BEGIN not in src or END not in src:
        print("README 里缺标记：%s / %s" % (BEGIN, END))
        return 2
    # 2026-11-17 修：原来直接拿 block 当替换串，block 里的反斜杠（如 tools\print\pdfjs）
    #   会被当成转义序列，re 直接报 bad escape \p。用函数替换就不做转义解析了。
    new = re.sub(re.escape(BEGIN) + r".*?" + re.escape(END), lambda _m: block, src, flags=re.S)
    if "--check" in argv:
        if new != src:
            print("最近更新表与 CHANGELOG 不一致：跑 python tools\\sync-readme.py")
            return 1
        print("最近更新表一致（%d 版候选，取前 %d）" % (len(rows), LIMIT))
        return 0
    io.open(README, "w", encoding="utf-8").write(new)
    print("已写回 README（%d 版候选，取前 %d）" % (len(rows), LIMIT))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
