#!/usr/bin/env python3
"""Controlled primary-to-secondary failover for the Claude-only proxy gate."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from ccg_detect import controller_get, controller_select_proxy, load_state, walk_leaf

try:
    import fcntl
except ImportError:  # Windows
    fcntl = None

try:
    import msvcrt
except ImportError:  # POSIX
    msvcrt = None

GUARD = HERE / "ccg_guard.py"


def config(state: dict[str, Any]) -> dict[str, Any]:
    value = state.get("failover")
    return value if isinstance(value, dict) else {}


def validate_config(state: dict[str, Any]) -> str | None:
    cfg = config(state)
    if not cfg.get("enabled"):
        return "自动故障转移未启用。"
    primary = str(cfg.get("primary_node") or "").strip()
    secondary = str(cfg.get("secondary_node") or "").strip()
    if not primary or not secondary or primary == secondary:
        return "主备节点配置缺失或重复。"
    failure_threshold = cfg.get("failure_threshold", 3)
    probe_interval = cfg.get("probe_interval_seconds", 10)
    if (
        isinstance(failure_threshold, bool)
        or not isinstance(failure_threshold, int)
        or isinstance(probe_interval, bool)
        or not isinstance(probe_interval, int)
    ):
        return "主备探测参数无效。"
    if not 2 <= failure_threshold <= 5 or not 5 <= probe_interval <= 60:
        return "主备探测参数超出安全边界。"
    if cfg.get("switching") is True or str(cfg.get("active_role") or "") == "blocked":
        return "主备状态已处于切换或 blocked；拒绝重入，需先人工核验恢复。"
    if str(cfg.get("active_role") or "") != "primary" or str(state.get("expected_node") or "") != primary:
        return "当前唯一出口不是主节点；不会自动回切或连续轮换。"
    controller = state.get("controller")
    group = str(state.get("ai_group") or "").strip()
    if not isinstance(controller, dict) or not group:
        return "Clash 控制口或 CC 专用策略组不可用。"
    proxies = (controller_get(controller, "/proxies") or {}).get("proxies")
    if not isinstance(proxies, dict):
        return "读取 Clash 节点失败。"
    for node in (primary, secondary):
        details = proxies.get(node)
        kind = str(details.get("type") or "") if isinstance(details, dict) else ""
        if not kind or kind.lower() in {"direct", "reject", "reject-drop", "pass", "compatible"}:
            return "主节点或备用节点不存在，或不是可用的最终叶子。"
    group_details = proxies.get(group)
    if not isinstance(group_details, dict) or group_details.get("type") != "Selector":
        return "CC 专用策略组必须是 Selector，禁止让 Mihomo 自行轮换。"
    members = group_details.get("all")
    if (
        not isinstance(members, list)
        or len(members) != 2
        or set(members) != {primary, secondary}
    ):
        return "CC 专用策略组必须且只能直接选择配置的主、备两个叶子。"
    _chain, leaf = walk_leaf(proxies, group)
    if leaf != primary:
        return "CC 专用策略组当前真实叶子不是主节点；拒绝故障转移。"
    return None


def atomic_save_state(state: dict[str, Any]) -> None:
    path = HERE / "state.json"
    fd, tmp_name = tempfile.mkstemp(prefix="state.json.", dir=str(HERE))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(state, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp_name, 0o600)
        os.replace(tmp_name, path)
    finally:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass


def clear_probe_cache(state: dict[str, Any]) -> None:
    configured = state.get("probe_state")
    paths = [
        Path(str(configured)) if configured else Path(tempfile.gettempdir()) / "claude-network-guard.state",
    ]
    for path in paths:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            pass


def fresh_probe() -> tuple[bool, str]:
    try:
        result = subprocess.run(
            [sys.executable, str(GUARD), "--probe-switch"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return False, type(error).__name__
    lines = (result.stdout or "探测失败").strip().splitlines()
    return result.returncode == 0, (lines[0] if lines else "探测失败")


def acquire_transition_lock() -> int | None:
    path = HERE / "failover.lock"
    try:
        fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
        if os.fstat(fd).st_size == 0:
            os.write(fd, b"0")
        if fcntl is not None:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        elif msvcrt is not None:
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        else:
            os.close(fd)
            return None
        return fd
    except (OSError, BlockingIOError):
        try:
            os.close(fd)
        except (UnboundLocalError, OSError):
            pass
        return None


def release_transition_lock(fd: int) -> None:
    try:
        if fcntl is not None:
            fcntl.flock(fd, fcntl.LOCK_UN)
        elif msvcrt is not None:
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    finally:
        os.close(fd)


def _switch_to_secondary(now: int | None = None) -> tuple[bool, str]:
    state = load_state()
    error = validate_config(state)
    if error:
        return False, error
    cfg = config(state)
    now = int(time.time()) if now is None else int(now)
    cooldown = max(60, int(cfg.get("cooldown_seconds") or 1800))
    last_switch = int(cfg.get("last_switch_at") or 0)
    if last_switch and now - last_switch < cooldown:
        return False, "自动故障转移仍在冷却期，保持阻断。"

    primary = str(cfg["primary_node"])
    secondary = str(cfg["secondary_node"])
    group = str(state["ai_group"])
    controller = state["controller"]
    proxies = (controller_get(controller, "/proxies") or {}).get("proxies") or {}
    _chain, current_leaf = walk_leaf(proxies, group)

    # Persist the transition before touching Mihomo. Normal fast checks reject
    # while this marker exists; only the private probe mode may validate the
    # candidate route. A crash therefore leaves the gate closed.
    cfg["switching"] = True
    state["failover"] = cfg
    atomic_save_state(state)

    if not controller_select_proxy(controller, group, secondary):
        cfg["active_role"] = "blocked"
        cfg["switching"] = True
        cfg["transition_failed_at"] = now
        cfg["transition_failure_reason"] = "secondary_select_failed"
        state["failover"] = cfg
        atomic_save_state(state)
        return False, "切换 Clash 专用策略组失败，保持强制阻断。"

    selected_proxies = (controller_get(controller, "/proxies") or {}).get("proxies") or {}
    _selected_chain, selected_leaf = walk_leaf(selected_proxies, group)
    if selected_leaf != secondary:
        cfg["active_role"] = "blocked"
        cfg["switching"] = True
        cfg["transition_failed_at"] = now
        cfg["transition_failure_reason"] = "secondary_readback_mismatch"
        cfg["transition_observed_leaf"] = str(selected_leaf)[:200]
        state["failover"] = cfg
        atomic_save_state(state)
        return False, "备用节点选择后的真实叶子读回不符，保持强制阻断。"

    state["expected_node"] = secondary
    cfg["active_role"] = "secondary"
    cfg["last_switch_at"] = now
    cfg["last_switch_reason"] = "primary_probe_failed"
    state["failover"] = cfg
    clear_probe_cache(state)
    atomic_save_state(state)

    ok, reason = fresh_probe()
    if ok:
        cfg["switching"] = False
        state["failover"] = cfg
        atomic_save_state(state)
        return True, "主节点不可用，已安全切换到备用节点；备用现为唯一合法出口。"

    # A failed standby must not become an accepted route. Restore both selectors
    # while leaving the gate closed; this is rollback, not automatic failback.
    rollback_target = primary if primary in proxies else current_leaf
    rollback_selected = controller_select_proxy(controller, group, rollback_target)
    rollback_proxies = (controller_get(controller, "/proxies") or {}).get("proxies") or {}
    _rollback_chain, rollback_leaf = walk_leaf(rollback_proxies, group)
    state["expected_node"] = primary
    cfg["active_role"] = "primary"
    cfg["switching"] = True
    cfg["last_failed_secondary_at"] = now
    cfg["last_failed_secondary_reason"] = reason[:200]
    if not rollback_selected or rollback_leaf != primary:
        cfg["active_role"] = "blocked"
        cfg["switching"] = True
        cfg["rollback_failed_at"] = now
        cfg["rollback_observed_leaf"] = str(rollback_leaf)[:200]
        state["failover"] = cfg
        clear_probe_cache(state)
        atomic_save_state(state)
        return False, "备用节点验证失败且主节点回滚未确认，保持强制阻断。"

    state["failover"] = cfg
    clear_probe_cache(state)
    atomic_save_state(state)
    rollback_ok, rollback_reason = fresh_probe()
    if not rollback_ok:
        cfg["active_role"] = "blocked"
        cfg["switching"] = True
        cfg["rollback_failed_at"] = now
        cfg["rollback_probe_reason"] = rollback_reason[:200]
        state["failover"] = cfg
        clear_probe_cache(state)
        atomic_save_state(state)
        return False, "备用节点验证失败且主节点严格复验失败，保持强制阻断。"

    cfg["switching"] = False
    state["failover"] = cfg
    clear_probe_cache(state)
    atomic_save_state(state)
    return False, "备用节点验证失败；主节点已严格复验恢复，未执行切换。"


def switch_to_secondary(now: int | None = None) -> tuple[bool, str]:
    lock_fd = acquire_transition_lock()
    if lock_fd is None:
        return False, "已有故障转移正在执行，保持阻断。"
    try:
        return _switch_to_secondary(now=now)
    finally:
        release_transition_lock(lock_fd)


def status() -> int:
    state = load_state()
    cfg = config(state)
    enabled = bool(cfg.get("enabled"))
    active = str(cfg.get("active_role") or "unknown")
    print(f"enabled={str(enabled).lower()} active={active} threshold={cfg.get('failure_threshold', 3)}")
    return 0


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "--status"
    if mode == "--status":
        return status()
    if mode == "--switch-secondary":
        ok, message = switch_to_secondary()
        print(message, file=sys.stdout if ok else sys.stderr)
        return 0 if ok else 1
    print("usage: ccg_failover.py [--status|--switch-secondary]", file=sys.stderr)
    return 64


if __name__ == "__main__":
    raise SystemExit(main())
