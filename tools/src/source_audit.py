# -*- coding: utf-8 -*-
"""source_audit.py · 源门：判「来源清单」够不够格当论据（多源讲义生产的门一）

为什么要有它：`audit_lesson.py` 只管版式（底色、页脚、页码引用），一份白底、无出处、
凭记忆写的讲义照样能「通过」。讲义一旦不吃 PDF、改吃关键词 / 论文 / 视频 / GitHub，
「原文为基」的物理前提就没了，必须有人判「这条事实的出处站不站得住」。

判据（红 = 挡提交，黄 = 记一笔）
    红 · 清单不存在 / 解析不出 S1·S2·S3 任何一节
    红 · S1 条数为 0（定义、公式、数字只许用 S1）
    红 · 某条缺定位（URL / DOI / arXiv 编号）
    红 · 某条缺访问日期（YYYY-MM-DD）
    红 · S1 的「原文关键句」不是照抄（没加引号）
    黄 · 状态列写「未核」的条数（允许存在，但不许进正文当论据）

不做的事（明说「没查」，不当通过）
    · 不判「S3 是否被写进定义段」——那要读正文，本脚本只读清单
    · 不判 URL 是否真的能打开（联网不可靠，会假绿）；只判「写了没有」

用法
    python tools\\src\\source_audit.py                    # 扫 _drafts\\*_sources.md
    python tools\\src\\source_audit.py --file <清单.md>    # 指定一份
    python tools\\src\\source_audit.py --json             # JSONL，给闸门用
退出码：有红 → 1；只有黄或全绿 → 0；找不到清单 → 2
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SECT = re.compile(r"^##\s*(S1|S2|S3)\b")
HEAD_SECT = re.compile(r"^#{1,6}\s")
LOC_RE = re.compile(r"arXiv:\s*\d{4}\.\d{4,5}|arxiv\.org/abs/|doi\.org/|10\.\d{4,}/\S+|https?://\S+",
                    re.I)
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
QUOTE_RE = re.compile(r"^[\"'“「]")


def parse_tables(text: str) -> dict[str, list[dict]]:
    """按 ## S1 / ## S2 / ## S3 分节，抽出每节的表格行（列名 → 值）。"""
    out: dict[str, list[dict]] = {}
    cur = None
    header: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if HEAD_SECT.match(line):
            m = SECT.match(line)
            cur = m.group(1) if m else None
            header = []
            continue
        if cur is None or not line.startswith("|"):
            if line and not line.startswith("|"):
                header = [] if not line.startswith("<") else header
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if all(set(c) <= set("-: ") for c in cells):      # 分隔行
            continue
        if not header:
            header = cells
            continue
        out.setdefault(cur, []).append(dict(zip(header, cells)))
    return out


def audit(path: str) -> dict:
    text = open(path, encoding="utf-8", errors="replace").read()
    try:
        rel = os.path.relpath(path, ROOT).replace("\\", "/")
    except ValueError:            # 演练用临时文件在别的盘上
        rel = path.replace("\\", "/")
    fails: list[str] = []
    warns: list[str] = []
    secs = parse_tables(text)
    n = {k: len(v) for k, v in secs.items()}
    if not secs:
        fails.append("解析不出 S1/S2/S3 任何一节（清单结构不对）")
    if n.get("S1", 0) == 0:
        fails.append("S1 条数为 0（定义/公式/数字必须有一手源）")

    for level, rows in secs.items():
        last_loc = last_acc = ""          # 「同上」继承上一行，别把它判成缺定位
        for i, row in enumerate(rows, 1):
            tag = row.get("#") or f"{level}-{i}"
            loc = row.get("定位", "") or ""
            acc = row.get("访问", "") or ""
            if "同上" in loc:
                loc = last_loc
            else:
                last_loc = loc
            if "同上" in acc:
                acc = last_acc
            else:
                last_acc = acc
            status = row.get("状态", "")
            if not LOC_RE.search(loc):
                fails.append(f"{tag} 缺定位（URL / DOI / arXiv 编号）：「{loc[:40] or '空'}」")
            if not DATE_RE.search(acc):
                fails.append(f"{tag} 缺访问日期（YYYY-MM-DD）：「{acc[:30] or '空'}」")
            if status and "未核" in status:
                warns.append(f"{tag} 标「未核」，不得进正文当论据")
            if level == "S1":
                quote = (row.get("原文关键句（照抄）") or row.get("关键句") or "").strip()
                if quote and not QUOTE_RE.match(quote):
                    warns.append(f"{tag} 关键句没加引号，看不出是照抄还是转述")
    return {"file": rel, "s1": n.get("S1", 0), "s2": n.get("S2", 0), "s3": n.get("S3", 0),
            "fails": fails, "warns": warns,
            "status": "FAIL" if fails else ("WARN" if warns else "OK")}


def main() -> int:
    for s in (sys.stdout, sys.stderr):
        if hasattr(s, "reconfigure"):
            s.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="源门：来源清单够不够格")
    ap.add_argument("--file", nargs="+", help="指定清单路径")
    ap.add_argument("--json", action="store_true", help="JSONL 输出")
    a = ap.parse_args()

    targets = ([os.path.abspath(f) for f in a.file] if a.file
               else sorted(glob.glob(os.path.join(ROOT, "_drafts", "*_sources.md"))))
    if not targets:
        print("没有可检查的来源清单（_drafts\\*_sources.md）。"
              "这是「没查」，不是「通过」。", file=sys.stderr)
        return 2

    rows = [audit(t) for t in targets]
    if a.json:
        for r in rows:
            print(json.dumps(r, ensure_ascii=False))
    else:
        for r in rows:
            print(f"\n{r['status']:>4}  {r['file']}")
            print(f"      S1 {r['s1']} 条 · S2 {r['s2']} 条 · S3 {r['s3']} 条")
            for f in r["fails"]:
                print(f"      ✗ {f}")
            for w in r["warns"]:
                print(f"      ! {w}")
        bad = sum(1 for r in rows if r["status"] == "FAIL")
        warn = sum(1 for r in rows if r["status"] == "WARN")
        print(f"\n{len(rows)} 份清单：OK {len(rows) - bad - warn} · WARN {warn} · FAIL {bad}")
        print("（未查：URL 是否可打开、S3 是否被写进定义段——需读正文／联网，本脚本不做）")
    return 1 if any(r["status"] == "FAIL" for r in rows) else 0


if __name__ == "__main__":
    raise SystemExit(main())
