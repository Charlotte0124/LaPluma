# -*- coding: utf-8 -*-
r"""规矩与判据接线检查（2026-11-22 用户定）。

为什么有这条：用户原话「每次改动结束之后都要保存最新的规矩，不然永远都会发生老问题，
并且制作钩子防止这事情发生」。所以规矩写在 AGENTS.md、判据写在 tools/check/，两边必须对上：
  · tools/check 里有判据，AGENTS.md 里没提 → 红（写了没人跑，等于没写）
  · AGENTS.md 提到 check-xxx.py，文件不存在 → 红（规矩指向空气）
"""
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CHECKS = os.path.join(ROOT, "tools", "check")
AGENTS = os.path.join(ROOT, "AGENTS.md")


def hooks_on() -> tuple:
    """钩子文件跟着仓库走，开关却是每个克隆的本地配置——换机器不跑 setup-hooks.py 就等于没有。

    用户 2026-11-22：「这些增加到了 github 了吗 不然的话换视窗就不管用了」。
    判据：仓库里有 .githooks/pre-commit 时，local 的 core.hooksPath 必须是 .githooks。
    """
    hook = os.path.join(ROOT, ".githooks", "pre-commit")
    if not os.path.isfile(hook):
        return True, "仓库里没有 .githooks/pre-commit（不判）"
    r = subprocess.run(["git", "-C", ROOT, "config", "--local", "core.hooksPath"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    val = (r.stdout or "").strip()
    if val == ".githooks":
        return True, "钩子已开"
    return False, "钩子没开（core.hooksPath=%r）：先跑 python tools/setup-hooks.py" % (val,)


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
    ok_hooks, why_hooks = hooks_on()
    if not ok_hooks:
        bad.append(why_hooks)
    for b in bad:
        print("[红] " + b)
    print("结论：%d 个判据 · %s · %s"
          % (len(files), why_hooks if ok_hooks else "钩子没开",
             "红 %d" % len(bad) if bad else "全接上"))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
