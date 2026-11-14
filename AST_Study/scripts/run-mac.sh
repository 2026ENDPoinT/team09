#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

if [[ ! -f .venv-pdf/bin/python3 ]]; then
  echo "Run bash scripts/setup-mac.sh first." >&2
  exit 1
fi

bash scripts/gradle-mac.sh run "$@"
