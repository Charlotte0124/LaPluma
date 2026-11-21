# -*- coding: utf-8 -*-
r"""开提交钩子：把 core.hooksPath 指到 .githooks（克隆后跑一次）。

为什么有这条：钩子文件在 .githooks/ 里，会跟着仓库走；但「用不用它」是每个克隆自己的
本地配置 core.hooksPath，**不会**跟着仓库走。换一台机器、或换一个视窗重新克隆，不跑这一步，
所有判据一条都不会跑，等于没有（用户 2026-11-22：「这些增加到了 github 了吗 不然的话换视窗
就不管用了」）。

用法：
    python tools/setup-hooks.py
退出码：0 已开 / 1 失败
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOK = os.path.join(ROOT, ".githooks", "pre-commit")


def git(*args):
    return subprocess.run(["git", "-C", ROOT] + list(args), capture_output=True,
                          text=True, encoding="utf-8", errors="replace")


def main():
    if not os.path.isfile(HOOK):
        print("[红] 仓库里没有 .githooks/pre-commit")
        return 1
    r = git("config", "core.hooksPath", ".githooks")
    if r.returncode != 0:
        print("[红] 设置失败：%s" % ((r.stderr or r.stdout).strip(),))
        return 1
    cur = git("config", "--local", "core.hooksPath")
    val = (cur.stdout or "").strip()
    if val != ".githooks":
        print("[红] 设完读回来是 %r" % (val,))
        return 1
    print("[绿] 提交钩子已开：core.hooksPath=%s → %s" % (val, HOOK))
    print("      以后每次 git commit 都会跑 tools/check 里的判据；")
    print("      想临时关掉：git config --unset core.hooksPath")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
