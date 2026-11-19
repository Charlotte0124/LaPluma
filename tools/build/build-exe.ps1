# 羽毛笔 La Pluma · 打包成单文件 exe
# 用法：powershell -File tools\build\build-exe.ps1
# 产物：dist\LaPluma.exe（数据写在 exe 旁边，资源解到临时目录）
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$root = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Definition))
Set-Location $root

Write-Host '检查 PyInstaller ...' -ForegroundColor DarkGray
& python -c "import PyInstaller" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host '安装 PyInstaller ...' -ForegroundColor DarkGray
    & python -m pip install --quiet pyinstaller
    if ($LASTEXITCODE -ne 0) { Write-Host '装 PyInstaller 失败' -ForegroundColor Red; exit 3 }
}

# 2026-11-19 用户第 8 条：打包前必须真点一遍按钮/浮层冲突，静态扫描抓不到
Write-Host '打包前行为判据（全屏/弹窗 → 导航）...' -ForegroundColor DarkGray
& python -X utf8 tools\check\check-ui-conflicts.py
if ($LASTEXITCODE -ne 0) {
    Write-Host '行为判据未过：不打包（先修按钮/浮层冲突）' -ForegroundColor Red
    exit 6
}

Write-Host '开始打包（一两分钟）...' -ForegroundColor DarkGray
& python -m PyInstaller "tools\build\lapluma.spec" --noconfirm --clean --distpath dist --workpath .build --log-level WARN
if ($LASTEXITCODE -ne 0) { Write-Host '打包失败，看上面的输出' -ForegroundColor Red; exit 4 }

$exe = Join-Path $root 'dist\LaPluma.exe'
if (-not (Test-Path $exe)) { Write-Host '没生成 dist\LaPluma.exe' -ForegroundColor Red; exit 5 }
$mb = [math]::Round((Get-Item $exe).Length / 1MB, 1)
Write-Host ("完成：dist\LaPluma.exe（{0} MB）" -f $mb) -ForegroundColor Green
Write-Host '双击运行即可；首次启动解包会慢几秒。数据写在 exe 旁边，配置在 %USERPROFILE%\.pluma' -ForegroundColor DarkGray
