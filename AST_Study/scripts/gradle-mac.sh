#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

if [[ -x .tools/jdk21/Contents/Home/bin/java ]]; then
  export JAVA_HOME="$PWD/.tools/jdk21/Contents/Home"
elif /usr/libexec/java_home -v 21 >/dev/null 2>&1; then
  export JAVA_HOME
  JAVA_HOME="$(/usr/libexec/java_home -v 21)"
fi

export GRADLE_USER_HOME="${GRADLE_USER_HOME:-$PWD/.gradle-user}"
exec bash ./gradlew "$@"
