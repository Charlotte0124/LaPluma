# -*- coding: utf-8 -*-
"""生成在线更新清单 feed\\latest.json（2026-11-17 用户：「不跳 GitHub，一步下完」）。

    python tools\\build\\make-feed.py --version 1.9.5 --exe dist\\LaPluma.exe
    python tools\\build\\make-feed.py --version 1.9.6 --exe dist\\LaPluma.exe --res dist\\LaPluma-res.zip

为什么要自己发一份清单：GitHub 的 Release API 只告诉你「有新版 + 页面地址」，
给不出「包多大、校验值是多少」——而没有这两样，应用内下载就不敢替用户换程序。
清单里同时放 exe 与资源包（assets.exe / assets.res），以后资源包单独更新时，
用户只下几 MB 的 res，不必重下 114 MB 的 exe。

清单随仓库发布，应用按 raw → jsDelivr 两个源依次取（见 ui\\server.py 的 FEED_URLS）。
摘要与条目直接从 CHANGELOG.md 的 `## vX.Y.Z` 小节抽，不另写一份（一份事实只存一处）。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
REPO = "Charlotte0124/LaPluma"


def sha256_of(path: str) -> tuple:
    h = hashlib.sha256()
    n = 0
    with open(path, "rb") as f:
        while True:
            b = f.read(1 << 20)
            if not b:
                break
            h.update(b)
            n += len(b)
    return h.hexdigest(), n


def section(version: str) -> tuple:
    """从 CHANGELOG 抽 (摘要, 条目列表)；找不到就回空。"""
    p = os.path.join(ROOT, "CHANGELOG.md")
    if not os.path.isfile(p):
        return "", []
    txt = open(p, encoding="utf-8").read()
    m = re.search(r"^## v%s\b.*?$(.*?)(?=^## v|\Z)" % re.escape(version), txt, re.S | re.M)
    if not m:
        return "", []
    body = m.group(1)
    summary = ""
    ms = re.search(r"<!--\s*摘要[:：]\s*(.*?)\s*-->", body, re.S)
    if ms:
        summary = " ".join(ms.group(1).split())
    notes = []
    for ln in body.splitlines():
        t = ln.strip()
        if not t.startswith(("-", "*")):
            continue
        s = re.sub(r"\*\*|`", "", t.lstrip("-* ").strip())
        # 去掉「（用户：「…」）」这类引语：清单是给最终用户看的，不是开发记录
        s = re.sub(r"（用户：「[^」]*」）", "", s)
        s = re.split(r"[。；;]", s)[0][:100]
        if s:
            notes.append(s)
    return summary, notes[:6]


def main(argv: list | None = None) -> int:
    for s in (sys.stdout, sys.stderr):
        if hasattr(s, "reconfigure"):
            s.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="生成 feed/latest.json（在线更新清单）")
    ap.add_argument("--version", required=True, help="这次发布的版本，如 1.9.5")
    ap.add_argument("--exe", required=True, help="exe 路径，如 dist\\LaPluma.exe")
    ap.add_argument("--res", default="", help="资源包路径（可选，如 dist\\LaPluma-res.zip）")
    ap.add_argument("--out", default=os.path.join(ROOT, "feed", "latest.json"))
    ap.add_argument("--date", default=time.strftime("%Y-%m-%d"))
    a = ap.parse_args(argv)

    ver = a.version.lstrip("vV")
    exe = os.path.abspath(a.exe)
    if not os.path.isfile(exe):
        print("找不到 exe：%s" % exe, file=sys.stderr)
        return 2
    sha, size = sha256_of(exe)
    assets = {"exe": {
        "url": "https://github.com/%s/releases/download/v%s/%s" % (
            REPO, ver, os.path.basename(exe)),
        "size": size, "sha256": sha, "name": os.path.basename(exe)}}
    if a.res:
        rp = os.path.abspath(a.res)
        if not os.path.isfile(rp):
            print("找不到资源包：%s" % rp, file=sys.stderr)
            return 2
        rsha, rsize = sha256_of(rp)
        assets["res"] = {
            "url": "https://github.com/%s/releases/download/v%s/%s" % (
                REPO, ver, os.path.basename(rp)),
            "size": rsize, "sha256": rsha, "name": os.path.basename(rp)}

    summary, notes = section(ver)
    if not summary:
        print("提醒：CHANGELOG 里没有 v%s 的「<!-- 摘要：… -->」，清单会缺一句摘要" % ver,
              file=sys.stderr)
    feed = {
        "schema": "lapluma-feed-v1",
        "product": "LaPluma",
        "latest": ver,
        "title": "v%s · %s" % (ver, summary.split("；")[0][:28] if summary else ""),
        "released": a.date,
        "summary": summary or "这一版改了什么，见更新日志。",
        "notes": notes,
        "page": "https://github.com/%s/releases/tag/v%s" % (REPO, ver),
        "assets": assets,
        "_generated": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(feed, f, ensure_ascii=False, indent=2)
        f.write("\n")
    # 写完回查：文件要真在、真能读回
    back = json.load(open(a.out, encoding="utf-8"))
    assert back.get("latest") == ver and back["assets"]["exe"]["size"] == size
    print("已写 %s（%d 字节）" % (a.out, os.path.getsize(a.out)))
    print("  版本 %s · exe %.1f MB · sha256 %s… · %d 条说明"
          % (ver, size / 1048576, sha[:12], len(notes)))
    if a.res:
        print("  资源包 %.1f MB" % (assets["res"]["size"] / 1048576))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
