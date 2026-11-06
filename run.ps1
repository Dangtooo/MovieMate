$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not (Test-Path -LiteralPath '.venv/Scripts/python.exe')) {
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Cannot create Python environment.' }
}
# Refresh existing environments when the dependency lock changes, too.
$requirementsHash = (Get-FileHash -LiteralPath 'requirements.lock.txt' -Algorithm SHA256).Hash
$requirementsStamp = '.venv/requirements.sha256'
$installedRequirementsHash = if (Test-Path -LiteralPath $requirementsStamp) {
    (Get-Content -LiteralPath $requirementsStamp -Raw).Trim()
} else {
    ''
}
if ($installedRequirementsHash -ne $requirementsHash) {
    Write-Host 'Installing/updating MovieMate dependencies...'
    & './.venv/Scripts/python.exe' -m pip install -r requirements.lock.txt
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
    & './.venv/Scripts/python.exe' -m pip check
    if ($LASTEXITCODE -ne 0) { throw 'Dependency compatibility check failed.' }
    Set-Content -LiteralPath $requirementsStamp -Value $requirementsHash -Encoding ASCII
}
& './.venv/Scripts/python.exe' scripts/setup_env.py
if ($LASTEXITCODE -ne 0) { throw 'Environment setup failed.' }
& './.venv/Scripts/python.exe' -m backend.demo_catalog
if ($LASTEXITCODE -ne 0) { throw 'Database initialization failed.' }
Write-Host 'MovieMate: http://127.0.0.1:8000 | API docs: http://127.0.0.1:8000/docs'
& './.venv/Scripts/python.exe' -m uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000 --reload-dir backend --reload-dir frontend

