# -*- coding: utf-8 -*-
"""判据：成品 PDF 页脚三要素（PRTS R105，2026-11-17 立）

    python tools\\check\\check-pdf-brand.py              # 查（0 绿 / 1 红 / 2 没查成）
    python tools\\check\\check-pdf-brand.py -SelfTest    # 造坏自测（4 例 + 复原全绿）

为什么要有：用户原话「把生成出来的 PDF 下面加入 AI 生成仅供参考，然后加上我项目的地址和
软件的名字（页脚的位置），注意要美观」。以前 README 写着「页脚固定印着免责」，代码里其实
从没印过——说的和做的对不上，所以这条要机器判。

查六项（全在临时目录造 PDF，不动真实课程数据）：
  1 品牌常量齐：_brand.py 里软件名 / 地址 / 免责都非空，地址是 https
  2 页脚真印出来了：每一页 get_text() 都含软件名、地址短写、免责文案
  3 地址可点：每页 get_links() 里有 uri == PROJECT_URL
  4 浅底看得见：页脚区像素亮度跨度够（不是同色写字）
  5 深底看得见：#0E0E0C 满页时页脚同样有对比度（以前写死深灰，深色讲义上等于没印）
  6 默认就印：html2pdf.main 不带 --footer/--bg 也走 postprocess（不许靠调用方记得传参）

退出码：0 全绿 / 1 有红 / 2 没查成（缺 pymupdf 或源文件）
"""
from __future__ import annotations

import importlib
import os
import shutil
import sys
import tempfile

try:
    sys.stdout.reconfigure(line_buffering=True)
except Exception:  # noqa: BLE001
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
PRINT_DIR = os.path.join(ROOT, "tools", "print")
MM = 72 / 25.4
RESULT = []
# 自测用锚点：深底配色那三行（改了实现就要一起改这里，否则自测会先说「没改到」）
DARK_BLOCK = ("            c_label, c_page = (0.80, 0.79, 0.75), (0.60, 0.59, 0.55)\n"
              "            c_brand, c_link = (0.66, 0.65, 0.61), (0.46, 0.80, 0.58)\n"
              "            c_note, c_rule = (0.50, 0.49, 0.45), (0.24, 0.24, 0.22)")


def note(ok: bool, name: str, detail: str = "") -> None:
    RESULT.append((bool(ok), name, detail))
    print(("  [绿] " if ok else "  [红] ") + name + (("｜" + detail) if detail and not ok else ""))


def load(src_dir: str):
    """从指定目录加载 html2pdf 与 _brand（自测时指向临时副本）。"""
    for m in ("html2pdf", "_brand"):
        sys.modules.pop(m, None)
    sys.path.insert(0, src_dir)
    try:
        mod = importlib.import_module("html2pdf")
    finally:
        sys.path.pop(0)
    return mod, sys.modules["_brand"]


def make_pdf(path: str, pages: int = 2) -> None:
    """造一份「有正文、有页边距」的 PDF，模拟 Chrome 打出来的样子。"""
    import pymupdf
    doc = pymupdf.open()
    for i in range(pages):
        pg = doc.new_page(width=210 * MM, height=297 * MM)
        y = 32 * MM
        for ln in ("第一段正文，用来占住上方版面。", "第二段正文。", "第三段正文。"):
            pg.insert_text((16 * MM, y), ln, fontname="china-s", fontsize=10.5)
            y += 7 * MM
        pg.insert_text((16 * MM, 120 * MM), "第 %d 页" % (i + 1),
                       fontname="china-s", fontsize=10.5)
    doc.save(path)
    doc.close()


def foot_contrast(path: str) -> list:
    """页脚那一条的亮度跨度（max-min，0..1）：同色写字会接近 0。"""
    import pymupdf
    out = []
    doc = pymupdf.open(path)
    try:
        for pg in doc:
            clip = pymupdf.Rect(14 * MM, pg.rect.height - 14.5 * MM,
                                pg.rect.width - 14 * MM, pg.rect.height - 4 * MM)
            pm = pg.get_pixmap(clip=clip, colorspace=pymupdf.csRGB, dpi=150)
            s = pm.samples
            lo, hi = 255.0, 0.0
            for i in range(0, len(s) - 3, 3 * 5):
                lum = 0.299 * s[i] + 0.587 * s[i + 1] + 0.114 * s[i + 2]
                lo = min(lo, lum)
                hi = max(hi, lum)
            out.append((hi - lo) / 255)
    finally:
        doc.close()
    return out


