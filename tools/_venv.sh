# Shared venv bootstrap. Sourced by dashboard.sh and tools/setup_transcribe.sh.
#
# The repo folder is shared between this Mac and the Cowork Linux sandbox, so a
# single .venv cannot serve both: a venv built in the sandbox has bin/python
# symlinked to /usr/bin/python3.10, which does not exist on macOS, and every
# command fails with "no such file or directory". The directory name carries the
# platform so the two never collide.
#
# It also repairs two things that bite in practice: a venv left half built, and
# a uv-made venv that ships without pip.

ci_venv_path() {
  echo ".venv-$(uname -s)-$(uname -m)"
}

ci_venv_ready() {
  VENV="$(ci_venv_path)"

  if [ -x "$VENV/bin/python" ] && "$VENV/bin/python" -c "import sys" >/dev/null 2>&1; then
    :
  else
    [ -e "$VENV" ] && echo "  $VENV is broken, rebuilding it"
    rm -rf "$VENV"
    echo "  building $VENV"
    python3 -m venv "$VENV" || {
      echo "python3 -m venv failed. Is python3 installed? Try: brew install python"
      exit 1
    }
  fi

  # uv builds venvs without pip. Put it back rather than failing later.
  if [ ! -x "$VENV/bin/pip" ]; then
    "$VENV/bin/python" -m ensurepip --upgrade >/dev/null 2>&1 || true
  fi
  if [ ! -x "$VENV/bin/pip" ]; then
    echo "pip is missing from $VENV and ensurepip could not add it."
    exit 1
  fi

  PY="$VENV/bin/python"
  PIP="$VENV/bin/pip"
  export VENV PY PIP
}

ci_project_deps() {
  if ! "$PY" -c "import yaml, pydantic" >/dev/null 2>&1; then
    echo "  installing the project's dependencies (first run only)"
    "$PIP" install -q --upgrade pip
    "$PIP" install -q -e . 2>/dev/null || "$PIP" install -q -r requirements.txt
  fi
}
