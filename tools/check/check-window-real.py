# -*- coding: utf-8 -*-
r"""真窗口自测：在羽毛笔**自己的 WebView2 窗口**里量窗口矩形、选中位置与生成列表。

为什么要有这一条（用户 2026-11-22）：
  「标题条按住没有交给系统」「从全屏退出之后会占据整个屏幕，没办法缩小」
  「选中的位置跟实际的字不完全重合」「生成完了应该要在列表里面消失掉」
  这四件事全是**窗口层/排版层**的行为：接口能返回 ok、静态判据也能绿，
  但真窗口里一拖就错。所以这里起真窗口，用 WebView2 的 CDP 端口驱动页面点击，
  再用 Win32 去量窗口矩形、用 pymupdf 的词框去校文字层——两把不同的尺子对同一页。

判据：
  W1 真窗口起来了（win 样式 + 自绘标题条 + 版本号）
  W2 阅读页点全屏 → 再退出，窗口矩形回到原样（±2px），且不是最大化
  W3 文字层是 pdf.js 官方 TextLayer（dataset.tl=official），且选中词的框与 pymupdf 词框对齐（±6px）
  W4 已成稿的讲次不在生成列表；抽屉成品行有「重新生成」，点了能放回并勾上
  W5 选完松手不弹菜单；右键才弹，且两项都在（翻译这段 / 记笔记）
  W7 黑框兜底：relayout() 幂等（不改窗口、不改画面），html 背景不透明（不会露纯黑）
  W8 Esc 退出全屏：全屏里按 Esc，全屏元素清掉、标题条回来（WebView2 自己不收这个键）
  W9 记笔记单框：点「记笔记」把侧栏切到写作页（灰底只读引用 + 1 个输入框），保存后回列表并带引用
  W10 翻译两框：上下两个框 + 中间 ↑↓ 可交换方向；上面能输入；没译文时不出「引用翻译记成笔记」
  W11 拖选：起点在按下的地方（不是行首），松手后选区保留
  W12 滚动条槽：出滚动条前后内容宽度不变（gutter 固定；不然「刚好一屏」时界面抖、底边闪白条）
  W13 不自激：relayout 之后 4 秒不再持续收到 resize（它 +1px 逼重算，页面别回头再调它）
  W14 正常记笔记（没引用）时不显示那个灰框；有选中时灰框回来
  W15 笔记悬停/点击 → PDF 里那段引用高亮（常驻）；右键换色 → 标签色与高亮色同改
  W16 点空白处把选区清掉
  W17 排版不挤：讲次芯片的徽标/讲号单行，笔记条目不被 flex 压扁

注意：主脚本是 <script type="module">，函数不在 window 上——所以这里只点界面元素，
      不调页面函数；页面里只读 DOM、设选区。

用法：
    python tools/check/check-window-real.py            # 起真窗口跑一遍，跑完自己关
    python tools/check/check-window-real.py --keep     # 留下临时数据根与窗口（排查用）
    python tools/check/check-window-real.py --drag     # 额外做一次真实鼠标拖动（会动一下鼠标）

退出码：0 全绿；1 有红；2 没查（缺 playwright / 起不来窗口）
"""
from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wt
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
GREEN, RED, YELLOW = [], [], []


def ok(name, detail):
    GREEN.append("%s %s" % (name, detail))


def bad(name, detail):
    RED.append("%s %s" % (name, detail))


def skip(name, detail):
    YELLOW.append("%s %s" % (name, detail))


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def wait_http(url, timeout):
    end = time.time() + timeout
    while time.time() < end:
        try:
            with urllib.request.urlopen(url, timeout=2) as r:
                if r.status == 200:
                    return True
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.4)
    return False


def make_home():
    """临时数据根：拷一份 DEMO，再造一个「原件 + 成品」都齐的讲次（D01）。

    要验「已成稿就隐藏」就必须有成对的数据，所以自己造一份；只在 tempfile 里，
    不碰用户真正的课程目录（启动时把 paths.DATA_ROOT 指过来，见 _win_launch.py），
    跑完删掉。
    """
    home = Path(tempfile.mkdtemp(prefix="pluma-win-"))
    course = home / "TDEMO"
    shutil.copytree(ROOT / "DEMO", course)
    (course / "00_原件").mkdir(exist_ok=True)
    import pymupdf
    doc = pymupdf.open()
    page = doc.new_page(width=420, height=595)
    page.insert_text((60, 90), "Sample 01 original source", fontsize=14)
    doc.save(str(course / "00_原件" / "Sample 01.pdf"))
    doc.close()
    # 首次运行向导会盖住整个界面：先写一份「已配置」的 api.json（不含 key），
    # 这样窗口起来就是正常界面——自测要测的是窗口与生成列表，不是向导。
    import json as _json
    (home / "api.json").write_text(_json.dumps(
        {"wizard_done": True, "model": "deepseek-flash", "save_dir": "out"}), encoding="utf-8")
    py = course / "_lessons" / "D01.py"
    text = py.read_text(encoding="utf-8")
    text2 = re.sub(r"(LESSON\s*=\s*\{)", r'\1\n    "orig": "Sample 01",', text, count=1)
    if text2 == text:
        text2 = text.replace('"lang"', '"orig": "Sample 01", "lang"', 1)
    py.write_text(text2, encoding="utf-8")
    return home


def find_hwnd(pid):
    u = ctypes.windll.user32
    hits = []
    CB = ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)

    def cb(hwnd, _l):
        p = wt.DWORD()
        u.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
        if p.value == pid:
            n = u.GetWindowTextLengthW(hwnd)
            if n > 0:
                buf = ctypes.create_unicode_buffer(n + 1)
                u.GetWindowTextW(hwnd, buf, n + 1)
                if "羽毛笔" in buf.value or "La Pluma" in buf.value:
                    hits.append(hwnd)
        return True

    u.EnumWindows(CB(cb), 0)
    return int(hits[0]) if hits else 0


def rect_of(hwnd):
    r = wt.RECT()
    ctypes.windll.user32.GetWindowRect(wt.HWND(hwnd), ctypes.byref(r))
    return (int(r.left), int(r.top), int(r.right - r.left), int(r.bottom - r.top))


def is_zoom(hwnd):
    return bool(ctypes.windll.user32.IsZoomed(wt.HWND(hwnd)))


def drag_test(hwnd):
    """真的按住标题条拖 120px：SendInput 是系统级输入，不是页面里合成的事件。"""
    u = ctypes.windll.user32
    ULONG_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [("dx", ctypes.c_long), ("dy", ctypes.c_long),
                    ("mouseData", ctypes.c_ulong), ("dwFlags", ctypes.c_ulong),
                    ("time", ctypes.c_ulong), ("dwExtraInfo", ULONG_PTR)]

    class INPUT(ctypes.Structure):
        class _U(ctypes.Union):
            _fields_ = [("mi", MOUSEINPUT)]
        _anonymous_ = ("u",)
        _fields_ = [("type", ctypes.c_ulong), ("u", _U)]

    before = rect_of(hwnd)
    cur = wt.POINT()
    u.GetCursorPos(ctypes.byref(cur))
    x0 = before[0] + before[2] // 2
    y0 = before[1] + 18

    def send(flags):
        inp = INPUT(type=0)
        inp.mi = MOUSEINPUT(0, 0, 0, flags, 0, 0)
        u.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))

    u.SetForegroundWindow(hwnd)
    time.sleep(0.3)
    u.SetCursorPos(int(x0), int(y0))
    time.sleep(0.25)
    send(0x0002)                        # MOUSEEVENTF_LEFTDOWN
    time.sleep(0.25)
    for i in range(1, 13):
        u.SetCursorPos(int(x0 + i * 10), int(y0))
        time.sleep(0.02)
    time.sleep(0.2)
    send(0x0004)                        # MOUSEEVENTF_LEFTUP
    time.sleep(0.5)
    after = rect_of(hwnd)
    u.SetCursorPos(int(cur.x), int(cur.y))
    return before, after


