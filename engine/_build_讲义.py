# -*- coding: utf-8 -*-
"""CS340 讲义生成器：一份数据 → 一份讲义源 HTML（深色主题、A4 打印、目录自动回填）。

为什么用生成器：8 讲共用同一套 CSS、封面、目录、术语表、附录结构。
只写「这一讲讲什么」，版式与固定件由脚本产出；改版式只改这一处。

用法：
    python CS340\\_build_讲义.py L02        # 生成 CS340\\06_笔记\\L02_零基础_讲义_源.html
    python CS340\\_build_讲义.py L02 L03    # 一次多份

数据文件放在 CS340\\_lessons\\<编号>.py，变量名 LESSON，结构见文件末尾注释。
术语附英不在这里做：生成后统一跑 tools\\print\\terms.py（同一口径，L01 也是这么来的）。

原件图（2026-11-21 加，R115）
    用户：「不是说要根据原件了吗 为什么我一点原件的图也看不到」「如有需要的话可以增加一些图片」。
    build() 开头先 ensure_figures()：按 assets\\gen\\<讲号>\\pNNN.png 修图名、给没图的节补 1 张
    （不超过课件总页数 1/3）、逐张图注补「课件 p.N」出处；一张图都没有时日志写明原因。
    图仍写绝对 file:// URI（HTML 搬到哪都能显示），缺图照旧记进 MISSING 让 _make.py 拦下。
"""
from __future__ import annotations

import importlib.util
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import paths  # noqa: E402  路径双根，见仓根 paths.py

# 2026-11-17：不再用 dirname(dirname(__file__))——冻结后那指向临时解包目录。
#   ROOT = 数据根（exe 旁的可写目录；源码运行时就是仓根，行为不变）。
ROOT = paths.DATA_ROOT
# 2026-11-17：课程代码不再写死（示例课程 / 截图演示用 PLUMA_COURSE 切，默认仍是 CS340）
COURSE = os.environ.get("PLUMA_COURSE") or "CS340"

# ── 课件页图（2026-11-16 加；2026-11-21 加 R115「原件图必须真的画出来」）────────
# 为什么要有：拆家后「课件原图」留在资料仓（80 MB），软件仓里一张都没有；
# 原先 `src="assets/…"` 是相对 HTML 的，HTML 又写在软件仓，于是 Chrome 只能画出
# 14×16 的缺图图标 —— 更坑的是它不报错，成品里就静静躺着一条白条。
# 现在：先找图，找到就写绝对 file:// URI（HTML 搬到哪都能显示），找不到就记进 MISSING，
# 由 _make.py 报「缺图」并停下，不再产出「看起来绿、其实没图」的 PDF。
# 2026-11-21 用户「为什么我一点原件的图也看不到」：只把图查出来还不够——数据里没有 fig 块
#   时讲义照样一张图都不画，而且一声不响。现在 build() 开头调 ensure_figures()：
#   修模型写错的图名、给没图的节按课件页顺序补 1 张（≤ 总页数 1/3）、逐张图注补「课件 p.N」。
ASSETS = None          # 解析到的图片目录（None = 没配置）
ASSETS_FROM = ''       # 这个目录是从哪来的（报错时好说话）
MISSING = []           # 本讲缺图的文件名
CURRENT_AVAIL = []     # 本讲可用的课件页图 [(相对 assets 的路径, 页码), …]（build 里设）
IMG_EXT = ('.png', '.jpg', '.jpeg', '.webp')


def _user_assets_map() -> dict:
    p = os.path.join(os.path.expanduser('~'), '.pluma', 'assets.json')
    try:
        import json
        with open(p, encoding='utf-8') as f:
            return json.load(f) or {}
    except Exception:
        return {}


def resolve_assets(code: str):
    """按四档顺序找课件图目录；返回 (目录 or None, 来源说明)。"""
    cands = []
    m = _user_assets_map()
    if m.get(code):
        v = m[code]
        cands.append((v if os.path.isabs(v) else os.path.join(ROOT, v),
                      '~\\.pluma\\assets.json'))
    try:
        import json
        with open(paths.data_or_res('courses.json'), encoding='utf-8') as f:
            v = (json.load(f).get(code) or {}).get('assets')
        if v:
            cands.append((v if os.path.isabs(v) else os.path.join(ROOT, v), 'courses.json'))
    except Exception:
        pass
    if os.environ.get('PLUMA_ASSETS'):
        cands.append((os.environ['PLUMA_ASSETS'], '环境变量 PLUMA_ASSETS'))
    cands.append((os.path.join(paths.course_dir(code), '06_笔记', 'assets'), '软件仓默认路径'))
    for path, src in cands:
        if os.path.isdir(path):
            return path, src
    return None, ''


