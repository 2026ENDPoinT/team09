#!/bin/sh
set -eu
cd "$(dirname "$0")"

node -e 'const [major, minor] = process.versions.node.split(".").map(Number); if (major < 22 || major === 22 && minor < 12) process.exit(1);' || {
    printf '%s\n' 'Node.js 22.12 이상을 설치해 주세요.' >&2
    exit 1
}
if ! command -v python3.12 >/dev/null 2>&1; then
    printf '%s\n' 'Python 3.12를 설치해 주세요.' >&2
    exit 1
fi
if [ -z "${JAVA_HOME:-}" ]; then
    JAVA_HOME=$(/usr/libexec/java_home -F -v 21 2>/dev/null) || {
        printf '%s\n' 'JDK 21을 설치하거나 JAVA_HOME을 지정해 주세요.' >&2
        exit 1
    }
fi
export JAVA_HOME
if ! "$JAVA_HOME/bin/java" -XshowSettings:properties -version 2>&1 | grep -Eq 'java\.specification\.version = 21$'; then
    printf '%s\n' 'JAVA_HOME을 JDK 21 경로로 지정해 주세요.' >&2
    exit 1
fi

if [ ! -x node_modules/.bin/electron ]; then
    npm ci --no-audit --no-fund
fi
if [ ! -x .venv/bin/python ]; then
    python3.12 -m venv .venv
fi
if ! .venv/bin/python -c 'import seoultech_lms.mcp_server' 2>/dev/null; then
    .venv/bin/python -m pip install -e .
fi
if [ ! -d '/Applications/Google Chrome.app' ] &&
   [ ! -d "$HOME/Applications/Google Chrome.app" ]; then
    PLAYWRIGHT_BROWSERS_PATH="$PWD/.playwright-browsers" .venv/bin/python -m playwright install --no-shell chromium
fi
(
    cd AST_Study
    if [ ! -x .venv-pdf/bin/python ]; then
        python3.12 -m venv .venv-pdf
    fi
    if ! .venv-pdf/bin/python -c 'import markitdown, pypdf, pypdfium2, pdfplumber, PIL, dotenv, urllib3' 2>/dev/null; then
        .venv-pdf/bin/python -m pip install -r requirements-pdf.txt
    fi
    ./gradlew installDist
)

exec npm start -- "$@"
