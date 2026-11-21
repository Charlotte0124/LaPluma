# -*- coding: utf-8 -*-
r"""分发形态判据：只允许「仓库文件夹 + 启动羽毛笔.cmd」，不许再出现单文件 exe 与打包脚本。

为什么有这条（2026-11-21 用户定）：
    dist\LaPluma.exe 是 PyInstaller 单文件包，启动第一步要在 %TEMP% 解包 86 MB；
    用户的机器上这一步建目录被拒，只弹 "Could not create temporary directory!"，
    我们的代码一行都没执行。用户随后定：「以后直接是文件夹的那种形式吧，不打包了。」

红：
    A  dist\LaPluma.exe 又出现了（单文件包）
    B  打包脚本 / spec 又回来了（tools\build\build-exe.ps1、lapluma.spec）
    C  启动入口缺失，或没指向 pythonw + ui\server.py
绿：以上都满足。
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    fails = []
    exe = ROOT / "dist" / "LaPluma.exe"
    if exe.exists():
        fails.append("红 A: 又出现了单文件 exe dist\\LaPluma.exe")
    for rel in ("tools/build/build-exe.ps1", "tools/build/lapluma.spec"):
        if (ROOT / rel).exists():
            fails.append("红 B: 打包脚本又回来了 " + rel)
    launcher = ROOT / "启动羽毛笔.cmd"
    if not launcher.exists():
        fails.append("红 C: 缺启动入口 启动羽毛笔.cmd")
    else:
        text = launcher.read_bytes().decode("gbk", "replace")
        if "pythonw" not in text.lower() or "ui\\server.py" not in text:
            fails.append("红 C: 启动入口没指向 pythonw + ui\\server.py")
    if fails:
        for f in fails:
            print(f)
        print("结论：红 %d" % len(fails))
        return 1
    print("结论：绿（文件夹版 + 启动羽毛笔.cmd，无 exe / 打包脚本）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
