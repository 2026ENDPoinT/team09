$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
Push-Location $projectRoot
try {
    if (-not (Test-Path '.venv-pdf/Scripts/python.exe')) {
        python -m venv .venv-pdf
        if ($LASTEXITCODE -ne 0) { throw 'PDF Python environment creation failed.' }
    }
    & '.venv-pdf/Scripts/python.exe' -m pip install --no-cache-dir -r requirements-pdf.txt
    if ($LASTEXITCODE -ne 0) { throw 'PDF dependency installation failed.' }
    Write-Output 'PDF dependencies ready. Local OCR is disabled. Page visual reading is opt-in. No model/API call was made.'
} finally { Pop-Location }
