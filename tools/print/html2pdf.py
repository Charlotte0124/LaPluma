"""HTML → PDF，用本机 Chrome headless 打印；可选自动回填目录页码与加页脚。

用法
    python tools\\print\\html2pdf.py "<源.html>" -o "<出.pdf>" --theme dark
    python tools\\print\\html2pdf.py "<源.html>" -o "<出.pdf>" --toc --footer "L01-02 · 强化学习基础与贝尔曼方程"

--toc 怎么工作
    源里每个目录项写成 <span class="pg" data-head="标题">·</span>。
    先打一遍草稿，用 pymupdf 搜每个「标题」落在第几页，把页码填回 HTML 再打正式版。
    标题改了、加节了，页码自动跟着变，不用手抄。

--footer
    打完在每页底部写「左：标签 / 右：N / M」，颜色与讲义一致的弱色。

退出码
    0 正常；2 参数或文件有问题；3 找不到 Chrome 或打印失败
"""

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pymupdf

CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]

CJK_FONT = r"C:\Windows\Fonts\msyh.ttc"   # 仅备用；页脚优先用内置 CJK 字体
MUTED = (0.43, 0.42, 0.38)                # #6E6B61
TOC_ITEM = re.compile(r'<span class="pg" data-head="([^"]+)">[^<]*</span>')


def find_chrome() -> str:
    for c in CHROME_CANDIDATES:
        if Path(c).exists():
            return c
    for name in ("chrome", "msedge"):
        got = shutil.which(name)
        if got:
            return got
    return ""


def render(chrome: str, html: Path, out: Path) -> bool:
    cmd = [
        chrome,
        "--headless=new",
        "--disable-gpu",
        "--no-pdf-header-footer",
        "--print-to-pdf-no-header",
        "--virtual-time-budget=5000",
        f"--print-to-pdf={out}",
        html.as_uri(),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=120,
                       encoding="utf-8", errors="replace")
    if out.exists():
        return True
    print("打印失败，Chrome 输出：", file=sys.stderr)
    print((r.stdout or "")[-800:], file=sys.stderr)
    print((r.stderr or "")[-800:], file=sys.stderr)
    return False


def page_of(pdf: Path, needle: str, min_size: float = 13.0) -> int:
    """某标题第一次出现的页号（1 起）；只认大字号行，否则目录页会把自己算进去。"""
    doc = pymupdf.open(pdf)
    try:
        for i, page in enumerate(doc, 1):
            for block in page.get_text("dict")["blocks"]:
                if block.get("type"):
                    continue
                for line in block["lines"]:
                    spans = [s for s in line["spans"] if s["text"].strip()]
                    if not spans:
                        continue
                    if max(s["size"] for s in spans) < min_size:
                        continue
                    text = "".join(s["text"] for s in spans).strip()
                    if text == needle:
                        return i
    finally:
        doc.close()
    return 0


def fill_toc(html: str, pdf: Path) -> tuple:
    """把目录里的占位符换成真实页码，返回 (新 HTML, 没找到的标题列表)。"""
    heads = TOC_ITEM.findall(html)
    pages = {h: page_of(pdf, h.strip()) for h in heads}
    miss = [h for h, p in pages.items() if not p]
    for h, p in pages.items():
        html = html.replace(f'<span class="pg" data-head="{h}">·</span>',
                            f'<span class="pg" data-head="{h}">{p or "·"}</span>')
    return html, miss


