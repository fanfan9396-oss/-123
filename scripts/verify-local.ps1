$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    throw "未找到 Python。请安装 Python 3.12+。"
}
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    throw "未找到 npm。请安装 Node.js 20+。"
}

Push-Location (Join-Path $Root "backend")
try {
    python -B -m unittest discover -s tests
    python -B -m compileall app tests
} finally {
    Pop-Location
}

Push-Location (Join-Path $Root "frontend")
try {
    npm run check
    npm run build
} finally {
    Pop-Location
}

Write-Output "本地验证通过。"
