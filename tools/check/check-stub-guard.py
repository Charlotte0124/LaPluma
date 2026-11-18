# -*- coding: utf-8 -*-
r"""占位骨架防护的回归：四条判据必须能红，也要能绿（2026-11-19）。

为什么要有它
    用户实测「导入 99 页课件 → 开始生成 → 出来 7 页占位」。修法不是只补一次正文，
    而是让「骨架」再也混不成「成品」。四条：
      ① 导入建骨架：数据必须带 "stub": true 与 "orig": <原件名>
      ② 渲染闸门：engine\_make.py 遇到占位必须停，不出 PDF
      ③ 内容门：见到「原件导入占位 / 正文待补」必须判红
      ④ 导入预检：没有文字层的 PDF 必须能被识别（扫描件 → 自动写正文不可用）

用法
    python tools\check\check-stub-guard.py
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "ui"))
sys.path.insert(0, os.path.join(ROOT, "engine"))
sys.path.insert(0, os.path.join(ROOT, "tools", "print"))

import audit_lesson  # noqa: E402
import _make  # noqa: E402
import server as app  # noqa: E402  ui\server.py（只 import，不启动服务）

COURSE = "_tmp_stubguard"

STUB = r'''# -*- coding: utf-8 -*-
"""占位样例（检查用）"""
LESSON = {
    "code": "__COURSE__", "no": "T99", "zh": "占位样例", "en": "", "orig": "占位样例",
    "lang": "zh", "stub": True, "out": "T99_占位样例_讲义.pdf",
    "sub": "原件导入占位 · 正文待补",
    "meta": (("源课件", "00_原件/不存在.pdf"), ("状态", "占位：正文未补")),
    "sections": ({"no": "0", "zh": "本讲导读", "en": "Read Me First", "lec": "占位。",
                  "body": (("p", "占位"),)},),
    "tail": (),
    "summary": {"no": "1", "zh": "本讲小结", "en": "Takeaways", "lec": "占位。",
                "head": ("a", "b"), "head_widths": ("50%", "50%"), "rows": (("a", "b"),), "tail": "占位"},
    "glossary": {"no": "2", "zh": "术语表", "en": "Glossary", "lec": "占位。",
                 "rows": (("a", "b", "课件 p.1", "c"),)},
    "appendix": {"no": "3", "zh": "附录", "en": "Appendix", "lec": "占位。",
                 "symbols": (), "myths_title": "常见误解", "myths": ()},
    "quiz": {"no": "4", "zh": "自测", "en": "Self-check", "lec": "占位。",
             "items": (("q", "答：回看 §0"),)},
}
'''


def check_stub_fields() -> tuple[bool, str]:
    """① 导入建骨架：stub / orig 两个字段必须落进数据文件。"""
    try:
        r = app.make_stub_lesson(COURSE, "02.散剂a.pdf")
        path = app.paths.data_or_res(COURSE, "_lessons", r["no"] + ".py")
        text = open(path, encoding="utf-8").read()
        ok = ('"stub": True' in text or '"stub": true' in text) and '"orig": "02.散剂a"' in text
        return ok, "no=%s · stub=%s · orig=%s" % (
            r.get("no"), ('"stub": True' in text), ('"orig": "02.散剂a"' in text))
    except Exception as e:  # noqa: BLE001
        return False, "异常 %r" % (e,)


def check_make_guard() -> tuple[bool, str]:
    """② 渲染闸门：占位不能出 PDF。"""
    les = os.path.join(ROOT, COURSE, "_lessons")
    os.makedirs(les, exist_ok=True)
    with open(os.path.join(les, "T99.py"), "w", encoding="utf-8") as f:
        f.write(STUB.replace("__COURSE__", COURSE))
    buf = []
    rc = _make.make(["T99"], course=COURSE, emit=buf.append)
    log = "\n".join(buf)
    ok = rc == 1 and "[停]" in log and "占位" in log
    return ok, ("rc=%s · %s" % (rc, log.replace("\n", " ")[:120]))


def check_content_gate() -> tuple[bool, str]:
    """③ 内容门：占位文本判红。"""
    fd, path = tempfile.mkstemp(suffix=".html")
    os.close(fd)
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write('<html data-theme="dark" data-reader="大学"><body>'
                    '<section class="cover">原件导入占位 · 正文待补</section></body></html>')
        r = audit_lesson.content_audit(path)
        hit = any("导入占位" in x for x in r["fails"])
        return hit, "status=%s · 命中=%s" % (r["status"], hit)
    finally:
        os.unlink(path)


def check_scan_detect() -> tuple[bool, str]:
    """④ 导入预检：无文字层 = 0 字符；有文字层 > 50。"""
    try:
        import pymupdf
        tmp = tempfile.mkdtemp(suffix="-stubscan")
        blank = os.path.join(tmp, "blank.pdf")
        text = os.path.join(tmp, "text.pdf")
        with pymupdf.open() as d:
            d.new_page()
            d.save(blank)
        with pymupdf.open() as d:
            p = d.new_page()
            p.insert_text((72, 72), "powder " * 40)
            d.save(text)
        a, b = app.pdf_text_chars(blank), app.pdf_text_chars(text)
        shutil.rmtree(tmp, ignore_errors=True)
        return (a == 0 and b > 50), "扫描件=%s 字符 · 有文字层=%s 字符" % (a, b)
    except Exception as e:  # noqa: BLE001
        return False, "异常 %r" % (e,)


def main() -> int:
    checks = [("① 导入建骨架", check_stub_fields),
              ("② 渲染闸门", check_make_guard),
              ("③ 内容门", check_content_gate),
              ("④ 扫描件识别", check_scan_detect)]
    rows = []
    try:
        for name, fn in checks:
            ok, ev = fn()
            rows.append(ok)
            print("[%s] %s —— %s" % ("通过" if ok else "失败", name, ev))
    finally:
        shutil.rmtree(os.path.join(ROOT, COURSE), ignore_errors=True)
    print("结论：%d/%d" % (sum(1 for x in rows if x), len(checks)))
    return 0 if all(rows) else 1


if __name__ == "__main__":
    sys.exit(main())
