# -*- coding: utf-8 -*-
r"""check-figure-pick.py — 「课件页图按重要性选，而不是先到先得」（2026-11-23 用户定）

为什么有这条：用户看到日志「课件有 48 页带图，超过单讲上限 40 张，后面的图没导出」后问
「不应该是以图片对于讲解的重要性来选择的吗 而不是先到先得名额吧」，并选了「按版面启发式排」。
原来的实现确实是**按页顺序抓前 40 张**，而「这页有图片对象」这个筛子也会放行只挂模板徽标的
纯文字页（实测一份 57 页课件：前 40 页里 10 页是徽标页，第 41–55 页的真图全丢）。

判据（造真 PDF 来量，不是读字符串）：
  1 徽标页不占名额：50 页里只有 12–50 有内容图、1–11 只挂模板徽标 → 导出的必须正好是 12–50
  2 名额不够按分排：45 页都有内容图，其中 5 页是「参考/复习」页 → 导出 40 张，那 5 页被丢
  3 手写指定优先：FIG_PAGES 点名必须进、FIG_SKIP 点名必须不进

用法：
    python tools\check\check-figure-pick.py            # 判本仓
    python tools\check\check-figure-pick.py --selftest # 把「先到先得」装回去，证明会红

退出码：0 = 全绿 · 1 = 有红
"""
from __future__ import annotations

import importlib.util
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
W, H = 420.0, 595.0


