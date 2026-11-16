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
# 接口 GET /models 实测只给这两个 id（python api\client.py --check 可复验）。
# 界面把它叫作 DeepSeek 4.1 Flash / 4.1 Pro，但发请求时用的必须是下面这两个 id，
# 写成 deepseek-4.1-flash 之类会被服务端拒。
MODELS = ("deepseek-flash", "deepseek-v4-pro")

USER_CFG = os.path.join(os.path.expanduser("~"), ".pluma", "api.json")
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PRTS_CFG = os.environ.get("PLUMA_PRTS_SECRETS") or os.path.normpath(
    os.path.join(_ROOT, "..", "Project", "PRTS", "projects", "课程", "ops", "secrets", "api.json")
)


def _read(path: str) -> dict:
    try:
        # PowerShell 写的 UTF-8 带 BOM，必须用 utf-8-sig，否则 json 解析直接失败
        with open(path, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception:
        return {}


def load_config(explicit_key: str | None = None) -> dict:
    """按三级顺序取配置；全空则报错，不静默降级。"""
    cfg = {"provider": "DeepSeek", "base_url": DEFAULT_BASE, "model": DEFAULT_MODEL, "api_key": "", "source": ""}

    env = os.environ.get("PLUMA_API_KEY", "").strip()
    if env:
        cfg["api_key"] = env
        cfg["source"] = "env:PLUMA_API_KEY"
        cfg["base_url"] = os.environ.get("PLUMA_BASE_URL", DEFAULT_BASE)
        cfg["model"] = os.environ.get("PLUMA_MODEL", DEFAULT_MODEL)
        return cfg

    for path in (USER_CFG, PRTS_CFG):
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
        "② 建 %s；③ 在界面里手填。" % USER_CFG
    )


def _post(url: str, payload: dict, key: str, timeout: int = 90) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + key},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


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
    text = body["choices"][0]["message"]["content"]
    return {
        "text": text,
        "model": use_model,
        "usage": body.get("usage", {}),
        "seconds": round(time.time() - t0, 2),
        "source": cfg["source"],
    }


def health(cfg: dict | None = None) -> dict:
    """不花钱的探活：/models。"""
    cfg = cfg or load_config()
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
