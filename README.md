# 羽毛笔 La Pluma

把一讲的**内容数据**渲染成一份**能核对的讲义 PDF**：数据 → 讲义源 → 打印 → 过三道门 → 输出。

不是排版模板集，是一条可复算的流水线：同一份数据重跑，页数、目录页码、术语英文都不该变。

## 分层（A–E）

| 层 | 目录 | 职责 | 换掉它会发生什么 |
|:--|:--|:--|:--|
| **A 引擎** | `engine/` | 数据 → 整份讲义源 HTML（模板、封面、目录、术语表、附录） | 版式变，内容不变 |
| **B 内容** | `CS340/_lessons/` | 每讲一份 `LESSON` 数据：节、讲法、原文引用、符号表 | 内容变，引擎不变 |
| **C 检查与打印** | `tools/print/` | 内容门 / 版式门、术语附英、HTML→PDF（本机 Chrome 无头打印） | 成品不出去 |
| **D API** | `api/client.py` | 内容生产用的模型接入（DeepSeek 兼容口径），key 永不入库 | 已有数据仍能出 PDF，只是没法自己写新内容 |
| **E 界面** | `ui/` | 本地网页界面：选课程、选输出、生成前免责声明 | 只剩命令行 |

分层的意义：A、B、C 三层零依赖外部服务，**离线可跑**；D 只在「写新内容」时才需要。

## 快速开始

```powershell
cd LaPluma
python engine\_make.py L02          # 生成 + 内容门 + 打 PDF + 版式门
python engine\_make.py L03 L04-01    # 一次多份
```

产物：
- 讲义源 `CS340\06_笔记\<讲号>_零基础_讲义_源.html`
- 成品 `CS340\01_讲义\<讲号>_…_讲义.pdf`

依赖：Python 3.12、`pymupdf`、本机 Chrome 或 Edge（打印用）。无前端构建、无 npm。

## 三道门

| 门 | 判据 | 跑法 |
|:--|:--|:--|
| 源 | 课件引用能对上、图注不空 | `python tools\src\source_audit.py` |
| 内容 | `data-reader`、公式后符号表、每节讲法、术语每节首次附英、单段 ≤210 字 | `python tools\print\audit_lesson.py --content --file <源.html>` |
| 版式 | 每页首行是标题/表格/图注、正文不起页、无空白残页 | `python tools\print\audit_lesson.py CS340` |

红项不出货——这不是建议，是流水线里的 `return 1`。

## API 配置（D 层）

**key 永不入库。** 读取顺序：`PLUMA_API_KEY` 环境变量 → `%USERPROFILE%\.pluma\api.json` → PRTS 侧 `secrets\api.json` → 界面手填。

```powershell
python api\client.py --check              # 探活，不花钱
python api\client.py --chat "写一句开场"   # 一次性问答
```

模型：`deepseek-flash`（默认，快省）、`deepseek-v4-pro`（更强）。

## 内容数据长什么样

`CS340/_lessons/L02.py` 里是一个 `LESSON` 字典：

```python
LESSON = {
    "code": "CS340", "no": "L02", "zh": "进程的基本管理", "en": "Basic Process Management",
    "out": "L02_进程的基本管理_讲义.pdf",
    "meta": [("源课件", "…58 页"), ("页码口径", "…")],
    "sections": [
        {"no": "0", "zh": "本讲导读", "en": "…", "lec": "这一节怎么讲",
         "body": [("p", "<b>…</b>正文段落"), ("q", "原文引用", "课件 p.4")]},
    ],
    "appendix": {"symbols": [...], "myths": [...]},
}
```

`lec` 是讲法，`body` 是内容；`("q", 原文, 出处)` 表示逐字引用并要求能对上源课件。

## 目录

```
engine/            A 引擎（_build_讲义.py / _make.py / _split_long.py / _pagediag.py）
CS340/_lessons/    B 内容数据（每讲一份）
CS340/06_笔记/     生成的讲义源 HTML（不入库）
CS340/01_讲义/     生成的 PDF（不入库）
tools/print/       C 三道门 + 打印 + KaTeX 字体
api/               D 模型接入
ui/                E 本地界面
```

## 许可与免责

MIT。见 `LICENSE`。

**讲义内容由 AI 辅助整理，可能与原始课件不一致；重要信息请自行核实。** 每份成品页脚固定带这条提示，不提供关闭。
