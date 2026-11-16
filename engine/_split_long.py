# -*- coding: utf-8 -*-
"""长段自动拆分（内容门 para_chars=210）。

为什么放在生成器流水线里：讲义源每次都是脚本重生成的，手工拆段会在下一次构建被覆盖。
所以拆段必须是「构建后自动跑的一步」，这样哪一讲都不会退回去。
"""
import re

TH = 210


def _split_para(open_tag, inner):
    toks = re.split(r'(<[^>]+>)', inner)
    cnt = 0
    best = None          # (优先级, -cnt, i, off)；优先级越小越好
    fallback = None      # 找不到标点时，在接近上限的位置硬切
    for i, t in enumerate(toks):
        if t.startswith('<'):
            continue
        for j, ch in enumerate(t):
            cnt += 1
            if cnt > TH:
                break
            if 150 <= cnt <= 205:
                fallback = (i, j + 1)
            if ch in '。；，：、':
                pri = 0 if ch == '。' else (1 if ch == '；' else 2)
                if cnt >= 110:
                    cand = (pri, -cnt, i, j + 1)
                    if best is None or cand < best:
                        best = cand
    if best is None:
        if fallback is None:
            return None
        i, off = fallback
    else:
        _, _, i, off = best
    left = ''.join(toks[:i]) + toks[i][:off]
    right = (toks[i][off:] + ''.join(toks[i + 1:])).strip()
    if len(re.sub(r'<[^>]+>', '', right)) < 10:
        return None
    return '%s%s</p>\n<p>%s</p>' % (open_tag, left, right)


def split_long(html, rounds=4):
    n = 0
    for _ in range(rounds):
        changed = 0

        def rep(m):
            nonlocal changed
            open_tag, inner = m.group(1), m.group(2)
            text = re.sub(r'<[^>]+>', '', inner)
            if len(text) <= TH:
                return m.group(0)
            new = _split_para(open_tag, inner)
            if not new:
                return m.group(0)
            changed += 1
            return new

        html = re.sub(r'(<p[^>]*>)(.*?)</p>', rep, html, flags=re.S)
        n += changed
        if not changed:
            break
    return html, n
