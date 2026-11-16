# 羽毛笔 La Pluma · 一键启动
# 用法：右键 → 使用 PowerShell 运行；或在 PowerShell 里执行 .\一键启动.ps1
# 做什么：查 Python → 装 pymupdf（缺才装）→ 起本地界面 → 打开浏览器
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$root = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $root

Write-Host '羽毛笔 La Pluma · 一键启动' -ForegroundColor DarkGray

$py = (Get-Command python -ErrorAction SilentlyContinue)
if (-not $py) {
    Write-Host '没有找到 python。请先装 Python 3.12（https://www.python.org/downloads/），勾选 Add to PATH。' -ForegroundColor Red
    Read-Host '按回车退出'
    exit 2
}
$ver = & python -c "import sys;print('%d.%d'%sys.version_info[:2])"
Write-Host "Python $ver"

& python -c "import pymupdf" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host '安装依赖 pymupdf ...' -ForegroundColor DarkGray
    & python -m pip install --quiet pymupdf
    if ($LASTEXITCODE -ne 0) {
        Write-Host '装 pymupdf 失败：检查网络或换 pip 源后重试。' -ForegroundColor Red
        Read-Host '按回车退出'
        exit 3
    }
}

Write-Host '启动界面：http://127.0.0.1:8765/  （Ctrl+C 停止）' -ForegroundColor Green
& python "ui\server.py"
