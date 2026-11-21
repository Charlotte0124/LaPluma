# 羽毛笔 La Pluma · 工作守则

> 工作目录设为本仓根时自动注入。这里只放**每次都要遵守**的硬规矩；产品说明在 `README.md`，用法在 `docs\`。
> 一条规矩必须带检查点，没有检查点的规矩等于不存在。

## 一、界面改动：先出图，再做（2026-11-16 用户定）

**为什么有这条**：提交 `390bd7b`（2026-11-16 20:20）把「成品形态（单本/合订本）」与「问课件」两块界面直接落库，用户此前没看过任何图，事后问「不是说会给我渲染图的吗」。
真因不是忘了，是**规矩只活在助手记得的地方**：仓里没有这条文件、没有判据、也没有放设计稿的位置，所以漏了不会变红，也没人发现。

1. **先画、先拍、先给图**：任何 `ui\` 的可见改动，先做样张（独立 HTML 或说明图）→ 用 Edge 无头拍到 `docs\预览\` → 把图给用户看。
2. **用户说「可以」之前，不改 `ui\index.html` 与 `ui\server.py`。** 自己判断「差不多了」不算许可。
3. **两个位置不许混**：设计稿 = `docs\预览\`（还没实现）；成品截图 = `docs\资产\界面-*.png`（已实现，能对得上真实界面）。
4. **新稿必须登记** `docs\预览\README.md`：文件名 · 画的是什么 · 解决什么 · 状态。
5. **图与码放同一个提交**：改 `ui\` 的提交里必须带上 `docs\预览`（设计稿或登记表）或 `docs\资产\界面-*.png`（真实截图）。分两次提交会被判红——这是判据的硬要求，不是建议。
6. 实现上线后：状态改「已实现」，并在 `docs\资产\` 补一张真实界面截图（不是把设计稿搬过去）。

**怎么验证它被执行**：`python tools\check\check-ui-preview.py`

| 灯 | 含义 |
|:--|:--|
| 红 A | `ui\` 最后一次提交比 `docs\预览` 晚 —— 改了界面没带新预览图 |
| 红 B | 预览目录里有没登记的孤儿图 / 一张图都没有 / 缺 `README.md` |
| 黄 C | `ui\` 有未提交改动，而 `docs\预览` 没动 —— 正在改界面，图没跟上 |
| 黄 D | `docs\资产\界面-*.png` 比 `ui\` 旧 —— 忘了重拍 |

它自带 `--selftest`：临时仓里造四种坏，五种情形全部按预期才算判据可信（先证明它会红，再看它绿）。

## 二、讲义的三道门不许绕过

- 一条命令出货：`python engine\_make.py L01`（生成 → 术语每节首次附英 → 拆长段 → 内容门 → html2pdf → 版式门）。
- **任一门红即停**，不许为了变绿改判据；判据要改，先说明旧判据放过了什么。口径见 `docs\使用\03-三道门.md`。
- 术语表必须 `class="glossary"`；文件名与路径不要手写数字，页数从产物里读。

## 三、密钥、路径、产物

- API key 只存本机：`%USERPROFILE%\.pluma\api.json`（三级回退 `PLUMA_API_KEY` → 用户目录 → 本仓 ops 下的 secrets），**任何 key 都不进 Git**。
- 成品 PDF 在 `CS340\01_讲义\`、`out\` 都是生成物，不进库（见 `.gitignore`）。
- 写入类操作先落地再回查（有大小、有条数），不许只报「已写入」。


## 四、署名

- 作者只用 `Ryo <210612614+Charlotte0124@users.noreply.github.com>`。
- 禁 `Co-authored-by`，禁任何 bot / AI / 工具署名。
- 一个提交做一件事；上传前扫一遍密钥、本机路径、真实人名。

## 五、导入占位不许当成品（2026-11-19）

用户实测：99 页课件导进来，点生成出 7 页「原件导入占位 · 正文待补」。根因不是排版，是**导入只建骨架、生成只渲染骨架**。以后按这四条做：

1. **导入**只建骨架，数据必须带 `"stub": true` 与 `"orig": "<原件名>"`（`ui\server.py` 的 `make_stub_lesson()`）。
2. **生成前**必须走 `ensure_body()`：占位先让 DeepSeek 补正文；补不出来就停，不许渲染占位 PDF。
3. **渲染 / 内容门双闸**：`engine\_make.py` 见 `stub` 直接 `[停]`；内容门见「原件导入占位 / 正文待补」判红。
4. **扫描件**（无文字层）导入时当场提示「自动写正文不可用」，不许等到生成才失败。

**怎么验证它被执行**：`python tools\check\check-stub-guard.py` 必须 **4/4**；提交前由 `.githooks/pre-commit` 自动跑（连同 `check-ui-preview.py`），红了提交就被拦下。新克隆 `core.hooksPath` 不会跟着过来，先跑一次 `powershell -File tools\check\install-hooks.ps1`。

## 六、分发只走文件夹，不再打 exe（2026-11-21 用户定）

**为什么有这条**：2026-11-21 用户在 `dist\LaPluma.exe` 上双击只看到 `Error / Could not create temporary directory!`——PyInstaller 单文件启动第一步要把 86 MB 解包到 `%TEMP%`，这台机器上建目录被拒，我们的代码一行都没执行。用户随后定：「以后直接是文件夹的那种形式吧，不打包了。」

1. 分发形态只有一个：**仓库文件夹 + `启动羽毛笔.cmd`**（控制台可见地起 `ui\server.py`：起不来时原因就在屏幕上；要无控制台加 `-Windowed`）。不再产出 `dist\LaPluma.exe`，不再维护单文件打包脚本与 spec。
2. 启动入口只有一个：`启动羽毛笔.cmd`。要 `-Lan` / `-NoWindow` 走 `一键启动.ps1`，不要另造入口。
3. **启动器必须是纯 ASCII，用 `*.ps1` 通配找启动脚本**（2026-11-21）。双击时 cmd.exe 按系统 ANSI 码页（本机 936）读 `.cmd`，文件里硬编码中文名会被解成乱码，powershell 拿到不存在的路径、控制台一闪即关——用户看到的就是「双击没反应」。同样内容改成 GBK 存的 `.bat` 就一直能用，这正是当时「只有 一键启动.bat 打得开」的原因。改启动器时不要把中文写回去。
4. 环境要求写进 README：Python 3.12 + `pymupdf`。

**怎么验证它被执行**：`python tools\check\check-distribution.py`（红 = 又出现 exe / 打包脚本、启动入口缺失、或启动器里混进非 ASCII 字节）。
## 七、模型返回的 JSON 要容错地取（2026-11-21）

**为什么有这条**：用户在「生成」页点开始生成，只拿到一句「[停] 补正文失败：JSONDecodeError('Expecting property name enclosed in double quotes: line 1 column 1126 (char 1125)')」——界面等于死路。旧实现取 JSON 是「第一个 `{` 到最后一个 `}`」一刀切：模型多吐一个对象、前面带一段示例、或者带尾逗号，就必错；输出被长度上限截断时也只会报这一句，看不出是截断。

1. 取 JSON 走 `engine\_draft._json_of`（整段 → 去掉尾逗号 → 从每个括号起点 `raw_decode`），不要在别处再写一刀切的 `json.loads`。
2. 解析不出来时**换更硬的提示重试一次**；两次都不行才停，并且把两次的原文落盘到 `<课程>\_trash\draft-*.txt`，停的时候要把路径说出来（没有原文，连作者都判不出是多了示例还是被截断）。
3. **截断要说得出口**：`api\client.chat` 返回 `finish_reason`，是 `length` 时日志要写明「输出被长度上限截断」。
4. 术语这类补充项解析失败不许把整讲判死（返回空表继续，后面会补齐）。

**怎么验证它被执行**：`python tools\check\check-draft-json.py` 必须 **7/7**（提交钩子 `.githooks\pre-commit` 自动跑）。

## 八、验证在真窗口里做，别开浏览器（2026-11-21 用户定）

**为什么有这条**：我为了截图和回归，反复用 Playwright / 无头浏览器跑检查，用户浏览器里堆了 7 个 `127.0.0.1:8896` 标签页。用户原话：「可以不要一直弹出浏览器吗」「你在浏览器可以做出来的，软件做不出来」「我也不会看截图」。

1. **任何起服务的脚本/检查，必须同时带 `--no-window --no-browser`**：`--no-window` 只是不起自绘窗口，服务端仍会 `webbrowser.open` 叫系统浏览器——这是那 7 个标签页的来源。
2. 验收以**软件自己的窗口（WebView2）**为准：截图用 `PrintWindow` 抓真窗口，不用浏览器页代替。
3. 浏览器只允许在用户明确要求时手动打开；不许把它当默认验证手段。
4. 给用户看结果时，一段话＋关键数字就够，不必附截图（用户明确说不看）。

**怎么验证它被执行**：`grep -L -- "--no-browser" tools/check/*.py` 里出现起服务的脚本即算红；`.githooks\pre-commit` 每次提交都会跑 `check-ui-conflicts`，它起服务的那一行必须带这两个开关。

## 九、改完必须落规矩，规矩必须接钩子（2026-11-22 用户定）

**为什么有这条**：用户原话「每次改动结束之后都要保存最新的规矩，不然永远都会发生老问题，并且制作钩子防止这事情发生、确保这规矩运行」。

1. 每次改动收尾时，问一句：**这次踩的坑，下次怎么挡住？** 要写就写进本文件（一句为什么 + 可执行的条 + 判据）。
2. 写进 AGENTS.md 的规矩，必须有一条能失败的判据放在 `tools/check/`，并接进 `.githooks/pre-commit`。
3. `tools/check/check-rules-wired.py` 检查「判据 ↔ 规矩」两边对得上：有判据没规矩、有规矩没判据都判红。

**怎么验证它被执行**：`python tools/check/check-rules-wired.py` 全接上才算绿（提交钩子自动跑）。

## 十、窗口层改动（2026-11-22）

1. 全屏前必须 `keep_bounds()` 记下矩形，退出时 `restore_bounds()` 设回去——用户实测「退出全屏后占满屏幕、缩不回去」。
2. 窗口层（无边框拖动 / 缩放 / 全屏）改动只能用软件窗口验（PrintWindow），不许用浏览器页代替。

## 十一、阅读页的移动 / 翻译 / 笔记（2026-11-22 用户定）

**为什么有这条**：用户按六条实测提了「标题条拖不动 / 全屏退出缩不回去 / 原件放错课程搬不走 / 右键翻译后没法记账 / 笔记只能挤在侧栏 / 译文翻完就丢」。这些都在 WebView2 的窗口层与阅读侧栏里，光看代码「好像接上了」不算，必须逐条有判据。

1. **标题条拖动的唯一实现**：`ui\index.html` 的标题条 mousedown 只调 `window.pywebview.api.drag_window()`；`_WinApi.drag_window()` 在 Python 侧跑拖动循环——`GetWindowRect` 记左上角、`GetCursorPos` 读系统光标、`GetAsyncKeyState(VK_LBUTTON)` 判松手、`SetWindowPos` 跟着挪。双击标题条走 `toggle_max()`。
   - 不许回到 JS pointermove + move_by（每步过一次桥，卡；指针离开标题条就丢事件）。
   - 不许回到 `ReleaseCapture()` + `SendMessageW(0x00A1, HTCAPTION)`：**2026-11-22 真窗口实测无效**——本窗口是 pywebview 的无边框 WinForms 窗口，WinForms 的 WndProc 不把这消息交给 DefWindowProc，系统拖动循环根本不启动，`SendMessage` 立刻返回 0、窗口纹丝不动（`check-window-real.py --drag` 量到位移 0px）。
2. **退出全屏必须还尺寸**：`restore_bounds()` 先 `SW_RESTORE` 掉最大化，再用 `SWP_SHOWWINDOW|SWP_FRAMECHANGED`（`0x0040|0x0020`）连设两次；页面在 `exitFullscreen` 后立刻调一次、260ms 再补一次。
3. **原件能搬走**：抽屉原件行必须有「移动」，弹窗选目标课程后调 `/api/move-originals`（原件 + 占位讲次一起搬）；成功后 `await boot()` 重取课程与讲次，再重画列表。
4. **译文能记成笔记**：译文结果必须有「记成笔记」，把 `【译文 p.N】…` 追加到 `#nDraft` 并切到「笔记」页签。选中文字菜单**只能**由 `contextmenu` 打开，不许在 mouseup / pointerup 里再弹。
5. **笔记分两层**：侧栏只留笔记列表 + `#nDraft` 快速记一笔；「记笔记」打开整页视图（左原文引用 / 右输入框），保存走 `/api/notes` 后回列表。
6. **翻译历史最多 5 条**：存 `%USERPROFILE%\.pluma\translate-history.json`（`PLUMA_HOME` 可改），字段为时间 / 原文前 120 字 / 译文前 400 字；翻译页签顶部列最近 5 条，点一条回填 `#trSrc` 与译文。

**怎么验证它被执行**：`python tools\check\check-reading-tools.py` 必须 **6/6**，且 `--selftest` 6/6（临时副本逐条造坏，证明判据会红）；提交钩子 `.githooks\pre-commit` 自动跑。

## 十二、文字层 / 已成稿列表 / 干净启动器（2026-11-22 用户定）

**为什么有这条**：用户按实测提了「选中的位置跟实际的字不完全重合」「生成完了之后 应该要在列表里面消失掉（虽然他还在那个课件里面），除非在课件里面选择重新生成」，并要求启动器单独放一个干净文件夹。三件都属于「代码看着对、真用起来错」，各配一条会失败的判据。

1. **文字层用 pdf.js 官方 TextLayer**：`renderTextLayer()` 必须 `new lib.TextLayer({textContentSource, container, viewport})`——每段一个 div，left/top 是整页百分比、宽度靠 scaleX。容器必须先 `box.style.setProperty('--scale-factor', String(vp.scale))`（官方层的字号是 `calc(Npx * var(--scale-factor))`；缺这个变量字号就错，选中框跟着偏）。不许回到「按行合并成一个 span」（只有整行的 left/top，逐段宽度还原不了）。官方层不可用时才退回按行合并，并把走的路记在 `#pdftext.dataset.tl`（official / official-fail / fallback）。
2. **已成稿的讲次不出现在生成列表**：后端 `lesson_meta()` 按磁盘事实算 `done`——原件目录里还有它那份源课件（`orig` 与文件名主干对上）**且** `01_讲义` 里有 `<讲号>_…pdf`；两条都成立才算成稿（只导入没生成的占位不算，出厂示例课程没原件也不算）。界面 `syncLessons()` 过滤掉 done 的讲并提示「另有 N 讲已成稿」。重做入口只有一个：课程抽屉的成品行「重新生成」（`data-fregen`）——点了把它放回列表并勾上（`REGEN` 集合），生成成功后自动移出、又回到隐藏。
3. **启动器单独一个干净文件夹**：`F:\DSH\apps\羽毛笔\` 里只放一个纯 ASCII 的 `启动羽毛笔.cmd`（`%~dp0` + 通配符找 `..\LaPluma\*.ps1`，带 `-Windowed`）；桌面快捷方式指向它。目录里多一个文件、或启动器里出现一个非 ASCII 字节，都算红——936 代码页会把中文读成乱码，双击就没反应（§六.3 的同一个坑）。
4. **自测一律跑临时数据根**：要造「原件 + 成品」这类数据，用 `tools\check\_win_launch.py` + `PLUMA_TEST_DATA=<临时目录>`（在 import 之前改 `paths.DATA_ROOT`），跑完删掉；不许往用户自己的课程目录里造样本。

**怎么验证它被执行**：`python tools\check\check-window-layer.py` 必须 **3/3**，`--selftest` 6/6（逐条造坏都要变红）；提交钩子自动跑。只有真窗口量得出的（窗口矩形、选中框对位、拖动），跑 `python tools\check\check-window-real.py`（会弹一下软件窗口，约 40 秒；加 `--drag` 再做一次真实鼠标拖动）：W1 真窗口 / W2 全屏进出还原（±2px）/ W3 文字层与 pymupdf 词框对位（±4px）/ W4 成稿隐藏与重新生成 / W5 只有右键弹菜单 / W6 拖动。

## 十三、判据清单（谁是自动跑、谁要手动跑）

| 判据 | 跑法 |
|:--|:--|
| `check-stub-guard.py` | 提交钩子自动 |
| `check-distribution.py` | 提交钩子自动 |
| `check-ui-preview.py` | 提交钩子自动 |
| `check-ui-conflicts.py` | 提交钩子自动 |
| `check-lecture-rules.py` | 提交钩子自动 |
| `check-draft-json.py` | 提交钩子自动 |
| `check-reading-tools.py` | 提交钩子自动（阅读页六条：拖动 / 全屏 / 移动 / 翻译笔记 / 整页笔记 / 历史） |
| `check-window-layer.py` | 提交钩子自动（文字层 / 成稿隐藏 / 干净启动器） |
| `check-rules-wired.py` | 提交钩子自动（本文件与 tools/check 对账） |
| `check-error-guard.py` | 手动：`python tools\check\check-error-guard.py`（打 14 条坏请求验错误兜底） |
| `check-fresh-install.py` | 手动：全新配置跑一遍首启流程 |
| `check-paths.py` | 手动：数据根 / 保存目录解析 |
| `check-figref.py` | 手动：讲义图引用路径 |
| `check-pdf-brand.py` | 手动：成品 PDF 的固定文案与品牌 |
| `check-startup-guard.py` | 手动：启动期自保（遮蔽目录 / stdout） |
| `check-update.py` | 手动：应用内更新逻辑 |
| `check-window-real.py` | 手动：真窗口量测（全屏矩形 / 选中框对位 / 成稿隐藏 / 右键菜单），`--drag` 含真实鼠标拖动；约 40 秒 |
| `_win_launch.py` | 不是判据：自测启动器（`PLUMA_TEST_DATA` 指临时数据根），只给 `check-window-real.py` 用 |
