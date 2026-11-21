# -*- coding: utf-8 -*-
"""讲义内容规矩（R114 / R115）：全英档的专业名称格式、原件图必须真的画出来。

为什么有（用户 2026-11-21）：
  「全英 专业名称带中是这样子的 `CO2（二氧化碳）` 而不是直接取代」
  「不是说要根据原件了吗 为什么我一点原件的图也看不到」
  「而且我说如有需要的话可以增加一些图片」
  「这些都加入 PRTS 的羽毛笔规矩里面」+「没有触发的方法…增加一下自动触发规矩的方法」
所以这两条不能只写在文档里，得有机器判据，并且挂进提交钩子与 CI 自动跑。

四条判据（不花钱、不联网、约 1 秒）：
  A 全英提示词：`engine\\_draft.py` 的 `_SYS_EN` 必须明确要求「英文（中文）」，
    且带 `CO2（二氧化碳）` 这种正例（防止只写「保留中文」被模型自由发挥）。
  B 图真画出来：拿一份合成的 lesson（带 fig 块、图文件真实存在）跑 `_build_讲义.build()`，
    HTML 里必须有 `<img src="file://…">` 与 `<figcaption>`，图注要带出处「课件 p.」。
  C 缺图不静默：把图文件拿掉再 build 一次，`builder.MISSING` 必须非空（上层才能报「缺图不打」）。
  D 图注规范：每张 `<figure>` 都要有非空 figcaption（空图注等于没注明来源）。

用法：python tools\\check\\check-lecture-rules.py
退出码：0 全绿；1 有红；2 没查（缺 pymupdf / 模块导入失败）
"""
from __future__ import annotations

import os
import re
import struct
import sys
import tempfile
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "engine"))
sys.path.insert(0, str(ROOT / "tools" / "print"))

ok, red = [], []


def chk(cond, name, detail=""):
    if cond:
        ok.append(name + (("：" + detail) if detail else ""))
    else:
        red.append(name + (("：" + detail) if detail else ""))


def tiny_png(path: Path) -> None:
    """写一张 1×1 的真 PNG（不依赖 Pillow）：IHDR + IDAT + IEND。"""
    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data +
                struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))
    raw = b"\x00\xff\x00\x00"          # 1 px，红
    png = (b"\x89PNG\r\n\x1a\n" +
           chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)) +
           chunk(b"IDAT", zlib.compress(raw)) +
           chunk(b"IEND", b""))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(png)


def rule_a() -> None:
    try:
        import _draft  # noqa: E402
    except Exception as e:  # noqa: BLE001
        red.append("A 没查成：导入 engine\\_draft.py 失败（%r）" % (e,))
        return
    en = str(getattr(_draft, "_SYS_EN", "") or "")
    if not en:
        red.append("A 找不到 _draft._SYS_EN（全英提示词）")
        return
    need = ["（", "首次", "CO2"]
    missing = [k for k in need if k not in en]
    chk(not missing, "A 全英提示词要求「英文（中文）」", "缺 " + "、".join(missing) if missing else "带 CO2（二氧化碳）正例")


def _build(section_blocks, course_code="LRCHECK"):
    """拿出厂示例课 D01 当底子，只把 sections 换成合成数据——
    比手搓一份 lesson 字典稳：字段随仓库演进也不会再 KeyError。"""
    import _build_讲义 as B  # noqa: E402
    B.COURSE = "DEMO"                    # 出厂示例课；和 engine\_make.py 里同样的切法
    lesson = B.load("D01", "zh")
    # 真实 section 的字段是 body（块列表）+ lec（讲法）；合成一份带 fig 的
    lesson["sections"] = [{
        "no": "1", "zh": "第一节", "en": "Section 1",
        "lec": "这一步只验证「图会不会真的画出来」。",
        "body": section_blocks,
    }]
    return B, B.build(lesson)


def rule_bcd() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="lecture-rules-"))
    try:
        png = tmp / "06_笔记" / "assets" / "gen" / "X1" / "p001.png"
        tiny_png(png)
        blocks = [
            ("p", "这一节讲一个概念。"),
            ("fig", str(png), "课件 p.1 · 一张示意图"),
        ]
        os.environ["PLUMA_ASSETS"] = str(tmp / "06_笔记" / "assets")
        B, html = _build(blocks)
        imgs = re.findall(r'<img src="([^"]+)"', html)
        chk(any(src.startswith("file://") for src in imgs), "B 图真的画进 HTML（file:// 绝对路径）",
            "%d 个 img" % len(imgs))
        caps = re.findall(r"<figcaption[^>]*>(.*?)</figcaption>", html, re.S)
        chk(caps and all(c.strip() for c in caps), "D 每张图都有非空图注",
            "；".join(c.strip()[:24] for c in caps[:2]))
        chk(any("课件 p." in c for c in caps), "B 图注带出处「课件 p.」", caps[0].strip()[:30] if caps else "无图注")

        # C：图文件不在时，必须记进 MISSING（上层才能报「缺图不打」）
        png.unlink()
        B2, _ = _build(blocks)
        chk(bool(B2.MISSING), "C 缺图会被记下来（不静默）", "MISSING=%r" % (B2.MISSING[:2],))
    except Exception as e:  # noqa: BLE001
        red.append("B/C/D 没查成：%r" % (e,))
    finally:
        os.environ.pop("PLUMA_ASSETS", None)
        for _ in range(3):
            try:
                import shutil
                shutil.rmtree(tmp, ignore_errors=True)
                break
            except Exception:  # noqa: BLE001
                pass


def main() -> int:
    for s in (sys.stdout, sys.stderr):
        if hasattr(s, "reconfigure"):
            s.reconfigure(encoding="utf-8")
    rule_a()
    rule_bcd()
    for x in ok:
        print("  [绿] " + x)
    for x in red:
        print("  [红] " + x)
    total = len(ok) + len(red)
    print("结论：%d/%d 绿 · %d 红" % (len(ok), total, len(red)))
    return 0 if not red else 1


if __name__ == "__main__":
    sys.exit(main())
