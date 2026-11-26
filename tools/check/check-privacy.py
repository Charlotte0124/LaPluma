# -*- coding: utf-8 -*-
"""真实课程名不出公开库（2026-11-26）

判据：把本机真实课程的名字（来自 courses.local.json 与真实课程目录名）拿到
「会被提交/会公开」的文件里搜一遍，搜到就红。

为什么要这条：截图、宣传片、文档反复把手里的真实课程名带进公开仓库；
提交前没有判据，只能靠人眼，于是同一个漏洞出现很多次。

用法：
  python -X utf8 tools/check/check-privacy.py                 # 查 git 跟踪的文件（= 会公开的那批）
  python -X utf8 tools/check/check-privacy.py --all-files     # 查工作区全部文件（不看 .gitignore）
  python -X utf8 tools/check/check-privacy.py --paths <目录>   # 查仓库以外的目录（宣传片产物、设计稿）

词表来源（按顺序合并）：
  1. tools/check/privacy-terms.local.txt（一行一个，可用 # 注释；不进公开库）
  2. courses.local.json 的键与 title/en（不进公开库）
  3. 仓根下含 _lessons 且不叫 DEMO 的目录名
没有词表时不算通过：打印「跳过」并说明没查（跳过 != 通过）。
"""
import argparse, json, os, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TERM_FILE = os.path.join(ROOT, "tools", "check", "privacy-terms.local.txt")
LOCAL_COURSES = os.path.join(ROOT, "courses.local.json")

# 允许出现的地方：本地覆盖文件与本地课程目录（本来就不进公开库）。
# 课程目录名直接从词表里取——写死哪个课程名，这个判据自己就先红一次（2026-11-27 实测）。
ALLOW_FIXED = ("courses.local.json", "tools/check/privacy-terms.local.txt")


def allow_prefixes(terms):
    """固定白名单 + 本机真实课程目录（词表里那个词本身就是目录名）。"""
    dirs = tuple("%s/" % t for t in terms if "/" not in t and "\\" not in t)
    return ALLOW_FIXED + dirs
# 不用查的目录（构建/缓存/日志）
SKIP_DIR = (".git", "__pycache__", "node_modules", "out", "dist", ".build", "_logs", "_trash", ".venv")
TEXT_EXT = {".md", ".txt", ".py", ".js", ".mjs", ".cjs", ".html", ".htm", ".css", ".json", ".yml", ".yaml",
            ".toml", ".ini", ".cfg", ".cmd", ".bat", ".ps1", ".sh", ".svg", ".csv", ".tsv", ".tex", ".log", ""}
MIN_LEN = 4  # 太短的词（如 "CS1"）误报太多，也基本不具识别性


def load_terms():
    terms, src = [], []
    if os.path.isfile(TERM_FILE):
        with open(TERM_FILE, encoding="utf-8") as fh:
            for ln in fh:
                ln = ln.strip()
                if ln and not ln.startswith("#"):
                    terms.append(ln)
                    src.append("privacy-terms.local.txt")
    if os.path.isfile(LOCAL_COURSES):
        try:
            with open(LOCAL_COURSES, encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception as e:
            print("[隐私扫描] courses.local.json 读不了：%s" % e)
            data = {}
        for k, v in (data.items() if isinstance(data, dict) else []):
            if k and k != "DEMO" and len(k) >= MIN_LEN:
                terms.append(k); src.append("courses.local.json:键")
            if isinstance(v, dict):
                for fld in ("title", "en"):
                    val = v.get(fld)
                    if isinstance(val, str) and val.strip() and val.strip() != "DEMO" and len(val.strip()) >= MIN_LEN:
                        terms.append(val.strip()); src.append("courses.local.json:" + fld)
    try:
        for name in os.listdir(ROOT):
            p = os.path.join(ROOT, name)
            if name != "DEMO" and os.path.isdir(p) and os.path.isdir(os.path.join(p, "_lessons")):
                if len(name) >= MIN_LEN:
                    terms.append(name); src.append("真实课程目录名")
    except OSError:
        pass
    uniq, seen = [], set()
    for t in terms:
        tl = t.casefold()
        if tl not in seen:
            seen.add(tl); uniq.append(t)
    uniq.sort(key=len, reverse=True)
    return uniq


def git_files():
    out = subprocess.run(["git", "-C", ROOT, "ls-files", "-z"], capture_output=True)
    if out.returncode != 0:
        return None
    return [p for p in out.stdout.decode("utf-8", "ignore").split("\0") if p]


def walk_files(base):
    found = []
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIR]
        for fn in filenames:
            found.append(os.path.join(dirpath, fn))
    return found


def scan(path, terms):
    """返回 [(行号, 命中的词)]"""
    hits = []
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
    except OSError:
        return hits
    ext = os.path.splitext(path)[1].lower()
    if ext in TEXT_EXT:
        text = raw.decode("utf-8", "ignore")
        low = text.casefold()
        for t in terms:
            if t.casefold() in low:
                idx = low.find(t.casefold())
                line = text.count("\n", 0, idx) + 1
                hits.append((line, t))
    else:
        # 非文本也查：PDF 文字层 / 未压缩的 PNG 文本块
        for t in terms:
            if t.encode("utf-8") in raw or (t.isascii() and t.lower().encode() in raw.lower()):
                hits.append((0, t))
    return hits


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all-files", action="store_true", help="查工作区全部文件（不看 .gitignore）")
    ap.add_argument("--paths", nargs="*", default=None, help="额外要查的目录（可给多个）")
    args = ap.parse_args()

    terms = load_terms()
    if not terms:
        print("[隐私扫描] 跳过：本机没有找到真实课程词表（no courses.local.json / 无真实课程目录）。")
        print("[隐私扫描] 这一关没查，不等于通过。要查就写 tools/check/privacy-terms.local.txt。")
        return 0

    targets = []
    if args.paths:
        for p in args.paths:
            if os.path.isdir(p):
                targets += walk_files(p)
            elif os.path.isfile(p):
                targets.append(p)
            else:
                print("[隐私扫描] 路径不存在：%s" % p)
    else:
        if args.all_files:
            targets = [os.path.join(ROOT, p) for p in walk_files(ROOT)] if False else walk_files(ROOT)
        else:
            rel = git_files()
            if rel is None:
                print("[隐私扫描] 跳过：这里不是 git 仓库，取不到跟踪文件清单。")
                return 0
            targets = [os.path.join(ROOT, p.replace("/", os.sep)) for p in rel]

    allowed = allow_prefixes(terms)
    bad = []
    checked = 0
    for p in targets:
        try:
            rp = os.path.relpath(p, ROOT).replace(os.sep, "/")
        except ValueError:  # 另一个盘符（--paths 指向仓外）
            rp = p.replace(os.sep, "/")
        if any(rp == a or rp.startswith(a) for a in allowed):
            continue
        if not os.path.isfile(p):
            continue
        checked += 1
        for line, term in scan(p, terms):
            bad.append((rp, line, term))

    print("[隐私扫描] 词表 %d 个｜查了 %d 个文件" % (len(terms), checked))
    if not bad:
        print("[隐私扫描] 通过：没有公开文件带真实课程名。")
        return 0
    print("[隐私扫描] 红：%d 处真实课程名出现在公开文件里" % len(bad))
    for rp, line, term in bad[:40]:
        print("  %s%s  <- %s" % (rp, (":%d" % line) if line else "", term))
    if len(bad) > 40:
        print("  ... 还有 %d 处" % (len(bad) - 40))
    print("[隐私扫描] 改法：换成示例名（DEMO / 示例课程 A/B），或把这份文件放进 .gitignore。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
