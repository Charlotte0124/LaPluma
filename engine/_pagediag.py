# -*- coding: utf-8 -*-
"""版面诊断：逐页给「填充高度 + 首行字体字号 + 首行文字」，并标出页首是正文的页。

    python CS340\\_pagediag.py L02
"""
import os
import sys

import pymupdf

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 2026-11-17：课程代码不再写死（示例课程 / 截图演示用 PLUMA_COURSE 切，默认仍是 CS340）
COURSE = os.environ.get("PLUMA_COURSE") or "CS340"


def main(no):
    pdf = None
    d = os.path.join(ROOT, COURSE, '01_讲义')
    for f in os.listdir(d):
        if f.startswith(no) and f.endswith('.pdf') and '讲义' in f:
            pdf = os.path.join(d, f)
    if not pdf:
        print('找不到 %s 的讲义 PDF' % no)
        return 1
    doc = pymupdf.open(pdf)
    print(os.path.basename(pdf), 'pages=%d' % doc.page_count)
    for i in range(doc.page_count):
        p = doc[i]
        rows = {}
        for b in p.get_text('dict')['blocks']:
            for l in b.get('lines', []):
                for sp in l['spans']:
                    if sp['text'].strip() and sp['size'] > 8:
                        rows.setdefault(round(l['bbox'][1], 1), sp)
        if not rows:
            print('%2d  (empty)' % (i + 1))
            continue
        ys = sorted(rows)
        first = rows[ys[0]]
        last = rows[ys[-1]]
        flag = 'RED ' if abs(first['size'] - 10.5) < 0.2 and 'Bold' not in first['font'] else '    '
        if abs(first['size'] - 10.5) < 0.2 and 'Bold' in first['font']:
            flag = 'RED*'
        print('%2d %s bottom=%4d first=%s %.1f %s' % (
            i + 1, flag, last['bbox'][3], first['font'].split('-')[-1], first['size'],
            first['text'][:34]))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1]))