def run_checks(mod, brand) -> int:
    """对一个（可能是副本的）实现跑六项，返回红条数。"""
    import pymupdf
    red = 0

    # 1 常量齐（含界面同源：别再出现一份手写旧文案）
    name, url, urlt, disc = (brand.PRODUCT_NAME, brand.PROJECT_URL,
                             brand.PROJECT_URL_TEXT, brand.DISCLAIMER)
    ok = bool(name.strip()) and bool(url.strip()) and bool(urlt.strip()) and bool(disc.strip())
    ok = ok and url.startswith("https://") and ("AI" in disc) and ("仅供参考" in disc)
    ui_note = ""
    try:
        idx = open(os.path.join(ROOT, "ui", "index.html"), encoding="utf-8").read()
        srv = open(os.path.join(ROOT, "ui", "server.py"), encoding="utf-8").read()
        same = (disc in idx) and ("BRAND.DISCLAIMER" in srv)
        if not same:
            ok = False
            ui_note = "；界面与 PDF 不同源（index.html 里找不到这句 / server.py 没用 BRAND.DISCLAIMER）"
    except OSError:
        ui_note = "；没读到 ui\\ 文件，同源这项没查"
        ok = False
    note(ok, "品牌常量齐且界面同源（软件名 / https 地址 / 含「AI 生成·仅供参考」的免责）",
         "name=%r url=%r disc=%r%s" % (name, url, disc, ui_note))
    red += 0 if ok else 1

    tmp = tempfile.mkdtemp(prefix="pluma-brand-")
    try:
        light = os.path.join(tmp, "light.pdf")
        dark = os.path.join(tmp, "dark.pdf")
        make_pdf(light)
        make_pdf(dark)
        mod.postprocess(__import__("pathlib").Path(light), "L01-02 · 强化学习基础与贝尔曼方程")
        mod.postprocess(__import__("pathlib").Path(dark), "L01-02 · 强化学习基础与贝尔曼方程", "#0E0E0C")

        # 2 每页都印了三样
        miss = []
        if not disc.strip():
            miss.append("免责文案是空的（空串在 get_text 里恒命中，不能算印了）")
        for tag, p in (("浅底", light), ("深底", dark)):
            doc = pymupdf.open(p)
            try:
                for i, pg in enumerate(doc, 1):
                    t = pg.get_text()
                    for what, val in (("软件名", name), ("地址", urlt), ("免责", disc)):
                        if val not in t:
                            miss.append("%s p%d 缺%s" % (tag, i, what))
            finally:
                doc.close()
        note(not miss, "每页都印出软件名 / 地址 / 免责", "；".join(miss[:4]))
        red += 0 if not miss else 1

        # 3 地址可点
        bad = []
        for tag, p in (("浅底", light), ("深底", dark)):
            doc = pymupdf.open(p)
            try:
                for i, pg in enumerate(doc, 1):
                    if url not in [str(l.get("uri") or "") for l in pg.get_links()]:
                        bad.append("%s p%d" % (tag, i))
            finally:
                doc.close()
        note(not bad, "地址可点（每页 uri == PROJECT_URL）", "没链到：" + "、".join(bad[:4]))
        red += 0 if not bad else 1

        # 4/5 对比度
        for tag, p in (("浅底", light), ("深底", dark)):
            cs = foot_contrast(p)
            worst = min(cs) if cs else 0.0
            note(worst >= 0.15, "%s页脚看得见（亮度跨度 %.2f ≥ 0.15）" % (tag, worst),
                 "跨度 %.3f" % worst)
            red += 0 if worst >= 0.15 else 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # 6 默认就印
    src = open(os.path.join(PRINT_DIR, "html2pdf.py"), encoding="utf-8").read()
    ok = ("if not a.no_post:" in src) and ("postprocess(out, a.footer, a.bg)" in src)
    note(ok, "默认就印（main 不带 --footer/--bg 也走 postprocess）",
         "没找到 `if not a.no_post:` + postprocess 调用")
    red += 0 if ok else 1
    return red


