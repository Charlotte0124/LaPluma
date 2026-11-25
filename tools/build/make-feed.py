# -*- coding: utf-8 -*-
"""生成在线更新清单 feed/latest.json（2026-11-17 立；2026-11-24 改文件夹版）。

    python tools/build/make-feed.py --version 1.9.18 --app dist/LaPluma-1.9.18.zip
    python tools/build/make-feed.py --version 1.9.5  --exe dist/LaPluma.exe --res dist/LaPluma-res.zip

为什么要有这份清单：GitHub 的 Release API 只告诉你「有新版 + 页面地址」，
给不出「包多大、校验值是多少」——而没有这两样，应用内下载就不敢替用户换程序。
v1.9.15 起分发是文件夹压缩包：assets.app 是整包（解压后覆盖程序文件，用户数据不动），
assets.res 仍在位，留给以后只换文档/示例的资源包；assets.exe 只为旧版兼容保留。

发版流程（维护者）：
    python tools/build/make-zip.py --version 1.9.18     # 从 HEAD 造 dist/LaPluma-1.9.18.zip
    python tools/build/make-feed.py --version 1.9.18 --app dist/LaPluma-1.9.18.zip
    # 把 zip 传到 GitHub Release，提交 feed/latest.json —— 顺序不能反：
    # 清单里的 sha256 必须就是上传的那个 zip。

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
        s = t.lstrip("-* ").strip().replace("**", "").replace(chr(96), "")
        # 去掉「（用户：「…」）」这类引语：清单是给最终用户看的，不是开发记录
        s = re.sub(r"（用户：「[^」]*」）", "", s)
        s = re.split(r"[。；;]", s)[0][:100]
        if s:
            notes.append(s)
    return summary, notes[:6]


def asset_of(path: str, ver: str) -> dict:
    p = os.path.abspath(path)
    sha, size = sha256_of(p)
    return {"url": "https://github.com/%s/releases/download/v%s/%s" % (
                REPO, ver, os.path.basename(p)),
            "size": size, "sha256": sha, "name": os.path.basename(p)}


def main(argv: list | None = None) -> int:
    for s in (sys.stdout, sys.stderr):
        if hasattr(s, "reconfigure"):
            s.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="生成 feed/latest.json（在线更新清单）")
    ap.add_argument("--version", required=True, help="这次发布的版本，如 1.9.18")
    ap.add_argument("--app", default="", help="文件夹版整包 zip（v1.9.15 起的正常形态）")
    ap.add_argument("--exe", default="", help="旧单文件 exe（已退役，仅旧版兼容）")
    ap.add_argument("--res", default="", help="资源包路径（可选，如 dist/LaPluma-res.zip）")
    ap.add_argument("--out", default=os.path.join(ROOT, "feed", "latest.json"))
    ap.add_argument("--date", default=time.strftime("%Y-%m-%d"))
    a = ap.parse_args(argv)

    ver = a.version.lstrip("vV")
    if not (a.app or a.exe):
        print("至少给一个包：--app（文件夹版）或 --exe（旧单文件版）", file=sys.stderr)
        return 2
    assets = {}
    if a.app:
        if not os.path.isfile(a.app):
            print("找不到整包：%s" % a.app, file=sys.stderr)
            return 2
        assets["app"] = asset_of(a.app, ver)
    if a.exe:
        if not os.path.isfile(a.exe):
            print("找不到 exe：%s" % a.exe, file=sys.stderr)
            return 2
        assets["exe"] = asset_of(a.exe, ver)
    if a.res:
        if not os.path.isfile(a.res):
            print("找不到资源包：%s" % a.res, file=sys.stderr)
            return 2
        assets["res"] = asset_of(a.res, ver)

    # 2026-11-25 用户：更新推送要带「版本速览」图——图在 docs/版本速览/v<版本>-*.png，
    # 清单里给 raw 地址（跟 tag 绑定），应用内更新卡与本条正文都用它。找不到不拦发布，只说一句。
    image_rel = ""
    shot_dir = os.path.join(ROOT, "docs", "版本速览")
    if os.path.isdir(shot_dir):
        cands = sorted(n for n in os.listdir(shot_dir)
                       if n.startswith("v%s-" % ver) and n.lower().endswith(".png"))
        if cands:
            image_rel = "docs/版本速览/" + cands[0]
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
        "image": ("https://raw.githubusercontent.com/%s/v%s/%s" % (REPO, ver, image_rel)) if image_rel else "",
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
    assert back.get("latest") == ver
    assert all(v.get("size") for v in back["assets"].values())
    print("已写 %s（%d 字节）" % (a.out, os.path.getsize(a.out)))
    for k, v in assets.items():
        print("  %-4s %6.1f MB · sha256 %s… · %s"
              % (k, v["size"] / 1048576, v["sha256"][:12], v["name"]))
    print("  %d 条说明" % len(notes))
    if image_rel:
        print("  速览图 %s" % image_rel)
    else:
        print("  提醒：docs/版本速览 里没有 v%s-*.png（本轮更新卡不会带图）" % ver, file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
