# -*- coding: utf-8 -*-
"""补齐 check-ui-preview 里需要交互的界面截图（2026-11-19）。

    python tools\check\shot-rest.py --base http://127.0.0.1:8810

只用示例课程 DEMO，保存目录显示 out；不拍真实课件名与本机路径。
"""
from __future__ import annotations

import argparse
import json
import os
import urllib.parse

from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(ROOT, "docs", "资产")

MSGS = [
    {"role": "user", "text": "这份讲义里散剂的粒度要求是什么？", "at": ""},
    {"role": "a", "text": "一般散剂通过 6 号筛的细粉不少于 95%；眼用散全部通过 9 号筛（200 目，75 μm）。",
     "refs": [{"course": "DEMO", "lesson": "D02", "sec": "2", "title": "散剂与粒度", "kind": "p",
               "pages": ["课件 p.13"], "text": "…"}],
     "meta": "出自 §2 散剂与粒度｜D02｜DeepSeek 4.1 Flash · 0.8s"},
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8810")
    a = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)

    with sync_playwright() as p:
        br = p.chromium.launch(channel="msedge", headless=True)
        pg = br.new_page(viewport={"width": 1440, "height": 900})

        def prep():
            pg.evaluate("""() => {
                const s = window.__pluma && window.__pluma.state();
                if(!s) return;
                s.B.courses = s.B.courses.filter(c => c.code === 'DEMO');
                s.B.save_dir = 'out';
                window.__pluma.render(); window.__pluma.fillSelects();
                const o = document.querySelector('#outPath'); if(o) o.textContent = 'out';
            }""")

        def shot(name):
            pg.evaluate("""() => {
                const t = document.querySelector('#toast'); if(t) t.classList.remove('on');
                const o = document.querySelector('#outPath'); if(o) o.textContent = 'out';
            }""")
            pg.wait_for_timeout(250)
            pg.screenshot(path=os.path.join(OUT, name))
            print("%-28s %8d" % (name, os.path.getsize(os.path.join(OUT, name))))

        # 1 设置
        pg.goto(a.base + "/?dbg=1&course=DEMO&settings=1", wait_until="networkidle")
        pg.wait_for_timeout(700); prep(); pg.wait_for_timeout(300); shot("界面-设置.png")

        # 2 搜索-最近
        pg.goto(a.base + "/?dbg=1&course=DEMO", wait_until="networkidle")
        pg.evaluate("localStorage.setItem('pluma.recent', JSON.stringify(['桃花源记','D02','总览']))")
        pg.reload(wait_until="networkidle"); prep()
        pg.click("#btnFind"); pg.wait_for_timeout(700); shot("界面-搜索-最近.png")

        # 3 会话（拦截 session，造两条示例消息）
        def session_route(route):
            if route.request.method == "GET":
                route.fulfill(status=200, content_type="application/json",
                              body=json.dumps({"code": "DEMO", "messages": MSGS, "updated": "2026-11-19 09:00"}, ensure_ascii=False))
            else:
                route.continue_()

        pg.route("**/api/session**", session_route)
        pg.goto(a.base + "/?dbg=1&course=DEMO&chat=DEMO", wait_until="networkidle")
        pg.wait_for_timeout(900); prep(); pg.wait_for_timeout(300); shot("界面-会话.png")
        pg.evaluate("document.documentElement.dataset.theme='dark'"); pg.wait_for_timeout(500); shot("界面-会话-深色.png")
        pg.evaluate("document.documentElement.dataset.theme='light'")

        # 4 笔记多选（同一会话，勾选全部消息）
        boxes = pg.query_selector_all(".m .pick")
        for b in boxes:
            b.click()
        pg.wait_for_timeout(500); shot("界面-笔记多选.png")

        # 5 导出笔记（选完后点生成笔记）
        pg.click("#btnNote"); pg.wait_for_timeout(900); shot("界面-导出笔记.png")
        pg.keyboard.press("Escape"); pg.wait_for_timeout(300)

        # 6 阅读（示例课程 D01 成品）
        pdf = "DEMO/01_讲义/D01_一份讲义是怎么出来的_讲义.pdf"
        q = urllib.parse.quote(pdf, safe="")
        pg.goto(a.base + "/?dbg=1&course=DEMO&pdf=" + q + "&code=DEMO&theme=light", wait_until="networkidle")
        pg.wait_for_timeout(2200); prep(); pg.wait_for_timeout(500); shot("界面-阅读.png")

        # 7 导出 / 合订本（课程卡右下角）
        pg.goto(a.base + "/?dbg=1&course=DEMO", wait_until="networkidle")
        prep(); pg.wait_for_timeout(300)
        pg.click(".course .expbtn"); pg.wait_for_timeout(600); shot("界面-导出.png")
        pg.click('#exMode [data-ex="book"]'); pg.wait_for_timeout(400); shot("界面-导出-合订本.png")
        pg.keyboard.press("Escape"); pg.wait_for_timeout(300)

        # 8 余额不足（拦 /api/ask 回 402 语义）
        pg2 = br.new_page(viewport={"width": 1440, "height": 900})
        pg2.route("**/api/ask", lambda r: r.fulfill(
            status=200, content_type="application/json",
            body=json.dumps({"ok": False, "need_money": True, "balance": {"ok": True, "balance": "0.00"},
                             "cost_est": "约 ¥0.02", "model": "deepseek-flash", "refs": []})))
        pg2.goto(a.base + "/?dbg=1&course=DEMO&chat=DEMO", wait_until="networkidle")
        pg2.wait_for_timeout(900)
        pg2.fill("#chatQ", "这一讲的粒度要求是什么？")
        pg2.click("#btnSend"); pg2.wait_for_timeout(900)
        pg2.screenshot(path=os.path.join(OUT, "界面-余额不足.png"))
        print("%-28s %8d" % ("界面-余额不足.png", os.path.getsize(os.path.join(OUT, "界面-余额不足.png"))))
        pg2.close()

        # 9 访问码（拦 /api/host 返回已上线状态，不真开端口）
        pg.route("**/api/host", lambda r: r.fulfill(
            status=200, content_type="application/json",
            body=json.dumps({"lan": True, "code": "12345678", "url_local": "http://127.0.0.1:8765",
                             "url_lan": "http://192.0.2.10:8765"}, ensure_ascii=False)))
        pg.goto(a.base + "/?dbg=1&course=DEMO&page=host", wait_until="networkidle")
        pg.wait_for_timeout(900); prep(); pg.wait_for_timeout(300); shot("界面-访问码.png")

        # 10 生成页语言档
        for lang, name in (("zh", "界面-生成-语言档-全中.png"), ("en", "界面-生成-语言档-全英.png")):
            pg.goto(a.base + "/?dbg=1&course=DEMO&page=generate&savedir=out&lang=" + lang, wait_until="networkidle")
            pg.wait_for_timeout(800); prep(); pg.wait_for_timeout(400); shot(name)

        br.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
