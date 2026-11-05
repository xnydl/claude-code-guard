#!/bin/zsh

# Launch official Claude Code inside the network sandbox.

set -u

readonly REAL_CLAUDE="${CLAUDE_REAL_BIN:-${HOME}/.local/bin/claude}"
readonly GUARD="${HOME}/.claude/hooks/network-killswitch.sh"
readonly CLAUDE_BROWSER="${HOME}/.local/claude-guard/bin/claude-fingerprint-chromium"
readonly GUARD_LOG="${HOME}/Library/Logs/Claude Code/network-guard.log"
readonly SANDBOX_EXEC="/usr/bin/sandbox-exec"
readonly SANDBOX_PROFILE="${HOME}/.local/claude-guard/claude-network.sb"
readonly GATE_HOST="127.0.0.1"
readonly GATE_PORT="7899"
readonly CONTROL_PORT="7900"

if [[ ! -x "$REAL_CLAUDE" ]]; then
  print -u2 -- "Claude 网络保护：找不到官方 Claude CLI：$REAL_CLAUDE"
  exit 127
fi
if [[ ! -x "$GUARD" ]]; then
  print -u2 -- "Claude 网络保护：保护脚本不存在或不可执行，已拒绝启动。"
  exit 78
fi
if [[ ! -x "$SANDBOX_EXEC" || ! -f "$SANDBOX_PROFILE" ]]; then
  print -u2 -- "Claude 网络保护：macOS 进程网络沙箱不可用，已拒绝启动。"
  exit 78
fi

preflight_ok="false"
preflight_output=""
for preflight_attempt in 1 2 3; do
  if preflight_output="$("$GUARD" --fast 2>&1)"; then
    preflight_ok="true"
    break
  fi
  if (( preflight_attempt < 3 )); then
    /bin/sleep 1
  fi
done
if [[ "$preflight_ok" != "true" ]]; then
  print -u2 -- "${preflight_output:-Claude 网络保护：启动前本地验证失败，已拒绝启动。}"
  exit 78
fi

if ! /usr/bin/nc -z -w 1 "$GATE_HOST" "$GATE_PORT" >/dev/null 2>&1; then
  print -u2 -- "Claude 网络保护：逐连接校验入口 localhost:7899 未运行，已拒绝启动。"
  exit 78
fi
if ! /usr/bin/nc -z -w 1 "$GATE_HOST" "$CONTROL_PORT" >/dev/null 2>&1; then
  print -u2 -- "Claude 网络保护：请求验证控制口 localhost:7900 未运行，已拒绝启动。"
  exit 78
fi

print -- "OK network-sandbox=on gate=localhost:7899 upstream=127.0.0.1:7898 request-egress-check=on"

export HTTP_PROXY="http://localhost:7899"
export HTTPS_PROXY="http://localhost:7899"
export ALL_PROXY="http://localhost:7899"
export http_proxy="$HTTP_PROXY"
export https_proxy="$HTTPS_PROXY"
export all_proxy="$ALL_PROXY"
export NO_PROXY="127.0.0.1,localhost,::1"
export no_proxy="$NO_PROXY"
export BROWSER="$CLAUDE_BROWSER"

"$SANDBOX_EXEC" -f "$SANDBOX_PROFILE" "$REAL_CLAUDE" "$@" &
claude_pid=$!

terminate_claude() {
  pkill -TERM -P "$claude_pid" >/dev/null 2>&1 || true
  kill -TERM "$claude_pid" >/dev/null 2>&1 || true
  sleep 1
  pkill -KILL -P "$claude_pid" >/dev/null 2>&1 || true
  kill -KILL "$claude_pid" >/dev/null 2>&1 || true
}

log_guard_event() {
  local action="$1"
  local reason="$2"
  printf '%s\taction=%s\treason=%s\n' \
    "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$action" "$reason" \
    >> "$GUARD_LOG" 2>/dev/null || true
}

collect_process_tree() {
  local parent_pid="$1"
  local child_pid=""
  for child_pid in $(/usr/bin/pgrep -P "$parent_pid" 2>/dev/null); do
    collect_process_tree "$child_pid"
  done
  print -r -- "$parent_pid"
}

suspend_claude_tree() {
  local process_pid=""
  local process_ids=("${(@f)$(collect_process_tree "$claude_pid")}")
  for process_pid in "${process_ids[@]}"; do
    kill -STOP "$process_pid" >/dev/null 2>&1 || true
  done
}

resume_claude_tree() {
  local process_pid=""
  local process_ids=("${(@f)$(collect_process_tree "$claude_pid")}")
  for process_pid in "${process_ids[@]}"; do
    kill -CONT "$process_pid" >/dev/null 2>&1 || true
  done
}

is_hard_failure() {
  local reason="$1"
  case "$reason" in
    *"TUN 当前未开启"*|*"不是 Rule 模式"*|*"IPv6 当前已开启"*|\
    *"mixed-port 不是"*|*"未绑定到"*|*"尚未选定"*)
      return 0
      ;;
  esac
  return 1
}

monitor_connection() {
  local failure_reason=""
  local retry_reason=""
  local recovered="false"
  local attempt=0

  while kill -0 "$claude_pid" >/dev/null 2>&1; do
    sleep 2
    if failure_reason="$("$GUARD" --fast 2>&1)"; then
      continue
    fi
    suspend_claude_tree
    if is_hard_failure "$failure_reason"; then
      log_guard_event "terminate-hard" "$failure_reason"
      print -u2 -- "Claude 网络保护触发：$failure_reason"
      terminate_claude
      return
    fi
    recovered="false"
    retry_reason="$failure_reason"
    for attempt in 1 2 3; do
      sleep 1
      if retry_reason="$("$GUARD" --fast 2>&1)"; then
        recovered="true"
        break
      fi
      if is_hard_failure "$retry_reason"; then
        break
      fi
    done
    if [[ "$recovered" == "true" ]]; then
      resume_claude_tree
      log_guard_event "resume-after-transient" "$failure_reason"
      continue
    fi
    log_guard_event "terminate-after-retry" "$retry_reason"
    print -u2 -- "Claude 网络保护触发：${retry_reason:-$failure_reason}"
    terminate_claude
    return
  done
}

monitor_connection &
monitor_pid=$!

cleanup_monitor() {
  kill "$monitor_pid" >/dev/null 2>&1 || true
  wait "$monitor_pid" >/dev/null 2>&1 || true
}

trap 'terminate_claude; cleanup_monitor; exit 130' INT TERM HUP
wait "$claude_pid"
claude_status=$?
cleanup_monitor
exit "$claude_status"
