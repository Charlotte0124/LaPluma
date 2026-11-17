# -*- coding: utf-8 -*-
"""把 Word / PowerPoint / 纯文本 / Markdown 抽成分页 PDF（只用标准库 + PyMuPDF）。

为什么是「转成 PDF」而不是「改流程」：
  · 讲义流水线的定位全靠页（内容门要求每条引文标「课件 p.N」），Word 与 PPT 没有页的概念；
  · 所以导入时就把它们排成一份 A4 PDF：PPT 一张幻灯片一页，Word 按段落顺序每页约 34 行，
    纯文本每页约 40 行。页码稳定、可回查，阅读页与三道门一行代码都不用改。
  · 只抽文字：图片、公式渲染、图上标注会丢（文档里写清楚了）；扫描件 PDF 仍然只能看图读。

命令：
    python engine\\_office.py <文件>          # 转换一次，旁边生成「<原名>（转换）.pdf」
    python engine\\_office.py --pages <文件>  # 只看会切成几页、每页首行是什么
"""
from __future__ import annotations

import os
import re
import sys
import zipfile
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 支持的原件后缀（PDF 与图片是原生支持，这里只列需要转换的）
CONVERTIBLE = (".docx", ".pptx", ".txt", ".md")
# 全部可导入的后缀（给界面提示与文件对话框用）
IMPORTABLE = (".pdf", ".png", ".jpg", ".jpeg", ".docx", ".pptx", ".txt", ".md")
SUFFIX_LABEL = {
    ".pdf": "PDF（原生）",
    ".png": "图片（原生）",
    ".jpg": "图片（原生）",
    ".jpeg": "图片（原生）",
    ".docx": "Word（导入时转成分页 PDF）",
    ".pptx": "PowerPoint（一张幻灯片一页）",
    ".txt": "纯文本（每页约 40 行）",
    ".md": "Markdown（每页约 40 行）",
}
CONVERT_TAG = "（转换）"

# A4 + 版心
PW, PH = 595.0, 842.0
MARGIN = 54.0
BODY_SIZE = 11.5
LINE_H = 17.0
TITLE_SIZE = 14.5
HEAD_SIZE = 9.0

_FONT_CACHE = {}


def _font():
    """找一个能写中文的字体文件（与生成讲义用的是同一批）。"""
    if "f" in _FONT_CACHE:
        return _FONT_CACHE["f"]
    cands = [
        r"C:\Windows\Fonts\msyh.ttc",
        r"C:\Windows\Fonts\msyh.ttf",
        r"C:\Windows\Fonts\msyhl.ttc",
        r"C:\Windows\Fonts\simsun.ttc",
        r"C:\Windows\Fonts\simhei.ttf",
    ]
    for c in cands:
        if os.path.isfile(c):
            _FONT_CACHE["f"] = c
            return c
    _FONT_CACHE["f"] = ""
    return ""


# ---------- 三种格式各抽成「页 + 行」 ----------

def _w_text_runs(xml: bytes) -> list:
    """从 Word/PPT 的 XML 里按段落抽文字。

    Word:  <w:p> 是一个段落，内部的 <w:t> 是文字片段；
    PPT:   <a:p> 是一个段落，<a:t> 是文字片段。
    命名空间随文件版本可能变，所以按「标签结尾」判断，不写死 ns URI。
    """
    out = []
    try:
        root = ET.fromstring(xml)
    except Exception:  # noqa: BLE001
        return out

    def walk(node, cur):
        tag = node.tag.split("}")[-1]
        if tag == "p":
            buf = []
            for t in node.iter():
                if t.tag.split("}")[-1] == "t" and (t.text or ""):
                    buf.append(t.text)
            text = "".join(buf).strip()
            out.append(text)
            return
        for ch in list(node):
            walk(ch, cur)

    walk(root, [])
    return [x for x in out if x]


def docx_pages(path: str) -> list:
    """Word：按段落顺序排版，每页约 34 行（标题行占两位）。"""
    with zipfile.ZipFile(path) as z:
        try:
            xml = z.read("word/document.xml")
        except KeyError:
            raise ValueError("这个 .docx 里找不到 word/document.xml（可能是 .doc 改的后缀）")
    paras = _w_text_runs(xml)
    return _pack(paras, per_page=34, title=os.path.splitext(os.path.basename(path))[0])


def pptx_pages(path: str) -> list:
    """PowerPoint：一张幻灯片一页；第一段当标题。"""
    pages = []
    with zipfile.ZipFile(path) as z:
        names = [n for n in z.namelist() if re.match(r"ppt/slides/slide\d+\.xml$", n)]
        names.sort(key=lambda n: int(re.search(r"(\d+)", os.path.basename(n)).group(1)))
        for n in names:
            paras = _w_text_runs(z.read(n))
            if not paras:
                paras = ["（这张幻灯片没有文字，只有图或媒体）"]
            pages.append({"title": paras[0], "lines": paras[1:] or [""]})
    if not pages:
        raise ValueError("这个 .pptx 里没有幻灯片")
    return pages


