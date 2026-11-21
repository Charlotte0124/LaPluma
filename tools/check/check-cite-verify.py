# -*- coding: utf-8 -*-
r"""check-cite-verify.py — 「课件 p.N」能不能被机器核实（2026-11-23 用户提的优化项 C）

为什么要有它
    用户原话（2026-11-23）：「讲义里每条引文都标「课件 p.N」，三道门的 audit 只检查有没有标，
    标错（页码对不上内容）也判绿」，要的是「让标注可核」。audit_lesson.py 里新增的
    cite_verify() 就是第一步：拿原件那一页的文字与引文所在那一行比用词重合，低于阈值就报
    「疑似标错」并给出重合最高的页。它**只报告不拦**（不进 fails、不改退出码）。

这条判据证明三件事（都用临时目录 + pymupdf 现造的 PDF，不碰用户真实课件）：
  1 标对的不会被报（中文课件、英文课件各一套；另加一条「同义改写不算错」，防止阈值只认照抄）
  2 标错的必须报出来，而且建议的页码是对的（把 p.2 的内容标成 p.6，得指出 p.2）
  3 查不了的必须说「没查」，不能冒充查过：没有原件 / 引文页码超出原件页数 / 引文是中文而
    那一页是纯英文（术语没留英文，词面对不上）

用法
    python tools\check\check-cite-verify.py            # 8 条判据，全绿退出 0
    python tools\check\check-cite-verify.py --selftest # 再把「核验弄坏」两次，证明它会红

--selftest 两个方向（不红 = 假绿，退出 1）：
    · 阈值放到 -1 → 等于回到旧口径「只看有没有标」→「标错」那两条必须不再报
    · 把词袋弄空 → 等于没在比对 →「标对」那几条必须判不出来（证明绿不是白给的）

退出码：0 = 全绿；1 = 有红；2 = 没查（缺 pymupdf / 导入失败）
"""
from __future__ import annotations

import os
import sys
import tempfile
import shutil

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 现造的课件页（第 1 页是提纲、第 6 页是参考文献：标错样本就把内容指向第 6 页）
EN_PAGES = [
    "BIOLOGY 101 Lecture outline and schedule",
    "Photosynthesis converts light energy into chemical energy stored in glucose molecules",
    "Mitochondria generate ATP through cellular respiration inside the cell",
    "DNA replication copies the double helix before the cell divides",
    "Osmosis moves water across a semipermeable membrane down its concentration gradient",
    "Reference list and further reading for this lecture",
]
ZH_PAGES = [
    "第一讲 课程提纲与日程安排",
    "光合作用把光能转成化学能，储存在葡萄糖分子里",
    "线粒体通过细胞呼吸产生 ATP，为细胞供能",
    "DNA 复制在细胞分裂前把双螺旋复制一份",
    "渗透作用是水分子穿过半透膜向低浓度一侧移动",
    "参考文献与延伸阅读清单",
]


def make_pdf(path: str, pages: list) -> None:
    """用 pymupdf 造一份有文字层的真 PDF（中文页要用内建 CJK 字体，否则写不进去）。"""
    import pymupdf
    doc = pymupdf.open()
    for text in pages:
        page = doc.new_page()
        cjk = any("\u4e00" <= ch <= "\u9fff" for ch in text)
        page.insert_textbox(pymupdf.Rect(50, 60, 545, 780), text,
                            fontsize=12, fontname="china-s" if cjk else "helv")
    doc.save(path)
    doc.close()


def write_lesson(course_dir: str, no: str, orig: str) -> None:
    """这一讲的数据文件（source_of() 认「源课件」那一行来找原件）。"""
    les = os.path.join(course_dir, "_lessons")
    os.makedirs(les, exist_ok=True)
    with open(os.path.join(les, no + ".py"), "w", encoding="utf-8") as f:
        f.write('# -*- coding: utf-8 -*-\n'
                'LESSON = {"code": "%s", "no": "%s", "zh": "样例", "en": "", "lang": "zh",\n'
                '          "meta": (("源课件", "%s"),)}\n'
                % (os.path.basename(course_dir), no, orig))


def write_source(course_dir: str, no: str, body: str) -> str:
    """讲义源（只要 h2 小节 + 带「课件 p.N」的正文，cite_verify 就够用了）。"""
    d = os.path.join(course_dir, "06_笔记")
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, no + "_零基础_讲义_源.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write('<!DOCTYPE html>\n<html lang="zh-CN" data-theme="dark" data-reader="大学">\n'
                '<head><meta charset="utf-8"></head><body>\n' + body + "\n</body></html>\n")
    return path


def section(no: str, zh: str, en: str, lines: str) -> str:
    return ('<section class="sec"><h2><span class="no">%s</span>'
            '<span class="zh">%s</span><span class="en">%s</span></h2>\n%s\n</section>'
            % (no, zh, en, lines))


