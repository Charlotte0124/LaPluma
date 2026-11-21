# 羽毛笔 La Pluma · 一键启动（源码/文件夹版，不需要打包）
# 双击 启动羽毛笔.cmd 会以 -Windowed 调起本脚本：先查 Python、再查 pymupdf，缺了就弹窗让你点一下装。
#   .\一键启动.ps1              起界面（控制台版，能看到每一步）
#   .\一键启动.ps1 -Lan         上线：局域网 + 8 位访问码
#   .\一键启动.ps1 -NoWindow    回浏览器页
#   .\一键启动.ps1 -CheckOnly   只检查环境（Python / pymupdf），不起界面
#   .\一键启动.ps1 -Python <exe> 指定解释器（默认 python / py -3.12）
param([switch]$Lan,[switch]$NoWindow,[switch]$Windowed,[switch]$CheckOnly,[string]$Python="")

$ErrorActionPreference = "Continue"
try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch { }
$root = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $root

# 2026-11-21 用户：「启动羽毛笔.cmd 也没有用 打不开」。双击（Explorer 拉起）时窗口是隐藏的，
#   脚本里任何一句失败都看不到、也不留痕。这里把每一步写进 .pluma\logs\launcher.log。
$launcherLog = Join-Path $env:USERPROFILE ".pluma\logs\launcher.log"
function Log-Step([string]$m) {
    try {
        $dir = Split-Path -Parent $launcherLog
        if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
        Add-Content -LiteralPath $launcherLog -Encoding UTF8 -Value ((Get-Date -Format "yyyy-MM-dd HH:mm:ss") + "  " + $m)
    } catch { }
}
Log-Step ("start cwd=" + (Get-Location).Path + " windowed=" + $Windowed + " lan=" + $Lan + " checkonly=" + $CheckOnly)

function Show-Msg([string]$text, [string]$title, [string]$kind) {
    if (-not $Windowed) {
        if ($kind -eq "error") { Write-Host $text -ForegroundColor Red } else { Write-Host $text }
        return
    }
    try {
        Add-Type -AssemblyName System.Windows.Forms | Out-Null
        $icon = [System.Windows.Forms.MessageBoxIcon]::Information
        if ($kind -eq "error") { $icon = [System.Windows.Forms.MessageBoxIcon]::Error }
        if ($kind -eq "warn")  { $icon = [System.Windows.Forms.MessageBoxIcon]::Warning }
        [void][System.Windows.Forms.MessageBox]::Show($text, $title, [System.Windows.Forms.MessageBoxButtons]::OK, $icon)
    } catch { Write-Host $text }
}

function Ask-YesNo([string]$text, [string]$title) {
    if (-not $Windowed) { return $false }
    try {
        Add-Type -AssemblyName System.Windows.Forms | Out-Null
        $r = [System.Windows.Forms.MessageBox]::Show($text, $title, [System.Windows.Forms.MessageBoxButtons]::YesNo, [System.Windows.Forms.MessageBoxIcon]::Warning)
        return ($r -eq [System.Windows.Forms.DialogResult]::Yes)
    } catch { return $false }
}

function Fail-Exit([string]$text, [int]$code) {
    Log-Step ("FAIL(" + $code + "): " + $text)
    Show-Msg $text "羽毛笔 La Pluma" "error"
    if (-not $Windowed) { Write-Host ""; Write-Host "按回车关闭这个窗口" -ForegroundColor DarkGray; [void](Read-Host) }
    exit $code
}

# ---------- 1. Python ----------
$pyExe = $null
$pyArgs = @()
if ($Python) {
    if (Test-Path $Python) { $pyExe = $Python } else { Fail-Exit "指定的 Python 不存在：$Python" 2 }
}
if (-not $pyExe) {
    $c = Get-Command python -ErrorAction SilentlyContinue
    if ($c) { $pyExe = $c.Source }
}
if (-not $pyExe) {
    $c = Get-Command py -ErrorAction SilentlyContinue
    if ($c) { $pyExe = $c.Source; $pyArgs = @("-3.12") }
}
if (-not $pyExe) {
    $yes = Ask-YesNo "没找到 Python。羽毛笔的文件夹版需要 Python 3.12。`n`n现在打开 Python 下载页吗？" "缺 Python"
    if ($yes) { Start-Process "https://www.python.org/downloads/" }
    Fail-Exit "没找到 Python —— 装 3.12 时务必勾上 Add python.exe to PATH，装完重新双击 启动羽毛笔.cmd。" 2
}
$verRaw = (& $pyExe @pyArgs -c "import sys;print(chr(46).join(str(x) for x in sys.version_info[:3]))" 2>$null)
if (-not $verRaw) { Fail-Exit "找到了 $pyExe，但它跑不起来（常见原因：Microsoft Store 的占位 python）。装一份官方 3.12 再来。" 2 }
$verRaw = ($verRaw | Select-Object -First 1).Trim()
$parts = $verRaw -split "\."
$major = [int]$parts[0]
$minor = [int]$parts[1]
if ($major -ne 3 -or $minor -lt 10) { Fail-Exit "Python 版本太低：要 3.12，现在是 $verRaw。" 2 }
Log-Step ("python=" + $pyExe + " ver=" + $verRaw + " pymupdf=" + $hasPdf)
if (-not $Windowed) { Write-Host "Python $verRaw   ($pyExe)" }
if ($minor -ne 12 -and -not $Windowed) { Write-Host "提示：本仓按 Python 3.12 开发与实测，你的是 $verRaw。" -ForegroundColor Yellow }

