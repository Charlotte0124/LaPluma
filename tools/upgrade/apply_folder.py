# -*- coding: utf-8 -*-
r"""文件夹版应用内更新的「落地」一步（v1.9.18）。

由 ui/server.py 在程序准备退出前拉起：等旧进程退出 → 把解压好的新版覆盖到程序目录
→ 保留用户数据 → 重新启动。这个脚本被复制到 %USERPROFILE%\.pluma\update\ 下执行，
所以它不 import 仓里的任何模块，旧目录被覆盖时也不会踩到自己。

为什么不整目录换名：文件夹版的数据就在程序目录里（课程、out、_logs）。整目录换名要
把用户数据再搬一次，中途失败就两头不靠；覆盖只动程序文件，用户数据一个字节都不碰。

用法（由服务端调用，不给人手敲）：
    pythonw apply_folder.py --staged <解压目录> --root <程序目录> --ver 1.9.18 --pid 1234
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import shutil
import subprocess
import sys
import time

HOME = os.path.expanduser("~")
PLUMA_HOME = os.environ.get("PLUMA_HOME") or os.path.join(HOME, ".pluma")
LOG = os.path.join(PLUMA_HOME, "update", "apply.log")
# 用户数据：新包里就算带了也不许覆盖（压缩包理论上只有程序，防一手）
KEEP_IF_EXISTS = {"courses.json", "courses.local.json"}
SKIP_NAMES = {".git", ".github", "__pycache__", "dist"}


def log(msg: str) -> None:
    try:
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write("%s  %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg))
    except Exception:  # noqa: BLE001
        pass


def wait_pid(pid: int, timeout: float = 180.0) -> bool:
    """等旧进程退出（Windows：OpenProcess + WaitForSingleObject；拿不到句柄就轮询）。"""
    if pid <= 0:
        return True
    try:
        k32 = ctypes.windll.kernel32
        h = k32.OpenProcess(0x00100000, False, int(pid))   # SYNCHRONIZE
        if h:
            try:
                r = k32.WaitForSingleObject(h, int(timeout * 1000))
                return r in (0x00000000, 0x00000102)        # signaled / timeout
            finally:
                k32.CloseHandle(h)
    except Exception as e:  # noqa: BLE001
        log("wait_pid 句柄失败，改轮询：%r" % (e,))
    end = time.time() + timeout
    while time.time() < end:
        try:
            os.kill(pid, 0)
        except OSError:
            return True
        time.sleep(0.5)
    return False


def read_version(server_py: str) -> str:
    try:
        with open(server_py, encoding="utf-8") as f:
            for line in f:
                if line.startswith("VERSION = "):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    except Exception:  # noqa: BLE001
        pass
    return ""


def _files_under(path: str):
    if os.path.isfile(path):
        yield path
        return
    for dirpath, dirnames, filenames in os.walk(path):
        dirnames[:] = [d for d in dirnames if d not in SKIP_NAMES]
        for n in filenames:
            yield os.path.join(dirpath, n)


def backup_and_copy(stage: str, root: str, backup: str) -> dict:
    """把 stage 覆盖到 root；被覆盖的旧文件先备份到 backup/<相对路径>。

    返回 {"copied": 文件数, "backed": 文件数}。任何一步抛异常，调用方回滚。
    """
    copied = backed = 0
    for name in sorted(os.listdir(stage)):
        if name in SKIP_NAMES:
            continue
        sp = os.path.join(stage, name)
        dp = os.path.join(root, name)
        if name in KEEP_IF_EXISTS and os.path.exists(dp):
            log("保留现有 %s（不覆盖）" % name)
            continue
        # 备份即将被覆盖的文件（只备份已存在的）
        for f in _files_under(sp):
            rel = os.path.relpath(f, stage)
            old = os.path.join(root, rel)
            if os.path.exists(old):
                b = os.path.join(backup, rel)
                os.makedirs(os.path.dirname(b), exist_ok=True)
                if not os.path.exists(b):
                    shutil.copy2(old, b)
                    backed += 1
        if os.path.isdir(sp):
            os.makedirs(dp, exist_ok=True)
            for dirpath, dirnames, filenames in os.walk(sp):
                dirnames[:] = [d for d in dirnames if d not in SKIP_NAMES]
                rel_dir = os.path.relpath(dirpath, sp)
                target_dir = dp if rel_dir == "." else os.path.join(dp, rel_dir)
                os.makedirs(target_dir, exist_ok=True)
                for n in filenames:
                    shutil.copy2(os.path.join(dirpath, n), os.path.join(target_dir, n))
                    copied += 1
        else:
            os.makedirs(os.path.dirname(dp), exist_ok=True)
            shutil.copy2(sp, dp)
            copied += 1
    return {"copied": copied, "backed": backed}


def restore(backup: str, root: str) -> int:
    n = 0
    for f in _files_under(backup):
        rel = os.path.relpath(f, backup)
        dst = os.path.join(root, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(f, dst)
        n += 1
    return n


def record_install(root: str, ver: str) -> None:
    try:
        os.makedirs(PLUMA_HOME, exist_ok=True)
        p = os.path.join(PLUMA_HOME, "install.json")
        data = {}
        if os.path.isfile(p):
            try:
                data = json.load(open(p, encoding="utf-8")) or {}
            except Exception:  # noqa: BLE001
                data = {}
        data.update({"last_data_root": os.path.abspath(root),
                     "updated": time.strftime("%Y-%m-%d %H:%M:%S"),
                     "last_version": ver})
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, p)
    except Exception as e:  # noqa: BLE001
        log("写 install.json 失败：%r" % (e,))


def relaunch(root: str) -> bool:
    ps = os.path.join(root, "一键启动.ps1")
    if not os.path.isfile(ps):
        log("找不到启动脚本：%s" % ps)
        return False
    try:
        # DETACHED_PROCESS：更新器退出后，新进程仍活着
        subprocess.Popen(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                          "-WindowStyle", "Hidden", "-File", ps, "-Windowed"],
                         cwd=root, close_fds=True, creationflags=0x00000008)
        log("已重新启动：%s" % ps)
        return True
    except Exception as e:  # noqa: BLE001
        log("重启失败：%r" % (e,))
        return False


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--staged", required=True)
    ap.add_argument("--root", required=True)
    ap.add_argument("--backup-root", default="")
    ap.add_argument("--ver", default="")
    ap.add_argument("--pid", type=int, default=0)
    ap.add_argument("--no-relaunch", action="store_true")
    a = ap.parse_args(argv)
    stage, root = os.path.abspath(a.staged), os.path.abspath(a.root)
    # 更新器必须离开程序目录，否则 Windows 可能因「当前目录被占用」拒绝对它的改名/覆盖
    try:
        os.chdir(os.path.join(PLUMA_HOME, "update"))
    except OSError:
        pass
    log("start ver=%s pid=%s stage=%s root=%s" % (a.ver, a.pid, stage, root))

    try:
        if not os.path.isfile(os.path.join(stage, "ui", "server.py")):
            raise RuntimeError("解压目录不像新版程序（缺 ui/server.py）")
        got = read_version(os.path.join(stage, "ui", "server.py"))
        if a.ver and got and got != a.ver:
            raise RuntimeError("包里的版本是 %s，清单写的是 %s" % (got, a.ver))
        if not os.path.isfile(os.path.join(root, "ui", "server.py")):
            raise RuntimeError("目标目录不像羽毛笔程序（缺 ui/server.py）：%s" % root)
        if not wait_pid(a.pid):
            raise RuntimeError("等旧进程退出超时（PID %s），为免半套文件先不动" % a.pid)
        ts = time.strftime("%Y%m%d-%H%M%S")
        backup = a.backup_root or os.path.join(
            PLUMA_HOME, "update", "backup-%s-%s" % (a.ver or "new", ts))
        os.makedirs(backup, exist_ok=True)
        log("备份目录：%s" % backup)
        got2 = backup_and_copy(stage, root, backup)
        # 回查：新包里的 ui/server.py 必须真到位，版本对得上
        now = read_version(os.path.join(root, "ui", "server.py"))
        if a.ver and now != a.ver:
            raise RuntimeError("覆盖后版本仍为 %r（期望 %s）" % (now, a.ver))
        record_install(root, now or a.ver)
        log("folder apply ok：copied=%d backed=%d version=%s backup=%s"
            % (got2["copied"], got2["backed"], now, backup))
        if not a.no_relaunch and os.environ.get("PLUMA_NO_RELAUNCH") != "1":
            relaunch(root)
        return 0
    except Exception as e:  # noqa: BLE001
        log("folder apply FAILED：%r" % (e,))
        # 尽力回滚：备份存在就拷回去
        try:
            b = locals().get("backup")
            if b and os.path.isdir(b):
                n = restore(b, root)
                log("已回滚 %d 个文件" % n)
        except Exception as e2:  # noqa: BLE001
            log("回滚也失败：%r" % (e2,))
        if not a.no_relaunch and os.environ.get("PLUMA_NO_RELAUNCH") != "1":
            relaunch(root)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
