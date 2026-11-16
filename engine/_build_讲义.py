# -*- coding: utf-8 -*-
"""CS340 讲义生成器：一份数据 → 一份讲义源 HTML（深色主题、A4 打印、目录自动回填）。

为什么用生成器：8 讲共用同一套 CSS、封面、目录、术语表、附录结构。
只写「这一讲讲什么」，版式与固定件由脚本产出；改版式只改这一处。

用法：
    python CS340\\_build_讲义.py L02        # 生成 CS340\\06_笔记\\L02_零基础_讲义_源.html
    python CS340\\_build_讲义.py L02 L03    # 一次多份

数据文件放在 CS340\\_lessons\\<编号>.py，变量名 LESSON，结构见文件末尾注释。
术语附英不在这里做：生成后统一跑 tools\\print\\terms.py（同一口径，L01 也是这么来的）。
"""
from __future__ import annotations

import importlib.util
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CSS = """
  :root{
    --bg:#0E0E0C; --card:#161614; --text:#F4F1E6; --dim:#A8A498;
    --mute:#6E6B61; --line:#2A2A24; --amber:#E7C246; --code:#121210;
  }
  *{box-sizing:border-box}
  html{background:var(--bg)}
  body{
    margin:0; padding:0; background:transparent; color:var(--text);
    font-family:"Microsoft YaHei","Source Han Sans SC","PingFang SC",system-ui,sans-serif;
    font-size:10.5pt; line-height:1.78;
    -webkit-print-color-adjust:exact; print-color-adjust:exact;
  }
  @page{size:A4; margin:15mm 16mm 16mm}
  h2,h3{break-after:avoid}
  h2{break-before:page}
  .lec{margin:3.4mm 0; padding:2mm 0 2mm 4mm; border-left:2px solid var(--line);
       color:var(--text); font-size:10.3pt}
  .lec b:first-child{color:var(--amber)}
  .pb{break-before:page}
  p,li{break-inside:avoid}
  section.sec{break-inside:avoid}
  p,li{orphans:2; widows:2}
  figure,.eq,.note,blockquote,table.sym{break-inside:avoid}
  tr{break-inside:avoid}
  table{break-inside:auto}
  .cover{height:calc(297mm - 31mm); display:flex; flex-direction:column; justify-content:center;
         break-after:page}
  .cover .kicker{color:var(--amber); font-size:9pt; letter-spacing:.14em}
  .cover h1{font-size:26pt; line-height:1.3; margin:5mm 0 3mm; font-weight:600}
  .cover .sub{color:var(--dim); font-size:10.5pt; line-height:1.9; margin-bottom:12mm}
  .meta{border:1px solid var(--line); border-radius:8px; background:var(--card); padding:5mm 6mm}
  .meta .row{display:grid; grid-template-columns:24mm 1fr; gap:4mm; font-size:9.2pt;
             color:var(--dim); padding:1.1mm 0}
  .meta .row b{color:var(--text); font-weight:500}
  .tocpage{break-after:page}
  .toc{margin-top:2mm}
  .toc .item{display:grid; grid-template-columns:9mm 1fr 10mm; gap:2mm; align-items:baseline;
             padding:1.4mm 0; border-bottom:1px dotted var(--line)}
  .toc .no{color:var(--amber); font-variant-numeric:tabular-nums}
  .toc .t{color:var(--text)}
  .toc .t small{color:var(--mute); font-size:8.4pt; margin-left:2.5mm; letter-spacing:.03em}
  .toc .pg{color:var(--dim); font-variant-numeric:tabular-nums; text-align:right}
  h2{display:grid; grid-template-columns:11mm 1fr; column-gap:4mm; align-items:baseline;
     margin:7mm 0 3mm; padding-top:4mm; border-top:1px solid var(--line)}
  h2 .no{grid-row:1; color:var(--amber); font-size:11pt; font-weight:600;
         font-variant-numeric:tabular-nums}
  h2 .zh{grid-column:2; font-size:14.5pt; font-weight:600; line-height:1.4}
  h2 .en{grid-column:2; color:var(--mute); font-size:8.8pt; letter-spacing:.05em; margin-top:.8mm}
  h3{font-size:11.2pt; font-weight:600; margin:6mm 0 1.5mm}
  p{margin:2.6mm 0}
  b,strong{font-weight:600}
  em{font-style:normal; color:var(--amber)}
  sub,sup{font-size:.74em; line-height:0}
  ul,ol{margin:2.2mm 0; padding-left:5.5mm}
  li{margin:1.4mm 0; list-style:none; position:relative; padding-left:4mm}
  li::before{content:"\u2013"; position:absolute; left:0; color:var(--mute)}
  ol{counter-reset:n}
  ol li{counter-increment:n}
  ol li::before{content:counter(n) "."; color:var(--amber); font-variant-numeric:tabular-nums}
  blockquote{margin:3.2mm 0; padding:3mm 4mm; background:var(--card); border-radius:8px;
             border-left:2px solid var(--amber)}
  blockquote .en{display:block; font-family:Georgia,"Times New Roman",serif; font-size:9.9pt;
                 color:var(--text); line-height:1.7}
  blockquote .ref{display:block; text-align:right; color:var(--mute); font-size:8.6pt; margin-top:1.2mm}
  .eq{margin:3mm 0 0; padding:2.8mm 4mm; background:var(--code); border:1px solid var(--line);
      border-radius:8px; font-family:"Cambria Math",Cambria,Georgia,"Times New Roman",serif;
      font-size:10.4pt; line-height:2.05; white-space:pre-wrap; overflow-wrap:anywhere}
  table.sym{width:100%; border-collapse:collapse; margin:0 0 3.4mm; font-size:8.8pt;
            table-layout:fixed}
  table.sym th{background:transparent; color:var(--mute); font-weight:600;
               border:none; border-bottom:1px solid var(--line); padding:1.2mm 2.2mm; text-align:left}
  table.sym td{border:none; border-bottom:1px dotted #22221C; padding:1.2mm 2.2mm;
               color:var(--dim); vertical-align:top; overflow-wrap:anywhere}
  table.sym td:first-child{color:var(--amber); white-space:nowrap}
  .note{margin:3.2mm 0; padding:3mm 4mm; background:var(--card); border:1px solid var(--line);
        border-radius:8px; font-size:9.7pt; color:var(--dim)}
  .note .tag{display:inline-block; color:var(--amber); font-size:8.4pt; letter-spacing:.06em;
             margin-right:2mm; border:1px solid var(--line); border-radius:5px; padding:.2mm 1.6mm}
  figure{margin:3.6mm 0}
  pre.code{margin:3mm 0; padding:3mm 4mm; background:#0F0F0D; border:1px solid var(--line);
           border-left:3px solid var(--amber); border-radius:6px; overflow-wrap:anywhere;
           white-space:pre-wrap; font-family:Consolas,"Courier New",monospace; font-size:8.9pt;
           line-height:1.75; color:#E4E0D4}
  pre.code .cap{display:block; color:var(--mute); font-size:8pt; margin-bottom:1.4mm;
                font-family:"Microsoft YaHei",sans-serif}
  .eg{margin:3.4mm 0; padding:3mm 4mm; background:var(--card); border:1px solid var(--line);
      border-left:3px solid #8FA7B8; border-radius:8px; break-inside:avoid}
  .eg .ask{font-weight:600; color:var(--text); margin-bottom:1.6mm; font-size:10pt}
  .eg ol{margin:0; padding-left:6mm; font-size:9.3pt; line-height:1.8; color:var(--dim)}
  .eg .a{margin-top:1.8mm; color:var(--amber); font-size:9.3pt}
  figure.diagram{margin:3.6mm 0; text-align:center; break-inside:avoid}
  figure.diagram svg{display:block; margin:0 auto; max-width:100%; height:auto}
  figure img{display:block; margin:0 auto; width:auto; max-width:100%; max-height:66mm;
             border:1px solid var(--line); border-radius:8px; background:#fff}
  figcaption{color:var(--mute); font-size:8.6pt; margin-top:1.6mm; text-align:center}
  table:not(.sym){width:100%; border-collapse:collapse; margin:3mm 0; font-size:9.2pt;
                  table-layout:fixed}
  table:not(.sym) th,table:not(.sym) td{border:1px solid var(--line); padding:1.8mm 2.2mm;
                  text-align:left; vertical-align:top; overflow-wrap:anywhere}
  table:not(.sym) th{background:var(--card); color:var(--dim); font-weight:600}
  thead{display:table-header-group}
  td .en{display:block; color:var(--mute); font-size:8.4pt}
  .src{color:var(--mute); font-size:8.8pt}
  .q{margin:3mm 0}
  .q b{color:var(--amber)}
  .ans{color:var(--dim); font-size:9.6pt; margin:1.6mm 0}
  .self{margin-top:6mm; padding-top:3mm; border-top:1px solid var(--line)}
  table.glossary td:first-child{white-space:nowrap}
  table.glossary td,table.glossary th{padding:.7mm 2.2mm; font-size:8.4pt}
  table.glossary td:nth-child(3){white-space:nowrap}
"""


