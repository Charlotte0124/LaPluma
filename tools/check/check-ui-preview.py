# -*- coding: utf-8 -*-
r"""check-ui-preview.py — 界面改动必须先有预览图（2026-11-16 立）

为什么有这条：
    2026-11-16 20:20 的提交 6b67d15 把「成品形态（单本/合订本）」与「问课件」两块界面
    直接落库，用户此前没看过任何图，事后问「不是说会给我渲染图的吗」。
    真因不是忘了，是**仓里没有这条规矩、也没有任何检查能变红**：
    三道门只查讲义（源/内容/版式），README 由 sync-readme 刷，没有一条看 ui\。
    现在把规矩写成文件（AGENTS.md）+ 判据（本脚本），漏了就红。

判据（红 = 规矩被破）：
    A 红：最后一次改动 ui\ 的提交里，既没带 docs\预览（设计稿/登记表）也没带 docs\资产（真实截图）
          —— 改界面而没留图。
          （2026-11-16 修正：原来比的是「提交时间先后」，会把「先出图、后改码」这一正确
            流程判红；改成看**同一次提交里带了什么**。代价是：如果图与码分成两个提交，
            会红 —— 规矩因此写成「预览稿/截图与界面改动放同一个提交」。）
    B 红：docs\预览 里的 png 没在 README.md 登记（孤儿图，别人不知道它解决什么）；
          或预览目录存在却一张图都没有；或缺 README.md。
    C 黄：工作区里 ui\ 有未提交改动，而 docs\预览 没有 —— 正在改界面，图还没出。
    D 黄：docs\资产\界面-*.png（已实现界面的截图）比 ui 旧 —— 忘了重拍。

用法：
    python tools\check\check-ui-preview.py                 # 判本仓
    python tools\check\check-ui-preview.py --root <目录>    # 判指定目录（拿副本造坏用）
    python tools\check\check-ui-preview.py --selftest      # 临时仓造坏，先证明它会红

退出码：0 = 绿（或只有黄）· 1 = 红 · 2 = 没查（git 不可用 / 不是仓库）
"""
import os
import shutil
import subprocess
import sys
import tempfile
import time

UI = 'ui'
PREV = os.path.join('docs', '预览')
ASSET = os.path.join('docs', '资产')


def git(repo, *args):
    cmd = ['git', '-c', 'core.quotepath=false'] + list(args)
    try:
        p = subprocess.run(cmd, cwd=repo, capture_output=True, text=True,
                           encoding='utf-8', errors='replace')
    except FileNotFoundError:
        return None, '', 'git 不可用'
    return p.returncode, (p.stdout or '').strip(), (p.stderr or '').strip()


def last_ts(repo, path):
    """该路径最后一次提交的 unix 时间；未跟踪或没记录 → None。"""
    rc, out, _ = git(repo, 'log', '-1', '--format=%ct', '--', path)
    if rc is None or rc != 0 or not out.isdigit():
        return None
    return int(out)


def dirty(repo, path):
    rc, out, _ = git(repo, 'status', '--porcelain', '--', path)
    return bool(rc == 0 and out)


def commit_files(repo, rev):
    """某次提交动了哪些路径（相对仓根，正斜杠）。"""
    rc, out, _ = git(repo, 'show', '--name-only', '--format=', rev)
    if rc != 0 or not out:
        return []
    return [line.strip() for line in out.splitlines() if line.strip()]


def fmt(ts):
    return time.strftime('%Y-%m-%d %H:%M', time.localtime(ts)) if ts else '（无提交记录）'


