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

# v1.4 起只用系统语音 + 音频打磨，不再打包 TTS 模型，包体积从 541 MB
# 回落到约 190 MB。numpy 是打磨后级的依赖，PyInstaller 会自动带上。
#
# 图标由 scripts/make_icon.py 生成（QPainter 绘制，非位图素材）。缺了就
# 先现生成一份，免得打出来的包顶着 PyInstaller 的默认图标。
if [ ! -f "$ROOT/assets/AppIcon.icns" ]; then
  echo "生成应用图标…"
  "$ROOT/.venv/bin/python" "$ROOT/scripts/make_icon.py"
fi

"$PYINSTALLER" --noconfirm --onedir --windowed \
  --name "文档朗读器" \
  --icon "$ROOT/assets/AppIcon.icns" \
  --add-data "$ROOT/assets/AppIcon.png:assets" \
  --paths "$ROOT" \
  --distpath "$ROOT/dist" \
  --workpath "$ROOT/build" \
  --specpath "$ROOT" \
  --osx-bundle-identifier "com.localtools.docreader" \
  --hidden-import PySide6.QtMultimedia \
  --hidden-import pymupdf \
  --hidden-import docx \
  --hidden-import src.core.oralizer \
  --hidden-import src.core.prosody \
  --hidden-import src.core.loudness \
  "$ROOT/src/main.py"

APP="$ROOT/dist/文档朗读器.app"
if [ -d "$APP" ]; then
  # PyInstaller 不会从代码里取版本，默认写 CFBundleShortVersionString=0.0.0，
  # 这样打出来的包在「关于」和系统面板里都没有版本可言。版本号只在
  # src/version.py 维护一份，这里读出来写进 Info.plist 再签名。
  VERSION="$("$ROOT/.venv/bin/python" - "$ROOT" <<'PY'
import sys
sys.path.insert(0, sys.argv[1])
from src.version import __version__

print(__version__)
PY
)"
  PLIST="$APP/Contents/Info.plist"
  set_plist() {  # key type value —— 已存在就改，不存在就加
    /usr/libexec/PlistBuddy -c "Set :$1 $3" "$PLIST" 2>/dev/null \
      || /usr/libexec/PlistBuddy -c "Add :$1 $2 $3" "$PLIST"
  }
  set_plist CFBundleShortVersionString string "$VERSION"
  set_plist CFBundleVersion string "$VERSION"
  # README 承诺 macOS 13+，写进 plist 让系统在更老的机器上直接拒绝安装，
  # 而不是等到调用 say 才出现难解释的失败。
  set_plist LSMinimumSystemVersion string "13.0"
  set_plist NSHumanReadableCopyright string "MIT License"
  echo "版本：$VERSION"

  # 改过 Info.plist 会让原签名失效，重新做一次临时签名。
  /usr/bin/codesign --force --deep --sign - "$APP" >/dev/null 2>&1 || true
  echo "已生成：$APP"
  /usr/bin/du -sh "$APP" 2>/dev/null || true
else
  echo "未找到 .app，请检查上方打包日志" >&2
  exit 1
fi
