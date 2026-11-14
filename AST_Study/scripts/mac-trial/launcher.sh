#!/bin/bash
set -euo pipefail
macos="$(cd "$(dirname "$0")" && pwd)"
contents="$(cd "$macos/.." && pwd)"
parent="$(cd "$contents/../../" && pwd)"
resources="$contents/Resources/workspace"
# Runtime code is always read from the application. Existing personal trial files remain untouched.
export SYNESIS_APP_ROOT="$resources"
export SYNESIS_LEGACY_ROOT="${SYNESIS_LEGACY_ROOT:-$parent/SYNESIS Data}"
export SYNESIS_DATA_DIR="${SYNESIS_DATA_DIR:-$parent/SYNESIS Data/User Data}"
export SYNESIS_CREDENTIALS_FILE="${SYNESIS_CREDENTIALS_FILE:-$parent/SYNESIS Data/.env}"
cd "$resources"
"$resources/.venv-pdf/bin/python3" -B "$resources/scripts/migrate_user_data.py" --legacy-root "$SYNESIS_LEGACY_ROOT" --destination "$SYNESIS_DATA_DIR" --apply
mkdir -p "$SYNESIS_DATA_DIR/.runtime/logs"
export PYTHONUTF8=1
export PYTHONDONTWRITEBYTECODE=1
exec "$macos/SYNESIS-runtime" "$@" >> "$SYNESIS_DATA_DIR/.runtime/logs/launcher.log" 2>&1
