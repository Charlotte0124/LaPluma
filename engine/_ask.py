# -*- coding: utf-8 -*-
"""问课件：在这一讲的内容数据里找相关片段，拼成带出处的提问包。

    python engine\\_ask.py L05 "生产者消费者两行 down 的顺序为什么不能反"        # 只做检索（不花钱）
    python engine\\_ask.py L05 "…" --ask                                   # 真调模型（会花钱）
    python engine\\_ask.py L05 --dump                                      # 看这一讲被切成几段

为什么要它：讲义数据本来就是结构化的（节 → 块），所以「问课件」不需要向量库——
按节切段，用词命中打分挑几段，把节号与课件页码一起给模型，回答就能标出处、能回原页核对。

边界（写在前面，别当成全知）
  · 只在**这一讲**的数据里找，不跨讲、不联网。
  · 找不到证据时应当回答「没找到」，而不是编。脚本判不了它编没编，得人看。
"""
from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import paths  # noqa: E402  路径双根（见仓根 paths.py）：本模块只需要只读资源
sys.path.insert(0, paths.res('engine'))
sys.path.insert(0, paths.res('api'))

import _build_讲义 as builder  # noqa: E402

TOP_K = 5
FRAG_CHARS = 420


def _flat(html: str) -> str:
    s = re.sub(r'<svg.*?</svg>', ' ', html, flags=re.S)
    s = re.sub(r'<[^>]+>', '', s)
    s = s.replace('&lt;', '<').replace('&gt;', '>').replace('&amp;', '&').replace('&nbsp;', ' ')
    return re.sub(r'\s+', ' ', s).strip()


def _pages(text: str) -> list[str]:
    return sorted(set(re.findall(r'课件\s*p\.\s*(\d+)', text)), key=int)


def fragments(lesson: dict) -> list[dict]:
    """把一讲切成「节 + 块」级片段，每段带元数据（节号/标题/类型/课件页码）。"""
    out = []
    for s in lesson['sections']:
        head = '§%s %s（%s）' % (s['no'], s['zh'], s['en'])
        if s.get('lec'):
            out.append({'sec': s['no'], 'title': s['zh'], 'kind': '讲法',
                        'text': _flat(s['lec']), 'head': head})
        for b in s['body']:
            kind, text = b[0], ''
            if kind == 'p':
                text = _flat(b[1])
            elif kind == 'q':
                text = _flat(b[1]) + '（%s）' % b[2]
            elif kind == 'code':
                text = _flat(b[2]) + (('　说明：' + _flat(b[3])) if len(b) > 3 and b[3] else '')
            elif kind == 'eg':
                text = '题：%s 步骤：%s 答案：%s' % (_flat(b[1]), '；'.join(_flat(x) for x in b[2]), _flat(b[3]))
            elif kind == 'svg':
                text = '图：%s' % _flat(b[2])
            elif kind == 'table':
                text = '表：' + '；'.join(_flat(' | '.join(r)) for r in b[2])
            elif kind == 'note':
                text = '%s：%s' % (_flat(b[1]), _flat(b[2]))
            elif kind in ('ul', 'ol'):
                text = '；'.join(_flat(x) for x in b[1])
            elif kind == 'h3':
                text = _flat(b[1])
            if not text:
                continue
            out.append({'sec': s['no'], 'title': s['zh'], 'kind': kind,
                        'text': text, 'head': head})
    return out


def _terms(q: str) -> list[str]:
    """问题切成检索词：中文按 2–4 字滑窗 + 英文单词，去掉常见虚词。"""
    stop = set('的是了在有和与怎么为什么吗呢请问如何多少什么这那一个不不能可以要会就都也很还'
               '把被让给对从到为我你他它们里上下中前后后么呀啊吧哦嗯')
    words = set(re.findall(r'[A-Za-z_][A-Za-z0-9_#+.\-]{1,}', q))
    zh = re.sub(r'[^\u4e00-\u9fff]', ' ', q)
    for seg in zh.split():
        for n in (2, 3, 4):
            for i in range(len(seg) - n + 1):
                w = seg[i:i + n]
                if any(c in stop for c in w):
                    continue
                words.add(w)
    return sorted(words)


def _wants_overview(q: str) -> bool:
    """问的是「这一讲讲什么」这类整体问题（问题本身往往没有能命中正文的实词）。"""
    return bool(re.search(r'(说什么|讲什么|讲了什么|讲啥|说啥|说的啥|是什么|干啥|总结|概括|概述|概要|内容|目录|提纲|重点|要点|梳理|介绍)', q or ''))


