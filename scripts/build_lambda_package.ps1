<# Builds lambda_package.zip for the OPTIONAL Terraform deployment (Windows). #>
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
$build = Join-Path ([System.IO.Path]::GetTempPath()) ("ccg-lambda-" + [guid]::NewGuid())
New-Item -ItemType Directory -Path $build | Out-Null
try {
  python -m pip install --quiet --upgrade pip
  python -m pip install --quiet --target $build --platform manylinux2014_aarch64 --implementation cp --python-version 3.12 --only-binary=:all: "pydantic>=2.5,<3" "pydantic-settings>=2.1,<3"
  python -m pip install --quiet --target $build --no-deps .
  Get-ChildItem -Path $build -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force
  if (Test-Path "lambda_package.zip") { Remove-Item "lambda_package.zip" }
  Compress-Archive -Path (Join-Path $build "*") -DestinationPath "lambda_package.zip"
  Write-Host "built lambda_package.zip"
} finally {
  Remove-Item -Recurse -Force $build
}
