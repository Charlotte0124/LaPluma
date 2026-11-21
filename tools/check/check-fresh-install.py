# -*- coding: utf-8 -*-
"""全新安装自测：把打包好的 exe 放进空目录，**在它自己的窗口里真点按钮**。

为什么这么测（用户 2026-11-21，两次强调）：
  「以后软件测试是要在实体软件、模拟全新环境，完全去测试软件的按键，测试 BUG 等等
   —— 有一些是依赖本机的一直没发现，很多 BUG 都是那么来的」
  「我指的是这种方式测试（浏览器打开 127.0.0.1:8896）有很多 BUG 都找不到，
   然后打包的时候就一大堆 BUG 出来了 —— 所以直接改用打包 APP 去测试吧，
   不然这种测试是无意义的」
所以判据分两段：
  A–D  接口段：exe 起得来 / 缺东西说得清 / 真出 PDF / 版本检查通（快，先跑）
  W1–W4 窗口段：**exe 自己的窗口**（WebView2，不是浏览器）里用 CDP 真点——
        点课程卡开抽屉（抽屉不许被顶栏压住）、点「生成」→ 选讲次 → 点「开始生成」→ 等 PDF、
        点「设置」看版本行。顶栏挡 UI 这种 bug 只有真窗口里点得出来，走接口看不见。
  只有窗口段才是「实体软件」；接口段留作快速定位。

环境：
  · 实体软件：只测 dist\\LaPluma.exe，不测源码，也不在浏览器里开 localhost
  · 全新环境：exe 复制到空临时目录（数据根），PLUMA_HOME 指到空目录（没有钥匙 / 更新缓存）
  · 窗口段靠 PLUMA_TEST_CDP=<端口> 打开 WebView2 的远程调试端口（只在自测里用）
  · 截图落在 _logs\\fresh-window-*.png，红了先看它们

用法：
    python tools\\check\\check-fresh-install.py            # 全跑（会短暂弹出软件窗口）
    python tools\\check\\check-fresh-install.py --api-only # 只跑接口段
    python tools\\check\\check-fresh-install.py --keep     # 留下临时目录

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
BOOT_WAIT = 45.0
CDP_WAIT = 90.0


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def http_json(url: str, timeout: float = 30.0, body: dict | None = None) -> tuple:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data,
                                 headers={"Content-Type": "application/json"} if data else {},
                                 method="POST" if data else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode("utf-8", "replace") or "{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8", "replace") or "{}")
        except Exception:  # noqa: BLE001
            return e.code, {}
    except Exception as e:  # noqa: BLE001
        return 0, {"error": repr(e)}


class Fresh:
    """一个全新的「用户目录」：exe 副本 + 空数据根 + 空配置目录。"""

    def __init__(self, with_key: bool = False) -> None:
        self.base = Path(tempfile.mkdtemp(prefix="pluma-fresh-"))
        self.app = self.base / "app"
        self.home = self.base / "home"
        self.app.mkdir(parents=True, exist_ok=True)
        self.home.mkdir(parents=True, exist_ok=True)
        self.exe = self.app / EXE.name
        shutil.copy2(EXE, self.exe)
        if with_key:
            src = Path(os.path.expanduser("~")) / ".pluma" / "api.json"
            if src.is_file():
                shutil.copy2(src, self.home / "api.json")
        self.port = free_port()
        self.proc = None

    def env(self, cdp: int = 0) -> dict:
        e = dict(os.environ)
        e["PLUMA_HOME"] = str(self.home)
        e["TEMP"] = str(self.base / "tmp")
        e["TMP"] = e["TEMP"]
        Path(e["TEMP"]).mkdir(parents=True, exist_ok=True)
        e.pop("PLUMA_API_KEY", None)
        if cdp:
            e["PLUMA_TEST_CDP"] = str(cdp)
        return e

    def start(self, window: bool = False, cdp: int = 0) -> tuple:
        args = [str(self.exe), "--port", str(self.port)]
        if not window:
            args += ["--no-window", "--no-browser"]
        self.proc = subprocess.Popen(
            args, cwd=str(self.app), env=self.env(cdp),
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        t0 = time.time()
        while time.time() - t0 < BOOT_WAIT:
            code, j = http_json("http://127.0.0.1:%d/api/bootstrap" % self.port, timeout=3)
            if code == 200 and j.get("version"):
                return True, j, round(time.time() - t0, 1)
            if self.proc.poll() is not None:
                return False, {"exited": self.proc.returncode}, round(time.time() - t0, 1)
            time.sleep(0.6)
        return False, {"error": "启动超时"}, round(time.time() - t0, 1)

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            # 2026-11-21：pid 是启动器，真窗口是它的子进程；只 terminate 父进程会留下子窗口
            # （用户实测：自检跑一次多一个窗口）。用 taskkill /T 连子进程一起收，再兜底扫一遍
            # 可执行文件路径在本轮临时目录下的进程。
            try:
                subprocess.run(
                    ["taskkill", "/PID", str(self.proc.pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10,
                )
            except Exception:  # noqa: BLE001
                try:
                    self.proc.kill()
                except Exception:  # noqa: BLE001
                    pass
        self._kill_leftovers()

    def _kill_leftovers(self) -> None:
        """按临时目录路径兜底：凡是 exe 在本轮 base 下的进程都收掉。"""
        try:
            out = subprocess.run(
                ["wmic", "process", "where", "name='LaPluma.exe'", "get", "ProcessId,ExecutablePath", "/format:csv"],
                capture_output=True, text=True, timeout=15,
            ).stdout
        except Exception:  # noqa: BLE001
            return
        base = str(self.base).lower()
        for line in out.splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 3:
                continue
            exe, pid = parts[1].lower(), parts[-1]
            if base in exe or "pluma-fresh-" in exe:
                try:
                    subprocess.run(["taskkill", "/PID", pid, "/T", "/F"],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
                except Exception:  # noqa: BLE001
                    pass

    def cleanup(self, keep: bool) -> None:
        self.stop()
        if keep:
            print("  （留下临时目录：%s）" % self.base)
            return
        for _ in range(3):
            try:
                shutil.rmtree(self.base, ignore_errors=False)
                return
            except Exception:  # noqa: BLE001
                time.sleep(0.5)


def api_phase(ok: list, red: list, keep: bool) -> None:
    f = Fresh(with_key=False)
    try:
        up, boot, sec = f.start()
        if not up:
            red.append("A 起不来：%s" % (boot,))
            return
        ok.append("A 起得来：v%s · %s 秒（单文件自解包）" % (boot.get("version"), sec))
        base = "http://127.0.0.1:%d" % f.port

        code, ask = http_json(base + "/api/ask", timeout=120,
                              body={"course": "DEMO", "lesson": "D01", "question": "这一讲讲了什么"})
        msg = str(ask.get("error") or "")
        if ask.get("need_key") and ("钥匙" in msg or "key" in msg.lower()):
            ok.append("B 没钥匙时说得清：" + msg[:50])
        else:
            red.append("B 没钥匙时没说清（HTTP %s · need_key=%s）" % (code, ask.get("need_key")))

        shutil.copy2(Path(os.path.expanduser("~")) / ".pluma" / "api.json", f.home / "api.json")
        pdf = f.app / "DEMO" / "01_讲义" / "D01_一份讲义是怎么出来的_讲义.pdf"
        before = pdf.stat().st_mtime if pdf.is_file() else 0
        code, g = http_json(base + "/api/generate", timeout=600,
                            body={"lesson": "D01", "course": "DEMO", "form": "single", "lang": "zh"})
        log = str(g.get("log") or "")
        if "打印失败" in log:
            red.append("C 打印失败：%s" % log.split("打印失败")[-1].strip().splitlines()[0][:80])
        elif not pdf.is_file() or pdf.stat().st_mtime <= before:
            red.append("C 没出 PDF：ok=%s" % g.get("ok"))
        else:
            ok.append("C 真出 PDF：%.0f KB" % (pdf.stat().st_size / 1024))

        code, u = http_json(base + "/api/update?force=1", timeout=60)
        if code == 200 and u.get("ok"):
            ok.append("D 版本检查：current %s · latest %s" % (u.get("current"), u.get("latest")))
        else:
            red.append("D 版本检查 HTTP %s" % code)
    finally:
        f.cleanup(keep)



def _close_drawer(page) -> bool:
    """把抽屉与遮罩收干净。生成完成后软件会自动打开课程抽屉（v1.9.12 的既定行为），
    它会挡住后面的导航 / 设置按钮——不关掉就成了脚本自己的假红。"""
    for _ in range(20):
        if not page.evaluate("() => !!document.querySelector('.drawer.on, .dveil.on')"):
            return True
        page.keyboard.press("Escape")
        time.sleep(0.15)
    return False

def window_phase(ok: list, red: list, keep: bool) -> None:
    """实体软件：真窗口 + 真点击。这一段才判「有没有 bug」。"""
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:  # noqa: BLE001
        red.append("W 没查成：装不上 playwright（%r）" % (e,))
        return

    f = Fresh(with_key=True)
    cdp = free_port()
    try:
        up, boot, sec = f.start(window=True, cdp=cdp)
        if not up:
            red.append("W1 窗口起不来：%s" % (boot,))
            return
        t0 = time.time()
        while time.time() - t0 < CDP_WAIT:
            code, v = http_json("http://127.0.0.1:%d/json/version" % cdp, timeout=2)
            if code == 200 and v.get("Browser"):
                break
            time.sleep(0.8)
        else:
            red.append("W1 窗口起来了但拿不到调试端口（%d）：无法真点" % cdp)
            return
        ok.append("W1 打包件窗口起来了：v%s · WebView2 %s" % (boot.get("version"), str(v.get("Browser"))[:40]))

        SHOTS.mkdir(parents=True, exist_ok=True)
        with sync_playwright() as p:
            br = p.chromium.connect_over_cdp("http://127.0.0.1:%d" % cdp)
            ctx = br.contexts[0] if br.contexts else br.new_context()
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.set_default_timeout(20000)
            page.wait_for_selector(".course", timeout=30000)
            page.screenshot(path=str(SHOTS / "fresh-window-1-home.png"))

            # W2 点课程卡开抽屉：抽屉顶部不许被顶栏压住（今晚那个 bug 的判据）
            page.click(".course")
            page.wait_for_selector(".drawer.on", timeout=15000)
            box = page.evaluate("""() => {
              const d = document.querySelector('.drawer.on');
              const t = document.getElementById('tbar');
              const b = d.getBoundingClientRect(), tb = t ? t.getBoundingClientRect() : {bottom: 0};
              const head = d.querySelector('h3, .dr-files-grp, header');
              return {top: Math.round(b.top), tbarBottom: Math.round(tb.bottom),
                      headTop: head ? Math.round(head.getBoundingClientRect().top) : null};
            }""")
            page.screenshot(path=str(SHOTS / "fresh-window-2-drawer.png"))
            if box["top"] >= box["tbarBottom"]:
                ok.append("W2 抽屉没被顶栏压住（抽屉 top=%s · 顶栏底=%s）" % (box["top"], box["tbarBottom"]))
            else:
                red.append("W2 抽屉被顶栏压住：top=%s < 顶栏底 %s" % (box["top"], box["tbarBottom"]))
            if not _close_drawer(page):
                red.append("W2 抽屉关不掉（点了课程卡之后收不回去）")

            # W3 点「生成」→ 选一讲 → 点「开始生成」→ 等 PDF 真落地
            page.click("#nav a[data-page=generate]")
            page.wait_for_selector("#btnGen", timeout=15000)
            page.click('#lessonPick [data-lsn="D01"]')
            pdf = f.app / "DEMO" / "01_讲义" / "D01_一份讲义是怎么出来的_讲义.pdf"
            before = pdf.stat().st_mtime if pdf.is_file() else 0
            page.click("#btnGen")
            done = False
            for _ in range(120):
                time.sleep(1.0)
                if pdf.is_file() and pdf.stat().st_mtime > before:
                    done = True
                    break
            page.screenshot(path=str(SHOTS / "fresh-window-3-generate.png"))
            if done:
                ok.append("W3 真窗口点「开始生成」出了 PDF：%.0f KB" % (pdf.stat().st_size / 1024))
            else:
                red.append("W3 真窗口点「开始生成」没出 PDF（看 fresh-window-3-generate.png）")

            # W4 点「设置」：版本行要说清本机与仓库
            _close_drawer(page)      # 生成完软件会自动开课程抽屉，先收起
            page.click("#btnSet")
            page.wait_for_selector("#sVer", timeout=15000)
            time.sleep(1.2)
            ver = page.inner_text("#sVer")
            upd = page.inner_text("#sUpd")
            page.screenshot(path=str(SHOTS / "fresh-window-4-settings.png"))
            if "本机 v" in ver and ("仓库" in upd or "最新" in upd):
                ok.append("W4 设置页版本行：%s · %s" % (ver[:24], upd[:34]))
            else:
                red.append("W4 设置页版本行不对：%r / %r" % (ver, upd))
            br.close()
    finally:
        f.cleanup(keep)


def main(argv=None) -> int:
    for s in (sys.stdout, sys.stderr):
        if hasattr(s, "reconfigure"):
            s.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="全新环境 + 实体软件真点")
    ap.add_argument("--keep", action="store_true")
    ap.add_argument("--api-only", action="store_true")
    a = ap.parse_args(argv)

    if not EXE.is_file():
        print("[黄] 没有 dist\\LaPluma.exe：先跑 tools\\build\\build-exe.ps1 再来自测")
        return 2
    print("用 %s（%.1f MB · %s）" % (EXE, EXE.stat().st_size / 1048576,
                                  time.strftime("%Y-%m-%d %H:%M", time.localtime(EXE.stat().st_mtime))))

    ok, red = [], []
    api_phase(ok, red, a.keep)
    if not a.api_only:
        # 窗口段任何异常都要变成一条红，不许抛栈把调用方（check-prts / 钩子）打断
        try:
            window_phase(ok, red, a.keep)
        except Exception as e:  # noqa: BLE001
            red.append('W 窗口段崩了：%r' % (e,))
    for x in ok:
        print("  [绿] " + x)
    for x in red:
        print("  [红] " + x)
    total = len(ok) + len(red)
    print("结论：%d/%d 绿 · %d 红" % (len(ok), total, len(red)))
    return 0 if not red else 1


if __name__ == "__main__":
    sys.exit(main())
