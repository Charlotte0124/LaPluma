# -*- coding: utf-8 -*-
r"""check-readme-fresh.py — 主页（README）的版本与图不许比最新发布旧（2026-11-26）

为什么有这条：用户 2026-11-26 看主页发现「图和文字一直没有更新」——下载按钮与版本
徽章停在 v1.9.17，Release 已经到 v1.9.24；主页顶上的介绍图还是 2026-11-17 的。
根因不是忘了改，是**没有任何东西会红**：sync-readme.py 只管「最近更新」表，
版本徽章是手写的，它的 --check 也从没接进钩子或 CI。

判据（红 = 主页与最新版对不上；黄 = 图旧了，要重拍）：
    R1 红：下载按钮（链接与文字）/ version 徽章 的版本 != feed/latest.json 的 latest
    R2 红：「最近更新」表与 CHANGELOG 不一致（交给 tools/sync-readme.py --check 判）
    Y1 黄：README 引用的 docs\资产\*.png 比 ui\ 最后一次提交旧 —— 主页还在用旧界面图

修法：python tools\sync-readme.py（R1/R2 自动改好；Y1 要重拍真实截图）

用法：python tools\check\check-readme-fresh.py
退出码：0 绿（或只有黄）· 1 红
"""
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
README = os.path.join(ROOT, "README.md")
FEED = os.path.join(ROOT, "feed", "latest.json")


def git(*args):
    p = subprocess.run(["git", "-c", "core.quotepath=false", "-C", ROOT] + list(args),
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return p.returncode, (p.stdout or "").strip()


def last_ts(path):
    rc, out = git("log", "-1", "--format=%ct", "--", path)
    return int(out) if rc == 0 and out.isdigit() else None


def main() -> int:
    red, yel = [], []
    ver = ""
    try:
        ver = str(json.load(open(FEED, encoding="utf-8")).get("latest") or "")
    except Exception as e:  # noqa: BLE001
        red.append("读不到 feed\\latest.json：%s" % e)
    src = open(README, encoding="utf-8").read()

    # R1 下载按钮 + 版本徽章
    m_link = re.search(r"releases/download/v([\d.]+)/LaPluma-([\d.]+)\.zip", src)
    m_btn = re.search(u"⬇_下载_v([\\d.]+)-", src)
    m_badge = re.search(r"badge/version-([\d.]+)-", src)
    for label, m in ((u"下载链接", m_link),
                     (u"下载按钮文字", m_btn),
                     (u"version 徽章", m_badge)):
        if not m:
            red.append(u"R1 README 里找不到%s的版本号（格式变了？）" % label)
            continue
        if ver and m.group(1) != ver:
            red.append(u"R1 %s 写的是 v%s，最新是 v%s" % (label, m.group(1), ver))
    if m_link and m_link.group(1) != m_link.group(2):
        red.append(u"R1 下载链接里 tag 与文件名版本不一致：v%s / %s"
                   % (m_link.group(1), m_link.group(2)))

    # R2 最近更新表
    sync = os.path.join(ROOT, "tools", "sync-readme.py")
    p = subprocess.run([sys.executable, "-X", "utf8", sync, "--check"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    if p.returncode != 0:
        red.append(u"R2 最近更新表与 CHANGELOG/feed 不一致：跑 python tools\\sync-readme.py")

    # Y1 主页用图跟着 ui 走
    t_ui = last_ts("ui")
    # 只算「界面截图」与主页介绍图：图标这类不随界面变的，不逼着重画
    imgs = sorted(set(name for name in re.findall(r'docs/资产/([^")\s]+\.png)', src)
                      if name.startswith(u"界面-") or name.startswith(u"产品介绍图")))
    stale = []
    for name in imgs:
        t = last_ts(u"docs/资产/" + name)
        if t and t_ui and t < t_ui:
            stale.append(name)
    if stale:
        yel.append(u"Y1 主页有 %d 张图比 ui\\ 旧（%s%s）：重拍一张放 docs\\资产"
                   % (len(stale), u"、".join(stale[:4]),
                      u" 等" if len(stale) > 4 else ""))

    for x in red:
        print(u"[红] " + x)
    for x in yel:
        print(u"[黄] " + x)
    print(u"主页版本 v%s · 引用图 %d 张 · 结论：%d 红 · %d 黄"
          % (ver or "?", len(imgs), len(red), len(yel)))
    return 1 if red else 0


if __name__ == "__main__":
    raise SystemExit(main())
