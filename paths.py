# -*- coding: utf-8 -*-
r"""路径双根：资源根（只读）与数据根（可写）。

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
    DATA_ROOT 默认在程序目录；用户在「设置 → 课程库位置」里指定了别的文件夹时，
    DATA_ROOT 就指向那里——课程不再随程序文件夹走，换新版本只换程序、不碰库。
    LIBRARY_DEFAULT 记默认值，LIBRARY_CUSTOM 表示当前是不是独立库，
    LIBRARY_IGNORED 非空表示配置的库找不到（已退回程序目录）。

    默认不在 C 盘（2026-11-25 用户：「那么默认不要在 c 盘可以吗」）
        没配置过库、程序本身装在系统盘（通常是 C:）时，若还有别的固定盘，库自动落到
        <那块盘>\羽毛笔库（写进 install.json，标记 library_auto），不再跟着系统盘走；
        只有一块固定盘时只能留在程序目录。已有库或已有用户数据时一律不动，
        那种情况由界面问用户要不要挪（见 ui\server.py 的 suggest / off_c_decline）。

自带示例课程
    演示课程 DEMO 随程序发布，属于资源；用户自己的课程写在 exe 旁边，属于数据。
    data_or_res() / course_dir() 先看数据根、没有再用资源根，两种都能跑。
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import time

FROZEN = bool(getattr(sys, "frozen", False))
FS_ROOT = os.path.dirname(os.path.abspath(__file__))
RES_ROOT = os.path.abspath(getattr(sys, "_MEIPASS", "") or FS_ROOT)
DATA_ROOT = os.path.dirname(os.path.abspath(sys.executable)) if FROZEN else FS_ROOT
PROGRAM_DIR = DATA_ROOT          # 程序目录：默认库位置，也是「只有一块盘」时的退路
SYSTEM_DRIVE = (os.environ.get("SystemDrive") or "C:").rstrip("\\/").upper()
LIBRARY_DIRNAME = "羽毛笔库"      # 自动放到别的盘时用的文件夹名（例如 D:\羽毛笔库）

# 2026-11-25 用户：「主要是设定好那个库是在哪吧」——课程库（数据根）可以不跟着程序走。
#   以前数据根就是程序目录：把新版解到新文件夹，旧课程自然不在里面（v1.9.18 只能事后导入）。
#   现在「设置 → 课程库位置」可以把库定在任意文件夹，换版本/换程序目录都不动课程。
#   优先级：PLUMA_DATA（检查器专用）> ~\.pluma\install.json 的 library_root > 程序目录。
#   配置的目录不存在（移动硬盘没插 / 被删）时退回程序目录，并把原因记在 LIBRARY_IGNORED 里。
PLUMA_HOME = os.environ.get("PLUMA_HOME") or os.path.join(os.path.expanduser("~"), ".pluma")
STATE_PATH = os.path.join(PLUMA_HOME, "install.json")
LIBRARY_DEFAULT = PROGRAM_DIR


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


def _drive_of(path: str) -> str:
    """盘符（"D:"）；不是盘符路径就返回空串。"""
    try:
        return os.path.splitdrive(os.path.abspath(path))[0].rstrip("\\/").upper()
    except Exception:  # noqa: BLE001
        return ""


def drive_of(path: str) -> str:
    """公开版本：界面 / 检查器判断「库是不是在系统盘」。"""
    return _drive_of(path)


def _fixed_drives() -> list:
    """本机固定盘（GetDriveTypeW == 3）：不含 U 盘、光驱、网络盘。"""
    if os.name != "nt":
        return []
    try:
        import ctypes
        k32 = ctypes.windll.kernel32
        out = []
        for letter in "DEFGHIJKLMNOPQRSTUVWXYZ":
            root = letter + ":\\"
            if k32.GetDriveTypeW(root) == 3:
                out.append(root)
        return out
    except Exception:  # noqa: BLE001
        return [c + ":\\" for c in "DEFGHIJKLMNOPQRSTUVWXYZ" if os.path.isdir(c + ":\\")]


def _usable_library(path: str) -> bool:
    """这个库目录现在能用吗：建得出、写得进、还剩 200 MB 以上。"""
    try:
        os.makedirs(path, exist_ok=True)
        if shutil.disk_usage(path).free < 200 * 1024 * 1024:
            return False
        probe = os.path.join(path, ".pluma-write-test")
        with open(probe, "w", encoding="utf-8") as f:
            f.write("ok")
        os.remove(probe)
        return True
    except Exception:  # noqa: BLE001
        return False


def _pick_auto_dir(program_dir: str, system_drive: str, drives, usable=None) -> str:
    """程序在系统盘、机器另有固定盘时，挑一块放课程库。

    纯选择：不建目录、不读状态；usable 可注入（check-paths 用它造反例）。
    程序本来就不在系统盘 → 返回空串（已经不在 C 盘，就地不动）。
    """
    sysd = str(system_drive or "").rstrip("\\/").upper()
    if not sysd or _drive_of(program_dir) != sysd:
        return ""
    for d in drives or []:
        if not d or _drive_of(d) == sysd:
            continue
        p = os.path.join(d, LIBRARY_DIRNAME)
        if usable is None or usable(p):
            return p
    return ""


# 程序自带、不是用户课程的目录（判断「程序目录里有没有用户数据」时跳过）
_PROGRAM_DIRS = {"DEMO", "ui", "engine", "api", "tools", "docs", "assets", "feed",
                 "dist", "out", "_logs", "_trash", "__pycache__"}


def _program_has_data() -> bool:
    """程序目录里有没有用户自己写的课程：有就绝不自动搬库（会看起来像课程丢了）。"""
    if any(os.path.exists(os.path.join(PROGRAM_DIR, n))
           for n in ("courses.local.json", "out", "_logs", "_trash")):
        return True
    try:
        for name in os.listdir(PROGRAM_DIR):
            p = os.path.join(PROGRAM_DIR, name)
            if not os.path.isdir(p) or name in _PROGRAM_DIRS or name.startswith("."):
                continue
            if any(os.path.isdir(os.path.join(p, sub))
                   for sub in ("_lessons", "01_讲义", "00_原件", "06_笔记")):
                return True
    except OSError:
        pass
    return False


def _auto_library() -> str:
    """默认库不落在 C 盘：程序本身在系统盘时，自动放到别的固定盘。

    只在「没配置过库 / 用户没点过「恢复默认」/ 程序目录里没有用户数据」时做，并写进
    install.json（library_root + library_auto），以后固定用它；只有 C 盘一块固定盘时
    什么也不做（没得选）。已有课程的机器不会被静默搬走——那种情况由界面问用户。
    """
    if os.name != "nt" or os.environ.get("PLUMA_NO_LIBRARY") == "1":
        return ""
    if os.environ.get("PLUMA_DATA"):
        return ""
    st = load_state()
    if st.get("library_root") or st.get("library_cleared"):
        return ""
    if _program_has_data():
        return ""
    p = _pick_auto_dir(PROGRAM_DIR, SYSTEM_DRIVE, _fixed_drives(), _usable_library)
    if not p:
        return ""
    st.update({"library_root": p, "library_auto": True,
               "library_set": time.strftime("%Y-%m-%d %H:%M:%S")})
    save_state(st)
    return p


def suggest_library() -> str:
    """当前库在系统盘时，给一个「另一块固定盘」上的位置；没有别的盘返回空串。

    只挑不建：真正点「挪过去」时才创建（/api/library 的 create）。
    """
    if os.name != "nt" or os.environ.get("PLUMA_NO_LIBRARY") == "1":
        return ""
    here = os.path.normcase(os.path.abspath(DATA_ROOT))
    for d in _fixed_drives():
        if _drive_of(d) == SYSTEM_DRIVE or not os.path.isdir(d):
            continue
        try:
            if shutil.disk_usage(d).free < 200 * 1024 * 1024:
                continue
        except Exception:  # noqa: BLE001
            continue
        p = os.path.join(d, LIBRARY_DIRNAME)
        if os.path.normcase(os.path.abspath(p)) != here:
            return p
    return ""


def _configured_library() -> str:
    if os.environ.get("PLUMA_NO_LIBRARY") == "1":
        return ""
    p = (os.environ.get("PLUMA_DATA") or "").strip()
    if not p:
        p = str(load_state().get("library_root") or "").strip()
    return os.path.abspath(os.path.expanduser(p)) if p else ""


LIBRARY_CONFIG = _configured_library()
LIBRARY_IGNORED = ""
LIBRARY_AUTO = False
if LIBRARY_CONFIG:
    if os.path.isdir(LIBRARY_CONFIG):
        DATA_ROOT = LIBRARY_CONFIG
        try:
            st0 = load_state()
            LIBRARY_AUTO = (bool(st0.get("library_auto"))
                            and os.path.normcase(os.path.abspath(str(st0.get("library_root") or "")))
                            == os.path.normcase(os.path.abspath(LIBRARY_CONFIG)))
        except Exception:  # noqa: BLE001
            LIBRARY_AUTO = False
    else:
        LIBRARY_IGNORED = LIBRARY_CONFIG
else:
    # 首次运行 + 程序在系统盘：默认把库放到别的固定盘（用户 2026-11-25 要求）。
    _AUTO_LIBRARY = _auto_library()
    if _AUTO_LIBRARY:
        DATA_ROOT = _AUTO_LIBRARY
        LIBRARY_AUTO = True
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


def detect_course() -> str:
    """默认课程：PLUMA_COURSE → 数据根/资源根里第一个带 _lessons 的目录 → DEMO。

    2026-11-27：课程代号不再写死在代码里（真实课程名不进公开仓）。只按磁盘事实认；
    一个都认不到时退回随程序发布的 DEMO，不指一个不存在的目录让下游报「找不到」。
    """
    env = os.environ.get("PLUMA_COURSE")
    if env:
        return env
    for root in (DATA_ROOT, RES_ROOT):
        try:
            names = sorted(os.listdir(root))
        except OSError:
            continue
        for name in names:
            if os.path.isdir(os.path.join(root, name, "_lessons")):
                return name
    return "DEMO"


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
