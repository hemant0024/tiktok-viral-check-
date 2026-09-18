#!/usr/bin/env bash
# One time setup for tools/transcribe.py. Everything here is free.
set -euo pipefail
cd "$(dirname "$0")/.."

# macOS refuses to compile anything until the Xcode licence is accepted, and the
# failure lands in the middle of a brew install where it reads like a broken
# formula rather than a one line fix.
if [ "$(uname)" = "Darwin" ] && /usr/bin/xcrun --version 2>&1 | grep -qi "license"; then
  echo
  echo "macOS needs the Xcode licence accepted before anything will build."
  echo "Run this, then start this script again:"
  echo
  echo "  sudo xcodebuild -license accept"
  echo
  exit 1
fi

echo "ffmpeg and tesseract"
if command -v brew >/dev/null; then
  brew list ffmpeg    >/dev/null 2>&1 || brew install ffmpeg
  brew list tesseract >/dev/null 2>&1 || brew install tesseract
else
  echo "  no homebrew. Install ffmpeg and tesseract yourself, then run this again."
fi

VENV=".venv"
[ -d "$VENV" ] || python3 -m venv "$VENV"
echo "python packages"
"$VENV/bin/pip" install -q --upgrade pip
"$VENV/bin/pip" install -q yt-dlp faster-whisper

echo
echo "Done. Try one video:"
echo "  .venv/bin/python tools/transcribe.py --top 1"
echo
echo "If it cannot reach TikTok, turn a VPN on. Indian ISPs block it."
