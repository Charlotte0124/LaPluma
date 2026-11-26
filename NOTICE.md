# 许可分层与归属

本仓库不是「一个许可覆盖全部」，而是按资产类型分层。**每一层的边界以本文件与各许可文件为准。**

| 范围 | 许可 | 你能做什么 | 文件 |
|:--|:--|:--|:--|
| 程序代码：`ui/`、`engine/`、`tools/`、`api/`、`paths.py`、`courses.json`、`一键启动.*` | **MIT** | 自由使用、修改、二次分发、商用；保留版权与许可文本即可 | [LICENSE](LICENSE) |
| 示例内容：`DEMO/`（课程数据、讲义成品 PDF、讲义源）与 `docs/资产/`、`docs/预览/` 的图片 | **CC BY-NC 4.0** | 署名后可查看、引用、学习、非商业再分发；**不得商用** | [LICENSE-CONTENT.md](LICENSE-CONTENT.md) |
| 文档正文：`docs/` 下除 `资产/`、`预览/` 以外的 Markdown | **CC BY 4.0** | 署名后可转载、翻译、改编（含商业场景） | [LICENSE-DOCS.md](LICENSE-DOCS.md) |
| 名称「羽毛笔 / La Pluma」、图标 `assets/lapluma.ico`、产品标识 | **保留所有权利** | 不得用于他方产品的命名、发布或宣传以致混淆来源 | 本文件 |

## 名称与图标

MIT 只授权代码，不授权名称与标识。你可以把代码改名后发布，但**不得**：

- 以「羽毛笔 / La Pluma」或其近似名称发布你修改后的版本；
- 使用 `assets/lapluma.ico` 或产品介绍图暗示原作者为你的产品背书。

## 真实课程数据不入库

真实课程目录里只保留两个 `.gitkeep` 占位。它的课程数据（`<课程>/_lessons/*.py`）与导入的原件（`*/00_原件/*`）由 [.gitignore](.gitignore) 排除，**从未进入本仓库历史**。

换句话说：仓库里能跑起来的是示例课程 `DEMO`，你自己的课件只在你本机。

## 归属

- 作者：Ryo `<210612614+Charlotte0124@users.noreply.github.com>`
- 版权：Copyright (c) 2026 Ryo
- 第三方组件：`tools/print/pdfjs/` 为 Mozilla pdf.js（Apache License 2.0，两个 `.mjs` 文件头已声明）；其余依赖见 [README](README.md) 的「依赖」一节。

## 这不是法律意见

本文件说明的是本仓库的授权范围，不构成法律建议。许可条款以各许可文件的官方全文为准。