def run(root):
    """返回 (reds, yellows, notes)。"""
    red, yel, note = [], [], []
    ui_dir = os.path.join(root, UI)
    prev_dir = os.path.join(root, PREV)
    asset_dir = os.path.join(root, ASSET)

    if not os.path.isdir(ui_dir):
        return ['没有 ui\\ 目录：这不是羽毛笔仓，或目录给错了'], [], note

    t_ui = last_ts(root, UI)
    t_prev = last_ts(root, PREV) if os.path.isdir(prev_dir) else None
    note.append('ui/ 最后提交 %s · docs\\预览 最后提交 %s' % (fmt(t_ui), fmt(t_prev)))

    # —— A：最后一次改界面的提交里，有没有给图留痕（同提交必须带 docs\预览 或 docs\资产）
    if not os.path.isdir(prev_dir):
        red.append('A 没有 docs\\预览 目录：设计稿无处可放，等于这条规矩不存在')
    elif t_ui:
        rev = git(root, 'log', '-1', '--format=%H', '--', UI)[1]
        files = [f.replace('\\', '/') for f in commit_files(root, rev)]
        touched = [f for f in files if f.startswith('docs/预览') or f.startswith('docs/资产')]
        note.append('最后一次界面提交 %s（%s）带图 %d 个' % (rev[:7] or '?', fmt(t_ui), len(touched)))
        if not touched:
            red.append('A 界面提交 %s（%s）里没带图：预览稿或真实截图要与界面改动放同一个提交'
                       % (rev[:7] or '?', fmt(t_ui)))

    # —— B：孤儿图 / 空目录 / 缺登记
    if os.path.isdir(prev_dir):
        pngs = sorted(f for f in os.listdir(prev_dir) if f.lower().endswith('.png'))
        readme = os.path.join(prev_dir, 'README.md')
        has_readme = os.path.exists(readme)
        txt = ''
        if has_readme:
            with open(readme, encoding='utf-8', errors='replace') as fh:
                txt = fh.read()
        if not pngs:
            red.append('B docs\\预览 里一张图都没有：界面改动没有可看的稿')
        if pngs and not has_readme:
            red.append('B 缺 docs\\预览\\README.md：图没有登记，别人不知道它解决什么')
        for name in pngs:
            if has_readme and name not in txt:
                red.append('B 孤儿图：%s 没在 docs\\预览\\README.md 里登记' % name)
        note.append('预览图 %d 张' % len(pngs))

    # —— C：界面在改，图没跟着动
    if dirty(root, UI) and not dirty(root, PREV):
        yel.append('C ui/ 有未提交改动，docs\\预览 没动 —— 正在改界面？图记得一起出')

    # —— D：已实现截图忘了重拍
    if os.path.isdir(asset_dir) and t_ui:
        stale = []
        for name in sorted(os.listdir(asset_dir)):
            if name.startswith('界面-') and name.lower().endswith('.png'):
                t = last_ts(root, os.path.join(ASSET, name))
                if t and t < t_ui:
                    stale.append(name)
        if stale:
            yel.append('D 已实现界面截图比 ui/ 旧（%s）：重拍一张放 docs\\资产'
                       % '、'.join(stale))

    return red, yel, note


def _w(path, text=''):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write(text)


