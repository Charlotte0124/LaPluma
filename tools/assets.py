# -*- coding: utf-8 -*-
"""课件图片目录的设置与体检（讲义里 fig 块引用的是文件名，图本身不在软件仓）。

为什么要有这个：课件原图（按页裁的 jpg）留在了资料仓，软件仓里没有；
引用的图找不到时 Chrome 只会画一个 14×16 的缺图图标，成品看起来「有图」其实是白条。
所以图的目录得能配、能查、能说清是从哪儿读的。

用法
    python tools\\assets.py --list                  # 这门课现在读哪个目录、有多少张图
    python tools\\assets.py --check                 # 每讲的 fig 引用能不能全部找到（缺就退 1）
    python tools\\assets.py --set <课程> "<目录>"       # 写进 %USERPROFILE%\\.pluma\\assets.json
    python tools\\assets.py --unset <课程>             # 清掉本机配置（回到默认查找）

退出码：0 正常；1 --check 发现缺图；2 参数问题
"""
from __future__ import annotations

import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import paths  # noqa: E402  路径双根：资源根只读，课程数据在数据根
ROOT = paths.DATA_ROOT
sys.path.insert(0, paths.res('engine'))

import _build_讲义 as builder  # noqa: E402


def cfg_path() -> str:
    return os.path.join(os.path.expanduser('~'), '.pluma', 'assets.json')


def read_cfg() -> dict:
    try:
        with open(cfg_path(), encoding='utf-8') as f:
            return json.load(f) or {}
    except Exception:
        return {}


def lessons() -> list[str]:
    files = sorted(glob.glob(os.path.join(ROOT, paths.detect_course(), '_lessons', 'L*.py')))
    return [os.path.splitext(os.path.basename(f))[0] for f in files]


def fig_names(lesson: dict) -> list[str]:
    names = []
    for s in lesson['sections']:
        for b in s['body']:
            if b[0] == 'fig':
                names.append(b[1])
    return names


def main(argv: list[str]) -> int:
    for s in (sys.stdout, sys.stderr):
        if hasattr(s, 'reconfigure'):
            s.reconfigure(encoding='utf-8')

    if '--set' in argv:
        i = argv.index('--set')
        if len(argv) < i + 3:
            print('用法：python tools\\assets.py --set <课程> "<课件图目录>"')
            return 2
        code, path = argv[i + 1], argv[i + 2]
        if not os.path.isdir(path):
            print('目录不存在：%s' % path)
            return 2
        data = read_cfg()
        data[code] = os.path.abspath(path)
        os.makedirs(os.path.dirname(cfg_path()), exist_ok=True)
        with open(cfg_path(), 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print('已写 %s' % cfg_path())
        print('  %s → %s（本机文件，不入库存）' % (code, data[code]))
        return 0

    if '--unset' in argv:
        i = argv.index('--unset')
        data = read_cfg()
        code = argv[i + 1] if len(argv) > i + 1 else paths.detect_course()
        data.pop(code, None)
        with open(cfg_path(), 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print('已清掉 %s 的本机配置' % code)
        return 0

    if '--list' in argv:
        code = argv[argv.index('--list') + 1] if len(argv) > argv.index('--list') + 1 else paths.detect_course()
        path, src = builder.resolve_assets(code)
        print('%s 的课件图目录' % code)
        if path:
            n = len([f for f in os.listdir(path)
                     if f.lower().endswith(('.jpg', '.jpeg', '.png'))])
            print('  目录：%s' % path)
            print('  来源：%s' % src)
            print('  图数：%d 张' % n)
        else:
            print('  没找到（四档都没命中：~/.pluma/assets.json → courses.json → PLUMA_ASSETS → 软件仓默认）')
        print('  本机配置：%s' % cfg_path())
        return 0

    if '--check' in argv:
        bad = 0
        for no in lessons():
            lesson = builder.load(no)
            builder.use_course(lesson['code'])
            names = fig_names(lesson)
            miss = [n for n in names
                    if not (builder.ASSETS and os.path.isfile(os.path.join(builder.ASSETS, n)))]
            if not names:
                print('  —   %-6s 不引用图片（结构图自绘）' % no)
                continue
            if miss:
                bad += 1
                print('  缺  %-6s %d/%d 张找不到，例如 %s' % (no, len(miss), len(names), miss[0]))
            else:
                print('  过  %-6s %d 张全部找到' % (no, len(names)))
        if bad:
            print('\n%d 讲引用的图找不到。指定目录：python tools\\assets.py --set <课程> "<课件图目录>"' % bad)
            return 1
        print('\n全部能找到。')
        return 0

    print(__doc__)
    return 2


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
