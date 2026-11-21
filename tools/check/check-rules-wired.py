# -*- coding: utf-8 -*-
r"""规矩与判据接线检查（2026-11-22 用户定）。

为什么有这条：用户原话「每次改动结束之后都要保存最新的规矩，不然永远都会发生老问题，
并且制作钩子防止这事情发生」。所以规矩写在 AGENTS.md、判据写在 tools/check/，两边必须对上：
  · tools/check 里有判据，AGENTS.md 里没提 → 红（写了没人跑，等于没写）
  · AGENTS.md 提到 check-xxx.py，文件不存在 → 红（规矩指向空气）
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CHECKS = os.path.join(ROOT, "tools", "check")
AGENTS = os.path.join(ROOT, "AGENTS.md")


def main() -> int:
    agents = open(AGENTS, encoding="utf-8").read()
    files = [f for f in os.listdir(CHECKS) if f.startswith("check-") and f.endswith(".py")]
    bad = []
    for f in sorted(files):
        if f not in agents:
            bad.append("判据 %s 没在 AGENTS.md 里出现（写了没人跑）" % f)
    for name in sorted(set(re.findall(r"check-[a-z0-9-]+\.py", agents))):
        if not os.path.isfile(os.path.join(CHECKS, name)):
            bad.append("AGENTS.md 提到 %s，但 tools/check 里没有" % name)
    for b in bad:
        print("[红] " + b)
    print("结论：%d 个判据 · %s" % (len(files), "红 %d" % len(bad) if bad else "全接上"))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
