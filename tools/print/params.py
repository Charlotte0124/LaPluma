"""记录一次讲义制作的全部参数，写成 JSON，保证任何人（或未来的我）能复现同一份成品。

为什么要有这个：讲义现在有两本书、六七个工具、十来个参数（dpi、长边、质量、切块、主题、
页面边距、图高、目录条数、页脚文字……）。只看 PDF 或只看命令历史都还原不出来。

用法（lesson.ps1 会自动调用，也可以单独跑）
    python tools\\print\\params.py --course BSAI402 --lesson L01-02 `
        --pdf "BSAI402\\01_讲义\\Week1-2-Introduction-PDF.pdf" `
        --origin-pdf "BSAI402\\01_讲义\\L01-02_..._课件原文.pdf" `
        --note-pdf   "BSAI402\\01_讲义\\L01-02_..._课件笔记.pdf" `
        --source     "BSAI402\\06_笔记\\L01-02_零基础_讲义_源.html"

产物
    <课程>\\01_讲义\\<课程>_<编号>_制作参数.json      紧随成品保存，一起入库

退出码：0 正常；2 参数有问题（缺原件）
"""

import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parents[2]
# 2026-11-17：路径双根（见仓根 paths.py）；本脚本只记参数、写数据，跟数据根走
sys.path.insert(0, str(ROOT))
import paths  # noqa: E402
ROOT = Path(paths.DATA_ROOT)


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def pdf_facts(p: Path) -> dict:
    if not p or not p.exists():
        return {}
    doc = pymupdf.open(p)
    try:
        chars = sum(len(pg.get_text()) for pg in doc)
        return {"file": p.name, "pages": doc.page_count, "chars": chars,
                "bytes": p.stat().st_size, "sha256_16": sha256(p)}
    finally:
        doc.close()


def extract_facts(md: Path) -> dict:
    if not md.exists():
        return {}
    t = md.read_text(encoding="utf-8")
    pages = len(re.findall(r"<!--\s*(?:p\.\d+|page\s+\d+\s+of\s+\d+)\s*-->", t))
    origin = "MinerU 本地 OCR" if re.search(r"<!--\s*page\s+\d+\s+of", t) else "pdf_flow 直抽"
    return {"file": md.name, "pages": pages, "chars": len(t), "origin": origin}


def assets_facts(d: Path, prefix: str = "") -> dict:
    """只数本讲课件裁的图（文件名以原件名开头），别把其他讲的一起数进去。"""
    if not d.is_dir():
        return {}
    pat = f"{prefix}_*" if prefix else "*"
    files = [f for f in d.glob(pat + ".jpg")] + [f for f in d.glob(pat + ".png")]
    return {"dir": str(d.relative_to(ROOT)), "prefix": prefix or "*", "count": len(files),
            "bytes": sum(f.stat().st_size for f in files)}


CSS_PATTERNS = {
    "page_margin": r"@page\{[^}]*margin:\s*([^;}]+)",
    "page_size": r"@page\{[^}]*size:\s*([^;}]+)",
    "bg": r"--bg:\s*(#[0-9a-fA-F]{6})",
    "text_color": r"--text:\s*(#[0-9a-fA-F]{6})",
    "amber": r"--amber:\s*(#[0-9a-fA-F]{6})",
    "body_font_size": r"body\{[^}]*font-size:\s*([0-9.]+pt)",
    "body_line_height": r"body\{[^}]*line-height:\s*([0-9.]+)",
    "figure_max_height": r"figure img\{[^}]*max-height:\s*([0-9.]+mm)",
    "eq_white_space": r"\.eq\{[^}]*(white-space:\s*[a-z-]+)",
    "h2_font_size": r"h2 \.zh\{[^}]*font-size:\s*([0-9.]+pt)",
}


def css_facts(html: Path) -> dict:
    if not html.exists():
        return {}
    t = html.read_text(encoding="utf-8")
    out = {}
    for k, pat in CSS_PATTERNS.items():
        m = re.search(pat, t)
        if m:
            out[k] = m.group(1).strip()
    out["toc_entries"] = len(re.findall(r'class="pg" data-head=', t))
    out["figures"] = len(re.findall(r"<img\s", t))
    m = re.search(r'<meta\s+name="out"\s+content="([^"]+)"', t)
    if m:
        out["declared_out"] = m.group(1)
    return out


