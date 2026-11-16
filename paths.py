# -*- coding: utf-8 -*-
"""路径双根：资源根（只读）与数据根（可写）。

为什么要分两根
    源码跑的时候，资源和数据都在仓根，一根就够。冻结成 exe（PyInstaller）之后不行：
      · 资源（ui\\ engine\\ tools\\ api\\，含 pdf.js 与 KaTeX 字体）被打进 exe，
        运行时解到临时目录（sys._MEIPASS）——那个目录随时会被删，往里写等于写在半空；
      · 数据（courses.json、<课程>\\_lessons、06_笔记、01_讲义、out\\、_logs\\）
        必须落在 exe 旁边，用户要能改、能备份、能看见。
    原来所有模块都写 ROOT = dirname(dirname(__file__))：源码下没问题，冻结后 ROOT 指到
    临时解包目录，于是 tools\\print\\pdfjs、KaTeX 字体全找不到，生成出来的讲义源也被写进
    临时目录，一关软件就没了。

口径
    RES_ROOT   只读资源，永远不要往里写
    DATA_ROOT  可写数据，所有生成物与用户课件都放这
    源码运行时两者相同（= 仓根），所以行为与改造前完全一致（回归见 tools\\check\\check-paths.py）。

自带示例课程
    演示课程 DEMO 随程序发布，属于资源；用户自己的课程写在 exe 旁边，属于数据。
    data_or_res() / course_dir() 先看数据根、没有再用资源根，两种都能跑。
"""
from __future__ import annotations

import os
import sys

FROZEN = bool(getattr(sys, "frozen", False))
FS_ROOT = os.path.dirname(os.path.abspath(__file__))
RES_ROOT = os.path.abspath(getattr(sys, "_MEIPASS", "") or FS_ROOT)
DATA_ROOT = os.path.dirname(os.path.abspath(sys.executable)) if FROZEN else FS_ROOT


def res(*parts: str) -> str:
    """资源路径（只读）：ui\\ tools\\ api\\ engine\\ 里跟着程序走的东西。"""
    return os.path.join(RES_ROOT, *parts)


def data(*parts: str) -> str:
    """数据路径（可写）：courses.json、<课程>\\、out\\、_logs\\。"""
    return os.path.join(DATA_ROOT, *parts)


def data_or_res(*parts: str) -> str:
    """优先数据根；数据根没有就用资源根（出厂自带的 courses.json / 示例课程走这条）。"""
    d = data(*parts)
    if os.path.exists(d):
        return d
    r = res(*parts)
    return r if os.path.exists(r) else d


def course_dir(code: str) -> str:
    """一门课的根目录：用户放在 exe 旁边就用它，否则退回随程序发布的那份。"""
    return data_or_res(code)


def bootstrap() -> None:
    """把两根与 engine\\ tools\\print\\ api\\ 挂上 sys.path；冻结后也照做（幂等）。"""
    for p in (DATA_ROOT, RES_ROOT, res("engine"), res("tools", "print"), res("api")):
        if p and p not in sys.path:
            sys.path.insert(0, p)
