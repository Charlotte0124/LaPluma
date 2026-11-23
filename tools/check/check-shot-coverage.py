# -*- coding: utf-8 -*-
r"""截图覆盖检查（2026-11-23 用户定）。

为什么有这条：用户原话「以后检测有新功能 截图的那边就要增加一个空位留补 等推送的时候再截图」。
只靠记得，新功能就会悄悄没图——图库（控制台 docs\资产）看着正常，缺的那条没人知道。
所以把「功能总表 ↔ 截图覆盖登记表 ↔ docs\资产 里真有这张图」三边对上：

  红 1  功能总表里已实现/部分实现的功能，截图覆盖表里没有登记（连「待补」都没有）
  红 2  登记为已拍的截图，docs\资产 里没有这个文件
  红 3  「待补」行没写原因（留空位可以，但要说清为什么先空着）

判据自己会红：--selftest 造三种坏，三种都必须报红才算可信。

    python tools\check\check-shot-coverage.py
    python tools\check\check-shot-coverage.py --selftest
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TABLE = os.path.join(ROOT, "docs", "功能总表.md")
COVER = os.path.join(ROOT, "docs", "资产", "截图覆盖.md")
ASSETS = os.path.join(ROOT, "docs", "资产")

FEATURE_RE = re.compile(r"^\|\s*(L\d+[a-z]?)\s*\|\s*([^|]+?)\s*\|.*\|\s*([✅🟡❌⬜])")
ROW_RE = re.compile(r"^\|\s*(L\d+[a-z]?)(?!\w)")


def features(table_path: str) -> dict:
    out = {}
    for line in open(table_path, encoding="utf-8"):
        m = FEATURE_RE.match(line)
        if m:
            out[m.group(1)] = {"name": m.group(2).strip(), "status": m.group(3)}
    return out


def coverage(cover_path: str) -> dict:
    """返回 {Lxx: {"section": "已拍"|"待补", "shot": str, "reason": str}}。"""
    out = {}
    section = "已拍"
    for line in open(cover_path, encoding="utf-8"):
        s = line.strip()
        if s.startswith("## "):
            section = "待补" if "待补" in s else ("未实现" if "未实现" in s else "已拍")
            continue
        m = ROW_RE.match(s)
        if not m:
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        lid = m.group(1)
        out[lid] = {"section": section,
                    "shot": cells[1] if len(cells) > 1 else "",
                    "reason": cells[2] if len(cells) > 2 else "",
                    "raw": s}
    return out


def audit(root: str) -> tuple:
    table = os.path.join(root, "docs", "功能总表.md")
    cover = os.path.join(root, "docs", "资产", "截图覆盖.md")
    assets = os.path.join(root, "docs", "资产")
    errs = []
    if not os.path.isfile(table):
        return [], ["没有 docs/功能总表.md"]
    if not os.path.isfile(cover):
        return [], ["没有 docs/资产/截图覆盖.md（新功能没有地方留空位）"]
    feats = features(table)
    cov = coverage(cover)
    need = [k for k, v in feats.items() if v["status"] in ("✅", "🟡")]
    shot_n = wait_n = 0
    for lid in need:
        row = cov.get(lid)
        if not row:
            errs.append("%s %s 已实现，但截图覆盖表没登记（连「待补」都没有）" % (lid, feats[lid]["name"]))
            continue
        if row["section"] == "待补" or "待补" in row["shot"]:
            if not row["reason"] or row["reason"].startswith("为什么"):
                errs.append("%s 标了待补但没写原因（推送前要补图）" % lid)
            wait_n += 1
            continue
        shot = row["shot"]
        if not shot or not re.search(r"\.png$", shot, re.I):
            errs.append("%s 登记行里没写 PNG 文件名：%r" % (lid, row["raw"]))
            continue
        if not os.path.isfile(os.path.join(assets, shot)):
            errs.append("%s 登记了 %s，但 docs/资产 里没有这个文件" % (lid, shot))
            continue
        shot_n += 1
    # 反向：登记表里引用了不存在的图（不管那条功能是否已实现）
    for lid, row in cov.items():
        if row["section"] == "已拍" and re.search(r"\.png$", row["shot"], re.I):
            if not os.path.isfile(os.path.join(assets, row["shot"])):
                msg = "%s 引用了不存在的图 %s" % (lid, row["shot"])
                if msg not in errs:
                    errs.append(msg)
    return (len(need), shot_n, wait_n), errs


def selftest() -> int:
    """造三种坏，三种都必须报红；再造一份对的，必须绿。"""
    tmp = tempfile.mkdtemp(prefix="shotcov-")
    cases = []

    def build(table_rows, cover_text, pngs=("界面-主页.png",)):
        root = os.path.join(tmp, "c%d" % len(cases))
        os.makedirs(os.path.join(root, "docs", "资产"))
        with open(os.path.join(root, "docs", "功能总表.md"), "w", encoding="utf-8") as f:
            f.write("# 功能\n\n| 编号 | 名称 | 说明 | 状态 | 证据 |\n|---|---|---|---|---|\n")
            for lid, name, st in table_rows:
                f.write("| %s | %s | x | %s | x |\n" % (lid, name, st))
        with open(os.path.join(root, "docs", "资产", "截图覆盖.md"), "w", encoding="utf-8") as f:
            f.write(cover_text)
        for p in pngs:
            open(os.path.join(root, "docs", "资产", p), "wb").write(b"x")
        return root

    good_cover = ("# 覆盖\n\n## 已拍\n\n| 功能 | 截图 | 拍于 |\n|:--|:--|:--|\n"
                  "| L01 浏览 | 界面-主页.png | 2026-11-23 |\n")
    r = build([("L01", "浏览", "✅"), ("L02", "收藏", "❌")], good_cover)
    cases.append(("绿：已实现都有图", r, 0))

    r = build([("L01", "浏览", "✅"), ("L02", "收藏", "✅")], good_cover)
    cases.append(("红：新功能没登记", r, 1))

    r = build([("L01", "浏览", "✅")],
              "# 覆盖\n\n## 已拍\n\n| 功能 | 截图 | 拍于 |\n|:--|:--|:--|\n| L01 浏览 | 缺失.png | 2026-11-23 |\n")
    cases.append(("红：登记了不存在的图", r, 1))

    r = build([("L01", "浏览", "✅")],
              "# 覆盖\n\n## 待补\n\n| 功能 | 状态 | 原因 |\n|:--|:--|:--|\n| L01 浏览 | 待补 · 推送前 |  |\n")
    cases.append(("红：待补没写原因", r, 1))

    r = build([("L01", "浏览", "✅")],
              "# 覆盖\n\n## 待补\n\n| 功能 | 状态 | 原因 |\n|:--|:--|:--|\n| L01 浏览 | 待补 · 推送前 | 要真跑一次模型 |\n")
    cases.append(("绿：待补写了原因", r, 0))

    bad = 0
    for label, root, expect in cases:
        _, errs = audit(root)
        got = 1 if errs else 0
        ok = got == expect
        if not ok:
            bad += 1
        print("%s  %s（期望%s，实际%s）" % ("[ok]" if ok else "[坏]", label,
                                          "红" if expect else "绿", "红" if got else "绿"))
    shutil.rmtree(tmp, ignore_errors=True)
    print("selftest：%d 项，%d 项不符" % (len(cases), bad))
    return 1 if bad else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        return selftest()
    counts, errs = audit(ROOT)
    for e in errs:
        print("[红] " + e)
    if counts:
        need, shot_n, wait_n = counts
        print("功能 %d 条：已拍 %d · 待补 %d · 缺登记 %d"
              % (need, shot_n, wait_n, len([e for e in errs if "没登记" in e])))
    print("结论：%s" % ("红 %d" % len(errs) if errs else "全绿"))
    return 1 if errs else 0


if __name__ == "__main__":
    raise SystemExit(main())
