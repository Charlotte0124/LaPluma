# -*- coding: utf-8 -*-
r"""check-shot-light.py — 截图一律用白天（浅色）模式（2026-11-27 用户定）

为什么有这条：用户 2026-11-27 定「截图一律以白天模式为标准」。界面默认是深色也能拍，
但深色图在文档、主页、项目台里都更难看清，而且同一批图深浅混着放，看的人分不清
「这是深色模式的演示」还是「这张恰好拍在深色下」。

判据：
    L1 红：docs\资产 里的界面截图平均亮度 < 100（几十张一色深底），
           且文件名里没有声明这是深色图（深色 / 夜间 / 暗）
    L2 黄：一张深色图都没有 —— 说明「深色模式」这件功能没图，
           要么补一张带「深色」的，要么这条判据被绕过

修法：用白天（浅色）模式重拍那张图；确实要展示深色模式的，文件名带「深色」。

用法：python tools\check\check-shot-light.py            # 查本仓 docs\资产
      python tools\check\check-shot-light.py a.png b.png  # 只查这几张（提交钩子传改动的图）
      python tools\check\check-shot-light.py --selftest  # 造图验判据本身
退出码：0 绿（或只有黄）· 1 红
"""
import glob
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SHOT_DIR = os.path.join(ROOT, "docs", u"资产")
DARK_MEAN = 100
DECLARED = re.compile(u"深色|夜间|暗")


def mean_luma(path):
    """平均亮度（0–255）：缩到 64×64 再取灰度均值，够判深浅，也不慢。"""
    from PIL import Image, ImageStat
    with Image.open(path) as im:
        small = im.convert("L").resize((64, 64))
    return ImageStat.Stat(small).mean[0]


def judge(items):
    """items = [(文件名, 平均亮度)] -> (红, 黄)。纯函数，selftest 直接喂。"""
    red = []
    declared = 0
    for name, m in sorted(items, key=lambda x: x[1]):
        if m >= DARK_MEAN:
            continue
        if DECLARED.search(name):
            declared += 1
            continue
        red.append(u"L1 %s 平均亮度 %.0f（< %d）——不是深色演示就别拍深色，用白天模式重拍"
                   % (name, m, DARK_MEAN))
    yel = []
    if items and not declared:
        yel.append(u"L2 一张声明「深色」的图都没有：深色模式这件功能在截图里看不见")
    return red, yel


def collect(dirpath):
    out = []
    for f in sorted(glob.glob(os.path.join(dirpath, u"界面-*.png")) + glob.glob(os.path.join(dirpath, u"产品介绍图*.png"))):
        try:
            out.append((os.path.basename(f), mean_luma(f)))
        except Exception as e:  # noqa: BLE001
            out.append((os.path.basename(f), -1.0))
    return out


def selftest():
    """造三张图：浅色合格 / 深色且文件名声明深色合格 / 深色没声明 —— 必须只红这一张。"""
    from PIL import Image
    import tempfile
    tmp = tempfile.mkdtemp(prefix="shot-light-")
    def make(name, v):
        Image.new("RGB", (80, 50), (v, v, v)).save(os.path.join(tmp, name))
    make(u"界面-白天.png", 240)
    make(u"界面-主页-深色.png", 18)
    make(u"界面-夜里拍的.png", 20)
    red, yel = judge(collect(tmp))
    ok = len(red) == 1 and u"夜里拍的" in red[0] and not [y for y in yel]
    print(u"[自测] 造 3 张：浅色 1 / 深色已声明 1 / 深色没声明 1")
    for x in red:
        print(u"  " + x)
    print(u"[自测] 结论：%s" % (u"按预期" if ok else u"不对——判据没在起作用"))
    return 0 if ok else 1


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()
    try:
        import PIL  # noqa: F401
    except Exception:  # noqa: BLE001
        print(u"[跳过] 没装 Pillow，这张检查没跑（不等于通过）：pip install Pillow")
        return 0
    only = [a for a in sys.argv[1:] if not a.startswith("-")]
    if only:
        items = []
        for f in only:
            path = f if os.path.isabs(f) else os.path.join(ROOT, f)
            if not os.path.exists(path):
                print(u"[黄] 这次没有查 %s（文件不在工作树里）" % f)
                continue
            try:
                items.append((os.path.basename(path), mean_luma(path)))
            except Exception:  # noqa: BLE001
                print(u"[黄] 读不出 %s（不是图片？）" % f)
        if not items:
            print(u"[跳过] 这次没有界面截图要查（不等于通过）")
            return 0
    else:
        items = collect(SHOT_DIR)
    if not items:
        print(u"[红] docs\资产 里一张界面截图都没有（%s）" % SHOT_DIR)
        return 1
    red, yel = judge(items)
    for x in red:
        print(u"[红] " + x)
    for x in yel:
        print(u"[黄] " + x)
    dark = [n for n, m in items if m < DARK_MEAN]
    print(u"扫了 %d 张 · 深色 %d 张（其中声明深色 %d 张）· 结论：%d 红 · %d 黄"
          % (len(items), len(dark), len(dark) - len(red), len(red), len(yel)))
    return 1 if red else 0


if __name__ == "__main__":
    raise SystemExit(main())
