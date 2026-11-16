# -*- coding: utf-8 -*-
"""讲义术语附英工具：**每一节里每个术语的首次出现**必须带「（English）」。

为什么不是「每次出现都附」：L01-02 实测「状态」出现 164 次，每次附要把正文插 82 个
「（state）」，读起来是括号堆。用户 2026-11-16 把口径定为「每节首次」——读者跳到中间
任何一节，第一次见到这个词就能对上英文；同一节里反复出现就不再打断句子。

对外两个函数：
    pairs_of(html)                      → [(中文, 英文短名), …]（从术语表取）
    attach_first_per_section(html)      → (新 html, 插入处数)

跳过：目录 / 术语表 / 自测 / 附录 / 符号速查 这些固定件节，以及 h2/h3 标题（改标题会破坏目录回填）。
"""
from __future__ import annotations

import re

SKIP_TITLES = ("目录", "术语表", "自测", "练习", "附录", "符号速查", "小结")
TEXT_NODE = re.compile(r">([^<]{1,})<")


def _plain(s: str) -> str:
    return re.sub(r"<[^>]+>", "", s)


def pairs_of(html: str) -> list[tuple[str, str]]:
    gloss = re.search(r'<table class="glossary">(.*?)</table>', html, re.S)
    if not gloss:
        return []
    out = []
    for tr in re.findall(r"<tr>(.*?)</tr>", gloss.group(1), re.S):
        tds = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)
        if len(tds) < 2 or not re.search(r"[A-Za-z]", _plain(tds[1])):
            continue
        zh = re.split(r"[（(/]", _plain(tds[0]))[0].strip()
        en = re.sub(r"\s*\([^)]*\)", "", _plain(tds[1]).split("/")[0]).strip()
        if len(zh) >= 2 and en:
            out.append((zh, en))
    return out


def _mask(html: str) -> str:
    """把不该动的区域（标题、术语表）替换成等长空格，保持下标不变。"""
    out = list(html)
    for pat in (r"<h2>.*?</h2>", r"<h3>.*?</h3>", r'<table class="glossary">.*?</table>'):
        for m in re.finditer(pat, html, re.S):
            for i in range(m.start(), m.end()):
                if out[i] != "\n":
                    out[i] = " "
    return "".join(out)


def covered_spans(text: str, term: str, pairs: list[tuple[str, str]]) -> list[tuple[int, int]]:
    """比 term 更长的术语在 text 里的所有出现位置（这些位置里的 term 不算「独立出现」）。

    为什么需要：「动作」在「动作价值（action value）」里也匹配得到，但它不是独立的名词；
    不排除就会一直判「动作没附英文」，而实际上（写得更好的是）长词已经附了。
    """
    spans = []
    for other, _ in pairs:
        if len(other) <= len(term):
            continue
        for m in re.finditer(re.escape(other), text):
            spans.append((m.start(), m.end()))
    return spans


def first_standalone(text: str, term: str, pairs: list[tuple[str, str]]) -> int:
    """term 在 text 里第一个「不被更长术语遮住」的出现位置（找不到返回 -1）。"""
    cov = covered_spans(text, term, pairs)
    for m in re.finditer(re.escape(term), text):
        s, e = m.start(), m.end()
        if any(s < ce and e > cs for cs, ce in cov):
            continue
        return s
    return -1


def attach_first_per_section(html: str) -> tuple[str, int]:
    pairs = sorted(pairs_of(html), key=lambda x: -len(x[0]))   # 长词优先，避免「状态」切进「状态价值」
    masked = _mask(html)
    # 按 h2 切节，记录每节在原文里的区间
    heads = [m.start() for m in re.finditer(r"<h2>", html)]
    heads.append(len(html))
    inserts: list[tuple[int, str]] = []
    for a, b in zip(heads, heads[1:]):
        seg = html[a:b]
        m = re.search(r'<span class="zh">(.*?)</span>', seg, re.S)
        title = _plain(m.group(1)).strip() if m else ""
        if not title or any(k in title for k in SKIP_TITLES):
            continue
        used: list[tuple[int, int]] = []
        seg_masked = masked[a:b]
        for zh, en in pairs:
            pos = -1
            cov = covered_spans(seg_masked, zh, pairs)
            for m2 in re.finditer(re.escape(zh), seg_masked):
                s, e = m2.start(), m2.end()
                if any(s < ce and e > cs for cs, ce in cov):   # 被长词遮住
                    continue
                pos = a + e
                break
            if pos < 0:
                continue
            tail = html[pos:pos + 6]
            if re.match(r"[（(]\s*[A-Za-z]", tail):
                used.append((pos - len(zh), pos))
                continue
            inserts.append((pos, f"（{en}）"))
            used.append((pos - len(zh), pos + len(en) + 2))
    for pos, text in sorted(inserts, key=lambda x: -x[0]):
        html = html[:pos] + text + html[pos:]
    return html, len(inserts)
