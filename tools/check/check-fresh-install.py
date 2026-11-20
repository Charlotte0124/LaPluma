# -*- coding: utf-8 -*-
"""全新安装自测：把打包好的 exe 放进一个空目录（模拟用户第一次拿到软件），真点一遍。

为什么有（用户 2026-11-21）：「以后软件测试是要在实体软件、模拟全新环境，完全去测试软件的按键，
测试 BUG 等等——有一些是依赖本机的一直没发现，很多 BUG 都是那么来的」。
当晚就是证据：源码里 `python ui\\server.py` 一路绿，打包后的 exe 却在**打印 PDF** 那步
Chrome 以 0x80000003 退出（父进程没有真的 stdio 句柄），而目录里还留着上一轮生成的 PDF，
所以本机看起来「能生成」。换成空目录跑，一次就露。

口径：
  · **实体软件**：只测 dist\\LaPluma.exe，不测源码
  · **全新环境**：exe 复制到空临时目录（数据根＝那里，没有 courses.json / _logs / 旧 PDF）、
    PLUMA_HOME 指到空目录（没有 API 钥匙、没有 update.json 缓存）
  · **真点按键**：走界面用的同一批接口——首页 bootstrap、生成、版本检查；不看「函数返回 True」
  · 判据：
      A 起得来：exe 起来并在 30 秒内回 /api/bootstrap（版号非空）
      B 无钥匙时说得清：生成一讲必须给出「没配置 API 钥匙」这类**人话**，不许静默失败
      C 真能出 PDF：装上钥匙后生成 DEMO/D01（出厂示例课，正文是现成的，不花钱），
        必须新出现一份 PDF，且日志里不许有「打印失败」
      D 版本检查通：/api/update 回 200（缓存目录是空的时候也不许 403）

用法：
    python tools\\check\\check-fresh-install.py            # 全跑
    python tools\\check\\check-fresh-install.py --keep     # 留下临时目录（排查用）

退出码：0 全绿；1 有红；2 没查（没有 exe / 没 python 能力）
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
ROOT = HERE.parent.parent          # <仓根>
EXE = ROOT / "dist" / "LaPluma.exe"
BOOT_WAIT = 45.0                   # 单文件自解包，第一次起要十几秒


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

    def __init__(self) -> None:
        self.base = Path(tempfile.mkdtemp(prefix="pluma-fresh-"))
        self.app = self.base / "app"
        self.home = self.base / "home"
        self.app.mkdir(parents=True, exist_ok=True)
        self.home.mkdir(parents=True, exist_ok=True)
        self.exe = self.app / EXE.name
        shutil.copy2(EXE, self.exe)
        self.port = free_port()
        self.proc = None

    def env(self) -> dict:
        e = dict(os.environ)
        e["PLUMA_HOME"] = str(self.home)
        e.pop("PLUMA_API_KEY", None)          # 全新环境没有钥匙
        e["PLUMA_NO_UPDATE_CHECK"] = "1"      # 别让首启的更新检查干扰判定（仍然单独测 D）
        return e

    def start(self) -> tuple:
        self.proc = subprocess.Popen(
            [str(self.exe), "--no-window", "--no-browser", "--port", str(self.port)],
            cwd=str(self.app), env=self.env(),
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
            print("  （留下临时目录：%s）" % self.base)
            return
        for _ in range(3):
            try:
                shutil.rmtree(self.base, ignore_errors=False)
                return
            except Exception:  # noqa: BLE001
                time.sleep(0.5)


def main(argv=None) -> int:
    for s in (sys.stdout, sys.stderr):
        if hasattr(s, "reconfigure"):
            s.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="全新环境真跑打包后的 exe")
    ap.add_argument("--keep", action="store_true")
    a = ap.parse_args(argv)

    if not EXE.is_file():
        print("[黄] 没有 dist\\LaPluma.exe：先跑 tools\\build\\build-exe.ps1 再来自测")
        return 2
    print("用 %s（%.1f MB · %s）" % (EXE, EXE.stat().st_size / 1048576,
                                  time.strftime("%Y-%m-%d %H:%M", time.localtime(EXE.stat().st_mtime))))

    red, ok = [], []
    f = Fresh()
    try:
        # ---- A 起得来 ----
        up, boot, sec = f.start()
        if up:
            ok.append("A 起得来：v%s · %s 秒（单文件自解包）" % (boot.get("version"), sec))
        else:
            red.append("A 起不来：%s" % (boot,))
            return _report(ok, red)

        base = "http://127.0.0.1:%d" % f.port

        # ---- B 没钥匙时说得清 ----
        # 用「问课件」这条不用钱也不会被原件缺失挡住的路径：全新环境没有钥匙，
        # 必须回 need_key + 一句人话，而不是静默失败或抛栈。
        code, ask = http_json(base + "/api/ask", timeout=120,
                              body={"course": "DEMO", "lesson": "D01", "question": "这一讲讲了什么"})
        msg = str(ask.get("error") or "")
        if ask.get("need_key") and ("钥匙" in msg or "key" in msg.lower()):
            ok.append("B 没钥匙时说得清：" + msg[:60])
        else:
            red.append("B 没钥匙时没说清（HTTP %s · need_key=%s · %s）"
                       % (code, ask.get("need_key"), msg[:120] or str(ask)[:120]))

        # ---- C 装上钥匙，真出一份 PDF ----
        src = Path(os.path.expanduser("~")) / ".pluma" / "api.json"
        if not src.is_file():
            red.append("C 没查成：本机没有 %s（判据需要一把真钥匙）" % src)
        else:
            shutil.copy2(src, f.home / "api.json")
            pdf = f.app / "DEMO" / "01_讲义" / "D01_一份讲义是怎么出来的_讲义.pdf"
            before = pdf.stat().st_mtime if pdf.is_file() else 0
            code, g2 = http_json(base + "/api/generate", timeout=600,
                                 body={"lesson": "D01", "course": "DEMO", "form": "single", "lang": "zh"})
            log2 = str(g2.get("log") or "")
            if "打印失败" in log2:
                red.append("C 打印失败：" + log2.split("打印失败")[-1].strip().splitlines()[0][:100])
            elif not pdf.is_file() or pdf.stat().st_mtime <= before:
                red.append("C 没出 PDF：ok=%s · %s" % (g2.get("ok"), log2[-200:].replace("\n", " / ")))
            else:
                ok.append("C 真出 PDF：%.0f KB · ok=%s" % (pdf.stat().st_size / 1024, g2.get("ok")))

        # ---- D 版本检查不许 403 ----
        code, up_j = http_json(base + "/api/update?force=1", timeout=60)
        if code == 200 and up_j.get("ok"):
            ok.append("D 版本检查：current %s · latest %s" % (up_j.get("current"), up_j.get("latest")))
        else:
            red.append("D 版本检查 HTTP %s：%s" % (code, str(up_j)[:120]))
    finally:
        f.cleanup(a.keep)

    return _report(ok, red)


def _report(ok: list, red: list) -> int:
    for x in ok:
        print("  [绿] " + x)
    for x in red:
        print("  [红] " + x)
    print("结论：%d/%d 绿 · %d 红" % (len(ok), len(ok) + len(red), len(red)))
    return 0 if not red else 1


if __name__ == "__main__":
    sys.exit(main())
