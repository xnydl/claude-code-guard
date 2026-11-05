#!/usr/bin/env python3
"""Deliver official Claude login URLs to an already-deployed guarded Chromium.

This is an IPC client, not a browser installer or a replacement network guard.
Never launch a raw Chromium binary or fall back to the system browser.
"""

from __future__ import annotations

import os
from pathlib import Path
import platform
import socket
import stat
import subprocess
import sys
import time
from urllib.parse import urlsplit

HOSTS = ("claude.ai", "anthropic.com", "claude.com")
ACK_TIMEOUT = 47
READY_TIMEOUT = 75


class BrowserError(RuntimeError):
    pass


def valid_url(value: str) -> bool:
    if not isinstance(value, str) or not value or len(value) >= 8192:
        return False
    if any(ord(char) <= 32 or ord(char) == 127 for char in value):
        return False
    try:
        parsed = urlsplit(value)
        host = (parsed.hostname or "").lower()
        return (
            parsed.scheme == "https"
            and parsed.username is None
            and parsed.password is None
            and parsed.port in (None, 443)
            and any(host == item or host.endswith("." + item) for item in HOSTS)
        )
    except ValueError:
        return False


def private_path(path: Path, *, is_socket: bool = False) -> None:
    info = path.lstat()
    correct_type = stat.S_ISSOCK(info.st_mode) if is_socket else stat.S_ISDIR(info.st_mode)
    if not correct_type or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise BrowserError("Chromium IPC 目录或 socket 的类型/权限不安全")


def receive_ack(connection) -> None:
    deadline = time.monotonic() + ACK_TIMEOUT
    data = bytearray()
    while b"\n" not in data and len(data) < 512:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise BrowserError("受保护 Chromium 没有确认打开登录页")
        connection.settimeout(remaining)
        chunk = connection.recv(512 - len(data))
        if not chunk:
            break
        data.extend(chunk)
    # Do not echo IPC error text: it must not expose a login URL or token.
    if bytes(data) != b"OK\n":
        raise BrowserError("受保护 Chromium 未通过检查或拒绝打开登录页")


def deliver(root: Path, url: str) -> None:
    private_path(root)
    endpoint = root / "open-url.sock"
    private_path(endpoint, is_socket=True)
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(ACK_TIMEOUT)
        connection.connect(str(endpoint))
        connection.sendall((url + "\n").encode("utf-8"))
        receive_ack(connection)


def open_guarded(url: str) -> None:
    if not valid_url(url):
        raise BrowserError("只接受一个 Claude 官方域名的 HTTPS 登录地址")
    if platform.system() != "Darwin":
        raise BrowserError("此平台尚未部署等效 Chromium IPC 适配器；不会回退系统浏览器")
    root = Path.home() / "Library/Application Support/Fingerprint Chromium Guarded"
    app = Path.home() / "Applications/Fingerprint Chromium Guarded.app"
    if not app.is_dir():
        raise BrowserError("Fingerprint Chromium Guarded 应用未部署；不能裸开 Chromium")
    try:
        private_path(root)
    except OSError as exc:
        raise BrowserError("Chromium 专用 IPC 目录不存在或不可读取") from exc
    try:
        deliver(root, url)
        return
    except (FileNotFoundError, ConnectionRefusedError):
        pass
    # Launch the verified guard application WITHOUT passing the secret URL
    # as a process argument. Its server performs route/egress checks before ACK.
    result = subprocess.run(
        ["/usr/bin/open", "-n", "-a", str(app)],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL, timeout=10, check=False,
    )
    if result.returncode:
        raise BrowserError("受保护 Chromium 启动失败")
    deadline = time.monotonic() + READY_TIMEOUT
    while time.monotonic() < deadline:
        try:
            deliver(root, url)
            return
        except (FileNotFoundError, ConnectionRefusedError):
            time.sleep(0.25)
    raise BrowserError("受保护 Chromium 未就绪或校验失败；登录地址没有打开")


def main(argv=None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if len(arguments) != 1 or not valid_url(arguments[0]):
        print("Claude 浏览器保护：只接受一个 Claude 官方 HTTPS 登录地址。", file=sys.stderr)
        return 78
    try:
        open_guarded(arguments[0])
    except (BrowserError, OSError, subprocess.TimeoutExpired) as exc:
        # OSError/TimeoutExpired may include argv; never echo their payloads.
        reason = str(exc) if isinstance(exc, BrowserError) else "本地受保护浏览器通信或启动失败"
        print("Claude 浏览器保护：" + reason, file=sys.stderr)
        return 78
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
