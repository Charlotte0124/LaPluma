# -*- coding: utf-8 -*-
r"""check-reading-tools.py — 阅读页六件事的判据（2026-11-22）

为什么有这条：用户按六条实测提了「标题条拖不动 / 全屏退出缩不回去 / 原件放错课程
搬不走 / 右键翻译后没法记账 / 笔记只能挤在侧栏 / 译文翻完就丢」。界面改动很容易
「改完看着对了」但实际没接上，所以这里把每条的可执行判据钉住：

  1 标题条 mousedown 调 _WinApi.drag_window（自己跑拖动循环：GetCursorPos + GetAsyncKeyState，
     不再用 JS pointermove，也不用 WM_NCLBUTTONDOWN——实测对无边框 WinForms 窗口无效）
  2 退出全屏 restore_bounds 带 SWP_FRAMECHANGED，并在 260ms 后再补一次
  3 文件列表原件行有「移动」，走 /api/move-originals，搬完重取课程与讲次
  4 译文有「记成笔记」，以【译文 p.N】进 #nDraft 并切笔记页签；菜单只由右键打开
  5 记笔记有独立整页（左原文引用 / 右输入框），#nDraft 仍保留
  6 翻译历史存 ~/.pluma/translate-history.json，最多 5 条；页签顶部可回填
  7 翻译是上下两个框 + 中间 ↑↓（上面输入、下面出译文；没译文时是占位不是空框）
  8 正常记笔记（没有引用）时不出那个灰框：灰框只给「引用原文/译文」用

用法：
    python tools\check\check-reading-tools.py            # 判本仓
    python tools\check\check-reading-tools.py --selftest # 临时副本逐个造坏，先证明会红

退出码：0 = 8/8 · 1 = 有红
"""
from __future__ import annotations

import json
import os
import re
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


def behavior_history(root):
    """真跑一下历史函数：7 条 → 只留 5 条，原文截 120、译文截 400，文件落在本机。"""
    base = os.path.join(root, "_trash")
    os.makedirs(base, exist_ok=True)
    home = tempfile.mkdtemp(prefix="pluma-hist-", dir=base)
    code = r"""
import importlib.util, json, os, sys
root, home = sys.argv[1], sys.argv[2]
os.environ["PLUMA_HOME"] = home
sys.path.insert(0, root)
spec = importlib.util.spec_from_file_location("pluma_server_uut", os.path.join(root, "ui", "server.py"))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
for i in range(7):
    m.push_translate_history("源" * 200, "译" * 500, "zh", i + 1)
items = m.load_translate_history()
print(json.dumps({"n": len(items), "src": len(items[0]["src"]),
                  "dst": len(items[0]["dst"]), "page": items[0]["page"],
                  "file": os.path.isfile(os.path.join(home, "translate-history.json"))},
                 ensure_ascii=False))
"""
    try:
        r = subprocess.run([sys.executable, "-X", "utf8", "-c", code, root, home],
                           cwd=root, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=90)
        if r.returncode != 0:
            return None, (r.stderr or r.stdout).strip()[-500:]
        lines = [x for x in (r.stdout or "").splitlines() if x.strip()]
        if not lines:
            return None, "子进程没有输出"
        data = json.loads(lines[-1])
        ok = (data.get("n") == 5 and data.get("src") == 120 and data.get("dst") == 400
              and data.get("page") == 7 and data.get("file") is True)
        return ok, json.dumps(data, ensure_ascii=False)
    except Exception as e:  # noqa: BLE001
        return None, repr(e)
    finally:
        shutil.rmtree(home, ignore_errors=True)


