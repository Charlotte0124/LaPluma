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
  9 讲次芯片排版：标题可省略，「占位」与讲号不收缩不折行
 10 「最近 5 条」翻译历史在整块最下面
 11 笔记颜色 + PDF 引用高亮（悬停亮、点击常驻、右键换色）
 12 笔记列表溢出不压扁条目；点空白处清掉选区
 13 离线语言包接在侧栏（管理常驻 / 状态条收起 / 三档引擎）
 14 侧栏三块各自选边：左右可同时存在，背板不复制面板，选择记在 localStorage

用法：
    python tools\check\check-reading-tools.py            # 判本仓
    python tools\check\check-reading-tools.py --selftest # 临时副本逐个造坏，先证明会红

退出码：0 = 全部绿（项数以输出为准）· 1 = 有红
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

    np = block(idx, "function openNotePage(quote, kind, src)", "function renderNotes")
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

    # 2026-11-23 用户：「这个（英文 ↑↓ 中文）就不可以放在两个方块中间吗，然后翻译再重新找一个位置」
    i_src, i_dir, i_out = idx.find('id="trSrc"'), idx.find('class="tr-dir"'), idx.find('id="trOut"')
    add(7, "翻译两框", (
        'id="trSwap"' in idx and 'id="trFrom"' in idx and 'id="trTo"' in idx
        and idx.count('id="trSrc"') == 1 and 'id="trOut"' in idx
        and "#sideTrans textarea#trSrc" in idx and ".tr-out" in idx
        and "if($('#trGo'))" in idx and "TR.to" in idx and "syncTrDir()" in idx
        # DOM 顺序：输入框 → 方向行 → 输出框；翻译按钮在标题行（在输入框之前）
        and 0 < i_src < i_dir < i_out
        and '<div class="tr-head">' in idx and 0 < idx.find('id="trGo"') < i_src
    ), "翻译：上面一个框输入、中间 ↑↓ 换方向、下面一个框出译文；翻译按钮在标题行（不夹在两个框中间）")

    # 2026-11-23 用户：「正常记笔记（就是没有引用的情况下）就不用灰字」
    add(8, "无引用不出灰框", (
        "const q = String(quote || '').trim();" in np
        and "currentPageQuote()" not in np          # 不再拿整页文字兜底当引用
        and "qw.hidden = !q" in np and "no-quote" in np
        and "function currentSelText()" in idx and "openNotePage(currentSelText()" in idx
        and ".note-quote[hidden]" in idx
    ), "没引用时灰框整块不出（连占位也没有）；「记笔记」只引用当前选中，选不到就是纯笔记")

    # ---- 2026-11-23 用户第二批（图1~图5）----
    # 1 排版：讲次芯片里「占位」「T06-2」被挤成竖排/折行
    lsn = block(idx, ".lsn button{position:relative", ".lsn .kill{display:none}")
    add(9, "讲次芯片不挤", (
        "display:inline-flex" in lsn and "min-width:0" in lsn
        and ".ttl{flex:1 1 auto" in idx
        and ".no{flex:0 0 auto;white-space:nowrap" in idx
        and ".stub{flex:0 0 auto;white-space:nowrap" in idx
    ), "标题独占可收缩那份（省略号），「占位」徽标与讲号不收缩不折行")

    # 2 最近五条翻译挪到整块最下面
    ti, to, th = idx.find('id="trHist"'), idx.find('id="trOut"'), idx.find("留空就直接翻这一页的文字层")
    add(10, "翻译历史在底部", (
        ti > 0 and to > 0 and th > 0 and ti > to and ti > th
        and ".tr-hist{margin:14px 0 0;border-top:1px solid var(--line2)" in idx
    ), "「最近 5 条」在译文框与提示语之后（整块最下面），不再挡在输入框上面")

    # 3 笔记颜色 + PDF 里的引用高亮
    add(11, "笔记颜色与高亮", (
        "const NC = {" in idx and "paintHL" in idx and "openNoteColorMenu" in idx
        and "action:'color'" in idx and "id=\"pdfhl\"" in idx
        and ".nitem.pin{" in idx and "#pdfhl .hl" in idx
        and "NOTE_COLORS = (\"green\", \"amber\", \"blue\", \"purple\", \"red\")" in srv
        and 'elif act == "color":' in srv
        and "paintHL();" in idx
    ), "悬停/点击高亮 PDF 里那段引用、右键选颜色（标签色与高亮色同改）；服务端 action=color 存颜色")

    # 4 笔记不被压扁 + 点空白处取消选中
    add(12, "笔记不压扁·点空白取消选中", (
        ".nlist{display:flex;flex-direction:column;gap:8px;max-height:320px;overflow:auto}" in idx
        and ".nlist > .nitem{flex:0 0 auto}" in idx      # 溢出时子项不许收缩（那条笔记被压成 25.6px 的坑）
        and "t.closest('#pdftext') || t.closest('.note-menu')" in idx
        # 笔记条目也叫 .trans；译文结果框那条样式必须只在 .tr-out 里生效
        and ".tr-out .trans{" in idx and "\n.trans{" not in idx
    ), "列表溢出时笔记不再被 flex 压成空条；.trans 样式只作用在译文框（笔记条目不再被当成译文框）；点空白清选区")

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

    # 13 离线语言包（2026-11-24）：管理常驻、状态条翻完收起、服务端三档引擎
    add(13, "离线语言包接在侧栏", (
        "offline_mt" in srv and "/api/translate/packs" in srv
        and "start_download" in srv and "remove_packs" in srv
        and '"translate_engine"' in srv and 'engine == "offline"' in srv
        and 'engine == "auto" and not has_key' in srv
        and 'id="trMgrBtn"' in idx and 'id="trStrip"' in idx
        and 'id="trBadge"' in idx and 'id="trEngine"' in idx
        and "pluma.trStripHidden" in idx and "hideTrStrip(true)" in idx
        and ".tr-strip{" in idx and ".mgr{" in idx
    ), "「管理」常驻（翻多少次都在）、状态条翻一次写 localStorage 收起、三档引擎与下载/删除都接上")

    # 14 侧栏三块各自选边（2026-11-25 用户：「这个设置保留 并且增加左右都可以同时存在的」）
    add(14, "侧栏三块各自选边（左右可同时存在）", (
        'data-dock="left"' in idx and 'data-dock="right"' in idx
        and '.read-body[data-docks="lr"]{grid-template-columns:300px 1fr 300px}' in idx
        and '.read-body[data-docks="l"]{grid-template-columns:300px 1fr}' in idx
        and ".side[data-dock=\"left\"]{border-left:0;border-right:1px solid var(--line2)}" in idx
        and "let SIDE_DOCK = {" in idx and "pluma.sideDock" in idx and "pluma.sideActive" in idx
        and "function applyDock()" in idx and "function movePanel(" in idx and "function swapSides()" in idx
        and 'id="btnSide"' in idx and ".side-tabs .stab.mv{" in idx
        and "el && el.parentElement !== box) box.appendChild(el)" in idx   # 面板跟着边搬，不复制
        and "applyDock();   // 首屏先把页签条画出来" in idx
    ), "笔记 / 翻译 / 会话 各自存边（left/right），两边没面板的列自动收起；页签条上 ⇤/⇥ 只挪一块，工具条 ⇄ 侧栏整叠换边；选择记在 localStorage")

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
            ("翻译输入框被改名", 7, IDX, 'id="trSrc"', 'id="trSrcX"'),
            ("没引用也画灰框", 8, IDX, "if(qw) qw.hidden = !q;", "if(qw) qw.hidden = false;"),
            ("讲次芯片又允许收缩", 9, IDX, ".lsn button .stub{flex:0 0 auto;white-space:nowrap;", ".lsn button .stub{"),
            ("翻译历史回到输入框上面", 10, IDX, '<button class="btn" id="trGo">翻译</button>', '<button class="btn" id="trGo">翻译</button><div class="tr-hist" id="trHist"></div>'),
            ("颜色表被改名", 11, IDX, "const NC = {", "const NCOLOR = {"),
            ("笔记又允许被压扁", 12, IDX, ".nlist > .nitem{flex:0 0 auto}", ".nlist > .nitem{flex:1 1 auto}"),
            ("译文框样式又变成全局", 12, IDX, ".tr-out .trans{white-space:pre-wrap;font-size:13px;line-height:1.8", ".trans{white-space:pre-wrap;font-size:13px;line-height:1.8"),
            ("管理按钮被拿掉", 13, IDX, 'id="trMgrBtn"', 'id="trMgrBtnX"'),
            ("状态条不再收起", 13, IDX, "hideTrStrip(true)", "hideTrStrip(false)"),
            ("侧栏不再分边", 14, IDX, "let SIDE_DOCK = {", "let SIDEDOCK = {"),
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
