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
    boot = ROOT / "一键启动.ps1"
    if not launcher.exists():
        fails.append("红 C: 缺启动入口 启动羽毛笔.cmd")
    else:
        raw = launcher.read_bytes()
        # 2026-11-21 用户：「启动羽毛笔.cmd 也没有用 打不开」，而同样内容的 一键启动.bat 能用。
        #   真因不是 pythonw，是码页：双击时 cmd.exe 按系统 ANSI 码页（本机 936）读文件，
        #   .cmd 当时是 UTF-8、里面硬编码了中文脚本名 → 解成乱码 → powershell 找不到路径 →
        #   控制台一闪即关。.bat 是 GBK 存的，所以一直好使。
        #   现在启动器纯 ASCII，用 *.ps1 通配找脚本；这条判据顺手把「又混进非 ASCII」也判红。
        if any(b > 127 for b in raw):
            fails.append("红 C: 启动羽毛笔.cmd 里有非 ASCII 字节（双击按系统码页解码会乱码）")
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = raw.decode("gbk", "replace")
        if "一键启动.ps1" not in text and "*.ps1" not in text:
            fails.append("红 C: 启动入口没调用启动脚本（一键启动.ps1 或 *.ps1 通配）")
    if not boot.exists():
        fails.append("红 C: 缺 一键启动.ps1（环境检查 + pymupdf 弹窗）")
    else:
        bt = boot.read_bytes().decode("utf-8-sig", "replace")
        if "pythonw" not in bt.lower() or "pymupdf" not in bt:
            fails.append("红 C: 一键启动.ps1 缺 pythonw 启动或 pymupdf 检查")
    if fails:
        for f in fails:
            print(f)
        print("结论：红 %d" % len(fails))
        return 1
    print("结论：绿（文件夹版 + 启动羽毛笔.cmd，无 exe / 打包脚本）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
