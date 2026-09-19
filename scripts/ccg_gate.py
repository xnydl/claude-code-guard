#!/usr/bin/env python3
"""Local HTTP proxy gate. Ports come from detect/install state, not hardcoded vendors."""

from __future__ import annotations

import logging
import select
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Optional, Tuple

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from ccg_detect import load_state

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

stop_event = threading.Event()
safe_event = threading.Event()
validation_lock = threading.Lock()
full_validation_lock = threading.Lock()
active_lock = threading.Lock()
active_pairs: set[Tuple[socket.socket, socket.socket]] = set()
listener: Optional[socket.socket] = None
control_listener: Optional[socket.socket] = None
GUARD = HERE / "ccg_guard.py"
FAILOVER = HERE / "ccg_failover.py"

# These failures mean that the verifier could not obtain fresh evidence.  They
# are different from affirmative unsafe evidence such as a selector mismatch,
# a wrong region, disabled TUN, enabled IPv6, or an inconsistent failover role.
TRANSIENT_FAILURE_MARKERS = (
    "Clash 控制口暂时无法读取",
    "Anthropic 接口探测失败",
    "出口探测没有返回明确的目标地区",
    "出口探测超时且没有近期选定地区缓存",
)


def run_guard(mode: str, timeout: float) -> Tuple[bool, str]:
    try:
        result = subprocess.run(
            [sys.executable, str(GUARD), mode],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return False, type(error).__name__
    reason = (result.stdout or "guard rejected connection").strip().splitlines()
    return result.returncode == 0, (reason[0] if reason else "guard rejected connection")


def is_transient_failure(reason: str) -> bool:
    """Return True only for bounded availability failures, never policy failures."""
    return reason == "TimeoutExpired" or any(marker in reason for marker in TRANSIENT_FAILURE_MARKERS)


def may_retain_validated_route(
    reason: str,
    failures: int,
    threshold: int,
    route_probe_safe: bool,
) -> bool:
    """Allow a short retry only while a previously validated route is still active."""
    return (
        safe_event.is_set()
        and route_probe_safe
        and failures < threshold
        and is_transient_failure(reason)
    )


def close_socket(sock: socket.socket) -> None:
    try:
        sock.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass
    try:
        sock.close()
    except OSError:
        pass


def close_all_active() -> None:
    with active_lock:
        pairs = list(active_pairs)
    for client, upstream in pairs:
        close_socket(client)
        close_socket(upstream)


def failover_config() -> dict:
    state = load_state()
    value = state.get("failover")
    return value if isinstance(value, dict) else {}


def run_failover() -> Tuple[bool, str]:
    try:
        result = subprocess.run(
            [sys.executable, str(FAILOVER), "--switch-secondary"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=75,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return False, type(error).__name__
    reason = (result.stdout or "自动故障转移失败").strip().splitlines()
    return result.returncode == 0, (reason[0] if reason else "自动故障转移失败")


def safety_monitor() -> None:
    last_safe: Optional[bool] = None
    probe_failures = 0
    fast_failures = 0
    last_probe_at = 0.0
    route_probe_safe = False
    while not stop_event.wait(1.0):
        try:
            fast_ok, reason = run_guard("--fast", 6)
            cfg = failover_config()
            failover_enabled = bool(cfg.get("enabled"))
            threshold = cfg.get("failure_threshold", 3)
            interval = cfg.get("probe_interval_seconds", 10)
            if (
                isinstance(threshold, bool)
                or not isinstance(threshold, int)
                or isinstance(interval, bool)
                or not isinstance(interval, int)
            ):
                raise ValueError("failover probe parameters must be integers")
            if not 2 <= threshold <= 5 or not 5 <= interval <= 60:
                raise ValueError("failover probe parameters outside safe bounds")
            if fast_ok:
                fast_failures = 0
            else:
                fast_failures += 1
            retain_after_fast_timeout = failover_enabled and may_retain_validated_route(
                reason,
                fast_failures,
                threshold,
                route_probe_safe,
            )
            combined_ok = (fast_ok or retain_after_fast_timeout) and (
                route_probe_safe or not failover_enabled
            )
            if combined_ok:
                safe_event.set()
                if last_safe is False:
                    logging.info("network guard recovered")
                if retain_after_fast_timeout:
                    logging.warning(
                        "transient fast check failure (%s/%s); retaining last validated route pending retry: %s",
                        fast_failures,
                        threshold,
                        reason,
                    )
            else:
                safe_event.clear()
                close_all_active()
                if last_safe is not False:
                    logging.warning("network guard closed all tunnels: %s", reason)
            last_safe = combined_ok

            if not failover_enabled:
                probe_failures = 0
                continue
            now = time.monotonic()
            if now - last_probe_at < interval:
                continue
            last_probe_at = now
            probe_ok, probe_reason = run_guard("--probe", 30)
            if probe_ok:
                probe_failures = 0
                fast_failures = 0
                route_probe_safe = True
                if fast_ok or retain_after_fast_timeout:
                    safe_event.set()
                    if last_safe is False:
                        logging.info("network guard recovered after full route probe")
                    last_safe = True
                continue
            probe_failures += 1
            role = str(cfg.get("active_role") or "primary")
            logging.warning(
                "%s probe failed (%s/%s): %s",
                role,
                probe_failures,
                threshold,
                probe_reason,
            )
            if may_retain_validated_route(
                probe_reason,
                probe_failures,
                threshold,
                route_probe_safe,
            ):
                logging.warning("retaining last validated route pending bounded probe retry")
                continue

            route_probe_safe = False
            safe_event.clear()
            close_all_active()
            last_safe = False
            if role != "primary":
                continue
            if probe_failures < threshold:
                continue
            switched, switch_reason = run_failover()
            logging.warning("automatic failover result: %s", switch_reason)
            probe_failures = 0
            if switched:
                route_probe_safe = True
                fast_ok, reason = run_guard("--fast", 6)
                if fast_ok:
                    safe_event.set()
                    last_safe = True
        except Exception:
            # A safety monitor must never die while leaving an old authorization
            # bit set. Malformed state or an unexpected verifier error closes
            # managed tunnels, then the daemon keeps retrying from a closed state.
            route_probe_safe = False
            probe_failures = 0
            fast_failures = 0
            safe_event.clear()
            close_all_active()
            last_safe = False
            logging.exception("network guard monitor failed closed; retrying")


def relay(client: socket.socket, upstream_addr: Tuple[str, int]) -> None:
    upstream: Optional[socket.socket] = None
    pair = None
    try:
        with validation_lock:
            ok, reason = run_guard("--fast", 6)
        if not ok or not safe_event.is_set():
            logging.warning("connection denied by guard: %s", reason)
            return
        upstream = socket.create_connection(upstream_addr, timeout=3.0)
        client.setblocking(True)
        upstream.setblocking(True)
        pair = (client, upstream)
        with active_lock:
            active_pairs.add(pair)
        while not stop_event.is_set() and safe_event.is_set():
            try:
                readable, _, exceptional = select.select([client, upstream], [], [client, upstream], 1.0)
            except OSError:
                # The safety monitor deliberately closes both sockets when a
                # route becomes unsafe; the relay should exit quietly.
                break
            if exceptional:
                break
            for source in readable:
                try:
                    chunk = source.recv(65536)
                except OSError:
                    chunk = b""
                if not chunk:
                    return
                destination = upstream if source is client else client
                try:
                    destination.sendall(chunk)
                except OSError:
                    return
    finally:
        if pair is not None:
            with active_lock:
                active_pairs.discard(pair)
        close_socket(client)
        if upstream is not None:
            close_socket(upstream)


def handle_control(client: socket.socket) -> None:
    try:
        client.settimeout(34)
        if client.recv(64).strip() != b"CHECK":
            client.sendall(b"BLOCK\tinvalid control request\n")
            return
        if not safe_event.is_set():
            client.sendall(b"BLOCK\tgate has no fresh validated-safe route\n")
            return
        with full_validation_lock:
            ok, reason = run_guard("--check", 32)
        if ok and safe_event.is_set():
            client.sendall(b"OK\n")
        else:
            detail = reason if not ok else "gate route became unsafe during validation"
            client.sendall(("BLOCK\t" + detail.replace("\t", " ").replace("\n", " ")[:500] + "\n").encode("utf-8"))
    except (OSError, UnicodeError):
        pass
    finally:
        close_socket(client)


def serve(bind: Tuple[str, int], handler) -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(bind)
    sock.listen(64)
    sock.settimeout(1.0)
    return sock


def main() -> int:
    global listener, control_listener
    state = load_state()
    if not state:
        print("gate: missing ~/.claude-guard/state.json — run detect then install", file=sys.stderr)
        return 78
    gate_port = int(state["gate_port"])
    control_port = int(state["control_port"])
    upstream_port = int(state.get("upstream_port") or state.get("bind_port"))
    upstream_addr = ("127.0.0.1", upstream_port)

    signal.signal(signal.SIGTERM, lambda *_: stop_event.set())
    signal.signal(signal.SIGINT, lambda *_: stop_event.set())

    ok, reason = run_guard("--fast", 6)
    cfg = state.get("failover") if isinstance(state.get("failover"), dict) else {}
    if ok and not cfg.get("enabled"):
        safe_event.set()
    elif ok:
        logging.info("gate starts closed pending a fresh route probe")
    else:
        logging.warning("gate starts closed: %s", reason)

    threading.Thread(target=safety_monitor, daemon=True).start()
    control_listener = serve(("127.0.0.1", control_port), None)
    listener = serve(("127.0.0.1", gate_port), None)
    logging.info("gate %s -> %s control %s", gate_port, upstream_addr, control_port)

    def accept_loop(server: socket.socket, target) -> None:
        while not stop_event.is_set():
            try:
                client, _ = server.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            threading.Thread(target=target, args=(client,), daemon=True).start()

    threading.Thread(target=accept_loop, args=(control_listener, handle_control), daemon=True).start()
    while not stop_event.is_set():
        try:
            client, _ = listener.accept()
        except socket.timeout:
            continue
        except OSError:
            break
        threading.Thread(target=relay, args=(client, upstream_addr), daemon=True).start()

    close_all_active()
    if listener:
        close_socket(listener)
    if control_listener:
        close_socket(control_listener)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