def check(root):
    idx = read(root, IDX)
    srv = read(root, SRV)
    rows = []

    def add(no, name, ok, detail):
        rows.append((no, name, bool(ok), detail))

    bar = block(idx, "function initBar()", "function initResize()")
    drag = block(srv, "def drag_window(", "def start_drag(")
    add(1, "标题条拖动", (
        "bar.addEventListener('mousedown'" in bar
        and "a.drag_window()" in bar
        and "bar.addEventListener('dblclick'" in bar
        and "toggle_max" in bar
        and "move_by" not in bar
        and "pointerdown" not in bar
        and "def drag_window(" in srv
        and "_find_hwnd()" in drag
        and "GetCursorPos" in drag and "GetAsyncKeyState" in drag and "SetWindowPos" in drag
        # 2026-11-22 实测：无边框 WinForms 窗口不吃 WM_NCLBUTTONDOWN，别再回到那条路
        #（注释里可以提那两次弯路，但代码里不许真的再发这条消息/再调 ReleaseCapture）
        and "0x00A1" not in drag and "u.ReleaseCapture()" not in drag
    ), "mousedown → drag_window（GetCursorPos + GetAsyncKeyState + SetWindowPos）；双击标题条最大化")

    rb = block(srv, "def restore_bounds(self):", "def _win(self):")
    fs = block(idx, "async function setFullscreen(on)", "$('#btnFs').onclick")
    exitfs = block(idx, "function exitReaderFullscreen()", "let SIDE_HIDDEN")
    add(2, "退出全屏尺寸", (
        "flags = 0x0040 | 0x0020" in rb and "for _ in range(2)" in rb
        and "restoreWin" in fs and "setTimeout(restoreWin, 260)" in fs
        and "setFullscreen(false)" in exitfs
    ), "restore_bounds 两次 SetWindowPos + SWP_FRAMECHANGED；260ms 再补一次")

    mv = block(idx, "function askMoveOriginal", "function openDrawer")
    add(3, "原件移动", (
        'data-fmove="' in idx and "function askMoveOriginal" in idx
        and "/api/move-originals" in mv and "await boot()" in mv
        and "data-fmove" in block(idx, "html += origs.length", "html += '<div class=\"dr-files-grp\">原件")
        and "/api/move-originals" in srv
    ), "原件行「移动」→ /api/move-originals，搬完 boot() 重取")

    tr = block(idx, "function transNote(text, page)", "function renderTransResult")
    rt = block(idx, "function renderTransResult", "function renderTransHistory")
    add(4, "译文记成笔记", (
        "openNotePage('【译文 p." in tr and "'trans'" in tr
        and 'id="nDraft"' not in idx          # 侧栏那个写入框已经删了（2026-11-22 用户）
        and "引用翻译记成笔记" in rt and "transNote(" in rt
        and "id=\"trNote\"" in rt
        and idx.count("openTextMenu(") == 2
        and "document.addEventListener('contextmenu'" in idx
    ), "译文「引用翻译记成笔记」→ 侧栏写作页，引用句是【译文 p.N】；菜单只在 contextmenu 里打开")

    np = block(idx, "function openNotePage(quote, kind)", "function renderNotes")
    qcss = block(idx, ".note-quote blockquote", "#noteCompose textarea")
    add(5, "记笔记（侧栏写作页）", (
        'id="noteCompose"' in idx and 'id="noteList"' in idx and 'id="page-note"' not in idx
        and 'id="npText"' in idx and 'id="npQuote"' in idx and 'id="btnNotePage"' in idx
        and 'id="nDraft"' not in idx and 'id="nAdd"' not in idx      # 写入框只在写作页里
        and "noteView(" in np and "noteView(true)" in np and "noteView(false)" in idx
        and "NP_QUOTE" in np and "q:NP_QUOTE" in idx and "NP_KIND" in np
        and "kind:NP_KIND" in idx
        and "color:var(--faint)" in qcss and "user-select:text" in qcss
        and ".nitem.self{" in idx and ".nitem.trans{" in idx
    ), "记笔记把侧栏切到写作页（灰底只读引用 + 1 个输入）；自己写/引用译文两种颜色；引用跟着笔记存（q）")

    add(7, "翻译两框", (
        'id="trSwap"' in idx and 'id="trFrom"' in idx and 'id="trTo"' in idx
        and idx.count('id="trSrc"') == 1 and 'id="trOut"' in idx
        and "#sideTrans textarea#trSrc" in idx and ".tr-out" in idx
        and "if($('#trGo'))" in idx and "TR.to" in idx and "syncTrDir()" in idx
    ), "翻译：上面一个框输入、中间 ↑↓ 换方向、下面一个框出译文（没译文时是占位）")

    # 2026-11-23 用户：「正常记笔记（就是没有引用的情况下）就不用灰字」
    add(8, "无引用不出灰框", (
        "const q = String(quote || '').trim();" in np
        and "currentPageQuote()" not in np          # 不再拿整页文字兜底当引用
        and "qw.hidden = !q" in np and "no-quote" in np
        and "function currentSelText()" in idx and "openNotePage(currentSelText()" in idx
        and ".note-quote[hidden]" in idx
    ), "没引用时灰框整块不出（连占位也没有）；「记笔记」只引用当前选中，选不到就是纯笔记")

    hist = block(idx, "function renderTransHistory(items)", "async function transPage")
    ok_hist, detail = behavior_history(root)
    add(6, "翻译历史 5 条", (
        "translate-history.json" in srv and "TRANS_HISTORY_MAX = 5" in srv
        and "/api/translate/history" in srv and "push_translate_history" in srv
        and "[:120]" in srv and "[:400]" in srv
        and "id=\"trHist\"" in idx and "最近 5 条" in hist
        and "renderTransHistory" in hist and "loadTransHistory" in idx
        and ok_hist is True
    ), detail or "历史函数没跑通")

    return rows


