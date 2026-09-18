#!/usr/bin/env bash
# One time setup for tools/transcribe.py. Everything here is free.
set -euo pipefail
cd "$(dirname "$0")/.."
. tools/_venv.sh

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

echo "python environment"
ci_venv_ready

ci_project_deps

echo "python packages"
"$PIP" install -q --upgrade pip
"$PIP" install -q yt-dlp faster-whisper

echo "checking"
"$PY" - <<'CHECK' || exit 1
import importlib.util as u, shutil, sys
missing = [n for n, m in (("yt-dlp", "yt_dlp"), ("faster-whisper", "faster_whisper"))
           if u.find_spec(m) is None]
if shutil.which("ffmpeg") is None:
    missing.append("ffmpeg")
if missing:
    print("  still missing: " + ", ".join(missing))
    sys.exit(1)
print("  yt-dlp, faster-whisper and ffmpeg are all in place")
if shutil.which("tesseract") is None:
    print("  tesseract is missing, so on screen text will be skipped")
CHECK

echo
echo "Done. Try one video:"
echo "  $PY tools/transcribe.py --top 1"
echo
echo "If it cannot reach TikTok, turn a VPN on. Indian ISPs block it."
