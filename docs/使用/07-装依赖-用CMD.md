# 装依赖：用 CMD 手动装（图文步骤）

最后核对：2026-11-17 · 适用 v1.9.0

一句话：**一键启动脚本自动装不上时，用「命令提示符（CMD）」手打两行就行。**

## 什么时候需要看这一页

| 现象 | 意思 | 怎么办 |
|:--|:--|:--|
| 双击 `一键启动.bat`，黑窗口一闪就没 | 多半是没装 Python 3.12 | 看下面第 1 节 |
| 窗口停在「pymupdf 没装上」 | 自动装依赖失败（网络 / pip 源） | 看下面第 2 节 |
| 界面能开，但点「开始生成」就失败 | pymupdf 缺失 | 看下面第 2 节 |
| 你用的是 Release 里的 `LaPluma.exe` | **exe 自带运行环境，不需要 Python、不需要装任何东西** | 这一页用不上 |

## 1. 先装 Python 3.12

1. 打开 <https://www.python.org/downloads/>, 下载 **Windows installer (64-bit)** 的 3.12.x。
2. 安装第一屏，**勾上最下面的 `Add python.exe to PATH`**，然后点 `Install Now`。
3. 装完**关掉所有黑窗口**，再双击 `一键启动.bat`。

验证：开始菜单搜 `cmd` → 打开「命令提示符」→ 输入

```
python --version
```

看到 `Python 3.12.x` 就对了。若提示「不是内部或外部命令」，说明 PATH 没勾上：重装一次，勾上那一项。

## 2. 装依赖 pymupdf

1. 开始菜单搜 `cmd` → 打开「命令提示符」。
2. 输入下面**一行**（整行粘进去，回车）：

```
python -m pip install pymupdf -i https://pypi.tuna.tsinghua.edu.cn/simple
```

3. 等它跑完，最后一行出现 `Successfully installed pymupdf-…` 就算好了。
4. 验证：

```
python -c "import pymupdf; print(pymupdf.__version__)"
```

打印一个版本号（例如 `1.24.x`）即成功。

> `python` 认不出来时，把命令里的 `python` 换成 `py -3.12`：
> `py -3.12 -m pip install pymupdf -i https://pypi.tuna.tsinghua.edu.cn/simple`

## 3. 回到软件

双击 `一键启动.bat`。窗口里应依次看到：

```
Python 3.12.x   (…)
启动界面 ...
```

然后弹出羽毛笔的窗口。**没有**「缺依赖」之类的红字就对了。

## 常见报错对照

| 报错里出现的词 | 怎么查 | 怎么改 |
|:--|:--|:--|
| `不是内部或外部命令` | `where python` 有没有输出 | 重装 Python 并勾 `Add python.exe to PATH` |
| `Could not find a version` / `No matching distribution` | 网络是否断、是否需要代理 | 换源：`-i https://pypi.tuna.tsinghua.edu.cn/simple`；仍不行换 `https://mirrors.aliyun.com/pypi/simple/` |
| `Access is denied` / `拒绝访问` | 是否装在 `C:\Program Files` 下的系统 Python | 换成「仅为我安装（Install for me only）」的用户级 Python，再装依赖 |
| `SSL` / `certificate` | 系统证书或 VPN 中间人 | 关掉抓包 / VPN 再装，或加 `--trusted-host pypi.tuna.tsinghua.edu.cn` |
| `ERROR: pip's dependency resolver` | 不影响 pymupdf 本身 | 只要最后有 `Successfully installed pymupdf` 就继续 |

## 为什么只有这一个依赖

出 PDF 要数页、回填目录页码、把笔记追加成附页，这些都靠 PyMuPDF（`import pymupdf`）。其余全部是 Python 标准库，不需要 npm、不需要前端构建、不需要数据库。
