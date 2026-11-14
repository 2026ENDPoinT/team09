#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This setup script is for macOS." >&2
  exit 1
fi

python_bin="${SYNESIS_PYTHON:-python3}"
if ! command -v "$python_bin" >/dev/null 2>&1; then
  echo "Python 3 is required. Set SYNESIS_PYTHON to its executable path." >&2
  exit 1
fi

"$python_bin" -m venv .venv-pdf

.venv-pdf/bin/python3 -m pip install --upgrade pip
.venv-pdf/bin/python3 -m pip install -r requirements-pdf.txt

echo "The PDF Python environment is ready."
