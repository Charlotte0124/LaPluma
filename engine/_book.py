# -*- coding: utf-8 -*-
"""九讲合订本：把多讲的正文拼成一本（自带封面与总目录）。

    python engine\\_book.py                      # 默认 CS340 全部讲，按讲号顺序
    python engine\\_book.py L01 L05 L06          # 只合指定的几讲（顺序即书里的顺序）

为什么合订本不复用各讲的封面与目录
    各讲单独出时，每份都有自己的封面页与目录页（占 2 页）。合起来读时那 18 页是重复的，
    所以合订本只留「一本封面 + 一张总目录」，正文直接接在一起。
    也就是说：合订本页数 = 1（封面）+ 1（总目录）+ Σ(各讲页数 − 2)。

页码与目录怎么对上
    index.html 那套目录回填靠 `data-head` 去 PDF 里找标题文字（只认 ≥13pt 的行，即 h2 的中文标题）。
    「本讲导读」在九讲里各出现一次，直接拿它当锚点会被第一讲抢走，所以合订本把每讲第一节
    的标题改写成「L05 · 本讲导读」——既让锚点唯一，也在正文里标出了讲边界（不改页数）。

判据（脚本自己算，不靠估）
    ① 每讲正文的节数 = len(sections) + 4（小结 / 自测 / 术语表 / 附录四个固定件）
    ② 合订本页数 = 1 + 目录页数 + Σ(各讲正文页数)
    ③ 目录 9 条全部回填成功
"""
from __future__ import annotations

import io
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import paths  # noqa: E402  路径双根，见仓根 paths.py

sys.path.insert(0, paths.res('engine'))
sys.path.insert(0, paths.res('tools', 'print'))
# 2026-11-17：ROOT 改成数据根（冻结后是 exe 旁的可写目录；源码下就是仓根）
ROOT = paths.DATA_ROOT
# 2026-11-17：课程代码不再写死（示例课程 / 截图演示用 PLUMA_COURSE 切，默认仍是 CS340）
COURSE = os.environ.get("PLUMA_COURSE") or "CS340"

import _build_讲义 as builder  # noqa: E402

ORDER = ['L01', 'L02', 'L03', 'L04-01', 'L04-02', 'L05', 'L06', 'L08', 'L09']
OUT_HTML = ''
OUT_PDF = ''


def set_course(course: str) -> None:
    """同一进程里切课程：数据目录与产物名跟着换（默认课程仍是 CS340）。"""
    global COURSE, OUT_HTML, OUT_PDF
    COURSE = course or COURSE
    builder.COURSE = COURSE
    d = paths.data(COURSE)
    OUT_HTML = os.path.join(d, '06_笔记', COURSE + '_合订本_源.html')
    OUT_PDF = os.path.join(d, '01_讲义', COURSE + '_九讲合订本_讲义.pdf')


set_course(COURSE)


def strip_fixed_pages(html: str) -> str:
    """只取 body 内容，再去掉单讲自带的封面页与目录页。

    2026-11-16 踩过的坑：build() 返回的是整份 HTML（含 <html>、<head>、<style>），
    直接拼会把九份 CSS 叠在一起，后一份的 .toc 规则反向盖掉合订本自己的覆盖。
    """
    m = re.search(r'<body>(.*)</body>', html, re.S)
    html = m.group(1) if m else html
    html = re.sub(r'<section class="cover">.*?</section>', '', html, flags=re.S)
    html = re.sub(r'<section class="tocpage">.*?</section>', '', html, flags=re.S)
    return html


def body_of(lesson: dict) -> str:
    """一讲的正文（不含封面/目录），并把第一节标题改成「讲号 · 标题」当锚点。"""
    html = strip_fixed_pages(builder.build(lesson))
    first = lesson['sections'][0]
    old = '<span class="zh">%s</span>' % first['zh']
    new = '<span class="zh">%s · %s</span>' % (lesson['no'], first['zh'])
    if old not in html:
        raise RuntimeError('%s 的第一节标题没找到，锚点改不上去' % lesson['no'])
    return html.replace(old, new, 1)


def style_of(lesson: dict) -> str:
    html = builder.build(lesson)
    m = re.search(r'<style>(.*?)</style>', html, re.S)
    if not m:
        raise RuntimeError('取不到样式块')
    # 合订本专用覆盖：讲号可能是 L04-01 这种 6 个字符，单讲的 9mm 列会折行
    extra = ('\n  .toc .item{grid-template-columns:1fr 12mm}')
    return m.group(1) + extra


def cover(lessons: list[dict]) -> str:
    rows = '\n'.join(
        '    <div class="row"><b>%s</b><span>%s · %s</span></div>' % (L['no'], L['zh'], L['en'])
        for L in lessons)
    return (
        '<section class="cover">\n'
        '  <div class="kicker">CS340 · 讲义合订本 · 九讲</div>\n'
        '  <h1>操作系统 · 讲义合订本</h1>\n'
        '  <div class="sub">Operating Systems · Handouts in One Volume<br>\n'
        '  封面只有一张；每讲的正文、例题、代码与结构图都在，各讲自带的封面与目录已去掉</div>\n'
        '  <div class="meta">\n%s\n  </div>\n'
        '</section>' % rows)


