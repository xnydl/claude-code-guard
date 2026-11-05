#!/bin/zsh
set -u
GUARD_DIR="${HOME}/.claude-guard"
PYTHON="${CLAUDE_GUARD_PYTHON:-python3}"
REAL="${CLAUDE_REAL_BIN:-${HOME}/.local/bin/claude}"
if ! "$PYTHON" "${GUARD_DIR}/ccg_guard.py" --fast; then
  print -u2 -- "Claude 网络保护：启动前验证失败。"
  exit 78
fi
GATE="$("$PYTHON" -c 'from pathlib import Path; import json; p=Path.home()/".claude-guard"/"state.json"; print(json.loads(p.read_text())["gate_port"])')"
export HTTP_PROXY="http://localhost:${GATE}" HTTPS_PROXY="http://localhost:${GATE}" ALL_PROXY="http://localhost:${GATE}"
export http_proxy="$HTTP_PROXY" https_proxy="$HTTPS_PROXY" all_proxy="$ALL_PROXY"
export NO_PROXY="127.0.0.1,localhost,::1" no_proxy="$NO_PROXY"
export BROWSER="${GUARD_DIR}/fingerprint-chromium.sh"
SB="${GUARD_DIR}/claude-network.sb"
if [[ -x /usr/bin/sandbox-exec && -f "$SB" ]]; then
  exec /usr/bin/sandbox-exec -f "$SB" "$REAL" "$@"
fi
exec "$REAL" "$@"
