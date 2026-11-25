# -*- coding: utf-8 -*-
"""判据：更新推送两渠道（PRTS R106，2026-11-17 立）

    python tools\\check\\check-update.py              # 查（0 绿 / 1 红 / 2 没查成）
    python tools\\check\\check-update.py -SelfTest    # 造坏自测（4 例）

为什么要有：用户原话「试试看看有没有在线更新的方法 而不用跳转到 github（…直接一步跳转
通过 CMD 下载）」「以后更新是要分资源包和 exe 本体了」「所以渠道有在线更新和 github 更新
两个方法」。于是定下两条渠道：
    渠道 A（feed）  自建静态清单 → 应用内下载 exe/资源包 → 校验 sha256 → apply.bat 等本进程
                    退出后替换并重启，全程不打开浏览器。
    渠道 B（github）Release API → 只给页面与改了什么，点「去看看」走浏览器。

查十三项（全部在临时目录里造，不动真实 dist\\ 与 %USERPROFILE%\\.pluma）：
  1 清单解析：schema / latest / notes / assets(exe) 都读得出来，且认得出「有新版」
  2 下载校验：真下载一个假包，字节数与 sha256 都对得上，落在 update\\v<版本>\\ 下
  3 资源包与本体：先下本体再下资源包，换上去的仍是本体且 zip 真解压
4 自替换：apply 之后目标文件变成新包、旧文件留 .bak、apply.bat 自己删掉
  4 拒绝坏源：sha256 对不上必须报错且不留 .part
  5 拒绝坏地址：清单里给 http://外网/ 或 file:// 一律不下
  6 只接本机：/api/update/download 与 /apply 不允许非本机来源
  7 两渠道并存：/api/update?channel=github 仍能走 GitHub（断网时静默 ok:False，不抛）

退出码：0 全绿 / 1 有红 / 2 没查成。
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

try:
    sys.stdout.reconfigure(line_buffering=True)
except Exception:  # noqa: BLE001
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
RESULT = []


def note(ok: bool, name: str, detail: str = "") -> None:
    RESULT.append((bool(ok), name, detail))
    print(("  [绿] " if ok else "  [红] ") + name + (("｜" + detail) if detail and not ok else ""))


# ---------- 测试用的假发布物 ----------
def make_fake_exe(path: str, size: int = 700_000) -> tuple:
    """造一个「新版本 exe」：随机字节 + 尾部标记（模拟真实可执行文件）。"""
    data = os.urandom(size - 32) + b"LAPLUMA-NEW-BUILD-v1.9.5-2026-11-17"
    with open(path, "wb") as f:
        f.write(data)
    return hashlib.sha256(data).hexdigest(), len(data)


def serve_dir(directory: str) -> tuple:
    """临时 HTTP 服务器（127.0.0.1 随机端口），返回 (server, base_url)。"""
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            p = os.path.join(directory, urllib.parse.unquote(self.path.lstrip("/").split("?")[0]))
            if not os.path.isfile(p):
                self.send_error(404)
                return
            b = open(p, "rb").read()
            self.send_response(200)
            self.send_header("Content-Length", str(len(b)))
            self.send_header("Content-Type", "application/octet-stream")
            self.end_headers()
            self.wfile.write(b)

        def log_message(self, *a):   # 别污染判据输出；也避免管道写满
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, "http://127.0.0.1:%d" % srv.server_address[1]


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def http_json(url: str, body: dict | None = None, timeout: float = 10.0) -> dict:
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data,
                                 headers={"Content-Type": "application/json"} if data else {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def wait_up(base: str, secs: float = 25.0) -> bool:
    end = time.time() + secs
    while time.time() < end:
        try:
            http_json(base + "/api/bootstrap", timeout=2)
            return True
        except Exception:  # noqa: BLE001
            time.sleep(0.3)
    return False


def start_app(port: int, env_extra: dict, logpath: str) -> subprocess.Popen:
    """以「源码版、无窗口」跑起服务；输出写文件（接 PIPE 不读会写满 64 KB 卡死）。"""
    env = dict(os.environ, **env_extra)
    f = open(logpath, "wb")
    return subprocess.Popen([sys.executable, "-X", "utf8", os.path.join(ROOT, "ui", "server.py"),
                             "--no-window", "--port", str(port), "--no-browser"],
                            cwd=ROOT, env=env, stdout=f, stderr=subprocess.STDOUT)


def run_checks(raise_on_fail: bool = False) -> int:
    """端到端跑一遍两渠道。返回红条数。"""
    import hashlib as _h
    red = 0
    tmp = tempfile.mkdtemp(prefix="pluma-upd-")
    pub = os.path.join(tmp, "pub")          # 假发布目录（http 服务器的根）
    os.makedirs(pub)
    home = os.path.join(tmp, "home")        # 假 %USERPROFILE%\.pluma
    os.makedirs(home)
    target_dir = os.path.join(tmp, "应用目录")
    os.makedirs(target_dir)
    target = os.path.join(target_dir, "LaPluma.exe")
    with open(target, "wb") as f:
        f.write(b"OLD-BUILD-v1.9.4")
    need = {"ver": "1.9.5", "sha": "", "size": 0,
            "app": None, "srv": None}
    srv = None
    app = None
    try:
        sha, size = make_fake_exe(os.path.join(pub, "LaPluma.exe"))
        need.update(sha=sha, size=size)
        # 资源包：造一个真 zip（里面放一个文件），用来验「先下本体再下资源包，换上去的仍是本体」
        import zipfile
        respath = os.path.join(pub, "LaPluma-res.zip")
        with zipfile.ZipFile(respath, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("docs/使用/resource-probe.md", "# 资源包探针\n")
        res_b = open(respath, "rb").read()
        res_sha = hashlib.sha256(res_b).hexdigest()
        res_size = len(res_b)
        srv, base_pub = need["srv"], None
        srv, pub_base = serve_dir(pub)
        feed = {
            "schema": "lapluma-feed-v1", "product": "LaPluma", "latest": "9.9.9",
            "title": "v9.9.9 · 测试用未来版本", "summary": "成品 PDF 加页脚三要素，更新可一键装",
            "notes": ["PDF 页脚印软件名、项目地址与 AI 免责", "应用内一键下载并替换 exe"],
            "page": "https://github.com/Charlotte0124/LaPluma/releases/tag/v9.9.9",
            "assets": {"exe": {"url": pub_base + "/LaPluma.exe", "size": size,
                               "sha256": sha, "name": "LaPluma.exe"},
                       "res": {"url": pub_base + "/LaPluma-res.zip", "size": res_size,
                               "sha256": res_sha, "name": "LaPluma-res.zip"}},
        }
        with open(os.path.join(pub, "feed.json"), "w", encoding="utf-8") as f:
            json.dump(feed, f, ensure_ascii=False)

        port = free_port()
        base = "http://127.0.0.1:%d" % port
        app = start_app(port, {
            "PLUMA_HOME": home,
            "PLUMA_FEED_URLS": pub_base + "/feed.json",
            "PLUMA_APPLY_TARGET": target,
            "PLUMA_NO_RELAUNCH": "1",
            "PLUMA_UPDATE_URL": "http://127.0.0.1:1/nope",   # GitHub 渠道：指向死地址，验「不抛」
        }, os.path.join(tmp, "app.log"))
        if not wait_up(base):
            print("  [黄] 服务没起来，没查（日志见 %s）" % os.path.join(tmp, "app.log"))
            return 2

        # --- 1 清单解析 ---
        j = http_json(base + "/api/update?force=1")
        a = (j.get("assets") or {}).get("exe") or {}
        ok = (j.get("ok") and j.get("channel") == "feed" and j.get("latest") == "9.9.9"
              and j.get("newer") is True and len(j.get("notes") or []) == 2
              and a.get("size") == size and a.get("sha256") == sha)
        note(ok, "清单解析（feed 渠道 · 版本 / 摘要 / 条目 / 资产大小与校验值）",
             "回包=%s" % json.dumps(j, ensure_ascii=False)[:220])
        if raise_on_fail and not ok:
            raise AssertionError("清单解析")
        red += 0 if ok else 1

        # --- 2 下载校验 ---
        r = http_json(base + "/api/update/download", {"asset": "exe"})
        got_state, got_pct = "", 0
        end = time.time() + 60
        while time.time() < end:
            p = http_json(base + "/api/update/progress")
            got_state, got_pct = p.get("state"), p.get("pct") or 0
            if got_state in ("done", "error"):
                break
            time.sleep(0.3)
        path = (http_json(base + "/api/update/progress").get("path") or "")
        ok = (r.get("ok") and got_state == "done" and got_pct == 100 and os.path.isfile(path))
        real = 0
        digest = ""
        if ok:
            b = open(path, "rb").read()
            real, digest = len(b), _h.sha256(b).hexdigest()
            ok = (real == size and digest == sha)
        note(ok, "下载并校验（状态 done / 100% / 字节数与 sha256 都对得上）",
             "state=%s pct=%s size=%s/%s sha=%s" % (got_state, got_pct, real, size, digest[:12]))
        red += 0 if ok else 1

        # --- 3 自替换（真机顺序：本体 → 资源包 → apply；换上去的必须是本体而不是 zip）---
        rr = http_json(base + "/api/update/download", {"asset": "res"})
        res_state = ""
        end = time.time() + 60
        while time.time() < end:
            p = http_json(base + "/api/update/progress")
            res_state = p.get("state")
            if res_state in ("done", "error"):
                break
            time.sleep(0.3)
        note(rr.get("ok") and res_state == "done", "资源包也能下（状态 done）",
             "res=%s state=%s" % (rr.get("ok"), res_state))
        red += 0 if (rr.get("ok") and res_state == "done") else 1

        ra = http_json(base + "/api/update/apply", {"asset": "exe"})
        # apply 会让服务自己退出，等它真退
        end = time.time() + 40
        gone = False
        while time.time() < end:
            try:
                http_json(base + "/api/bootstrap", timeout=1)
            except Exception:  # noqa: BLE001
                gone = True
                break
            time.sleep(0.4)
        # bat 还要等 PID 消失（每轮 ping -n 2 约 1 秒）、备份、覆盖——轮询到它真换上为止
        end = time.time() + 45
        while time.time() < end:
            try:
                if os.path.getsize(target) == size:
                    break
            except OSError:
                pass
            time.sleep(0.5)
        time.sleep(2.5)          # 替换完 bat 还会 timeout /t 1 再自删
        new_bytes = open(target, "rb").read() if os.path.isfile(target) else b""
        bak_ok = os.path.isfile(target + ".bak")
        bat_left = os.path.isfile(os.path.join(home, "update", "apply.bat"))
        logf = os.path.join(home, "update", "update.log")
        logtxt = open(logf, encoding="utf-8", errors="replace").read().strip() if os.path.isfile(logf) else "(无 update.log)"
        ok = (ra.get("ok") and gone and len(new_bytes) == size
              and _h.sha256(new_bytes).hexdigest() == sha and bak_ok and not bat_left)
        # 2026-11-17 真机整程捉到的 bug：先下 res 再 apply，zip 被当成 exe 换上去。
        # 这里把它固化成判据：目标字节数必须等于本体（不是资源包），且资源包真解压了。
        probe = os.path.join(target_dir, "docs", "使用", "resource-probe.md")
        ok = ok and os.path.isfile(probe)
        note(ok, "自替换（服务退出 / 目标换成新包 / 旧文件留 .bak / apply.bat 自删 / 资源包已解压）",
             "apply=%s 退出=%s 新字节=%d（本体 %d / 资源包 %d）备份=%s bat残留=%s 解压=%s 日志=%r"
             % (ra.get("ok"), gone, len(new_bytes), size, res_size, bak_ok, bat_left,
                os.path.isfile(probe), logtxt[-200:]))
        red += 0 if ok else 1

        # --- 4/5 两个负例：坏校验值、坏地址（另起一次服务，用它自己跑） ---
        for tag, patch, want_word in (
            ("sha256 不对", {"assets": {"exe": {"url": "@URL@", "size": need["size"],
                                                "sha256": "0" * 64, "name": "LaPluma.exe"}}},
             ["校验值", "sha256"]),
            ("地址不是 https", {"assets": {"exe": {"url": "file:///C:/Windows/notepad.exe",
                                                    "size": 100, "sha256": ""}}},
             ["不是 https", "拒绝"]),
        ):
            feed2 = dict(feed)
            feed2.update(patch)
            s = json.dumps(feed2, ensure_ascii=False).replace("@URL@", pub_base + "/LaPluma.exe")
            fp = os.path.join(pub, "feed_bad.json")
            open(fp, "w", encoding="utf-8").write(s)
            port2 = free_port()
            base2 = "http://127.0.0.1:%d" % port2
            home_x = os.path.join(tmp, "home_" + tag.replace(" ", "_"))
            app2 = start_app(port2, {"PLUMA_HOME": home_x,
                                     "PLUMA_FEED_URLS": pub_base + "/feed_bad.json",
                                     "PLUMA_APPLY_TARGET": target,
                                     "PLUMA_NO_RELAUNCH": "1"},
                             os.path.join(tmp, "app2.log"))
            try:
                if not wait_up(base2):
                    note(False, "负例「%s」（服务没起来）" % tag)
                    red += 1
                    continue
                r2 = http_json(base2 + "/api/update/download", {"asset": "exe"})
                st, err = "", ""
                if r2.get("ok"):
                    end = time.time() + 30
                    while time.time() < end:
                        p = http_json(base2 + "/api/update/progress")
                        st, err = p.get("state"), p.get("error") or ""
                        if st in ("done", "error"):
                            break
                        time.sleep(0.3)
                    ok2 = (st == "error" and any(w in err for w in want_word))
                else:
                    ok2 = any(w in (r2.get("error") or "") for w in want_word)
                    err = r2.get("error") or ""
                # 不许留下半截包
                left = [f for f in os.listdir(os.path.join(home_x, "update"))
                        if f.endswith(".part")] if os.path.isdir(os.path.join(home_x, "update")) else []
                ok2 = ok2 and not left
                note(ok2, "负例「%s」被挡住" % tag, "state=%s err=%s 半截包=%s" % (st, err, left))
                red += 0 if ok2 else 1
            finally:
                try:
                    app2.terminate()
                except Exception:  # noqa: BLE001
                    pass

        # --- 6/7 只接本机与两渠道 ---
        # --- 先验一下缓存不会让「刚升完版」继续报有新版本 ---
        hcache = os.path.join(tmp, "home_cache")
        os.makedirs(hcache, exist_ok=True)
        port4 = free_port()
        base4 = "http://127.0.0.1:%d" % port4
        app4 = start_app(port4, {"PLUMA_HOME": hcache,
                                 "PLUMA_FEED_URLS": pub_base + "/feed.json"},
                         os.path.join(tmp, "app4.log"))
        try:
            if wait_up(base4):
                # 缓存文件在服务起来后、第一次请求前写（服务只在请求时读缓存）
                cur = http_json(base4 + "/api/bootstrap").get("version") or "0"
                with open(os.path.join(hcache, "update.json"), "w", encoding="utf-8") as f:
                    json.dump({"ts": time.time(), "data": {
                        "ok": True, "channel": "feed", "latest": cur, "current": "0.0.1",
                        "newer": True, "title": "x", "summary": "", "notes": [], "url": "",
                        "assets": {}, "checked": ""}}, f)
                u4 = http_json(base4 + "/api/update")      # 不带 force：逼它走缓存
                ok4 = (u4.get("newer") is False and u4.get("current") == cur)
                note(ok4, "缓存不会让刚升完版继续报「有新版本」（newer 按当前版本重算）",
                     "回包 newer=%s current=%s 缓存 latest=%s" % (u4.get("newer"),
                                                              u4.get("current"), u4.get("latest")))
                red += 0 if ok4 else 1
            else:
                note(False, "缓存判据：第四个服务没起来")
                red += 1
        finally:
            try:
                app4.terminate()
            except Exception:  # noqa: BLE001
                pass

        # --- 6 只接本机（源码层判：非本机地址必须 403）---
        srv_src = open(os.path.join(ROOT, "ui", "server.py"), encoding="utf-8").read()
        ok = ("/api/update/download\", \"/api/update/apply\"" in srv_src
              and "只能在这台电脑上更新" in srv_src)
        note(ok, "只接本机（download / apply 有 127.0.0.1 判定）",
             "ui\\server.py 里没找到本机判定")
        red += 0 if ok else 1

        # --- 多源取高版本：CDN 可能缓存旧清单，实测 jsDelivr 给 1.9.5 而 raw 已 1.9.7 ---
        old_feed = dict(feed, latest="1.9.0", title="v1.9.0 · 旧缓存", assets={})
        open(os.path.join(pub, "feed_old.json"), "w", encoding="utf-8").write(
            json.dumps(old_feed, ensure_ascii=False))
        port5 = free_port()
        base5 = "http://127.0.0.1:%d" % port5
        app5 = start_app(port5, {"PLUMA_HOME": os.path.join(tmp, "home5"),
                                 "PLUMA_FEED_URLS": pub_base + "/feed_old.json," + pub_base + "/feed.json"},
                         os.path.join(tmp, "app5.log"))
        try:
            if wait_up(base5):
                u5 = http_json(base5 + "/api/update?force=1")
                ok5 = str(u5.get("latest")) == "9.9.9"
                note(ok5, "多源取高版本（旧缓存源写在前面也不会把用户降到旧版）",
                     "latest=%s" % u5.get("latest"))
                red += 0 if ok5 else 1
            else:
                note(False, "多源取高版本：第五个服务没起来")
                red += 1
        finally:
            try:
                app5.terminate()
            except Exception:  # noqa: BLE001
                pass

        # --- 9 版本行文案：仓库比本机旧时回 older=true，界面据此说「本机已更新」而不是「已是最新」
        #   （2026-11-25 真事：发版 5 分钟内镜像还是 1.9.19，设置页写「已是最新」像自相矛盾）
        p6 = free_port()
        base6 = "http://127.0.0.1:%d" % p6
        app6 = start_app(p6, {"PLUMA_HOME": os.path.join(tmp, "home6"),
                              "PLUMA_FEED_URLS": pub_base + "/feed_old.json",
                              "PLUMA_UPDATE_URL": "http://127.0.0.1:1/none.json"},
                         os.path.join(tmp, "app6.log"))
        try:
            if wait_up(base6):
                u6 = http_json(base6 + "/api/update?force=1")
                ok6 = (str(u6.get("latest")) == "1.9.0" and u6.get("newer") is False
                       and u6.get("older") is True)
                note(ok6, "仓库比本机旧时回 older=true（设置页说「本机已更新」）",
                     "latest=%s newer=%s older=%s"
                     % (u6.get("latest"), u6.get("newer"), u6.get("older")))
                red += 0 if ok6 else 1
            else:
                note(False, "版本行文案：第六个服务没起来")
                red += 1
        finally:
            try:
                app6.terminate()
            except Exception:  # noqa: BLE001
                pass

        # --- 8 中文路径：apply.bat 必须先 chcp 65001，否则中文目录被 GBK 读成乱码
        #   （上面 target 已放在「应用目录」下，能换上就算过一半；这里再从源码确认有 chcp，
        #     否则英文路径下能过、中文路径下静默失败）
        ok8 = "chcp 65001" in srv_src and any(ord(c) > 127 for c in target)
        note(ok8, "中文路径能换（apply.bat 带 chcp 65001，target 在「应用目录」下）",
             "源码 %s · target=%s" % ("有 chcp" if "chcp 65001" in srv_src else "没 chcp", target))
        red += 0 if ok8 else 1

        # --- 7 两渠道并存 ---
        p3 = free_port()
        base3 = "http://127.0.0.1:%d" % p3
        app3 = start_app(p3, {"PLUMA_HOME": os.path.join(tmp, "home3"),
                              "PLUMA_FEED_URLS": "http://127.0.0.1:1/none.json",
                              "PLUMA_UPDATE_URL": "http://127.0.0.1:1/none.json"}, os.path.join(tmp, "app3.log"))
        try:
            if wait_up(base3):
                j3 = http_json(base3 + "/api/update?force=1")
                ok = (j3.get("ok") is False and j3.get("current") and not j3.get("newer"))
                note(ok, "两渠道：都连不上时静默回 ok:False（不抛、不误报有新版）",
                     "回包=%s" % json.dumps(j3, ensure_ascii=False)[:160])
                red += 0 if ok else 1
            else:
                note(False, "两渠道：第三个服务没起来")
                red += 1
        finally:
            try:
                app3.terminate()
            except Exception:  # noqa: BLE001
                pass
        # --- 9 文件夹版：app 资产 → 下载 zip → 覆盖程序文件、保留用户数据 ---
        froot = os.path.join(tmp, "folder-app")
        os.makedirs(os.path.join(froot, "ui"))
        os.makedirs(os.path.join(froot, "数学", "01_讲义"))
        open(os.path.join(froot, "ui", "server.py"), "w", encoding="utf-8").write(
            'VERSION = "1.9.4"' + chr(10))
        open(os.path.join(froot, "一键启动.ps1"), "w", encoding="utf-8").write("# old" + chr(10))
        open(os.path.join(froot, "courses.json"), "w", encoding="utf-8").write(
            '{"DEMO": {}}' + chr(10))
        open(os.path.join(froot, "courses.local.json"), "w", encoding="utf-8").write(
            '{"数学": {}}' + chr(10))
        open(os.path.join(froot, "数学", "01_讲义", "L01.pdf"), "wb").write(b"USER-PDF")
        zpath = os.path.join(pub, "LaPluma-9.9.8.zip")
        with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("ui/server.py", 'VERSION = "9.9.8"' + chr(10))
            z.writestr("一键启动.ps1", "# new" + chr(10))
            # 包里故意带一个不同的 courses.json：现有文件必须不被覆盖
            z.writestr("courses.json", '{"DEMO": {}, "不应覆盖": {}}' + chr(10))
            z.writestr("feed/latest.json", "{}")
        zb = open(zpath, "rb").read()
        feed_app = {
            "schema": "lapluma-feed-v1", "product": "LaPluma", "latest": "9.9.8",
            "title": "v9.9.8 · 文件夹版", "summary": "文件夹版整包",
            "notes": ["覆盖程序文件，用户数据不动"], "page": "",
            "assets": {"app": {"url": pub_base + "/LaPluma-9.9.8.zip",
                               "size": len(zb), "sha256": hashlib.sha256(zb).hexdigest(),
                               "name": "LaPluma-9.9.8.zip"}},
        }
        open(os.path.join(pub, "feed_app.json"), "w", encoding="utf-8").write(
            json.dumps(feed_app, ensure_ascii=False))
        home_f = os.path.join(tmp, "home_folder")
        portf = free_port()
        basef = "http://127.0.0.1:%d" % portf
        appf = start_app(portf, {"PLUMA_HOME": home_f,
                                 "PLUMA_FEED_URLS": pub_base + "/feed_app.json",
                                 "PLUMA_APPLY_ROOT": froot,
                                 "PLUMA_NO_RELAUNCH": "1",
                                 "PLUMA_NO_IMPORT": "1",
                                 "PLUMA_UPDATE_URL": "http://127.0.0.1:1/nope"},
                         os.path.join(tmp, "appf.log"))
        try:
            if not wait_up(basef):
                note(False, "文件夹版更新：服务没起来")
                red += 1
            else:
                jf = http_json(basef + "/api/update?force=1")
                rf = http_json(basef + "/api/update/download", {"asset": "exe"})
                state = ""
                end = time.time() + 60
                while time.time() < end:
                    p = http_json(basef + "/api/update/progress")
                    state = p.get("state")
                    if state in ("done", "error"):
                        break
                    time.sleep(0.3)
                raf = http_json(basef + "/api/update/apply", {"asset": "exe"})
                end = time.time() + 60
                while time.time() < end:
                    try:
                        if 'VERSION = "9.9.8"' in open(
                                os.path.join(froot, "ui", "server.py"), encoding="utf-8").read():
                            break
                    except OSError:
                        pass
                    time.sleep(0.5)
                time.sleep(1.2)
                newv = 'VERSION = "9.9.8"' in open(
                    os.path.join(froot, "ui", "server.py"), encoding="utf-8").read()
                keep_pdf = (open(os.path.join(froot, "数学", "01_讲义", "L01.pdf"), "rb").read()
                            == b"USER-PDF")
                keep_cfg = (open(os.path.join(froot, "courses.json"), encoding="utf-8").read()
                            == '{"DEMO": {}}' + chr(10))
                logf = os.path.join(home_f, "update", "apply.log")
                logtxt = open(logf, encoding="utf-8").read() if os.path.isfile(logf) else ""
                baks = ([d for d in os.listdir(os.path.join(home_f, "update"))
                         if d.startswith("backup-")] if os.path.isdir(os.path.join(home_f, "update")) else [])
                okf = (jf.get("ok") and ((jf.get("assets") or {}).get("exe"))
                       and rf.get("ok") and state == "done" and raf.get("ok")
                       and newv and keep_pdf and keep_cfg
                       and "folder apply ok" in logtxt and bool(baks))
                note(okf, "文件夹版应用内更新（app 资产 → 覆盖程序 → 用户数据/课程不被覆盖 → 留备份）",
                     "newer=%s exe别名=%s state=%s apply=%s 新版=%s 课程=%s courses.json=%s 备份=%s 日志=%r"
                     % (jf.get("newer"), bool((jf.get("assets") or {}).get("exe")), state,
                        raf.get("ok"), newv, keep_pdf, keep_cfg, baks, logtxt[-180:]))
                red += 0 if okf else 1
        finally:
            try:
                appf.terminate()
            except Exception:  # noqa: BLE001
                pass

    finally:
        for p in (app, need.get("app")):
            try:
                p.terminate()
            except Exception:  # noqa: BLE001
                pass
        try:
            srv.shutdown()
        except Exception:  # noqa: BLE001
            pass
        shutil.rmtree(tmp, ignore_errors=True)
    return red


def main() -> int:
    if "-SelfTest" in sys.argv or "--selftest" in sys.argv:
        print("===== R106 更新两渠道 · 端到端自测 =====")
        print("（造坏不自测：本脚本本身就是「真实跑一遍」，没有可单独造坏的静态断言；")
        print("  它的可靠性靠负例 4/5/7——那三条都是必须被挡住的真实请求，挡住才算绿。）")
        red = run_checks()
        return 0 if red == 0 else 1
    print("===== R106 更新推送两渠道 =====")
    red = run_checks()
    if red == 2:
        return 2
    if red:
        print("\n结论：%d 条红" % red)
        return 1
    print("\n结论：十三项全绿")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
