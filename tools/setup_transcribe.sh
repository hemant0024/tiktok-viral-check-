#!/usr/bin/env bash
# One time setup for tools/transcribe.py. Everything here is free.
set -euo pipefail
cd "$(dirname "$0")/.."

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
