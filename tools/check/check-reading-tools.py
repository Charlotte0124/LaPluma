# -*- coding: utf-8 -*-
r"""check-reading-tools.py — 阅读页六件事的判据（2026-11-22）

为什么有这条：用户按六条实测提了「标题条拖不动 / 全屏退出缩不回去 / 原件放错课程
搬不走 / 右键翻译后没法记账 / 笔记只能挤在侧栏 / 译文翻完就丢」。界面改动很容易
「改完看着对了」但实际没接上，所以这里把每条的可执行判据钉住：

  1 标题条 mousedown 调 _WinApi.drag_window（ReleaseCapture + WM_NCLBUTTONDOWN/HTCAPTION）
  2 退出全屏 restore_bounds 带 SWP_FRAMECHANGED，并在 260ms 后再补一次
  3 文件列表原件行有「移动」，走 /api/move-originals，搬完重取课程与讲次
  4 译文有「记成笔记」，以【译文 p.N】进 #nDraft 并切笔记页签；菜单只由右键打开
  5 记笔记有独立整页（左原文引用 / 右输入框），#nDraft 仍保留
  6 翻译历史存 ~/.pluma/translate-history.json，最多 5 条；页签顶部可回填

用法：
    python tools\check\check-reading-tools.py            # 判本仓
    python tools\check\check-reading-tools.py --selftest # 临时副本逐个造坏，先证明会红

退出码：0 = 6/6 · 1 = 有红
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
    add(1, "标题条拖动", (
        "bar.addEventListener('mousedown'" in bar
        and "a.drag_window()" in bar
        and "move_by" not in bar
        and "pointerdown" not in bar
        and "def drag_window(" in srv
        and "_find_hwnd()" in block(srv, "def drag_window(", "def start_drag(")
        and "ReleaseCapture()" in block(srv, "def drag_window(", "def start_drag(")
        and "SendMessageW" in block(srv, "def drag_window(", "def start_drag(")
        and "0x00A1" in block(srv, "def drag_window(", "def start_drag(")
    ), "mousedown → drag_window；服务端 ReleaseCapture + WM_NCLBUTTONDOWN")

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
        "【译文 p." in tr and "#nDraft" in tr and "sideTab('notes')" in tr
        and "id=\"trNote\"" in rt and "transNote(" in rt
        and idx.count("openTextMenu(") == 2
        and "document.addEventListener('contextmenu'" in idx
    ), "译文「记成笔记」→【译文 p.N】进 #nDraft 并切笔记页签；菜单只在 contextmenu 里打开")

    np = block(idx, "function openNotePage(quote)", "function renderNotes")
    add(5, "整页笔记", (
        "id=\"page-note\"" in idx and "id=\"npText\"" in idx and "id=\"npQuote\"" in idx
        and "id=\"btnNotePage\"" in idx and "function openNotePage(quote)" in idx
        and "action:'add'" in np and "showPage('read')" in np
        and "id=\"nDraft\"" in idx
    ), "整页笔记左原文右输入，保存走 /api/notes；#nDraft 仍保留")

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
        print("[%s] %d/6 %s —— %s" % ("绿" if ok else "红", no, name, detail))
        if not ok:
            bad += 1
    print("结论：%d/6" % (len(rows) - bad))
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
            ("整页笔记页缺失", 5, IDX, 'id="page-note"', 'id="page-note-x"'),
            ("历史条数改成 9", 6, SRV, "TRANS_HISTORY_MAX = 5", "TRANS_HISTORY_MAX = 9"),
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
