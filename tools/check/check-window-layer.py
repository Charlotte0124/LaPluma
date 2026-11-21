# -*- coding: utf-8 -*-
r"""check-window-layer.py — 窗口/列表层的三条判据（2026-11-22）

为什么有这条：这一轮改的三件事都属于「静态看着对、真用起来错」那一类，各留一条可执行判据：

  1 文字层：必须用 pdf.js 官方 TextLayer（每段一个 div，left/top 按整页百分比、宽度 scaleX），
     容器必须给 --scale-factor，并把走的那条路记在 #pdftext.dataset.tl 上。
     以前是「按行合并成一个 span」，选中框和字对不齐——用户就是这么发现的。
  2 已成稿隐藏：后端 lesson_meta 必须**按磁盘事实**算出 done（原件在 + 成品在），
     生成列表滤掉这些讲；重做入口只在课件成品行的「重新生成」。
  4 滚动条槽固定：#appScroll 用 scrollbar-gutter:stable（不然「刚好过一屏」时界面上下抖、底边闪白条）
  3 干净启动器：F:/DSH/apps/羽毛笔 只能有一个纯 ASCII 的 .cmd，靠 %~dp0 + 通配符找
     .. 下的 LaPluma 的 .ps1；混进别的文件或中文内容，双击就会没反应。

真窗口里的量测不在这里（那要弹窗口、约 40 秒）：见 tools/check/check-window-real.py，
提交钩子只跑本文件的静态判据 + 一次真的 lesson_meta 计算。

用法：
    python tools/check/check-window-layer.py
    python tools/check/check-window-layer.py --selftest   # 逐条造坏，先证明会红

退出码：0 全绿；1 有红
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
LAUNCHER = os.path.join(os.path.dirname(ROOT), "羽毛笔")


def read(root, rel):
    with open(os.path.join(root, rel), encoding="utf-8") as f:
        return f.read()


def block(text, start, end):
    i = text.find(start)
    if i < 0:
        return ""
    j = text.find(end, i + len(start))
    return text[i:] if j < 0 else text[i:j]


def behavior_done(root):
    """真造一份「原件 + 成品」都在的课程，跑 lesson_meta：D01 必须 done=True、D02=False。

    只信磁盘事实：把 DEMO 拷进临时数据根，补一份原件、把 D01 的 orig 指过去；
    另一讲 D02 没原件，必须仍是 False。跑完删临时目录。
    """
    base = os.path.join(root, "_trash")
    os.makedirs(base, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="pluma-done-", dir=base)
    d = os.path.join(tmp, "data")
    try:
        shutil.copytree(os.path.join(root, "DEMO"), os.path.join(d, "TDEMO"))
        od = os.path.join(d, "TDEMO", "00_原件")
        os.makedirs(od, exist_ok=True)
        pdfs = [f for f in os.listdir(os.path.join(root, "DEMO", "01_讲义"))
                if f.lower().endswith(".pdf")]
        if not pdfs:
            return None, "DEMO 里没有成品 PDF，造不出样本"
        shutil.copyfile(os.path.join(root, "DEMO", "01_讲义", pdfs[0]),
                        os.path.join(od, "Sample 01.pdf"))
        py = os.path.join(d, "TDEMO", "_lessons", "D01.py")
        text = open(py, encoding="utf-8").read()
        text = text.replace("LESSON = {", 'LESSON = { "orig": "Sample 01",', 1)
        open(py, "w", encoding="utf-8", newline="").write(text)
        code = r"""
