# -*- coding: utf-8 -*-
r"""导入原件 → DeepSeek 写正文 → 落成 <课程>\_lessons\<讲号>.py（英文进 .en.py）。

为什么要有它
    2026-11-18 用户实测：导入 99 页课件后点「开始生成」，出来的是 7 页占位骨架
    （「原件导入占位 · 正文待补」），因为导入只建骨架、不写正文。用户要的是
    「导入 → 开始生成」就能拿到能读的讲义。这个模块补的就是中间这一步。

边界（明写）
    · 只读 <课程>\00_原件 里那一份源 PDF 的文字层；扫描件（没文字层）出不了内容，会明确报错。
    · 源文本超过 MAX_SRC 字符时只取前 MAX_SRC，并在日志里写明（不静默截断）。
    · 模型只负责组织与标注出处；三道门仍照跑，红项不产出。
    · 全英档（lang="en"）专业名称写「English（中文）」：英文在前、中文原名放全角括号里，首次出现写全，
      之后只写英文（用户 2026-11-21「CO2（二氧化碳）而不是直接取代」）。
    · 原件图（用户 2026-11-21「为什么我一点原件的图也看不到」）：课件页导出成 PNG 后列表随提示词下发，
      并要求每节引用；模型漏写时渲染阶段按清单补齐（_build_讲义.ensure_figures），一张都没有时日志写明原因。

用法
    python engine\_draft.py T02 --course DEMO --lang zh
    python engine\_draft.py T02 --course DEMO --lang en
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import shutil
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import paths  # noqa: E402

for _p in (paths.res("api"), paths.res("engine")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import client  # noqa: E402  api\client.py

MAX_SRC = 45000          # 一次送进模型的源文本上限（字符）
MAX_FIGS = 40            # 最多抽多少张课件页图（整页截图）
FALLBACK_FIGS = 12       # 课件没有图片对象时，整页兜底导出最多几张（2026-11-21 加）
# 2026-11-23 用户：「不应该是以图片对于讲解的重要性来选择的吗 而不是先到先得名额吧」
#   名额按「这一页的图值不值」排（_fig_score），先得把「不是内容图」的东西认出来：
FIG_MIN_AREA = 0.01      # 一张图占页面不到 1% → 模板徽标 / 边框 / 水印，不当作内容图
FIG_MIN_PX = 300         # 原图短边不到 300px → 缩略图 / 图标，不当作内容图
FIG_DUP_MAX = 3          # 同一张图出现在 >3 页 → 模板 / 横幅（复制到每页的那种）
# 2026-11-23 用户要求把「图」做得更有信息量：实测图页上最大一张图只占页面 8.7%–41%，
#   整页截图里一多半是页面文字与留白（讲义里等于又贴了一遍正文）。所以导出时裁到图区。
FIG_CROP = True          # 只导出图区（关掉就退回整页截图）
FIG_CROP_PAD = 0.02      # 裁切四周留 2% 页面尺寸的边
FIG_CROP_MIN = 0.12      # 图区占页面 <12% 时不裁（裁了像缩略图，反而看不清）
FIG_CROP_MAX = 0.85      # 图区占页面 ≥85% 基本等于整页，不裁
# 裁切后要多少像素：讲义里图宽度约 17cm，1000px 约合 150dpi（够印）；再高只是把体积抬上去。
FIG_CROP_TARGET_PX = 1000
FIG_CROP_DPI_MAX = 150
FIG_LOW_HEAD = ("目录", "大纲", "致谢", "参考", "参考文献", "复习", "作业", "本章小结",
                "agenda", "outline", "thank", "reference", "revision", "homework", "outcomes")
GLOSSARY_MIN = 20        # 内容门要求的最小术语条数
# 表格（2026-11-23）：get_text 会把表格拍平，有真表时补一段结构化文字
TABLE_MIN_ROWS = 2
TABLE_MIN_COLS = 2
TABLE_MAX_ROWS = 30
ORIG_DIR = "00_原件"

_SYS_ZH = """你是课程讲义编辑。把给定课件（逐页文本，页码已标）整理成一份可打印自学的讲义数据。
硬规则（全部遵守）：
1. 只用课件里真实存在的内容，禁止编造事实、数字、药名；课件没写的就不写。
2. 每节至少一处出处标注，格式严格为「课件 p.N」；引用原句用 q 块。
3. 每节必须有 lec（讲法，1-2 句）。
4. 每个内容节（§0 导读除外）至少一个 eg（例题 / 计算 / 配制步骤）。
5. 每节 2-4 段，单段 ≤ 120 字；整节控制在一页内（约 600 字），宁多分节。
6. 术语表至少 20 条，每条带页码。
7. 自测 3-6 题，答案末尾必须写「回看 §<节号>」。
8. 只输出 JSON，不要 markdown 代码围栏，不要注释，json.loads 可直接解析。
9. 全中模式：正文中文；术语英文只在术语表给，正文不要自己加英文括号。
10. 节数 8-12 节，no 从 0 连续；summary / glossary / appendix / quiz 的 no 顺延。
11. 输出尽量紧凑，避免超出输出长度。
12. 原件图（重要，用户 2026-11-21 明确要求「要能看到原件的图」）：输入末尾给了本讲导出的课件页图清单。
    每个内容节（§0 导读除外）在正文末尾放 1 个 fig 块，按课件页顺序取图：
      · 格式：["fig", "gen/<讲号>/pNNN.png", "这张图画的是什么（课件 p.N）"]；
      · 路径只能原样照抄清单里的，不得改名、加前缀或编造；
      · 图注要写清它是什么，并带「课件 p.N」出处（引擎会自动加「图 N ·」编号）；
      · 不要只在正文里写「见图」而不用 fig 块；清单为空才不写 fig。
"""

_SYS_EN = """You are a course handout editor. Turn the given lecture slides (page texts, page numbers marked) into printable self-study handout data.
Hard rules:
1. Use ONLY facts present in the slides. Never invent facts, numbers, or drug names.
2. Every section cites at least one source as "课件 p.N" (keep this exact Chinese marker); use q blocks for direct quotes.
3. Every section needs "lec" (how to teach it, 1-2 sentences).
4. Every content section (except §0) needs at least one "eg" block (worked example / calculation / preparation steps).
5. Each section 2-4 paragraphs, at most 60 words each; keep one section within one printed page (~350 words).
6. Glossary at least 20 rows, each with a page: [中文术语, English term, "课件 p.N", one-line note]
   (the engine prints English first and 中文原名 second in English handouts — keep the Chinese original in data).