def build_samples(tmp: str) -> None:
    """造两门课：CITEEN（英文课件）/ CITEZH（中文课件），每门各一条标对、一条标错。"""
    en = os.path.join(tmp, "CITEEN")
    os.makedirs(os.path.join(en, "00_原件"), exist_ok=True)
    make_pdf(os.path.join(en, "00_原件", "en.pdf"), EN_PAGES)
    for no in ("E01", "E02", "E03", "E04"):
        write_lesson(en, no, "00_原件/en.pdf")
    quote = ("<blockquote><span class=\"en\">Photosynthesis converts light energy into "
             "chemical energy stored in glucose molecules.</span>"
             "<span class=\"ref\">课件 p.2</span></blockquote>")
    write_source(en, "E01", section("1", "光合作用", "Photosynthesis", quote))
    write_source(en, "E02", section("1", "光合作用", "Photosynthesis",
                                    quote.replace("课件 p.2", "课件 p.6")))
    # 中文引文配纯英文页面、且没留英文术语 → 词面对不上，必须记「没查」而不是「疑似」
    write_source(en, "E03", section("1", "光合作用", "Photosynthesis",
                                    "<p>光合作用把光能转成化学能，储存在葡萄糖分子里（课件 p.2）。</p>"))
    # 页码超出原件页数 → 必须报出来，并说清原件只有几页
    write_source(en, "E04", section("1", "光合作用", "Photosynthesis",
                                    quote.replace("课件 p.2", "课件 p.99")))

    zh = os.path.join(tmp, "CITEZH")
    os.makedirs(os.path.join(zh, "00_原件"), exist_ok=True)
    make_pdf(os.path.join(zh, "00_原件", "zh.pdf"), ZH_PAGES)
    for no in ("Z01", "Z02", "Z03"):
        write_lesson(zh, no, "00_原件/zh.pdf")
    line = "<p>光合作用把光能转成化学能，储存在葡萄糖分子里（课件 p.2）。</p>"
    write_source(zh, "Z01", section("1", "光合作用", "Photosynthesis", line))
    write_source(zh, "Z02", section("1", "光合作用", "Photosynthesis",
                                    line.replace("课件 p.2", "课件 p.6")))
    # 同义改写（不是照抄）也必须算对：阈值不能只认逐字相同，否则真讲义全军覆没
    write_source(zh, "Z03", section("1", "能量工厂", "Powerhouse",
                                    "<p>线粒体是细胞的发电站，靠细胞呼吸把能量做成 ATP（课件 p.3）。</p>"))

    # 没有原件的那门课：必须「没查」，不许因为缺数据就沉默
    noo = os.path.join(tmp, "CITENO")
    os.makedirs(noo, exist_ok=True)
    write_lesson(noo, "N01", "00_原件/none.pdf")
    write_source(noo, "N01", section("1", "光合作用", "Photosynthesis", line))


