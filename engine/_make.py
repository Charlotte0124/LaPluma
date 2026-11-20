# -*- coding: utf-8 -*-
"""一讲一条命令：生成 HTML → 术语每节首次附英 → 内容门 → 打 PDF → 版式门。

    python engine\\_make.py L02

为什么用 Python 而不是 .ps1：本仓的 .ps1 必须是 UTF-8 with BOM，随手写会按 GBK 读中文；
Python 源文件是 UTF-8 无 BOM，照原样就能跑。

2026-11-17：改成「进程内调用」（打包改造的第二半）
    原来这道流程用 subprocess + sys.executable 去跑 audit_lesson.py 与 html2pdf.py。
    源码下没毛病；冻结成 exe 后 sys.executable 就是 exe 自己，等于生成一次再开一个软件，
    还会顶掉本地界面的单实例。现在换成 import + 直接调它们的 main(argv)：
      · make() 是给界面调的入口（emit 收日志，返回退出码）
      · main() 是命令行入口，只是把日志打到屏幕
"""
from __future__ import annotations

import importlib
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import paths  # noqa: E402  路径双根，见仓根 paths.py

# 只读资源（tools\\print 下的检查器与打印器）走 RES_ROOT；课程数据与生成物走 DATA_ROOT
sys.path.insert(0, paths.res('tools', 'print'))
sys.path.insert(0, paths.res('engine'))
ROOT = paths.DATA_ROOT
# 2026-11-17：课程代码不再写死（示例课程 / 截图演示用 PLUMA_COURSE 切，默认仍是 CS340）
COURSE = os.environ.get("PLUMA_COURSE") or "CS340"

from terms import attach_first_per_section  # noqa: E402
from _split_long import split_long  # noqa: E402


def _call(modname: str, argv: list) -> tuple[int, str]:
    """在进程内跑 tools\\print 下的脚本，返回 (退出码, 它打印的内容)。

    它们都是「argparse + main() 返回退出码」的形状，所以只需要把 stdout 收进来；
    这样界面能把同一份日志回显给用户，而不用再起一个进程。
    """
    mod = importlib.import_module(modname)
    buf = io.StringIO()
    out, err = sys.stdout, sys.stderr
    sys.stdout = sys.stderr = buf
    try:
        rc = mod.main([str(x) for x in argv])
    finally:
        sys.stdout, sys.stderr = out, err
    return int(rc or 0), buf.getvalue()


def make(nos: list, course: str | None = None, emit=print, lang: str | None = None) -> int:
    """生成若干讲并过三道门。返回 0 = 全绿；非 0 = 有红项（日志在 emit 里）。

    2026-11-18：lang="en" 时用 <no>.en.py（DeepSeek 英文版），固定件与页脚也切英文；
    全英档不再跑「术语每节首次附英」（正文本来就是英文）。
    """
    global COURSE
    if course:
        COURSE = course
    import _build_讲义 as builder  # 中文模块名，靠 sys.path 直接 import
    builder.COURSE = COURSE          # 同一进程里切课程：数据目录跟着换
    cdir = paths.course_dir(COURSE)  # 读课件讲数据：先在数据根找，没有就用随程序发布的那份
    out_dir = paths.data(COURSE)     # 生成物一律写数据根（exe 旁边；源码下就是仓内）

    for no in nos:
        emit('=' * 60)
        emit('## %s' % no)
        lesson = builder.load(no, lang)
        llang = builder._lang_of(lesson)
        # 2026-11-19：拦住「把骨架当成品」——占位数据不再能直接渲染出 PDF
        if lesson.get("stub") or "正文待补" in str(lesson.get("sub") or ""):
            emit("[停] %s 还是导入占位，没有正文；先让 DeepSeek 补正文：" % no)
            emit("     python engine\\_draft.py %s --course %s --lang %s" % (no, COURSE, llang))
            emit("     （界面上点「开始生成」会自动先补；补完再渲染）")
            return 1
        if lang == "en" and llang != "en":
            emit('[停] 这一讲还没有英文版（%s.en.py）：先在「输出模式」里选全英并点生成，或先跑 engine\\_draft.py %s --lang en' % (no, no))
            return 1
        src = os.path.join(out_dir, '06_笔记', '%s_零基础_讲义_源.html' % no)
        html = builder.build(lesson)
        if builder.MISSING:
            emit('缺图 %d 张：%s' % (len(builder.MISSING), '、'.join(builder.MISSING[:4])))
            if builder.ASSETS:
                emit('  图片目录（%s）：%s' % (builder.ASSETS_FROM, builder.ASSETS))
            else:
                emit('  没找到课件图目录。用这条指定：python tools\\assets.py --set %s "<课件图目录>"'
                     % lesson['code'])
            emit('[停] 缺图不打——先补图或改讲法（把那张图换成自绘结构图）')
            return 1
        if llang == "en":
            html2, n = html, 0          # 全英档：正文已是英文，不再插「（English）」
        else:
            html2, n = attach_first_per_section(html)
        html2, ns = split_long(html2)
        os.makedirs(os.path.dirname(src), exist_ok=True)
        open(src, 'w', encoding='utf-8').write(html2)
        emit('生成 %s（%d 字符，术语附英 %d 处，拆长段 %d 处）'
             % (os.path.basename(src), len(html2), n, ns))

        rc, out = _call('audit_lesson', ['--content', '--file', src])
        emit(out.strip())
        if rc != 0:
            emit('[停] 内容门未过，先修源')
            return 1

        pdf = os.path.join(out_dir, '01_讲义', lesson['out'])
        foot_title = lesson.get('en') if llang == 'en' else lesson.get('zh')
        rc, out = _call('html2pdf', [src, '-o', pdf, '--theme', 'dark', '--toc',
                                     '--bg', '#0E0E0C',
                                     '--footer', '%s %s · %s' % (lesson['code'], no, foot_title)])
        # 2026-11-21：原来只回显最后一行——打印失败时那行正好是空行，
        #   界面上只剩「[停] 打印失败」，连 Chrome 的退出码和命令都看不到（用户没法报，我也没法查）。
        #   现在把 tail 的最后几行原样给出来。
        tail = [ln for ln in (out or '').strip().splitlines() if ln.strip()]
        emit('\n'.join(tail[-6:]) if tail else '(no output)')
        if rc != 0:
            emit('[停] 打印失败')
            return 1

        rc, out = _call('audit_lesson', [COURSE])
        head = [l for l in out.strip().splitlines()
                if lesson['out'] in l or l.strip().startswith(('OK', 'WARN', 'FAIL', '✗', '!'))]
        emit('\n'.join(head))
        # 版式门这里只报不改退出码（与改前一致）：红项会打印出来，人看到红自己改；
        # 是否改成「红即非 0」属于口径变更，得单独定，不夹在这次打包改造里。
    return 0


def main(argv: list) -> int:
    # 2026-11-18：--lang en 走英文数据（<no>.en.py）与英文固定件
    lang = None
    argv = list(argv)
    if "--lang" in argv:
        i = argv.index("--lang")
        lang = argv[i + 1] if i + 1 < len(argv) else "zh"
        argv = argv[:i] + argv[i + 2:]
    if not argv:
        print('用法: python engine\\_make.py L02 [L03 ...] [--lang zh|en]')
        return 2
    return make(argv, lang=lang)


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))