def esc(s: str) -> str:
    return s


def render_block(b):
    kind = b[0]
    if kind == 'p':
        return '<p>%s</p>' % b[1]
    if kind == 'h3':
        return '<h3>%s</h3>' % b[1]
    if kind == 'q':                     # 英文原句 + 页码
        return ('<blockquote><span class="en">%s</span>\n<span class="ref">%s</span></blockquote>'
                % (b[1], b[2]))
    if kind == 'fig':
        cap = b[2]
        return ('<figure>\n  <img src="assets/%s" alt="%s">\n  <figcaption>%s</figcaption>\n</figure>'
                % (b[1], cap.replace('"', ''), cap))
    if kind == 'ul':
        return '<ul>\n' + '\n'.join('  <li>%s</li>' % x for x in b[1]) + '\n</ul>'
    if kind == 'ol':
        return '<ol>\n' + '\n'.join('  <li>%s</li>' % x for x in b[1]) + '\n</ol>'
    if kind == 'code':                  # (lang 标签, 代码文本, 说明)
        esc = (b[2].replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;'))
        cap = ('<span class="cap">%s</span>' % b[3]) if len(b) > 3 and b[3] else ''
        return '<pre class="code">%s%s</pre>' % (cap, esc)
    if kind == 'eg':                    # (题面, [步骤], 答案)
        steps = ''.join('<li>%s</li>' % x for x in b[2])
        return ('<div class="eg"><div class="ask">%s</div><ol>%s</ol><div class="a">%s</div></div>'
                % (b[1], steps, b[3]))
    if kind == 'svg':                   # (svg 源码, 图注)
        return '<figure class="diagram">%s<figcaption>%s</figcaption></figure>' % (b[1], b[2])
    if kind == 'note':
        return '<div class="note"><span class="tag">%s</span>%s</div>' % (b[1], b[2])
    if kind == 'table':                 # (head, [rows], [widths])
        head, rows, widths = b[1], b[2], b[3]
        th = ''.join('<th style="width:%s">%s</th>' % (widths[i], h) for i, h in enumerate(head))
        trs = ['<tr>%s</tr>' % th]
        for r in rows:
            trs.append('<tr>' + ''.join('<td>%s</td>' % c for c in r) + '</tr>')
        return '<table>\n' + '\n'.join(trs) + '\n</table>'
    if kind == 'table_sym':
        head, rows = b[1], b[2]
        trs = ['<tr>' + ''.join('<th style="%s">%s</th>' % (st, lb) for st, lb in head) + '</tr>']
        for r in rows:
            trs.append('<tr>' + ''.join('<td>%s</td>' % c for c in r) + '</tr>')
        return '<table class="sym">\n' + '\n'.join(trs) + '\n</table>'
    if kind == 'pb':
        return '<div class="pb"></div>'
    if kind == 'eq':                     # 公式块（内容门：含 = 的 .eq 后 400 字符内必须有 table.sym）
        return '<div class="eq">%s</div>' % b[1]
    raise ValueError('unknown block: %r' % (kind,))


def build(lesson: dict) -> str:
    L = lesson
    code, no = L['code'], L['no']
    out = []
    out.append('<!DOCTYPE html>\n<html lang="zh-CN" data-theme="dark" data-reader="大学">')
    out.append('<head>\n<meta charset="utf-8">\n<meta name="out" content="%s">' % L['out'])
    out.append('<title>%s %s · 讲义</title>\n<style>%s</style>\n</head>\n<body>' % (no, L['zh'], CSS))

    # 封面
    meta = '\n'.join('    <div class="row"><b>%s</b><span>%s</span></div>' % (k, v) for k, v in L['meta'])
    out.append(
        '<section class="cover">\n'
        '  <div class="kicker">%s · LECTURE %s</div>\n'
        '  <h1>%s</h1>\n'
        '  <div class="sub">%s<br>\n  %s</div>\n'
        '  <div class="meta">\n%s\n  </div>\n</section>'
        % (code, no.lstrip('L'), L['zh'], L['en'], L['sub'], meta))

    # 目录（自动）
    items = []
    for s in L['sections']:
        items.append('    <div class="item"><span class="no">%s</span><span class="t">%s<small>%s</small></span>'
                     '<span class="pg" data-head="%s">·</span></div>'
                     % (s['no'], s['zh'], s['en'], s['zh']))
    for s in L['tail']:
        items.append('    <div class="item"><span class="no">%s</span><span class="t">%s<small>%s</small></span>'
                     '<span class="pg" data-head="%s">·</span></div>'
                     % (s['no'], s['zh'], s['en'], s['zh']))
    out.append('<section class="tocpage">\n'
               '  <h2 style="margin-top:0"><span class="no">·</span><span class="zh">目录</span>'
               '<span class="en">CONTENTS</span></h2>\n  <div class="toc">\n'
               + '\n'.join(items) + '\n  </div>\n</section>')

    # 正文章节
    for s in L['sections']:
        body = '\n'.join(render_block(b) for b in s['body'])
        lec = ('<p class="lec"><b>讲法。</b>%s</p>\n' % s['lec']) if s.get('lec') else ''
        out.append('<section class="sec">\n'
                   '<h2><span class="no">%s</span><span class="zh">%s</span><span class="en">%s</span></h2>\n'
                   '%s%s\n</section>' % (s['no'], s['zh'], s['en'], lec, body))

    # 小结
    sm = L['summary']
    th = ''.join('<th style="width:%s">%s</th>' % (sm['head_widths'][i], h)
                 for i, h in enumerate(sm['head']))
    rows = '\n'.join('<tr>' + ''.join('<td>%s</td>' % c for c in r) + '</tr>' for r in sm['rows'])
    out.append('<section class="sec">\n<h2><span class="no">%s</span><span class="zh">%s</span><span class="en">%s</span></h2>\n'
               '%s<table>\n<tr>%s</tr>\n%s\n</table>\n<p>%s</p>\n</section>'
               % (sm['no'], sm['zh'], sm['en'],
                  ('<p class="lec"><b>讲法。</b>%s</p>\n' % sm['lec']) if sm.get('lec') else '',
                  th, rows, sm['tail']))

    # 自测
    q = L['quiz']
    body = []
    for i, (qq, aa) in enumerate(q['items'], 1):
        body.append('<div class="q"><b>Q%d.</b> %s</div>\n<div class="ans">%s</div>' % (i, qq, aa))
    out.append('<section class="sec">\n<h2><span class="no">%s</span><span class="zh">%s</span><span class="en">%s</span></h2>\n'
               '<p class="lec"><b>讲法。</b>%s</p>\n\n%s\n</section>'
               % (q['no'], q['zh'], q['en'], q['lec'], '\n\n'.join(body)))

    # 术语表
    g = L['glossary']
    grows = '\n'.join('  <tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>' % r for r in g['rows'])
    out.append('<section class="sec">\n<h2><span class="no">%s</span><span class="zh">%s</span><span class="en">%s</span></h2>\n'
               '<p class="lec"><b>讲法。</b>%s</p>\n\n'
               '<table class="glossary">\n'
               '  <colgroup><col style="width:20%%"><col style="width:27%%">'
               '<col style="width:15%%"><col style="width:38%%"></colgroup>\n'
               '  <thead><tr><th>中文</th><th>English</th><th>页码</th><th>备注</th></tr></thead>\n'
               '  <tbody>\n%s\n  </tbody>\n</table>\n</section>'
               % (g['no'], g['zh'], g['en'], g['lec'], grows))

    # 附录
    a = L['appendix']
    srows = '\n'.join('<tr>' + ''.join('<td>%s</td>' % c for c in r) + '</tr>' for r in a['symbols'])
    myths = '\n'.join('<li>%s</li>' % m for m in a['myths'])
    out.append('<section class="sec">\n<h2><span class="no">%s</span><span class="zh">%s</span><span class="en">%s</span></h2>\n'
               '<p class="lec"><b>讲法。</b>%s</p>\n\n'
               '<table class="sym">\n<tr><th>符号 / 缩写</th><th>读法·含义</th><th>出处</th></tr>\n%s\n</table>\n\n'
               '<h3>%s</h3>\n<ol>\n%s\n</ol>\n</section>'
               % (a['no'], a['zh'], a['en'], a['lec'], srows, a['myths_title'], myths))

    out.append('\n</body>\n</html>\n')
    return '\n\n'.join(out)


def load(no: str) -> dict:
    path = os.path.join(ROOT, 'CS340', '_lessons', no + '.py')
    spec = importlib.util.spec_from_file_location('lesson_' + no, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.LESSON


def main(argv):
    if not argv:
        print('用法: python CS340\\_build_讲义.py L02 [L03 ...]')
        return 2
    for no in argv:
        lesson = load(no)
        html = build(lesson)
        dst = os.path.join(ROOT, 'CS340', '06_笔记', '%s_零基础_讲义_源.html' % no)
        open(dst, 'w', encoding='utf-8').write(html)
        print('已生成 %s（%d 字符）' % (dst, len(html)))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