def main() -> int:
    for s in (sys.stdout, sys.stderr):
        if hasattr(s, "reconfigure"):
            s.reconfigure(encoding="utf-8", errors="replace")
    selftest = "--selftest" in sys.argv
    tmp = tempfile.mkdtemp(prefix="pluma-citeverify-")
    try:
        build_samples(tmp)
        sys.path.insert(0, ROOT)
        import paths
        paths.DATA_ROOT = tmp          # 数据根指到临时目录：绝不碰用户自己的课程
        sys.path.insert(0, os.path.join(ROOT, "engine"))
        sys.path.insert(0, os.path.join(ROOT, "tools", "print"))
        import audit_lesson
        # 「找原件」这一半走 engine\_draft.py（与生成同一条口径）。引擎此刻导入不了时
        # （例如另一条线正在改 _draft.py），只能说「没查」，不能把这 8 条判成绿，也不能
        # 判成红——红会让人以为是判据坏了。没查 ≠ 通过。
        if not getattr(audit_lesson, "_HAVE_DRAFT", True):
            print("没查：engine\\_draft.py 在这个进程里导入失败 —— %s"
                  % (getattr(audit_lesson, "_DRAFT_ERR", ""),))
            print("      核验逻辑本身没跑（源文件/临时 PDF 都已就绪）；等引擎能导入再跑。")
            return 2
        cases = run_cases(audit_lesson, tmp, {})
        if selftest:
            return selftest_report(audit_lesson, tmp, cases)
        bad = [n for n, ok, _ in cases if not ok]
        for name, ok, ev in cases:
            print("  [%s] %s —— %s" % ("绿" if ok else "红", name, ev))
        print("结论：%d/%d 绿 · %d 红" % (len(cases) - len(bad), len(cases), len(bad)))
        return 0 if not bad else 1
    except ImportError as e:            # noqa: BLE001
        print("没查：%r" % (e,))
        return 2
    except Exception as e:              # noqa: BLE001
        print("[红] 跑不起来：%r" % (e,))
        return 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def run_cases(mod, tmp: str, th: dict) -> list:
    """跑 8 条判据，返回 [(名字, 是否绿, 证据)]。th 用来做 --selftest 的「弄坏」实验。"""
    def run(course, no):
        src = os.path.join(tmp, course, "06_笔记", no + "_零基础_讲义_源.html")
        return mod.cite_verify(src, th=th or None)

    def case_ok(course, no, label):
        r = run(course, no)
        ok = bool(r["checked"]) and not r["suspects"] and not r["notes"]
        return ok, "%s：判定 %d 处 · 疑似 %d 处" % (label, r["checked"], len(r["suspects"]))

    def case_wrong(course, no, want_page, want_best):
        r = run(course, no)
        hit = [s for s in r["suspects"] if s["page"] == want_page]
        ok = bool(hit) and any(s["best"] == want_best for s in hit)
        ev = "疑似 %d 处" % len(r["suspects"])
        if hit:
            ev += "（p.%d → 建议 p.%d，重合 %.0f%% / %.0f%%）" % (
                hit[0]["page"], hit[0]["best"], 100 * hit[0]["cover"], 100 * hit[0]["best_cover"])
        return ok, ev

    rows = []
    ok, ev = case_ok("CITEEN", "E01", "英文课件·标对")
    rows.append(("① 英文课件标对不误报", ok, ev))
    ok, ev = case_wrong("CITEEN", "E02", 6, 2)
    rows.append(("② 英文课件标错要报出来", ok, ev))
    ok, ev = case_ok("CITEZH", "Z01", "中文课件·标对")
    rows.append(("③ 中文课件标对不误报", ok, ev))
    ok, ev = case_wrong("CITEZH", "Z02", 6, 2)
    rows.append(("④ 中文课件标错要报出来", ok, ev))
    ok, ev = case_ok("CITEZH", "Z03", "中文同义改写")
    rows.append(("⑤ 同义改写不算错（阈值不只认照抄）", ok, ev))

    r = run("CITEEN", "E03")
    ok = (not r["suspects"]) and r["checked"] == 0 and r["skipped"].get("跨语言且可比词不足", 0) >= 1
    rows.append(("⑥ 中文引文配纯英文页 → 没查（不冒充）", ok,
                 "判定 %d 处 · 没查 %s" % (r["checked"], r["skipped"] or "{}")))
    r = run("CITENO", "N01")
    ok = bool(r["notes"]) and "没查" in " ".join(r["notes"])
    rows.append(("⑦ 找不到原件 → 没查", ok, "；".join(r["notes"]) or "（没说没查）"))
    r = run("CITEEN", "E04")
    ok = bool(r["suspects"]) and any("原件只有" in (s.get("why") or "") for s in r["suspects"])
    rows.append(("⑧ 页码超出原件页数 → 报出来", ok,
                 "；".join(s.get("why") or "" for s in r["suspects"]) or "（没报）"))
    return rows


def selftest_report(mod, tmp: str, cases: list) -> int:
    """--selftest：把核验弄坏两次，证明「标对/标错」这两类判据真的会翻脸。"""
    print("  正常口径：%d/%d 绿" % (sum(1 for _n, ok, _e in cases if ok), len(cases)))
    old = dict(mod.CITE_TH)

    def run_with(**patch):
        mod.CITE_TH.update(patch)
        try:
            return run_cases(mod, tmp, {})
        finally:
            mod.CITE_TH.clear()
            mod.CITE_TH.update(old)

    bad = 0
    # 方向一：阈值 -1 = 回到旧口径「只看有没有标」→ 标错的那两条必须不再报（判据要红）
    rows = run_with(cover_min=-1.0)
    wrong = [n for n, ok, _ in rows if not ok]
    if wrong:
        print("  [过] 阈值 -1（旧口径只看有没有标）→ %d 条判据变红：%s" % (len(wrong), "、".join(wrong)))
    else:
        print("  [红] 阈值 -1 → 一条都没变红：标错样本也判绿，判据是假绿")
        bad += 1
    # 方向二：把词袋弄空（等于没在比对）→ 标对的那几条必须判不出来（判据要红）。
    # 这一步防的是另一种假绿：判据只写了「跑通了」却没真的依赖比对结果。
    old_tokens = mod._tokens
    try:
        mod._tokens = lambda _t: set()
        rows = run_cases(mod, tmp, {})
    finally:
        mod._tokens = old_tokens
    wrong = [n for n, ok, _ in rows if not ok]
    if wrong:
        print("  [过] 词袋置空（等于不比对）→ %d 条判据变红：%s" % (len(wrong), "、".join(wrong)))
    else:
        print("  [红] 词袋置空 → 一条都没变红：标对样本不比对也判绿，判据是假绿")
        bad += 1
    print("结论：--selftest %s" % ("两条都变红（判据可信）" if not bad else "有 %d 项没变红" % bad))
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