def chrome_version() -> str:
    for exe in (r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"):
        if Path(exe).exists():
            try:
                r = subprocess.run([exe, "--version"], capture_output=True, text=True,
                                   timeout=20, encoding="utf-8", errors="replace")
                return (r.stdout or r.stderr).strip()
            except Exception:
                return "未知"
    return "未找到"


def tool_versions() -> dict:
    import platform
    v = {"python": platform.python_version(), "pymupdf": pymupdf.__version__,
         "chrome": chrome_version()}
    try:
        import PIL
        v["pillow"] = PIL.__version__
    except Exception:
        pass
    try:
        h = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True,
                           text=True, timeout=10, cwd=ROOT)
        if h.returncode == 0:
            v["git_commit"] = h.stdout.strip()
    except Exception:
        pass
    return v


def main() -> int:
    for s in (sys.stdout, sys.stderr):
        if hasattr(s, "reconfigure"):
            s.reconfigure(encoding="utf-8")

    ap = argparse.ArgumentParser(description="记录一次讲义制作的全部参数")
    ap.add_argument("--course", required=True)
    ap.add_argument("--lesson", required=True)
    ap.add_argument("--pdf", required=True, help="课件原件")
    ap.add_argument("--origin-pdf", default="", help="课件原文 PDF")
    ap.add_argument("--note-pdf", default="", help="课件笔记 PDF")
    ap.add_argument("--source", default="", help="笔记的 HTML 源")
    a = ap.parse_args()

    pdf = (ROOT / a.pdf) if not Path(a.pdf).is_absolute() else Path(a.pdf)
    if not pdf.exists():
        print(f"原件不存在：{pdf}", file=sys.stderr)
        return 2

    course = ROOT / a.course
    note_dir = course / "06_笔记"
    stem = pdf.stem

    src_pdf = Path(a.origin_pdf) if a.origin_pdf else None
    note_pdf = Path(a.note_pdf) if a.note_pdf else None
    html = Path(a.source) if a.source else None

    data = {
        "生成参数": {
            "course": a.course,
            "lesson": a.lesson,
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "git_commit": tool_versions().get("git_commit", ""),
            "复现命令": [
                f'python tools\\pdf\\pdf_flow.py build "{a.pdf}"',
                'python tools\\print\\src_pdf.py "<提取正文.md>" -o "<…_课件原文.pdf>" '
                '--title "<编号> <标题> · 课件原文" --note "<…_课件笔记.pdf>"',
                'python tools\\print\\html2pdf.py "<讲义源.html>" -o "<…_课件笔记.pdf>" '
                '--theme dark --toc --bg "#0E0E0C" --footer "<编号> · <标题> · 课件笔记"',
                'python tools\\print\\params.py …（本文件）',
            ],
        },
        "课件原件": pdf_facts(pdf),
        "素材": {
            "命令参数": {"dpi": 150, "max_edge": 1600, "format": "jpg", "quality": 85,
                         "split": "auto"},
            "提取正文": extract_facts(note_dir / f"{stem}_提取正文.md"),
            "页码地图": (lambda p: {"file": p.name, "bytes": p.stat().st_size} if p.exists() else {})(
                note_dir / f"{stem}_outline.md"),
            "裁图": assets_facts(note_dir / "assets", stem),
        },
        "课件原文": pdf_facts(src_pdf) if src_pdf else {},
        "课件笔记": pdf_facts(note_pdf) if note_pdf else {},
        "笔记源样式": css_facts(html) if html else {},
        "工具版本": tool_versions(),
    }

    out = course / "01_讲义" / f"{a.course}_{a.lesson}_制作参数.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def line(k, v):
        print(f"  {k:<10}{v}")

    print(f"已写    {out.relative_to(ROOT)}")
    op, npd = data["课件原文"], data["课件笔记"]
    if op:
        line("原文", f"{op['pages']} 页 · {op['chars']:,} 字符 · {op['bytes'] / 1024:.0f} KB")
    if npd:
        line("笔记", f"{npd['pages']} 页 · {npd['chars']:,} 字符 · {npd['bytes'] / 1024:.0f} KB")
    m = data["素材"]["裁图"]
    if m:
        line("裁图", f"{m['count']} 张 · {m['bytes'] / 1024 / 1024:.2f} MB")
    cs = data["笔记源样式"]
    if cs:
        line("版式", f"{cs.get('page_margin', '?')} · 图高 {cs.get('figure_max_height', '?')} "
                     f"· 目录 {cs.get('toc_entries', 0)} 条 · 底色 {cs.get('bg', '?')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
