# -*- coding: utf-8 -*-
"""audit_lesson.py · 讲义成品质量硬测（本库唯一入口）

为什么要有它：doccheck.ps1 只查「文件在不在、多大」，所以一份白底、无页脚、
零页码引用的半成品也能「通过」。这个脚本只按可失败的事实打分，不看文档怎么写。

「成品」的判定：**有讲义源（06_笔记\\*_讲义_源.html 里的 <meta name="out">）声明的才审**。
01_讲义 目录里同时放着课件原件（lesson.ps1 归档），原件没有源，默认跳过
（--all 可强制全审）。不这样区分，原件会被当成白底半成品误判。

用法（相对本库根目录执行）：
    python tools\\print\\audit_lesson.py                       # 只审有源声明的成品（全部课程）
    python tools\\print\\audit_lesson.py BSAI402               # 只审一门课
    python tools\\print\\audit_lesson.py --all                 # 连课件原件一起审（会大量 FAIL）
    python tools\\print\\audit_lesson.py --file "<某个.pdf>"     # 强制只测这几份
    python tools\\print\\audit_lesson.py --json                # 机器可读（JSONL，每行一个对象；给 doccheck / lesson.ps1 用）
    python tools\\print\\audit_lesson.py --light               # 按浅色版验收（白底不扣分）

验收口径来自 docs\\01-讲义生产方案.md §6：
    1 四角为底色（深色版无白边）
    2 页脚 N / M 覆盖率
    3 「课件 p.N」引用密度（六条第 2 条）
    4 目录页码回填、自测题在不在

退出码：有 FAIL → 1；只有 WARN → 0；全 OK → 0。
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys

import pymupdf

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import paths  # noqa: E402  路径双根，见仓根 paths.py

# 2026-11-17：ROOT = 数据根（冻结后是 exe 旁的可写目录；源码下就是仓根）。
#   只用来找「课程目录」与相对路径显示；本脚本自己（与 terms.py）从 __file__ 旁边找。
ROOT = paths.DATA_ROOT

FOOTER_RE = re.compile(r"(\d+)\s*/\s*(\d+)\s*$")
# 定位引用：PDF 入口用「课件 p.N」，论文入口用 arXiv 编号 / DOI——两者都是「能回到原文某一处」
# 2026-11-16 改：LNN 讲义是论文入口，旧口径只认「课件 p.N」会把合格成品判红（不是放宽，是换成方案 §2 的定位定义）
CITE_RE = re.compile(r"课件\s*p\.?\s*\d+|arXiv:\s*\d{4}\.\d{4,5}|10\.\d{4}/\S+", re.I)

# 判定阈值（改这里就是改验收标准，改完同步 docs\01-讲义生产方案.md §6）
TH = {
    "footer_ratio": 0.90,   # 页脚命中率下限
    "cite_per_page": 0.5,   # 每页至少半处页码引用
    "min_chars_page": 400,  # 低于此值提醒「内容太薄」
    "dark_luma": 90,        # 深色版四角平均亮度上限
    "light_luma": 215,      # 浅色版四角平均亮度下限
}

# 深色简约风的标准色（讲义唯一主题）。改这里 = 改全库标准，必须同步：
#   docs\01-讲义生产方案.md §4、迷迭香 Rosmarinus\docs\47-三套外观.md §4.3、
#   BSAI402\06_笔记\*_讲义_源.html 的 :root 块。
# 2026-11-16 补：来源是迷迭香「简约风」（炭黑底 + 琥珀强调），讲义侧取略深的 #0E0E0C。
THEME = {"bg": "#0e0e0c", "text": "#f4f1e6", "amber": "#e7c246", "line": "#2a2a24"}

# 内容门阈值（方案-多源讲义生产 §4 门二）。改这里 = 改内容标准。
CONTENT_TH = {
    "term_bare": 2,          # 术语正文出现达到几次才判「裸术语」
    "term_attach_warn": 0.5,  # 附英比例低于它 → 黄
    "para_chars": 210,       # 单段超过这么多字 ≈ 超过 5 行 → 黄
    "glossary_min": 20,      # 术语表至少这么多条
    "quiz_min": 3,
    "quiz_max": 8,
    "table_cols_max": 6,
}
# 定位标注：页码 / arXiv 编号 / 章节号 / 视频时间戳 / 代码行号，任一种即可
LOC_RE = re.compile(
    r"课件\s*p\.?\s*\d+|arXiv:\s*\d{4}\.\d{4,5}|arxiv\.org/abs/|doi\.org/|10\.\d{4}/|§\s*\d+"
    r"|\d{1,2}:\d{2}\b|\b[\w./\\-]+\.(?:py|js|ts|md|ps1|html|css):\d+|https?://\S+", re.I)
# 术语表里的页码只写「p.1」也认（正文里不认，否则随便一个 p.1 就能冒充定位）
GLOSS_LOC_RE = re.compile(LOC_RE.pattern + r"|p\.\s*\d+", re.I)
# 这些节不强求定位标注（目录 / 导读 / 自测 / 术语表 本身不是「知识点」）
LOC_SKIP = ("目录", "本讲导读", "术语表", "自测", "练习", "小结")
# 这些节不强求「讲法」段（都是固定件或纯工具页；2026-11-16 用户要求概念节必须有讲法）
LEC_SKIP = ("目录", "本讲导读", "术语表", "自测", "练习", "小结", "附录", "符号速查")

from html import unescape as _unescape

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from terms import pairs_of, first_standalone
    _HAVE_TERMS = True
except Exception:          # 工具目录被挪走时退回空实现，判据明说「没查」
    _HAVE_TERMS = False

    def pairs_of(html):
        return []

    def first_standalone(flat, term, pairs):
        return -1


def strip_tags(s: str) -> str:
    return _unescape(re.sub(r"<[^>]+>", "", s))


def content_audit(path: str, draft: bool = False) -> dict:
    """内容门：扫讲义源 HTML（方案 §4 门二）。draft=True 时跳过固定件类判据（预览稿用）。"""
    html = open(path, encoding="utf-8", errors="replace").read()
    rel = _rel(path)
    fails, warns = [], []

    # 1 主题：深色简约风，色值必须与标准一致（2026-11-15 上一轮把样张改成了白底蓝框，这里拦住）
    if 'data-theme="dark"' not in html:
        fails.append('缺 <html data-theme="dark">（讲义只有深色一套）')
    for k, v in THEME.items():
        m = re.search(rf"--{k}:\s*(#[0-9A-Fa-f]{{6}})", html)
        if not m:
            fails.append(f"缺 CSS 变量 --{k}（标准 {v}）")
        elif m.group(1).lower() != v:
            fails.append(f"--{k} = {m.group(1)}，不等于标准 {v}（主题被改过）")
    if re.search(r"background\s*:\s*(#fff\b|#ffffff|white)\b",
                 re.sub(r"figure img\{[^}]*\}", "", html), re.I):
        fails.append("出现白底声明（background:#fff），深色讲义不允许")
        # 注：figure img 里的 white 是「图保持课件原白底」（用户 2026-11-12 定），不算违规

    # 2 读者口径：默认「大学」（本科在读，可跳专业；2026-11-16 用户定）
    m = re.search(r'data-reader="([^"]*)"', html)
    if not m:
        fails.append('缺 data-reader 属性（读者口径未声明，默认应为「大学」）')
    elif "大学" not in m.group(1):
        fails.append(f'data-reader="{m.group(1)}"，不是「大学」口径')

    body = html
    gloss = re.search(r'<table class="glossary">(.*?)</table>', html, re.S)
    if gloss:
        body = html.replace(gloss.group(0), "")

    # 3 每条公式后紧跟符号表（§3.1）；两种写法都认：<div class="eq"> 与 KaTeX 的 \[…\]
    #    只认含「=」的，图示与轨迹不算公式
    spans = [(m.start(), m.end(), strip_tags(m.group(1)))
             for m in re.finditer(r'<div class="eq">(.*?)</div>', html, re.S)]
    spans += [(m.start(), m.end(), m.group(1))
              for m in re.finditer(r"\\\[(.*?)\\\]", html, re.S)]
    spans.sort()
    n_eq = n_eq_bad = 0
    for _, end, text in spans:
        if "=" not in text:
            continue
        n_eq += 1
        if 'table class="sym"' not in html[end:end + 600]:
            n_eq_bad += 1
            if n_eq_bad <= 3:
                fails.append(f"公式后没跟符号表：{text.strip()[:36]}")
    if n_eq_bad > 3:
        fails.append(f"…另有 {n_eq_bad - 3} 条公式缺符号表")

    # 3b KaTeX 接线（2026-11-16 接进正式链路）：用了就三件必须在，且文件真存在
    uses_katex = bool(re.search(r"\\\[|\\\(", html))
    if uses_katex:
        for need in ("katex.min.css", "katex.min.js", "auto-render.min.js", "renderMathInElement"):
            if need not in html:
                fails.append(f"用了 KaTeX 但缺「{need}」（打印时公式会原样输出来）")
        for ref in re.findall(r'(?:src|href)="([^"]*katex[^"]*)"', html):
            target = os.path.normpath(os.path.join(os.path.dirname(path), ref))
            if not os.path.exists(target):
                fails.append(f"KaTeX 资源路径不存在：{ref}")

    # 4 术语附英（§3.2，2026-11-16 改为「每节首次出现必附」）：
    #    每个概念节里，术语的**第一次出现**必须紧跟「（English）」。
    #    为什么不是「每次出现都附」：L01-02 的「状态」出现 164 次，每次附要插 82 个括号，正文会变成括号堆。
    pairs = pairs_of(html)
    plain = strip_tags(body)      # 后面「回看 §」与段落检查都用它（2026-11-16：改术语判据时补偿这一行）
    if not _HAVE_TERMS:
        warns.append("未查术语附英：取不到 tools\\print\\terms.py")
    no_en = []
    sec_list = re.split(r"(?=<h2)", html)[1:]
    for sec in sec_list:
        m = re.search(r'<span class="zh">(.*?)</span>', sec, re.S)
        title = strip_tags(m.group(1)).strip() if m else ""
        if not title or any(k in title for k in LEC_SKIP):
            continue
        flat = strip_tags(re.sub(r"<h[23]>.*?</h[23]>", " ",
                                 re.sub(r"<svg.*?</svg>|<pre class=\"code\">.*?</pre>", " ", sec, flags=re.S),
                                 flags=re.S))
        for zh, _en in pairs:
            i = first_standalone(flat, zh, pairs)
            if i < 0:
                continue
            after = flat[i + len(zh):i + len(zh) + 6]
            if not re.match(r"[（(]\s*[A-Za-z]", after):
                no_en.append(f"{title[:12]}·{zh}")
    if no_en:
        fails.append("这些节里的术语首次出现没附英文（§3.2）：" + "、".join(no_en[:6])
                     + (f"…共 {len(no_en)} 处" if len(no_en) > 6 else ""))

    # 5 每节有定位标注（方案 §4 门二）
    secs = re.split(r"(?=<h2)", html)[1:]
    no_loc = []
    for sec in secs:
        m = re.search(r'<span class="zh">(.*?)</span>', sec, re.S)
        title = strip_tags(m.group(1)).strip() if m else ""
        if not title or any(k in title for k in LOC_SKIP):
            continue
        if not LOC_RE.search(strip_tags(sec)):
            no_loc.append(title)
    if no_loc:
        fails.append("这些节没有任何定位标注（页码/§/时间戳/行号）：" + "、".join(no_loc[:5]))

    # 5b 每个概念节都要有「讲法」段（用户 2026-11-16：讲义不能只是 PPT 要点）
    no_lec = []
    for sec in secs:
        m = re.search(r'<span class="zh">(.*?)</span>', sec, re.S)
        title = strip_tags(m.group(1)).strip() if m else ""
        if not title or any(k in title for k in LEC_SKIP):
            continue
        if 'class="lec"' not in sec.split('<h3>')[0] and 'class="lec"' not in sec:
            no_lec.append(title)
    if no_lec:
        fails.append("这些概念节没有「讲法」段（<p class=\"lec\">）：" + "、".join(no_lec[:5]))

    # 5c 每节要有「代码 / 例题」（用户 2026-11-16 定：以代码、题目运算为主，理论为辅）
    #    现在记 WARN：存量 L02–L09 是老口径，返工完再转 FAIL；新写的讲必须每节至少一个。
    no_prac = []
    for sec in secs:
        m = re.search(r'<span class="zh">(.*?)</span>', sec, re.S)
        title = strip_tags(m.group(1)).strip() if m else ""
        if not title or any(k in title for k in LEC_SKIP):
            continue
        if not re.search(r'<pre class="code">|<div class="eg">', sec):
            no_prac.append(title)
    if no_prac:
        warns.append("这些节只有理论、没有代码或例题（练习型讲义要求每节至少一个）："
                     + "、".join(no_prac[:5]) + (f"…共 {len(no_prac)} 节" if len(no_prac) > 5 else ""))

    n_prac = len(re.findall(r'<pre class="code">|<div class="eg">', html))
    n_dia = len(re.findall(r'figure class="diagram"', html))

    n_q = len(re.findall(r'class="(?:q|ans)"', html))
    n_qq = len(re.findall(r'class="q"', html))
    n_ans = len(re.findall(r'class="ans"', html))

    if not draft:  # 6–9 固定件 / 术语表 / 自测：预览稿（--draft）不判
        fixed = {"封面": 'class="cover"', "目录": "CONTENTS", "导读": "导读",
                 "小结": "小结", "自测": "自测", "术语表": "术语表", "附录": "附录"}
        miss = [k for k, v in fixed.items() if v not in html]
        if miss:
            fails.append("固定件缺：" + "、".join(miss))
        if gloss:
            rows = re.findall(r"<tr>(.*?)</tr>", gloss.group(1), re.S)
            rows = [r for r in rows if "<td" in r]
            if len(rows) < CONTENT_TH["glossary_min"]:
                fails.append(f"术语表 {len(rows)} 条，少于 {CONTENT_TH['glossary_min']} 条")
            no_pg = [r for r in rows if not GLOSS_LOC_RE.search(strip_tags(r))]
            if no_pg:
                fails.append(f"术语表 {len(no_pg)} 条没标定位（页码/§）")
        else:
            fails.append("没有术语表表格（table class=\\\"glossary\\\"）")
        if not (CONTENT_TH["quiz_min"] <= n_qq <= CONTENT_TH["quiz_max"]):
            fails.append(f"自测 {n_qq} 题，要求 {CONTENT_TH['quiz_min']}–{CONTENT_TH['quiz_max']} 题")
        if n_ans != n_qq:
            fails.append(f"自测 {n_qq} 题但只有 {n_ans} 个答案")
        if "回看 §" not in plain:
            fails.append("自测答案里没有「回看 §x」（错题回不去原节）")

    # 10–11 段落过长 / 表格列数过多
    # 2026-11-16 修：原来写 <p[^>]*>，会把 <pre class="code"> 也当成 <p>（代码整块被算成一个「段落」，
    # 于是每讲都报 7–8 段超长）。改成只匹配真正的 <p>——<p> 或 <p 加属性。
    long_p = [strip_tags(p).strip() for p in re.findall(r"<p(?:\s[^>]*)?>(.*?)</p>", html, re.S)
              if 'class="src"' not in html[max(0, html.find(p) - 40):html.find(p)]]
    long_p = [p for p in long_p if len(p) > CONTENT_TH["para_chars"]]
    if long_p:
        warns.append(f"{len(long_p)} 段超过 {CONTENT_TH['para_chars']} 字（约 5 行）")
    wide = 0
    for t in re.findall(r"<table.*?</table>", html, re.S):
        m = re.search(r"<tr>(.*?)</tr>", t, re.S)
        if m and len(re.findall(r"<th", m.group(1))) > CONTENT_TH["table_cols_max"]:
            wide += 1
    if wide:
        warns.append(f"{wide} 张表超过 {CONTENT_TH['table_cols_max']} 列")

    return {"file": rel, "status": "FAIL" if fails else ("WARN" if warns else "OK"),
            "fails": fails, "warns": warns, "terms": len(pairs), "eq": n_eq,
            "eq_bad": n_eq_bad, "quiz": n_qq, "draft": draft}


def corner_luma(page) -> int:
    """取四角 3×3 像素的平均亮度，判白边用。"""
    w, h = page.rect.width, page.rect.height
    spots = [(0, 0), (w - 3, 0), (0, h - 3), (w - 3, h - 3)]
    vals = []
    for x, y in spots:
        pix = page.get_pixmap(clip=pymupdf.Rect(x, y, x + 3, y + 3), dpi=72)
        r, g, b = pix.pixel(1, 1)
        vals.append(0.299 * r + 0.587 * g + 0.114 * b)
    return int(sum(vals) / len(vals))


def _rel(path: str) -> str:
    """仓内路径用相对；演练用的临时文件在别的盘上时退回全路径（否则 relpath 抛 ValueError）。"""
    try:
        return os.path.relpath(path, ROOT).replace("\\", "/")
    except ValueError:
        return path.replace("\\", "/")


def body_start_pages(doc) -> list[tuple[int, str]]:
    """找出「页面第一行不是标题/图注/表头/公式」的页（＝这一节被切到上一页去了）。

    2026-11-16 加：用户要求「章节不能一部分落在两页」，这条判据就是它的机器判法。
    2026-11-16 收紧（L05 实测）：原来只认 YaHei 10.5 正文，漏掉了三类真断裂——
      例题题面（YaHei-Bold 10.0）、代码块（Consolas 8.9）、结构图里的字（YaHei 8.1）；
    现在改成「白名单」：页首只允许 h2 标题、h3、图注/表头（YaHei 8.3–9.5）、公式（Cambria/Math），
    其余一律算「页从中间开始」。宁可红也要看得见，跳过 ≠ 通过。
    """
    bad = []
    for i, page in enumerate(doc, 1):
        if i == 1:          # 封面不判
            continue
        for block in page.get_text("dict")["blocks"]:
            if block.get("type"):
                continue
            line = next((ln for ln in block["lines"]
                         if any(s["text"].strip() for s in ln["spans"])), None)
            if line is None:
                continue
            span = max((s for s in line["spans"] if s["text"].strip()),
                       key=lambda s: s["size"])
            text = "".join(s["text"] for s in line["spans"]).strip()
            font, size = span["font"], span["size"]
            ok = False
            if "Bold" in font and 13.0 <= size <= 15.5:
                ok = True                                     # h2 标题
            elif "Bold" in font and 10.8 <= size <= 11.5:
                ok = True                                     # h2 编号 / h3
            elif "Cambria" in font or "Math" in font:
                ok = True                                     # 公式
            elif ("YaHei" in font or "Source Han" in font) and 8.3 <= size <= 9.5:
                ok = True                                     # 图注 / 表头
            if not ok and text[:2] not in ("符号", "中文"):
                bad.append((i, text[:40]))
            break
    return bad


def audit_one(path: str, light: bool = False) -> dict:
    doc = pymupdf.open(path)
    n = doc.page_count
    chars = 0
    imgs = 0
    broken_imgs = 0
    footer_hit = 0
    texts = []
    for i in range(n):
        p = doc[i]
        t = p.get_text("text")
        texts.append(t)
        chars += len(t)
        found = p.get_images(full=True)
        imgs += len(found)
        # 破图判据（2026-11-16 加）：图文件丢失时 Chrome 会画一个 14×16 的「缺图图标」，
        # 原来只数张数，于是「图全丢了」也报 6 图、看起来是绿的。宽高 < 32 就计入破图。
        for im in found:
            if im[2] < 32 or im[3] < 32:
                broken_imgs += 1
        clip = pymupdf.Rect(0, p.rect.height - 40, p.rect.width, p.rect.height)
        lines = [l.strip() for l in p.get_text("text", clip=clip).splitlines() if l.strip()]
        # 2026-11-17：页脚从一行变成两行（上行讲次 + N/M，下行品牌名 + 地址 + 免责），
        #   页码不再一定是从底区抽出来的最后一行。这里改成「底部 40pt 条里有一行收在 N / M」。
        #   仍然能失败：不带页脚的 PDF 拿这份判据跑过，报 0/10（见 tools\check\check-pdf-brand.py）。
        if any(FOOTER_RE.search(l) for l in lines):
            footer_hit += 1
    full = "\n".join(texts)

    # 底色：第 1 页 + 最后一页，避免封面特殊
    lumas = [corner_luma(doc[0])] + ([corner_luma(doc[-1])] if n > 1 else [])
    luma = max(lumas)

    cites = len(CITE_RE.findall(full))
    has_toc = ("目录" in full and "CONTENTS" in full.upper())
    has_quiz = ("自测" in full or "练习" in full) and ("答案" in full)
    added = full.count("整理者补充")
    body_starts = body_start_pages(doc)
    doc.close()

    fails, warns = [], []
    if broken_imgs:
        fails.append(f"{broken_imgs} 张图是破图（宽高 < 32px，Chrome 缺图图标）：图文件没找到",)
    if light:
        if luma < TH["light_luma"]:
            fails.append(f"非浅色底(亮度{luma})")
    else:
        if luma > TH["dark_luma"]:
            fails.append(f"白底/白边(亮度{luma})")
    ratio = footer_hit / n if n else 0
    if ratio < TH["footer_ratio"]:
        fails.append(f"页脚 {footer_hit}/{n}")
    if cites == 0:
        fails.append("无「课件 p.N」页码引用")
    elif cites / n < TH["cite_per_page"]:
        warns.append(f"页码引用偏少 {cites} 处/{n} 页")
    if chars / max(n, 1) < TH["min_chars_page"]:
        warns.append(f"内容偏薄 {chars // max(n, 1)} 字/页")
    if not has_toc:
        warns.append("无目录")
    if not has_quiz:
        warns.append("无自测+答案")
    if body_starts:
        fails.append("页面从正文中间开始（节被切到两页）：" + "、".join(
            f"p{i}「{t}」" for i, t in body_starts[:4]) +
            (f"…共 {len(body_starts)} 页" if len(body_starts) > 4 else ""))

    rel = _rel(path)
    return {
        "file": rel,
        "pages": n,
        "chars": chars,
        "chars_per_page": chars // max(n, 1),
        "images": imgs,
        "footer": f"{footer_hit}/{n}",
        "corner_luma": luma,
        "cites": cites,
        "has_toc": has_toc,
        "has_quiz": has_quiz,
        "added_notes": added,
        "body_starts": len(body_starts),
        "fails": fails,
        "warns": warns,
        "status": "FAIL" if fails else ("WARN" if warns else "OK"),
    }


def declared_outputs() -> dict[str, str]:
    """扫所有 *_讲义_源.html 的 <meta name="out">，返回 {成品绝对路径: 源 HTML 相对路径}。"""
    decl: dict[str, str] = {}
    for src in glob.glob(os.path.join(ROOT, "*", "06_笔记", "*_讲义_源.html")):
        try:
            html = open(src, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        m = re.search(r'<meta\s+name="out"\s+content="([^"]+)"', html)
        if not m:
            continue
        course = os.path.dirname(os.path.dirname(src))
        for cand in glob.glob(os.path.join(course, "**", m.group(1)), recursive=True):
            decl[os.path.abspath(cand)] = os.path.relpath(src, ROOT).replace("\\", "/")
    return decl


def collect(targets: list[str], light: bool) -> list[dict]:
    out = []
    for t in targets:
        try:
            out.append(audit_one(t, light))
        except Exception as e:  # noqa: BLE001
            out.append({
                "file": _rel(t),
                "status": "FAIL", "fails": [f"{type(e).__name__}: {e}"], "warns": [],
                "pages": 0, "chars": 0, "chars_per_page": 0, "images": 0,
                "footer": "0/0", "corner_luma": 0, "cites": 0,
                "has_toc": False, "has_quiz": False, "added_notes": 0,
            })
    return out


def main(argv: list | None = None) -> int:
    for s in (sys.stdout, sys.stderr):   # Windows 控制台默认 GBK，中文路径与 ✗ 会直接抛异常
        if hasattr(s, "reconfigure"):
            s.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("course", nargs="?", help="课程代码，如 BSAI402；省略=扫全部课程")
    ap.add_argument("--file", nargs="+", help="直接指定 PDF 路径")
    ap.add_argument("--json", action="store_true", help="输出 JSONL（每行一个对象，给 doccheck / lesson.ps1 用）")
    ap.add_argument("--quiet", action="store_true", help="只报非 OK 的成品（日常验收用，省输出）")
    ap.add_argument("--all", action="store_true", help="连课件原件一起审（默认只审有源声明的成品）")
    ap.add_argument("--light", action="store_true", help="按浅色版验收")
    ap.add_argument("--content", action="store_true", help="内容门：扫讲义源 HTML（公式符号表/裸术语/定位/固定件/主题色/读者口径）")
    ap.add_argument("--draft", action="store_true", help="配 --content：预览稿模式，不判固定件/术语表/自测")
    a = ap.parse_args(argv)

    if a.content:
        srcs = ([os.path.abspath(f) for f in a.file] if a.file else
                sorted(glob.glob(os.path.join(ROOT, "*", "06_笔记", "*_讲义_源.html"))))
        if not srcs:
            print("没有可检查的讲义源（*\\06_笔记\\*_讲义_源.html）。这是「没查」，不是「通过」。",
                  file=sys.stderr)
            return 2
        rows = [content_audit(s, a.draft) for s in srcs]
        if a.json:
            for r in rows:
                print(json.dumps(r, ensure_ascii=False))
        else:
            for r in rows:
                print(f"\n{r['status']:>4}  {r['file']}")
                print(f"      {r['eq']} 条公式（缺符号表 {r['eq_bad']}） · {r['terms']} 个术语 · "
                      f"自测 {r['quiz']} 题" + (" · 预览稿模式" if r["draft"] else ""))
                for f in r["fails"]:
                    print(f"      ✗ {f}")
                for w in r["warns"]:
                    print(f"      ! {w}")
            bad = sum(1 for r in rows if r["status"] == "FAIL")
            warn = sum(1 for r in rows if r["status"] == "WARN")
            print(f"\n{len(rows)} 份讲义源：OK {len(rows) - bad - warn} · WARN {warn} · FAIL {bad}")
            print("（人工仍需抽查：类比是否误导、例题数字是否真算过——脚本判不了，别当已查）")
        return 1 if any(r["status"] == "FAIL" for r in rows) else 0

    skipped: list[str] = []
    if a.file:
        targets = [os.path.abspath(f) for f in a.file]
    else:
        courses = [a.course] if a.course else [
            d for d in os.listdir(ROOT)
            if os.path.isdir(os.path.join(ROOT, d, "01_讲义"))
        ]
        targets = []
        for c in courses:
            targets += glob.glob(os.path.join(ROOT, c, "01_讲义", "*.pdf"))
        targets = [t for t in targets if "\\_drafts\\" not in t and "/_drafts/" not in t]
        if not a.all:
            decl = declared_outputs()
            for t in sorted(targets):
                if os.path.abspath(t) not in decl:
                    skipped.append(os.path.relpath(t, ROOT).replace("\\", "/"))
            targets = [t for t in targets if os.path.abspath(t) in decl]

    if not targets:
        print("没有可检查的成品 PDF。" + ("（被跳过：" + ", ".join(skipped) + "）" if skipped else ""),
              file=sys.stderr)
        return 2

    rows = collect(sorted(targets), a.light)

    if a.json:
        # JSONL：每行一个对象。不用顶层数组，因为 PowerShell 5.1 的 ConvertFrom-Json
        # 会把数组当成单个对象，$r.status 变数组、-eq 判定恒真，闸门就假绿了。
        for r in rows:
            print(json.dumps(r, ensure_ascii=False))
    elif a.quiet:
        for r in rows:
            if r["status"] == "OK":
                continue
            print(f"{r['status']}  {os.path.basename(r['file'])}")
            for f in r["fails"]:
                print(f"    ✗ {f}")
            for w in r["warns"]:
                print(f"    ! {w}")
        bad = sum(1 for r in rows if r["status"] == "FAIL")
        warn = sum(1 for r in rows if r["status"] == "WARN")
        print(f"{len(rows)} 份：OK {len(rows) - bad - warn} · WARN {warn} · FAIL {bad}")
        if skipped:
            print(f"（另有 {len(skipped)} 份课件原件已跳过）")
    else:
        for r in rows:
            print(f"\n{r['status']:>4}  {os.path.basename(r['file'])}")
            print(f"      {r['pages']} 页 · {r['chars']} 字符 · {r['chars_per_page']} 字/页 · {r['images']} 图"
                  f" · 页脚 {r['footer']} · 四角亮度 {r['corner_luma']} · 页码引用 {r['cites']} 处")
            for f in r["fails"]:
                print(f"      ✗ {f}")
            for w in r["warns"]:
                print(f"      ! {w}")
        bad = sum(1 for r in rows if r["status"] == "FAIL")
        warn = sum(1 for r in rows if r["status"] == "WARN")
        print(f"\n{len(rows)} 份成品：OK {len(rows) - bad - warn} · WARN {warn} · FAIL {bad}")
        if skipped:
            print(f"跳过 {len(skipped)} 份无讲义源的 PDF（课件原件，不是成品）：")
            for s in skipped:
                print(f"  · {s}")

    return 1 if any(r["status"] == "FAIL" for r in rows) else 0


if __name__ == "__main__":
    sys.exit(main())
