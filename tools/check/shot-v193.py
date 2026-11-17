# -*- coding: utf-8 -*-
"""重拍 v1.9.3 的界面截图（示例课程 DEMO，1440x900）。

2026-11-17：本轮改了三处可见界面（文案口径 / 删除入口 / 阅读全屏），
check-ui-preview 的 A 项要求「改界面的提交必须带图」，D 项要求资产截图比 ui 新。
所以这里一次拍齐：主页 / 生成 / 抽屉 / 搜索 / 阅读深色 / 删除讲次 / 删除课程 / 队列取消。
不拍任何真实课程（CS340）——公开仓的图只能出现示例课程 DEMO。
"""
import asyncio
import os

from playwright.async_api import async_playwright

BASE = os.environ.get('PLUMA_SHOT_BASE', 'http://127.0.0.1:8765')
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(ROOT, 'docs', '资产')


async def main():
    async with async_playwright() as p:
        br = await p.chromium.launch(channel='msedge', headless=True)
        pg = await br.new_page(viewport={'width': 1440, 'height': 900})
        await pg.goto(BASE + '/?dbg=1&course=DEMO', wait_until='networkidle')
        await pg.wait_for_selector('.course', timeout=15000)
        # 只留示例课程：公开仓的截图里不能出现真实课程名
        await pg.evaluate("""() => {
            const p = window.__pluma;
            p.state().B.courses = p.state().B.courses.filter(c => c.code === 'DEMO');
            p.state().B.save_dir = 'out';
            p.render(); p.fillSelects();
            const o = document.querySelector('#outPath'); if (o) o.textContent = 'out';
        }""")
        await pg.wait_for_timeout(400)

        async def shot(name):
            # 2026-11-17：保存目录不能拍出本机路径（public-scan 与 R98 都判红）；toast 不留上一张的残影
            await pg.evaluate("""() => {
                const t = document.querySelector('#toast'); if (t) t.classList.remove('on');
                const o = document.querySelector('#outPath'); if (o) o.textContent = 'out';
            }""")
            await pg.wait_for_timeout(120)
            path = os.path.join(OUT, name)
            await pg.screenshot(path=path)
            print('%-28s %8d 字节' % (name, os.path.getsize(path)))

        # 1 主页（课程页，含卡片底部「删除」）
        await shot('界面-主页.png')

        # 2 搜索面板（未输字：最近搜索 + 清除记录）
        await pg.evaluate("() => localStorage.setItem('pluma.recent', JSON.stringify(['桃花源记','D02','总览']))")
        await pg.click('#btnFind')
        await pg.wait_for_timeout(350)
        await shot('界面-搜索.png')
        await pg.keyboard.press('Escape')
        await pg.keyboard.press('Escape')
        await pg.wait_for_timeout(250)

        # 3 抽屉（每行右侧「删除」——靠悬停才显示，先把鼠标停在一行上）
        await pg.evaluate("""() => {
            const p = window.__pluma;
            const c = p.state().B.courses.find(x => x.code === 'DEMO');
            p.openDrawer(c);
        }""")
        await pg.wait_for_timeout(500)
        rows = await pg.query_selector_all('#drFiles .f')
        if rows:
            await rows[0].hover()
        await pg.wait_for_timeout(300)
        await shot('界面-文件列表.png')
        await pg.click('#dveil')
        await pg.wait_for_timeout(300)

        # 4 生成页（讲次区「删除 / 全选」）
        await pg.evaluate("() => window.__pluma.showPage('generate')")
        await pg.wait_for_timeout(300)
        sel = await pg.query_selector('#courseSel')
        await sel.select_option('DEMO')
        await pg.wait_for_timeout(300)
        await shot('界面-生成.png')

        # 5 讲次删除模式（讲号右上角红 ×）
        await pg.click('#lsnDel')
        await pg.wait_for_timeout(350)
        await shot('界面-删除讲次.png')

        # 6 队列取消（造两个假队列项：一个跑着、一个已取消）
        await pg.evaluate("""() => {
            const p = window.__pluma;
            p.queue().push({course:'DEMO', lesson:'D01', st:'run'},
                           {course:'DEMO', lesson:'D02', st:'wait'});
            p.renderQueue();
            p.cancelQueueItem(p.queue()[1]);
        }""")
        await pg.wait_for_timeout(400)
        await shot('界面-队列取消.png')
        await pg.evaluate("() => { const p = window.__pluma; p.queue().length = 0; p.renderQueue(); }")
        await pg.click('#lsnDel')          # 退出删除模式
        await pg.wait_for_timeout(250)

        # 7 整门删除确认弹窗（只拍，不点确认；并先卸掉确认按钮的动作，防止误点真删）
        await pg.evaluate("""() => {
            const p = window.__pluma;
            const src = p.state().B.courses.find(c => c.code === 'DEMO');
            if (!src) return;
            p.askDeleteCourse(Object.assign({}, src));
            const yes = document.querySelector('#dlYes');
            if (yes) yes.onclick = () => {};   // 拍图用：点不到真删除
        }""")
        await pg.wait_for_timeout(400)
        await shot('界面-删除课程.png')
        await pg.click('#dlNo')
        await pg.wait_for_timeout(300)

        # 8 阅读页深色（含「全屏」按钮）
        await pg.goto(BASE + '/?dbg=1&theme=dark&code=DEMO&pdf=DEMO%2F01_%E8%AE%B2%E4%B9%89%2FD02_%E6%A1%83%E8%8A%B1%E6%BA%90%E8%AE%B0_%E8%AE%B2%E4%B9%89.pdf',
                      wait_until='networkidle')
        await pg.wait_for_selector('#pdfcanvas', timeout=20000)
        await pg.wait_for_timeout(1800)
        await shot('界面-阅读-深色.png')
        await pg.wait_for_timeout(200)
        await br.close()


asyncio.run(main())
