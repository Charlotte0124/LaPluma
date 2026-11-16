# API 与密钥

一句话：**key 永不入库。** 仓库里只有「去哪读」的代码，没有 key 本身。

## key 放哪（按顺序找，命中即用）

| 顺序 | 位置 | 适合谁 |
|:--|:--|:--|
| 1 | 环境变量 `PLUMA_API_KEY`（可配 `PLUMA_BASE_URL` / `PLUMA_MODEL`） | 临时跑一次、CI |
| 2 | `%USERPROFILE%\.pluma\api.json` | 自己机器长期用 |
| 3 | 界面里手填（只落到上面第 2 个位置） | 第一次用 |

配置文件长这样：

```json
{
  "provider": "DeepSeek",
  "base_url": "https://api.deepseek.com",
  "model": "deepseek-flash",
  "api_key": "sk-…"
}
```

## 什么时候需要 key

| 任务 | 需要吗 |
|:--|:--|
| 已有数据 → 出 PDF（重建讲义） | **不需要**，纯本地 |
| 写新一讲的内容（读课件 → 写正文、讲法、术语） | **需要** |

界面上右上角的灯就是在说这件事：`API 可用` 或 `API 未配置（不影响出 PDF）`。

## 命令

```powershell
python api\client.py --check                # 探活，不花钱（走 /models）
python api\client.py --chat "写一句开场"     # 一次性问答
```

返回里会带来源，例如 `--- deepseek-flash · %USERPROFILE%\.pluma\api.json · 0.71s`，方便你确认它读的是哪一份配置。

## 两个安全约定

1. **`.gitignore` 已经挡住** `api.json`、`.env`、`*.key`、`*.pem`、`secrets/`。往里加新仓库时，这几条要跟着走。
2. **别把 key 贴进聊天框、issue、PR 描述。** 一旦贴出去就当作已泄露，去控制台换一把新的。

## 模型怎么选

| 模型 | 场景 |
|:--|:--|
| `deepseek-flash`（默认） | 快、便宜，日常生成足够 |
| `deepseek-v4-pro` | 长讲、结构复杂的推导，值得多花钱时用 |

换模型只改配置文件里的 `model`，或界面里选。同一份数据换模型重跑，内容会变，页数可能变——这不是 bug。
