"""HTML → PDF，用本机 Chrome headless 打印；可选自动回填目录页码与加页脚。

用法
    python tools\\print\\html2pdf.py "<源.html>" -o "<出.pdf>" --theme dark
    python tools\\print\\html2pdf.py "<源.html>" -o "<出.pdf>" --toc --footer "L01-02 · 强化学习基础与贝尔曼方程"

--toc 怎么工作
    源里每个目录项写成 <span class="pg" data-head="标题">·</span>。
    先打一遍草稿，用 pymupdf 搜每个「标题」落在第几页，把页码填回 HTML 再打正式版。
    标题改了、加节了，页码自动跟着变，不用手抄。

--footer
    第一行左侧的讲次标签（如「L01-02 · 强化学习基础与贝尔曼方程」），右侧自动跟 N / M。

页脚三要素（2026-11-17 用户定，成品 PDF 一律带、不可关）
    第二行固定印「软件名 · 项目地址（可点）」与「本内容由 AI 生成，仅供参考…」，
    文案与地址的唯一出处是 tools\\print\\_brand.py。颜色跟着底色自动反转（深底浅字）。
    --no-post 只给调试用：正式成品不许少了这三样。

退出码
    0 正常；2 参数或文件有问题；3 找不到 Chrome 或打印失败
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pymupdf

# 品牌常量（软件名 / 项目地址 / 免责）在同目录的 _brand.py，改一处全仓生效
sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    import _brand as BRAND
except Exception:  # noqa: BLE001  万一打包漏了，页脚也不能空着
    class BRAND:  # type: ignore[no-redef]
        PRODUCT_NAME = "羽毛笔 La Pluma"
        PROJECT_URL = "https://github.com/Charlotte0124/LaPluma"
        PROJECT_URL_TEXT = "github.com/Charlotte0124/LaPluma"
        DISCLAIMER = "本内容由 AI 生成，仅供参考；重要信息请自行核实"
        DISCLAIMER_SHORT = "AI 生成，仅供参考"
        SEP = "·"

CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]

CJK_FONT = r"C:\Windows\Fonts\msyh.ttc"   # 仅备用；页脚优先用内置 CJK 字体
MUTED = (0.43, 0.42, 0.38)                # #6E6B61（浅底页脚用；深底另有一套，见 postprocess）
MM = 72 / 25.4                            # 1 毫米 = 2.8346 pt
FOOT = {"rule": 14.0, "row1": 11.0, "row2": 7.2}   # 页脚三条线离页底的距离（毫米）：细线在上，讲次居中，品牌在下
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
    """Chrome 无头打印一页。

    2026-11-21 实测（打包后的 exe）：Chrome 退出码 2147483651 = 0x80000003
    STATUS_BREAKPOINT，零输出、零字节，PDF 不落地；同一条命令在 python 下跑却是好的。
    根因是**父进程是 console=False 的打包程序**：它没有真的 stdin/stdout 句柄，
    子进程继承过去的是一堆无效句柄，Chrome 起来就撞断点。两处一起治：
      · stdin 显式给 DEVNULL，不再继承；
      · 万一还是 0x80000003（受限环境里 Chrome 的沙箱起不来），自动带 --no-sandbox 重试一次。
    另外失败时把 rc / 命令 / 两个尾部都写出来——原来只回显最后一行，那行正好是空行，
    界面上只剩「[停] 打印失败」，谁也查不出原因。
    """
    # 独立 profile：免得好落到用户正在用的默认 profile 上（那也会让 headless 静默退出）
    profile = Path(os.environ.get("TEMP") or ".") / "pluma-chrome-profile"
    try:
        profile.mkdir(parents=True, exist_ok=True)
    except Exception:  # noqa: BLE001
        profile = Path(os.environ.get("TEMP") or ".")
    base = [
        chrome,
        "--headless=new",
        "--disable-gpu",
        "--no-pdf-header-footer",
        "--print-to-pdf-no-header",
        "--virtual-time-budget=5000",
        f"--user-data-dir={profile}",
        f"--print-to-pdf={out}",
        html.as_uri(),
    ]
    BRK = 2147483651          # 0x80000003 STATUS_BREAKPOINT
    tries = [("默认", []), ("--no-sandbox", ["--no-sandbox"])]
    last = None
    for label, extra in tries:
        cmd = base[:-1] + extra + [base[-1]] if extra else list(base)
        try:
            r = subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                               timeout=120, encoding="utf-8", errors="replace",
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except Exception as e:  # noqa: BLE001
            print("打印失败：Chrome 起不来 %r" % (e,), file=sys.stderr)
            print("  命令：%s" % " ".join(cmd), file=sys.stderr)
            return False
        if out.exists() and out.stat().st_size > 0:
            if extra:
                print("（Chrome 第一次以 0x80000003 退出，带 --no-sandbox 重试成功）", file=sys.stderr)
            return True
        last = (label, cmd, r)
        if getattr(r, "returncode", None) != BRK:
            break
    label, cmd, r = last
    print("打印失败，Chrome 输出：", file=sys.stderr)
    print("  尝试：%s" % label, file=sys.stderr)
    print("  命令：%s" % " ".join(cmd), file=sys.stderr)
    print("  退出码：%r · 有输出 %d / 错误 %d 字节" % (getattr(r, "returncode", None),
                                                     len(r.stdout or ""), len(r.stderr or "")),
          file=sys.stderr)
    print("  stdout：" + (r.stdout or "")[-600:], file=sys.stderr)
    print("  stderr：" + (r.stderr or "")[-600:], file=sys.stderr)
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


def _runs(text: str) -> list:
    """按字符集切段：ASCII 走 helv、其余走内置 CJK。

    实测（2026-11-17）内置 china-s 把拉丁画成全角：「La Pluma」度量 27.9pt、实际占 52.8pt，
    混排时 URL 会叠到中文上。所以拉丁一行只能走 helv，中文一行只能走 CJK。
    """
    out, buf, kind = [], "", None
    for ch in text:
        k = "lat" if ord(ch) < 128 else "zh"
        if k != kind and buf:
            out.append((buf, kind))
            buf = ""
        kind, buf = k, buf + ch
    if buf:
        out.append((buf, kind))
    return out


def _width(text: str, size: float, zh, lat) -> float:
    return sum((zh if k == "zh" else lat).text_length(r, fontsize=size) for r, k in _runs(text))


def _lum(rgb) -> float:
    return 0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]


def _page_is_dark(page) -> bool:
    """没传 --bg 时探一眼页脚那一条的底色（深色讲义否则会拿深灰字写上看不见）。"""
    try:
        clip = pymupdf.Rect(6 * MM, page.rect.height - 15 * MM,
                            min(page.rect.width, 60 * MM), page.rect.height - 5 * MM)
        pm = page.get_pixmap(clip=clip, colorspace=pymupdf.csRGB)
        s, acc, cnt = pm.samples, [0, 0, 0], 0
        for i in range(0, len(s) - 3, 3 * 11):
            acc[0] += s[i]; acc[1] += s[i + 1]; acc[2] += s[i + 2]; cnt += 1
        if not cnt:
            return False
        return _lum([c / cnt / 255 for c in acc]) < 0.45
    except Exception:  # noqa: BLE001
        return False


def postprocess(pdf: Path, label: str, bg: str = "") -> None:
    """在 Chrome 输出上铺底色（补上页边距那圈）+ 写页脚。

    Chrome 不会把 html/body 背景画进 @page 的页边距区，所以想要「有边距 + 黑底满页」
    只能打完再填一层底色（overlay=False 画在内容下层）。

    页脚（每页固定，2026-11-17 用户定：软件名 / 项目地址 / AI 免责）：
        细线 ───────────────────────────────────────────────
        左 讲次标签（长则截断）                右 N / M
        左 软件名 · 项目地址（可点）            右 免责文案
    导航效果靠层次，不靠砌字：主行较实、品牌行次之、免责最淡，细线把页脚与正文隔开。
    颜色跟着底色反转——以前写死深灰，深色讲义上这行等于没印（#0E0E0C 底 + #6E6B61 字）。
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
    fn = "china-s" if cjk else "helv"
    zh, latin = (cjk or pymupdf.Font("helv")), pymupdf.Font("helv")

    try:
        # 深浅只需要定一次：传了 --bg 看它，没传就看页脚那一带实际像素
        dark = _lum(fill) < 0.45 if fill else _page_is_dark(doc[0])
        if dark:
            c_label, c_page = (0.80, 0.79, 0.75), (0.60, 0.59, 0.55)
            c_brand, c_link = (0.66, 0.65, 0.61), (0.46, 0.80, 0.58)
            c_note, c_rule = (0.50, 0.49, 0.45), (0.24, 0.24, 0.22)
        else:
            c_label, c_page = (0.30, 0.29, 0.26), (0.50, 0.49, 0.45)
            c_brand, c_link = (0.42, 0.41, 0.37), (0.13, 0.45, 0.28)
            c_note, c_rule = (0.55, 0.54, 0.50), (0.84, 0.82, 0.78)

        pre = BRAND.PRODUCT_NAME + " " + BRAND.SEP + " "
        y1, y2 = FOOT["row1"] * MM, FOOT["row2"] * MM
        s_label, s_brand = 7.2, 6.6

        def put(page, x: float, base: float, text: str, size: float, color) -> float:
            """从 x 起按字符集分段画一行（同色），返回结束位置。"""
            for run, kind in _runs(text):
                f = zh if kind == "zh" else latin
                page.insert_text((x, base), run,
                                 fontname=(fn if kind == "zh" else "helv"),
                                 fontsize=size, color=color)
                x += f.text_length(run, fontsize=size)
            return x

        for i, page in enumerate(doc, 1):
            if fill:
                page.draw_rect(page.rect, color=None, fill=fill, overlay=False)
            h, w = page.rect.height, page.rect.width
            left, right = 16 * MM, w - 16 * MM
            page.draw_line((left, h - FOOT["rule"] * MM), (right, h - FOOT["rule"] * MM),
                           color=c_rule, width=0.5)

            # ---- 第一行：讲次标签 ←→ N / M ----
            num = f"{i} / {total}"
            num_w = latin.text_length(num, fontsize=7.6)
            page.insert_text((right - num_w, h - y1), num,
                             fontname="helv", fontsize=7.6, color=c_page)
            if label:
                avail = right - num_w - 6 * MM - left
                text = label
                while _width(text, s_label, zh, latin) > avail and len(text) > 6:
                    text = text[:-2]
                if text != label:
                    text = text[:-1] + "…"
                put(page, left, h - y1, text, s_label, c_label)

            # ---- 第二行：软件名 · 地址（可点） ←→ 免责 ----
            note = BRAND.DISCLAIMER
            need = (_width(pre + BRAND.PROJECT_URL_TEXT, s_brand, zh, latin)
                    + _width(note, s_brand, zh, latin) + 10 * MM)
            if need > right - left:
                note = BRAND.DISCLAIMER_SHORT
            put(page, right - _width(note, s_brand, zh, latin), h - y2, note, s_brand, c_note)
            x0 = put(page, left, h - y2, pre, s_brand, c_brand)
            x1 = put(page, x0, h - y2, BRAND.PROJECT_URL_TEXT, s_brand, c_link)
            page.draw_line((x0, h - y2 + 1.1), (x1, h - y2 + 1.1), color=c_link, width=0.35)
            page.insert_link({"kind": pymupdf.LINK_URI, "uri": BRAND.PROJECT_URL,
                              "from": pymupdf.Rect(x0, h - y2 - 6.2, x1, h - y2 + 2.0)})
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
    ap.add_argument("--no-post", action="store_true",
                    help="不写页脚（仅调试；成品 PDF 一律带品牌页脚）")
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

    if not a.no_post:
        postprocess(out, a.footer, a.bg)

    doc = pymupdf.open(out)
    pages = doc.page_count
    chars = sum(len(p.get_text()) for p in doc)
    doc.close()
    print(f"已写    {out}（{out.stat().st_size / 1024:.0f} KB · {pages} 页 · {chars} 字符）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
