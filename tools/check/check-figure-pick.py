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
    spec = importlib.util.spec_from_file_location(
        "pluma_draft_uut", os.path.join(root, "engine", "_draft.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def make_png(path, w, h, color):
    from PIL import Image
    Image.new("RGB", (w, h), color).save(path)


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
            print("  [%s] 先到先得 → 判据 1 %s" % ("过" if bad1 else "红", "变红" if bad1 else "没变红（假绿）"))
            print("  [%s] 先到先得 → 判据 2 %s" % ("过" if bad2 else "红", "变红" if bad2 else "没变红（假绿）"))
            return 0 if (bad1 and bad2) else 1

        for f in fails:
            print("[红] " + f)
        print("结论：%d 项%s" % (3, " 全绿" if not fails else " 有红 %d" % len(fails)))
        return 0 if not fails else 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
