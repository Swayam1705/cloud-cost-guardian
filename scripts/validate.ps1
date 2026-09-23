<# Runs the full local quality gate: lint, format, types, tests, dependency audit. #>
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
$py = if (Test-Path ".venv\Scripts\python.exe") { ".venv\Scripts\python.exe" }
      elseif (Test-Path ".venv/bin/python") { ".venv/bin/python" }
      else { "python" }

function Step($name, $block) {
  Write-Host "`n== $name ==" -ForegroundColor Cyan
  & $block
  if ($LASTEXITCODE -ne 0) { throw "$name FAILED" }
}

Step "ruff check"        { & $py -m ruff check . }
Step "ruff format check" { & $py -m ruff format --check . }
Step "mypy"              { & $py -m mypy }
Step "pytest"            { & $py -m pytest -q }
Step "pip-audit"         { & $py -m pip_audit --skip-editable }
Write-Host "`nAll checks passed." -ForegroundColor Green