def use_course(code: str) -> None:
    """切换当前课程的图片目录（build 开头调用，render_block 里的 fig 依赖它）。"""
    global ASSETS, ASSETS_FROM, MISSING
    ASSETS, ASSETS_FROM = resolve_assets(code)
    MISSING = []


def figure_files(no: str) -> list:
    """本讲可用的课件页图：优先 assets/gen/<讲号>/，兼容 assets/<讲号>/；按页码排序。

    返回 [(相对 assets 的路径, 页码), …]。文件名里的 pNNN 就是课件页码（_draft.extract_figures
    的命名口径）；认不出页码的按顺序编号，至少能补进讲义、图注不会空。
    """
    if not ASSETS:
        return []
    for d in (os.path.join(ASSETS, 'gen', no), os.path.join(ASSETS, no)):
        if not os.path.isdir(d):
            continue
        rows = []
        for fn in sorted(os.listdir(d)):
            if not fn.lower().endswith(IMG_EXT):
                continue
            m = re.search(r'p0*(\d{1,3})', fn, re.I)
            page = int(m.group(1)) if m else len(rows) + 1
            rel = os.path.relpath(os.path.join(d, fn), ASSETS).replace('\\', '/')
            rows.append((rel, page))
        if rows:
            return sorted(rows, key=lambda x: (x[1], x[0]))
    return []


def _ref_rel(ref: str) -> str:
    """把数据里的图片引用归一成「相对 assets 的路径」（绝对路径也剥回相对段）。"""
    r = str(ref or '').strip().replace('\\', '/')
    if '://' in r:                                   # file:///F:/… → F:/…
        r = r.split('://', 1)[1].lstrip('/')
    for pre in ('/06_笔记/assets/', '/assets/'):     # 绝对路径里的 asset 段也能剥掉
        if pre in r:
            r = r.split(pre, 1)[1]
            break
    while True:
        for pre in ('06_笔记/assets/', 'assets/'):
            if r.startswith(pre):
                r = r[len(pre):]
                break
        else:
            break
    while r.startswith('./'):
        r = r[2:]
    return r.lstrip('/')


def _match_fig(ref: str, avail: list) -> tuple | None:
    """图片引用 → 清单里的 (相对路径, 页码)。认：原路径 / 带 assets 前缀 / 只给文件名 / 只给页码。

    为什么认这么多：模型抄路径时会自己加前缀（assets/…）、只写文件名（p012.png）、
    或只写页码（p.12）。原来只认一字不差的路径，对不上就整块删掉——用户看到的就是
    「导出了 28 张图，讲义里一张也没有」。
    """
    if not avail:
        return None
    r = _ref_rel(ref).lower()
    if not r:
        return None
    for rel, page in avail:                          # ① 原路径 / 尾部一致
        rl = rel.lower()
        if r == rl or r.endswith('/' + rl) or rl.endswith('/' + r):
            return (rel, page)
    name = r.rsplit('/', 1)[-1]
    for rel, page in avail:                          # ② 只给文件名
        if rel.rsplit('/', 1)[-1].lower() == name:
            return (rel, page)
    m = re.search(r'(?:p\.?|第)(\d{1,3})(?:\s*页)?', r) or re.search(r'(\d{1,3})', name)
    if m:                                            # ③ 只给页码：p.12 / p012 / 第12页 / 12
        want = int(m.group(1))
        for rel, page in avail:
            if page == want:
                return (rel, page)
    return None


def _page_of_ref(ref: str) -> int:
    """图引用对应的课件页码（图注补出处用）；认不出返回 0。"""
    hit = _match_fig(ref, CURRENT_AVAIL)
    if hit:
        return hit[1]
    m = re.search(r'p0*(\d{1,3})', _ref_rel(ref), re.I)
    return int(m.group(1)) if m else 0


