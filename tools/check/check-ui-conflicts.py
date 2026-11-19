# -*- coding: utf-8 -*-
"""按钮/浮层冲突的行为回归（2026-11-19，用户第 8 条）。

为什么不是扫代码：全屏→点导航、弹窗→点导航这类冲突，静态扫描看不出来，必须真点。
本脚本自己起一个 --no-window 服务，用 Playwright(Edge) 真点三组，任一组失败退出 1。
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
import urllib.request

from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PORT = 8896
BASE = "http://127.0.0.1:%d" % PORT
PDF = "DEMO/01_讲义/D01_一份讲义是怎么出来的_讲义.pdf"


def wait_up(secs=25.0) -> bool:
    end = time.time() + secs
    while time.time() < end:
        try:
            urllib.request.urlopen(BASE + "/api/bootstrap", timeout=2).read()
            return True
        except Exception:  # noqa: BLE001
            time.sleep(0.3)
    return False


def main() -> int:
    py = subprocess.Popen([sys.executable, "-X", "utf8", os.path.join(ROOT, "ui", "server.py"),
                           "--no-window", "--port", str(PORT)],
                          cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    rows = []
    try:
        if not wait_up():
            print("[红] 服务没起来")
            return 1
        with sync_playwright() as p:
            br = p.chromium.launch(channel="msedge", headless=True)
            for label, action in (
                ("全屏 → 点导航", "fullscreen_nav"),
                ("全屏 → Esc", "fullscreen_esc"),
                ("阅读 → 返回课程", "read_back"),
            ):
                pg = br.new_page(viewport={"width": 1440, "height": 900})
                # 强制走「满屏浮层」兜底路径：无头环境允许原生全屏时 Esc 由浏览器处理，测不到页面逻辑
                pg.add_init_script("Element.prototype.requestFullscreen = () => Promise.reject(new Error('headless-deny'))")
                pg.goto(BASE + "/?dbg=1&win=1&course=DEMO&pdf=" + urllib.request.quote(PDF, safe="") + "&code=DEMO",
                        wait_until="networkidle")
                pg.wait_for_timeout(3200)
                # CI 是全新配置：首次配置/欢迎浮层会挡住按钮，先按软件自己的关闭函数收掉
                pg.evaluate("try{ if(document.querySelector('#veil.on')) closeVeil(); }catch(e){}")
                pg.wait_for_timeout(200)
                if action == "fullscreen_nav":
                    pg.click("#btnFs"); pg.wait_for_timeout(500)
                    pg.evaluate("document.querySelector('#nav a[data-page=\"courses\"]').click()")
                    pg.wait_for_timeout(600)
                    ok = (pg.evaluate("document.querySelector('#page-courses').classList.contains('on')")
                          and not pg.evaluate("document.body.classList.contains('fs-read')")
                          and not pg.evaluate("document.querySelector('#page-read .read-card').classList.contains('fs')"))
                elif action == "fullscreen_esc":
                    pg.click("#btnFs"); pg.wait_for_timeout(500)
                    pg.keyboard.press("Escape"); pg.wait_for_timeout(600)
                    ok = (not pg.evaluate("document.body.classList.contains('fs-read')")
                          and not pg.evaluate("document.querySelector('#page-read .read-card').classList.contains('fs')"))
                else:
                    pg.click("#readBack"); pg.wait_for_timeout(500)
                    ok = pg.evaluate("document.querySelector('#page-courses').classList.contains('on')")
                rows.append(ok)
                print("[%s] %s" % ("绿" if ok else "红", label))
                pg.close()
            br.close()
    finally:
        py.terminate()
        try:
            py.wait(timeout=8)
        except Exception:  # noqa: BLE001
            py.kill()
    bad = sum(1 for x in rows if not x)
    print("结论：%d/%d" % (len(rows) - bad, len(rows)))
    return 0 if rows and bad == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