7. Quiz 3-6 items; every answer ends with "Review §<section no>".
8. Output JSON only, no code fences, no comments; must parse with json.loads.
9. Full-English mode — professional names (用户 2026-11-21「CO2（二氧化碳）而不是直接取代」):
   body text is English, but EVERY professional name / drug name / formula name / compound name / technical term /
   proper name must appear at its 首次 occurrence as English（中文）— English FIRST, the Chinese original inside
   FULL-WIDTH Chinese parentheses（）. After that first occurrence, use the English term alone.
   Good: "CO2（二氧化碳） dissolves in water"; "the Bellman optimality equation（贝尔曼最优方程） holds";
   "Pharmacopoeia（药典） requires it".
   Bad: "CO2 dissolves in water" (Chinese original DROPPED); "二氧化碳 dissolves in water" (English missing);
   "carbon dioxide" alone (Chinese original replaced). Never drop or replace the Chinese original.
10. 8-12 sections, no starting at 0; summary / glossary / appendix / quiz numbers follow.
11. Be compact to fit the output limit.
12. Source-slide figures (important): the input ends with a list of exported slide-page images.
    For EVERY content section (except §0) add ONE fig block at the end of its body, in slide-page order:
      ["fig", "gen/<no>/p012.png", "what the slide shows（课件 p.N）"]
    Copy the path EXACTLY from the list — never rename it, add a prefix, or invent one. Keep the "课件 p.N"
    source marker in the caption (the engine adds "图 N ·" automatically). Do not merely write "see the figure"
    in prose without a fig block. If the list is empty, emit no fig blocks.
