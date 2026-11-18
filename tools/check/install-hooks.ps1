# 2026-11-19：新克隆 / 换机器后，把提交钩子接上（core.hooksPath 不会被 clone 带过来）
$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $repo
git config core.hooksPath .githooks
if ($LASTEXITCODE -ne 0) { Write-Host "设置失败：不是 git 仓库？" -ForegroundColor Red; exit 1 }
Write-Host ("已接上提交钩子：" + (git config --get core.hooksPath)) -ForegroundColor Green
Write-Host "提交前会自动跑 check-stub-guard.py 与 check-ui-preview.py"
