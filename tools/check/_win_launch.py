# -*- coding: utf-8 -*-
"""自测用启动器：把数据根指到临时目录再起真界面，绝不碰用户自己的课程。

为什么不在 server.py 里加一个 --data-root：
  自测要隔离数据（造「原件 + 成品」都齐的课程），但产品不需要这个开关；
  这里在 import 之前改 paths.DATA_ROOT，server.py 里的 ROOT 与各处的 paths.DATA_ROOT
  都跟着变，产品代码一行不动。

用法（只给 tools\\check\\check-window-real.py 用）：
    set PLUMA_TEST_DATA=<临时数据根>
    python tools\\check\\_win_launch.py --port 8899 --no-browser
"""
import os
import runpy
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)

import paths  # noqa: E402

data = (os.environ.get("PLUMA_TEST_DATA") or "").strip()
if not data:
    sys.exit("PLUMA_TEST_DATA 没设：这是自测启动器，正常启动请用 一键启动.ps1")
paths.DATA_ROOT = os.path.abspath(data)
os.makedirs(paths.DATA_ROOT, exist_ok=True)

target = os.path.join(ROOT, "ui", "server.py")
sys.argv = [target] + sys.argv[1:]
runpy.run_path(target, run_name="__main__")
