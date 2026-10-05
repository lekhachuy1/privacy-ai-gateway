$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path ".venv")) {
    python -m venv .venv
}

& .\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt

if (-not (Test-Path ".env")) {
    Copy-Item .env.example .env
}

Write-Host "Privacy AI Gateway v$((Get-Content VERSION -Raw).Trim())"
Write-Host "Mo trinh duyet tai http://127.0.0.1:8000"
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
