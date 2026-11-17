# -*- coding: utf-8 -*-
"""判据：图注 / 表号编号连续、正文引用都落地（2026-11-17，优化项 L1）

    python tools\\check\\check-figref.py              # 查（0 绿 / 1 红 / 2 没查成）
    python tools\\check\\check-figref.py -SelfTest    # 造坏自测（4 例）

为什么要有：借 quarto 的「自动编号 + 交叉引用」——引擎现在会给图自动加「图 N · 」前缀
（`engine\\_build_讲义.py` 的 `number_figures()`），但「编号有没有断号、正文里引的图存不存在、
图注写好了却没人引用」这三件事没人查，写错了读者就找不到图。

查四项（对每门课 `06_笔记\\*_源.html`）：
  1 每个图注都有编号（`图 N` 开头；引擎自动加，手写也算）
  2 编号从 1 连续、不重复
  3 正文里出现的「图 N」必须在编号集合里（引到不存在的图 → 红）
  4 有编号却全文没有一处引用 → 黄（读者找不到它在讲哪张图）
  某份讲义一张图都没有 → 记「不适用」并说出来（跳过 ≠ 通过）

退出码：0 全绿 / 1 有红 / 2 没查成（找不到源文件）。
"""
from __future__ import annotations

import glob
import os
import re
import sys
import tempfile

try:
    sys.stdout.reconfigure(line_buffering=True)
except Exception:  # noqa: BLE001
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
CAP = re.compile(r"<figcaption[^>]*>(.*?)</figcaption>", re.S)
NUM = re.compile(r"^\s*[图表]\s*(\d+)")
REF = re.compile(r"[图表]\s*(\d+)")
TAB = re.compile(r"[图表]\s*(\d+)")


def analyse(html: str) -> dict:
    """返回 {caps, nums, refs, bad_cap, broken, unused}。纯函数，自测直接喂字符串。"""
    caps = [c.strip() for c in CAP.findall(html)]
    nums, bad_cap = [], []
    for c in caps:
        m = NUM.match(c)
        if not m:
            bad_cap.append(c[:40])
        else:
            nums.append(int(m.group(1)))
    # 正文引用：先剥掉图注自身，再去标签
    body = re.sub(r"<figcaption[^>]*>.*?</figcaption>", " ", html, flags=re.S)
    body = re.sub(r"<[^>]+>", " ", body)
    refs = sorted({int(x) for x in REF.findall(body)})
    broken = sorted(set(refs) - set(nums))
    unused = sorted(set(nums) - set(refs)) if refs else sorted(set(nums))
    return {"caps": caps, "nums": nums, "refs": refs, "bad_cap": bad_cap,
            "broken": broken, "unused": unused}


def check_one(path: str) -> dict:
    html = open(path, encoding="utf-8").read()
    r = analyse(html)
    reds, yels = [], []
    if not r["caps"]:
        return {"path": path, "state": "skip", "reds": [], "yels": [], "info": r}
    if r["bad_cap"]:
        reds.append("图注没编号：" + "、".join(r["bad_cap"][:3]))
    nums = r["nums"]
    if nums and sorted(nums) != list(range(1, max(nums) + 1)):
        reds.append("图编号不连续或重复：%s" % nums)
    if r["broken"]:
        reds.append("正文引了不存在的图：%s" % r["broken"])
    if nums and not r["refs"]:
        yels.append("有 %d 张图但正文一处引用都没有（读者找不到它在讲哪张）" % len(nums))
    state = "red" if reds else ("yellow" if yels else "ok")
    return {"path": path, "state": state, "reds": reds, "yels": yels, "info": r}


def collect() -> list:
    """找各门课的讲义源；回收站 / 归档 / 合订本不算。

    合订本（`*_合订本_源.html`）是按讲拼接的，每讲自己从「图 1」数——册内重号是设计如此，
    不在这条判据里管（真要全册连续得重映射正文引用，风险大于收益）。
    """
    out = []
    for pat in (os.path.join(ROOT, "*", "06_笔记", "*_源.html"),
                os.path.join(ROOT, "**", "06_笔记", "*_源.html")):
        out.extend(glob.glob(pat, recursive=True))
    keep = []
    for p in sorted(set(out)):
        rel = os.path.relpath(p, ROOT)
        if "_trash" in rel or "_归档" in rel or "合订本" in rel:
            continue
        keep.append(p)
    return keep


def run(paths: list) -> tuple:
    red = yel = ok = skip = 0
    for p in paths:
        r = check_one(p)
        tag = os.path.relpath(p, ROOT)
        if r["state"] == "skip":
            skip += 1
            print("  [不适用] %s：这一讲没有图" % tag)
        elif r["state"] == "red":
            red += 1
            print("  [红] %s：%s" % (tag, "；".join(r["reds"])))
        elif r["state"] == "yellow":
            yel += 1
            print("  [黄] %s：%s" % (tag, "；".join(r["yels"])))
        else:
            ok += 1
            i = r["info"]
            print("  [绿] %s：图 %d 张（编号 1–%d）· 正文引用 %d 处"
                  % (tag, len(i["nums"]), max(i["nums"]), len(i["refs"])))
    print("查了 %d 份 / 绿 %d · 黄 %d · 红 %d · 不适用 %d（不适用＝这一讲没图，不算通过）"
          % (len(paths), ok, yel, red, skip))
    return red, yel, ok, skip


def selftest() -> int:
    print("===== 图注编号 · 造坏自测 =====")
    base = '<p>正文：见图 1 与图 2。</p>'
    good = (base + '<figure><img src="a.png"><figcaption>图 1 · 流程图</figcaption></figure>'
                   '<figure><img src="b.png"><figcaption>图 2 · 调用栈</figcaption></figure>')
    cases = [
        ("好样本应通过", good, "ok"),
        ("图注没编号", '<figure><figcaption>流程图</figcaption></figure>', "red"),
        ("编号断号", '<figure><figcaption>图 1 · a</figcaption></figure>'
                    '<figure><figcaption>图 3 · b</figcaption></figure>', "red"),
        ("引了不存在的图", '<figure><figcaption>图 1 · a</figcaption></figure><p>见图 2。</p>', "red"),
        ("有图无引用", '<figure><figcaption>图 1 · a</figcaption></figure>', "yellow"),
    ]
    bad = 0
    for name, html, want in cases:
        r = analyse(html)
        reds = []
        if r["bad_cap"]:
            reds.append("图注没编号")
        if r["nums"] and sorted(r["nums"]) != list(range(1, max(r["nums"]) + 1)):
            reds.append("编号不连续")
        if r["broken"]:
            reds.append("引用不存在")
        got = "red" if reds else ("yellow" if (r["nums"] and not r["refs"]) else "ok")
        if got == want:
            print("  过  %s → %s" % (name, got))
        else:
            print("  红  %s → 期望 %s，实得 %s" % (name, want, got))
            bad += 1
    print("===== 自测结论：%s =====" % ("全过（%d 例）" % len(cases) if not bad else "%d 例没抓到" % bad))
    return 0 if not bad else 1


def main() -> int:
    if "-SelfTest" in sys.argv or "--selftest" in sys.argv:
        return selftest()
    print("===== 图注 / 表号编号与引用（L1） =====")
    paths = collect()
    if not paths:
        print("  [黄] 没找到任何 06_笔记\\*_源.html，没查")
        return 2
    red, yel, ok, skip = run(paths)
    if red:
        print("\n结论：%d 份红" % red)
        return 1
    print("\n结论：0 红（黄 %d · 不适用 %d）" % (yel, skip))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
