# -*- coding: utf-8 -*-
r"""check-draft-chunks.py — 超长课件分块生成 + 表格结构化（2026-11-23 用户定）

为什么有这条：用户要求「提高 PDF 的信息量」，其中两条是
  · 源文本超过 MAX_SRC 时不再硬截断（后半本不参与生成）→ 按页切成多段分别生成再拼；
  · 表格别被 get_text 拍平成一行行文字（列关系丢光）→ 有真表就补一段「行1: a | b」。

判据（真跑 draft()，用假 client，不花钱、不联网）：
  1 分块：把 MAX_SRC 压到很小，一份 6 页课件必须切成 ≥2 段，模型被调 ≥2 次，每段提示里带「第 k/n 段」
  2 拼装：段数 × 每段节数 → 节号仍然 0..n-1 连续；§0 导读只留一份；术语表按首列去重不翻倍
  3 表格：给一个「能吐出表格」的假页，_table_text 必须产出可读的行（含「|」分隔），没有表就一个字不加

用法：
    python tools\check\check-draft-chunks.py            # 判本仓
    python tools\check\check-draft-chunks.py --selftest # 拼装/表格逻辑造坏，必须变红

退出码：0 = 全绿 · 1 = 有红
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

FAKE_SECTION = [
    {"no": "0", "zh": "导读", "en": "Intro", "lec": "导读怎么读", "body": [["p", "这是一段导读正文。"]]},
    {"no": "1", "zh": "第一节", "en": "Section 1", "lec": "第一节讲什么",
     "body": [["p", "第一节正文（课件 p.1）。"], ["fig", "gen/X04/p001.png", "示意图（课件 p.1）"]]},
]


def fake_lesson():
    rows = [["术语%d" % i, "term %d" % i, "课件 p.1", "解释 %d" % i] for i in range(24)]
    return {
        "zh": "测试讲义", "en": "Test Handout", "sub": "副标题",
        "sections": json.loads(json.dumps(FAKE_SECTION)),
        "glossary": {"no": "2", "zh": "术语表", "en": "Glossary", "rows": rows},
        "summary": {"no": "3", "zh": "小结", "en": "Summary", "rows": [["做什么", "要点", "怎么验"]]},
        "appendix": {"no": "4", "zh": "附录", "en": "Appendix",
                     "symbols": [["S", "含义", "课件 p.1"]], "myths": []},
        "quiz": {"no": "5", "zh": "自测", "en": "Self-check", "items": [["问", "答", "课件 p.1"]]},
    }


def load(root):
    sys.path.insert(0, root)
    sys.path.insert(0, os.path.join(root, "engine"))
    spec = importlib.util.spec_from_file_location("pluma_draft_chk", os.path.join(root, "engine", "_draft.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def make_deck(tmp, pages=6):
    """造一份 6 页、每页一句中文的课件 + 认得出它的讲次文件。"""
    import pymupdf
    course = os.path.join(tmp, "CASE")
    os.makedirs(os.path.join(course, "00_原件"), exist_ok=True)
    doc = pymupdf.open()
    for i in range(1, pages + 1):
        page = doc.new_page(width=420, height=595)
        page.insert_text((60, 100), "第%d页的内容：主题%d的讲解要点若干字" % (i, i),
                         fontsize=14, fontname="china-s")
    pdf = os.path.join(course, "00_原件", "Deck.pdf")
    doc.save(pdf)
    doc.close()
    os.makedirs(os.path.join(course, "_lessons"), exist_ok=True)
    with open(os.path.join(course, "_lessons", "X04.py"), "w", encoding="utf-8") as f:
        f.write('LESSON = {"no": "X04"}\n# stub-from: 00_原件/Deck.pdf\n')
    return pdf


class FakeTable:
    def extract(self):
        return [["姓名", "分数"], ["甲", "90"], ["乙", "85"]]


class FakeTabs:
    def __init__(self, tables):
        self.tables = tables


class FakePage:
    def __init__(self, tables):
        self._t = tables

    def find_tables(self):
        return FakeTabs(self._t)


def main():
    selftest = "--selftest" in sys.argv
    tmp = tempfile.mkdtemp(prefix="pluma-chunks-")
    try:
        mod = load(ROOT)
        import paths
        paths.DATA_ROOT = tmp
        make_deck(tmp)

        calls = []

        def fake_chat(messages, **kw):
            calls.append(messages)
            return {"text": json.dumps(fake_lesson(), ensure_ascii=False), "seconds": 0.01,
                    "finish_reason": "stop", "usage": {}}

        old_chat, old_cfg = mod.client.chat, mod.client.load_config
        old_max = mod.MAX_SRC
        fails = []
        try:
            mod.client.chat = fake_chat
            mod.client.load_config = lambda: {"model": "fake-model"}
            mod.MAX_SRC = 40             # 强迫分块（6 页共 ~106 字符 → 切成 ≥3 段）
            logs = []
            info = mod.draft("CASE", "X04", "zh", emit=logs.append, save=False)
        finally:
            mod.client.chat, mod.client.load_config = old_chat, old_cfg
            mod.MAX_SRC = old_max

        n = len(calls)
        if n < 2:
            fails.append("没分块：模型只被调了 %d 次（MAX_SRC=160 时 6 页应切多段）" % n)
        elif not any("第 2/" in (m[-1]["content"] if m else "") for m in calls[1:]):
            fails.append("第二段起的提示里没有「第 2/n 段」：%r"
                         % ((calls[-1][-1]["content"][:60]) if calls else "",))

        # 拼装结果（再跑一次，拿到 dict）
        data_file = os.path.join(tmp, "CASE", "_lessons", "X04.py")
        if n >= 2:
            txt = open(data_file, encoding="utf-8").read() if os.path.isfile(data_file) else ""
            # save=False 不落盘，所以这里直接看返回值：info 里有 sections 数
            if info.get("sections") != n + 1:
                fails.append("拼装后的节数不对：%r（%d 段 → 应为 %d 节：导读 1 + 每段 1）"
                             % (info.get("sections"), n, n + 1))

        # 表格：假页必须能吐出「|」分隔的行
        tab = mod._table_text(FakePage([FakeTable()]))
        if "【表格】" not in tab or "|" not in tab:
            fails.append("表格没变成结构化文字：%r" % (tab[:60],))
        elif mod._table_text(FakePage([])).strip():
            fails.append("没有表格的页也硬塞了表格文字")

        if selftest:
            # 把拼装弄坏（只取第一段）→ 节数判据必须红
            orig = mod._merge_parts
            try:
                mod._merge_parts = lambda parts: parts[0]
                calls.clear()
                mod.client.chat = fake_chat
                mod.client.load_config = lambda: {"model": "fake-model"}
                mod.MAX_SRC = 40
                info2 = mod.draft("CASE", "X04", "zh", emit=lambda s: None, save=False)
            finally:
                mod._merge_parts = orig
                mod.client.chat, mod.client.load_config = old_chat, old_cfg
                mod.MAX_SRC = old_max
            bad = info2.get("sections") != len(calls) + 1
            print("  [%s] 拼装坏掉 → 判据 2 %s（节数 %r / %d 段）"
                  % ("过" if bad else "红", "变红" if bad else "没变红（假绿）",
                     info2.get("sections"), len(calls)))
            return 0 if bad else 1

        for f in fails:
            print("[红] " + f)
        print("结论：%d 项%s（模型调用 %d 次 · 拼装后 %r 节）"
              % (3, " 全绿" if not fails else " 有红 %d" % len(fails), n, info.get("sections")))
        return 0 if not fails else 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
