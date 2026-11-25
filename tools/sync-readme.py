# -*- coding: utf-8 -*-
"""从 CHANGELOG 生成 README 的「最近更新」表（只改标记之间的内容）。

    python tools\\sync-readme.py            # 写回 README
    python tools\\sync-readme.py --check    # 只比对，不一致退出 1

为什么要有它：主页上的版本表靠人记得改，迟早会旧。让它生成，`--check` 放进推送前检查。
"""
from __future__ import annotations

import io
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import paths  # noqa: E402  路径双根：CHANGELOG / README 属于随程序发布的东西（资源根）
ROOT = paths.RES_ROOT
CHANGELOG = os.path.join(ROOT, "CHANGELOG.md")
README = os.path.join(ROOT, "README.md")
FEED = os.path.join(ROOT, "feed", "latest.json")
BEGIN = "<!-- 最近更新:begin（由 tools/sync-readme.py 生成，别手改） -->"
END = "<!-- 最近更新:end -->"
LIMIT = 5        # 只列最近 5 个版本；更早的指向 CHANGELOG（用户 2026-11-17 定）


def pick_rows(rows):
    return rows if not LIMIT else rows[:LIMIT]


def brief(items: list[str]) -> str:
    """从一版的条目里抽出「用户看得到的改动」：只取粗体功能名，去掉括号注，最多 4 个。

    表是给用户看的，技术细节（类名撞车、根因、接口参数）一概不进来。
    """
    words = []
    for it in items:
        m = re.match(r"\*\*([^*]+)\*\*", it)
        if not m:
            continue
        w = re.sub(r"（[^）]*）", "", m.group(1)).strip().rstrip("：:· ")
        if w and w not in words:
            words.append(w)
        if len(words) >= 4:
            break
    if not words:
        return (items[0][:40] if items else "").rstrip("…")
    s = " · ".join(words)
    return s + (" 等" if len(words) < len(items) else "")


def parse(path: str) -> list[tuple[str, str, str]]:
    """读出每个版本：版号、日期、给用户看的摘要。

    摘要优先取 `<!-- 摘要：… -->`（手写、用户视角）；没写的版本才回退到从粗体功能名里凑。
    """
    rows = []
    cur = None
    for line in io.open(path, encoding="utf-8"):
        t = line.strip()
        m = re.match(r"^##\s+(v[\d.]+)\s*·\s*(\d{4}-\d{2}-\d{2})\s*$", t)
        if m:
            cur = [m.group(1), m.group(2), [], ""]
            rows.append(cur)
            continue
        if not cur:
            continue
        mb = re.match(r"^<!--\s*摘要[:：]\s*(.+?)\s*-->$", t)
        if mb and not cur[3]:
            cur[3] = mb.group(1)
            continue
        if t.startswith("- "):
            cur[2].append(t[2:].strip())
    return [(v, d, b or brief(items)) for v, d, items, b in rows]


def render(rows) -> str:
    head = "| 版本 | 日期 | 这一版做了什么 |\n|:--|:--|:--|"
    shown = pick_rows(rows)
    body = "\n".join("| **%s** | %s | %s |" % (v, d[5:], t) for v, d, t in shown)
    if len(shown) < len(rows):
        body += "\n| — | — | 更早的 %d 个版本 → [CHANGELOG](CHANGELOG.md) |" % (len(rows) - len(shown))
    return BEGIN + "\n" + head + "\n" + body + "\n" + END


def feed_version() -> str:
    """最新版本只认 feed/latest.json 一个来源（应用内更新读的也是它）。"""
    try:
        return str(json.load(io.open(FEED, encoding="utf-8")).get("latest") or "")
    except Exception:  # noqa: BLE001
        return ""


def sync_head(src: str, ver: str) -> str:
    """把顶部「下载」按钮与版本徽章钉到 feed 的版本（2026-11-26）。

    为什么补这段：用户 2026-11-26 看主页发现图与文字一直没更新——下载按钮与徽章停在
    v1.9.17，Release 已到 v1.9.24。根因是这两处以前手写、没有任何东西会红。
    """
    if not ver:
        return src
    src = re.sub(r"releases/download/v[\d.]+/LaPluma-[\d.]+\.zip",
                 "releases/download/v%s/LaPluma-%s.zip" % (ver, ver), src)
    src = re.sub(u"⬇_下载_v[\\d.]+", u"⬇_下载_v" + ver, src)
    src = re.sub(r"badge/version-[\d.]+", "badge/version-" + ver, src)
    return src


def main(argv: list[str]) -> int:
    rows = parse(CHANGELOG)
    if not rows:
        print("CHANGELOG 里没有符合 `## vX.Y.Z · YYYY-MM-DD` 的条目")
        return 2
    block = render(rows)
    src = io.open(README, encoding="utf-8").read()
    if BEGIN not in src or END not in src:
        print("README 里缺标记：%s / %s" % (BEGIN, END))
        return 2
    # 2026-11-17 修：原来直接拿 block 当替换串，block 里的反斜杠（如 tools\print\pdfjs）
    #   会被当成转义序列，re 直接报 bad escape \p。用函数替换就不做转义解析了。
    new = re.sub(re.escape(BEGIN) + r".*?" + re.escape(END), lambda _m: block, src, flags=re.S)
    ver = feed_version()
    new = sync_head(new, ver)
    if "--check" in argv:
        if new != src:
            print("最近更新表与 CHANGELOG 不一致：跑 python tools\\sync-readme.py")
            return 1
        print("最近更新表一致（%d 版里列了 %d 版）" % (len(rows), len(pick_rows(rows))))
        return 0
    io.open(README, "w", encoding="utf-8").write(new)
    print("已写回 README（%d 版里列了 %d 版）" % (len(rows), len(pick_rows(rows))))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
