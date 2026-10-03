$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Backend = Join-Path $Root "backend"
$FrontendDist = Join-Path $Root "frontend\dist"

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    throw "未找到 Python。请安装 Python 3.12+ 并确保 python 在 PATH 中。"
}
if (-not (Test-Path $FrontendDist)) {
    throw "未找到 frontend\dist。请先执行：cd frontend; npm install; npm run build"
}

Push-Location $Backend
try {
    python run.py
} finally {
    Pop-Location
}
