#!/usr/bin/python3

"""TCP gate for the Claude Code process tree.

Claude/Anthropic HTTP_PROXY bytes go to the pinned inbound :7898 after a
guard check. Optional CCG_RULES_HOST_SUFFIXES (comma-separated) send matching
CONNECT hosts to the rules inbound :7897. The payload is never logged.

Shell/DB clients that ignore HTTP_PROXY do not pass through this process;
the Seatbelt profile must allow those on the real network.
"""

from __future__ import annotations

import logging
import os
import select
import signal
import socket
import subprocess
import threading
from typing import Optional, Tuple


LISTEN_ADDRESS = ("127.0.0.1", 7899)
CONTROL_ADDRESS = ("127.0.0.1", 7900)
PINNED_UPSTREAM = ("127.0.0.1", 7898)
RULES_UPSTREAM = ("127.0.0.1", 7897)
GUARD = os.path.expanduser("~/.claude/hooks/network-killswitch.sh")
GUARD_TIMEOUT_SECONDS = 6
FULL_GUARD_TIMEOUT_SECONDS = 32
MONITOR_INTERVAL_SECONDS = 1.0

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

stop_event = threading.Event()
safe_event = threading.Event()
validation_lock = threading.Lock()
full_validation_lock = threading.Lock()
active_lock = threading.Lock()
active_pairs: set[Tuple[socket.socket, socket.socket]] = set()
listener: Optional[socket.socket] = None
control_listener: Optional[socket.socket] = None


def run_guard(mode: str, timeout: float) -> Tuple[bool, str]:
    try:
        result = subprocess.run(
            [GUARD, mode],
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


def run_fast_guard() -> Tuple[bool, str]:
    return run_guard("--fast", GUARD_TIMEOUT_SECONDS)


def run_full_guard() -> Tuple[bool, str]:
    return run_guard("--check", FULL_GUARD_TIMEOUT_SECONDS)


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


def safety_monitor() -> None:
    last_safe: Optional[bool] = None
    while not stop_event.wait(MONITOR_INTERVAL_SECONDS):
        ok, reason = run_fast_guard()
        if ok:
            safe_event.set()
            if last_safe is False:
                logging.info("network guard recovered")
        else:
            safe_event.clear()
            close_all_active()
            if last_safe is not False:
                logging.warning("network guard closed all tunnels: %s", reason)
        last_safe = ok


def rules_host_suffixes() -> tuple[str, ...]:
    raw = os.environ.get("CCG_RULES_HOST_SUFFIXES", "").strip()
    if not raw:
        return ()
    return tuple(part.strip().lower().rstrip(".") for part in raw.split(",") if part.strip())


def host_from_http_prefix(data: bytes) -> Optional[str]:
    if not data:
        return None
    first = data.split(b"\r\n", 1)[0].decode("latin1", "replace")
    parts = first.split()
    if len(parts) < 2:
        return None
    method, target = parts[0].upper(), parts[1]
    if method == "CONNECT":
        hostport = target.strip()
        if hostport.startswith("[") and "]:" in hostport:
            return hostport[1:hostport.index("]")].lower()
        return hostport.rsplit(":", 1)[0].lower()
    if "://" in target:
        rest = target.split("://", 1)[1]
        host = rest.split("/", 1)[0]
        if host.startswith("[") and "]" in host:
            return host[1:host.index("]")].lower()
        return host.rsplit(":", 1)[0].lower()
    return None


def uses_clash_rules(host: Optional[str]) -> bool:
    if not host:
        return False
    host = host.lower().rstrip(".")
    return any(host == suffix or host.endswith("." + suffix) for suffix in rules_host_suffixes())


def peek_http_prefix(sock: socket.socket, limit: int = 8192) -> bytes:
    sock.settimeout(3.0)
    buf = b""
    try:
        while b"\r\n" not in buf and len(buf) < limit:
            chunk = sock.recv(1024)
            if not chunk:
                break
            buf += chunk
    except OSError:
        return buf
    finally:
        sock.settimeout(None)
        sock.setblocking(True)
    return buf


def relay_connection(client: socket.socket) -> None:
    upstream: Optional[socket.socket] = None
    pair: Optional[Tuple[socket.socket, socket.socket]] = None
    try:
        with validation_lock:
            ok, reason = run_fast_guard()
        if not ok or not safe_event.is_set():
            logging.warning("connection denied by guard: %s", reason)
            return

        client.setblocking(True)
        prefix = peek_http_prefix(client)
        host = host_from_http_prefix(prefix)
        upstream_addr = RULES_UPSTREAM if uses_clash_rules(host) else PINNED_UPSTREAM
        upstream = socket.create_connection(upstream_addr, timeout=3.0)
        upstream.setblocking(True)
        if prefix:
            upstream.sendall(prefix)
        pair = (client, upstream)
        with active_lock:
            active_pairs.add(pair)

        while not stop_event.is_set() and safe_event.is_set():
            readable, _, exceptional = select.select(
                [client, upstream], [], [client, upstream], 1.0
            )
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
        client.settimeout(FULL_GUARD_TIMEOUT_SECONDS + 2)
        command = client.recv(64).strip()
        if command != b"CHECK":
            client.sendall(b"BLOCK\tinvalid control request\n")
            return
        with full_validation_lock:
            ok, reason = run_full_guard()
        if ok:
            client.sendall(b"OK\n")
        else:
            safe_reason = reason.replace("\t", " ").replace("\n", " ")[:500]
            client.sendall(("BLOCK\t" + safe_reason + "\n").encode("utf-8"))
    except (OSError, UnicodeError):
        pass
    finally:
        close_socket(client)


def control_server() -> None:
    global control_listener

    control_listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    control_listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    control_listener.bind(CONTROL_ADDRESS)
    control_listener.listen(16)
    control_listener.settimeout(1.0)
    logging.info("Claude network validation control listening on localhost:7900")

    while not stop_event.is_set():
        try:
            client, _address = control_listener.accept()
        except socket.timeout:
            continue
        except OSError:
            break
        threading.Thread(target=handle_control, args=(client,), daemon=True).start()


def request_stop(_signum: int, _frame: object) -> None:
    stop_event.set()
    safe_event.clear()
    close_all_active()
    if listener is not None:
        close_socket(listener)
    if control_listener is not None:
        close_socket(control_listener)


def main() -> int:
    global listener

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)

    initial_ok, initial_reason = run_fast_guard()
    if initial_ok:
        safe_event.set()
    else:
        logging.warning("gate starts closed: %s", initial_reason)

    threading.Thread(target=safety_monitor, name="safety-monitor", daemon=True).start()
    threading.Thread(target=control_server, name="control-server", daemon=True).start()

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(LISTEN_ADDRESS)
    listener.listen(64)
    listener.settimeout(1.0)
    logging.info("Claude network gate listening on localhost:7899")

    while not stop_event.is_set():
        try:
            client, _address = listener.accept()
        except socket.timeout:
            continue
        except OSError:
            break
        threading.Thread(target=relay_connection, args=(client,), daemon=True).start()

    request_stop(0, None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
