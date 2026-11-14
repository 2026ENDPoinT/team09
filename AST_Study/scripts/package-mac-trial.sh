#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
project="$PWD"
jdk="$project/.tools/jdk21/Contents/Home"
stamp="$(date +%Y%m%d-%H%M%S)"
staging="$project/build/mac-trial-$stamp"
mkdir -p "$staging/input" "$staging/preferences" "$staging/icon.iconset"
bash scripts/gradle-mac.sh installDist --offline --no-daemon
cp build/install/synesis-audio-poc/lib/*.jar "$staging/input/"
"$jdk/bin/javac" --release 21 -d "$staging/preferences" scripts/mac-trial/TrialPreferencesFactory.java
"$jdk/bin/jar" --create --file "$staging/input/trial-preferences.jar" -C "$staging/preferences" .
logo="src/main/resources/dev/synesis/poc/synesis-logo.png"
for size in 16 32 128 256 512; do
  /usr/bin/sips -z "$size" "$size" "$logo" --out "$staging/icon.iconset/icon_${size}x${size}.png" >/dev/null
  double=$((size*2))
  /usr/bin/sips -z "$double" "$double" "$logo" --out "$staging/icon.iconset/icon_${size}x${size}@2x.png" >/dev/null
done
/usr/bin/iconutil -c icns "$staging/icon.iconset" -o "$staging/SYNESIS.icns"
"$jdk/bin/jpackage" --type app-image --dest "$staging/output" --name SYNESIS \
  --input "$staging/input" --main-jar synesis-audio-poc.jar --main-class dev.synesis.poc.Main \
  --app-version 1.0.0 --vendor SYNESIS --mac-package-identifier dev.synesis.trial \
  --icon "$staging/SYNESIS.icns" \
  --java-options '--add-exports=java.desktop/com.apple.eawt=ALL-UNNAMED' \
  --java-options '-Dstdout.encoding=UTF-8' --java-options '-Dstderr.encoding=UTF-8'
app="$staging/output/SYNESIS.app"
resources="$app/Contents/Resources/workspace"
mkdir -p "$resources"
/usr/bin/ditto scripts "$resources/scripts"
# Archived assistant experiments must never ship, even if copied back into scripts.
experimental_assistant_scripts=(
  assistant_capabilities.py assistant_engine.py assistant_protocol_eager.py
  benchmark_assistant_engines.py test_assistant_capabilities.py
  test_assistant_engine.py test_benchmark_assistant_engines.py
)
for name in "${experimental_assistant_scripts[@]}"; do
  /usr/bin/find "$resources/scripts" -name "$name" ! -type d -delete
done
# Remove bytecode only from the staged copy, never from the project scripts.
/usr/bin/find "$resources/scripts" -name __pycache__ -prune -exec /bin/rm -rf {} +
/usr/bin/find "$resources/scripts" ! -type d \( -name '*.pyc' -o -name '*.pyo' \) -delete
/usr/bin/ditto .venv-pdf "$resources/.venv-pdf"
python_base="$(.venv-pdf/bin/python3 -c 'import sys;print(sys.base_prefix)')"
/usr/bin/ditto "$python_base" "$resources/python-runtime"
ln -sf ../../python-runtime/bin/python3 "$resources/.venv-pdf/bin/python3"
printf 'include-system-site-packages = false\nversion = 3.13.16\n' > "$resources/.venv-pdf/pyvenv.cfg"
mv "$app/Contents/MacOS/SYNESIS" "$app/Contents/MacOS/SYNESIS-runtime"
cp "$app/Contents/app/SYNESIS.cfg" "$app/Contents/app/SYNESIS-runtime.cfg"
cp scripts/mac-trial/launcher.sh "$app/Contents/MacOS/SYNESIS-launcher.sh"
/usr/bin/clang -O2 -Wall -Wextra scripts/mac-trial/launcher.c -o "$app/Contents/MacOS/SYNESIS"
chmod +x "$app/Contents/MacOS/SYNESIS"
# Ad-hoc signature for this local trial, including the renamed native launcher.
/usr/bin/codesign --force --deep --sign - "$app" >/dev/null 2>&1
printf '%s\n' "$staging/output"
