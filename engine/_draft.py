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
GLOSSARY_MIN = 20        # 内容门要求的最小术语条数
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


def pages_text(pdf: str, emit=print) -> tuple[str, int, int]:
    """PDF 文字层 → (带页码的文本, 有文字的页数, 总页数)。扫描件会得到 0 页。"""
    try:
        import pymupdf
    except Exception as e:  # noqa: BLE001
        raise RuntimeError("缺 pymupdf，读不了 PDF：%r" % (e,))
    doc = pymupdf.open(pdf)
    out, n = [], 0
    total = len(doc)
    for i, pg in enumerate(doc, 1):
        t = (pg.get_text("text") or "").strip()
        if not t:
            continue
        t = "\n".join(x.strip() for x in t.splitlines() if x.strip())
        out.append("【课件 p.%d】\n%s" % (i, t))
        n += 1
    text = "\n\n".join(out)
    if not text:
        raise RuntimeError("这份 PDF 没有文字层（像是扫描件）：%s" % os.path.basename(pdf))
    if len(text) > MAX_SRC:
        emit("[注意] 源文本 %d 字符，超过上限 %d，只取前 %d 字符（后半本未参与生成）"
             % (len(text), MAX_SRC, MAX_SRC))
        text = text[:MAX_SRC]
    return text, n, total


def _save_page_png(page, out_root: str, i: int) -> str | None:
    """把一页课件导出成 96 dpi 的整页 PNG；成功返回文件名，失败返回 None。"""
    try:
        pix = page.get_pixmap(dpi=96)
        name = "p%03d.png" % i
        pix.save(os.path.join(out_root, name))
        return name
    except Exception:  # noqa: BLE001
        return None


