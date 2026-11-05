#!/bin/zsh
set -eu
PYTHON="${CLAUDE_GUARD_PYTHON:-python3}"
exec "$PYTHON" "${0:A:h}/ccg_browser.py" "$@"
