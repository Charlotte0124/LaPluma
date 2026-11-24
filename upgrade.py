# -*- coding: utf-8 -*-
r"""升级与数据迁移（v1.9.18，2026-11-24）。

为什么有这支脚本：用户实测「下载 1.9.17 的时候，1.9.16 的课程并没有在那里面
（1.9.16 整了三个课程，到 1.9.17 就不见了）」。

原因不是课程被删，而是文件夹版的数据根就是程序目录本身（见 paths.py）：
把新压缩包解到一个新文件夹，旧文件夹里的课程当然不在新文件夹里。
这份脚本做两件事，都不动旧目录：

  1 import_from(src, dst)  把旧目录里的「用户数据」搬到新目录：courses.local.json、
     真实课程目录、out / _logs / _trash、根目录下的 PDF。目标已存在的文件不覆盖。
  2 pending_for(root)      新目录首次启动时找旧目录（install.json 记的上一次数据根、
     同级目录、Downloads / Desktop 里名字像 LaPluma 的目录），只**列出来给界面问**，
     不再偷偷导入（v1.9.19 用户：「要么就加上个检测到有以前版本的 是否要导入？」）。

课程库位置（v1.9.19）
    set_library(path) / clear_library() 把「库」定在任意文件夹（install.json 的
    library_root），换新版本只换程序、课程留在库里。命令行 --where / --set-library。

命令行：
    python upgrade.py --where
    python upgrade.py --set-library "D:\我的羽毛笔库"
    python upgrade.py --list
    python upgrade.py --from "D:\旧版\LaPluma" --dry-run
    python upgrade.py --from "D:\旧版\LaPluma"
    python upgrade.py --stop-old            # 只列出占用 8765-8775 的旧实例
    python upgrade.py --stop-old --kill     # 结束这些旧实例（卸载旧版前用）
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
HOME = os.path.expanduser("~")
PLUMA_HOME = os.environ.get("PLUMA_HOME") or os.path.join(HOME, ".pluma")
STATE = os.path.join(PLUMA_HOME, "install.json")

# 程序自带的目录，绝不当成用户数据搬
PROGRAM_DIRS = {
    "ui", "engine", "api", "tools", "docs", "assets", "feed", "DEMO",
    "dist", "out", "_logs", "_trash", ".build", ".git", ".github", ".githooks",
    "__pycache__",
}
# 这些即使看起来像课程，也是程序自带的示例
PROGRAM_COURSES = {"DEMO"}
DATA_TOP = ("courses.local.json", "out", "_logs", "_trash")


def _read_json(path: str, default):
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return default


def _course_keys(root: str) -> list:
    keys = []
    for name in ("courses.json", "courses.local.json"):
        cfg = _read_json(os.path.join(root, name), {})
        if isinstance(cfg, dict):
            keys += [k for k in cfg if not str(k).startswith("_")]
    seen, out = set(), []
    for k in keys:
        if k not in seen:
            seen.add(k)
            out.append(k)
    return out


def course_dirs(root: str) -> list:
    """真实课程目录：配置里登记的 + 长得像课程的（有 _lessons / 01_讲义 / 00_原件 / 06_笔记）。"""
    out = []
    for k in _course_keys(root):
        if k in PROGRAM_COURSES:
            continue
        p = os.path.join(root, k)
        if os.path.isdir(p) and k not in out:
            out.append(k)
    try:
        for name in sorted(os.listdir(root)):
            p = os.path.join(root, name)
            if (not os.path.isdir(p) or name in PROGRAM_DIRS or name in PROGRAM_COURSES
                    or name.startswith(".") or name in out):
                continue
            if any(os.path.isdir(os.path.join(p, sub)) for sub in
                   ("_lessons", "01_讲义", "00_原件", "06_笔记")):
                out.append(name)
    except OSError:
        pass
    return out


def user_items(root: str) -> list:
    """用户数据相对路径列表（只列真存在的）。"""
    items = []
    for name in DATA_TOP:
        p = os.path.join(root, name)
        if os.path.exists(p):
            items.append(name)
    items += course_dirs(root)
    # 根目录下的 PDF 是用户自己的原件/成品（仓里根目录的 PDF 已被 .gitignore 拦住）
    try:
        for name in sorted(os.listdir(root)):
            p = os.path.join(root, name)
            if os.path.isfile(p) and name.lower().endswith(".pdf"):
                items.append(name)
    except OSError:
        pass
    # 去重、保持顺序
    seen, out = set(), []
    for x in items:
        if x not in seen and os.path.exists(os.path.join(root, x)):
            seen.add(x)
            out.append(x)
    return out


def _files_of(path: str):
    if os.path.isfile(path):
        yield "", path
        return
    for dirpath, _dirnames, filenames in os.walk(path):
        rel = os.path.relpath(dirpath, path)
        if rel == ".":
            rel = ""
        for n in filenames:
            yield os.path.join(rel, n) if rel else n, os.path.join(dirpath, n)


def count_files(path: str) -> int:
    return sum(1 for _ in _files_of(path)) if os.path.exists(path) else 0


def size_of(path: str) -> int:
    n = 0
    for _rel, p in _files_of(path):
        try:
            n += os.path.getsize(p)
        except OSError:
            pass
    return n


def _copy_missing(src_item: str, dst_item: str, copied: list, skipped: list) -> None:
    """把 src 里目标没有的文件补过去；目标已有的不覆盖（并记下来）。"""
    if os.path.isfile(src_item):
        if os.path.exists(dst_item):
            skipped.append(os.path.basename(dst_item))
        else:
            os.makedirs(os.path.dirname(dst_item) or ".", exist_ok=True)
            shutil.copy2(src_item, dst_item)
            copied.append(dst_item)
        return
    for rel, sp in _files_of(src_item):
        dp = os.path.join(dst_item, rel) if rel else dst_item
        if os.path.exists(dp):
            skipped.append(os.path.relpath(dp, os.path.dirname(dst_item)))
            continue
        os.makedirs(os.path.dirname(dp) or ".", exist_ok=True)
        shutil.copy2(sp, dp)
        copied.append(dp)


def import_from(src: str, dst: str, dry_run: bool = False) -> dict:
    """把 src 的用户数据补进 dst。返回报告（含逐项与文件数、字节数、校验结果）。"""
    src, dst = os.path.abspath(src), os.path.abspath(dst)
    if not os.path.isdir(src):
        return {"ok": False, "error": "源目录不存在：%s" % src}
    if not os.path.isdir(dst):
        return {"ok": False, "error": "目标目录不存在：%s" % dst}
    items = user_items(src)
    if not items:
        return {"ok": True, "src": src, "dst": dst, "items": [], "copied_files": 0,
                "skipped_files": 0, "bytes": 0, "note": "源目录里没有用户数据"}
    report = {"ok": True, "src": src, "dst": dst, "when": time.strftime("%Y-%m-%d %H:%M:%S"),
              "dry_run": bool(dry_run), "items": [], "copied_files": 0,
              "skipped_files": 0, "bytes": 0, "missing_after": []}
    for name in items:
        sp, dp = os.path.join(src, name), os.path.join(dst, name)
        n = count_files(sp)
        b = size_of(sp)
        exists_before = os.path.exists(dp)
        if dry_run:
            action = "would-copy" if not exists_before else "merge"
        else:
            copied, skipped = [], []
            _copy_missing(sp, dp, copied, skipped)
            report["copied_files"] += len(copied)
            report["skipped_files"] += len(skipped)
            report["bytes"] += sum(os.path.getsize(p) for p in copied if os.path.isfile(p))
            action = "copied" if copied and not skipped else ("merged" if copied else "already-there")
        report["items"].append({"name": name, "files": n, "bytes": b,
                                "existed": exists_before, "action": action})
        # 干跑不做存在性回查
        if not dry_run:
            for rel, _sp in _files_of(sp):
                want = os.path.join(dp, rel) if os.path.isdir(dp) else dp
                if not os.path.exists(want):
                    report["missing_after"].append(os.path.join(name, rel))
    if not dry_run:
        report["ok"] = not report["missing_after"]
        _write_report(report)
    return report


def _write_report(report: dict) -> str:
    d = os.path.join(report["dst"], "_logs")
    try:
        os.makedirs(d, exist_ok=True)
        p = os.path.join(d, "upgrade-import-%s.json" % time.strftime("%Y%m%d-%H%M%S"))
        with open(p, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        return p
    except Exception:  # noqa: BLE001
        return ""


def _write_state(st: dict) -> bool:
    try:
        os.makedirs(PLUMA_HOME, exist_ok=True)
        tmp = STATE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(st, f, ensure_ascii=False, indent=2)
        os.replace(tmp, STATE)
        return True
    except Exception:  # noqa: BLE001
        return False


def record_install(root: str) -> None:
    """记下这次用的数据根，下一次在别处启动时能找到旧课程。"""
    old = _read_json(STATE, {})
    if not isinstance(old, dict):
        old = {}
    old.update({"last_data_root": os.path.abspath(root),
                "updated": time.strftime("%Y-%m-%d %H:%M:%S")})
    _write_state(old)


# ---------- 课程库位置（v1.9.19） ----------
def library_status() -> dict:
    """当前库：root 实际用的数据根；config 配置里写的；ignored 配置了但找不到的。"""
    try:
        import paths
    except Exception:  # noqa: BLE001
        return {"root": ROOT, "default": ROOT, "custom": False,
                "config": "", "ignored": ""}
    return {"root": paths.DATA_ROOT, "default": paths.LIBRARY_DEFAULT,
            "custom": paths.LIBRARY_CUSTOM, "config": paths.LIBRARY_CONFIG,
            "ignored": paths.LIBRARY_IGNORED}


def _inside(child: str, parent: str) -> bool:
    c = os.path.normcase(os.path.abspath(child))
    p = os.path.normcase(os.path.abspath(parent))
    return c == p or c.startswith(p.rstrip(os.sep) + os.sep)


def set_library(path: str) -> dict:
    """把课程库定在 path（必须已存在）。下次启动生效，调用方负责提示重启。"""
    p = os.path.abspath(os.path.expanduser(str(path or "").strip()))
    if not str(path or "").strip():
        return {"ok": False, "error": "没有给文件夹"}
    if not os.path.isdir(p):
        return {"ok": False, "error": "这个文件夹不存在：%s" % p}
    st = _read_json(STATE, {})
    if not isinstance(st, dict):
        st = {}
    st.update({"library_root": p,
               "library_set": time.strftime("%Y-%m-%d %H:%M:%S")})
    # 用户自己选的库：不再算「自动挑的」，C 盘提醒也不用再问
    st.pop("library_auto", None)
    st.pop("library_off_c_declined", None)
    if not _write_state(st):
        return {"ok": False, "error": "写不进安装状态：%s" % STATE}
    return {"ok": True, "library": p}


def clear_library() -> dict:
    """恢复默认：库 = 程序目录。"""
    st = _read_json(STATE, {})
    if not isinstance(st, dict):
        st = {}
    st.pop("library_root", None)
    st.pop("library_auto", None)
    st["library_cleared"] = time.strftime("%Y-%m-%d %H:%M:%S")
    if not _write_state(st):
        return {"ok": False, "error": "写不进安装状态：%s" % STATE}
    return {"ok": True}


def declined_paths() -> list:
    raw = _read_json(STATE, {}).get("import_declined") or []
    return [os.path.abspath(x) for x in raw if isinstance(x, str) and x.strip()]


def decline(path: str) -> None:
    """用户点了「不用」：记住这个旧目录，下次启动不再拿它问。"""
    p = os.path.abspath(path)
    st = _read_json(STATE, {})
    if not isinstance(st, dict):
        st = {}
    keep = [x for x in (st.get("import_declined") or []) if isinstance(x, str)
            and os.path.normcase(x) != os.path.normcase(p)]
    keep.append(p)
    st["import_declined"] = keep[-20:]
    _write_state(st)


def has_user_data(root: str) -> bool:
    """这个目录里有没有用户课程数据（课程目录 / 导入记录）。"""
    return _has_user_data(root)


def off_c_declined() -> bool:
    """用户说过「先不用」挪库：下次启动不再拿 C 盘的事问他。"""
    return bool(_read_json(STATE, {}).get("library_off_c_declined"))


def decline_off_c() -> None:
    st = _read_json(STATE, {})
    if not isinstance(st, dict):
        st = {}
    st["library_off_c_declined"] = time.strftime("%Y-%m-%d %H:%M:%S")
    _write_state(st)


def pending_for(root: str) -> list:
    """首次启动「要不要导入」的候选。当前库已有用户数据、或用户明确拒绝过，就不再问。"""
    if os.environ.get("PLUMA_NO_IMPORT") == "1":
        return []
    root = os.path.abspath(root)
    if _has_user_data(root):
        return []
    no = {os.path.normcase(x) for x in declined_paths()}
    return [c for c in find_candidates(root) if os.path.normcase(c["path"]) not in no]


def _has_user_data(root: str) -> bool:
    return bool(course_dirs(root)) or os.path.isfile(os.path.join(root, "courses.local.json"))


def _looks_like_install(p: str) -> bool:
    if not os.path.isdir(p):
        return False
    if not (os.path.isfile(os.path.join(p, "ui", "server.py"))
            or os.path.isfile(os.path.join(p, "paths.py"))):
        return False
    return _has_user_data(p)


def find_candidates(current: str) -> list:
    """可能有旧课程的数据根，最近的排前面。"""
    current = os.path.abspath(current)
    seen, out = set(), []

    def add(p: str, why: str):
        p = os.path.abspath(p)
        if p == current or p in seen or not _looks_like_install(p):
            return
        seen.add(p)
        out.append({"path": p, "why": why,
                    "items": len(user_items(p)),
                    "mtime": max([os.path.getmtime(os.path.join(p, x)) for x in user_items(p)] or [0])})

    prev = _read_json(STATE, {}).get("last_data_root")
    if prev:
        add(prev, "install.json 记的上一次数据根")
    parent = os.path.dirname(current)
    try:
        for name in os.listdir(parent):
            if name.lower().startswith(("lapluma", "羽毛笔")) and ".bak-" not in name.lower():
                add(os.path.join(parent, name), "同级目录")
    except OSError:
        pass
    # 截图 / 判据里不该翻开发机自己的 Downloads、Desktop（会混进真实课程名）；
    #   只在这一档关掉，正常启动不设这个变量。
    if os.environ.get("PLUMA_NO_HOME_SCAN") != "1":
        for base in (os.path.join(HOME, "Downloads"), os.path.join(HOME, "Desktop")):
            try:
                for name in os.listdir(base):
                    if name.lower().startswith(("lapluma", "羽毛笔")) and ".bak-" not in name.lower():
                        add(os.path.join(base, name), os.path.basename(base))
            except OSError:
                pass
    out.sort(key=lambda x: (-x["items"], -x["mtime"]))
    return out


# ---------- 旧实例（卸载旧版被「正在占用」挡住时用） ----------
def listening_pluma() -> list:
    """8765-8775 上正在监听的 python/pythonw 进程。"""
    ps = (
        "$ports = 8765..8775; "
        "Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | "
        "Where-Object { $ports -contains $_.LocalPort } | "
        "Select-Object -Unique OwningProcess | ForEach-Object { "
        "  $p = Get-CimInstance Win32_Process -Filter ('ProcessId=' + $_.OwningProcess) "
        "  -ErrorAction SilentlyContinue; "
        "  if ($p -and $p.Name -match 'python') { [pscustomobject]@{ pid=$p.ProcessId; "
        "    port=$_.LocalPort; name=$p.Name; cmd=$p.CommandLine } } } | ConvertTo-Json -Compress"
    )
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                            "-Command", ps], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=20)
        txt = (r.stdout or "").strip()
        if not txt:
            return []
        data = json.loads(txt)
        return data if isinstance(data, list) else [data]
    except Exception:  # noqa: BLE001
        return []


def stop_old(kill: bool = False) -> int:
    rows = listening_pluma()
    if not rows:
        print("没有发现占用 8765-8775 的 Python 实例。")
        return 0
    for r in rows:
        print("PID %s · %s · 端口 %s" % (r.get("pid"), r.get("name"), r.get("port")))
        print("  %s" % (r.get("cmd") or ""))
    if not kill:
        print("\n只列出，没有结束。确认这些是旧版羽毛笔后加 --kill 再跑一次。")
        return 0
    for r in rows:
        pid = str(r.get("pid") or "")
        if pid.isdigit():
            subprocess.run(["taskkill", "/PID", pid, "/F"], capture_output=True)
            print("已结束 PID %s" % pid)
    time.sleep(1)
    left = listening_pluma()
    print("结束后仍在监听：%d 个" % len(left))
    return 0 if not left else 1


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    ap = argparse.ArgumentParser(description="羽毛笔升级：课程库位置 / 导入旧课程 / 关闭旧实例")
    ap.add_argument("--from", dest="src", default="", help="旧版目录")
    ap.add_argument("--to", dest="dst", default="", help="导入目标（默认当前课程库）")
    ap.add_argument("--list", action="store_true", help="列出可能含旧课程的目录")
    ap.add_argument("--where", action="store_true", help="显示当前课程库位置")
    ap.add_argument("--set-library", dest="lib", default="", help="把课程库定在这个文件夹（下次启动生效）")
    ap.add_argument("--clear-library", action="store_true", help="课程库恢复为程序目录")
    ap.add_argument("--dry-run", action="store_true", help="只看会复制什么，不写盘")
    ap.add_argument("--stop-old", action="store_true", help="列出占用端口的旧实例")
    ap.add_argument("--kill", action="store_true", help="配合 --stop-old：结束旧实例")
    a = ap.parse_args(argv)

    if a.stop_old:
        return stop_old(a.kill)
    if a.where:
        print(json.dumps(library_status(), ensure_ascii=False, indent=2))
        return 0
    if a.lib:
        res = set_library(a.lib)
        print(json.dumps(res, ensure_ascii=False, indent=2))
        if res.get("ok"):
            print("已记录。关闭软件重新打开后生效；课程留在原文件夹，不复制。")
        return 0 if res.get("ok") else 1
    if a.clear_library:
        res = clear_library()
        print(json.dumps(res, ensure_ascii=False, indent=2))
        if res.get("ok"):
            print("已恢复默认（课程库 = 程序目录）。关闭软件重新打开后生效。")
        return 0 if res.get("ok") else 1
    dst = os.path.abspath(a.dst) if a.dst else library_status()["root"]
    if a.list:
        cands = find_candidates(dst)
        no = {os.path.normcase(x) for x in declined_paths()}
        if not cands:
            print("没找到含用户数据的旧目录。")
            return 0
        for c in cands:
            mark = "（问过，用户选了不用）" if os.path.normcase(c["path"]) in no else ""
            print("%-60s  项目 %d  ·  %s%s" % (c["path"], c["items"], c["why"], mark))
        return 0
    if not a.src:
        ap.print_help()
        return 2
    rep = import_from(a.src, dst, dry_run=a.dry_run)
    print(json.dumps(rep, ensure_ascii=False, indent=2)[:4000])
    return 0 if rep.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