def extract_figures(pdf: str, course: str, no: str, emit=print) -> list:
    """把课件页导出成整页 PNG，供模型用 fig 块引用。

    2026-11-19 用户：「生成的东西少了引用课件 PDF 原文截图图片」——讲义要以课件为依据，
    不是只把文字复述一遍。导出有图片对象的页，最多 MAX_FIGS 张，96 dpi。
    2026-11-21 用户：「为什么我一点原件的图也看不到」——两条修：
      · 纯文字 / 矢量版式的课件（没有图片对象）不再「抽 0 张、一声不响」：改为整页导出，
        让读者至少能看到原件版式（日志写明这是兜底，最多 FALLBACK_FIGS 张）；
      · 导出前清掉上一次的 pNNN.png，换课件重导不会把旧图混进新讲义。
    返回 [(相对 <课程>\\06_笔记\\assets 的路径, 页码), …]；返回空列表时日志一定说明原因。
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

    out, total, with_img, failed = [], 0, 0, 0
    try:
        with pymupdf.open(pdf) as doc:
            total = len(doc)
            for i, page in enumerate(doc, 1):
                try:
                    imgs = page.get_images(full=True)
                except Exception:  # noqa: BLE001
                    continue
                if not imgs:
                    continue
                with_img += 1
                if len(out) >= MAX_FIGS:
                    continue
                name = _save_page_png(page, out_root, i)
                if name:
                    out.append(("gen/%s/%s" % (no, name), i))
                else:
                    failed += 1
            if not out:
                # 兜底：这份课件没有图片对象（纯文字/矢量版式）。整页导出，别静默给一份没图的讲义。
                cap = min(MAX_FIGS, FALLBACK_FIGS)
                for i, page in enumerate(doc, 1):
                    if len(out) >= cap:
                        break
                    try:
                        if not (page.get_text("text") or "").strip():
                            continue          # 空白页不导
                    except Exception:  # noqa: BLE001
                        continue
                    name = _save_page_png(page, out_root, i)
                    if name:
                        out.append(("gen/%s/%s" % (no, name), i))
                if out:
                    emit("[图] 这份课件 %d 页都没有图片对象（纯文字/矢量版式）：改为整页导出 %d 页，"
                         "让讲义能看到原件版式 → %s" % (total, len(out), out_root))
                else:
                    emit("[图] 这份课件导不出页图（%d 页既没有图片对象、也没有文字层，像是扫描件）"
                         "→ 这一讲不会有原件图" % total)
                    return []
    except Exception as e:  # noqa: BLE001
        emit("[图] 抽图失败（%r）；这一讲不会有原件图" % (e,))
        return []
    if out and with_img:
        emit("[图] 课件共 %d 页：有图片对象的 %d 页 → 导出 %d 张%s → %s"
             % (total, with_img, len(out),
                "（另有 %d 页导出失败）" % failed if failed else "", out_root))
    if out and with_img > len(out) and not failed:
        emit("[图] 注意：课件有 %d 页带图，超过单讲上限 %d 张，后面的图没导出"
             % (with_img, MAX_FIGS))
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


def draft(course: str, no: str, lang: str = "zh", emit=print, model: str | None = None,
          save: bool = True) -> dict:
    """导入的原件 → DeepSeek 写 LESSON → 落盘（中文 <no>.py / 英文 <no>.en.py）。"""
    lang = "en" if str(lang).lower().startswith("en") else "zh"
    model = model or client.load_config()["model"]
    pdf, orig = source_of(course, no)
    emit("[原件] %s" % orig)
    src, ntext, total = pages_text(pdf, emit=emit)
    emit("[源文本] %d 页有文字 / 共 %d 页 · %d 字符" % (ntext, total, len(src)))
    figs = extract_figures(pdf, course, no, emit=emit)
    fig_help = _fig_help(figs, lang)
    if not figs:
        emit("[图] 这一讲没有可用课件页图（原因见上面的 [图] 日志）；讲义里不会出现原件图")
    sysmsg = _SYS_EN if lang == "en" else _SYS_ZH
    # 图清单放在用户消息最后：模型最容易照最近读到的格式写（上面 _fig_help 有说明）。
    user = (("Slides (%d pages with text):\n\n%s\n\nProduce LESSON JSON in this shape:\n%s%s"
             % (ntext, src, _SCHEMA, fig_help)) if lang == "en" else
            ("下面是课件全文（%d 页有文字）：\n\n%s\n\n按这个 JSON 结构输出 LESSON：\n%s%s"
             % (ntext, src, _SCHEMA, fig_help)))
    emit("[生成] %s · %s" % (model, "全英（专有名称中文）" if lang == "en" else "全中（专业名称英文）"))
    out = client.chat([{"role": "system", "content": sysmsg}, {"role": "user", "content": user}],
                      model=model, temperature=0.3, max_tokens=30000)
    try:
        data = _norm(_json_of(out["text"]))
    except Exception as e1:  # noqa: BLE001
        # 2026-11-21 用户点「开始生成」只拿到一句「[停] 补正文失败：JSONDecodeError(...)」，
        #   界面等于死路。模型偶尔会多吐一段示例、或者输出被截断；这里把原文落盘、
        #   换更硬的提示再要一次，两次都不行才停（并告诉用户原文在哪）。
        dump1 = _dump_raw(course, out.get("text") or "", "draft-1")
        emit("[重试] 模型这次给的不是合法 JSON（%s%s）；原文已存 %s，换一次更严格的提示重来。"
             % (e1.__class__.__name__,
                "，输出被长度上限截断" if out.get("finish_reason") == "length" else "",
                dump1))
        nudge = ("上一次的输出不是合法 JSON（%s）。请只输出**一个** JSON 对象："
                 "不要示例、不要代码围栏、不要注释、不要解释；字符串里不要出现未转义的换行。" % e1.__class__.__name__)
        out = client.chat([{"role": "system", "content": sysmsg},
                           {"role": "user", "content": user},
                           {"role": "assistant", "content": (out.get("text") or "")[:2000]},
                           {"role": "user", "content": nudge}],
                          model=model, temperature=0.1, max_tokens=30000)
        try:
            data = _norm(_json_of(out["text"]))
        except Exception as e2:  # noqa: BLE001
            dump2 = _dump_raw(course, out.get("text") or "", "draft-2")
            raise ValueError("模型连续两次都没给出合法 JSON（%s / %s）。原文已存：%s、%s —— 把这行发作者，或直接再点一次生成。"
                             % (e1.__class__.__name__, e2.__class__.__name__, dump1, dump2)) from e2
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
        extra = _glossary_rows(src, lang, model)
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