def text_pages(path: str) -> list:
    """纯文本 / Markdown：按行切，每页约 40 行；Markdown 只去掉井号与反引号。"""
    raw = open(path, "rb").read()
    for enc in ("utf-8-sig", "utf-8", "gbk", "cp936"):
        try:
            txt = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        txt = raw.decode("utf-8", "replace")
    if path.lower().endswith(".md"):
        lines = []
        for ln in txt.splitlines():
            s = re.sub(r"^#{1,6}\s*", "", ln)
            s = re.sub(r"^\s*[-*+]\s+", "· ", s)      # 列表符号换成间隔号，读起来更像课件
            s = s.replace("```", "").replace("**", "").replace("`", "")
            lines.append(s.rstrip())
        txt = "\n".join(lines)
    return _pack(txt.splitlines(), per_page=40, title=os.path.splitext(os.path.basename(path))[0])


def _pack(lines: list, per_page: int, title: str) -> list:
    lines = ["" if l is None else str(l).rstrip() for l in lines]
    pages = []
    for i in range(0, len(lines), per_page):
        chunk = lines[i:i + per_page]
        if not any(x.strip() for x in chunk):
            continue
        pages.append({"title": "", "lines": chunk})
    return pages or [{"title": "", "lines": ["（这个文件里没有可读文字）"]}]


def pages_of(path: str) -> list:
    """按后缀选抽取方式，返回 [{title, lines}]。"""
    ext = os.path.splitext(path)[1].lower()
    if ext == ".docx":
        return docx_pages(path)
    if ext == ".pptx":
        return pptx_pages(path)
    if ext in (".txt", ".md"):
        return text_pages(path)
    raise ValueError("不支持转换的后缀：%s" % ext)


# ---------- 排版成 PDF ----------

def _wrap(text: str, font, size: float, width: float) -> list:
    """按真实字宽折行（中文没有空格，只能量宽）。"""
    if not text.strip():
        return [""]
    out, line = [], ""
    for ch in text:
        cand = line + ch
        w = font.text_length(cand, size) if font else len(cand) * size * 0.55
        if w > width and line:
            out.append(line)
            line = ch
        else:
            line = cand
    if line:
        out.append(line)
    return out


def to_pdf(src: str, dst: str = "") -> dict:
    """把 src 排成 PDF 写到 dst（默认同目录 <原名>（转换）.pdf），返回统计。"""
    import pymupdf

    if not dst:
        d = os.path.dirname(os.path.abspath(src))
        stem = os.path.splitext(os.path.basename(src))[0]
        dst = os.path.join(d, stem + CONVERT_TAG + ".pdf")
    pages = pages_of(src)
    fontfile = _font()
    if not fontfile:
        raise RuntimeError("没找到中文字体（msyh.ttc），不能把 Office 文件排成 PDF")
    font = pymupdf.Font(fontfile=fontfile)
    doc = pymupdf.open()
    name = os.path.basename(src)
    width = PW - MARGIN * 2
    for i, pg in enumerate(pages, 1):
        page = doc.new_page(width=PW, height=PH)
        y = MARGIN
        # 页眉：来源 + 第几页（回查时报「课件 p.N」就对得上）
        page.insert_text((MARGIN, y), "%s ｜ 第 %d 页" % (name, i),
                         fontsize=HEAD_SIZE, fontfile=fontfile, fontname="cjk",
                         color=(0.45, 0.44, 0.41))
        y += LINE_H
        if pg.get("title"):
            for ln in _wrap(pg["title"], font, TITLE_SIZE, width):
                page.insert_text((MARGIN, y), ln, fontsize=TITLE_SIZE, fontfile=fontfile,
                                 fontname="cjkB", color=(0.10, 0.09, 0.08))
                y += LINE_H + 3
        for raw in pg["lines"]:
            for ln in _wrap(raw, font, BODY_SIZE, width):
                if y > PH - MARGIN - LINE_H:
                    break
                page.insert_text((MARGIN, y), ln, fontsize=BODY_SIZE, fontfile=fontfile,
                                 fontname="cjk", color=(0.12, 0.11, 0.10))
                y += LINE_H
            if y > PH - MARGIN - LINE_H:
                break
    doc.set_metadata({"title": name, "producer": "LaPluma _office"})
    try:
        doc.subset_fonts()      # 不裁子集会把 msyh.ttc 整份塞进去（实测 3 页 12 MB）
    except Exception:  # noqa: BLE001
        pass
    doc.save(dst, deflate=True, garbage=3)
    n = doc.page_count
    doc.close()
    return {"src": src, "pdf": dst, "pages": n}


def ensure_pdf(src: str) -> dict | None:
    """需要转换就转换；已经是 PDF/图片则返回 None。转换件比原件新就复用。"""
    ext = os.path.splitext(src)[1].lower()
    if ext not in CONVERTIBLE:
        return None
    d = os.path.dirname(os.path.abspath(src))
    stem = os.path.splitext(os.path.basename(src))[0]
    dst = os.path.join(d, stem + CONVERT_TAG + ".pdf")
    if os.path.isfile(dst) and os.path.getmtime(dst) >= os.path.getmtime(src):
        import pymupdf
        with pymupdf.open(dst) as doc:
            return {"src": src, "pdf": dst, "pages": doc.page_count, "cached": True}
    return to_pdf(src, dst)


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print(__doc__)
        return 2
    src = args[0]
    if not os.path.isfile(src):
        print("文件不存在：%s" % src)
        return 2
    if "--pages" in sys.argv:
        for i, pg in enumerate(pages_of(src), 1):
            first = pg["title"] or (pg["lines"][0] if pg["lines"] else "")
            print("  第 %d 页：%s" % (i, str(first)[:60]))
        return 0
    r = to_pdf(src)
    print("已写出：%s（%d 页）" % (r["pdf"], r["pages"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
