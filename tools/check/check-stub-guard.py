# -*- coding: utf-8 -*-
r"""占位骨架防护的回归：两条判据必须能红，也要能绿（2026-11-19）。

为什么要有它
    用户实测「导入 99 页课件 → 开始生成 → 出来 7 页占位」。修法不是只补一次正文，
    而是让「骨架」再也混不成「成品」。这里把两条闸门做成可重跑的检查：
      ① engine\_make.py 遇到 "stub": True 必须停，不出 PDF；
      ② 内容门遇到「原件导入占位 / 正文待补」必须判红。

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
sys.path.insert(0, os.path.join(ROOT, "engine"))
sys.path.insert(0, os.path.join(ROOT, "tools", "print"))

import audit_lesson  # noqa: E402
import _make  # noqa: E402

STUB = '''# -*- coding: utf-8 -*-
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


def check_make_guard(course: str) -> tuple[bool, str]:
    les = os.path.join(ROOT, course, "_lessons")
    os.makedirs(les, exist_ok=True)
    with open(os.path.join(les, "T99.py"), "w", encoding="utf-8") as f:
        f.write(STUB.replace("__COURSE__", course))
    buf = []
    rc = _make.make(["T99"], course=course, emit=buf.append)
    log = "\n".join(buf)
    ok = rc == 1 and "[停]" in log and "占位" in log
    return ok, ("rc=%s · %s" % (rc, log.replace("\n", " ")[:120]))


def check_content_gate() -> tuple[bool, str]:
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


def main() -> int:
    course = "_tmp_stubguard"
    try:
        a, ea = check_make_guard(course)
        b, eb = check_content_gate()
    finally:
        shutil.rmtree(os.path.join(ROOT, course), ignore_errors=True)
    print("[%s] 渲染闸门：占位不能出 PDF —— %s" % ("通过" if a else "失败", ea))
    print("[%s] 内容门：占位文本判红 —— %s" % ("通过" if b else "失败", eb))
    print("结论：%d/2" % (int(a) + int(b)))
    return 0 if (a and b) else 1


if __name__ == "__main__":
    sys.exit(main())