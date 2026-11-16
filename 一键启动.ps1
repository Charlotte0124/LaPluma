# 羽毛笔 La Pluma · 一键启动（源码版）
# 最省事：双击 一键启动.bat（直接双击 .ps1 在默认设置下会被记事本打开，不运行）
#   .\一键启动.ps1            起界面（默认开自己的窗口）
#   .\一键启动.ps1 -Lan       上线：局域网 + 8 位访问码（平板同一 WiFi 用）
#   .\一键启动.ps1 -NoWindow  回到浏览器页（远程调试 / 老显卡）
# 它做三件事：查 Python（要 3.12）→ 查 pymupdf（缺就自动装）→ 起界面；哪步不行都说清怎么办
param([switch]$Lan, [switch]$NoWindow)

$ErrorActionPreference = 'Continue'
try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch { }
$root = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $root

function Stop-Here([string]$msg, [int]$code) {
    Write-Host ''
    Write-Host $msg -ForegroundColor Red
    Write-Host ''
    Write-Host '按回车关闭这个窗口' -ForegroundColor DarkGray
    [void](Read-Host)
    exit $code
}

Write-Host '羽毛笔 La Pluma · 一键启动' -ForegroundColor DarkGray

# ---------- 1. Python（要 3.12） ----------
$pyExe = $null
$pyArgs = @()
$c = Get-Command python -ErrorAction SilentlyContinue
if ($c) { $pyExe = $c.Source }
if (-not $pyExe) {
    # 没把 python 加进 PATH 时，py 启动器通常还在
    $c = Get-Command py -ErrorAction SilentlyContinue
    if ($c) { $pyExe = $c.Source; $pyArgs = @('-3.12') }
}
if (-not $pyExe) {
    Stop-Here @'
没找到 Python —— 这个仓库的源码版要 Python 3.12：https://www.python.org/downloads/
安装时务必勾上「Add python.exe to PATH」，装完关掉这个窗口重新双击。
只想用软件、不写代码：装现成的 exe 更省事，那个不需要 Python：
https://github.com/Charlotte0124/LaPluma/releases/latest
'@ 2
}
$verRaw = (& $pyExe @pyArgs -c "import sys;print('%d.%d.%d'%sys.version_info[:3])" 2>$null)
if (-not $verRaw) {
    Stop-Here "找到了 $pyExe，但它跑不起来（常见原因：这是 Microsoft Store 的占位 python）。装一份官方 3.12 再来。" 2
}
$verRaw = ($verRaw | Select-Object -First 1).Trim()
$parts = $verRaw -split '\.'
$major = [int]$parts[0]
$minor = [int]$parts[1]
Write-Host "Python $verRaw   ($pyExe)"
if ($major -ne 3 -or $minor -lt 10) {
    Stop-Here "版本太低：要 Python 3.12，现在是 $verRaw。下载：https://www.python.org/downloads/" 2
}
if ($minor -ne 12) {
    Write-Host "提示：本仓按 Python 3.12 开发与实测，你的是 $verRaw。" -ForegroundColor Yellow
    Write-Host '      先往下跑也行；出怪问题先换回 3.12（安装包地址同上）。' -ForegroundColor DarkGray
}

# ---------- 2. 依赖 pymupdf（只有这一个） ----------
& $pyExe @pyArgs -c "import pymupdf" 2>$null
$hasPdf = ($LASTEXITCODE -eq 0)
if (-not $hasPdf) {
    Write-Host '缺依赖 pymupdf，正在自动安装（要联网，几十秒）...' -ForegroundColor DarkGray
    & $pyExe @pyArgs -m pip install --quiet --disable-pip-version-check pymupdf
    & $pyExe @pyArgs -c "import pymupdf" 2>$null
    $hasPdf = ($LASTEXITCODE -eq 0)
}
if (-not $hasPdf) {
    Write-Host ''
    Write-Host 'pymupdf 没装上（大概率是网络 / pip 源）。手动装一次，三步：' -ForegroundColor Yellow
    Write-Host '  1) 开始菜单搜 cmd → 打开「命令提示符」'
    Write-Host '  2) 粘下面这一行，回车（走清华镜像，国内快）：'
    Write-Host ("     `"$pyExe`" -m pip install pymupdf -i https://pypi.tuna.tsinghua.edu.cn/simple") -ForegroundColor White
    Write-Host '  3) 看到 Successfully installed 就关掉 cmd，再双击一次「一键启动.bat」'
    Write-Host '图文步骤：docs\使用\07-装依赖-用CMD.md' -ForegroundColor DarkGray
    Stop-Here '依赖没装好，先停下（界面能开，但出 PDF 与阅读会失败）。' 3
}

# ---------- 3. 起界面 ----------
# 输出被重定向到文件时（自动化 / 留日志），强制 python 用 UTF-8，否则中文全变乱码
if ([Console]::IsOutputRedirected) { $env:PYTHONIOENCODING = 'utf-8' }
$flags = @()
if ($Lan) { $flags += '--lan' }
if ($NoWindow) { $flags += '--no-window' }
Write-Host '启动界面 ...' -ForegroundColor DarkGray
Write-Host '如果弹「Windows 安全中心」问防火墙，选「专用网络」允许（只在你开上线时才用得上）。' -ForegroundColor DarkGray
& $pyExe @pyArgs 'ui\server.py' @flags
$rc = $LASTEXITCODE
if ($rc -ne 0) {
    Stop-Here "界面退出了（退出码 $rc）。上面最后几行就是原因；看不懂就把那几行发给作者。" $rc
}