def _png(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as fh:
        fh.write(b'\x89PNG\r\n\x1a\n' + b'\x00' * 64)


def _commit(repo, msg, when=None):
    env = os.environ.copy()
    if when is not None:
        stamp = '%d +0800' % when
        env['GIT_AUTHOR_DATE'] = stamp
        env['GIT_COMMITTER_DATE'] = stamp
    subprocess.run(['git', 'add', '-A'], cwd=repo, capture_output=True, env=env)
    subprocess.run(['git', 'commit', '-m', msg, '--allow-empty'], cwd=repo,
                   capture_output=True, env=env)


def selftest():
    """拿临时仓造四种坏：判据必须分别变红 / 变黄。"""
    tmp = tempfile.mkdtemp(prefix='pluma-uiprev-')
    repo = os.path.join(tmp, 'repo')
    os.makedirs(repo)
    steps = []

    def init():
        git(repo, 'init', '-q')
        git(repo, 'config', 'user.email', 't@example.com')
        git(repo, 'config', 'user.name', 't')

    try:
        init()
        # 1) 界面与预览图同一次提交 → 期望绿
        _w(os.path.join(repo, 'ui', 'index.html'), '<b>v1</b>')
        _w(os.path.join(repo, 'docs', '预览', 'README.md'), '01-a.png\n')
        _png(os.path.join(repo, 'docs', '预览', '01-a.png'))
        _commit(repo, 'step1', when=1700000000)
        r, y, _ = run(repo)
        steps.append(('同提交带图 → 绿', not r, r))

        # 2) 只改界面、不带新图 → 期望红 A
        time.sleep(1.1)
        _w(os.path.join(repo, 'ui', 'index.html'), '<b>v2</b>')
        _commit(repo, 'step2', when=1700000100)
        r, y, _ = run(repo)
        steps.append(('改界面不带图 → 红 A', any(x.startswith('A') for x in r), r))

        # 3) 补一张没登记的图 → 期望红 B
        _png(os.path.join(repo, 'docs', '预览', '02-b.png'))
        _commit(repo, 'step3', when=1700000200)
        r, y, _ = run(repo)
        steps.append(('未登记图 → 红 B', any(x.startswith('B') for x in r), r))

        # 3b) 把那张图登记进 README → 期望红 B 消失（证明 B 判的是「有没有登记」，不是「有没有新图」）
        #     不做这一步，下一步会带着 B 的红去判 C，把「黄里夹红」误报成不按预期（第一版就错在这）
        _w(os.path.join(repo, 'docs', '预览', 'README.md'), '01-a.png\n02-b.png\n')
        _commit(repo, 'step3b', when=1700000300)
        r, y, _ = run(repo)
        # 只验「B 消失」：A 还红是对的——上一次界面提交（step2）确实没带图
        steps.append(('登记该图后 → 红 B 消失', not any(x.startswith('B') for x in r), r))

        # 3c) 改界面且同提交带图 → 期望全绿（把 A 清掉，证明「图与码同一提交」能过）
        _w(os.path.join(repo, 'ui', 'index.html'), '<b>v2b</b>')
        _w(os.path.join(repo, 'docs', '预览', 'README.md'), '01-a.png\n02-b.png\n（v2b 对应）\n')
        _commit(repo, 'step3c', when=1700000400)
        r, y, _ = run(repo)
        steps.append(('图与码同一提交 → 绿', not r, r))

        # 4) 界面有未提交改动 → 期望黄 C（不算红）
        _w(os.path.join(repo, 'ui', 'index.html'), '<b>v3</b>')
        r, y, _ = run(repo)
        steps.append(('界面未提交 → 黄 C', (not r) and any(x.startswith('C') for x in y), y))

        # 5) 删掉预览目录 → 期望红 A
        shutil.rmtree(os.path.join(repo, 'docs', '预览'))
        r, y, _ = run(repo)
        steps.append(('删预览目录 → 红 A', any(x.startswith('A') for x in r), r))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    ok = True
    for label, good, detail in steps:
        print('  [%s] %s' % ('过' if good else '红', label))
        if not good:
            ok = False
            for line in detail:
                print('       未按预期：' + line)
    print('自测：%d 项 %s' % (len(steps), '全按预期' if ok else '有不符'))
    return 0 if ok else 1


def main():
    args = sys.argv[1:]
    if '--selftest' in args:
        return selftest()
    root = os.getcwd()
    if '--root' in args:
        i = args.index('--root')
        if i + 1 < len(args):
            root = os.path.abspath(args[i + 1])
    if git(root, 'rev-parse', '--git-dir')[0] != 0:
        print('没查：%s 不是 git 仓库（跳过不等于通过）' % root)
        return 2
    red, yel, note = run(root)
    print('===== 界面预览图检查 =====')
    for line in note:
        print('  ' + line)
    for line in yel:
        print('  [黄] ' + line)
    for line in red:
        print('  [红] ' + line)
    print('结论：%d 红 · %d 黄' % (len(red), len(yel)))
    return 1 if red else 0


if __name__ == '__main__':
    sys.exit(main())