def main():
    if "--selftest" in sys.argv:
        return selftest()
    rows = check(ROOT)
    bad = 0
    for no, name, ok, detail in rows:
        print("[%s] %d/%d %s —— %s" % ("绿" if ok else "红", no, len(rows), name, detail))
        if not ok:
            bad += 1
    print("结论：%d/%d" % (len(rows) - bad, len(rows)))
    return 0 if bad == 0 else 1


def selftest():
    """临时副本逐个造坏：每条判据都必须变红，证明它真的会失败。"""
    base = os.path.join(ROOT, "_trash")
    os.makedirs(base, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="pluma-reading-tools-", dir=base)
    root = os.path.join(tmp, "repo")
    try:
        os.makedirs(os.path.join(root, "ui"))
        for rel in (IDX, SRV, "paths.py", "courses.json"):
            src = os.path.join(ROOT, rel)
            dst = os.path.join(root, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copyfile(src, dst)
        orig_idx = read(root, IDX)
        orig_srv = read(root, SRV)

        def reset():
            with open(os.path.join(root, IDX), "w", encoding="utf-8", newline="") as f:
                f.write(orig_idx)
            with open(os.path.join(root, SRV), "w", encoding="utf-8", newline="") as f:
                f.write(orig_srv)

        defects = [
            ("标题条退回 pointermove", 1, IDX, "bar.addEventListener('mousedown'", "bar.addEventListener('pointerdown'"),
            ("退出全屏去掉 SWP_FRAMECHANGED", 2, SRV, "flags = 0x0040 | 0x0020", "flags = 0x0040"),
            ("移动入口被拿掉", 3, IDX, 'data-fmove="', 'data-mv="'),
            ("左键松手也弹菜单", 4, IDX, "/* 全屏（2026-11-17", "document.addEventListener('mouseup', e => { const s = String(window.getSelection()); if(s) openTextMenu(1,1,s); });\n/* 全屏（2026-11-17"),
            ("侧栏写作页缺失", 5, IDX, 'id="noteCompose"', 'id="noteCompose-x"'),
            ("历史条数改成 9", 6, SRV, "TRANS_HISTORY_MAX = 5", "TRANS_HISTORY_MAX = 9"),
            ("没引用也画灰框", 8, IDX, "if(qw) qw.hidden = !q;", "if(qw) qw.hidden = false;"),
        ]
        all_ok = True
        for label, no, rel, old, new in defects:
            reset()
            p = os.path.join(root, rel)
            text = read(root, rel)
            if text.count(old) != 1:
                print("  [红] %s：造坏锚点出现 %d 次" % (label, text.count(old)))
                all_ok = False
                continue
            with open(p, "w", encoding="utf-8", newline="") as f:
                f.write(text.replace(old, new, 1))
            rows = check(root)
            hit = [r for r in rows if r[0] == no and not r[2]]
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
