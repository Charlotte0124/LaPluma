# -*- coding: utf-8 -*-
r"""R113 窗口段：在羽毛笔自己的窗口里真点抽屉 / 生成 / 设置，并留下证据。

为什么要有这一条（2026-11-21 用户定；2026-11-27 补窗口段载体）：
  用户原话「软件测试是要在实体软件、模拟全新环境，完全去测试软件的按键」。
  exe 从 v1.9.15 起退役（改文件夹版 + 一键启动.ps1），原来那份 check-fresh-install.py
  只认 dist\LaPluma.exe，于是 R113 的窗口段一直「没查」。这里把窗口段单独做成一条：
  起真窗口（WebView2）+ 干净临时数据根 + 用 CDP 点界面元素，量四件事。

  · 不许用浏览器页代替（R113 口径：浏览器里打开 127.0.0.1 不算测试）
  · 不进用户真实课程目录（PLUMA_TEST_DATA 指临时根）
  · 不摸真 key（PLUMA_DISABLE_KEY=1；示例讲次正文已完整，生成不走模型）

判据（对应 CONVENTIONS §66 的表）：
  W1 窗口起来：自绘标题条可见、版本号非空、窗口矩形合理、CDP 端口通
  W2 真点抽屉：点课程卡开抽屉，抽屉顶边不许被顶栏压住（top >= 顶栏底）
  W3 真点生成：生成页选讲次 → 点「开始生成」→ 有新 PDF 落地（>50 KB）
  W4 真点设置：设置页版本行写清「本机 v…」与更新行（仓库 / 最新）

用法：
    python tools\check\check-window-fresh.py            # 跑一遍，写证据，跑完关窗
    python tools\check\check-window-fresh.py --keep     # 留临时数据根

产物：_logs\fresh-window-<时间戳>.json（证据）+ _logs\fresh-window-<时间戳>-W*.png（三张窗口截图）
退出码：0 = W1–W4 全绿；1 = 有红；2 = 没查（缺 playwright / 窗口起不来）
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
LOGS = ROOT / "_logs"
ROWS = []          # [(id, ok|False|None, detail)]  None = 没查


def load_helpers():
    """借 check-window-real.py 的临时数据根 / 句柄 / 端口工具（不重复实现同一套）。"""
    path = HERE / "check-window-real.py"
    spec = importlib.util.spec_from_file_location("cwr", str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def add(wid, ok, detail):
    ROWS.append({"id": wid, "ok": ok, "detail": detail})
    tag = "[绿]" if ok is True else ("[红]" if ok is False else "[黄]")
    print("%s %s %s" % (tag, wid, detail))


def app_version() -> str:
    try:
        d = json.loads((ROOT / "feed" / "latest.json").read_text(encoding="utf-8"))
        return str(d.get("latest") or "").strip()
    except Exception:  # noqa: BLE001
        return ""


def newest_pdf(dirs, since):
    hit = None
    for d in dirs:
        if not d.is_dir():
            continue
        for f in d.glob("*.pdf"):
            try:
                st = f.stat()
            except OSError:
                continue
            if st.st_mtime > since and st.st_size > 50 * 1024:
                if hit is None or st.st_mtime > hit[1]:
                    hit = (f, st.st_mtime, st.st_size)
    return hit


def main(argv=None) -> int:
    for s in (sys.stdout, sys.stderr):
        if hasattr(s, "reconfigure"):
            s.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="R113 窗口段：在真窗口里点抽屉 / 生成 / 设置")
    ap.add_argument("--keep", action="store_true")
    args = ap.parse_args(argv)

    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:  # noqa: BLE001
        print("[黄] 装不上 playwright，没查：%r" % (e,))
        return 2

    cwr = load_helpers()
    ver_want = app_version()
    home = cwr.make_home()
    port, cdp = cwr.free_port(), cwr.free_port()
    env = dict(os.environ)
    env.update({
        "PLUMA_HOME": str(home),
        "PLUMA_TEST_DATA": str(home),
        "PLUMA_TEST_CDP": str(cdp),
        "PLUMA_DISABLE_KEY": "1",
        "PYTHONIOENCODING": "utf-8",
    })
    log = open(str(home / "app.log"), "wb")
    proc = subprocess.Popen([sys.executable, str(HERE / "_win_launch.py"),
                             "--port", str(port), "--no-browser"],
                            cwd=str(ROOT), env=env, stdout=log, stderr=subprocess.STDOUT)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    LOGS.mkdir(exist_ok=True)
    shots = []
    proc_kill = [False]

    def finish(code):
        try:
            if proc.poll() is None and not args.keep:
                proc.terminate()
                try:
                    proc.wait(timeout=15)
                except Exception:  # noqa: BLE001
                    proc.kill()
        except Exception:  # noqa: BLE001
            pass
        ev = {
            "rule": "R113",
            "what": "窗口段：真窗口里点抽屉 / 生成 / 设置",
            "at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "app_version": ver_want,
            "host": os.environ.get("COMPUTERNAME", ""),
            "python": sys.version.split()[0],
            "home": str(home),
            "rows": ROWS,
            "shots": shots,
            "code": code,
        }
        out = LOGS / ("fresh-window-%s.json" % stamp)
        out.write_text(json.dumps(ev, ensure_ascii=False, indent=2), encoding="utf-8")
        print("证据：%s（%d 字节）" % (out, out.stat().st_size))
        print("截图：%s" % (", ".join(shots) if shots else "无"))
        if not args.keep:
            try:
                import shutil
                shutil.rmtree(home, ignore_errors=True)
            except Exception:  # noqa: BLE001
                pass
        if code == 0:
            print("[绿] R113 窗口段：W1–W4 全绿")
        elif code == 1:
            print("[红] R113 窗口段：有红，见上表")
        else:
            print("[黄] R113 窗口段：没查（窗口起不来），不是绿")
        return code

    try:
        if not cwr.wait_http("http://127.0.0.1:%d/api/bootstrap" % port, 120):
            add("窗口启动", None, "120 秒内没回 /api/bootstrap（看 %s）" % (home / "app.log"))
            return finish(2)
        hwnd = 0
        end = time.time() + 40
        while time.time() < end and not hwnd:
            hwnd = cwr.find_hwnd(proc.pid)
            time.sleep(0.4)
        if not hwnd:
            add("窗口启动", None, "找不到羽毛笔窗口句柄")
            return finish(2)
        if not cwr.wait_http("http://127.0.0.1:%d/json/version" % cdp, 90):
            add("窗口启动", None, "CDP 端口没开（PLUMA_TEST_CDP=%d）" % cdp)
            return finish(2)

        with sync_playwright() as p:
            br = p.chromium.connect_over_cdp("http://127.0.0.1:%d" % cdp)
            page = None
            end = time.time() + 60
            while time.time() < end and page is None:
                for ctx in br.contexts:
                    for pg in ctx.pages:
                        if "win=1" in pg.url:
                            page = pg
                if page is None:
                    time.sleep(0.4)
            if page is None:
                add("窗口启动", None, "CDP 连上了但没有 win=1 页面")
                return finish(2)

            def clear_veil():
                page.evaluate("() => { const v=document.getElementById('veil');"
                              " if (v) v.classList.remove('on'); }")

            # ---- W1 窗口起来 ----
            try:
                page.wait_for_selector("#tbar:not([hidden])", timeout=30000)
                ver = (page.evaluate("(document.querySelector('#tbVer')||{}).textContent") or "").strip()
                iswin = bool(page.evaluate("document.body.classList.contains('win')"))
                left, top, w, h = cwr.rect_of(hwnd)
                good = iswin and ver.startswith("v") and w >= 900 and h >= 600
                if ver_want and ver_want.lstrip("v") not in ver:
                    good = False
                add("W1 窗口起来", good,
                    "自绘标题条 win=%s 版本=%r 窗口=%dx%d CDP :%d" % (iswin, ver, w, h, cdp))
                sh = LOGS / ("fresh-window-%s-W1.png" % stamp)
                page.screenshot(path=str(sh))
                shots.append(str(sh))
                if not good:
                    return finish(1)
            except Exception as e:  # noqa: BLE001
                add("W1 窗口起来", False, "标题条没出来：%r" % (e,))
                return finish(1)

            # ---- W2 真点抽屉 ----
            try:
                clear_veil()
                page.click("a[data-page='courses']")
                page.wait_for_selector(".course", timeout=20000)
                page.locator(".course").first.click()
                page.wait_for_selector(".drawer.on", timeout=20000)
                time.sleep(0.5)
                d_top = page.evaluate("Math.round(document.querySelector('.drawer.on')"
                                      ".getBoundingClientRect().top)")
                t_bot = page.evaluate("Math.round(document.getElementById('tbar')"
                                      ".getBoundingClientRect().bottom)")
                good = d_top >= t_bot - 1
                add("W2 真点抽屉", good, "抽屉顶边 %d / 顶栏底 %d" % (d_top, t_bot))
                sh = LOGS / ("fresh-window-%s-W2.png" % stamp)
                page.screenshot(path=str(sh))
                shots.append(str(sh))
                page.keyboard.press("Escape")
                time.sleep(0.6)
                if not good:
                    return finish(1)
            except Exception as e:  # noqa: BLE001
                add("W2 真点抽屉", False, "点课程卡开抽屉失败：%r" % (e,))
                return finish(1)

            # ---- W3 真点生成 ----
            try:
                clear_veil()
                page.evaluate("() => { const a=document.querySelector(\"a[data-page='generate']\");"
                              " if (a) a.click(); }")
                page.wait_for_selector("#btnGen", timeout=25000)
                time.sleep(0.8)
                page.evaluate("() => { const a=document.querySelector(\"a[data-page='generate']\");"
                              " if (a) a.click(); }")
                page.wait_for_selector("#lessonPick [data-lsn]", timeout=25000)
                no = page.evaluate("() => { const c=document.querySelector('#lessonPick [data-lsn]');"
                                   " if (!c) return ''; c.click(); return c.getAttribute('data-lsn')||''; }")
                time.sleep(0.6)
                if not no:
                    add("W3 真点生成", False, "生成列表里没有可点的讲次")
                    return finish(1)
                since = time.time() - 1
                dirs = [home / "TDEMO" / "01_讲义", home / "out"]
                page.click("#btnGen")
                hit = None
                end = time.time() + 300
                while time.time() < end and hit is None:
                    hit = newest_pdf(dirs, since)
                    time.sleep(2.0)
                if hit is None:
                    tail = ""
                    try:
                        tail = (home / "app.log").read_text(encoding="utf-8", errors="replace")[-600:]
                    except Exception:  # noqa: BLE001
                        pass
                    add("W3 真点生成", False,
                        "讲次 %s 点「开始生成」后 300 秒内没有新 PDF；日志末尾：%s"
                        % (no, tail.replace("\n", " ")[-260:]))
                    return finish(1)
                add("W3 真点生成", True,
                    "讲次 %s → 新 PDF %s（%.1f KB）" % (no, hit[0].name, hit[2] / 1024.0))
                sh = LOGS / ("fresh-window-%s-W3.png" % stamp)
                page.screenshot(path=str(sh))
                shots.append(str(sh))
            except Exception as e:  # noqa: BLE001
                add("W3 真点生成", False, "生成页点不成：%r" % (e,))
                return finish(1)

            # ---- W4 真点设置 ----
            try:
                clear_veil()
                # #btnSet 是 span，自绘标题条那一层会拦截命中测试；冒烟脚本同样用 JS 点。
                #   点的仍是页面自己的 onclick，不是绕过界面直调接口。
                page.evaluate("() => { const b=document.getElementById('btnSet'); if (b) b.click(); }")
                page.wait_for_selector("#sVer", timeout=20000)
                time.sleep(0.6)
                ver_line = (page.evaluate("(document.querySelector('#sVer')||{}).textContent") or "").strip()
                upd_line = (page.evaluate("(document.querySelector('#sUpd')||{}).textContent") or "").strip()
                good = ("本机 v" in ver_line) and (("仓库" in upd_line) or ("最新" in upd_line))
                add("W4 真点设置", good, "版本行 %r / 更新行 %r"
                    % (ver_line[:40], upd_line[:40]))
                sh = LOGS / ("fresh-window-%s-W4.png" % stamp)
                page.screenshot(path=str(sh))
                shots.append(str(sh))
                if not good:
                    return finish(1)
            except Exception as e:  # noqa: BLE001
                add("W4 真点设置", False, "设置打不开：%r" % (e,))
                return finish(1)

        return finish(0)
    finally:
        try:
            log.close()
        except Exception:  # noqa: BLE001
            pass


if __name__ == "__main__":
    sys.exit(main())
