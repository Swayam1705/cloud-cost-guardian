<#
.SYNOPSIS
  One-shot local setup for Cloud Cost Guardian on Windows (zero cost, no AWS needed).
.EXAMPLE
  PS> .\scripts\setup_local.ps1
  PS> .\scripts\setup_local.ps1 -Dev      # also installs test/lint tooling
#>
[CmdletBinding()]
param(
  [switch]$Dev
)
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

Write-Host "== Cloud Cost Guardian: local setup ==" -ForegroundColor Cyan

$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) { $python = Get-Command py -ErrorAction SilentlyContinue }
if (-not $python) { throw "Python 3.10+ not found. Install from https://www.python.org/downloads/ and re-run." }

$version = & $python.Source -c "import sys; print('%d.%d' % sys.version_info[:2])"
if ([version]$version -lt [version]"3.10") { throw "Python 3.10+ required, found $version" }
Write-Host "Python $version found at $($python.Source)"

if (-not (Test-Path ".venv")) {
  Write-Host "Creating virtual environment .venv ..."
  & $python.Source -m venv .venv
}
function Get-VenvPython {
  $win = Join-Path ".venv" "Scripts\python.exe"
  $nix = Join-Path ".venv" "bin/python"
  if (Test-Path $win) { return $win }
  if (Test-Path $nix) { return $nix }
  return $null
}
$venvPython = Get-VenvPython
if (-not $venvPython) { throw "virtual environment was created but its python executable was not found" }

Write-Host "Upgrading pip ..."
& $venvPython -m pip install --quiet --upgrade pip

$req = if ($Dev) { "requirements-dev.txt" } else { "requirements.txt" }
Write-Host "Installing $req ..."
& $venvPython -m pip install --quiet -r $req

if (-not (Test-Path ".env") -and (Test-Path ".env.example")) {
  Copy-Item ".env.example" ".env"
  Write-Host "Created .env from .env.example (edit as needed; it is git-ignored)."
}

Write-Host "Validating configuration ..."
& $venvPython -m cloud_cost_guardian.cli.main validate-config | Out-Null

Write-Host ""
Write-Host "Setup complete." -ForegroundColor Green
Write-Host "Activate the environment:   .venv\Scripts\Activate.ps1"
Write-Host "Run the demo:               python -m cloud_cost_guardian.cli.main scan --mode demo"
Write-Host "Preview cleanup:            python -m cloud_cost_guardian.cli.main cleanup --dry-run"
if ($Dev) { Write-Host "Run tests:                  pytest" }
Write-Host ""
Write-Host "If activation is blocked, run once:  Set-ExecutionPolicy -Scope CurrentUser RemoteSigned"
