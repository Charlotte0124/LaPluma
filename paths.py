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

课程库位置（2026-11-25）
    DATA_ROOT 默认仍是程序目录；但用户在「设置 → 课程库位置」里指定了别的文件夹时，
    DATA_ROOT 就指向那里——课程不再随程序文件夹走，换新版本只换程序、不碰库。
    LIBRARY_DEFAULT 记默认值，LIBRARY_CUSTOM 表示当前是不是独立库，
    LIBRARY_IGNORED 非空表示配置的库找不到（已退回程序目录）。

自带示例课程
    演示课程 DEMO 随程序发布，属于资源；用户自己的课程写在 exe 旁边，属于数据。
    data_or_res() / course_dir() 先看数据根、没有再用资源根，两种都能跑。
"""
from __future__ import annotations

import json
import os
import sys

FROZEN = bool(getattr(sys, "frozen", False))
FS_ROOT = os.path.dirname(os.path.abspath(__file__))
RES_ROOT = os.path.abspath(getattr(sys, "_MEIPASS", "") or FS_ROOT)
DATA_ROOT = os.path.dirname(os.path.abspath(sys.executable)) if FROZEN else FS_ROOT

# 2026-11-25 用户：「主要是设定好那个库是在哪吧」——课程库（数据根）可以不跟着程序走。
#   以前数据根就是程序目录：把新版解到新文件夹，旧课程自然不在里面（v1.9.18 只能事后导入）。
#   现在「设置 → 课程库位置」可以把库定在任意文件夹，换版本/换程序目录都不动课程。
#   优先级：PLUMA_DATA（检查器专用）> ~\.pluma\install.json 的 library_root > 程序目录。
#   配置的目录不存在（移动硬盘没插 / 被删）时退回程序目录，并把原因记在 LIBRARY_IGNORED 里。
PLUMA_HOME = os.environ.get("PLUMA_HOME") or os.path.join(os.path.expanduser("~"), ".pluma")
STATE_PATH = os.path.join(PLUMA_HOME, "install.json")
LIBRARY_DEFAULT = DATA_ROOT


def load_state() -> dict:
    """本机安装状态（install.json）：上一次数据根、库位置、拒绝过的导入……读不到就当空。"""
    try:
        with open(STATE_PATH, "r", encoding="utf-8-sig") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def save_state(d: dict) -> bool:
    """写 install.json（原子替换）。写不进去返回 False，调用方自己决定怎么提示。"""
    try:
        os.makedirs(PLUMA_HOME, exist_ok=True)
        tmp = STATE_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
        os.replace(tmp, STATE_PATH)
        return True
    except Exception:  # noqa: BLE001
        return False


def _configured_library() -> str:
    if os.environ.get("PLUMA_NO_LIBRARY") == "1":
        return ""
    p = (os.environ.get("PLUMA_DATA") or "").strip()
    if not p:
        p = str(load_state().get("library_root") or "").strip()
    return os.path.abspath(os.path.expanduser(p)) if p else ""


LIBRARY_CONFIG = _configured_library()
LIBRARY_IGNORED = ""
if LIBRARY_CONFIG:
    if os.path.isdir(LIBRARY_CONFIG):
        DATA_ROOT = LIBRARY_CONFIG
    else:
        LIBRARY_IGNORED = LIBRARY_CONFIG
LIBRARY_ROOT = DATA_ROOT
LIBRARY_CUSTOM = (os.path.normcase(os.path.abspath(DATA_ROOT))
                  != os.path.normcase(os.path.abspath(LIBRARY_DEFAULT)))


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
    """把资源根与 engine\\ tools\\print\\ api\\ 挂上 sys.path；冻结后也照做（幂等）。

    2026-11-25：数据根改成可配置后，不能再把它插到 sys.path 最前面——库若指向一个
    旧版程序目录，旧 ui\\ paths.py 会遮住新程序自己的模块。数据根垫到最后（源码下它
    就是资源根，行为不变）。
    """
    for p in (RES_ROOT, res("engine"), res("tools", "print"), res("api")):
        if p and p not in sys.path:
            sys.path.insert(0, p)
    if DATA_ROOT and DATA_ROOT not in sys.path:
        sys.path.append(DATA_ROOT)