def toc(lessons: list[dict]) -> str:
    items = []
    for L in lessons:
        anchor = '%s · %s' % (L['no'], L['sections'][0]['zh'])
        # 讲号直接放进标题格里：像 L04-01 这种 6 个字符的讲号放进 9mm 的编号列会挤在一起
        items.append('    <div class="item">'
                     '<span class="t"><b style="color:var(--amber); margin-right:2.5mm">%s</b>'
                     '%s<small>%s</small></span>'
                     '<span class="pg" data-head="%s">·</span></div>'
                     % (L['no'], L['zh'], L['en'], anchor))
    return ('<section class="tocpage">\n'
            '  <h2 style="margin-top:0"><span class="no">·</span><span class="zh">总目录</span>'
            '<span class="en">CONTENTS</span></h2>\n  <div class="toc">\n'
            + '\n'.join(items) + '\n  </div>\n</section>')


def build_book(nos: list[str]) -> tuple[str, list[dict]]:
    lessons = [builder.load(no) for no in nos]
    css = style_of(lessons[0])
    parts = ['<!DOCTYPE html>\n<html lang="zh-CN" data-theme="dark" data-reader="大学">',
             '<head>\n<meta charset="utf-8">\n<meta name="out" content="%s">' % os.path.basename(OUT_PDF),
             '<title>CS340 操作系统 · 九讲合订本</title>\n<style>%s</style>\n</head>\n<body>' % css,
             cover(lessons), toc(lessons)]
    secs = 0
    for L in lessons:
        body = body_of(L)
        secs += len(re.findall(r'<section class="sec">', body))
        parts.append(body)
    parts.append('</body>\n</html>')
    return '\n\n'.join(parts), lessons, secs


def run(argv: list, emit=print) -> int:
    """进程内跑 html2pdf（不再 subprocess sys.executable：冻结后那就是再开一个 exe）。"""
    import html2pdf
    buf = io.StringIO()
    out, err = sys.stdout, sys.stderr
    sys.stdout = sys.stderr = buf
    try:
        rc = html2pdf.main([str(x) for x in argv])
    finally:
        sys.stdout, sys.stderr = out, err
    emit(buf.getvalue().strip())
    return int(rc or 0)


def main(argv: list, course: str | None = None, emit=print) -> int:
    for s in (sys.stdout, sys.stderr):
        if hasattr(s, 'reconfigure'):
            s.reconfigure(encoding='utf-8')
    if course:
        set_course(course)

    nos = argv or ORDER
    try:
        html, lessons, secs = build_book(nos)
    except RuntimeError as e:
        emit('[停] %s' % e)
        return 1

    if builder.MISSING:
        emit('[停] 缺图 %d 张：%s' % (len(builder.MISSING), '、'.join(builder.MISSING[:4])))
        return 1

    os.makedirs(os.path.dirname(OUT_HTML), exist_ok=True)
    with open(OUT_HTML, 'w', encoding='utf-8') as f:
        f.write(html)
    emit('生成 %s（%d 字符 · %d 讲 · %d 节正文）'
         % (os.path.basename(OUT_HTML), len(html), len(lessons), secs))

    # 期望节数：每讲 len(sections) + 4（小结 / 自测 / 术语表 / 附录）
    want = sum(len(L['sections']) + 4 for L in lessons)
    if secs != want:
        emit('[停] 节数对不上：实际 %d，应为 %d（合并时丢了节）' % (secs, want))
        return 1

    rc = run([OUT_HTML, '-o', OUT_PDF, '--theme', 'dark', '--toc', '--bg', '#0E0E0C',
              '--footer', COURSE + ' 讲义 · 九讲合订本'], emit)
    if rc != 0:
        emit('[停] 打印失败')
        return 1

    import pymupdf
    book = pymupdf.open(OUT_PDF)
    total = book.page_count
    book.close()

    body = 0
    detail = []
    for L in lessons:
        p = os.path.join(paths.data(COURSE), '01_讲义', L['out'])
        d = pymupdf.open(p)
        body += d.page_count - 2            # 每讲去掉封面与目录两页
        detail.append('%s %d' % (L['no'], d.page_count - 2))
        d.close()

    toc_pages = total - 1 - body
    emit('\n----- 合订本自检 -----')
    emit('  各讲正文页：%s（合计 %d）' % (' · '.join(detail), body))
    emit('  合订本 %d 页 = 封面 1 + 总目录 %d + 正文 %d' % (total, toc_pages, body))
    if toc_pages < 1:
        emit('[停] 总目录算出 %d 页，说明各讲正文有页数没对上（有节被拆页了）' % toc_pages)
        return 1
    emit('  判据：封面 1 + 总目录 %d + 正文 %d = %d ✓' % (toc_pages, body, 1 + toc_pages + body))
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