def clear_overlay(page):
    """有弹窗盖着就先关掉（自测在真窗口里点，不要被遮罩挡住）。"""
    try:
        if not page.evaluate("!!document.querySelector('#veil.on')"):
            return True
        page.keyboard.press("Escape")
        time.sleep(0.4)
        if page.evaluate("!!document.querySelector('#veil.on')"):
            ghost = page.locator("#dlg .btn.ghost").first
            if ghost.count():
                ghost.click(timeout=3000)
                time.sleep(0.3)
        return not page.evaluate("!!document.querySelector('#veil.on')")
    except Exception:  # noqa: BLE001
        return False


def snap(hwnd):
    """PrintWindow 抓真窗口（跟给人看的那套一样，不依赖浏览器截图）。"""
    from PIL import Image
    u = ctypes.windll.user32
    r = rect_of(hwnd)
    w, h = r[2], r[3]
    hdc = u.GetWindowDC(wt.HWND(hwnd))
    mdc = ctypes.windll.gdi32.CreateCompatibleDC(hdc)
    bmp = ctypes.windll.gdi32.CreateCompatibleBitmap(hdc, w, h)
    ctypes.windll.gdi32.SelectObject(mdc, bmp)
    u.PrintWindow(wt.HWND(hwnd), mdc, 2)

    class BMI(ctypes.Structure):
        _fields_ = [("biSize", ctypes.c_uint32), ("biWidth", ctypes.c_int32),
                    ("biHeight", ctypes.c_int32), ("biPlanes", ctypes.c_uint16),
                    ("biBitCount", ctypes.c_uint16), ("biCompression", ctypes.c_uint32),
                    ("biSizeImage", ctypes.c_uint32), ("biXPelsPerMeter", ctypes.c_int32),
                    ("biYPelsPerMeter", ctypes.c_int32), ("biClrUsed", ctypes.c_uint32),
                    ("biClrImportant", ctypes.c_uint32)]

    bi = BMI()
    bi.biSize = ctypes.sizeof(BMI)
    bi.biWidth = w
    bi.biHeight = -h
    bi.biPlanes = 1
    bi.biBitCount = 32
    buf = ctypes.create_string_buffer(w * h * 4)
    ctypes.windll.gdi32.GetDIBits(mdc, bmp, 0, h, buf, ctypes.byref(bi), 0)
    img = Image.frombuffer("RGBA", (w, h), buf, "raw", "BGRA", 0, 1).convert("RGB")
    ctypes.windll.gdi32.DeleteObject(bmp)
    ctypes.windll.gdi32.DeleteDC(mdc)
    u.ReleaseDC(wt.HWND(hwnd), hdc)
    return img


def diff_ratio(a, b, top_skip=0.5):
    """两张同尺寸图在下半部分有多少像素明显不同（0~1）。"""
    if a.size != b.size:
        return 1.0
    w, h = a.size
    y0 = int(h * top_skip)
    pa, pb = a.load(), b.load()
    n = bad = 0
    for y in range(y0, h, 3):
        for x in range(0, w, 3):
            n += 1
            r1, g1, b1 = pa[x, y]
            r2, g2, b2 = pb[x, y]
            if abs(r1 - r2) + abs(g1 - g2) + abs(b1 - b2) > 36:
                bad += 1
    return bad / float(n or 1)


def main_child(hwnd):
    """父窗口里面积最大的那个直接子窗口（WebView2 的宿主）。"""
    u = ctypes.windll.user32
    hits = []
    CB = ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)

    def cb(ch, _l):
        r = wt.RECT()
        u.GetWindowRect(wt.HWND(ch), ctypes.byref(r))
        hits.append((int(ch), (r.right - r.left) * (r.bottom - r.top)))
        return True

    u.EnumChildWindows(wt.HWND(hwnd), CB(cb), 0)
    hits.sort(key=lambda x: -x[1])
    return hits[0][0] if hits else 0


def open_drawer(page, code):
    clear_overlay(page)
    page.click("a[data-page='courses']")
    page.wait_for_selector(".course", timeout=20000)
    page.locator(".course").filter(has_text=code).first.click()
    page.wait_for_selector("#drFiles .f", timeout=20000)


def open_reader_from_drawer(page):
    page.locator("#drFiles .f").first.click()
    page.wait_for_function("document.querySelectorAll('#pdftext span').length > 3", timeout=40000)