def _cap_with_page(cap: str, page: int) -> str:
    """图注必须带出处「课件 p.N」（R115）；数据里没写就按文件名页码补上。"""
    cap = str(cap or '').strip()
    if page and not re.search(r'课件\s*p\.\s*\d+', cap):
        if cap:
            cap = cap.rstrip('。.；;，,、)） ') + '（课件 p.%d）' % page
        else:
            cap = '原件第 %d 页（课件 p.%d）' % (page, page)
    return cap


_PAGE_TEXTS: dict = {}


def _orig_pdf(no: str):
    """这一讲对应的原件 PDF；找不到返回 None（只读，用来把「补图」选到对的一页）。"""
    try:
        import _draft                      # engine 同目录；运行时才导入（它会带 client）
        return _draft.source_of(COURSE, no)[0]
    except Exception:  # noqa: BLE001
        return None


def _page_texts(no: str, pages) -> dict:
    """页码 → 该页文字（去空白、小写）。读不到原件就返回空 dict，补图退回页序。"""
    key = (no, tuple(sorted(pages)))
    if key in _PAGE_TEXTS:
        return _PAGE_TEXTS[key]
    out = {}
    pdf = _orig_pdf(no)
    if pdf and os.path.isfile(pdf):
        try:
            import pymupdf
            with pymupdf.open(pdf) as doc:
                for p in key[1]:
                    if 1 <= p <= len(doc):
                        out[p] = re.sub(r"\s+", "", doc[p - 1].get_text("text") or "").lower()
        except Exception:  # noqa: BLE001
            out = {}
    _PAGE_TEXTS[key] = out
    return out


def _bigrams(s) -> set:
    t = re.sub(r"\s+", "", str(s or "")).lower()
    if len(t) < 2:
        return {t} if t else set()
    return {t[i:i + 2] for i in range(len(t) - 1)}


def _sec_query(sec: dict) -> str:
    """这一节「想找什么图」：标题（中英）+ 正文前几块的文字。"""
    parts = [str(sec.get('zh') or ''), str(sec.get('en') or '')]
    for b in (sec.get('body') or [])[:12]:
        if isinstance(b, (list, tuple)) and len(b) > 1 and b and b[0] != 'fig':
            parts.append(str(b[1]))
    return ''.join(parts)[:600]


def _pick_page(query: str, pending: list, texts: dict):
    """在还没用过的页里选「文字最像这一节」的一页；都不像就返回 None（调用方退回页序）。

    2026-11-23 用户要求提高「信息相关性」：以前补图是**按页序**弹一张——弹到哪页算哪页，
    和这一节内容可能毫无关系（比如讲免疫的节配了张化学式）。现在按「节标题+正文」与该页
    文字的 2-gram 重合度选页；读不到原件文字时仍然退回页序，并在日志里说明。
    """
    q = _bigrams(query)
    if not q or not texts:
        return None
    best, best_s = None, 0.0
    for item in pending:
        rel, pg = item[0], item[1]
        t = texts.get(pg) or ''
        if not t:
            continue
        tb = _bigrams(t)
        if not tb:
            continue
        s = len(q & tb) / float(len(q))
        if s > best_s:
            best, best_s = (rel, pg), s
    return best


