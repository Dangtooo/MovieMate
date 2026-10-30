$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not (Test-Path -LiteralPath '.venv/Scripts/python.exe')) {
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Cannot create Python environment.' }
    & './.venv/Scripts/python.exe' -m pip install -r requirements.lock.txt
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
}
& './.venv/Scripts/python.exe' scripts/setup_env.py
if ($LASTEXITCODE -ne 0) { throw 'Environment setup failed.' }
& './.venv/Scripts/python.exe' -m backend.demo_catalog
if ($LASTEXITCODE -ne 0) { throw 'Database initialization failed.' }
Write-Host 'Cinephile: http://127.0.0.1:8000 | API docs: http://127.0.0.1:8000/docs'
& './.venv/Scripts/python.exe' -m uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000 --reload-dir backend --reload-dir frontend

