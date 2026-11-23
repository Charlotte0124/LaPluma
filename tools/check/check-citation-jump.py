# -*- coding: utf-8 -*-
r"""check-citation-jump.py — 「课件 p.N」点了要能打开原件那一页（2026-11-23 用户优化项 F）

为什么有这条：用户原话「讲义里的『课件 p.N』现在只是文字，点了不能跳到原件那一页」。
讲义是按课件生成的，正文 / 图注里写着（课件 p.27）这类出处，核对时应该一点就跳过去。
这件事特别容易「看着接上了」：文字层是绝对定位 + scaleX 的 span（2026-11-22 自己接管拖选
就是因为它），所以「点中的是哪几个字」「这一次是单击还是拖选」「这份讲义对应哪份原件」
任何一环写错，表现出来只是「点了没反应」，或者更糟——正选着一段字要去记笔记，手一松跳到别处。

判据（6 项）：
  1 服务端 /api/orig-of：只读接口在，原件对应关系复用 engine\_draft.source_of（不另写一套）
  2 只有单击才跳：pointermove 超过 3px 记 moved，pointerup 里 !moved 才判出处；
    pointercancel（手势被打断 / 触控滚走）不跳；拖选松手照旧保留选区
  3 两种写法都认：课件 p.N / 课件第 N 页；拿到原件后用 openReader(rel, name, code, page) 翻到该页
  4 提示只加类名与 title：markCites 不碰 span 的 left / top / 字号 / 文字
    （W3 的文字层对位判据量的是这些几何量，改了就偏）
  5 行为：真造一份「原件 + 讲次数据」，调 orig_of 验 讲义→原件 / 长讲号优先 /
    原件本身（就地翻页）/ 合订本拒绝
  6 既有选择器没被拆：官方 TextLayer、setBaseAndExtent 拖选、右键菜单只在 contextmenu、
    #pdftext span 的定位样式原样

用法：
    python tools\check\check-citation-jump.py            # 判本仓
    python tools\check\check-citation-jump.py --selftest # 临时副本逐项造坏，先证明会红

退出码：0 = 全绿；1 = 有红；2 = 有项没验（例如本机没有 pymupdf）
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
IDX = os.path.join("ui", "index.html")
SRV = os.path.join("ui", "server.py")


def read(root, rel):
    with open(os.path.join(root, rel), encoding="utf-8") as f:
        return f.read()


def block(text, start, end):
    i = text.find(start)
    if i < 0:
        return ""
    j = text.find(end, i + len(start))
    return text[i:] if j < 0 else text[i:j]


# ---------- 5 行为：真造数据调 orig_of ----------
T01 = '''# 造样本：T01 是导入占位，stub-from 指向 Lecture A
LESSON = {
    "zh": "测试讲",
    "meta": [["源课件", "00_原件/Lecture A.pdf"]],
    "stub-from: 00_原件/Lecture A.pdf",
}
'''
T012 = '''# 造样本：T01-2 走 meta 的「源课件」行（source_of 的第二条路）
LESSON = {
    "zh": "更细的一讲",
    "meta": [["源课件", "00_原件/Lecture B.pdf"]],
}
'''


def behavior(root):
    """真造一份数据：课程 TDEMO 有原件与讲次数据，调 orig_of 看它认不认得。

    为什么必须真跑：静态判据只能证明「代码里出现了 source_of 这个词」。
    真正会坏的是映射本身——长讲号被短讲号抢走（T01-2 认成 T01）、合订本被硬塞一份原件、
    原件目录空了还回 ok:true。这些只有真调一次才看得见。
    """
    base = os.path.join(root, "_trash")
    os.makedirs(base, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="pluma-cite-", dir=base)
    data = os.path.join(tmp, "data")
    try:
        orig = os.path.join(data, "TDEMO", "00_原件")
        for d in (orig, os.path.join(data, "TDEMO", "_lessons"),
                  os.path.join(data, "TDEMO", "01_讲义")):
            os.makedirs(d, exist_ok=True)
        pages_known = False
        try:
            import pymupdf
            a = pymupdf.open()
            for _ in range(3):
                a.new_page(width=200, height=200)
            a.save(os.path.join(orig, "Lecture A.pdf"))
            b = pymupdf.open()
            b.new_page(width=200, height=200)
            b.new_page(width=200, height=200)
            b.save(os.path.join(orig, "Lecture B.pdf"))
            a.close()
            b.close()
            pages_known = True
        except Exception:  # noqa: BLE001
            # 没有 pymupdf 也要能查映射：造两个空 PDF，页数那一条标记为「没验」
            for nm in ("Lecture A.pdf", "Lecture B.pdf"):
                with open(os.path.join(orig, nm), "wb") as f:
                    f.write(b"%PDF-1.4\n%selftest\n")
        with open(os.path.join(data, "TDEMO", "_lessons", "T01.py"), "w", encoding="utf-8") as f:
            f.write(T01)
        with open(os.path.join(data, "TDEMO", "_lessons", "T01-2.py"), "w", encoding="utf-8") as f:
            f.write(T012)
        code = r'''
import json, os, sys
root, data = sys.argv[1], sys.argv[2]
os.environ["PLUMA_HOME"] = os.path.join(data, "home")
sys.path.insert(0, root)
import paths
paths.DATA_ROOT = data
import importlib.util as iu
spec = iu.spec_from_file_location("pluma_of_uut", os.path.join(root, "ui", "server.py"))
m = iu.module_from_spec(spec)
spec.loader.exec_module(m)
out = {
    "hit": m.orig_of("TDEMO", "TDEMO/01_讲义/T01_测试讲_讲义.pdf"),
    "longest": m.orig_of("TDEMO", "TDEMO/01_讲义/T01-2_更细的一讲_讲义.pdf"),
    "same": m.orig_of("TDEMO", "TDEMO/00_原件/Lecture A.pdf"),
    "book": m.orig_of("TDEMO", "TDEMO/01_讲义/TDEMO_合订本_讲义.pdf"),
    "empty": m.orig_of("TDEMO", ""),
}
print(json.dumps(out, ensure_ascii=False))
'''
        # 2026-11-23 自测时踩到：判据要证明「改坏会红」，而 __pycache__ 的 pyc 头里
        # mtime 只到秒、大小又没变（">" 换成 "<" 一个字节都不差）——同一秒内改完再跑，
        # 子进程会读到上一次的 pyc，坏代码被当成好代码（假绿）。所以这里既不许写 pyc，
        # 也先把这份 server 的旧 pyc 清掉，强制按源码重编译。
        pc = os.path.join(root, "ui", "__pycache__")
        if os.path.isdir(pc):
            for fn in os.listdir(pc):
                if fn.startswith("server.") and fn.endswith((".pyc", ".pyo")):
                    try:
                        os.unlink(os.path.join(pc, fn))
                    except OSError:
                        pass
        env = dict(os.environ, PLUMA_HOME=os.path.join(tmp, "home"),
                   PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1")
        r = subprocess.run([sys.executable, "-X", "utf8", "-c", code, root, data],
                           cwd=root, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=120, env=env)
        if r.returncode != 0:
            return None, "orig_of 没跑通：" + (r.stderr or r.stdout).strip()[-400:]
        lines = [x for x in (r.stdout or "").splitlines() if x.strip()]
        if not lines:
            return None, "子进程没有输出"
        got = json.loads(lines[-1])
        hit, lon = got.get("hit") or {}, got.get("longest") or {}
        same, book, empty = got.get("same") or {}, got.get("book") or {}, got.get("empty") or {}
        bad = []
        if not hit.get("ok") or hit.get("no") != "T01" \
                or hit.get("rel") != "TDEMO/00_原件/Lecture A.pdf":
            bad.append("讲义 T01 → 没对到 Lecture A：%r" % (hit,))
        elif pages_known and hit.get("pages") != 3:
            bad.append("页数没读出来：%r（应为 3）" % (hit.get("pages"),))
        if not lon.get("ok") or lon.get("no") != "T01-2":
            bad.append("长讲号没优先（T01-2 被认成别的讲）：%r" % (lon,))
        if not same.get("ok") or not same.get("same"):
            bad.append("在看原件本身时没给 same:true（会重复打开）：%r" % (same,))
        if book.get("ok") is not False or "认不出" not in str(book.get("error", "")):
            bad.append("合订本没被拒绝：%r" % (book,))
        if empty.get("ok") is not False:
            bad.append("缺 doc 参数没被拒绝：%r" % (empty,))
        if bad:
            return False, " · ".join(bad)
        return True, "T01→Lecture A（3 页）；T01-2 认到长讲号；原件本身 same；合订本 / 空参数都拒"
    except Exception as e:  # noqa: BLE001
        return None, "行为检查没跑完：%r" % (e,)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------- 1~4、6 静态 ----------
def static_rows(root):
    idx = read(root, IDX)
    srv = read(root, SRV)
    rows = []

    def add(no, name, ok, detail):
        rows.append((no, name, ok, detail))

    # 1 服务端接口 + 复用 source_of
    # 2026-11-23：签名多了可选的第三个参数（阅读侧栏「会话」要按讲号找原件），
    # 所以锚点只钉到参数表开头——判的仍是「这个函数在、且复用 source_of」，不是签名一字不差。
    of = block(srv, "def orig_of(course: str, doc: str", "def rel_out(")
    add(1, "服务端 /api/orig-of", (
        '/api/orig-of' in srv
        and 'orig_of(q.get("code", [DEFAULT_COURSE])[0]' in srv
        and 'q.get("doc", [""])[0]' in srv
        and '_engine("_draft").source_of(' in of          # 原件怎么找只有一处实现
        and 'ORIG_DIR' in of
        and '"ok": False' in of                            # 找不到要说得出口
    ), "GET /api/orig-of 只读：复用 engine/_draft.source_of 认原件，认不出回 ok:false + 原因")

    # 6 既有选择器（先取这一段，2 也用它）
    selreg = block(idx, "let selDrag = null;",
                   "$('#readerBox').addEventListener('pointerup', endSelect);")
    add(6, "既有选择器没被拆", (
        "new lib.TextLayer(" in idx and "setProperty('--scale-factor'" in idx
        and "setBaseAndExtent" in selreg
        and "inTextLayer(r.startContainer)" in selreg
        and "$('#readerBox').addEventListener('pointercancel', endSelect)" in idx
        and "document.addEventListener('contextmenu'" in idx
        and idx.count("openTextMenu(") == 2                # 菜单只在 contextmenu 里打开
        and "t.closest('#pdftext') || t.closest('.note-menu')" in idx
        and "#pdftext span{position:absolute;white-space:pre;transform-origin:0 0;cursor:text;color:transparent}" in idx
    ), "官方 TextLayer + 拖选 setBaseAndExtent + 右键菜单 + 点空白清选区 + span 定位样式 都在")

    # 2 只有单击才跳
    end = block(idx, "const endSelect = e => {",
                "$('#readerBox').addEventListener('pointerup', endSelect);")
    mov = block(idx, "if(!selDrag.moved){", "const r = caretAt(e.clientX, e.clientY);")
    add(2, "只有单击才跳", (
        "!g.moved" in end and "e.type === 'pointerup'" in end and "e.button === 0" in end
        and "citeAtPoint(e.clientX" in end and "jumpToCite(" in end
        and "selDrag.moved = true" in mov and "> 9" in mov     # >3px 就算拖选
        and "removeAllRanges" not in end                        # 松手不清选区（既有行为）
    ), "pointermove >3px 记 moved；pointerup 里 !moved 才判出处；pointercancel 不跳；拖选照旧保留选区")

    # 3 两种写法 + 调接口 + 翻页
    add(3, "认两种写法并翻页", (
        r"const CITE_RE = /课件\s*p\.\s*(\d+)|课件第\s*(\d+)\s*页/" in idx
        and "/api/orig-of?code=" in idx
        and "await openReader(j.rel, j.name, j.course || RD.code, go)" in idx
        and "j.pages" in idx and "原件只有 " in idx              # 页码超了要说出口，不静默
        and "RD.page = Math.min(go, max)" in idx                 # 本来在看原件：就地翻页
        and "pre.toString()" in idx and "box.textContent" in idx
        and "full.slice(0, off) === head" in idx        # 偏移能用才算，不能就退回这一段
    ), "课件 p.N / 课件第 N 页 都认；按光标字符偏移判「点的是不是这段字」；"
       "拿到原件 openReader(rel, name, code, go)，页码超过原件页数时说一句再翻到最后一页")

    # 4 提示只加类名与 title，不动几何
    mark = block(idx, "function markCites(){", "function citeAtPoint(")
    add(4, "提示不动文字层几何", (
        "classList.add('cite')" in mark and "sp.title" in mark
        and not any(k in mark for k in ("style.left", "style.top", "style.fontSize", "textContent ="))
        and "#pdftext span.cite{cursor:pointer}" in idx
        and "markCites();" in block(idx, "async function renderTextLayer(", "async function renderPdf()")
    ), "markCites 只加 class 与 title；CSS 只给 cursor（悬停才出下划虚线）")
    return rows


def check(root):
    rows = static_rows(root)
    ok_b, detail_b = behavior(root)
    rows.append((5, "行为：讲义→原件", ok_b, detail_b))
    rows.sort(key=lambda r: r[0])
    return rows


def main():
    if "--selftest" in sys.argv:
        return selftest()
    rows = check(ROOT)
    bad = skip = 0
    for no, name, ok, detail in rows:
        tag = "绿" if ok is True else ("未验" if ok is None else "红")
        print("[%s] %d/%d %s —— %s" % (tag, no, len(rows), name, detail))
        if ok is False:
            bad += 1
        elif ok is None:
            skip += 1
    print("结论：查了 %d 项 / 跳过 %d 项 · %s"
          % (len(rows) - skip, skip, ("全绿" if not bad else "红 %d 项" % bad)))
    if bad:
        return 1
    return 2 if skip else 0


def selftest():
    """临时副本逐项造坏：每一项判据都必须变红，证明它真的会失败（假绿比没判据更糟）。"""
    base = os.path.join(ROOT, "_trash")
    os.makedirs(base, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="pluma-cite-st-", dir=base)
    root = os.path.join(tmp, "repo")
    try:
        for rel in (IDX, SRV, "paths.py", "courses.json",
                    os.path.join("engine", "_draft.py"), os.path.join("api", "client.py")):
            src = os.path.join(ROOT, rel)
            dst = os.path.join(root, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            if os.path.isfile(src):
                shutil.copyfile(src, dst)
        orig_idx = read(root, IDX)
        orig_srv = read(root, SRV)

        def reset():
            with open(os.path.join(root, IDX), "w", encoding="utf-8", newline="") as f:
                f.write(orig_idx)
            with open(os.path.join(root, SRV), "w", encoding="utf-8", newline="") as f:
                f.write(orig_srv)

        defects = [
            ("接口被改名", 1, SRV, "/api/orig-of", "/api/orig-x"),
            ("拖选也跳", 2, IDX,
             "if(e.type === 'pointerup' && !g.moved && e.button === 0){",
             "if(e.type === 'pointerup' && e.button === 0){"),
            ("只认 p.N 不再认「第 N 页」", 3, IDX, r"|课件第\s*(\d+)\s*页", ""),
            ("提示改成动几何", 4, IDX, "sp.classList.add('cite');",
             "sp.classList.add('cite'); sp.style.left = '0px';"),
            ("合订本硬塞一份原件", 5, SRV, "and len(no) > len(hit)", "and len(no) < len(hit)"),
            ("span 定位样式被换掉", 6, IDX,
             "#pdftext span{position:absolute;white-space:pre;transform-origin:0 0;cursor:text;color:transparent}",
             "#pdftext span{position:relative;cursor:text;color:transparent}"),
        ]
        all_ok = True
        for label, no, rel, old, new in defects:
            reset()
            text = read(root, rel)
            if text.count(old) != 1:
                print("  [红] %s：造坏锚点出现 %d 次（判据或造坏点过时了）" % (label, text.count(old)))
                all_ok = False
                continue
            with open(os.path.join(root, rel), "w", encoding="utf-8", newline="") as f:
                f.write(text.replace(old, new, 1))
            rows = check(root)
            hit = [r for r in rows if r[0] == no and r[2] is False]
            if hit:
                print("  [过] %s → 判据 %d 变红" % (label, no))
            else:
                print("  [红] %s → 判据 %d 没变红（假绿）" % (label, no))
                all_ok = False
        reset()
        print("自测：%d 项 %s" % (len(defects), "全按预期" if all_ok else "有不符"))
        return 0 if all_ok else 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
