# -*- coding: utf-8 -*-
"""找黑框：几种窗口状态变化后，量 innerHeight 与窗口实际客户区，看是否对得上。"""
import importlib.util, json, os, sys, time, subprocess, ctypes, ctypes.wintypes as wt
from pathlib import Path
HERE = Path(r"F:/DSH/apps/LaPluma/tools/check")
spec = importlib.util.spec_from_file_location("cwr", str(HERE / "check-window-real.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
from playwright.sync_api import sync_playwright

home = m.make_home(); port, cdp = m.free_port(), m.free_port()
env = dict(os.environ, PLUMA_HOME=str(home), PLUMA_TEST_CDP=str(cdp), PLUMA_TEST_DATA=str(home), PYTHONIOENCODING="utf-8")
log = open(str(home / "app.log"), "wb")
proc = subprocess.Popen([sys.executable, str(HERE / "_win_launch.py"), "--port", str(port), "--no-browser"],
    cwd=r"F:/DSH/apps/LaPluma", env=env, stdout=log, stderr=subprocess.STDOUT)
u = ctypes.windll.user32

def client(hwnd):
    r = wt.RECT(); u.GetClientRect(wt.HWND(hwnd), ctypes.byref(r)); return (r.right, r.bottom)

def state(page, hwnd, tag):
    win = m.rect_of(hwnd); cl = client(hwnd)
    inner = page.evaluate("[innerWidth, innerHeight]")
    app = page.evaluate("(()=>{const e=document.getElementById('appScroll');const r=e.getBoundingClientRect();return [Math.round(r.height), getComputedStyle(e).height];})()")
    print(tag, "win", win, "client", cl, "inner", inner, "appScroll", app,
          "zoomed", m.is_zoom(hwnd), "fsEl", page.evaluate("!!document.fullscreenElement"))
try:
    m.wait_http("http://127.0.0.1:%d/api/bootstrap" % port, 90)
    m.wait_http("http://127.0.0.1:%d/json/version" % cdp, 60)
    hwnd = 0
    for _ in range(80):
        hwnd = m.find_hwnd(proc.pid)
        if hwnd: break
        time.sleep(0.4)
    with sync_playwright() as p:
        br = p.chromium.connect_over_cdp("http://127.0.0.1:%d" % cdp)
        page = None
        for _ in range(80):
            for ctx in br.contexts:
                for pg in ctx.pages:
                    if "win=1" in pg.url: page = pg
            if page: break
            time.sleep(0.5)
        page.wait_for_selector("#tbar:not([hidden])", timeout=25000)
        time.sleep(2); m.clear_overlay(page)
        state(page, hwnd, "0 初始")
        # 最大化
        page.click("#tbMax"); time.sleep(0.8)
        state(page, hwnd, "1 最大化")
        m.open_drawer(page, "TDEMO"); m.open_reader_from_drawer(page)
        page.click("#btnFs"); time.sleep(1.2)
        state(page, hwnd, "2 全屏(按钮)")
        page.click("#btnNotePage"); time.sleep(1.0)
        state(page, hwnd, "3 记笔记")
        page.click("a[data-page='courses']"); time.sleep(0.8)
        state(page, hwnd, "4 课程")
        m.open_drawer(page, "TDEMO"); time.sleep(0.5)
        page.locator("#drFiles .f").nth(1).click()
        page.wait_for_function("document.querySelectorAll('#pdftext span').length > 3", timeout=40000)
        time.sleep(1.0)
        state(page, hwnd, "5 再读")
        # 退出最大化
        page.click("#tbMax"); time.sleep(1.0)
        state(page, hwnd, "6 还原")
        # 再全屏 + Esc
        page.click("#btnFs"); time.sleep(1.0)
        page.keyboard.press("Escape"); time.sleep(1.2)
        state(page, hwnd, "7 Esc 退出全屏")
finally:
    proc.terminate()
    try: proc.wait(timeout=10)
    except Exception: proc.kill()
    log.close()
