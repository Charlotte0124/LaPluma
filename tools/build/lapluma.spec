# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置：羽毛笔 La Pluma → 单文件 exe。

两根的关系（见仓根 paths.py）：
  · 资源（ui / engine / tools / api / DEMO / courses.json / paths.py）打进 exe，运行时解到 sys._MEIPASS
  · 数据（用户自己的课程、out\\、_logs\\、~/.pluma 配置）落在 exe 旁边

所以这里只 add-data 资源，绝不把 CS340（真实课程）打进去——公开仓不含它。
"""
import os

from PyInstaller.utils.hooks import collect_data_files

ROOT = os.path.abspath(os.path.join(SPECPATH, "..", ".."))

datas = [
    (os.path.join(ROOT, "ui"), "ui"),
    (os.path.join(ROOT, "engine"), "engine"),
    (os.path.join(ROOT, "tools"), "tools"),
    (os.path.join(ROOT, "api"), "api"),
    (os.path.join(ROOT, "DEMO"), "DEMO"),
    # 2026-11-17：资产目录必须打进去——/favicon.ico 与窗口图标都读 assets\lapluma.ico
    (os.path.join(ROOT, "assets"), "assets"),
    (os.path.join(ROOT, "courses.json"), "."),
    (os.path.join(ROOT, "paths.py"), "."),
    # 2026-11-17：许可分层落地——分发件必须带版权与许可声明（MIT 的要求）。
    # 四个文件打到 _MEIPASS 根目录，界面的「设置」页底部也能读出路径供用户查看。
    (os.path.join(ROOT, "LICENSE"), "."),
    (os.path.join(ROOT, "NOTICE.md"), "."),
    (os.path.join(ROOT, "LICENSE-CONTENT.md"), "."),
    (os.path.join(ROOT, "LICENSE-DOCS.md"), "."),
]
# pywebview 自带 js/css，不带就会白窗口
for src, dst in collect_data_files("webview"):
    datas.append((src, dst))

# engine / api 是运行时按名字 import 的（server.py 的 _engine()），modulegraph 看不出来；
# 它们已经作为数据文件在 _MEIPASS 里，sys.path 也覆盖了，所以不用 hiddenimports 抓它们。
hidden = [
    "pymupdf", "tkinter", "tkinter.filedialog", "tkinter.messagebox",
    # 2026-11-17：v1.9.0 起界面装在 WebView2 窗口里（pywebview）
    "webview", "webview.platforms.edgechromium", "webview.platforms.winforms",
    "clr", "pythonnet",
]

a = Analysis(
    [os.path.join(ROOT, "ui", "server.py")],
    pathex=[ROOT],
    binaries=[],
    datas=datas,
    hiddenimports=hidden,
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        "numpy", "pandas", "matplotlib", "scipy", "PIL", "IPython",
        "pytest", "playwright", "setuptools", "pip", "wheel",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="LaPluma",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,       # 无控制台：双击就是一个自己的窗口（v1.9.0）
    icon=os.path.join(ROOT, "assets", "lapluma.ico"),
    disable_windowed_traceback=False,
)
