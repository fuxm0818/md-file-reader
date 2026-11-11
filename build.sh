#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
PYINSTALLER="$ROOT/.venv/bin/pyinstaller"

if [ ! -x "$PYINSTALLER" ]; then
  echo "缺少 .venv，请先运行： python3 -m venv .venv && .venv/bin/pip install -r requirements.txt" >&2
  exit 1
fi

export PYINSTALLER_CONFIG_DIR="$ROOT/.pyinstaller-config"
mkdir -p "$PYINSTALLER_CONFIG_DIR"

cd "$ROOT"

# Move (never bulk-delete) previous outputs so PyInstaller can rebuild cleanly.
STAMP="$(date +%s)"
for target in "$ROOT/dist/文档朗读器" "$ROOT/dist/文档朗读器.app"; do
  if [ -e "$target" ]; then
    mv "$target" "/tmp/docreader-prev-${STAMP}-$(basename "$target")"
  fi
done

"$PYINSTALLER" --noconfirm --onedir --windowed \
  --name "文档朗读器" \
  --paths "$ROOT" \
  --distpath "$ROOT/dist" \
  --workpath "$ROOT/build" \
  --specpath "$ROOT" \
  --osx-bundle-identifier "com.localtools.docreader" \
  --hidden-import PySide6.QtMultimedia \
  --hidden-import pymupdf \
  --hidden-import docx \
  "$ROOT/src/main.py"

APP="$ROOT/dist/文档朗读器.app"
if [ -d "$APP" ]; then
  /usr/bin/codesign --force --deep --sign - "$APP" >/dev/null 2>&1 || true
  echo "已生成：$APP"
else
  echo "未找到 .app，请检查上方打包日志" >&2
  exit 1
fi