# ---------- 2. pymupdf ----------
& $pyExe @pyArgs -c "import pymupdf" 2>$null
$hasPdf = ($LASTEXITCODE -eq 0)

if (-not $hasPdf -and $CheckOnly) {
    Write-Host "pymupdf: 缺（需要装）"
    Write-Host "python: $verRaw ($pyExe)"
    exit 3
}
if ($hasPdf -and $CheckOnly) {
    Write-Host "pymupdf: 有"
    Write-Host "python: $verRaw ($pyExe)"
    exit 0
}

if (-not $hasPdf) {
    $install = $true
    if ($Windowed) {
        $install = Ask-YesNo "缺依赖 pymupdf（出 PDF 与阅读要用）。`n`n现在自动安装吗？点「是」开始装（要联网，几十秒）；点「否」打开下载页。" "缺 pymupdf"
        if (-not $install) { Start-Process "https://pypi.org/project/PyMuPDF/" }
    } else {
        Write-Host "缺依赖 pymupdf，正在自动安装（要联网，几十秒）..." -ForegroundColor DarkGray
    }
    if ($install) {
        & $pyExe @pyArgs -m pip install --quiet --disable-pip-version-check -i https://pypi.tuna.tsinghua.edu.cn/simple pymupdf
        & $pyExe @pyArgs -c "import pymupdf" 2>$null
        $hasPdf = ($LASTEXITCODE -eq 0)
    }
    if (-not $hasPdf) {
        $cmdline = "`"$pyExe`" -m pip install pymupdf -i https://pypi.tuna.tsinghua.edu.cn/simple"
        Fail-Exit ("pymupdf 没装上（大概率网络 / pip 源）。`n`n在命令行里跑这一行再试：`n" + $cmdline + "`n`n图文步骤：docs\使用\07-装依赖-用CMD.md") 3
    }
    if ($Windowed) { Show-Msg "pymupdf 装好了，继续启动。" "羽毛笔 La Pluma" "info" }
}

# ---------- 3. 起界面 ----------
$flags = @()
if ($Lan) { $flags += "--lan" }
if ($NoWindow) { $flags += "--no-window" }

if ($Windowed) {
    $pyw = Join-Path (Split-Path -Parent $pyExe) "pythonw.exe"
    if (-not (Test-Path $pyw)) { $pyw = $pyExe }
    Log-Step ("starting " + $pyw + " args=" + ((@("ui\server.py") + $flags) -join " "))
    $proc = Start-Process -FilePath $pyw -ArgumentList (@("ui\server.py") + $flags) -WorkingDirectory $root -PassThru
    # 2026-11-21 用户：「启动羽毛笔.cmd 也没有用 打不开」。windowed 模式没有控制台，
    #   起不来时只表现为「双击了没反应」。这里等到窗口出现为止；进程提前退出就弹窗说清楚。
    $deadline = (Get-Date).AddSeconds(30)
    $hwnd = 0
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Milliseconds 300
        $proc.Refresh()
        if ($proc.HasExited) { break }
        if ($proc.MainWindowHandle -ne 0) { $hwnd = $proc.MainWindowHandle; break }
    }
    Log-Step ("wait done hwnd=" + $hwnd + " exited=" + $proc.HasExited + " err=" + $Error[0])
    if ($proc.HasExited) {
        Fail-Exit ("羽毛笔启动后立刻退出了（退出码 $($proc.ExitCode)）。`n`n请双击同一个文件夹里的 一键启动.bat 再来一次：那个窗口会停住不关，最后几行就是原因。") 4
    }
    if ($hwnd -eq 0) {
        Show-Msg "后台服务起来了，但 30 秒内没等到窗口。`n`n先按 Alt+Tab 找找「羽毛笔 La Pluma」——可能被全屏程序挡在后面。`n`n还找不到就双击 一键启动.bat，那个窗口会显示报错。" "羽毛笔 La Pluma" "warn"
    }
    exit 0
}

if ([Console]::IsOutputRedirected) { $env:PYTHONIOENCODING = "utf-8" }
Write-Host "启动界面 ..." -ForegroundColor DarkGray
& $pyExe @pyArgs "ui\server.py" @flags
$rc = $LASTEXITCODE
if ($rc -ne 0) { Fail-Exit "界面退出了（退出码 $rc）。上面最后几行就是原因；看不懂就把那几行发给作者。" $rc }
