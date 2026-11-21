# -*- coding: utf-8 -*-
r"""模型输出解析判据：带示例 / 多吐一个对象 / 尾逗号 / 代码围栏 / 控制字符 都要能吃下。

为什么有这条（2026-11-21）：
    用户在「生成」页点开始生成，拿到的是「[停] 补正文失败：JSONDecodeError('Expecting
    property name enclosed in double quotes: line 1 column 1126 (char 1125)')」——界面
    等于死路。旧实现只做「第一个 { 到最后一个 }」一刀切：模型多吐一个对象、或前面带一段
    示例，就必错。现在按候选逐个解，并且连续两次不行时把原文落盘。

绿：下面 7 个样例全部按预期；有一例不符就红。
"""
import importlib.util
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
import paths  # noqa: E402

for _p in (paths.res("api"), paths.res("engine")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

_spec = importlib.util.spec_from_file_location("pluma_draft", os.path.join(ROOT, "engine", "_draft.py"))
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
_json_of = _mod._json_of

OBJ = '{"zh":"标题","sections":[{"no":"0","zh":"导读"}]}'

CASES = [
    ("原样对象", OBJ, lambda r: r.get("zh") == "标题"),
    ("代码围栏", "```json" + chr(10) + OBJ + chr(10) + "```", lambda r: r.get("zh") == "标题"),
    ("前面有客套话", "好的，结果如下：" + chr(10) + OBJ + chr(10) + "以上。", lambda r: r.get("zh") == "标题"),
    ("先吐示例再吐真货", '{"zh":"示例","demo":1}' + chr(10)*2 + OBJ, lambda r: r.get("zh") == "标题"),
    ("尾逗号", '{"zh":"标题","sections":[{"no":"0"},]}', lambda r: r.get("zh") == "标题"),
    ("字符串里有裸换行", '{"zh":"第一行' + chr(10) + '第二行","sections":[]}', lambda r: "第二行" in r.get("zh", "")),
    ("纯废话必须报错", "对不起，我无法完成。", None),
]


def main() -> int:
    bad = 0
    for name, text, check in CASES:
        try:
            got = _json_of(text)
        except Exception as e:  # noqa: BLE001
            got, err = None, e.__class__.__name__
        else:
            err = ""
        if check is None:
            ok = got is None
            want = "报错"
        else:
            ok = got is not None and check(got)
            want = "解析成功"
        print("%s %s（期望 %s%s）" % ("[绿]" if ok else "[红]", name, want,
                                      "，实际 " + err if err else ""))
        if not ok:
            bad += 1
    print("结论：%d/%d" % (len(CASES) - bad, len(CASES)))
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