def span_probe(page, probes):
    """在页面里量「选中这些字」得到的选择框，与 pymupdf 的期望框作差。"""
    return page.evaluate("""(probes) => {
      const spans = [...document.querySelectorAll('#pdftext span')];
      const base = document.getElementById('pdftext').getBoundingClientRect();
      const out = [];
      for (const pr of probes) {
        let hit = null;
        for (const s of spans) {
          if (s.textContent && s.textContent.indexOf(pr.t) >= 0) { hit = s; break; }
        }
        if (!hit) { out.push({t: pr.t, miss: true}); continue; }
        const i = hit.textContent.indexOf(pr.t);
        const node = hit.firstChild;
        if (!node || node.nodeType !== 3) { out.push({t: pr.t, miss: true}); continue; }
        const rg = document.createRange();
        rg.setStart(node, i);
        rg.setEnd(node, i + pr.t.length);
        const r = rg.getBoundingClientRect();
        out.push({t: pr.t, dx: (r.left - base.left) - pr.x0,
                  dw: r.width - (pr.x1 - pr.x0),
                  dy: (r.top - base.top) - pr.y0});
      }
      return out;
    }""", probes)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep", action="store_true")
    ap.add_argument("--drag", action="store_true")
    args = ap.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:  # noqa: BLE001
        print("[没查] 装不上 playwright：%r" % (e,))
        return 2

    home = make_home()
    port, cdp = free_port(), free_port()
    env = dict(os.environ)
    env["PLUMA_HOME"] = str(home)
    env["PLUMA_TEST_CDP"] = str(cdp)
    env["PYTHONIOENCODING"] = "utf-8"
    log = open(str(home / "app.log"), "wb")
    env["PLUMA_TEST_DATA"] = str(home)
    proc = subprocess.Popen([sys.executable, str(HERE / "_win_launch.py"),
                             "--port", str(port), "--no-browser"],
                            cwd=str(ROOT), env=env, stdout=log, stderr=subprocess.STDOUT)
    try:
        if not wait_http("http://127.0.0.1:%d/api/bootstrap" % port, 90):
            print("[没查] 窗口起不来（看 %s）" % (home / "app.log"))
            return 2
        hwnd = 0
        end = time.time() + 30
        while time.time() < end and not hwnd:
            hwnd = find_hwnd(proc.pid)
            time.sleep(0.4)
        if not hwnd:
            print("[没查] 找不到窗口句柄")
            return 2

        if not wait_http("http://127.0.0.1:%d/json/version" % cdp, 60):
            tail = ""
            try:
                tail = (home / "app.log").read_text(encoding="utf-8", errors="replace")[-1200:]
            except Exception:  # noqa: BLE001
                pass
            print("[没查] CDP 端口没开（PLUMA_TEST_CDP=%d）；app.log 末尾：\n%s" % (cdp, tail))
            print("临时数据根：%s" % home)
            for _ in range(0):
                pass
            return 2

        with sync_playwright() as p:
            br = p.chromium.connect_over_cdp("http://127.0.0.1:%d" % cdp)
            page = None
            end = time.time() + 40
            while time.time() < end and page is None:
                for ctx in br.contexts:
                    for pg in ctx.pages:
                        if "win=1" in pg.url:
                            page = pg
                if page is None:
                    time.sleep(0.4)
            if page is None:
                print("[没查] CDP 连上了但没有 win=1 页面")
                return 2

            # ---- W1 真窗口 ----
            try:
                page.wait_for_selector("#tbar:not([hidden])", timeout=25000)
                page.wait_for_function(
                    "!!(document.querySelector('#tbVer')||{}).textContent", timeout=25000)
                ver = (page.evaluate("document.querySelector('#tbVer').textContent") or "").strip()
                iswin = page.evaluate("document.body.classList.contains('win')")
                if iswin and re.match(r"v\d", ver):
                    ok("W1 真窗口", "自绘标题条可见，版本号 %s" % ver)
                else:
                    bad("W1 真窗口", "win=%r 版本号=%r" % (iswin, ver))
            except Exception as e:  # noqa: BLE001
                bad("W1 真窗口", "标题条没出来：%r" % (e,))

            pdf_path = None
            for f in sorted((home / "TDEMO" / "01_讲义").glob("*.pdf")):
                pdf_path = f
                break

            # ---- 先打开阅读页（W2/W3/W5 都要它）----
            opened = False
            if pdf_path is not None:
                try:
                    open_drawer(page, "TDEMO")
                    open_reader_from_drawer(page)
                    opened = True
                except Exception as e:  # noqa: BLE001
                    bad("打开阅读页", "抽屉里点不成成品：%r" % (e,))
            else:
                bad("打开阅读页", "临时数据里没有成品 PDF")

            # ---- W2 全屏进出还原 ----
            if opened:
                try:
                    r0 = rect_of(hwnd)
                    page.click("#btnFs")
                    time.sleep(1.2)
                    page.click("#btnFs")
                    time.sleep(1.5)
                    r1 = rect_of(hwnd)
                    zoomed = is_zoom(hwnd)
                    d = max(abs(r1[i] - r0[i]) for i in range(4))
                    if zoomed:
                        bad("W2 全屏还原", "退出后仍是最大化：%r → %r" % (r0, r1))
                    elif d <= 2:
                        ok("W2 全屏还原", "%r → %r（最大偏差 %dpx）" % (r0, r1, d))
                    else:
                        bad("W2 全屏还原", "窗口没回原样：%r → %r（偏差 %dpx）" % (r0, r1, d))
                except Exception as e:  # noqa: BLE001
                    bad("W2 全屏还原", "全屏进出失败：%r" % (e,))

            # ---- W3 文字层与词框 ----
            if opened:
                try:
                    mode = page.evaluate("document.querySelector('#pdftext').dataset.tl || ''")
                    nspan = page.evaluate("document.querySelectorAll('#pdftext span').length")
                    # 2026-11-22：尺子有两把——页面里 pdf.js 排出来的 span，与 pymupdf 从同一份 PDF
                    #   独立解出的词框。逐段找「同一基线上最近的词」，左端偏差就是排版是否对位。
                    spans = page.evaluate("""() => {
                      const base = document.getElementById('pdftext').getBoundingClientRect();
                      return [...document.querySelectorAll('#pdftext span')]
                        .map(s => { const r = s.getBoundingClientRect();
                          return {t: s.textContent || '', x: r.left - base.left,
                                  y: r.top - base.top, w: r.width}; });
                    }""")
                    import pymupdf
                    d = pymupdf.open(str(pdf_path))
                    pg = d[0]
                    page_w = pg.rect.width
                    scale = page.evaluate(
                        "document.getElementById('pdfcanvas').clientWidth") / page_w
                    words = [(w[4].strip(), w[0] * scale, w[1] * scale, (w[2] - w[0]) * scale)
                             for w in pg.get_text("words") if w[4].strip()]
                    d.close()
                    norm = lambda s: re.sub(r"\s+", "", s)
                    by_text = {}
                    for t, wx, wy, ww in words:
                        by_text.setdefault(norm(t), ww)
                    checked, hits, worst, wbad, wdiffs = 0, 0, 0.0, 0, []
                    for sp in spans:
                        if not norm(sp["t"]):
                            continue
                        checked += 1
                        near = [(abs(sp["x"] - wx), wx, wy) for t, wx, wy, ww in words
                                if abs(sp["y"] - wy) <= 14]
                        if not near:
                            continue
                        dx = min(near)[0]
                        worst = max(worst, dx)
                        if dx <= 4:
                            hits += 1
                        key = norm(sp["t"])
                        if key in by_text:
                            wdiffs.append(abs(sp["w"] - by_text[key]))
                    if mode != "official":
                        bad("W3 文字层", "dataset.tl=%r（不是 pdf.js 官方 TextLayer）" % (mode,))
                    elif checked == 0:
                        skip("W3 文字层", "文字层是空的（%d 段），没敢判" % (nspan,))
                    elif hits < 0.75 * checked:
                        bad("W3 文字层", "只有 %d/%d 段落在 pymupdf 词框起点上（最差 %.1fpx，容差 4）"
                            % (hits, checked, worst))
                    elif wdiffs and max(wdiffs) > 8:
                        bad("W3 文字层", "段宽对不上：最差 %.1fpx（%d 段比对，容差 8）"
                            % (max(wdiffs), len(wdiffs)))
                    else:
                        ok("W3 文字层",
                           "官方 TextLayer %d 段；%d/%d 段与词框对位（最差 %.1fpx）；%d 段宽度偏差 ≤%.1fpx"
                           % (nspan, hits, checked, worst, len(wdiffs),
                              max(wdiffs) if wdiffs else 0.0))
                except Exception as e:  # noqa: BLE001
                    bad("W3 文字层", "没量成：%r" % (e,))

            # ---- W4 已成稿隐藏 / 重新生成 ----
            try:
                clear_overlay(page)
                page.click("a[data-page='generate']")
                page.wait_for_selector("#courseSel", timeout=15000)
                page.select_option("#courseSel", "TDEMO")
                time.sleep(0.5)
                chips = page.evaluate(
                    "[...document.querySelectorAll('#lessonPick [data-lsn]')].map(x=>x.dataset.lsn)")
                hint = (page.evaluate(
                    '(document.querySelector("#lsnDone")||{}).textContent || ""') or "").strip()
                if "D01" in chips:
                    bad("W4 隐藏成稿", "D01 已成稿却还在生成列表：%r" % (chips,))
                else:
                    open_drawer(page, "TDEMO")
                    has_btn = page.evaluate(
                        "!!document.querySelector('#drFiles [data-fregen=\"D01\"]')")
                    if not has_btn:
                        bad("W4 隐藏成稿", "D01 已隐藏，但抽屉成品行没有「重新生成」")
                    else:
                        page.click('#drFiles [data-fregen="D01"]')
                        time.sleep(0.6)
                        back = page.evaluate(
                            "!!document.querySelector('#lessonPick [data-lsn=\"D01\"]')")
                        sel = page.evaluate(
                            "(document.querySelector('#lsnCnt')||{}).textContent || ''")
                        if back and "1" in sel:
                            ok("W4 隐藏成稿", "列表已隐藏 %r；抽屉「重新生成」放回并勾上（%s / 提示 %s）"
                               % (chips, sel.strip(), hint[:20]))
                        else:
                            bad("W4 隐藏成稿", "点了重新生成但没放回：chip=%r 计数=%r"
                                % (back, sel))
            except Exception as e:  # noqa: BLE001
                bad("W4 隐藏成稿", "没验成：%r" % (e,))

            # ---- W5 只有右键弹菜单 ----
            if opened:
                try:
                    page.click("a[data-page='read']")
                    page.wait_for_function(
                        "document.querySelectorAll('#pdftext span').length > 3", timeout=30000)
                    box = page.evaluate("""() => {
                        const sp = [...document.querySelectorAll('#pdftext span')]
                          .filter(s => s.getBoundingClientRect().width > 80)
                          .sort((a,b)=>b.textContent.length-a.textContent.length)[0];
                        if(!sp) return null;
                        sp.scrollIntoView({block:'center'});
                        const r = sp.getBoundingClientRect();
                        return {x:r.left, y:r.top, w:r.width, h:r.height, t:sp.textContent.slice(0,8)};
                    }""")
                    # 判的是「菜单只由右键打开」这条规矩，不判「鼠标拖选能不能选上」
                    #   （拖选在 CDP 发真鼠标事件时偶发选不上，跟规矩无关；选区这里用 Range 造，
                    #   右键仍然是真的右键）。
                    sel_text = page.evaluate("""() => {
                      const sp = [...document.querySelectorAll('#pdftext span')]
                        .filter(s => s.getBoundingClientRect().width > 80)
                        .sort((a,b)=>b.textContent.length-a.textContent.length)[0];
                      if(!sp) return '';
                      sp.scrollIntoView({block:'center'});
                      const rg = document.createRange(); rg.selectNodeContents(sp);
                      const s = window.getSelection(); s.removeAllRanges(); s.addRange(rg);
                      const r = sp.getBoundingClientRect();
                      window.__w5 = {x: r.left + 20, y: r.top + r.height / 2};
                      return s.toString().trim();
                    }""")
                    x0 = page.evaluate("window.__w5 && window.__w5.x") if sel_text else None
                    y0 = page.evaluate("window.__w5 && window.__w5.y") if sel_text else None
                    menu = []
                    if x0 is not None:
                        clear_overlay(page)
                        # 先真右键（选区还在）：菜单必须弹出来
                        page.mouse.click(x0, y0, button="right")
                        time.sleep(0.5)
                        menu = page.evaluate(
                            "[...document.querySelectorAll('.note-menu button')].map(b=>b.textContent)")
                        # 关掉菜单，重新造一次选区，再「只松手」：不许弹
                        page.evaluate("document.querySelectorAll('.note-menu').forEach(e=>e.remove())")
                        page.evaluate("""() => {
                          const sp = [...document.querySelectorAll('#pdftext span')]
                            .filter(s => s.getBoundingClientRect().width > 80)
                            .sort((a,b)=>b.textContent.length-a.textContent.length)[0];
                          const rg = document.createRange(); rg.selectNodeContents(sp);
                          const s = window.getSelection(); s.removeAllRanges(); s.addRange(rg);
                        }""")
                        page.dispatch_event("#pdftext", "mouseup",
                                            {"clientX": x0, "clientY": y0, "button": 0, "bubbles": True})
                        time.sleep(0.4)
                    after_up = page.evaluate("document.querySelectorAll('.note-menu').length")
                    if x0 is None:
                        skip("W5 右键菜单", "页面上没有足够宽的文字段，菜单没法判")
                    elif not sel_text:
                        skip("W5 右键菜单", "没造出选区，菜单没法判")
                    elif after_up:
                        bad("W5 右键菜单", "只松手就弹了 %d 个菜单" % after_up)
                    elif len(menu) >= 2 and any("翻译" in m for m in menu) and any("记" in m for m in menu):
                        ok("W5 右键菜单", "选完松手不弹；右键弹出 %r（选中 %r）" % (menu, sel_text[:10]))
                    else:
                        bad("W5 右键菜单", "右键后菜单不对：%r" % (menu,))
                except Exception as e:  # noqa: BLE001
                    bad("W5 右键菜单", "没验成：%r" % (e,))

            # ---- W7 黑框兜底：relayout 不改变窗口、背景不透明 ----
            # 说明（2026-11-22）：用户那块「下半截黑」在本机复现不出来——这台机器的 WebView2 是
            #   无窗口（合成）模式，EnumChildWindows 只有一个 0×0 的 Chrome_WidgetWin_0，
            #   没有可重设尺寸的子窗口（缩它画面一点不变）。所以 W7 只钉住两条能钉的事实：
            #   ① relayout() 是幂等的（调用前后窗口矩形不变、画面不变），不会把界面整坏；
            #   ② html/body 背景不透明——合成表面就算没跟上，露出来的也是界面底色而不是纯黑。
            if opened:
                try:
                    page.click("a[data-page='read']")
                    page.wait_for_function(
                        "document.querySelectorAll('#pdftext span').length > 3", timeout=30000)
                    time.sleep(0.8)
                    page.evaluate("window.pywebview.api.relayout()")   # 预热：先出一遍冷却期，再量
                    time.sleep(0.8)
                    img0 = snap(hwnd)
                    r0 = rect_of(hwnd)
                    res = page.evaluate("window.pywebview.api.relayout()")
                    time.sleep(1.0)
                    img1 = snap(hwnd)
                    r1 = rect_of(hwnd)
                    bg = page.evaluate(
                        "getComputedStyle(document.documentElement).backgroundColor")
                    drift = max(abs(r1[i] - r0[i]) for i in range(4))
                    vis = diff_ratio(img0, img1)
                    opaque = bool(bg) and bg not in ("transparent", "rgba(0, 0, 0, 0)")
                    if (res or {}).get("skipped"):
                        # 被冷却挡掉就等于什么都没做：量了个空，不能算绿
                        bad("W7 黑框兜底", "relayout() 被冷却挡掉（%r）：这一项等于没查" % (res,))
                    elif not (res or {}).get("ok"):
                        bad("W7 黑框兜底", "relayout() 返回 %r" % (res,))
                    elif drift > 1 or vis > 0.02:
                        bad("W7 黑框兜底", "relayout() 动了窗口/画面：矩形漂 %dpx、画面差 %.0f%%"
                            % (drift, vis * 100))
                    elif not opaque:
                        bad("W7 黑框兜底", "html 背景是 %r：合成表面没跟上时会露出纯黑" % (bg,))
                    else:
                        ok("W7 黑框兜底", "relayout() 幂等（矩形漂 %dpx、画面差 %.1f%%），html 底色 %s"
                           % (drift, vis * 100, bg))
                except Exception as e:  # noqa: BLE001
                    bad("W7 黑框兜底", "没验成：%r" % (e,))

            # ---- W8 全屏后按 Esc 能退出 ----
            if opened:
                try:
                    # WebView2 偶尔把 requestFullscreen 当「没有用户手势」拒掉（2026-11-23 见过两次，
                    # 机上还开着另一个实例时更容易）：先把页面提到前台再点，还不行就再点一次；
                    # 两次都进不去才算「没验」，不许把没查当成通过。
                    try: page.bring_to_front()
                    except Exception: pass
                    page.click("#btnFs")
                    time.sleep(1.0)
                    was = page.evaluate("!!document.fullscreenElement")
                    if not was:
                        page.click("#btnFs")
                        time.sleep(1.0)
                        was = page.evaluate("!!document.fullscreenElement")
                    page.keyboard.press("Escape")
                    time.sleep(1.2)
                    now_fs = page.evaluate("!!document.fullscreenElement")
                    card_fs = page.evaluate(
                        "!!document.querySelector('#page-read .read-card.fs')")
                    tbar = page.evaluate(
                        "!!(document.querySelector('#tbar')||{}).offsetParent")
                    if not was:
                        skip("W8 Esc 退出全屏", "全屏没进去（requestFullscreen 被拒），没敢判")
                    elif now_fs or card_fs or not tbar:
                        bad("W8 Esc 退出全屏", "按 Esc 后 fullscreenElement=%r 卡片fs=%r 标题条=%r"
                            % (now_fs, card_fs, tbar))
                    else:
                        ok("W8 Esc 退出全屏", "Esc 之后全屏元素清掉、标题条回来")
                except Exception as e:  # noqa: BLE001
                    bad("W8 Esc 退出全屏", "没验成：%r" % (e,))

            # ---- W9 记笔记：一个框（灰底只读引用 + 输入），侧栏只留列表 ----
            if opened:
                try:
                    page.click("a[data-page='read']")
                    page.wait_for_function(
                        "document.querySelectorAll('#pdftext span').length > 3", timeout=30000)
                    page.evaluate("""() => {
                      const sp = [...document.querySelectorAll('#pdftext span')]
                        .filter(s => s.getBoundingClientRect().width > 80)[0];
                      sp.scrollIntoView({block:'center'});
                      const rg = document.createRange(); rg.selectNodeContents(sp);
                      const s = window.getSelection(); s.removeAllRanges(); s.addRange(rg);
                      const r = sp.getBoundingClientRect();
                      window.__w9 = {x: r.left + 20, y: r.top + r.height / 2};
                    }""")
                    pt = page.evaluate("window.__w9")
                    page.mouse.click(pt["x"], pt["y"], button="right")
                    time.sleep(0.5)
                    page.click(".note-menu button:nth-child(2)")   # 记笔记（引用这段原文）
                    time.sleep(0.8)
                    info = page.evaluate("""() => {
                      const comp = document.querySelector('#noteCompose');
                      const list = document.querySelector('#noteList');
                      const q = document.querySelector('#npQuote');
                      const cs = q ? getComputedStyle(q) : null;
                      return {inSide: !!comp && !comp.hidden, listHidden: !!list && list.hidden,
                              textareas: comp ? comp.querySelectorAll('textarea').length : -1,
                              quoteLen: q ? q.textContent.trim().length : -1,
                              quoteColor: cs ? cs.color : '',
                              editable: q ? (q.isContentEditable || q.tagName === 'TEXTAREA' || q.tagName === 'INPUT') : true,
                              hasDraft: !!document.querySelector('#nDraft'),
                              pageNote: !!document.querySelector('#page-note')};
                    }""")
                    page.fill("#npText", "W9 由自测写入的一条笔记")
                    page.click("#npSave")
                    time.sleep(1.2)
                    after = page.evaluate("""() => ({
                      backList: !document.querySelector('#noteList').hidden,
                      count: document.querySelector('#nCount').textContent,
                      items: document.querySelectorAll('#nlist .nitem').length,
                      quotes: document.querySelectorAll('#nlist .nq').length,
                      self: document.querySelectorAll('#nlist .nitem.self').length,
                      draft: !!document.querySelector('#nDraft')
                    })""")
                    if not info["inSide"] or not info["listHidden"]:
                        bad("W9 记笔记单框", "点「记笔记」没有把侧栏切到写作页：%r" % (info,))
                    elif info["pageNote"]:
                        bad("W9 记笔记单框", "还留着整页 #page-note（用户要求就在侧栏里）")
                    elif info["textareas"] != 1:
                        bad("W9 记笔记单框", "写作页里有 %d 个输入框（应该只有 1 个）" % (info["textareas"],))
                    elif info["quoteLen"] < 4:
                        bad("W9 记笔记单框", "引用区是空的")
                    elif info["editable"]:
                        bad("W9 记笔记单框", "引用区可编辑（必须只读）")
                    elif info["hasDraft"]:
                        bad("W9 记笔记单框", "侧栏还留着 #nDraft 写入框")
                    elif not after["backList"] or after["items"] < 1 or after["quotes"] < 1:
                        bad("W9 记笔记单框", "保存后没回列表 / 列表没出现带引用的笔记：%r" % (after,))
                    else:
                        ok("W9 记笔记单框", "侧栏写作页：引用 %d 字、颜色 %s、只读；保存后回列表 %s 条（带引用 %s 条，自写 %s 条）"
                           % (info["quoteLen"], info["quoteColor"], after["count"], after["quotes"], after["self"]))
                except Exception as e:  # noqa: BLE001
                    bad("W9 记笔记单框", "没验成：%r" % (e,))

            # ---- W14 正常记笔记（没引用）不出灰框 ----
            # 2026-11-23 用户：「如果正常记笔记（就是没有引用的情况下）就不用灰字」。
            # 所以：没选中文字时点「记笔记」，灰框整块不出现（连占位也没有）；
            # 有选中时灰框回来，引用就是选中的那段。
            if opened:
                try:
                    page.click("a[data-page='read']")
                    page.click("#tabNotes")
                    time.sleep(0.4)
                    page.evaluate("""() => {
                      const b = document.getElementById('npBack');
                      if(b && b.offsetParent) b.click();          // 万一还停在写作页，先回列表
                      const s = window.getSelection(); if(s) s.removeAllRanges();
                      document.getElementById('btnNotePage').click();
                    }""")
                    time.sleep(0.7)
                    n0 = page.evaluate("""() => {
                      const w = document.querySelector('#noteCompose .note-quote');
                      const ta = document.querySelector('#npText');
                      const cs = ta ? getComputedStyle(ta) : null;
                      return {display: w ? getComputedStyle(w).display : '',
                              mt: cs ? cs.marginTop : '',
                              inCompose: !document.querySelector('#noteCompose').hidden};
                    }""")
                    # 写的时候列表是藏着的，#btnNotePage 点不到——先选中，再用 JS 触发那次点击
                    page.evaluate("""() => {
                      const sp = [...document.querySelectorAll('#pdftext span')]
                        .filter(s => s.getBoundingClientRect().width > 80)[0];
                      const rg = document.createRange(); rg.selectNodeContents(sp);
                      const s = window.getSelection(); s.removeAllRanges(); s.addRange(rg);
                      document.getElementById('btnNotePage').click();
                    }""")
                    time.sleep(0.7)
                    n1 = page.evaluate("""() => {
                      const w = document.querySelector('#noteCompose .note-quote');
                      const q = document.querySelector('#npQuote');
                      return {display: w ? getComputedStyle(w).display : '',
                              len: q ? q.textContent.trim().length : -1};
                    }""")
                    if not n0["inCompose"]:
                        bad("W14 无引用不出灰框", "点「记笔记」没进写作页：%r" % (n0,))
                    elif n0["display"] != "none":
                        bad("W14 无引用不出灰框", "没选中文字时灰框还在（display=%r）" % (n0["display"],))
                    elif n0["mt"] not in ("0px", "0"):
                        bad("W14 无引用不出灰框", "灰框藏了但输入框还留着上边距 %r" % (n0["mt"],))
                    elif n1["display"] == "none" or n1["len"] < 4:
                        bad("W14 无引用不出灰框", "有选中时灰框/引用没回来：%r" % (n1,))
                    else:
                        ok("W14 无引用不出灰框", "没选中时灰框 display=none、输入框贴顶；选中后灰框回来（引用 %d 字）"
                           % n1["len"])
                except Exception as e:  # noqa: BLE001
                    bad("W14 无引用不出灰框", "没验成：%r" % (e,))

            # ---- W15 笔记颜色 + PDF 引用高亮 ----
            # 2026-11-23 用户：「指针放上去那个笔记之后要看到引用的那里（如果有引用的话），
            #   那一块地方就会高亮，点击一下就常驻高亮；右键那个笔记可以选择颜色什么的
            #   （同时也会改变高亮的颜色和那个笔记的标签颜色）」。
            if opened:
                try:
                    page.evaluate("() => { const b=document.getElementById('npBack'); if(b && b.offsetParent) b.click(); }")
                    page.click("a[data-page='read']")
                    page.wait_for_function(
                        "document.querySelectorAll('#pdftext span').length > 3", timeout=30000)
                    page.evaluate("""() => {
                      const sp = [...document.querySelectorAll('#pdftext span')]
                        .filter(s => (s.textContent||'').trim().length > 12)[0];
                      const rg = document.createRange(); rg.selectNodeContents(sp);
                      const s = window.getSelection(); s.removeAllRanges(); s.addRange(rg);
                      document.getElementById('btnNotePage').click();
                    }""")
                    time.sleep(0.8)
                    page.fill("#npText", "W15 高亮测试")
                    page.click("#npSave")
                    time.sleep(1.2)
                    page.click("#tabNotes")
                    time.sleep(0.4)
                    page.hover("#nlist .nitem:last-child")      # 悬停：PDF 上应亮起来
                    time.sleep(0.6)
                    hov = page.evaluate("document.querySelectorAll('#pdfhl .hl').length")
                    page.click("#nlist .nitem:last-child")      # 点一下：常驻
                    time.sleep(0.9)
                    pin = page.evaluate("""() => ({
                      hl: document.querySelectorAll('#pdfhl .hl.pin').length,
                      item: document.querySelectorAll('#nlist .nitem.pin').length})""")
                    page.click("#nlist .nitem:last-child", button="right")
                    time.sleep(0.6)
                    dots = page.evaluate("document.querySelectorAll('.note-menu .nc-dot').length")
                    page.click(".note-menu .nc-dot[data-nc='blue']")
                    time.sleep(1.1)
                    col = page.evaluate("""() => {
                      const it = [...document.querySelectorAll('#nlist .nitem')].pop();
                      const hl = document.querySelector('#pdfhl .hl');
                      const cs = it ? getComputedStyle(it) : null;
                      return {nc: cs ? cs.getPropertyValue('--nc').trim() : '',
                              left: cs ? cs.borderLeftColor : '',
                              fill: hl ? getComputedStyle(hl).getPropertyValue('--hl').trim() : '',
                              n: document.querySelectorAll('#pdfhl .hl').length};
                    }""")
                    if hov < 1:
                        bad("W15 笔记高亮", "悬停那条笔记，PDF 上没有出现高亮块（%d 块）" % hov)
                    elif pin["hl"] < 1 or pin["item"] != 1:
                        bad("W15 笔记高亮", "点了没有常驻（高亮 %r / 笔记 %r）" % (pin["hl"], pin["item"]))
                    elif dots != 5:
                        bad("W15 笔记高亮", "右键菜单里颜色点有 %d 个（应为 5）" % dots)
                    elif "59, 110, 165" not in col["fill"] and "59,110,165" not in col["fill"]:
                        bad("W15 笔记高亮", "选了蓝色，PDF 高亮没跟着变：%r" % (col,))
                    elif col["nc"].lower() != "#3b6ea5":
                        bad("W15 笔记高亮", "选了蓝色，笔记那条的 --nc 还是 %r" % (col["nc"],))
                    else:
                        ok("W15 笔记高亮", "悬停亮 %d 块、点击常驻 %d 块、右键 5 色；换蓝后笔记 --nc=%s、高亮=%s"
                           % (hov, pin["hl"], col["nc"], col["fill"]))
                except Exception as e:  # noqa: BLE001
                    bad("W15 笔记高亮", "没验成：%r" % (e,))

            # ---- W16 点空白处取消选中 ----
            if opened:
                try:
                    page.evaluate("""() => {
                      const sp = [...document.querySelectorAll('#pdftext span')][2];
                      const rg = document.createRange(); rg.selectNodeContents(sp);
                      const s = window.getSelection(); s.removeAllRanges(); s.addRange(rg);
                    }""")
                    before = page.evaluate("String(window.getSelection())")
                    pt = page.evaluate("""() => {
                      const r = document.getElementById('readerBox').getBoundingClientRect();
                      return {x: r.left + 8, y: r.top + 8};
                    }""")
                    page.mouse.click(pt["x"], pt["y"])
                    time.sleep(0.5)
                    after = page.evaluate("String(window.getSelection())")
                    if len(before.strip()) < 2:
                        skip("W16 点空白取消选中", "没能先造出选区（%r），没敢判" % (before[:20],))
                    elif after.strip():
                        bad("W16 点空白取消选中", "点了空白处选区还在：%r" % (after[:30],))
                    else:
                        ok("W16 点空白取消选中", "选中 %d 字 → 点空白 → 选区清空" % len(before.strip()))
                except Exception as e:  # noqa: BLE001
                    bad("W16 点空白取消选中", "没验成：%r" % (e,))

            # ---- W17 排版不挤：讲次芯片单行、笔记条目不被压扁 ----
            if opened:
                try:
                    page.click("a[data-page='generate']")
                    page.wait_for_selector("#courseSel", timeout=15000)
                    page.select_option("#courseSel", "TDEMO")
                    time.sleep(0.6)
                    # 一次量完（芯片 + 照用户图1 造的那个）：分两次 eval 时页面可能已经切到「阅读」，
                    #   #lessonPick 变成 display:none，量出来全是 0——这样的 0 不能算绿。
                    meas = page.evaluate("""() => {
                      const box = document.getElementById('lessonPick');
                      if(!box) return null;
                      const h = el => el ? Math.round(el.getBoundingClientRect().height) : 0;
                      const chips = [...box.querySelectorAll('[data-lsn]')].map(b => {
                        const st = b.querySelector('.stub'), no = b.querySelector('.no');
                        return {s: h(st), n: h(no), w: Math.round(b.getBoundingClientRect().width),
                                shrink: st ? getComputedStyle(st).flexShrink : 'x'};
                      });
                      const b2 = document.createElement('button');
                      b2.setAttribute('data-lsn','W17STUB');
                      b2.innerHTML = '<span class="ttl">Lecture 6 Human anatomy and physiology (3)</span>' +
                                     '<span class="stub">占位</span><span class="no">T06-2</span>';
                      box.appendChild(b2);
                      const m = s => { const e = b2.querySelector(s); const r = e.getBoundingClientRect();
                                       return {h: Math.round(r.height), w: Math.round(r.width)}; };
                      const stub = {stub: m('.stub'), no: m('.no'),
                                    chip: Math.round(b2.getBoundingClientRect().width)};
                      b2.remove();
                      return {chips: chips, stubChip: stub};
                    }""")
                    chips = (meas or {}).get("chips") or []
                    stub_chip = (meas or {}).get("stubChip")
                    page.click("a[data-page='read']")
                    time.sleep(0.8)
                    page.click("#tabNotes")
                    time.sleep(0.4)
                    items = page.evaluate("""() => {
                      const list = document.getElementById('nlist');
                      return {overflow: list ? list.scrollWidth - list.clientWidth : 0,
                        rows: [...document.querySelectorAll('#nlist .nitem')].map(el => {
                          const q = el.querySelector('.nq');
                          return {h: Math.round(el.getBoundingClientRect().height),
                                  q: q ? Math.round(q.getBoundingClientRect().height) : 0,
                                  shrink: getComputedStyle(el).flexShrink};
                        })};
                    }""")
                    nlist_ov = items.get("overflow", 0) if isinstance(items, dict) else 0
                    items = (items.get("rows") or []) if isinstance(items, dict) else items
                    tall = [c for c in chips if c["s"] > 18 or c["n"] > 18 or c["w"] > 344]
                    squash = [it for it in items if it["q"] and it["h"] + 1 < it["q"]]
                    badshrink = [it for it in items if it["shrink"] != "0"]
                    if not stub_chip or stub_chip["chip"] == 0:
                        skip("W17 排版不挤", "造出来的芯片量到 0（没布局），这一项没查到")
                    elif (stub_chip["stub"]["h"] > 18 or stub_chip["no"]["h"] > 18
                                      or stub_chip["chip"] > 344):
                        bad("W17 排版不挤", "照用户图1 造的芯片还是挤：「占位」%r、讲号 %r、宽 %r"
                            % (stub_chip["stub"], stub_chip["no"], stub_chip["chip"]))
                    elif not chips:
                        skip("W17 排版不挤", "生成页没有讲次芯片，没敢判")
                    elif nlist_ov > 1:
                        bad("W17 排版不挤", "笔记列表横向溢出了 %dpx（底下会冒一条横向滚动条）" % nlist_ov)
                    elif tall:
                        bad("W17 排版不挤", "芯片里还有被挤的家伙：%r" % (tall,))
                    elif badshrink:
                        bad("W17 排版不挤", "笔记条目还允许被压缩（flex-shrink=%r）" % (badshrink[0]["shrink"],))
                    elif squash:
                        bad("W17 排版不挤", "笔记被压扁了：条目 %dpx、里面的引用块 %dpx"
                            % (squash[0]["h"], squash[0]["q"]))
                    else:
                        ok("W17 排版不挤",
                           "%d 个真芯片单行（讲号 %dpx、最宽 %dpx）；照用户图1 造的芯片宽 %dpx、"
                           "「占位」%d×%dpx、讲号 %d×%dpx；%d 条笔记都没被压扁"
                           % (len(chips), max([c["n"] for c in chips] or [0]),
                              max([c["w"] for c in chips] or [0]), stub_chip["chip"],
                              stub_chip["stub"]["w"], stub_chip["stub"]["h"],
                              stub_chip["no"]["w"], stub_chip["no"]["h"], len(items)))
                except Exception as e:  # noqa: BLE001
                    bad("W17 排版不挤", "没验成：%r" % (e,))

            # ---- W10 翻译：两个框 + 中间 ↑↓ ----
            if opened:
                try:
                    page.click("a[data-page='read']")
                    page.click("#tabTrans")
                    time.sleep(0.5)
                    t0 = page.evaluate("""() => {
                      const r = s => { const e = document.querySelector(s);
                        return e ? e.getBoundingClientRect() : null; };
                      const src = r('#trSrc'), dir = r('.tr-dir'), out = r('#trOut'), go = r('#trGo');
                      return {from: (document.querySelector('#trFrom')||{}).textContent,
                        to: (document.querySelector('#trTo')||{}).textContent,
                        swap: !!document.querySelector('#trSwap'),
                        boxes: document.querySelectorAll('#sideTrans textarea').length,
                        noteBtn: !!document.querySelector('#trNote'),
                        outEmpty: ((document.querySelector('#trOut')||{}).className || '').indexOf('empty') >= 0,
                        // 2026-11-23 用户：方向切换要夹在两个框中间；翻译按钮别夹在中间
                        geo: src && dir && out && go ? {
                          srcB: Math.round(src.bottom), dirT: Math.round(dir.top),
                          dirB: Math.round(dir.bottom), outT: Math.round(out.top),
                          goB: Math.round(go.bottom), srcT: Math.round(src.top)} : null};
                    }""")
                    page.click("#trSwap")
                    time.sleep(0.4)
                    t1 = page.evaluate("""() => ({
                      from: (document.querySelector('#trFrom')||{}).textContent,
                      to: (document.querySelector('#trTo')||{}).textContent,
                      ph: (document.querySelector('#trSrc')||{}).placeholder || ''
                    })""")
                    page.fill("#trSrc", "测试输入")
                    kept = page.evaluate("document.querySelector('#trSrc').value")
                    geo = t0.get("geo") or {}
                    if not t0["swap"] or t0["boxes"] != 1:
                        bad("W10 翻译两框", "结构不对：swap=%r 文本框=%d" % (t0["swap"], t0["boxes"]))
                    elif not geo:
                        bad("W10 翻译两框", "量不到输入框 / 方向行 / 输出框的位置")
                    elif not (geo["dirT"] >= geo["srcB"] - 1 and geo["outT"] >= geo["dirB"] - 1):
                        bad("W10 翻译两框", "方向切换不在两个框中间：输入底 %d / 方向 %d-%d / 输出顶 %d"
                            % (geo["srcB"], geo["dirT"], geo["dirB"], geo["outT"]))
                    elif geo["goB"] > geo["srcT"]:
                        bad("W10 翻译两框", "翻译按钮还夹在两个框之间（按钮底 %d / 输入顶 %d）"
                            % (geo["goB"], geo["srcT"]))
                    elif t0["from"] == t1["from"] or t0["to"] == t1["to"]:
                        bad("W10 翻译两框", "点 ↑↓ 方向没换：%r → %r" % (t0, t1))
                    elif t0["noteBtn"] or not t0["outEmpty"]:
                        bad("W10 翻译两框", "还没译文就出现了「引用翻译记成笔记」")
                    elif kept != "测试输入":
                        bad("W10 翻译两框", "上面那个框输入不进去：%r" % (kept,))
                    else:
                        ok("W10 翻译两框",
                           "方向 %s→%s 可交换（%d-%dpx 夹在输入框底 %d 与输出框顶 %d 之间）；"
                           "翻译按钮在标题行（底 %d < 输入顶 %d）；上面可输入；译文未出时不显示「引用翻译记成笔记」"
                           % (t0["from"], t0["to"], geo["dirT"], geo["dirB"], geo["srcB"],
                              geo["outT"], geo["goB"], geo["srcT"]))
                except Exception as e:  # noqa: BLE001
                    bad("W10 翻译两框", "没验成：%r" % (e,))

            # ---- W11 拖选：起点在按下的地方、松手不掉 ----
            if opened:
                try:
                    open_drawer(page, "TDEMO")
                    open_reader_from_drawer(page)
                    time.sleep(2.0)      # 等排版那几次重排落地（重排会把文字层重建）
                    # 用页面内的 PointerEvent 直接走我们那套 handler：判的是「起点在按下的地方、
                    #   松手保留」这两条契约。真鼠标在 CDP 下时序不稳（文字层会被重排重建），
                    #   但鼠标最终走的就是同一组 pointer 事件。
                    res = page.evaluate("""() => {
                      const spans = [...document.querySelectorAll('#pdftext span')]
                        .filter(s => s.getBoundingClientRect().width > 80);
                      const sp = spans[0];
                      if (!sp) return {miss: 'no span'};
                      sp.scrollIntoView({block:'center'});
                      const r = sp.getBoundingClientRect();
                      const box = document.getElementById('readerBox');
                      const fire = (type, x, y, buttons) => {
                        const ev = new PointerEvent(type, {clientX: x, clientY: y, button: 0,
                          buttons: buttons, bubbles: true, cancelable: true, pointerId: 1});
                        const el = (type === 'pointerdown') ? document.elementFromPoint(x, y) : box;
                        el.dispatchEvent(ev);
                        return ev.defaultPrevented;
                      };
                      const x0 = r.left + 20, y0 = r.top + r.height / 2;
                      const accepted = fire('pointerdown', x0, y0, 1);
                      const x1 = x0 + Math.min(70, r.width - 30);
                      fire('pointermove', x1, y0, 1);
                      const sel = window.getSelection();
                      const mid = {t: sel.toString(), a: sel.anchorOffset, c: sel.isCollapsed};
                      fire('pointerup', x1, y0, 0);
                      const after = {t: sel.toString(), c: sel.isCollapsed};
                      // 反方向再来一次：从右往左
                      fire('pointerdown', x1, y0, 1);
                      fire('pointermove', x0, y0, 1);
                      const rev = {t: sel.toString(), a: sel.anchorOffset,
                                   f: sel.focusOffset, c: sel.isCollapsed};
                      fire('pointerup', x0, y0, 0);
                      return {accepted: accepted, mid: mid, after: after, rev: rev};
                    }""")
                    if res.get("miss"):
                        skip("W11 拖选", "页面上没有够宽的文字段")
                    elif not res["accepted"]:
                        bad("W11 拖选", "pointerdown 没被我们接管（浏览器会自己选，方向会乱）")
                    elif res["mid"]["c"] or len(res["mid"]["t"].strip()) < 2:
                        bad("W11 拖选", "拖的时候没选中字：%r" % (res["mid"],))
                    elif res["mid"]["a"] <= 0:
                        bad("W11 拖选", "选区起点不在按下的地方（anchorOffset=%d）" % (res["mid"]["a"],))
                    elif res["after"]["c"] or len(res["after"]["t"].strip()) < 2:
                        bad("W11 拖选", "一松手选区就没了：%r → %r" % (res["mid"], res["after"]))
                    elif res["rev"]["c"] or len(res["rev"]["t"].strip()) < 2 \
                            or res["rev"]["a"] <= res["rev"]["f"]:
                        bad("W11 拖选", "反方向（右→左）选区不对（anchor 应在右边）：%r" % (res["rev"],))
                    else:
                        ok("W11 拖选", "起点在按下处（anchor=%d）、松手保留、反向也对：%r / %r"
                           % (res["mid"]["a"], res["mid"]["t"][:10], res["rev"]["t"][:10]))
                except Exception as e:  # noqa: BLE001
                    bad("W11 拖选", "没验成：%r" % (e,))

            # ---- W12 滚动条槽固定：有没有滚动条，内容宽度都不变 ----
            try:
                page.click("a[data-page='generate']")
                time.sleep(0.6)
                m0 = page.evaluate("""() => {
                  const s = document.getElementById('appScroll');
                  return {cw: s.clientWidth, ow: s.offsetWidth, gutter: getComputedStyle(s).scrollbarGutter};
                }""")
                page.evaluate("""() => {
                  const d = document.createElement('div');
                  d.id = 'w12spacer'; d.style.height = '900px';
                  document.getElementById('appScroll').appendChild(d);
                }""")
                time.sleep(0.5)
                m1 = page.evaluate("""() => {
                  const s = document.getElementById('appScroll');
                  return {cw: s.clientWidth, ow: s.offsetWidth};
                }""")
                page.evaluate("() => { const d = document.getElementById('w12spacer'); if (d) d.remove(); }")
                time.sleep(0.4)
                d1 = abs(m1["cw"] - m0["cw"])
                if m0["gutter"] != "stable":
                    bad("W12 滚动条槽", "scrollbar-gutter=%r（应为 stable）" % (m0["gutter"],))
                elif d1 > 1:
                    bad("W12 滚动条槽", "出滚动条之后内容宽度变了 %dpx（会来回抖）" % d1)
                else:
                    ok("W12 滚动条槽", "滚动条出现前后内容宽度都是 %dpx（槽固定，不会抖）" % m0["cw"])
            except Exception as e:  # noqa: BLE001
                bad("W12 滚动条槽", "没验成：%r" % (e,))

            # ---- W13 不再自激：relayout 之后窗口尺寸不许反复来回 ----
            # 2026-11-23 用户：「依旧一直闪烁，无法选中，我电脑指针都在闪」。
            # 成因：relayout 为逼 WebView2 收 WM_SIZE 会 +1px 再改回，页面收到 resize 又调 relayout，
            #   成了每秒好几轮的自激循环（窗口一直在改尺寸 → 整页重排、PDF 重画、指针跟着闪）。
            # 这里数 4 秒里的 resize：前 2 秒最多 4 次（自己那一下的回声），后 2 秒必须 0 次。
            try:
                page.evaluate("""() => {
                  window.__rz = [];
                  if(!window.__rzHooked){
                    window.__rzHooked = 1;
                    window.addEventListener('resize', () => { window.__rz.push(Date.now()); });
                  }
                }""")
                page.evaluate("window.pywebview.api.relayout()")
                time.sleep(2.0)
                n1 = page.evaluate("window.__rz.length")
                time.sleep(2.0)
                n2 = page.evaluate("window.__rz.length")
                if n2 - n1 > 0:
                    bad("W13 不自激", "前 2 秒 resize %d 次、后 2 秒又 %d 次：relayout 在自激"
                        % (n1, n2 - n1))
                elif n1 > 4:
                    bad("W13 不自激", "2 秒内 resize %d 次（自己那一下最多 4 次）" % n1)
                else:
                    ok("W13 不自激", "relayout 之后 4 秒共 %d 次 resize，后 2 秒 0 次（不自激）" % n1)
            except Exception as e:  # noqa: BLE001
                bad("W13 不自激", "没验成：%r" % (e,))

            # ---- W6 真拖动（可选，会动鼠标）----
            if args.drag:
                try:
                    page.click("a[data-page='generate']")
                    time.sleep(0.4)
                    b, a = drag_test(hwnd)
                    moved = abs(a[0] - b[0]) + abs(a[1] - b[1])
                    if moved >= 40:
                        ok("W6 窗口拖动", "%r → %r（位移 %dpx）" % (b, a, moved))
                        ctypes.windll.user32.SetWindowPos(wt.HWND(hwnd), None, b[0], b[1],
                                                          b[2], b[3], 0x0004 | 0x0010)
                    else:
                        bad("W6 窗口拖动", "拖了 120px，位移只有 %dpx：%r → %r" % (moved, b, a))
                except Exception as e:  # noqa: BLE001
                    bad("W6 窗口拖动", "没拖成：%r" % (e,))
    finally:
        try:
            proc.terminate()
            proc.wait(timeout=10)
        except Exception:  # noqa: BLE001
            try:
                proc.kill()
            except Exception:  # noqa: BLE001
                pass
        log.close()
        if not args.keep:
            shutil.rmtree(str(home), ignore_errors=True)
        else:
            print("临时数据根保留：%s" % home)

    for line in GREEN:
        print("[通过] " + line)
    for line in YELLOW:
        print("[未验] " + line)
    for line in RED:
        print("[红]   " + line)
    print("结论：%d 绿 / %d 未验 / %d 红" % (len(GREEN), len(YELLOW), len(RED)))
    return 0 if not RED else 1


if __name__ == "__main__":
    sys.exit(main())