import importlib.util, json, os, sys
root, data = sys.argv[1], sys.argv[2]
sys.path.insert(0, root)
import paths
paths.DATA_ROOT = data
spec = importlib.util.spec_from_file_location("pluma_server_uut", os.path.join(root, "ui", "server.py"))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
meta = m.lesson_meta("TDEMO")
print(json.dumps({k: bool(v.get("done")) for k, v in meta.items()}, ensure_ascii=False))
"""
        env = dict(os.environ, PLUMA_HOME=os.path.join(tmp, "home"), PYTHONIOENCODING="utf-8")
        r = subprocess.run([sys.executable, "-X", "utf8", "-c", code, root, d],
                           cwd=root, env=env, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=90)
        if r.returncode != 0:
            return None, (r.stderr or r.stdout).strip()[-400:]
        lines = [x for x in (r.stdout or "").splitlines() if x.strip()]
        dataj = json.loads(lines[-1]) if lines else {}
        good = dataj.get("D01") is True and dataj.get("D02") is False
        return good, json.dumps(dataj, ensure_ascii=False)
    except Exception as e:  # noqa: BLE001
        return None, repr(e)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def launcher_rows(ldir):
    """干净启动器：只有一个纯 ASCII 的 .cmd，靠 %~dp0 + 通配符找 ../LaPluma 的 .ps1。"""
    if not os.path.isdir(ldir):
        return None, "目录不在：%s" % ldir
    files = sorted(f for f in os.listdir(ldir) if os.path.isfile(os.path.join(ldir, f)))
    if len(files) != 1:
        return False, "目录里应该只有启动器一个文件，实际 %d 个：%r" % (len(files), files)
    name = files[0]
    if not name.lower().endswith(".cmd"):
        return False, "唯一的文件不是 .cmd：%r" % (name,)
    raw = open(os.path.join(ldir, name), "rb").read()
    bad = [b for b in raw if b > 127]
    if bad:
        return False, "启动器里有 %d 个非 ASCII 字节（cmd.exe 会按 936 读成乱码）" % (len(bad),)
    text = raw.decode("ascii", "replace")
    if "%~dp0" not in text or "LaPluma" not in text:
        return False, "启动器没靠 %~dp0 去找 LaPluma 目录"
    if "-Windowed" not in text:
        return False, "启动器没带 -Windowed（会又弹出控制台黑框）"
    if ".ps1" not in text:
        return False, "启动器没按通配符找 .ps1（写死中文名会在 936 下变乱码）"
    return True, "%s（%d B，纯 ASCII）" % (name, len(raw))


def check(root, ldir=None):
    idx = read(root, IDX)
    srv = read(root, SRV)
    rows = []

    def add(no, name, ok, detail):
        rows.append((no, name, ok, detail))

    rtl = block(idx, "async function renderTextLayer(page, vp, lib)", "async function renderPdf()")
    add(1, "文字层官方 TextLayer", (
        "new lib.TextLayer(" in rtl
        and "textContentSource: tc" in rtl
        and "container: box" in rtl
        and "viewport: vp" in rtl
        and "setProperty('--scale-factor'" in rtl
        and "dataset.tl = 'official'" in rtl
        and "dataset.tl = 'fallback'" in rtl
    ), "官方 TextLayer + --scale-factor；走哪条路记在 dataset.tl（真窗口量测见 check-window-real.py）")

    lm = block(srv, "def lesson_meta(course: str)", "def ensure_body(")
    sync = block(idx, "function syncLessons()", "function syncLsnCnt()")
    # 成品行里的「重新生成」：直接看整份页面，免得被模板字符串里的反引号绊住
    files_ok = ('data-fregen="' in idx and "const lsnOf = nm =>" in idx
                and "function regenLesson(no, code)" in idx)
    ok_done, detail = behavior_done(root)
    add(2, "已成稿讲次隐藏", (
        '"done": bool(_stem' in lm and "orig_stems" in lm and "pdf_names" in lm
        and "const isDone = n =>" in sync and "REGEN.has(n)" in sync
        and "const shown = les.filter" in sync
        and files_ok
        and "REGEN.add(no)" in block(idx, "function regenLesson(no, code)", "function openDrawer")
        and "REGEN.delete(no)" in idx
        and ok_done is True
    ), detail or "lesson_meta 没跑通")

    add(4, "滚动条槽固定", (
        "scrollbar-gutter:stable" in idx
        and "body.win #appScroll{flex:1 1 auto" in idx
    ), "body.win #appScroll 必须 scrollbar-gutter:stable —— 内容是「刚好高过一屏」时，"
       "滚动条出现/消失会让内容宽度来回变，界面上下抖、底边白条闪（2026-11-22 用户图1）")

    if ldir is None:
        ldir = LAUNCHER
    ok_l, detail_l = launcher_rows(ldir)
    if ok_l is None:
        rows.append((3, "干净启动器", None, detail_l))
    else:
        add(3, "干净启动器", ok_l, detail_l)
    return rows


def main():
    if "--selftest" in sys.argv:
        return selftest()
    rows = check(ROOT)
    bad = 0
    for no, name, ok, detail in rows:
        tag = "绿" if ok else ("未验" if ok is None else "红")
        print("[%s] %d/4 %s —— %s" % (tag, no, name, detail))
        if ok is False:
            bad += 1
    print("结论：%d 绿 / %d 红" % (len([r for r in rows if r[2] is True]), bad))
    return 0 if bad == 0 else 1


def selftest():
    """临时副本逐条造坏：每条都必须变红，证明判据真的会失败。"""
    base = os.path.join(ROOT, "_trash")
    os.makedirs(base, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="pluma-window-layer-", dir=base)
    root = os.path.join(tmp, "repo")
    good_dir = os.path.join(tmp, "好启动器")
    bad_dir = os.path.join(tmp, "坏启动器")
    try:
        os.makedirs(os.path.join(root, "ui"))
        for rel in (IDX, SRV, "paths.py"):
            shutil.copyfile(os.path.join(ROOT, rel), os.path.join(root, rel))
        for d in (good_dir, bad_dir):
            os.makedirs(d)
        if os.path.isdir(LAUNCHER):
            name = [f for f in os.listdir(LAUNCHER) if f.lower().endswith(".cmd")][0]
            shutil.copyfile(os.path.join(LAUNCHER, name), os.path.join(good_dir, name))
            shutil.copyfile(os.path.join(LAUNCHER, name), os.path.join(bad_dir, name))
            open(os.path.join(bad_dir, "readme.txt"), "w").write("x")
        else:
            print("  [未验] 启动器目录不在，跳过第 3 条造坏")
        orig_idx = read(root, IDX)
        orig_srv = read(root, SRV)

        def reset():
            for rel, txt in ((IDX, orig_idx), (SRV, orig_srv)):
                with open(os.path.join(root, rel), "w", encoding="utf-8", newline="") as f:
                    f.write(txt)

        defects = [
            ("文字层退回按行合并", 1, IDX, "new lib.TextLayer(", "new lib.NoSuchLayer("),
            ("去掉 --scale-factor", 1, IDX, "box.style.setProperty('--scale-factor'", "box.style.setProperty('--x'"),
            ("done 固定为假", 2, SRV, '"done": bool(_stem', '"done": False and bool(_stem'),
            ("生成列表不过滤", 2, IDX, "const isDone = n =>", "const isDone = n => false &&"),
            ("重新生成入口拿掉", 2, IDX, "function regenLesson(no, code){", "function regenLessonX(no, code){"),
            ("滚动条槽去掉", 4, IDX, "scrollbar-gutter:stable", "scrollbar-gutter:auto"),
            ("启动器目录混进别的文件", 3, None, None, bad_dir),
        ]
        all_ok = True
        for label, no, rel, old, new in defects:
            reset()
            if rel is None:
                rows = check(root, new)
            else:
                p = os.path.join(root, rel)
                text = read(root, rel)
                if text.count(old) != 1:
                    print("  [红] %s：造坏锚点出现 %d 次" % (label, text.count(old)))
                    all_ok = False
                    continue
                with open(p, "w", encoding="utf-8", newline="") as f:
                    f.write(text.replace(old, new, 1))
                rows = check(root, good_dir)
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
