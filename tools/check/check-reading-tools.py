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
 14 侧栏三块各自选边：左右可同时存在，背板不复制面板，拖页签换边，选择记在 localStorage
 15 阅读空态：最近阅读 5 文件 + 3 课程（分组、按打开先后；课程用卡片；不再弹「先到课程抽屉…」）

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

    # 14 四角停靠（2026-11-25 用户第三条：左上 / 左下 / 右上 / 右下，同侧可上下各一块）
    add(14, "四角停靠（同侧上下两块）", (
        'data-slot="lt"' in idx and 'data-slot="lb"' in idx and 'data-slot="rt"' in idx and 'data-slot="rb"' in idx
        and 'class="dropzone dz-lt" data-drop="lt"' in idx and 'class="dropzone dz-lb" data-drop="lb"' in idx
        and 'class="dropzone dz-rt" data-drop="rt"' in idx and 'class="dropzone dz-rb" data-drop="rb"' in idx
        and "const SLOTS = ['lt', 'lb', 'rt', 'rb']" in idx
        and "let SIDE_DOCK = { notes: 'rt'" in idx and "pluma.sideDock" in idx and "pluma.sideActive" in idx
        and "function applyDock()" in idx
        and "b.draggable = true" in idx and "let DRAG_KEY" in idx and "function movePanelTo(k, slot)" in idx
        and 'id="btnSide"' not in idx and ".stab.mv{" not in idx          # 换边不再靠按钮
        and "el && el.parentElement !== box) box.appendChild(el)" in idx   # 面板跟着格子搬，不复制
        and ".side-col.left{grid-column:1;grid-row:1}" in idx             # 一侧 hidden 时讲义不被顶到第 1 列
        and ".read-body[data-docks=\"none\"] .reader{grid-column:1}" in idx
        and ".side[hidden]{display:none}" in idx and "#sideChat[hidden]{display:none}" in idx
        and "col.classList.toggle('one', on.length === 1)" in idx         # 只有一格时占满整列
        and "SIDE_SPLIT[side]" in idx and "pluma.sideSplit" in idx        # 上下比例可拖、可记忆
    ), "四角（左上/左下/右上/右下）都能停；同侧上下各一块、比例可拖；面板只搬家不复制；单格占满整列，空列收起")

    # 15 阅读页空态「最近阅读」（2026-11-25 用户第四条）
    add(15, "阅读空态：最近阅读（5 文件 + 3 课程，分组、按打开先后）", (
        'id="recentPage"' in idx and "const RECENT_RD_KEY = 'pluma.recentRead'" in idx
        and "function recentRdFile(" in idx and "function recentRdCourse(" in idx
        and "function renderRecent()" in idx and "function showReadPage()" in idx
        and "st.files.slice(0, 5)" in idx and "st.courses.slice(0, 3)" in idx
        and '<div class="rg">文件</div>' in idx and '<div class="rg">课程</div>' in idx
        and 'class="course" data-rcc=' in idx            # 课程用卡片，不是行
        and "recentRdFile(rel, name, code, goPage || 1)" in idx      # 打开讲义就记一笔
        and "recentRdCourse(c.code)" in idx                          # 打开课程抽屉也记一笔
        and "先到课程抽屉里点一份讲义" not in idx                    # 那句 toast 不再拦人
    ), "没打开讲义时进阅读页给最近阅读：文件 5 条 + 课程 3 张卡片（分组、按先后点开排）；文件点开续读、课程点开抽屉；没有记录才给一句空态提示")

    # 16 阅读页铺满高度（2026-11-25 用户第二条：侧栏底线还有空位）
    add(16, "阅读页铺满高度（侧栏到窗口底边）", (
        "body.read-mode .wrap{max-width:none;padding:4px 12px 0}" in idx
        and "body.read-mode footer{display:none}" in idx
        and "function fitReadCard()" in idx
        and "card.style.height = h + 'px';" in idx
        and "window.innerHeight - top - 12" in idx
        and "calc(100vh - 190px)" not in idx
        and ".reader{background:var(--reader-bg);padding:18px;min-height:0;min-width:0;height:100%;display:flex" in idx
        and ".side{background:var(--card);padding:14px;border:0;min-height:0;height:100%;max-height:none" in idx
    ), "卡片按窗口可用高度钉住（不再跟 PDF 内容走），讲义与侧栏一起到窗口底边；阅读页用满宽度、不显示 footer")

    # 17 侧栏宽度可拖 + 窗口同步加宽（2026-11-25 用户第四条）
    add(17, "侧栏可拖宽，窗口跟着加宽", (
        "const SIDE_W_MIN = 260, SIDE_W_MAX = 560;" in idx
        and "pluma.sideW" in idx and "pluma.sideSplit" in idx
        and "function initSideResizers()" in idx and "function setSideWidth(side, w" in idx
        and "function shiftWindow(delta)" in idx and "a.shift_width" in idx
        and "let WIN_EXTRA = 0;" in idx
        and "def shift_width(self, dx):" in srv and "SystemParametersInfoW(0x0030" in srv
        and "SWP_NOZORDER | SWP_NOACTIVATE" in srv       # 只在注释里也行：改动窗口不动层级
        and "u.SetWindowPos(h, None, int(x), int(y), int(w), int(oldh)," in srv
    ), "左右侧栏各自可拖 260–560（双击回 300）；开/收/拖宽时窗口按同样像素向外加，到屏幕工作区边为止，讲义列不被挤窄")

    # 18 全屏 / 最大化拖动（2026-11-25 用户第一条：软件全屏之后拖不动）
    add(18, "全屏与最大化也能拖窗口", (
        "bindReadTopDrag" in idx
        and "top.addEventListener('mousedown'" in idx
        and "if(!inFullscreen()) return;" in idx
        and "setFullscreen(false).then(() => {" in idx
        and "a.drag_window()" in idx
        and "time.sleep(0.10)" in drag
        and 'return {"ok": True, "restored": True}' not in drag
        and "u.SetWindowPos(h, None, x0 + dx, y0 + dy, 0, 0, flags)" in drag
    ), "全屏时按住阅读工具条空白 → 先退出全屏回原尺寸 → 继续跟手拖；最大化时还原后不再要求拖第二次")

    # 19 全屏保留出血位（2026-11-25 用户：「全屏的情况下也要保留出血位」）
    add(19, "全屏保留出血位", (
        ".read-card.fs{position:fixed;inset:12px" in idx
        and "border:12px solid var(--bg)" in idx
        and "width:100vw;height:100vh" in idx
        and ".read-card:fullscreen::backdrop{background:var(--bg)}" in idx
        and "border-radius:12px" in idx
    ), "全屏不再贴死屏幕四边：留 12px 界面底色（与窗口模式的 12px 对齐），带同款圆角；原生全屏的 backdrop 也用界面底色")

    # 20 窗口缩放时卡片跟着变高 + WebView 底色跟主题（2026-11-25 用户：「图一图二的同一类问题」
    #   与「拉伸窗口的时候卡顿感太强了 甚至会出现白边」）
    add(20, "窗口缩放后卡片仍铺满，拖动不露白边", (
        "window.__plumaFitReadCard = fitReadCard;" in idx          # 模块作用域的函数挂到 window，窗口层才调得到
        and "function fitReadCardOnResize()" in idx
        and "window.addEventListener('resize', fitReadCardOnResize" in idx   # 每帧跟高度
        and "if(window.__plumaFitReadCard) window.__plumaFitReadCard();" in idx
        and "nudgeWin();\n      try{ fitReadCard();" not in idx    # 拖边收尾不再做 ±1px 的 relayout
        and "background_color=_window_bg_color()" in srv          # 露出来的那块不再是写死浅色
        and '"#111110" if theme == "dark" else "#F7F5EF"' in srv
        and "def set_bg(self, theme):" in srv                     # 换主题立刻换底色
        and "DefaultBackgroundColor" in srv
        and "api.set_bg(t)" in idx
    ), "卡片高度每帧跟窗口（窗口层通过 window.__plumaFitReadCard 调）；窗口/WebView2 底色按主题取（深色 #111110、浅色 #F7F5EF），换主题即换；细碎拖边不重设窗口，跨度 >220px 才兜一次 relayout")

    # 21 阅读空态 / 侧栏「列表」/ 会话开场白（2026-11-25 用户看图后定）
    add(21, "空态只留最近阅读 · 侧栏列表 · 会话开场白", (
        'id="readCard" hidden' in idx                                  # 空态不露空讲义卡
        and ".read-card[hidden]{display:none}" in idx                  # display:flex 会顶掉 [hidden]
        and "if(typeof showReadPage === 'function' && !RD.doc) showReadPage();" in idx
        and 'id="sideList" hidden' in idx
        and "const PANEL_KEYS = ['notes', 'trans', 'chat', 'list'];" in idx
        and "list: 'sideList'" in idx and "list: '列表'" in idx
        and "function renderSideList()" in idx
        and "只列这门课" in idx
        and "00_原件 · 只列 PDF" in idx                               # 原件只列能读的 PDF
        and "data-lrel=" in idx and "openReader(el.dataset.lrel, el.dataset.lname, RD.code, 1)" in idx
        and 'class="msg a sc-welcome"' in idx
        and 'data-ex="这一讲最重要的三个概念是什么？"' in idx
        and "SC.messages.length ? box.scrollHeight : 0" in idx        # 开场白从第一句看起
        and 'id="updShot"' not in idx and "更新卡只要纯文字，不显示版本速览图" in idx
    ), "没打开讲义只显示最近阅读；列表页签只列本课程（成品 + 00_原件 的 PDF）、当前行标「正在读」、点一行换读；会话空记录给开场白 + 三个例子（只填输入框不发请求）；更新卡只要纯文字、不显示版本速览图")

    # 22 pdf.js 测量画布不许在 body 里占位（2026-11-25 用户：「偶尔一大片黑」）
    add(22, "阅读页不被 pdf.js 测量画布挤黑", (
        ".hiddenCanvasElement{position:absolute !important" in idx
        and "left:-9999px !important" in idx
        and "width:1px !important;height:1px !important" in idx
        and "body.win{height:100vh;overflow:hidden;display:flex;flex-direction:column}" in idx
    ), "pdf.js 的字体测量画布（不透明黑）被挪出视口并缩到 1px；否则它会成为 body 的 flex 子项，实测把 #appScroll 从 794 挤到 168（页面下半截全黑）")

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
            ("四角又变回左右", 14, IDX, "const SLOTS = ['lt', 'lb', 'rt', 'rb'];", "const SLOTS = ['left','right'];"),
            ("换边又改回按钮", 14, IDX, "b.draggable = true", "b.draggable = false"),
            ("卡片高度又跟内容走", 16, IDX, "card.style.height = h + 'px';", "card.style.height = '';"),
            ("侧栏不再可拖", 17, IDX, "function initSideResizers(){", "function initSideResizersX(){"),
            ("全屏拖动被拿掉", 18, IDX, "if(!inFullscreen()) return;", "return;"),
            ("全屏又贴死屏幕", 19, IDX, "inset:12px;z-index:70", "inset:0;z-index:70"),
            ("原生全屏的出血边框被拿掉", 19, IDX, "border:12px solid var(--bg)", "border:0"),
            ("最近阅读不再记录", 15, IDX, "const RECENT_RD_KEY = 'pluma.recentRead'", "const RECENT_RD_KEY = 'pluma.recentReadX'"),
            ("卡片不再跟窗口缩放", 20, IDX, "window.__plumaFitReadCard = fitReadCard;", ""),
            ("WebView 底色又写死浅色", 20, SRV, "background_color=_window_bg_color()", 'background_color="#F7F5EF"'),
            ("空态又露出空讲义卡", 21, IDX, 'id="readCard" hidden', 'id="readCard"'),
            ("列表页签被拿掉", 21, IDX, 'id="sideList" hidden', 'id="sideListX" hidden'),
            ("会话开场白被拿掉", 21, IDX, 'class="msg a sc-welcome"', 'class="msg a"'),
            ("pdf.js 测量画布又占位", 22, IDX, ".hiddenCanvasElement{position:absolute !important", ".hiddenCanvasElement{"),
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