def load_draft(root):
    sys.path.insert(0, root)
    sys.path.insert(0, os.path.join(root, "engine"))
    spec = importlib.util.spec_from_file_location(
        "pluma_draft_uut", os.path.join(root, "engine", "_draft.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_build(root):
    """加载 engine/_build_讲义.py（补图选页那套逻辑在里面）。"""
    sys.path.insert(0, root)
    sys.path.insert(0, os.path.join(root, "engine"))
    spec = importlib.util.spec_from_file_location(
        "pluma_build_uut", os.path.join(root, "engine", "_build_讲义.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def build_case5(tmp):
    """造「补图选页」的数据：5 页课件，每页一句不同的中文，讲次只有两个内容节、都没图。

    2026-11-23：以前补图是按页序弹一张；现在按「节内容 ↔ 该页文字」的相似度选页。
    这条判的是：讲免疫的节要配到免疫那一页，而不是第 1 页。
    """
    import pymupdf
    course = os.path.join(tmp, "CASE")
    os.makedirs(os.path.join(course, "00_原件"), exist_ok=True)
    texts = ["阿尔法测试页", "叶绿素与光合作用", "线粒体与能量代谢", "DNA复制过程", "免疫系统与抗体"]
    doc = pymupdf.open()
    for t in texts:
        page = doc.new_page(width=W, height=H)
        page.insert_text((60, 120), t, fontsize=20, fontname="china-s")   # 内置简体，造中文文字层
    pdf = os.path.join(course, "00_原件", "Test Deck.pdf")
    doc.save(pdf)
    doc.close()
    os.makedirs(os.path.join(course, "_lessons"), exist_ok=True)
    with open(os.path.join(course, "_lessons", "X03.py"), "w", encoding="utf-8") as f:
        f.write('LESSON = {"no": "X03"}\n# stub-from: 00_原件/Test Deck.pdf\n')
    return pdf


def make_png(path, w, h, color):
    from PIL import Image
    Image.new("RGB", (w, h), color).save(path)


def build_crop_pdf(path):
    """造「图区裁切」用的样本：3 页图占 60%（应裁）、3 页图占 92%（裁了没意义，应整页）。

    2026-11-23 用户要提高「信息量」：图页上最大的图只占 8.7%–41%，整页截图大半是页面正文。
    这条判的是导出到底裁没裁、该整页的有没有整页。
    """
    import pymupdf
    tmp = tempfile.mkdtemp(prefix="figcrop-")
    try:
        logo = os.path.join(tmp, "logo.png")
        make_png(logo, 40, 20, (200, 200, 200))
        doc = pymupdf.open()
        sq = os.path.join(tmp, "sq.png")
        make_png(sq, 600, 600, (40, 90, 160))            # 正方形：放进 300×300 的框刚好铺满
        full = os.path.join(tmp, "full.png")
        make_png(full, 840, 1190, (70, 120, 190))        # 整页比例：铺满整页 → 不该裁
        for i in range(1, 7):
            page = doc.new_page(width=W, height=H)
            page.insert_image(pymupdf.Rect(20, 10, 50, 24), filename=logo)
            if i <= 3:
                page.insert_image(pymupdf.Rect(60, 120, 360, 420), filename=sq)
            else:
                page.insert_image(pymupdf.Rect(0, 0, W, H), filename=full)
            page.insert_text((60, 90), "crop case p%d" % i, fontsize=12)
        doc.save(path)
        doc.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def build_pdf(path, spec, big_pages, heads=None):
    """spec 里每页都有同一张模板徽标；big_pages 里的页再盖一张大图。

    heads: {页号: 首行文字} —— 用来造「参考/复习」这类低分页。
    """
    import pymupdf
    tmp = tempfile.mkdtemp(prefix="figsrc-")
    try:
        logo = os.path.join(tmp, "logo.png")
        make_png(logo, 40, 20, (200, 200, 200))          # 40px < FIG_MIN_PX，面积 ~0.2% < 1%
        doc = pymupdf.open()
        for i in range(1, spec + 1):
            page = doc.new_page(width=W, height=H)
            page.insert_image(pymupdf.Rect(20, 10, 50, 24), filename=logo)
            if i in big_pages:
                fig = os.path.join(tmp, "fig%02d.png" % i)
                make_png(fig, 900, 600, (30 + i * 3 % 200, 90, 140))   # 每页不同 → 不是重复图
                page.insert_image(pymupdf.Rect(60, 120, 360, 420), filename=fig)
            head = (heads or {}).get(i, "内容页 p%d" % i)
            page.insert_text((60, 90), head, fontsize=12)
        doc.save(path)
        doc.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    selftest = "--selftest" in sys.argv
    tmp = tempfile.mkdtemp(prefix="pluma-figpick-")
    try:
        mod = load_draft(ROOT)
        import paths
        paths.DATA_ROOT = tmp
        os.makedirs(os.path.join(tmp, "CASE"), exist_ok=True)
        case1 = os.path.join(tmp, "case1.pdf")
        case2 = os.path.join(tmp, "case2.pdf")
        big1 = set(range(12, 51))                     # 12..50 有内容图（39 页）
        build_pdf(case1, 50, big1)
        low = {3: "参考答案 References", 7: "参考答案 References", 11: "复习 Revision",
               15: "参考答案 References", 19: "复习 Revision"}
        build_pdf(case2, 45, set(range(1, 46)), heads=low)

        logs = []

        def emit(s):
            logs.append(s)

        def run_case(pdf, **kw):
            logs.clear()
            out = mod.extract_figures(pdf, "CASE", "X01", emit=emit, **kw)
            return sorted(pg for _rel, pg in out), list(logs)

        fails = []

        got, lg = run_case(case1)
        if set(got) == big1:
            pass
        else:
            fails.append("徽标页占了名额：导出 %d 页，含徽标页 %r、缺内容图页 %r"
                         % (len(got), [p for p in got if p not in big1][:6],
                            sorted(big1 - set(got))[:6]))

        got2, lg2 = run_case(case2)
        dropped = sorted(set(low) - set(got2))
        if len(got2) != 40:
            fails.append("名额不足时没按 40 张封顶：导出 %d 页" % len(got2))
        elif set(dropped) != set(low):
            fails.append("被丢的不是「参考/复习」那几页：dropped=%r，期望 %r"
                         % (dropped, sorted(low)))
        elif not any("真图没进讲义" in s for s in lg2):
            fails.append("丢了图却没说：日志里没有「名额不够」那行")

        # —— 4 图区裁切：该裁的裁、接近整页的不裁 ——
        case4 = os.path.join(tmp, "case4.pdf")
        build_crop_pdf(case4)
        out4 = mod.extract_figures(case4, "CASE", "X02", emit=emit)
        gen4 = os.path.join(tmp, "CASE", "06_笔记", "assets", "gen", "X02")
        from PIL import Image
        full_w = None
        try:
            import pymupdf
            d4 = pymupdf.open(case4)
            full_w = d4[0].get_pixmap(dpi=96).width
            d4.close()
            dims = {int(os.path.splitext(name)[0][1:]): Image.open(os.path.join(gen4, name)).size
                    for _rel, pg in out4 for name in [os.path.basename(_rel)]}
        except Exception as e:  # noqa: BLE001
            dims, full_w = {}, None
            fails.append("裁切用例没量成：%r" % (e,))
        if full_w:
            # 比例才是「裁没裁」的判据：裁到图区时宽高比≈1（300×300 的框），整页是 420×595≈0.71
            cropped = {p: wh for p, wh in dims.items() if p <= 3}
            kept = {p: wh for p, wh in dims.items() if p >= 4}
            asp = lambda wh: round(wh[0] / wh[1], 3) if wh and wh[1] else 0
            if len(cropped) != 3 or len(kept) != 3:
                fails.append("裁切用例张数不对：裁过的 %r / 没裁的 %r" % (sorted(cropped), sorted(kept)))
            elif any(not (0.85 <= asp(wh) <= 1.10) for wh in cropped.values()):
                fails.append("图占 60%% 的页没裁到图区：宽高比 %r（图区应≈0.98，整页≈0.71）"
                             % ({p: asp(wh) for p, wh in cropped.items()},))
            elif any(abs(asp(wh) - 0.706) > 0.03 for wh in kept.values()):
                fails.append("图占 92%% 的页不该裁，但宽高比 %r"
                             % ({p: asp(wh) for p, wh in kept.items()},))

        # —— 5 补图按节内容选页，不按页序 ——
        build_case5(tmp)
        bmod = load_build(ROOT)
        bmod.COURSE = "CASE"
        avail5 = [("gen/X03/p%03d.png" % i, i) for i in range(1, 6)]
        # figs_total 决定补图预算（≤ 总页数 1/3）：写 15 → 预算 5 张，够补两个节
        lesson5 = {"no": "X03", "figs_total": 15, "sections": [
            {"no": "0", "zh": "导读", "body": [["p", "本讲导读"]]},
            {"no": "1", "zh": "免疫系统", "body": [["p", "抗体与免疫应答"] ]},
            {"no": "2", "zh": "光合作用", "body": [["p", "叶绿素 chlorophyll"]]},
        ]}
        import re as _re
        def fill_pages():
            les = {"no": "X03", "figs_total": 15,
                   "sections": [dict(s, body=[list(x) for x in s["body"]]) for s in lesson5["sections"]]}
            bmod.ensure_figures(les, emit=emit, avail=avail5)
            out = []
            for s in les["sections"]:
                for b in s["body"]:
                    if b and b[0] == "fig":
                        m = _re.search(r"p0*(\d+)", b[1])
                        out.append(int(m.group(1)) if m else 0)
            return out
        pages5 = fill_pages()
        if pages5[:2] != [5, 2]:
            fails.append("补图没按节内容选页：免疫节→%r、光合节→%r（应 5、2）"
                         % (pages5[0] if pages5 else None, pages5[1] if len(pages5) > 1 else None))

        got3, lg3 = run_case(case1, fig_pages=(5,), fig_skip=(12,))
        if 5 not in got3:
            fails.append("FIG_PAGES=(5,) 没生效：第 5 页没导出")
        elif 12 in got3:
            fails.append("FIG_SKIP=(12,) 没生效：第 12 页还是导出了")
        elif len(got3) != len(big1):
            fails.append("手写指定后张数不对：%d（应为 %d）" % (len(got3), len(big1)))

        if selftest:
            # 把「先到先得」装回去：所有页都算真图、分数一律为 0（同分 → 按页序），
            # 这时判据必须变红；不红说明判据是假绿。
            old = (mod.FIG_MIN_AREA, mod.FIG_MIN_PX, mod.FIG_DUP_MAX, mod._fig_score)
            try:
                mod.FIG_MIN_AREA, mod.FIG_MIN_PX, mod.FIG_DUP_MAX = 0.0, 0, 10 ** 9
                mod._fig_score = lambda c, r, b, h: 0.0
                g1, _ = run_case(case1)
                g2, _ = run_case(case2)
            finally:
                mod.FIG_MIN_AREA, mod.FIG_MIN_PX, mod.FIG_DUP_MAX, mod._fig_score = old
            bad1 = set(g1) != big1
            bad2 = sorted(set(low) - set(g2)) != sorted(low)
            # 第 4 项：把裁切关掉，必须变红
            mod.FIG_CROP = False
            try:
                out4b = mod.extract_figures(case4, "CASE", "X03", emit=emit)
                gen4b = os.path.join(tmp, "CASE", "06_笔记", "assets", "gen", "X03")
                dims4b = {}
                from PIL import Image as _Im
                for _rel, pg in out4b:
                    dims4b[pg] = _Im.open(os.path.join(gen4b, os.path.basename(_rel))).size
                bad4 = any(abs(round(wh[0] / wh[1], 3) - 0.706) <= 0.03
                           for p, wh in dims4b.items() if p <= 3 and wh[1])
            finally:
                mod.FIG_CROP = True
            print("  [%s] 先到先得 → 判据 1 %s" % ("过" if bad1 else "红", "变红" if bad1 else "没变红（假绿）"))
            print("  [%s] 先到先得 → 判据 2 %s" % ("过" if bad2 else "红", "变红" if bad2 else "没变红（假绿）"))
            # 第 5 项：把「按内容选页」关掉（退回页序），免疫节应该配到第 1 页 → 判据必须红
            old_pick = bmod._pick_page
            try:
                bmod._pick_page = lambda *a, **k: None
                pages5b = fill_pages()
            finally:
                bmod._pick_page = old_pick
            bad5 = pages5b[:2] != [5, 2]
            print("  [%s] 关掉裁切 → 判据 4 %s" % ("过" if bad4 else "红", "变红" if bad4 else "没变红（假绿）"))
            print("  [%s] 退回页序 → 判据 5 %s（免疫节配到第 %r 页）"
                  % ("过" if bad5 else "红", "变红" if bad5 else "没变红（假绿）",
                     pages5b[0] if pages5b else None))
            return 0 if (bad1 and bad2 and bad4 and bad5) else 1

        for f in fails:
            print("[红] " + f)
        print("结论：%d 项%s" % (5, " 全绿" if not fails else " 有红 %d" % len(fails)))
        return 0 if not fails else 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
