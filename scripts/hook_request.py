#!/usr/bin/env python3
"""Legacy template Hook: gate CHECK only, with one bounded fail-closed deadline."""

from __future__ import annotations

import json
import socket
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from ccg_detect import load_state

CHECK_TIMEOUT = 32.0  # Must remain below the configured 35-second hook timeout.


def block(reason: str) -> int:
    print(json.dumps({"decision": "block", "reason": reason}, ensure_ascii=False))
    return 0


def check_via_gate(port: int) -> tuple[bool, str]:
    deadline = time.monotonic() + CHECK_TIMEOUT

    def remaining() -> float:
        value = deadline - time.monotonic()
        if value <= 0:
            raise TimeoutError("control deadline")
        return value

    try:
        with socket.create_connection(("127.0.0.1", port), timeout=remaining()) as sock:
            sock.settimeout(remaining())
            sock.sendall(b"CHECK\n")
            chunks = bytearray()
            while b"\n" not in chunks and len(chunks) < 1024:
                sock.settimeout(remaining())
                chunk = sock.recv(1024 - len(chunks))
                if not chunk:
                    break
                chunks.extend(chunk)
    except OSError:
        return False, "network control unavailable or timed out; request blocked"
    if b"\n" not in chunks:
        return False, "incomplete network control response; request blocked"
    data = bytes(chunks).decode("utf-8", "replace").strip()
    if data == "OK":
        return True, ""
    if data == "BLOCK" or data.startswith("BLOCK\t"):
        return False, data.partition("\t")[2].strip() or "network validation blocked"
    return False, "invalid network control response; request blocked"


def main() -> int:
    try:
        state = load_state()
        control = int(state["control_port"])
        if not 1 <= control <= 65535:
            raise ValueError("invalid port")
    except (OSError, ValueError, KeyError, TypeError):
        return block("missing or invalid guard state; request blocked")
    allowed, reason = check_via_gate(control)
    if allowed:
        return 0
    return block(reason)


if __name__ == "__main__":
    raise SystemExit(main())
