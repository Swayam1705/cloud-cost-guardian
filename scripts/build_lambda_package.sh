#!/usr/bin/env bash
# Builds lambda_package.zip for the OPTIONAL Terraform deployment.
# boto3/botocore are provided by the Lambda runtime, so only pydantic + the app are vendored.
set -euo pipefail
cd "$(dirname "$0")/.."
BUILD="$(mktemp -d)"
trap 'rm -rf "$BUILD"' EXIT
python -m pip install --quiet --upgrade pip
# Pure-python wheels for pydantic-core exist per platform; target the Lambda arm64 runtime.
python -m pip install --quiet --target "$BUILD" \
  --platform manylinux2014_aarch64 --implementation cp --python-version 3.12 --only-binary=:all: \
  "pydantic>=2.5,<3" "pydantic-settings>=2.1,<3"
python -m pip install --quiet --target "$BUILD" --no-deps .
rm -f lambda_package.zip
( cd "$BUILD" && find . -name '__pycache__' -type d -prune -exec rm -rf {} + && zip -qr "$OLDPWD/lambda_package.zip" . )
echo "built lambda_package.zip ($(du -h lambda_package.zip | cut -f1))"
