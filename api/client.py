# -*- coding: utf-8 -*-
"""D 层 · API 接入（DeepSeek 兼容 OpenAI 口径）。

铁律：**key 永不入库**。仓库里只有「去哪读」的代码，没有 key 本身。

读取顺序（命中即用）：
  1. 环境变量 PLUMA_API_KEY（可同时给 PLUMA_BASE_URL / PLUMA_MODEL）
  2. 本机配置 %USERPROFILE%\\.pluma\\api.json
  3. PRTS 侧密钥文件 PRTS\\projects\\课程\\ops\\secrets\\api.json（本机开发默认）
  4. 界面里手填（由上层传进来，只落本机，不写仓）

用法：
    python api\\client.py --check              # 只读探测：配置文件在哪、模型列表
    python api\\client.py --chat "写一句开场"   # 一次性问答
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request

DEFAULT_BASE = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-flash"


class BalanceError(RuntimeError):
    """钱不够（接口 402 / Insufficient Balance）。

    2026-11-17：以前这也被当普通 HTTPError 抛上去，界面就只显示
    「模型调用失败：HTTP Error 402: Payment Required」——用户看不出是余额问题。
    现在单独一类，上层（ui\\server.py 的 /api/ask）能直接换成「人话弹窗」。
    """

    def __init__(self, status: int = 402, detail: str = ""):
        self.status = status
        self.detail = detail
        super().__init__("余额不足（HTTP %s）：%s" % (status, detail or "Insufficient Balance"))


def _looks_broke(status: int, body: str) -> bool:
    """认得出「余额 / 额度不够」的几种写法。"""
    low = (body or "").lower()
    if status == 402:
        return True
    for k in ("insufficient balance", "insufficient_quota", "exceeded your current quota",
              "余额不足", "额度不足"):
        if k in low:
            return True
    return False

# 接口 GET /models 实测只给这两个 id（python api\client.py --check 可复验）。
# 界面把它叫作 DeepSeek 4.1 Flash / 4.1 Pro，但发请求时用的必须是下面这两个 id，
# 写成 deepseek-4.1-flash 之类会被服务端拒。
MODELS = ("deepseek-flash", "deepseek-v4-pro")

def _user_dir() -> str:
    """本机配置目录：`PLUMA_HOME` 优先，否则 `%USERPROFILE%\\.pluma`。

    2026-11-21 修：ui\\server.py 的 USER_DIR 早就认 PLUMA_HOME（配置、会话、更新缓存都落在那里），
    这里却一直只看 `~`。后果是「用 PLUMA_HOME 隔离一份干净配置」根本不生效——
    界面写的是 PLUMA_HOME，读钥匙却还是回 ~\\.pluma，于是「全新环境」永远能读到本机的 key
    （自测里就撞到了：没有钥匙的环境居然答得出问题）。
    两处口径必须一致，配置目录只有一个。
    """
    home = (os.environ.get("PLUMA_HOME") or "").strip()
    return home or os.path.join(os.path.expanduser("~"), ".pluma")


USER_CFG = os.path.join(_user_dir(), "api.json")
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# PRTS 侧密钥文件的相对位置（仓外，禁止提交）
_SECRET_TAIL = ("projects", "课程", "ops", "secrets", "api.json")


def _app_roots() -> list:
    """可能「站在 PRTS 旁边」的目录：冻结点 = exe 所在目录，源码 = 仓根。"""
    out = []
    for r in ((os.path.dirname(os.path.abspath(sys.executable)) if getattr(sys, "frozen", False) else ""),
              _ROOT):
        if r and r not in out:
            out.append(r)
    return out


def secret_candidates() -> list:
    """按「离得最近」的顺序列出可能藏 key 的 PRTS 密钥文件。

    为什么不是一条写死的相对路径：2026-11-19 把 LaPluma 从 `F:\\DSH\\work\\…` 挪到
    `F:\\DSH\\apps\\LaPluma` 之后，原来那条 `..\\Project\\PRTS\\…` 指向了不存在的
    `F:\\DSH\\apps\\Project\\PRTS\\…`；界面只显示「未配置模型」，点生成就报
    「找不到 API key」。软件位置一变就再坏一次，所以改成从自己所在的目录往上找几层，
    两种常见摆法（`<p>\\work\\Project\\PRTS`、`<p>\\Project\\PRTS`）都试。
    环境变量 PLUMA_PRTS_SECRETS 仍然优先，可以指任意路径。
    """
    cands = []
    env = (os.environ.get("PLUMA_PRTS_SECRETS") or "").strip()
    if env:
        cands.append(env)
    for root in _app_roots():
        p = os.path.abspath(root)
        for _ in range(7):
            for head in (("work", "Project", "PRTS"), ("Project", "PRTS")):
                cands.append(os.path.join(p, *(head + _SECRET_TAIL)))
            nxt = os.path.dirname(p)
            if nxt == p:
                break
            p = nxt
    out = []
    for c in cands:
        c = os.path.normpath(c)
        if c not in out:
            out.append(c)
    return out


# 兼容旧引用：第一条候选（通常就是本机真实的那份）
PRTS_CFG = secret_candidates()[0]


def _read(path: str) -> dict:
    try:
        # PowerShell 写的 UTF-8 带 BOM，必须用 utf-8-sig，否则 json 解析直接失败
        with open(path, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception:
        return {}


def config_candidates() -> list:
    """本机所有可能读到 key 的文件，按优先级排（界面「设置」页与 --check 都用它）。"""
    out = [USER_CFG]
    for c in secret_candidates():
        if c not in out:
            out.append(c)
    return out


def load_config(explicit_key: str | None = None) -> dict:
    """按三级顺序取配置；全空则报错，不静默降级。"""
    cfg = {"provider": "DeepSeek", "base_url": DEFAULT_BASE, "model": DEFAULT_MODEL, "api_key": "", "source": ""}

    if os.environ.get("PLUMA_DISABLE_KEY", "").strip() not in ("", "0"):
        # 自测隔离（2026-11-23）：临时数据根里不该摸到真 key（含 PRTS secrets 回退）；
        # 置空让调用方走「未配置」分支，测试不会真花钱。
        return cfg

    env = os.environ.get("PLUMA_API_KEY", "").strip()
    if env:
        cfg["api_key"] = env
        cfg["source"] = "env:PLUMA_API_KEY"
        cfg["base_url"] = os.environ.get("PLUMA_BASE_URL", DEFAULT_BASE)
        cfg["model"] = os.environ.get("PLUMA_MODEL", DEFAULT_MODEL)
        return cfg

    for path in config_candidates():
        disk = _read(path)
        if disk.get("api_key"):
            cfg.update({k: v for k, v in disk.items() if k in cfg and v})
            cfg["source"] = path
            return cfg

    if explicit_key:
        cfg["api_key"] = explicit_key.strip()
        cfg["source"] = "ui"
        return cfg

    raise RuntimeError(
        "找不到 API key。三条路任选：① 设环境变量 PLUMA_API_KEY；"
        "② 建 %s；③ 在界面「设置」里填一次。" % USER_CFG
    )


def _post(url: str, payload: dict, key: str, timeout: int = 90) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + key},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raw = ""
        try:
            raw = e.read().decode("utf-8", "replace")[:400]
        except Exception:  # noqa: BLE001
            pass
        if _looks_broke(e.code, raw):
            msg = raw
            try:
                msg = json.loads(raw).get("error", {}).get("message", raw)
            except Exception:  # noqa: BLE001
                pass
            raise BalanceError(e.code, str(msg)[:120]) from e
        raise


def _get(url: str, key: str, timeout: int = 20) -> dict:
    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + key})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def list_models(cfg: dict | None = None) -> list[str]:
    cfg = cfg or load_config()
    body = _get(cfg["base_url"].rstrip("/") + "/models", cfg["api_key"])
    return [m["id"] for m in body.get("data", [])]


def chat(messages: list[dict], model: str | None = None, temperature: float = 0.7,
         max_tokens: int = 4096, cfg: dict | None = None) -> dict:
    """一次对话补全。返回 {text, model, usage, seconds, source}。"""
    cfg = cfg or load_config()
    use_model = model or cfg["model"]
    t0 = time.time()
    body = _post(
        cfg["base_url"].rstrip("/") + "/chat/completions",
        {"model": use_model, "messages": messages, "temperature": temperature,
         "max_tokens": max_tokens, "stream": False},
        cfg["api_key"],
    )
    choice = body["choices"][0] or {}
    text = (choice.get("message") or {}).get("content") or ""
    return {
        "text": text,
        "model": use_model,
        "usage": body.get("usage", {}),
        "seconds": round(time.time() - t0, 2),
        "source": cfg["source"],
        # 2026-11-21：「补正文失败 JSONDecodeError」有一半是输出被长度上限截断，
        #   截断时 finish_reason=length。留着它，日志里能一句话说清是截断还是格式错。
        "finish_reason": choice.get("finish_reason") or "",
    }


def health(cfg: dict | None = None) -> dict:
    """不花钱的探活：/models。没 key 时把找过的路径一起列出来（排查「未配置模型」用）。"""
    if cfg is None:
        try:
            cfg = load_config()
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e), "tried": config_candidates()}
    t0 = time.time()
    try:
        models = list_models(cfg)
        return {"ok": True, "models": models, "source": cfg["source"],
                "base_url": cfg["base_url"], "seconds": round(time.time() - t0, 2)}
    except urllib.error.HTTPError as e:
        return {"ok": False, "error": "HTTP %s" % e.code, "source": cfg["source"]}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e), "source": cfg["source"]}


def main(argv: list[str]) -> int:
    if "--check" in argv:
        info = health()
        print(json.dumps(info, ensure_ascii=False, indent=2))
        return 0 if info.get("ok") else 1
    if "--chat" in argv:
        i = argv.index("--chat")
        prompt = argv[i + 1] if i + 1 < len(argv) else "说一句话"
        out = chat([{"role": "user", "content": prompt}])
        print(out["text"])
        print("--- %s · %s · %ss" % (out["model"], out["source"], out["seconds"]))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