"""

_SCHEMA = """{
  "zh": "本讲中文标题（英文模式也留中文原名）", "en": "English Title", "sub": "一句话副标题",
  "sections": [
    {"no": "0", "zh": "本讲导读", "en": "Read Me First", "lec": "讲法",
     "body": [["p", "段落，标出处（课件 p.5）"], ["q", "课件原句", "课件 p.5"],
              ["ul", ["要点一", "要点二"]], ["eg", "题面", ["步骤1", "步骤2"], "答案"],
              ["table", ["列一", "列二"], [["a", "b"]], ["50%", "50%"]]]}
  ],
  "summary": {"no": "6", "zh": "本讲小结", "en": "Takeaways", "lec": "…",
    "head": ["要做什么", "要点", "怎么验"], "head_widths": ["26%", "42%", "32%"],
    "rows": [["…", "…", "…"]], "tail": "一句收尾"},
  "glossary": {"no": "7", "zh": "术语表", "en": "Glossary", "lec": "…",
    "rows": [["中文术语", "English", "课件 p.N", "解释"]]},
  "appendix": {"no": "8", "zh": "附录", "en": "Appendix", "lec": "…",
    "symbols": [["符号/缩写", "读法·含义", "出处"]], "myths_title": "常见误解", "myths": ["…"]},
  "quiz": {"no": "9", "zh": "自测", "en": "Self-check", "lec": "…",
    "items": [["题目", "答：… 回看 §0"]]}
}"""


def _pylit(v, ind: int = 0) -> str:
    r"""把 dict / list 写成 Python 字面量；全标量列表写成 tuple。

    与 ui\server.py 的 _pylit 同一口径：引擎里 '…%s…' % row 只展开 tuple，
    JSON 的 list 会被当成单个值 → not enough arguments。
    """
    pad = " " * ind
    if isinstance(v, dict):
        if not v:
            return "{}"
        items = []
        for k, x in v.items():
            items.append('%s    %s: %s' % (pad, json.dumps(str(k), ensure_ascii=False), _pylit(x, ind + 4)))
        return "{\n" + ",\n".join(items) + "\n" + pad + "}"
    if isinstance(v, (list, tuple)):
        if not v:
            return "()" if isinstance(v, tuple) else "[]"
        if all(not isinstance(x, (dict, list, tuple)) for x in v):
            body = ", ".join(_pylit(x, 0) for x in v)
            return "(" + body + ("," if len(v) == 1 else "") + ")"
        inner = ",\n".join(pad + "    " + _pylit(x, ind + 4) for x in v)
        return "[\n" + inner + ",\n" + pad + "]"
    if isinstance(v, str):
        return json.dumps(v, ensure_ascii=False)
    if v is None:
        return "None"                      # JSON 的 null 不是合法 Python 字面量
    if isinstance(v, bool):
        return "True" if v else "False"
    if isinstance(v, (int, float)):
        return json.dumps(v)
    return repr(v)


def _read_text(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:  # noqa: BLE001
        return ""


def lesson_path(course: str, no: str, lang: str = "zh") -> str:
    """讲次数据文件：中文 = <no>.py；英文 = <no>.en.py（不覆盖中文）。"""
    suffix = ".en.py" if lang == "en" else ".py"
    return paths.data_or_res(course, "_lessons", no + suffix)


def fig_overrides(course: str, no: str) -> tuple:
    r"""读 <课程>\_lessons\<讲号>.py 里手写的 FIG_PAGES / FIG_SKIP（按页号指定，优先于自动排序）。

    2026-11-23：自动排序只认版面与文字，认不出「这一页是本节的关键图」这种语义；
    所以留一个手闸——你在讲次数据文件里加一行就能一票指定（不用改代码）：
        FIG_PAGES = [12, 13, 27]   # 这几页的图必须进讲义
        FIG_SKIP  = [1, 48]        # 这几页不要（封面/致谢/重复图）
    """
    text = _read_text(lesson_path(course, no, "zh"))
    def nums(key):
        m = re.search(key + r"\s*=\s*\[([0-9,\s]*)\]", text)
        if not m:
            return ()
        return tuple(int(x) for x in re.findall(r"\d+", m.group(1)))
    return nums("FIG_PAGES"), nums("FIG_SKIP")


def source_of(course: str, no: str) -> tuple[str, str]:
    """找到这一讲对应的原件 PDF：先认 stub-from 标记，再按标题在 00_原件 里找。"""
    p = lesson_path(course, no, "zh")
    text = _read_text(p)
    m = re.search(r"stub-from:\s*" + re.escape(ORIG_DIR) + r"/([^\"'\n]+)", text)
    name = (m.group(1).strip() if m else "")
    odir = paths.data(course, ORIG_DIR)
    if not os.path.isdir(odir):
        odir = paths.res(course, ORIG_DIR)
    if name:
        full = os.path.join(odir, name)
        if os.path.isfile(full):
            return full, name
    # 二次导入 / 已生成过的讲次：从 meta 的「源课件」行取
    m3 = re.search(r'"源课件"\s*,\s*"([^"]+)"', text) or re.search(r"\('源课件',\s*'([^']+)'\)", text)
    if m3:
        nm = m3.group(1).split("/")[-1]
        full = os.path.join(odir, nm)
        if os.path.isfile(full):
            return full, nm
    if os.path.isdir(odir):
        pdfs = [x for x in os.listdir(odir) if x.lower().endswith(".pdf")]
        if len(pdfs) == 1:                       # 这门课只有一份原件：就用它
            return os.path.join(odir, pdfs[0]), pdfs[0]
    m2 = re.search(r'"zh":\s*"([^"]+)"', text)
    if m2 and os.path.isdir(odir):
        for fn in os.listdir(odir):
            if fn.lower().endswith(".pdf") and os.path.splitext(fn)[0] == m2.group(1):
                return os.path.join(odir, fn), fn
    raise FileNotFoundError("找不到这一讲的原件：%s\\%s（先导入课件）" % (course, ORIG_DIR))


def _table_text(page) -> str:
    """把这一页里的表格补成「行1: a | b | c」的结构化文字（2026-11-23）。

    为什么：get_text("text") 把表格拍成一行行文字，列的对应关系全丢——模型看到的是
    「AaBbCc」这种串，写进讲义就错位。实测真实课件里表格不多（11 份里 3 份有，共 6 张），
    所以这里只做「有真表就补一段」，没有表格的页一个字都不加。
    """
    try:
        tabs = page.find_tables()
        rows = []
        for t in tabs.tables:
            try:
                data = t.extract()
            except Exception:  # noqa: BLE001
                continue
            data = [r for r in (data or []) if r]
            if len(data) < TABLE_MIN_ROWS:
                continue
            if max(len(r) for r in data) < TABLE_MIN_COLS:
                continue
            for r in data[:TABLE_MAX_ROWS]:
                cells = [re.sub(r"\s+", " ", str(c or "")).strip() for c in r]
                rows.append(" | ".join(cells))
        return ("\n【表格】\n" + "\n".join(rows)) if rows else ""
    except Exception:  # noqa: BLE001
        return ""


def page_blocks(pdf: str) -> tuple[list, int, int]:
    """PDF → 每页一块「【课件 p.N】+ 文字（有表格就附结构化表格）」。

    返回 (blocks, 有内容的页数, 总页数)。扫描件得到 0 块。draft() 用它来分块生成。
    """
    try:
        import pymupdf
    except Exception as e:  # noqa: BLE001
        raise RuntimeError("缺 pymupdf，读不了 PDF：%r" % (e,))
    doc = pymupdf.open(pdf)
    blocks, n = [], 0
    total = len(doc)
    for i, pg in enumerate(doc, 1):
        t = (pg.get_text("text") or "").strip()
        tab = _table_text(pg)
        if not t and not tab:
            continue
        t = "\n".join(x.strip() for x in t.splitlines() if x.strip())
        body = t + (("\n" + tab) if tab else "")
        blocks.append("【课件 p.%d】\n%s" % (i, body))
        n += 1
    doc.close()
    return blocks, n, total


def pages_text(pdf: str, emit=print) -> tuple[str, int, int]:
    """PDF 文字层 → (带页码的文本, 有文字的页数, 总页数)。扫描件会得到 0 页。"""
    blocks, n, total = page_blocks(pdf)
    text = "\n\n".join(blocks)
    if not text:
        raise RuntimeError("这份 PDF 没有文字层（像是扫描件）：%s" % os.path.basename(pdf))
    if len(text) > MAX_SRC:
        emit("[注意] 源文本 %d 字符，超过上限 %d：draft() 会分块生成（这一份不再被截断）"
             % (len(text), MAX_SRC))
    return text, n, total


def _save_page_png(page, out_root: str, i: int, clip=None) -> str | None:
    """把一页课件导出成 PNG；clip 给了就只导出那块区域。

    2026-11-23（用户要求提高「信息量」）：以前一律整页 96 dpi，而实测图页上最大的图只占
    8.7%–41%，整页截图一多半是页面文字与留白——讲义里那张「原件图」等于又贴了一遍正文。
    现在按图区裁切，并按比例提 dpi（裁到 30% 宽就按 ~300 dpi 出图），保证贴进讲义时
    像素量不低于整页截图，不会变糊；整页那条路原样保留。
    """
    try:
        import pymupdf
        name = "p%03d.png" % i
        dst = os.path.join(out_root, name)
        if clip is None or not FIG_CROP:
            page.get_pixmap(dpi=96).save(dst)
            return name
        w_pt = max(1.0, clip[2] - clip[0])
        dpi = int(min(FIG_CROP_DPI_MAX, max(96, round(FIG_CROP_TARGET_PX * 72.0 / w_pt))))
        page.get_pixmap(dpi=dpi, clip=pymupdf.Rect(*clip)).save(dst)
        return name
    except Exception:  # noqa: BLE001
        return None


def _page_head(page) -> str:
    """这一页的开头一行（用来认「目录 / 致谢 / 复习」这类页）。"""
    try:
        t = (page.get_text("text") or "").strip()
    except Exception:  # noqa: BLE001
        return ""
    return t.split("\n")[0][:60] if t else ""


def _fig_score(chars: int, real: float, big: float, head: str) -> float:
    """这一页的图「值不值占一个名额」的分数——只量版面与文字，不猜语义。

    2026-11-23 用户：「不应该是以图片对于讲解的重要性来选择的吗 而不是先到先得名额吧」，
    选了「按版面启发式排」。于是规则明写成三条，可复算、可复盘：
      · 真图占页比（去掉模板徽标 / 缩略图 / 重复图之后）：占半页的示意图 >> 角落小图；
      · 这一页的字数：字越少，图越像这一页的主角；
      · 页首文本：目录 / 大纲 / 致谢 / 参考 / 复习 / 作业 这类页降权。
    """
    s = 3.0 * min(big, 1.0) + 1.2 * min(real, 1.0)
    if chars < 120:
        s += 0.6
    elif chars < 300:
        s += 0.2
    low = (head or "").strip().lower()
    if any(k in low for k in FIG_LOW_HEAD):
        s -= 1.5
    return round(s, 3)


def _crop_rect(page, imgs: list, dup: dict) -> tuple | None:
    """这一页要导出的区域：真图的并集 + 2% 留白；太小 / 接近整页时返回 None（用整页）。

    2026-11-23：图区占页 <12% 时裁出来只有一小块，贴进讲义反而是缩略图（看不清），
    所以那种页仍然整页导出；≥85% 时裁不裁差别不大，也不裁。
    """
    keep = [im for im in imgs
            if im[0] >= FIG_MIN_AREA and im[1] >= FIG_MIN_PX
            and dup.get(im[2], 1) <= FIG_DUP_MAX and len(im) > 3]
    if not keep:
        return None
    r = page.rect
    pad_x, pad_y = r.width * FIG_CROP_PAD, r.height * FIG_CROP_PAD
    x0 = max(r.x0, min(im[3][0] for im in keep) - pad_x)
    y0 = max(r.y0, min(im[3][1] for im in keep) - pad_y)
    x1 = min(r.x1, max(im[3][2] for im in keep) + pad_x)
    y1 = min(r.y1, max(im[3][3] for im in keep) + pad_y)
    if x1 - x0 <= 1 or y1 - y0 <= 1:
        return None
    frac = ((x1 - x0) * (y1 - y0)) / ((r.width * r.height) or 1)
    if frac < FIG_CROP_MIN or frac >= FIG_CROP_MAX:
        return None
    return (x0, y0, x1, y1)


def _real_area(imgs: list, dup: dict) -> tuple:
    """一页里「真图」的合计占比与最大一张占比。

    2026-11-23：课件几乎每页都带同一个模板徽标（实测一份 57 页课件里，同一张图重复 57 页、
    每页只占 0.3%）。这种页整页截进讲义只是「一张文字页的照片」，不增加信息，所以不算真图；
    但它不影响这一讲照常生成正文，只是不占图的名额。
    """
    keep = [im for im in imgs
            if im[0] >= FIG_MIN_AREA and im[1] >= FIG_MIN_PX
            and dup.get(im[2], 1) <= FIG_DUP_MAX]
    if not keep:
        return 0.0, 0.0
    return round(sum(min(im[0], 1.0) for im in keep), 3), round(max(im[0] for im in keep), 3)


def real_figure_pages(pdf: str) -> set:
    """这份课件里「真有内容图」的页（与 extract_figures 同一判据：占页 ≥1%、短边 ≥300px、同图不重复 >3 页）。

    2026-11-22 用户：「90% 都要是原课件的图，也要防伪图」——补图 / 修图名之前先用它过一遍：
    页上只有模板徽标、或者干脆是纯文字页的「页图」，看着像图，其实什么也没画出来。
    读不到就返回空集合（调用方当作「不知道」，不拦，别把好图误杀）。"""
    try:
        import pymupdf
    except Exception:  # noqa: BLE001
        return set()
    out = set()
    try:
        dup = {}
        per = {}
        with pymupdf.open(pdf) as doc:
            for i, page in enumerate(doc, 1):
                try:
                    infos = page.get_image_info(xrefs=True)
                except Exception:  # noqa: BLE001
                    continue
                r = page.rect
                parea = (r.width * r.height) or 1.0
                imgs = []
                for im in infos:
                    bb = im.get("bbox") or (0, 0, 0, 0)
                    area = max(0.0, bb[2] - bb[0]) * max(0.0, bb[3] - bb[1]) / parea
                    px = max(int(im.get("width") or 0), int(im.get("height") or 0))
                    try:
                        h = hashlib.md5(doc.extract_image(im["xref"])["image"]).hexdigest()[:10]
                    except Exception:  # noqa: BLE001
                        h = "?"
                    imgs.append((area, px, h, (bb[0], bb[1], bb[2], bb[3])))
                    if area >= FIG_MIN_AREA and px >= FIG_MIN_PX:
                        dup[h] = dup.get(h, 0) + 1
                per[i] = imgs
        for i, imgs in per.items():
            real, _big = _real_area(imgs, dup)
            if real > 0:
                out.add(i)
    except Exception:  # noqa: BLE001
        return set()
    return out


def extract_figures(pdf: str, course: str, no: str, emit=print,
                    fig_pages=(), fig_skip=()) -> list:
    """把课件页导出成整页 PNG，供模型用 fig 块引用。

    2026-11-19 用户：「生成的东西少了引用课件 PDF 原文截图图片」——讲义要以课件为依据，
    不是只把文字复述一遍。导出有图片对象的页，最多 MAX_FIGS 张，96 dpi。
    2026-11-21 用户：「为什么我一点原件的图也看不到」——两条修：
      · 纯文字 / 矢量版式的课件（没有图片对象）不再「抽 0 张、一声不响」：改为整页导出，
        让读者至少能看到原件版式（日志写明这是兜底，最多 FALLBACK_FIGS 张）；
      · 导出前清掉上一次的 pNNN.png，换课件重导不会把旧图混进新讲义。
    2026-11-23 用户：「不应该是以图片对于讲解的重要性来选择的吗 而不是先到先得名额吧」：
      以前是**按页序抓前 40 张**，名额被「只挂模板徽标的纯文字页」占掉、真图被砍（实测一份
      57 页课件：前 40 页里 10 页是徽标页，第 41–55 页的真图全丢）。现在按 _fig_score 从高到低
      取，页序只在同分时定先后；被丢掉的页在日志里点名 + 给分，可复盘。
      个人指定：FIG_PAGES / FIG_SKIP（写在 <课程>\\_lessons\\<讲号>.py 里，优先于自动排序）。
    返回 [(相对 <课程>\\\\06_笔记\\\\assets 的路径, 页码), …]；返回空列表时日志一定说明原因。
    """
    try:
        import pymupdf
    except Exception:  # noqa: BLE001
        emit("[图] 缺 pymupdf，抽不了课件页图；这一讲不会有原件图")
        return []
    out_root = paths.data(course, "06_笔记", "assets", "gen", no)
    try:
        os.makedirs(out_root, exist_ok=True)
    except Exception as e:  # noqa: BLE001
        emit("[图] 建目录失败（%r），抽不了课件页图；这一讲不会有原件图：%s" % (e, out_root))
        return []
    # 清掉上一轮导出的页图：换课件重导时旧图会混进清单（gen/ 是生成物，删了可重导）
    stale = 0
    for fn in os.listdir(out_root):
        if re.match(r"^p\d{3}\.(png|jpg|jpeg|webp)$", fn, re.I):
            try:
                os.remove(os.path.join(out_root, fn))
                stale += 1
            except Exception:  # noqa: BLE001
                pass
    if stale:
        emit("[图] 清掉上次导出的 %d 张旧页图（换课件重导不带旧图）" % stale)

    out, failed = [], []
    total = 0
    try:
        with pymupdf.open(pdf) as doc:
            total = len(doc)
            cands, dup, imgs_of = [], {}, {}
            for i, page in enumerate(doc, 1):
                try:
                    infos = page.get_image_info(xrefs=True)
                except Exception:  # noqa: BLE001
                    continue
                if not infos:
                    continue
                r = page.rect
                parea = (r.width * r.height) or 1.0
                imgs = []
                for im in infos:
                    bb = im.get("bbox") or (0, 0, 0, 0)
                    area = max(0.0, bb[2] - bb[0]) * max(0.0, bb[3] - bb[1]) / parea
                    px = max(int(im.get("width") or 0), int(im.get("height") or 0))
                    try:
                        h = hashlib.md5(doc.extract_image(im["xref"])["image"]).hexdigest()[:10]
                    except Exception:  # noqa: BLE001
                        h = "?"
                    imgs.append((area, px, h, (bb[0], bb[1], bb[2], bb[3])))
                    if area >= FIG_MIN_AREA and px >= FIG_MIN_PX:
                        dup[h] = dup.get(h, 0) + 1
                imgs_of[i] = imgs
                cands.append((i, len((page.get_text("text") or "").strip()), _page_head(page), imgs))

            scored = []
            for i, chars, head, imgs in cands:
                real, big = _real_area(imgs, dup)
                if real <= 0:
                    continue            # 只有模板徽标 / 缩略图：这页不给名额（正文照旧生成）
                scored.append((i, _fig_score(chars, real, big, head)))
            scored.sort(key=lambda x: (-x[1], x[0]))
            score_of = dict(scored)

            forced = sorted({int(p) for p in fig_pages if 1 <= int(p) <= total})
            skipped = {int(p) for p in fig_skip if 1 <= int(p) <= total}
            if not scored and not forced:
                # 一页真图都没有（纯文字 / 矢量版式）：整页兜底导出，别静默给一份没图的讲义
                cap = min(MAX_FIGS, FALLBACK_FIGS)
                for i, page in enumerate(doc, 1):
                    if len(out) >= cap:
                        break
                    if not (page.get_text("text") or "").strip():
                        continue        # 空白页不导
                    name = _save_page_png(page, out_root, i)
                    if name:
                        out.append(("gen/%s/%s" % (no, name), i))
                    if len(out) >= cap:
                        break
                if out:
                    emit("[图] 这份课件 %d 页都没有内容图（纯文字/矢量版式）：改为整页导出 %d 页，"
                         "让讲义能看到原件版式 → %s" % (total, len(out), out_root))
                else:
                    emit("[图] 这份课件导不出页图（%d 页既没有图片对象、也没有文字层，像是扫描件）"
                         "→ 这一讲不会有原件图" % total)
                # 注意：这里必须把整页兜底导出的清单返回出去（HEAD 版本就是这样）。
                #   2026-11-23 我重写这个函数时只写了 return []，结果纯文字课件「导了 6 页却说
                #   没有可用页图」，提示词里一张图都没有——由 check-draft-chunks 第 1 项抓出来。
                return out

            keep = [p for p in forced if p not in skipped][:MAX_FIGS]
            for i, _s in scored:
                if len(keep) >= MAX_FIGS:
                    break
                if i in skipped or i in keep:
                    continue
                keep.append(i)
            keep = sorted(set(keep))[:MAX_FIGS]
            if not keep:
                emit("[图] 一页可用的课件图都没有（真图全被 FIG_SKIP 排除，或都是模板徽标）→ 这一讲不带原件图")
            for i in keep:
                page = doc[i - 1]
                name = _save_page_png(page, out_root, i, _crop_rect(page, imgs_of.get(i, []), dup))
                if name:
                    out.append(("gen/%s/%s" % (no, name), i))
                else:
                    failed.append(i)
    except Exception as e:  # noqa: BLE001
        emit("[图] 抽图失败（%r）；这一讲不会有原件图" % (e,))
        return []

    if out:
        emit("[图] 课件共 %d 页：%d 页有图片对象 → 其中 %d 页是真图 → 按重要性取 %d 张%s → %s"
             % (total, len(cands), len(scored), len(out),
                "（另有 %d 页导出失败：%s）" % (len(failed), "、".join("p.%d" % p for p in failed[:5]))
                if failed else "", out_root))
    dropped = [(i, score_of.get(i)) for i, _s in scored if i not in set(keep) and i not in skipped]
    if dropped:
        head = "、".join("p.%d(分 %.1f)" % (i, s) for i, s in dropped[:8])
        emit("[图] 名额 %d 张不够：另有 %d 页真图没进讲义 —— %s%s（要指定就写 FIG_PAGES / FIG_SKIP）"
             % (MAX_FIGS, len(dropped), head, " 等" if len(dropped) > 8 else ""))
    if forced or skipped:
        emit("[图] 手写指定覆盖：FIG_PAGES=%r FIG_SKIP=%r" % (list(forced), sorted(skipped)))
    return out


def _fig_help(figs: list, lang: str) -> str:
    """把图清单 + 用法说明紧贴在用户输入末尾：模型最容易照着最近的格式写。

    2026-11-21：只在 system 里写一条「有图就引用」时，模型经常只写文字描述、不写 fig 块；
    把清单和「每节 1 张、路径原样照抄」贴到源文本后面，比远在 system 里的规矩更容易被照做。
    """
    if not figs:
        return ""
    rows = "\n".join("p.%d → %s" % (pg, rel) for rel, pg in figs)
    if lang == "en":
        return ("\n\nExported source-slide images for this lecture (use fig blocks; copy the path EXACTLY, "
                "do not rename it or add a prefix):\n" + rows +
                "\n\nFor EVERY content section (except §0) add ONE fig block at the end of body, in page order:\n"
                '["fig", "<exact path from the list above>", "what the slide shows（课件 p.N）"]\n'
                'Never just write "see the figure" in prose without a fig block.')
    return ("\n\n本讲导出的课件页图（fig 块只能引用这些路径，原样照抄，不要改名或加前缀）：\n" + rows +
            "\n\n每个内容节（§0 导读除外）在正文末尾放 1 个 fig 块，按课件页顺序取图：\n"
            '["fig", "<上面清单里的原路径>", "这张图画的是什么（课件 p.N）"]\n'
            "不要只在正文里写「见图」而不用 fig 块。")


def _strip_fence(txt: str) -> str:
    txt = (txt or "").strip()
    fence = chr(96) * 3
    if txt.startswith(fence):
        txt = txt.split("\n", 1)[1] if "\n" in txt else ""
    txt = txt.replace(fence + "json", "").replace(fence, "").strip()
    return txt


def _loads_exact(txt: str):
    """整段能当 JSON 读才算数；读不出返回 None。"""
    body = (txt or "").strip()
    if not body:
        return None
    try:
        return json.loads(body, strict=False)
    except Exception:  # noqa: BLE001
        return None


def _scan_any(txt: str):
    """模型偶尔把示例 JSON 和真正的 JSON 一起吐出来，或正文后面又跟一段。

    从每个 { / [ 起试 raw_decode：优先取「像 LESSON」（带 sections）的那个，
    否则取第一个能解开的。
    """
    dec = json.JSONDecoder(strict=False)
    first_any = None
    for m in re.finditer(r"[\[{]", txt or ""):
        try:
            obj, _end = dec.raw_decode((txt or "")[m.start():])
        except Exception:  # noqa: BLE001
            continue
        if isinstance(obj, dict) and "sections" in obj:
            return obj
        if first_any is None:
            first_any = obj
    return first_any


def _json_of(txt: str) -> dict:
    """从模型输出里取 JSON。

    2026-11-21 用户点「开始生成」拿到「[停] 补正文失败：JSONDecodeError('Expecting property
    name enclosed in double quotes: line 1 column 1126')」——模型这次没按约定只吐一个对象。
    以前是「第一个 { 到最后一个 }」一刀切：多吐一个对象、或前面带示例，就必错。
    现在分两轮：先要求整段可解析（原样 / 去掉尾逗号），都不行再从括号起点逐个扫描。
    """
    body = _strip_fence(txt)
    cands = [body]
    fixed = re.sub(r",\s*([}\]])", r"\1", body)
    if fixed != body:
        cands.append(fixed)
    for cand in cands:
        obj = _loads_exact(cand)
        if obj is not None:
            return obj
    for cand in cands:
        obj = _scan_any(cand)
        if obj is not None:
            return obj
    raise ValueError("模型输出不是合法 JSON（%d 字符）" % len(body or ""))


def _norm(data: dict) -> dict:
    """把模型输出规范成引擎能渲染的形状；不删内容，只修块形状与缺省键。"""
    if not isinstance(data, dict):
        raise ValueError("模型返回的不是对象")
    secs = data.get("sections")
    if not isinstance(secs, list) or not secs:
        raise ValueError("模型没给 sections")
    fixed = []
    for s in secs:
        if not isinstance(s, dict):
            continue
        body = []
        for b in (s.get("body") or []):
            if not isinstance(b, (list, tuple)) or not b:
                continue
            kind = b[0]
            if kind in ("ul", "ol"):
                if len(b) >= 2 and isinstance(b[1], str):
                    b = [kind, [str(x) for x in b[1:]]]
                elif len(b) == 2 and isinstance(b[1], list):
                    b = [kind, [str(x) for x in b[1]]]
                else:
                    b = [kind, [str(x) for x in b[1:]]]
            elif kind == "table":
                if len(b) < 4:
                    continue
                head = [str(x) for x in (b[1] or [])]
                rows = []
                for r in (b[2] or []):
                    r = list(r) if isinstance(r, (list, tuple)) else [r]
                    if len(r) < len(head):
                        r += [""] * (len(head) - len(r))
                    rows.append([str(x) for x in r[:len(head)]])
                widths = [str(x) for x in (b[3] or [])]
                if len(widths) < len(head):
                    widths += ["%d%%" % max(10, 100 // max(1, len(head)))] * (len(head) - len(widths))
                b = ["table", head, rows, widths]
            elif kind == "eg":
                if len(b) < 4:
                    continue
                steps = b[2] if isinstance(b[2], (list, tuple)) else [b[2]]
                b = ["eg", str(b[1]), [str(x) for x in steps], str(b[3])]
            elif kind == "fig":
                # 2026-11-21：模型偶尔只给 [fig, 路径]（图注省了）。不再整块丢弃——
                #   渲染时会用清单里的页码补出「原件第 N 页（课件 p.N）」图注（R115 要求每张图有出处）。
                if len(b) < 2:
                    continue
                b = ["fig", str(b[1]), str(b[2]) if len(b) > 2 and b[2] else ""]
            elif kind == "q":
                if len(b) < 3:
                    continue
                b = ["q", str(b[1]), str(b[2])]
            elif kind in ("p", "h3", "eq"):
                if len(b) < 2:
                    continue
                b = [kind, str(b[1])]
            elif kind == "code":
                if len(b) < 3:
                    continue
                b = ["code", str(b[1]), str(b[2])] + ([str(b[3])] if len(b) > 3 and b[3] else [])
            elif kind == "note":
                if len(b) < 3:
                    continue
                b = ["note", str(b[1]), str(b[2])]
            else:
                continue
            body.append(b)
        s["body"] = body
        s["lec"] = str(s.get("lec") or "").strip() or "本节按课件顺序讲要点。"
    data["sections"] = [s for s in secs if isinstance(s, dict) and s.get("body")]
    if not data["sections"]:
        raise ValueError("规范化后没有可用正文块")
    for i, s in enumerate(data["sections"]):
        s["no"] = str(i)
    tail_no = len(data["sections"])
    for key in ("summary", "glossary", "appendix", "quiz"):
        d = data.get(key)
        if not isinstance(d, dict):
            continue
        d["no"] = str(tail_no)
        tail_no += 1
    for key, defaults in (("summary", {"head": ["要做什么", "要点", "怎么验"],
                                       "head_widths": ["26%", "42%", "32%"], "rows": [], "tail": ""}),
                          ("glossary", {"rows": []}),
                          ("appendix", {"symbols": [], "myths_title": "常见误解", "myths": []}),
                          ("quiz", {"items": []})):
        if not isinstance(data.get(key), dict):
            data[key] = dict(defaults)
        for k, v in defaults.items():
            data[key].setdefault(k, v)
    return data


def _glossary_rows(src: str, lang: str, model: str) -> list:
    sysmsg = ("你是药学讲义编辑。只从给定课件里抽取术语，不得编造。只输出 JSON 数组，"
              "不要代码围栏与注释。")
    if lang == "en":
        ask = ("From the slides below, extract 24 terms. Output a JSON array; each item is "
               "[Chinese term, English term, \"课件 p.N\", one-line English note]. Keep Chinese proper names. "
               "Cover definition, particle size/sieves, comminution, sieving, mixing, dosing, diluted powder, "
               "eutectic mixture, quality tests. Every page must be one given.\n\n")
    else:
        ask = ("从下面课件里抽 24 条术语，输出 JSON 数组，每条是 [中文, English, \"课件 p.N\", 一句中文解释]。"
               "覆盖散剂定义、粒度筛号、粉碎、筛分、混合、分剂量、倍散、低共熔、质量检查；"
               "每条页码必须是给定页；英文用药学通用译名。\n\n")
    out = client.chat([{"role": "system", "content": sysmsg},
                       {"role": "user", "content": ask + src}],
                      model=model, temperature=0.2, max_tokens=8000)
    try:
        rows = _json_of(out["text"])
    except Exception:  # noqa: BLE001
        # 术语是补充项：这一段没解析出来不该把整讲判死。
        return []
    if not isinstance(rows, list):
        return []
    fixed = []
    for r in rows:
        if isinstance(r, (list, tuple)) and len(r) >= 3:
            fixed.append([str(r[0]), str(r[1]), str(r[2]), str(r[3]) if len(r) > 3 else ""])
    return fixed


def _dump_raw(course: str, text: str, tag: str) -> str:
    """把模型「不是合法 JSON」的原文落盘。

    2026-11-21 用户只看到「[停] 补正文失败：JSONDecodeError(...)」——没有原文，连我都没法判断
    是多了个示例还是被截断。以后这条路上永远留一份 txt，路径会写进日志与报错里。
    """
    try:
        d = os.path.join(paths.data(course), "_trash")
        os.makedirs(d, exist_ok=True)
        p = os.path.join(d, "%s-%s.txt" % (tag, time.strftime("%Y%m%d-%H%M%S")))
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(text or "")
        return p
    except Exception:  # noqa: BLE001
        return "(原文落盘失败)"


def _write_lesson(course: str, no: str, data: dict, lang: str, emit=print) -> str:
    path = lesson_path(course, no, lang)
    if lang == "zh" and os.path.isfile(path):
        bak = os.path.join(paths.data(course), "_trash", "draft-" + time.strftime("%Y%m%d-%H%M%S"))
        os.makedirs(bak, exist_ok=True)
        shutil.copy2(path, os.path.join(bak, os.path.basename(path)))
        emit("[备份] 旧数据 → %s" % os.path.join(bak, os.path.basename(path)))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    head = "# -*- coding: utf-8 -*-\n"
    head += '"""%s · %s（DeepSeek 生成；出处按课件页标注，交人复核）"""\n\n' % (no, data.get("zh", ""))
    with open(path, "w", encoding="utf-8") as f:
        f.write(head + "LESSON = " + _pylit(data) + "\n")
    return path


def _page_chunks(blocks: list, limit: int) -> list:
    """按页把源文本切成 ≤limit 字符的段（不切页）。"""
    chunks, cur, size = [], [], 0
    for b in blocks:
        if cur and size + len(b) > limit:
            chunks.append(cur)
            cur, size = [], 0
        cur.append(b)
        size += len(b)
    if cur:
        chunks.append(cur)
    return chunks or [[]]


def _merge_parts(parts: list) -> dict:
    """多段生成的 LESSON 拼成一份：元信息取第一段，节按段顺序拼并重编号。

    2026-11-23 用户要求处理「超长课件」：以前超过 MAX_SRC 直接截断（后半本不参与生成）。
    现在按页切成多段分别生成，这里负责拼回去：
      · sections 按段顺序接起来（§0 导读只留第一段的，避免三份导读）；
      · summary / glossary / appendix / quiz 的列表合并去重（按首列/首项判重）；
      · 最后统一重编号 no=0,1,2…，保证渲染与内容门看到的仍然是「节号连续」。
    """
    base = dict(parts[0])
    secs = []
    for p in parts:
        for s in (p.get("sections") or []):
            if not isinstance(s, dict):
                continue
            if str(s.get("no")) == "0" and secs:
                continue
            secs.append(s)
    for i, s in enumerate(secs):
        s["no"] = str(i)
    base["sections"] = secs

    def _key(x):
        if isinstance(x, (list, tuple)) and x:
            return str(x[0]).strip().lower()
        if isinstance(x, dict):
            return str(x.get("zh") or x.get("en") or "").strip().lower()
        return str(x).strip().lower()

    for key, field in (("glossary", "rows"), ("appendix", "symbols"),
                       ("quiz", "items"), ("summary", "rows")):
        merged, seen = [], set()
        for p in parts:
            d = p.get(key)
            if not isinstance(d, dict):
                continue
            for item in (d.get(field) or []):
                k = _key(item)
                if k and k in seen:
                    continue
                seen.add(k)
                merged.append(item)
        if merged:
            base.setdefault(key, {})
            base[key][field] = merged
    tail = len(secs)
    for key in ("summary", "glossary", "appendix", "quiz"):
        if isinstance(base.get(key), dict):
            base[key]["no"] = str(tail)
            tail += 1
    return base


def _ask_lesson(sysmsg: str, body: str, fig_help: str, note: str,
                course: str, model: str, lang: str = "zh", emit=print) -> tuple:
    """问一次模型要 LESSON（原来那段「不合法就重试一次」的逻辑搬到这里，供分块调用复用）。"""
    npages = body.count("\u3010\u8bfe\u4ef6 p.")
    user = (("Slides (%d pages with text):\n\n%s\n\nProduce LESSON JSON in this shape:\n%s%s"
             % (npages, body, _SCHEMA, fig_help)) if lang == "en" else
            ("\u4e0b\u9762\u662f\u8bfe\u4ef6\u5168\u6587\uff08%d \u9875\u6709\u6587\u5b57\uff09\uff1a\n\n%s\n\n\u6309\u8fd9\u4e2a JSON \u7ed3\u6784\u8f93\u51fa LESSON\uff1a\n%s%s"
             % (npages, body, _SCHEMA, fig_help)))
    if note:
        user = note + "\n\n" + user
    out = client.chat([{"role": "system", "content": sysmsg}, {"role": "user", "content": user}],
                      model=model, temperature=0.3, max_tokens=30000)
    try:
        return _norm(_json_of(out["text"])), out
    except Exception as e1:  # noqa: BLE001
        # 2026-11-21 用户点「开始生成」只拿到一句「[停] 补正文失败：JSONDecodeError(...)」，
        #   界面等于死路。模型偶尔会多吐一段示例、或者输出被截断；这里把原文落盘、
        #   换更硬的提示再要一次，两次都不行才停（并告诉用户原文在哪）。
        dump1 = _dump_raw(course, out.get("text") or "", "draft-1")
        emit("[\u91cd\u8bd5] \u6a21\u578b\u8fd9\u6b21\u7ed9\u7684\u4e0d\u662f\u5408\u6cd5 JSON\uff08%s%s\uff09\uff1b\u539f\u6587\u5df2\u5b58 %s\uff0c\u6362\u4e00\u6b21\u66f4\u4e25\u683c\u7684\u63d0\u793a\u91cd\u6765\u3002"
             % (e1.__class__.__name__,
                "\uff0c\u8f93\u51fa\u88ab\u957f\u5ea6\u4e0a\u9650\u622a\u65ad" if out.get("finish_reason") == "length" else "",
                dump1))
        nudge = ("\u4e0a\u4e00\u6b21\u7684\u8f93\u51fa\u4e0d\u662f\u5408\u6cd5 JSON\uff08%s\uff09\u3002\u8bf7\u53ea\u8f93\u51fa**\u4e00\u4e2a** JSON \u5bf9\u8c61\uff1a"
                 "\u4e0d\u8981\u793a\u4f8b\u3001\u4e0d\u8981\u4ee3\u7801\u56f4\u680f\u3001\u4e0d\u8981\u6ce8\u91ca\u3001\u4e0d\u8981\u89e3\u91ca\uff1b\u5b57\u7b26\u4e32\u91cc\u4e0d\u8981\u51fa\u73b0\u672a\u8f6c\u4e49\u7684\u6362\u884c\u3002" % e1.__class__.__name__)
        out = client.chat([{"role": "system", "content": sysmsg},
                           {"role": "user", "content": user},
                           {"role": "assistant", "content": (out.get("text") or "")[:2000]},
                           {"role": "user", "content": nudge}],
                          model=model, temperature=0.1, max_tokens=30000)
        try:
            return _norm(_json_of(out["text"])), out
        except Exception as e2:  # noqa: BLE001
            dump2 = _dump_raw(course, out.get("text") or "", "draft-2")
            raise ValueError("\u6a21\u578b\u8fde\u7eed\u4e24\u6b21\u90fd\u6ca1\u7ed9\u51fa\u5408\u6cd5 JSON\uff08%s / %s\uff09\u3002\u539f\u6587\u5df2\u5b58\uff1a%s\u3001%s \u2014\u2014 \u628a\u8fd9\u884c\u53d1\u4f5c\u8005\uff0c\u6216\u76f4\u63a5\u518d\u70b9\u4e00\u6b21\u751f\u6210\u3002"
                             % (e1.__class__.__name__, e2.__class__.__name__, dump1, dump2)) from e2

def draft(course: str, no: str, lang: str = "zh", emit=print, model: str | None = None,
          save: bool = True) -> dict:
    """导入的原件 → DeepSeek 写 LESSON → 落盘（中文 <no>.py / 英文 <no>.en.py）。"""
    lang = "en" if str(lang).lower().startswith("en") else "zh"
    model = model or client.load_config()["model"]
    pdf, orig = source_of(course, no)
    emit("[原件] %s" % orig)
    blocks, ntext, total = page_blocks(pdf)
    src = "\n\n".join(blocks)
    if not src.strip():
        raise RuntimeError("这份 PDF 没有文字层（像是扫描件）：%s" % os.path.basename(pdf))
    chunks = _page_chunks(blocks, MAX_SRC)
    emit("[源文本] %d 页有文字 / 共 %d 页 · %d 字符%s"
         % (ntext, total, len(src),
            "" if len(chunks) == 1
            else "（超过单次上限 %d，分 %d 段分别生成再拼）" % (MAX_SRC, len(chunks))))
    fp, fs = fig_overrides(course, no)
    figs = extract_figures(pdf, course, no, emit=emit, fig_pages=fp, fig_skip=fs)
    fig_help = _fig_help(figs, lang)
    if not figs:
        emit("[图] 这一讲没有可用课件页图（原因见上面的 [图] 日志）；讲义里不会出现原件图")
    sysmsg = _SYS_EN if lang == "en" else _SYS_ZH
    # 图清单放在用户消息最后：模型最容易照最近读到的格式写（上面 _fig_help 有说明）。
    emit("[生成] %s · %s" % (model, "全英（专有名称中文）" if lang == "en" else "全中（专业名称英文）"))
    parts, out = [], None
    for k, ch in enumerate(chunks, 1):
        note = ""
        if len(chunks) > 1:
            note = (("This is part %d of %d of the slides. Write ONLY the sections covered by these "
                     "pages (page numbers are marked 【课件 p.N】)." % (k, len(chunks))) if lang == "en"
                    else ("这是课件的第 %d/%d 段，只写这一段覆盖的页（页号见【课件 p.N】）。"
                          % (k, len(chunks))))
        data_k, out = _ask_lesson(sysmsg, "\n\n".join(ch), fig_help, note,
                                  course, model, lang, emit=emit)
        parts.append(data_k)
    data = _merge_parts(parts) if len(parts) > 1 else parts[0]
    # 2026-11-21（R115，用户「一点原件的图也看不到」）：模型编的图名不再「静默整块删掉」。
    #   这里只点数并说明；真正按清单修名 / 补图在渲染时做（_build_讲义.ensure_figures），
    #   于是旧数据重打一遍 PDF 也能把漏掉的原件图补上，不必再花钱重跑模型。
    n_model_figs = sum(1 for s in data.get("sections", []) for b in s.get("body", [])
                       if b and b[0] == "fig")
    if figs:
        emit("[图] 模型引用课件页图 %d 处（清单 %d 张）%s"
             % (n_model_figs, len(figs),
                "" if n_model_figs else "——正文没写 fig 块，渲染时会按清单补齐并记日志"))
    emit("[生成] 完成 %.1fs · 入 %d / 出 %d tokens（含思考 %d）"
         % (out["seconds"], out.get("usage", {}).get("prompt_tokens", 0),
            out.get("usage", {}).get("completion_tokens", 0),
            (out.get("usage", {}).get("completion_tokens_details") or {}).get("reasoning_tokens", 0)))
    rows = data.get("glossary", {}).get("rows") or []
    if len(rows) < GLOSSARY_MIN:
        emit("[术语] 只有 %d 条，补到 %d 条" % (len(rows), GLOSSARY_MIN))
        # 分块生成时 src 是整份课件（可能很长）：术语抽取只喂第一段，别再把词表那次调用顶爆
        extra = _glossary_rows("\n\n".join(chunks[0]) if len(chunks) > 1 else src, lang, model)
        if extra:
            data["glossary"]["rows"] = extra
            data["glossary"].setdefault("lec", "术语按出现顺序整理，便于对照课件页码。")
            data["glossary"].setdefault("zh", "术语表")
            data["glossary"].setdefault("en", "Glossary")
    # 导入的讲：原件名要留住（用户 2026-11-18「导入的项目不是原本的名字」）
    if "orig" not in data:
        try:
            old = _read_text(lesson_path(course, no, "zh"))
            mo = re.search(r'"orig":\s*"([^"]*)"', old)
            src = re.search(r'"源课件"\s*,\s*"([^"]+)"', old)
            zh = re.search(r'"zh":\s*"([^"]*)"', old)
            if mo:
                data["orig"] = mo.group(1)
            elif src:
                data["orig"] = os.path.splitext(src.group(1).split("/")[-1])[0]
            elif zh:
                data["orig"] = zh.group(1)
            else:
                data["orig"] = os.path.splitext(orig)[0]
        except Exception:  # noqa: BLE001
            data["orig"] = os.path.splitext(orig)[0]
    data["code"] = course
    data["no"] = no
    data["lang"] = lang
    # 课件总页数：渲染时用它算「自动补图不超过总页数 1/3」的上限（R115，见 _build_讲义.ensure_figures）
    if total:
        data["figs_total"] = total
    title_src = data.get("en") if lang == "en" and data.get("en") else data.get("zh")
    title = re.sub(r"[\\/:*?\"<>|]+", "_", str(title_src or os.path.splitext(orig)[0]))
    data["zh"] = str(data.get("zh") or os.path.splitext(orig)[0])
    data.setdefault("en", "")
    data.setdefault("sub", "")
    data["out"] = "%s_%s_讲义%s.pdf" % (no, title, "_EN" if lang == "en" else "")
    data["meta"] = data.get("meta") or [
        ["源课件", "%s/%s" % (ORIG_DIR, orig)],
        ["状态", "DeepSeek 生成 · 出处按课件页 · 待人工复核"],
    ]
    data.setdefault("tail", [])
    info = {"no": no, "lang": lang, "title": data["zh"], "sections": len(data["sections"]),
            "source": orig, "seconds": out["seconds"], "usage": out.get("usage", {})}
    if save:
        path = _write_lesson(course, no, data, lang, emit=emit)
        info["file"] = path
        emit("[落盘] %s" % path)
    return info


def main(argv: list) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="导入原件 → DeepSeek 写讲义数据")
    ap.add_argument("no")
    ap.add_argument("--course", default=os.environ.get("PLUMA_COURSE") or "CS340")
    ap.add_argument("--lang", default="zh", choices=["zh", "en"])
    ap.add_argument("--model", default="")
    ap.add_argument("--no-save", action="store_true")
    a = ap.parse_args(argv)
    try:
        info = draft(a.course, a.no, a.lang, emit=print, model=(a.model or None), save=not a.no_save)
    except Exception as e:  # noqa: BLE001
        print("[失败] %r" % (e,))
        return 1
    print("[完成] %s" % json.dumps({k: v for k, v in info.items() if k != "usage"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