def outline(lesson: dict, top_k: int = TOP_K) -> list[dict]:
    """检索零命中时的兜底：本讲目录 + 前几节开头。

    2026-11-23 用户实测：在会话里问「L01 在说什么」，旧实现把「在说什么」全当虚词滤掉，
    正文里又没有「L01」三个字，于是返回空片段，模型只能回「这讲里没写」。
    整体问题要的是结构与主题，应该给目录，而不是零上下文。
    """
    secs = lesson.get('sections') or []
    if not secs:
        return []
    heads = '；'.join('§%s %s' % (s.get('no'), s.get('zh')) for s in secs)
    out = [{'score': 0, 'sec': '全讲', 'title': '本讲目录', 'kind': '大纲',
            'pages': [], 'text': '本讲共 %d 节：%s。' % (len(secs), heads)}]
    for f in fragments(lesson):
        if len(out) >= max(1, top_k):
            break
        out.append({'score': 0, 'sec': f['sec'], 'title': f['title'], 'kind': '大纲',
                    'pages': _pages(f['text']), 'text': f['text'][:240]})
    return out


def search(lesson: dict, question: str, top_k: int = TOP_K) -> list[dict]:
    frags = fragments(lesson)
    terms = _terms(question)
    scored = []
    for f in frags:
        t = f['text']
        hit = 0
        for w in terms:
            c = t.count(w)
            if c:
                hit += min(c, 4) * (2 if len(w) >= 3 else 1)
        # 标题命中加权（问题直接点了节名）
        if any(len(w) >= 3 and w in f['title'] for w in terms):
            hit += 6
        if hit:
            scored.append((hit, f))
    scored.sort(key=lambda x: (-x[0], x[1]['sec']))
    picked = []
    for score, f in scored[:top_k]:
        picked.append({'score': score, 'sec': f['sec'], 'title': f['title'],
                       'kind': f['kind'], 'pages': _pages(f['text']),
                       'text': f['text'][:FRAG_CHARS]})
    if not picked and (_wants_overview(question) or not terms):
        picked = outline(lesson, top_k)
    return picked


def build_prompt(lesson: dict, question: str, picked: list[dict]) -> list[dict]:
    ctx = []
    for i, p in enumerate(picked, 1):
        pg = ('　课件 p.%s' % '、p.'.join(p['pages'])) if p['pages'] else ''
        ctx.append('[%d] §%s %s（%s）%s\n%s' % (i, p['sec'], p['title'], p['kind'], pg, p['text']))
    outline_only = bool(picked) and all(p.get('kind') == '大纲' for p in picked)
    system = (
        '你是这门课讲义的答疑助手。只能依据下面给出的讲义片段回答。\n'
        '规则：① 先给一句结论，再展开；② 每个关键结论后面标出处，格式【§节号 课件 p.N】；\n'
        '③ 片段里没有的内容就直说「这讲里没写」，不要靠常识补；④ 涉及代码时给出能跑的最小写法；\n'
        '⑤ 用中文，别客套。')
    if outline_only:
        system += ('\n⑥ 这一问没有命中具体段落，下面给的是本讲目录与各节开头：'
                   '可以据此概括主题和结构，但没有的细节不要编，也不要假造页码。')
    user = ('讲义：《%s》%s（%s）\n\n可用片段：\n%s\n\n问题：%s'
            % (lesson['code'], lesson['no'], lesson['zh'], '\n\n'.join(ctx) or '（没有检索到相关片段）', question))
    return [{'role': 'system', 'content': system}, {'role': 'user', 'content': user}]


def answer(lesson: dict, question: str, model: str | None = None) -> dict:
    picked = search(lesson, question)
    messages = build_prompt(lesson, question, picked)
    import client as api_client
    out = api_client.chat(messages, model=model, temperature=0.3, max_tokens=900)
    return {'ok': True, 'text': out['text'], 'model': out['model'], 'seconds': out['seconds'],
            'usage': out.get('usage', {}), 'refs': picked}


def main(argv: list[str]) -> int:
    for s in (sys.stdout, sys.stderr):
        if hasattr(s, 'reconfigure'):
            s.reconfigure(encoding='utf-8')
    if not argv:
        print(__doc__)
        return 2
    no = argv[0]
    lesson = builder.load(no)
    if '--dump' in argv:
        frags = fragments(lesson)
        print('%s 共 %d 段' % (no, len(frags)))
        for f in frags[:8]:
            print('  §%-2s %-8s %4d 字  %s' % (f['sec'], f['kind'], len(f['text']), f['text'][:40]))
        return 0
    q = next((a for a in argv[1:] if not a.startswith('-')), '')
    if not q:
        print('缺问题。例：python engine\\_ask.py L05 "信号量初值 0 时 down 会怎样"')
        return 2
    picked = search(lesson, q)
    print('问题：%s' % q)
    print('命中 %d 段：' % len(picked))
    for p in picked:
        print('  §%-2s %-6s %5d 分  课件 p.%s  %s'
              % (p['sec'], p['kind'], p['score'], '、'.join(p['pages']) or '—', p['text'][:44]))
    if '--ask' not in argv:
        print('\n（只做检索，没调模型；加 --ask 才会真问，会花钱）')
        msgs = build_prompt(lesson, q, picked)
        print('提问包 %d 字符' % sum(len(m['content']) for m in msgs))
        return 0
    out = answer(lesson, q)
    print('\n----- 回答（%s · %.1fs）-----' % (out['model'], out['seconds']))
    print(out['text'])
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
