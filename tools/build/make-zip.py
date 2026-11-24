# -*- coding: utf-8 -*-
"""从 git HEAD 造「文件夹版」发布包（v1.9.18）。

    python tools/build/make-zip.py --version 1.9.18 [--out dist/LaPluma-1.9.18.zip]

只打包进 Git 的文件：真课件、courses.local.json、_logs、_trash、out 都不会进去
（它们本来就在 .gitignore 里）。feed/latest.json 也从包里剔除——它是给更新检查读的，
由 make-feed.py 单独生成并提交；剔掉它，改清单不会改变发布包的 sha256。
"""
from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
import sys
import tempfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
EXCLUDE = {"feed/latest.json"}
NEED = ("ui/server.py", "一键启动.ps1", "启动羽毛笔.cmd", "paths.py", "upgrade.py")


def main(argv=None) -> int:
    for s in (sys.stdout, sys.stderr):
        if hasattr(s, "reconfigure"):
            s.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="造文件夹版发布包")
    ap.add_argument("--version", required=True)
    ap.add_argument("--out", default="")
    a = ap.parse_args(argv)
    ver = a.version.lstrip("vV")
    out = os.path.abspath(a.out or os.path.join(ROOT, "dist", "LaPluma-%s.zip" % ver))
    os.makedirs(os.path.dirname(out), exist_ok=True)
    tmp = tempfile.mktemp(suffix=".zip")
    r = subprocess.run(["git", "-C", ROOT, "archive", "--format=zip",
                        "-o", tmp, "HEAD"], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.returncode != 0:
        print("git archive 失败：%s" % (r.stderr or r.stdout), file=sys.stderr)
        return 2
    try:
        with zipfile.ZipFile(tmp) as zin, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
            for info in zin.infolist():
                if info.filename in EXCLUDE:
                    continue
                zout.writestr(info, zin.read(info.filename))
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass

    # 回查：版本、启动脚本、关键文件都在，用户数据一个都不在
    with zipfile.ZipFile(out) as z:
        names = set(z.namelist())
        bad = []
        for need in NEED:
            if need not in names:
                bad.append("缺 %s" % need)
        for deny in ("courses.local.json", "_logs/", "_trash/", "out/"):
            if any(n == deny or n.startswith(deny) for n in names):
                bad.append("混进用户数据 %s" % deny)
        if "feed/latest.json" in names:
            bad.append("feed/latest.json 应剔除（改清单不该改变发布包 sha256）")
        if bad:
            for b in bad:
                print("[红] " + b, file=sys.stderr)
            return 1
        txt = z.read("ui/server.py").decode("utf-8", "replace")
        if 'VERSION = "%s"' % ver not in txt:
            print("[红] 包里的 ui/server.py 版本不是 %s" % ver, file=sys.stderr)
            return 1
    data = open(out, "rb").read()
    print("已写 %s（%.1f MB，%d 个文件）" % (out, len(data) / 1048576, len(names)))
    print("  sha256 %s" % hashlib.sha256(data).hexdigest())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
