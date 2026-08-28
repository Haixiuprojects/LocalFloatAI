$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

if (-not (Test-Path .venv)) {
    py -3 -m venv .venv
}
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
New-Item -ItemType Directory -Force models | Out-Null
if (-not (Test-Path config.json)) { Copy-Item config.example.json config.json }

& .\.venv\Scripts\python.exe -m PyInstaller --clean --noconfirm build\LocalFloatAI.spec
New-Item -ItemType Directory -Force dist\LocalFloatAI\models | Out-Null
Copy-Item models\* dist\LocalFloatAI\models -Force -ErrorAction SilentlyContinue
Copy-Item config.example.json dist\LocalFloatAI\ -Force
Copy-Item README.md dist\LocalFloatAI\ -Force
Write-Host "Build complete: dist\LocalFloatAI\LocalFloatAI.exe"
