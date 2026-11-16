# -*- coding: utf-8 -*-
"""压力测试：一门课很多讲义 / 很多门课。用完自动清理，结果写 _logs\\stress-last.json。

    python tools\\check\\stress.py --lessons 120      # 一门课塞 120 份讲义
    python tools\\check\\stress.py --courses 60       # 60 门课，每门 1-3 份讲义
    python tools\\check\\stress.py --all              # 两样都跑

为什么要它（PRTS 三之十二 §50）：界面的病在「量一上来」才露头——讲义一多列表就乱、
课程一多主页就滚不完。所以「能跑」不算完，得有一条命令把规模拉上去看。
不需要 Playwright 也能跑（只测接口与磁盘），有 Playwright 才拍图与量 DOM。

退出码：0 跑完并写出记录；2 环境不对（缺 python 包 / 端口被占）
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# 记录放 docs\（_logs 进了 .gitignore，放那儿等于换个克隆就判红）：这是给人和判据共读的证据
LOG_DIR = os.path.join(ROOT, "docs")
PORT = 8791
BASE = "http://127.0.0.1:%d" % PORT
TMP_PREFIX = "压力测试_"


def _free(port: int) -> bool:
    s = socket.socket()
    try:
        return s.connect_ex(("127.0.0.1", port)) != 0
    finally:
        s.close()


def _up() -> bool:
    try:
        urllib.request.urlopen(BASE + "/", timeout=1.5)
        return True
    except Exception:
        return False


def _pdf(path: str, pages: int) -> None:
    import pymupdf
    d = pymupdf.open()
    for _ in range(max(1, pages)):
        d.new_page()
    d.save(path)
    d.close()


def make_lessons(n: int) -> list[str]:
    """一门课里造 n 份讲义（含长文件名），返回课程目录名。"""
    name = TMP_PREFIX + "多讲义"
    d = os.path.join(ROOT, name)
    if os.path.isdir(d):
        shutil.rmtree(d)
    os.makedirs(os.path.join(d, "01_讲义"))
    os.makedirs(os.path.join(d, "_lessons"))
    for i in range(1, n + 1):
        tail = "进程调度与上下文切换的内存可见性问题" if i % 7 == 0 else "示例"
        _pdf(os.path.join(d, "01_讲义", "D%02d_%s第%d讲_讲义.pdf" % (i, tail, i)), 1 + i % 12)
    src = os.path.join(ROOT, "DEMO", "_lessons", "D01.py")
    if os.path.exists(src):
        shutil.copy2(src, os.path.join(d, "_lessons", "D01.py"))
    return [name]


def make_courses(n: int) -> list[str]:
    """n 门课，每门 1-3 份讲义。"""
    made = []
    for i in range(1, n + 1):
        name = "%s多课%02d" % (TMP_PREFIX, i)
        d = os.path.join(ROOT, name)
        if os.path.isdir(d):
            shutil.rmtree(d)
        os.makedirs(os.path.join(d, "01_讲义"))
        os.makedirs(os.path.join(d, "_lessons"))
        for k in range(1 + i % 3):
            _pdf(os.path.join(d, "01_讲义", "D%02d_第%d讲_讲义.pdf" % (k + 1, k + 1)), 3 + k)
        src = os.path.join(ROOT, "DEMO", "_lessons", "D01.py")
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(d, "_lessons", "D01.py"))
        made.append(name)
    return made


def probe() -> dict:
    """接口层：bootstrap 三次耗时 + 返回体大小。"""
    out = {"ms": [], "courses": 0, "kb": 0.0}
    for _ in range(3):
        t0 = time.time()
        body = urllib.request.urlopen(BASE + "/api/bootstrap", timeout=120).read().decode()
        out["ms"].append(round((time.time() - t0) * 1000))
        if not out["courses"]:
            data = json.loads(body)
            out["courses"] = len(data.get("courses") or [])
            out["kb"] = round(len(body) / 1024, 1)
    return out


def ui_probe(mode: str) -> dict:
    """界面层（有 Playwright 才做）：量 DOM 高度 / 行高种类 / 有无搜索。"""
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return {"skipped": "没装 playwright，界面层没测"}
    res = {}
    with sync_playwright() as p:
        br = p.chromium.launch(channel="msedge", headless=True)
        pg = br.new_page(viewport={"width": 1440, "height": 900})
        pg.goto(BASE + "/", wait_until="networkidle")
        time.sleep(2.2)
        res["courses_page"] = pg.evaluate("""()=>({
            cards: document.querySelectorAll('.course').length,
            pageH: document.body.scrollHeight,
            screens: +(document.body.scrollHeight / innerHeight).toFixed(1),
            hasSearch: !!document.querySelector('#page-courses input[placeholder*="找"]')})""")
        if mode == "lessons":
            pg.evaluate("""()=>{const cs=[...document.querySelectorAll('.course')];
                const k=cs.find(x=>x.innerText.includes('多讲义')); if(k) k.click();}""")
            time.sleep(1.2)
            res["drawer"] = pg.evaluate("""()=>{const f=document.querySelector('#drFiles');
                const rows=[...f.querySelectorAll('.f')];
                const h=rows.map(r=>Math.round(r.getBoundingClientRect().height));
                return {rows: rows.length, clientH: f.clientHeight, scrollH: f.scrollHeight,
                        rowHeights: new Set(h).size,
                        hasSearch: !!document.querySelector('#drFind')};}""")
        br.close()
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lessons", type=int, default=0, help="一 门课里造多少份讲义")
    ap.add_argument("--courses", type=int, default=0, help="造多少门课")
    ap.add_argument("--all", action="store_true", help="两者都跑（120 份 / 60 门）")
    a = ap.parse_args()
    if a.all:
        a.lessons, a.courses = max(a.lessons, 120), max(a.courses, 60)
    if not a.lessons and not a.courses:
        ap.print_help()
        return 2
    if not _free(PORT):
        print("端口 %d 被占，换个口再跑" % PORT)
        return 2

    report = {"at": time.strftime("%Y-%m-%d %H:%M"), "items": []}
    proc = subprocess.Popen([sys.executable, os.path.join(ROOT, "ui", "server.py"),
                             "--port", str(PORT), "--no-browser"],
                            cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            creationflags=0x08000000 if os.name == "nt" else 0)
    for _ in range(80):
        if _up():
            break
        time.sleep(0.4)
    made: list[str] = []
    try:
        if a.lessons:
            made += make_lessons(a.lessons)
            r = {"kind": "讲义数", "scale": a.lessons, "api": probe(), "ui": ui_probe("lessons")}
            print("讲义 %d 份：%s" % (a.lessons, json.dumps(r, ensure_ascii=False)))
            report["items"].append(r)
        if a.courses:
            made += make_courses(a.courses)
            r = {"kind": "课程数", "scale": a.courses, "api": probe(), "ui": ui_probe("courses")}
            print("课程 %d 门：%s" % (a.courses, json.dumps(r, ensure_ascii=False)))
            report["items"].append(r)
    finally:
        proc.terminate()
        try:
            proc.wait(8)
        except Exception:
            proc.kill()
        for name in made:
            shutil.rmtree(os.path.join(ROOT, name), ignore_errors=True)
        left = [x for x in os.listdir(ROOT) if x.startswith(TMP_PREFIX)]
        report["cleaned"] = not left

    os.makedirs(LOG_DIR, exist_ok=True)
    out = os.path.join(LOG_DIR, "stress-last.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print("记录：%s（清理干净：%s）" % (out, report["cleaned"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
