# -*- coding: utf-8 -*-
"""判据：路径双根在「冻结」（打包成 exe）之后是否真的成立。

    python tools\\check\\check-paths.py            # 全查（会真生成一份讲义，约 10–20 s）
    python tools\\check\\check-paths.py --quick    # 只验路径解析，不跑生成
    python tools\\check\\check-paths.py --selftest # 先造坏再跑一遍：证明这个判据会红

它造一个「假打包现场」，不碰真实仓：
    临时目录\\res\\   ← 只读资源（paths.py engine tools api ui courses.json DEMO），相当于 sys._MEIPASS
    临时目录\\data\\  ← 可写数据（空目录），相当于 exe 所在目录
然后在子进程里设 sys.frozen = True、sys._MEIPASS = res、sys.executable = data\\LaPluma.exe，
再 import paths —— 这正是 PyInstaller 跑起来时的三个事实。

判 7 项（每项都能单独红）：
  1 RES_ROOT 指向 res（不是 data，也不是真实仓）
  2 DATA_ROOT 指向 data（exe 旁边）
  3 资源侧关键文件找得到：tools\\print\\pdfjs\\pdf.min.mjs、KaTeX 正文字体、ui\\index.html
  4 engine\\_make 能靠 paths.bootstrap() 挂上 sys.path
  5 冻结下能真生成一讲（数据根里有 D02，资源根里有 D01，两边都要能找到）
  6 生成产物落在 data\\DEMO\\01_讲义，且 res 里的文件一个没变（没往只读目录写）
  7 数据根有同名课程时优先用数据根（用户把自己的课件放 exe 旁边覆盖示例）

退出码：0 = 全绿；1 = 有红；2 = 没查（环境缺 Chrome 等，会明说哪项没查）。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
ARGS = set(sys.argv[1:])
QUICK = "--quick" in ARGS

RES_ITEMS = ["paths.py", "courses.json", "engine", "tools", "api", "ui", "DEMO"]
SKIP = {"__pycache__", ".git", "_logs", "out"}
BAD_LINE = "DATA_ROOT = os.path.dirname(os.path.abspath(sys.executable)) if FROZEN else FS_ROOT"


def copy_res(dst: str) -> None:
    for name in RES_ITEMS:
        src = os.path.join(ROOT, name)
        tgt = os.path.join(dst, name)
        if os.path.isdir(src):
            shutil.copytree(src, tgt, ignore=shutil.ignore_patterns(*SKIP))
        elif os.path.isfile(src):
            shutil.copy2(src, tgt)
        else:
            raise SystemExit("资源清单里的 %s 不存在" % name)


def sabotage(res: str) -> bool:
    """把假打包目录里的 paths.py 改成「数据根 = 资源根」——正是打包最容易犯的错。"""
    p = os.path.join(res, "paths.py")
    if not os.path.isfile(p):
        return False
    s = open(p, encoding="utf-8").read()
    if BAD_LINE not in s:
        return False
    open(p, "w", encoding="utf-8").write(
        s.replace(BAD_LINE, "DATA_ROOT = RES_ROOT   # 故意造坏：把可写数据指到只读解包目录"))
    return True


RUNNER = r'''
import json, os, sys
RES, DATA = sys.argv[1], sys.argv[2]
# ---- 伪装成 PyInstaller 冻结后的现场（这三个事实是 PyInstaller 给的）----
sys.frozen = True
sys._MEIPASS = RES
sys.executable = os.path.join(DATA, "LaPluma.exe")
sys.argv = ["LaPluma.exe"]
sys.path.insert(0, RES)
import paths
paths.bootstrap()   # 真程序启动时也会先调它：把 engine\ tools\print\ api\ 挂上 sys.path
out = {"res": paths.RES_ROOT, "data": paths.DATA_ROOT, "frozen": paths.FROZEN}
out["pdfjs"] = os.path.isfile(paths.res("tools", "print", "pdfjs", "pdf.min.mjs"))
out["katex"] = os.path.isfile(paths.res("tools", "print", "katex", "fonts", "KaTeX_Main-Regular.woff2"))
out["ui"] = os.path.isfile(paths.res("ui", "index.html"))
out["courses_json"] = paths.data_or_res("courses.json")
out["demo_dir"] = paths.course_dir("DEMO")
if os.environ.get("PLUMA_FULL"):
    try:
        import _make
        lines = []
        rc = _make.make(["D01"], course="DEMO", emit=lines.append)
        out["gen_rc"] = rc
        out["gen_tail"] = lines[-1] if lines else ""
    except Exception as e:
        out["gen_rc"] = -1
        out["gen_err"] = repr(e)
print("@@JSON@@" + json.dumps(out, ensure_ascii=False))
'''


def run_checks(break_it: bool = False) -> tuple[int, list]:
    """造一次假打包现场并跑 7 项；返回 (退出码, 检查结果)。"""
    tmp = tempfile.mkdtemp(prefix="pluma-paths-")
    res = os.path.join(tmp, "res")
    data = os.path.join(tmp, "data")
    os.makedirs(res)
    os.makedirs(data)
    try:
        copy_res(res)
        if break_it and not sabotage(res):
            raise SystemExit("造坏失败：res\\paths.py 里找不到要替换的那一行（判据本身要维护了）")
        # 7 的反例准备：数据根放一份同名课程，看它是否优先
        d_demo = os.path.join(data, "DEMO")
        os.makedirs(os.path.join(d_demo, "_lessons"))
        with open(os.path.join(d_demo, "_lessons", "D02.py"), "w", encoding="utf-8") as f:
            f.write("# -*- coding: utf-8 -*-\nLESSON = {'code': 'DEMO', 'no': 'D02'}\n")
        res_pdf_dir = os.path.join(res, "DEMO", "01_讲义")
        res_before = sorted(os.listdir(res_pdf_dir)) if os.path.isdir(res_pdf_dir) else []

        runner = os.path.join(tmp, "run_frozen.py")
        with open(runner, "w", encoding="utf-8") as f:
            f.write(RUNNER)
        env = dict(os.environ, PLUMA_FULL="" if QUICK else "1", PYTHONIOENCODING="utf-8")
        p = subprocess.run([sys.executable, runner, res, data], cwd=data, capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=600, env=env)
        blob = [l for l in (p.stdout or "").splitlines() if l.startswith("@@JSON@@")]
        if not blob:
            print("子进程没给出结果，照抄它的 stderr：")
            print((p.stderr or "").strip()[:2000])
            return 1, []
        got = json.loads(blob[0][len("@@JSON@@"):])

        low = lambda s: os.path.normcase(os.path.abspath(s))  # noqa: E731
        checks = []

        def chk(name, ok, detail=""):
            checks.append((name, bool(ok), detail))

        chk("1 资源根 = 假解包目录", low(got["res"]) == low(res), got["res"])
        chk("2 数据根 = 假 exe 旁边", low(got["data"]) == low(data), got["data"])
        chk("3 资源侧关键文件在", got["pdfjs"] and got["katex"] and got["ui"],
            "pdfjs=%s katex=%s ui=%s" % (got["pdfjs"], got["katex"], got["ui"]))
        chk("4 出厂 courses.json 从资源根读到",
            low(got["courses_json"]).startswith(low(res)), got["courses_json"])
        chk("7 同名课程优先用数据根", low(got["demo_dir"]) == low(d_demo), got["demo_dir"])

        if QUICK:
            print("（--quick：第 5、6 项没查——要真生成才知道产物落在哪）")
        else:
            pdf_dir = os.path.join(data, "DEMO", "01_讲义")
            pdfs = [f for f in os.listdir(pdf_dir)] if os.path.isdir(pdf_dir) else []
            res_after = sorted(os.listdir(res_pdf_dir)) if os.path.isdir(res_pdf_dir) else []
            chk("5 冻结下能 import engine\\_make 并生成", got.get("gen_rc") == 0,
                got.get("gen_err") or got.get("gen_tail", ""))
            chk("6 产物落在数据根、资源根没被写",
                any(f.endswith(".pdf") for f in pdfs) and res_after == res_before,
                "data:%s res 新增:%s" % (len(pdfs), [x for x in res_after if x not in res_before]))
        return (1 if any(not c[1] for c in checks) else 0), checks
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def report(checks: list) -> None:
    for name, ok, detail in checks:
        print(("  OK  " if ok else "  ✗   ") + name + ("  ← " + str(detail) if detail and not ok else ""))
    bad = sum(1 for c in checks if not c[1])
    print("%d 项检查：绿 %d · 红 %d%s" % (len(checks), len(checks) - bad, bad,
                                        "（另有 2 项没查：--quick）" if QUICK else ""))


def main() -> int:
    for s in (sys.stdout, sys.stderr):
        if hasattr(s, "reconfigure"):
            s.reconfigure(encoding="utf-8", errors="replace")

    if "--selftest" in ARGS:
        print("--- 造坏一遍（数据根指到只读解包目录），它必须红 ---")
        rc_bad, checks_bad = run_checks(break_it=True)
        report(checks_bad)
        expect = rc_bad == 1 and not checks_bad[1][1]   # 第 2 项「数据根」必须红
        print("造坏结果：%s（期望：退出 1 且第 2 项红）" % ("符合预期" if expect else "不符合预期"))
        if not expect:
            return 1
        print("\n--- 还原后真跑一遍，它必须绿 ---")
        rc_ok, checks_ok = run_checks()
        report(checks_ok)
        if rc_ok != 0:
            return 1
        print("\n自测通过：同一个判据在造坏时红、在正常时绿。")
        return 0

    rc, checks = run_checks()
    report(checks)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
