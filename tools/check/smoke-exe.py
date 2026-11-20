# -*- coding: utf-8 -*-
"""按键冒烟：拿**打包后的 exe**，在它自己的窗口里把能点的都点一遍，连跑三轮。

为什么这么测（用户 2026-11-21）：
  「我指的是这种方式测试（浏览器打开 127.0.0.1）有很多 BUG 都找不到，然后打包的时候就
   一大堆 BUG 出来了」「所以直接改用打包 APP 去测试吧，不然这种测试是无意义的」
  「完全测试我的 exe 冒烟三轮 全部按键功能测试」

口径：
  · 只测 dist\\LaPluma.exe；窗口是 WebView2 真窗口，不是浏览器
  · 干净环境：exe 复制到空目录 + 空 PLUMA_HOME（只放一把钥匙，好让「生成」能真出 PDF）
  · 每轮从 `page.reload()` 重新开始；同一个窗口连跑三轮（第二轮、第三轮才容易暴露状态残留）
  · 每个按键单独 try：一个红了不影响后面，最后一并报
  · **不点会卡住或毁数据的**：导入课件 / 选择文件夹（会弹系统对话框，阻塞）、删除（真删）、
    上线（会开局域网 + 防火墙）。这些单独列在「本轮跳过」里，不假装点过。

用法：
    python tools\\check\\smoke-exe.py                 # 三轮
    python tools\\check\\smoke-exe.py --rounds 1       # 一轮（改完快速回归）
    python tools\\check\\smoke-exe.py --keep          # 留临时目录

截图：_logs\\smoke-r<轮>-<序号>-<名字>.png（只在失败时留）
退出码：0 全绿；1 有红；2 没查（没有 exe / 缺 playwright）
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
EXE = ROOT / "dist" / "LaPluma.exe"
SHOTS = ROOT / "_logs"
CDP_WAIT = 90.0

SKIPPED = [
    ("导入课件", "会弹系统文件对话框，阻塞无头点击；由人工或 check-stub-guard 覆盖"),
    ("选择文件夹", "同上"),
    ("删除课程 / 删除讲次", "真删数据，不在冒烟里做"),
    ("一键上线", "会开局域网监听与防火墙提示，不在冒烟里做"),
    ("合订本生成", "要跑全部讲次，单轮几分钟；单本已覆盖打印链路"),
]


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def http_json(url: str, timeout: float = 5.0) -> tuple:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode("utf-8", "replace") or "{}")
    except Exception as e:  # noqa: BLE001
        return 0, {"error": repr(e)}


class App:
    def __init__(self) -> None:
        self.base = Path(tempfile.mkdtemp(prefix="pluma-smoke-"))
        self.app = self.base / "app"
        self.home = self.base / "home"
        self.tmp = self.base / "tmp"
        for d in (self.app, self.home, self.tmp):
            d.mkdir(parents=True, exist_ok=True)
        self.exe = self.app / EXE.name
        shutil.copy2(EXE, self.exe)
        key = Path(os.path.expanduser("~")) / ".pluma" / "api.json"
        if key.is_file():
            shutil.copy2(key, self.home / "api.json")   # 有钥匙才能测「真出 PDF」
        self.port = free_port()
        self.cdp = free_port()
        self.proc = None

    def start(self) -> bool:
        env = dict(os.environ)
        env.update({"PLUMA_HOME": str(self.home), "TEMP": str(self.tmp), "TMP": str(self.tmp),
                    "PLUMA_TEST_CDP": str(self.cdp)})
        env.pop("PLUMA_API_KEY", None)
        self.proc = subprocess.Popen(
            [str(self.exe), "--port", str(self.port)], cwd=str(self.app), env=env,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        t0 = time.time()
        while time.time() - t0 < CDP_WAIT:
            code, v = http_json("http://127.0.0.1:%d/json/version" % self.cdp, timeout=2)
            if code == 200 and v.get("Browser"):
                print("窗口与调试端口就绪：WebView2 %s（%.1f s）"
                      % (str(v.get("Browser"))[:40], time.time() - t0))
                return True
            if self.proc.poll() is not None:
                print("[红] exe 退出了，退出码 %s" % self.proc.returncode)
                return False
            time.sleep(0.8)
        print("[红] %.0f 秒内没等到调试端口" % CDP_WAIT)
        return False

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.terminate()
                self.proc.wait(timeout=8)
            except Exception:  # noqa: BLE001
                try:
                    self.proc.kill()
                except Exception:  # noqa: BLE001
                    pass

    def cleanup(self, keep: bool) -> None:
        self.stop()
        if keep:
            print("（留下临时目录：%s）" % self.base)
            return
        for _ in range(3):
            try:
                shutil.rmtree(self.base, ignore_errors=False)
                return
            except Exception:  # noqa: BLE001
                time.sleep(0.5)


def _txt(page, sel: str) -> str:
    try:
        return page.inner_text(sel, timeout=4000)
    except Exception:  # noqa: BLE001
        return ""


def _jsclick(page, sel: str) -> None:
    """按「功能」点，不按「命中判定」点：导航 / 全选这类按钮用 JS 触发 onclick。

    为什么不全用真点击：Playwright 的真点击要求元素在**视口内且没被遮住**，
    一旦上一步的遮罩还在做关闭动画就 20 秒超时——那是脚本的时序，不是软件的病。
    真窗口里「按钮有没有被盖住」由下面 _covered 单独判，别混为一谈。
    """
    ok = page.evaluate("""(sel) => { const el = document.querySelector(sel);
        if (!el) return false; el.click(); return true; }""", sel)
    if not ok:
        raise AssertionError("找不到可点的元素：%s" % sel)
    time.sleep(0.35)


def _covered(page, sel: str) -> str:
    """这个按钮在窗口里有没有被别的东西盖住（返回盖住它的元素，没被盖返回空串）。"""
    return page.evaluate("""(sel) => { const el = document.querySelector(sel);
        if (!el) return 'MISSING';
        const r = el.getBoundingClientRect();
        if (r.width <= 0 || r.height <= 0) return 'SIZE0';
        const hit = document.elementFromPoint(Math.round(r.left + r.width / 2),
                                              Math.round(r.top + r.height / 2));
        return (!hit || hit === el || el.contains(hit)) ? '' : (hit.id || hit.className || hit.tagName); }""", sel)


def _settle(page) -> None:
    """每个按键前先把浮层收干净，免得「上一步的遮罩还在」被当成软件故障。"""
    try:
        for _ in range(20):
            busy = page.evaluate(
                "() => !!document.querySelector('.veil.on, .veil.closing, .dveil.on, .drawer.on')")
            if not busy:
                return
            page.keyboard.press("Escape")
            time.sleep(0.15)
    except Exception:  # noqa: BLE001
        pass


def _pick_lesson(page) -> str:
    """挑一个还能进批次的讲次。上一轮生成完的讲次会被移出批次（v1.9.14 的既定行为），
    所以第二轮起不能还死等 D01——批次空了就返回空串，由调用方那句话来判断。"""
    chips = page.query_selector_all("#lessonPick [data-lsn]")
    chips = [c for c in chips if not c.get_attribute("disabled")]
    if not chips:
        return ""
    no = chips[0].get_attribute("data-lsn")
    chips[0].click()
    time.sleep(0.3)
    return no or ""


# ---------- 一轮里逐个按键 ----------
def actions(page, pdf: Path, appdir: Path) -> list:
    """返回 [(名字, 函数)]。函数抛异常 = 红。"""
    def nav_courses():
        _jsclick(page, "#nav a[data-page=courses]")
        page.wait_for_selector(".course", timeout=10000)

    def theme_toggle():
        before = page.evaluate("document.documentElement.getAttribute('data-theme') "
                               "|| document.body.getAttribute('data-theme') || ''")
        page.click("#btnTheme")
        time.sleep(0.5)
        after = page.evaluate("document.documentElement.getAttribute('data-theme') "
                              "|| document.body.getAttribute('data-theme') || ''")
        if before == after:
            raise AssertionError("主题没变（%r → %r）" % (before, after))
        page.click("#btnTheme")
        time.sleep(0.4)

    def drawer_open_close():
        page.click(".course")
        page.wait_for_selector(".drawer.on", timeout=10000)
        top = page.evaluate("() => Math.round(document.querySelector('.drawer.on')"
                            ".getBoundingClientRect().top)")
        bar = page.evaluate("() => { const t=document.getElementById('tbar');"
                            " return t ? Math.round(t.getBoundingClientRect().bottom) : 0; }")
        if top < bar:
            raise AssertionError("抽屉被顶栏压住：top=%s < 顶栏底 %s" % (top, bar))
        page.keyboard.press("Escape")
        time.sleep(0.5)

    def gen_page_and_pdf():
        _jsclick(page, "#nav a[data-page=generate]")
        page.wait_for_selector("#btnGen", timeout=12000)
        no = _pick_lesson(page)
        if not no:
            # 批次被上一轮生成空了：判「界面有没有说清楚」，而不是假装失败
            hint = _txt(page, "#genHint") or _txt(page, "body")
            if "批次" in hint or "已生成" in hint or "全部" in hint:
                return "批次已空（界面有说明）"
            raise AssertionError("批次里没有可生成的讲次，界面也没说明")
        before = {}
        for f in (appdir / "DEMO" / "01_讲义").glob("%s_*.pdf" % no):
            before[f.name] = f.stat().st_mtime
        page.click("#btnGen")
        for _ in range(150):
            time.sleep(1.0)
            for f in (appdir / "DEMO" / "01_讲义").glob("%s_*.pdf" % no):
                if f.stat().st_mtime > before.get(f.name, 0):
                    return
        raise AssertionError("点「开始生成」后没等到 %s 的 PDF" % no)

    def gen_switch_form():
        _jsclick(page, "#nav a[data-page=generate]")
        page.wait_for_selector("#btnGen", timeout=12000)
        page.click('#formOpts [data-form="book"]')
        time.sleep(0.4)
        page.click('#formOpts [data-form="single"]')
        time.sleep(0.3)

    def gen_switch_lang():
        page.click('#langOpts [data-lang="en"]')
        time.sleep(0.3)
        page.click('#langOpts [data-lang="zh"]')
        time.sleep(0.3)

    def gen_pick_all():
        cov = _covered(page, "#lsnAll")
        if cov in ("SIZE0", "MISSING"):
            # 批次空了以后这条工具条整个不显示——这是既定行为，不是被挡住
            if not page.evaluate("() => !!document.querySelector('#lessonPick [data-lsn]')"):
                return "批次已空（全选按钮不显示）"
        if cov:
            raise AssertionError("「全选」被 %s 盖住" % cov)
        _jsclick(page, "#lsnAll")
        time.sleep(0.5)
        # 选中态就是 chip 自己的 class="on"（不是 .lsn.on，别把判据写错）
        n = page.evaluate("() => document.querySelectorAll('#lessonPick [data-lsn].on').length")
        if n == 0:
            # 回合后半段批次会被生成空了：这时「全选」按钮该是禁用的，不是故障
            if page.evaluate("() => !!(document.getElementById('lsnAll')||{}).disabled"):
                return "批次已空（全选已禁用）"
            raise AssertionError("点了「全选」但一个讲次都没选中")
        _jsclick(page, "#lsnAll")          # 再点一次复原（不改用户的选择习惯）
        time.sleep(0.3)

    def settings_open_save():
        page.click("#btnSet")
        page.wait_for_selector("#sVer", timeout=10000)
        time.sleep(0.8)
        ver = _txt(page, "#sVer")
        upd = _txt(page, "#sUpd")
        if "本机 v" not in ver:
            raise AssertionError("设置页版本行不对：%r" % ver)
        if not (("仓库" in upd) or ("最新" in upd)):
            raise AssertionError("设置页更新行不对：%r" % upd)
        page.click("#sSave")
        # 保存后对话框必须自己关（第 1 轮实测有时不关，后面的按键就被它挡住）
        for _ in range(40):
            if not page.evaluate("() => !!document.querySelector('.veil.on, .veil.closing')"):
                return
            time.sleep(0.15)
        raise AssertionError("点「保存」后设置对话框没关")

    def tutorial_open_close():
        # 上一步保存后遮罩还在做关闭动画，直接点会被它挡住（实测 20 s 超时）——等它真的消失
        for _ in range(40):
            if not page.evaluate("() => !!document.querySelector('.veil.on, .veil.closing')"):
                break
            time.sleep(0.15)
        page.click("#btnSet")
        page.wait_for_selector("#sTut", timeout=8000)
        page.click("#sTut")
        time.sleep(0.8)
        page.keyboard.press("Escape")
        time.sleep(0.4)

    def host_page():
        cov = _covered(page, "#nav a[data-page=host]")
        if cov:
            raise AssertionError("「上线」导航被 %s 盖住" % cov)
        _jsclick(page, "#nav a[data-page=host]")
        time.sleep(0.8)
        n = page.evaluate("() => document.querySelectorAll('#nav a.on').length")
        if n == 0:
            raise AssertionError("上线页没有高亮导航项，可能没切过去")

    def read_page():
        # 没选过成品时点「阅读」是**有意不动**的：只弹一句「先到课程抽屉里点一份讲义」。
        # 判据按这个真实行为来：要么切过去，要么出现那句提示（两种都算对）。
        _jsclick(page, "#nav a[data-page=read]")
        time.sleep(0.8)
        switched = page.evaluate("() => !!document.querySelector('#nav a[data-page=read].on')")
        toast = _txt(page, "#toast")
        if not switched and "抽屉" not in toast:
            raise AssertionError("点「阅读」既没切页也没提示（toast=%r）" % toast[:40])
        return "切页" if switched else "提示：%s" % toast[:18]

    def reader_pdf():
        # 从课程抽屉里点一份成品进阅读（走界面自己的入口）
        _jsclick(page, "#nav a[data-page=courses]")
        page.wait_for_selector(".course", timeout=10000)
        page.click(".course")
        page.wait_for_selector(".drawer.on", timeout=10000)
        link = page.query_selector(".drawer a, .drawer button")
        if not link:
            raise AssertionError("抽屉里没有可点的成品行")
        link.click()
        time.sleep(2.0)
        page.keyboard.press("Escape")

    return [
        ("导航→课程", nav_courses),
        ("深色/浅色切换", theme_toggle),
        ("课程卡→抽屉开合", drawer_open_close),
        ("导航→生成", lambda: _jsclick(page, "#nav a[data-page=generate]")),
        ("成品形态（单本/合订本）", gen_switch_form),
        ("讲义语言（全中/全英）", gen_switch_lang),
        ("讲次全选", gen_pick_all),
        ("开始生成→出 PDF", lambda: gen_page_and_pdf()),
        ("设置→版本行→保存", settings_open_save),
        ("重看教学→关闭", tutorial_open_close),
        ("导航→上线", host_page),
        ("导航→阅读", read_page),
        ("抽屉成品→进阅读", reader_pdf),
    ]


def main(argv=None) -> int:
    for s in (sys.stdout, sys.stderr):
        if hasattr(s, "reconfigure"):
            s.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="打包件按键冒烟（真窗口）")
    ap.add_argument("--rounds", type=int, default=3)
    ap.add_argument("--keep", action="store_true")
    a = ap.parse_args(argv)
    if not EXE.is_file():
        print("[黄] 没有 dist\\LaPluma.exe")
        return 2
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:  # noqa: BLE001
        print("[红] 装不上 playwright：%r" % (e,))
        return 2

    print("被测：%s（%.1f MB · %s）"
          % (EXE, EXE.stat().st_size / 1048576,
             time.strftime("%Y-%m-%d %H:%M", time.localtime(EXE.stat().st_mtime))))
    SHOTS.mkdir(parents=True, exist_ok=True)
    app = App()
    rows = []
    try:
        if not app.start():
            return 1
        with sync_playwright() as p:
            br = p.chromium.connect_over_cdp("http://127.0.0.1:%d" % app.cdp)
            ctx = br.contexts[0] if br.contexts else br.new_context()
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.set_default_timeout(20000)
            pdf = app.app / "DEMO" / "01_讲义" / "D01_一份讲义是怎么出来的_讲义.pdf"

            for rnd in range(1, a.rounds + 1):
                page.goto("http://127.0.0.1:%d/?win=1" % app.port, wait_until="load")
                time.sleep(1.5)
                print("\n—— 第 %d 轮 ——" % rnd)
                for i, (name, fn) in enumerate(actions(page, pdf, app.app), 1):
                    t0 = time.time()
                    try:
                        _settle(page)      # 上一步的遮罩别把这一步挡住
                        out = fn()
                        rows.append((rnd, name, True, "%.1fs" % (time.time() - t0)))
                        print("  [绿] %-22s %.1fs %s" % (name, time.time() - t0, out or ""))
                    except Exception as e:  # noqa: BLE001
                        ms = str(e)[:120].replace("\n", " ")
                        rows.append((rnd, name, False, ms))
                        print("  [红] %-22s %s" % (name, ms))
                        try:
                            page.screenshot(path=str(SHOTS / ("smoke-r%d-%02d.png" % (rnd, i))))
                        except Exception:  # noqa: BLE001
                            pass
                        try:
                            page.goto("http://127.0.0.1:%d/?win=1" % app.port, wait_until="load")
                            time.sleep(1.2)
                        except Exception:  # noqa: BLE001
                            pass
            br.close()
    finally:
        app.cleanup(a.keep)

    print("\n本轮跳过（不假装点过）：")
    for n, why in SKIPPED:
        print("  · %-18s %s" % (n, why))
    bad = [r for r in rows if not r[2]]
    print("\n合计 %d 次点击 · 通过 %d · 失败 %d" % (len(rows), len(rows) - len(bad), len(bad)))
    if bad:
        for rnd, name, _, ms in bad:
            print("  [红] 第 %d 轮 %s：%s" % (rnd, name, ms))
        return 1
    print("三轮全绿")
    return 0


if __name__ == "__main__":
    sys.exit(main())