def selftest() -> int:
    """造坏 4 例：每例都要求对应项变红；最后复原要全绿。"""
    print("===== R105 成品页脚 · 造坏自测 =====")
    real_mod, real_brand = load(PRINT_DIR)
    n = run_checks(real_mod, real_brand)
    if n:
        print("  红  原实现本身有红 %d 条，先修实现再自测" % n)
        return 1
    print("  ── 原始实现全绿，开始造坏 ──")

    cases = [
        {"名": "免责文案清空", "文件": "_brand.py",
         "改": lambda s: s.replace('DISCLAIMER = "', 'DISCLAIMER = "', 1) and s.replace(
             'DISCLAIMER = "本内容由 AI 生成，仅供参考；重要信息请自行核实"',
             'DISCLAIMER = ""', 1),
         "期望": "每页都印出"},
        {"名": "地址不是 https", "文件": "_brand.py",
         "改": lambda s: s.replace('PROJECT_URL = "https://', 'PROJECT_URL = "http://', 1),
         "期望": "品牌常量齐"},
        {"名": "删掉 insert_link", "文件": "html2pdf.py",
         "改": lambda s: s.replace("page.insert_link({", "_ = ({", 1),
         "期望": "地址可点"},
        {"名": "深底整块写成底色", "文件": "html2pdf.py",
         "改": lambda s: s.replace(DARK_BLOCK,
                                   ("            c_label, c_page = (0.055, 0.055, 0.047), (0.055, 0.055, 0.047)\n"
                                    "            c_brand, c_link = (0.055, 0.055, 0.047), (0.055, 0.055, 0.047)\n"
                                    "            c_note, c_rule = (0.055, 0.055, 0.047), (0.055, 0.055, 0.047)")),
         "期望": "深底页脚看得见"},
    ]
    bad = 0
    for c in cases:
        label, fname, want = c["名"], c["文件"], c["期望"]
        tmp = tempfile.mkdtemp(prefix="pluma-brand-bad-")
        try:
            for f in ("html2pdf.py", "_brand.py"):
                shutil.copy2(os.path.join(PRINT_DIR, f), os.path.join(tmp, f))
            p = os.path.join(tmp, fname)
            s = open(p, encoding="utf-8").read()
            new = c["改"](s)
            if new == s:
                print("  红  造坏「%s」没改到（锚点不在文件里）" % label)
                bad += 1
                continue
            open(p, "w", encoding="utf-8").write(new)
            RESULT.clear()
            print("  ── 造坏：%s ──" % label)
            mod, brand = load(tmp)
            run_checks(mod, brand)
            hit = [r for r in RESULT if (not r[0]) and want in r[1]]
            if hit:
                print("  过  造坏「%s」→「%s」变红" % (label, hit[0][1]))
            else:
                print("  红  造坏「%s」后「%s」没红（假绿）" % (label, want))
                bad += 1
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    print("===== 自测结论：%s =====" % ("全过（%d 例造坏都抓到）" % len(cases) if bad == 0
                                     else "%d 例没抓到" % bad))
    return 0 if bad == 0 else 1


def main() -> int:
    if "-SelfTest" in sys.argv or "--selftest" in sys.argv:
        return selftest()
    print("===== R105 成品 PDF 页脚三要素 =====")
    try:
        import pymupdf  # noqa: F401
    except Exception as e:  # noqa: BLE001
        print("  [黄] 没装 pymupdf（%s），没查" % e.__class__.__name__)
        return 2
    if not os.path.isfile(os.path.join(PRINT_DIR, "html2pdf.py")):
        print("  [黄] 找不到 tools\\print\\html2pdf.py，没查")
        return 2
    mod, brand = load(PRINT_DIR)
    red = run_checks(mod, brand)
    if red:
        print("\n结论：%d 条红" % red)
        return 1
    print("\n结论：六项全绿")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
