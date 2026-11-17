# -*- coding: utf-8 -*-
"""批量重拍界面截图（2026-11-17）。

    python tools\\check\\shot-ui.py                 # 只拍能靠 URL 参数直达的那些
    python tools\\check\\shot-ui.py -Only 主页,生成

为什么要有：`check-ui-preview.py` 一直有一条黄——「已实现界面截图比 ui/ 旧」。
界面改过之后图不换，别人看 README 看到的是旧样子。这个脚本把**能无交互直达**的状态
用无头 Chrome 重拍（URL 参数见下表），需要点开弹窗 / 进删除模式的那几张仍要人工，
脚本会把它们列出来，不假装拍过。

直达参数（`ui\\index.html` 里已有）：`?theme=light|dark`、`?page=generate|host`、
`?course=<码>`、`?wizard=N`、`?pdf=<相对路径>&code=<码>&to=N`、`?upd=demo`、`?win=1`
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
OUT = os.path.join(ROOT, "docs", "资产")
PORT = 8894
CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]

# (输出文件名, 查询串, 说明)
SHOTS = [
    ("界面-主页.png", "?theme=light", "课程首页（浅色）"),
    ("界面-主页-深色.png", "?theme=dark", "课程首页（深色）"),
    ("界面-生成.png", "?theme=light&page=generate&course=DEMO", "生成页"),
    ("界面-生成-导入.png", "?theme=light&page=generate&course=DEMO", "生成页（导入入口同一屏）"),
    ("界面-上线.png", "?theme=light&page=host", "上线页"),
    ("界面-上线-一键已开.png", "?theme=light&page=host", "上线页（按钮同屏）"),
    ("界面-首次配置.png", "?theme=light&wizard=1", "首次配置第 1 步"),
    ("界面-向导-保存目录.png", "?theme=light&wizard=3", "向导第 3 步（保存目录）"),
    ("界面-应用内更新卡.png", "?theme=light&upd=demo", "更新卡（应用内一键更新）"),
]
# 需要交互才能出现的界面：脚本不拍，列出来交给人（不假装拍过）
MANUAL = [
    "界面-会话.png / 界面-会话-深色.png（要开一门课的会话）",
    "界面-阅读.png / 界面-阅读-深色.png（要选一份成品 PDF；也可用 ?pdf= 直达，但需真实路径）",
    "界面-文件列表.png（点开课程卡抽屉）",
    "界面-搜索.png / 界面-搜索-最近.png（点放大镜）",
    "界面-设置.png（顶栏「设置」）",
    "界面-删除讲次.png / 界面-删除课程.png（进删除模式）",
    "界面-导出.png / 界面-导出-合订本.png / 界面-导出笔记.png",
    "界面-队列取消.png、界面-笔记多选.png",
    "界面-余额不足.png（需假接口返 402）、界面-访问码.png（需开上线并取码）",
]


def find_chrome() -> str:
    for c in CHROME_CANDIDATES:
        if os.path.isfile(c):
            return c
    return ""


def wait_up(secs: float = 25.0) -> bool:
    end = time.time() + secs
    while time.time() < end:
        try:
            urllib.request.urlopen("http://127.0.0.1:%d/api/bootstrap" % PORT, timeout=2).read()
            return True
        except Exception:  # noqa: BLE001
            time.sleep(0.3)
    return False


def main(argv: list | None = None) -> int:
    for s in (sys.stdout, sys.stderr):
        if hasattr(s, "reconfigure"):
            s.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="用无头 Chrome 批量重拍界面截图")
    ap.add_argument("-Only", default="", help="只拍名字里含这些词的（逗号分隔）")
    ap.add_argument("--width", type=int, default=1440)
    ap.add_argument("--height", type=int, default=900)
    a = ap.parse_args(argv)

    chrome = find_chrome()
    if not chrome:
        print("找不到 Chrome / Edge，没拍", file=sys.stderr)
        return 2
    os.makedirs(OUT, exist_ok=True)

    env = dict(os.environ)
    py = subprocess.Popen([sys.executable, "-X", "utf8", os.path.join(ROOT, "ui", "server.py"),
                           "--no-window", "--port", str(PORT), "--no-browser"],
                          cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        if not wait_up():
            print("服务没起来，没拍", file=sys.stderr)
            return 2
        picks = [s for s in SHOTS if not a.Only or any(k in s[0] for k in a.Only.split(","))]
        ok = 0
        for name, qs, why in picks:
            url = "http://127.0.0.1:%d/%s" % (PORT, qs)
            out = os.path.join(OUT, name)
            r = subprocess.run([chrome, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                                "--window-size=%d,%d" % (a.width, a.height),
                                "--screenshot=" + out, "--virtual-time-budget=6000", url],
                               capture_output=True)
            if os.path.isfile(out) and os.path.getsize(out) > 20000:
                ok += 1
                print("  已拍 %s（%d KB）· %s" % (name, os.path.getsize(out) // 1024, why))
            else:
                print("  失败 %s · %s" % (name, (r.stderr or b"").decode("utf-8", "replace")[-160:]))
        print("\n拍了 %d 张，写入 %s" % (ok, OUT))
        print("仍需人工的 %d 组：" % len(MANUAL))
        for m in MANUAL:
            print("  · " + m)
        return 0 if ok else 1
    finally:
        py.terminate()
        try:
            py.wait(timeout=8)
        except Exception:  # noqa: BLE001
            py.kill()


if __name__ == "__main__":
    raise SystemExit(main())
