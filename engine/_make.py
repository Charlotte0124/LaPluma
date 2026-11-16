# -*- coding: utf-8 -*-
"""一讲一条命令：生成 HTML → 术语每节首次附英 → 内容门 → 打 PDF → 版式门。

    python CS340\\_make.py L02

为什么用 Python 而不是 .ps1：本仓的 .ps1 必须是 UTF-8 with BOM，随手写会按 GBK 读中文；
Python 源文件是 UTF-8 无 BOM，照原样就能跑。
"""
from __future__ import annotations

import importlib
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'tools', 'print'))
sys.path.insert(0, os.path.join(ROOT, 'engine'))

from terms import attach_first_per_section  # noqa: E402
from _split_long import split_long  # noqa: E402


def run(cmd):
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding='utf-8', errors='replace')
    return p.returncode, (p.stdout or '') + (p.stderr or '')


def main(argv):
    if not argv:
        print('用法: python CS340\\_make.py L02 [L03 ...]')
        return 2
    import _build_讲义 as builder  # 中文模块名，靠 sys.path 直接 import

    for no in argv:
        print('=' * 60)
        print('## %s' % no)
        lesson = builder.load(no)
        src = os.path.join(ROOT, 'CS340', '06_笔记', '%s_零基础_讲义_源.html' % no)
        html = builder.build(lesson)
        html2, n = attach_first_per_section(html)
        html2, ns = split_long(html2)
        open(src, 'w', encoding='utf-8').write(html2)
        print('生成 %s（%d 字符，术语附英 %d 处，拆长段 %d 处）' % (os.path.basename(src), len(html2), n, ns))

        rc, out = run([sys.executable, os.path.join('tools', 'print', 'audit_lesson.py'),
                       '--content', '--file', src])
        print(out.strip())
        if rc != 0:
            print('[停] 内容门未过，先修源')
            return 1

        pdf = os.path.join(ROOT, 'CS340', '01_讲义', lesson['out'])
        rc, out = run([sys.executable, os.path.join('tools', 'print', 'html2pdf.py'), src,
                       '-o', pdf, '--theme', 'dark', '--toc', '--bg', '#0E0E0C',
                       '--footer', '%s %s · %s' % (lesson['code'], no, lesson['zh'])])
        print(out.strip().splitlines()[-1] if out.strip() else '(no output)')
        if rc != 0:
            print('[停] 打印失败')
            return 1

        rc, out = run([sys.executable, os.path.join('tools', 'print', 'audit_lesson.py'), 'CS340'])
        head = [l for l in out.strip().splitlines() if lesson['out'] in l or l.strip().startswith(('OK', 'WARN', 'FAIL', '✗', '!'))]
        print('\n'.join(head))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
