<# End-to-end smoke test of the zero-cost demo lifecycle. Exits non-zero on any failure. #>
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
$py = if (Test-Path ".venv\Scripts\python.exe") { ".venv\Scripts\python.exe" }
      elseif (Test-Path ".venv/bin/python") { ".venv/bin/python" }
      else { "python" }
$tmpRoot = if ($env:TEMP) { $env:TEMP } else { [System.IO.Path]::GetTempPath() }
$smokeRoot = Join-Path $tmpRoot "ccg-smoke"
$env:CCG_ARTIFACTS_DIR = Join-Path $smokeRoot "artifacts"
$env:CCG_DATA_DIR      = Join-Path $smokeRoot "data"
$env:CCG_LOG_LEVEL     = "WARNING"
if (Test-Path $smokeRoot) { Remove-Item -Recurse -Force $smokeRoot }

function Run($desc, [string[]]$cmdArgs, [int]$expect = 0) {
  Write-Host "-> $desc"
  & $py -m cloud_cost_guardian.cli.main @cmdArgs | Out-Null
  if ($LASTEXITCODE -ne $expect) { throw "${desc}: expected exit $expect, got $LASTEXITCODE" }
}

Run "validate-config"                 @("validate-config")
Run "demo scan"                       @("scan", "--mode", "demo")
Run "report"                          @("report")
Run "cleanup dry-run"                 @("cleanup", "--dry-run")
Run "protected resource is blocked"   @("cleanup", "--resource", "vol-0a1b2c3d4e5f60005", "--approve") 3
Run "approved simulated remediation"  @("cleanup", "--resource", "vol-0a1b2c3d4e5f60001", "--approve")
Run "re-scan after remediation"       @("scan", "--mode", "demo", "--no-notify")
Run "demo reset"                      @("demo", "reset")

foreach ($f in @("reports/latest.json", "reports/latest.md", "notifications/latest-slack-message.json", "audit/latest-cleanup.json")) {
  if (-not (Test-Path (Join-Path $env:CCG_ARTIFACTS_DIR $f))) { throw "missing artifact $f" }
}
Write-Host "Smoke test passed." -ForegroundColor Green