def ensure_figures(lesson: dict, emit=print, avail: list | None = None) -> dict:
    """修图名 + 每节补图 + 图注补出处（R115，用户 2026-11-21）。

    用户原话：「不是说要根据原件了吗 为什么我一点原件的图也看不到」「如有需要的话可以增加一些图片」。
    对 lesson['sections'] 就地做三件事：
      ① 模型写错的图名按清单（原路径 / 文件名 / 页码）修回来；实在对不上才丢，丢几个、为什么写进日志；
      ② 每张图注补「课件 p.N」出处（数据里没写时）；
      ③ 某一节（§0 导读除外）一张图都没有时，按课件页顺序补 1 张；补图总量 ≤ 课件总页数的
         1/3（用户定的「不要滥补」），且同一份数据重复 build 不会越补越多。
    没图可用时也会在日志里说明原因，不再静默产出一份没图的讲义。返回统计 dict。
    """
    no = str(lesson.get('no') or '')
    if avail is None:
        avail = figure_files(no)
    secs = lesson.get('sections') or []
    stats = {'no': no, 'available': len(avail), 'model': 0, 'fixed': 0,
             'dropped': [], 'added': 0, 'used': 0, 'cap': 0,
             'total': int(lesson.get('figs_total') or 0) or len(avail), 'sections_no_fig': 0}
    # 同一份 lesson 可能被 build() 调两次（例如合订本先取正文再拼）：
    #   记下已经自动补过几张，第二次不再重复补，否则每 build 一回就多出几张图。
    added_before = int(lesson.get('figs_added') or 0)

    # 先把数据里已有的 fig 块收出来点数（后面日志要说清「数据里已有几张」）
    for s in secs:
        stats['model'] += sum(1 for b in s.get('body') or [] if b and b[0] == 'fig')

    if not avail:
        # 没有清单：已有的 fig 块原样留着（可能是绝对路径，照样能画），但要说明为什么补不了图
        if stats['model']:
            emit('[图] %s 没有可用课件页图清单（%s），已有 %d 个 fig 引用按原路径解析'
                 % (no, ASSETS or '没找到课件图目录', stats['model']))
        else:
            emit('[图] %s 这一讲没有可用课件页图（%s；先导入原件让 _draft 抽图，'
                 '或用 tools\\assets.py --set 指课件图目录）→ 讲义里不会出现原件图'
                 % (no, ASSETS or '没找到 06_笔记\\assets'))
        return stats

    # ① 修名 + ② 图注补出处
    used = set()
    for s in secs:
        body, fixed_body = list(s.get('body') or []), []
        for b in body:
            if not b or b[0] != 'fig':
                fixed_body.append(b)
                continue
            ref = b[1] if len(b) > 1 else ''
            hit = _match_fig(ref, avail)
            if not hit:
                stats['dropped'].append(str(ref))
                continue
            rel, page = hit
            if str(ref).strip().replace('\\', '/') != rel:
                stats['fixed'] += 1           # 模型写错前缀/文件名，已按清单修回来
            fixed_body.append(('fig', rel, _cap_with_page(b[2] if len(b) > 2 else '', page)))
            used.add(rel)
        s['body'] = fixed_body
    stats['used'] = len(used)
    stats['model'] = len(used)               # 数据里真正认得的图（编的/对不上的已计入 dropped）

    # ③ 没图的节（§0 导读除外，与提示词口径一致）补 1 张；
    #    自动补图总量 ≤ 课件总页数的 1/3（用户「不要滥补」），跨多次 build 也算同一个预算。
    #    2026-11-23 用户要求提高「信息相关性」：选页改成按「节内容 ↔ 该页文字」的相似度，
    #    不再按页序弹一张（弹到哪页算哪页，讲免疫的节配了张化学式那种）。读不到原件文字时退回页序。
    cap = max(1, stats['total'] // 3)
    stats['cap'] = max(0, cap - added_before)
    pending = [x for x in avail if x[0] not in used]
    texts = _page_texts(no, {x[1] for x in pending}) if pending else {}
    by_sim = 0
    for s in secs:
        if stats['added'] >= stats['cap'] or not pending:
            break
        if str(s.get('no')) == '0':
            continue                       # 导读不塞原页图：提示词也是「§0 导读除外」
        if any(b and b[0] == 'fig' for b in s.get('body') or []):
            continue
        hit = _pick_page(_sec_query(s), pending, texts)
        if hit is not None:
            pending = [x for x in pending if x != hit]
            by_sim += 1
        else:
            hit = pending.pop(0)           # 读不到原件文字 / 没有像的页 → 退回页序
        rel, page = hit
        s['body'] = list(s.get('body') or []) + [('fig', rel, '原件第 %d 页（课件 p.%d）' % (page, page))]
        stats['added'] += 1
        used.add(rel)
    if stats['added']:
        lesson['figs_added'] = added_before + stats['added']
        emit('[图] 这一轮补了 %d 张：%d 张按「节内容 ↔ 该页文字」的相似度选页%s'
             % (stats['added'], by_sim,
                '' if by_sim == stats['added'] else
                '；其余 %d 张退回页序（读不到原件文字，或没有像的页）' % (stats['added'] - by_sim)))
    stats['used'] = len(used)
    stats['sections_no_fig'] = sum(
        1 for s in secs
        if str(s.get('no')) != '0' and not any(b and b[0] == 'fig' for b in s.get('body') or []))

    if stats['dropped']:
        emit('[图] 丢弃 %d 个对不上的图名（清单里没有，说明模型编了或路径写错）：%s'
             % (len(stats['dropped']), '、'.join(stats['dropped'][:4])))
    emit('[图] 可用课件页图 %d 张（课件 %s 页）· 本讲用 %d 张（数据里已有 %d · 修名 %d · 本次补 %d，'
         '补图上限 %d）%s'
         % (stats['available'], stats['total'], stats['used'], stats['model'], stats['fixed'],
            stats['added'], cap,
            ('· 还有 %d 个内容节没图（清单用完或补图到上限）' % stats['sections_no_fig'])
            if stats['sections_no_fig'] else ''))
    return stats


def fig_src(name: str) -> str:
    """把图片引用变成能直接加载的 src；找不到就记进 MISSING（上层据此报「缺图不打」）。"""
    hit = _match_fig(name, CURRENT_AVAIL)
    cands = []
    if hit:
        cands.append(hit[0])
    rel = _ref_rel(name)
    if rel:
        cands.append(rel)
    raw = str(name or '')
    if os.path.isabs(raw):
        cands.append(raw)
    for c in cands:
        if os.path.isabs(c):
            p = c
        elif ASSETS:
            p = os.path.join(ASSETS, c)
        else:
            p = c
        if os.path.isfile(p):
            return 'file:///' + p.replace('\\', '/').lstrip('/')
    shown = hit[0] if hit else (rel or raw)
    if name not in MISSING:
        MISSING.append(name)
    return 'assets/' + shown

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
  figure,.eq,.note,blockquote,table.sym,pre.code,.eg{break-inside:avoid}
  .eg .ask{break-after:avoid}
  h3{break-after:avoid}
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
        ref = b[1] if len(b) > 1 else ''
        # 图注必须带出处「课件 p.N」（R115）：数据没写就按图名里的页码补，绝不空着
        cap = _cap_with_page(b[2] if len(b) > 2 else '', _page_of_ref(ref))
        return ('<figure>\n  <img src="%s" alt="%s">\n  <figcaption>%s</figcaption>\n</figure>'
                % (fig_src(ref), cap.replace('"', ''), cap))
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


# ── 语言档（2026-11-18）────────────────────────────────────────────────────────
# 「全中」= 正文中文 + 术语每节首次附英文（原有口径）；「全英」= 正文英文 + 专有名称中文。
# 固定件（目录 / 术语表 / 附录 / 自测 / 讲法）也按这一档切换，否则英文正文里会夹中文标题。
# 2026-11-21（R114，用户「CO2（二氧化碳）而不是直接取代」）：全英档的固定件跟正文口径一致——
#   英文在前、中文原名在后。封面主标题用 en、中文原名降到副行；术语表第一列 English、第二列「中文原名」；
#   讲法 / 目录 / 附录 / 自测同样先英文后中文。正文里每个专有名称首次出现写「English（中文）」。
LABELS = {
    "zh": {"lec": "讲法。", "toc": "目录", "toc_sub": "CONTENTS",
           "gloss": ["中文", "English", "页码", "备注"],
           "sym": ["符号 / 缩写", "读法·含义", "出处"],
           "myths": "常见误解"},
    "en": {"lec": "How to use. ", "toc": "Contents", "toc_sub": "",
           "gloss": ["English", "中文原名", "Page", "Note"],
           "sym": ["Symbol / Abbreviation", "Meaning", "Source"],
           "myths": "Common misconceptions"},
}


def _lang_of(lesson: dict) -> str:
    return "en" if str(lesson.get("lang") or "zh").lower().startswith("en") else "zh"


def build(lesson: dict) -> str:
    L = lesson
    code, no = L['code'], L['no']
    lang = _lang_of(L)
    lab = LABELS[lang]
    use_course(code)
    # 2026-11-21（R115）：本讲可用的课件页图 + 修名/补图/图注补出处。
    #   放在渲染前：数据里没有 fig 块（旧数据、或模型漏写）时也能把原件图画出来。
    global CURRENT_AVAIL
    CURRENT_AVAIL = figure_files(no)
    ensure_figures(L, emit=print)
    out = []
    out.append('<!DOCTYPE html>\n<html lang="%s" data-theme="dark" data-reader="大学" data-lang="%s">'
               % ("en" if lang == "en" else "zh-CN", lang))
    out.append('<head>\n<meta charset="utf-8">\n<meta name="out" content="%s">' % L['out'])
    out.append('<title>%s %s · 讲义</title>\n<style>%s</style>\n</head>\n<body>' % (no, L['zh'], CSS))

    # 封面：全英档主标题用 en，中文原名降到副行（专有名称仍看得见）
    main_title = L['en'] if lang == "en" and L.get('en') else L['zh']
    sub_title = L['zh'] if lang == "en" and L.get('en') else L['en']
    meta = '\n'.join('    <div class="row"><b>%s</b><span>%s</span></div>' % (k, v) for k, v in L['meta'])
    out.append(
        '<section class="cover">\n'
        '  <div class="kicker">%s · LECTURE %s</div>\n'
        '  <h1>%s</h1>\n'
        '  <div class="sub">%s<br>\n  %s</div>\n'
        '  <div class="meta">\n%s\n  </div>\n</section>'
        % (code, no.lstrip('L'), main_title, sub_title, L['sub'], meta))

    # 目录（自动）
    def head_of(sec):
        """全中：中文主标题 + 英文副行；全英：英文主标题 + 中文副行。"""
        if lang == "en" and sec.get('en'):
            return sec['en'], sec.get('zh', '')
        return sec['zh'], sec.get('en', '')

    items = []
    for s in list(L['sections']) + list(L['tail']):
        main, sub = head_of(s)
        items.append('    <div class="item"><span class="no">%s</span><span class="t">%s<small>%s</small></span>'
                     '<span class="pg" data-head="%s">·</span></div>'
                     % (s['no'], main, sub, main))
    out.append(('<section class="tocpage">\n'
                '  <h2 style="margin-top:0"><span class="no">·</span><span class="zh">%s</span>'
                '<span class="en">%s</span></h2>\n  <div class="toc">\n'
                + '\n'.join(items) + '\n  </div>\n</section>')
               % (lab['toc'], lab['toc_sub']))

    # 正文章节
    for s in L['sections']:
        body = '\n'.join(render_block(b) for b in s['body'])
        lec = ('<p class="lec"><b>%s</b>%s</p>\n' % (lab['lec'], s['lec'])) if s.get('lec') else ''
        main, sub = head_of(s)
        out.append('<section class="sec">\n'
                   '<h2><span class="no">%s</span><span class="zh">%s</span><span class="en">%s</span></h2>\n'
                   '%s%s\n</section>' % (s['no'], main, sub, lec, body))

    # 小结
    sm = L['summary']
    th = ''.join('<th style="width:%s">%s</th>' % (sm['head_widths'][i], h)
                 for i, h in enumerate(sm['head']))
    rows = '\n'.join('<tr>' + ''.join('<td>%s</td>' % c for c in r) + '</tr>' for r in sm['rows'])
    sm_main, sm_sub = head_of(sm)
    out.append('<section class="sec">\n<h2><span class="no">%s</span><span class="zh">%s</span><span class="en">%s</span></h2>\n'
               '%s<table>\n<tr>%s</tr>\n%s\n</table>\n<p>%s</p>\n</section>'
               % (sm['no'], sm_main, sm_sub,
                  ('<p class="lec"><b>%s</b>%s</p>\n' % (lab['lec'], sm['lec'])) if sm.get('lec') else '',
                  th, rows, sm['tail']))

    # 自测
    q = L['quiz']
    body = []
    for i, (qq, aa) in enumerate(q['items'], 1):
        if lang == "en":
            aa = re.sub(r'^\s*答[：:]\s*', 'A: ', str(aa))   # 全英档答案前缀统一成 A:
        body.append('<div class="q"><b>Q%d.</b> %s</div>\n<div class="ans">%s</div>' % (i, qq, aa))
    q_main, q_sub = head_of(q)
    out.append('<section class="sec">\n<h2><span class="no">%s</span><span class="zh">%s</span><span class="en">%s</span></h2>\n'
               '<p class="lec"><b>%s</b>%s</p>\n\n%s\n</section>'
               % (q['no'], q_main, q_sub, lab['lec'], q['lec'], '\n\n'.join(body)))

    # 术语表（全英档把 English 放第一列）
    g = L['glossary']
    grows = '\n'.join('  <tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>'
                       % ((r[1], r[0], r[2], r[3]) if lang == "en" and len(r) >= 4 else tuple(r))
                       for r in g['rows'])
    g_main, g_sub = head_of(g)
    gh = lab['gloss']
    out.append('<section class="sec">\n<h2><span class="no">%s</span><span class="zh">%s</span><span class="en">%s</span></h2>\n'
               '<p class="lec"><b>%s</b>%s</p>\n\n'
               '<table class="glossary">\n'
               '  <colgroup><col style="width:20%%"><col style="width:27%%">'
               '<col style="width:15%%"><col style="width:38%%"></colgroup>\n'
               '  <thead><tr><th>%s</th><th>%s</th><th>%s</th><th>%s</th></tr></thead>\n'
               '  <tbody>\n%s\n  </tbody>\n</table>\n</section>'
               % (g['no'], g_main, g_sub, lab['lec'], g['lec'],
                  gh[0], gh[1], gh[2], gh[3], grows))

    # 附录
    a = L['appendix']
    srows = '\n'.join('<tr>' + ''.join('<td>%s</td>' % c for c in r) + '</tr>' for r in a['symbols'])
    myths = '\n'.join('<li>%s</li>' % m for m in a['myths'])
    a_main, a_sub = head_of(a)
    sy = lab['sym']
    out.append('<section class="sec">\n<h2><span class="no">%s</span><span class="zh">%s</span><span class="en">%s</span></h2>\n'
               '<p class="lec"><b>%s</b>%s</p>\n\n'
               '<table class="sym">\n<tr><th>%s</th><th>%s</th><th>%s</th></tr>\n%s\n</table>\n\n'
               '<h3>%s</h3>\n<ol>\n%s\n</ol>\n</section>'
               % (a['no'], a_main, a_sub, lab['lec'], a['lec'],
                  sy[0], sy[1], sy[2], srows, a.get('myths_title') or lab['myths'], myths))

    out.append('\n</body>\n</html>\n')
    return number_figures('\n\n'.join(out))


# 图 / 表自动编号（2026-11-17，优化项 L1：借 quarto 的「自动编号 + 交叉引用」）
#   为什么放渲染末尾一次性数：图是逐块拼出来的，每个块自己不知道前面已有几张图；
#   统一过一遍 HTML 才能保证「图 1、图 2…」连续且不重号。
#   手写优先：已经以「图 N」开头的 figcaption 不再加前缀（人工标过的不动）。
FIGCAP_RE = re.compile(r'(<figcaption[^>]*>)(\s*)(.*?)(</figcaption>)', re.S)
TABCAP_RE = re.compile(r'(<caption[^>]*>)(\s*)(.*?)(</caption>)', re.S)


def number_figures(html: str) -> str:
    """给图片加「图 N · 」、给带 caption 的表加「表 N · 」；返回新 HTML。"""
    state = {'fig': 0, 'tab': 0}

    def fig(m):
        text = m.group(3).strip()
        if not text or re.match(r'^图\s*\d+', text):
            return m.group(0)
        state['fig'] += 1
        return '%s%s图 %d · %s%s' % (m.group(1), m.group(2), state['fig'], text, m.group(4))

    def tab(m):
        text = m.group(3).strip()
        if not text or re.match(r'^表\s*\d+', text):
            return m.group(0)
        state['tab'] += 1
        return '%s%s表 %d · %s%s' % (m.group(1), m.group(2), state['tab'], text, m.group(4))

    return TABCAP_RE.sub(tab, FIGCAP_RE.sub(fig, html))


def load(no: str, lang: str = None) -> dict:
    # 逐文件回落：数据根有这一讲就用它（用户改过的），没有就用随程序发布的那份。
    # 2026-11-18：语言档 = en 时优先 <no>.en.py（DeepSeek 生成/翻译的英文版），没有才回中文。
    path = None
    if lang == "en":
        p_en = paths.data_or_res(COURSE, '_lessons', no + '.en.py')
        if os.path.isfile(p_en):
            path = p_en
    if not path:
        path = paths.data_or_res(COURSE, '_lessons', no + '.py')
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
        dst = os.path.join(ROOT, COURSE, '06_笔记', '%s_零基础_讲义_源.html' % no)
        open(dst, 'w', encoding='utf-8').write(html)
        print('已生成 %s（%d 字符）' % (dst, len(html)))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))