def postprocess(pdf: Path, label: str, bg: str = "") -> None:
    """在 Chrome 输出上铺底色（补上页边距那圈）+ 写页脚。

    Chrome 不会把 html/body 背景画进 @page 的页边距区，所以想要「有边距 + 黑底满页」
    只能打完再填一层底色（overlay=False 画在内容下层）。
    """
    doc = pymupdf.open(pdf)
    total = doc.page_count
    fill = None
    if bg and re.fullmatch(r"#?[0-9a-fA-F]{6}", bg):
        s = bg.lstrip("#")
        fill = tuple(int(s[i:i + 2], 16) / 255 for i in (0, 2, 4))
    # 内置 CJK 字体（不嵌字体文件，否则体积暴涨）
    cjk = None
    for name in ("china-s", "china-t", "japan", "korea"):
        try:
            cjk = pymupdf.Font(name)
            break
        except Exception:
            continue
    latin = pymupdf.Font("helv")
    try:
        for i, page in enumerate(doc, 1):
            if fill:
                page.draw_rect(page.rect, color=None, fill=fill, overlay=False)
            h = page.rect.height
            y = h - 8 * 72 / 25.4
            if label:
                page.insert_text((16 * 72 / 25.4, y), label,
                                 fontname="china-s" if cjk else "helv",
                                 fontsize=7.2, color=MUTED)
            num = f"{i} / {total}"
            width = latin.text_length(num, fontsize=7.6)
            page.insert_text((page.rect.width - 16 * 72 / 25.4 - width, y), num,
                             fontname="helv", fontsize=7.6, color=MUTED)
        try:
            doc.subset_fonts()
        except Exception:
            pass
        doc.saveIncr()
    finally:
        doc.close()


def main(argv: list | None = None) -> int:
    for s in (sys.stdout, sys.stderr):
        if hasattr(s, "reconfigure"):
            s.reconfigure(encoding="utf-8")

    ap = argparse.ArgumentParser(description="HTML → PDF（Chrome headless + 目录回填 + 页脚）")
    ap.add_argument("html", help="源 HTML（相对资源路径以它所在目录为基准）")
    ap.add_argument("-o", "--out", required=True, help="输出 PDF")
    ap.add_argument("--theme", default="as-is", choices=("dark", "light", "as-is"),
                    help="改 <html data-theme>；as-is 用源里的设置")
    ap.add_argument("--toc", action="store_true", help="自动回填目录页码（多打一遍草稿）")
    ap.add_argument("--footer", default="", help="页脚左侧标签，如「L01-02 · 强化学习基础与贝尔曼方程」")
    ap.add_argument("--bg", default="", help="补铺页面底色（如 #0E0E0C），用于深色满页效果")
    a = ap.parse_args(argv)

    src = Path(a.html).resolve()
    if not src.is_file():
        print(f"源文件不存在：{src}", file=sys.stderr)
        return 2
    out = Path(a.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)

    chrome = find_chrome()
    if not chrome:
        print("找不到 Chrome / Edge，没法打印 PDF", file=sys.stderr)
        return 3

    html = src.read_text(encoding="utf-8")
    if a.theme != "as-is":
        if not re.search(r"<html[^>]*data-theme=", html):
            print("源里没有 <html data-theme=…>，--theme 无从下手", file=sys.stderr)
            return 2
        html = re.sub(r'(<html[^>]*data-theme=")[^"]*(")', rf"\g<1>{a.theme}\g<2>", html, count=1)

    drafts = []

    def write_temp(text: str) -> Path:
        fd = tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8",
                                         dir=src.parent)
        fd.write(text)
        fd.close()
        drafts.append(Path(fd.name))
        return Path(fd.name)

    try:
        if a.toc:
            draft_pdf = out.with_suffix(".draft.pdf")
            if not render(chrome, write_temp(html), draft_pdf):
                return 3
            html, miss = fill_toc(html, draft_pdf)
            draft_pdf.unlink(missing_ok=True)
            if miss:
                print(f"目录回填：{len(miss)} 个标题没在 PDF 里找到（{', '.join(miss[:3])}…）",
                      file=sys.stderr)
            else:
                print(f"目录回填：{TOC_ITEM.findall(html).__len__()} 条全部命中")

        if not render(chrome, write_temp(html), out):
            return 3
    finally:
        for f in drafts:
            f.unlink(missing_ok=True)

    if a.footer or a.bg:
        postprocess(out, a.footer, a.bg)

    doc = pymupdf.open(out)
    pages = doc.page_count
    chars = sum(len(p.get_text()) for p in doc)
    doc.close()
    print(f"已写    {out}（{out.stat().st_size / 1024:.0f} KB · {pages} 页 · {chars} 字符）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
