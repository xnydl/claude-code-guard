#!/usr/bin/env python3
"""Detect OS and whatever proxy client is actually running. No hardcoded vendor."""

from __future__ import annotations

import json
import os
import platform
import shutil
import socket
import subprocess
import sys
from glob import glob
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


GROUP_TYPES = {"Selector", "URLTest", "Fallback", "LoadBalance", "Relay"}
TW_HINT = ("台湾", "台灣", "Hinet", "Seednet", "Taipei", "Chunghwa", "台北")
AUTO_HINT = ("自动", "自動", "auto", "loadbalance", "urltest", "fallback")

HTTP_CONTROLLER_PORTS = (9097, 9090, 9091, 9093, 33331, 6170, 9092)
COMMON_PROXY_PORTS = (
    7897,
    7890,
    7891,
    7892,
    7893,
    7898,
    10808,
    10809,
    1080,
    20171,
    20172,
    6152,
    6153,
    2080,
    7894,
)

PROCESS_HINTS = (
    ("clash-verge", ("Clash Verge", "clash-verge", "Clash Verge Rev")),
    ("clash-for-windows", ("Clash for Windows", "ClashCore", "Clash for Windows.exe")),
    ("mihomo", ("mihomo", "clash-meta", "Clash Meta")),
    ("v2rayn", ("v2rayN", "v2rayn", "v2rayN.exe", "xray.exe")),
    ("sing-box", ("sing-box", "singbox", "Hiddify")),
    ("nekoray", ("nekoray", "nekobox", "NekoRay")),
    ("surge", ("Surge", "surge-core")),
)


def home() -> Path:
    return Path.home()


def os_name() -> str:
    sysname = platform.system().lower()
    if sysname.startswith("darwin"):
        return "darwin"
    if sysname.startswith("win"):
        return "windows"
    return "linux"


def claude_home() -> Path:
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or (home() / ".claude"))


def guard_home() -> Path:
    return home() / ".claude-guard"


def state_path() -> Path:
    return guard_home() / "state.json"


def load_state() -> dict[str, Any]:
    path = state_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_state(data: dict[str, Any]) -> Path:
    path = state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return path


def tcp_open(host: str, port: int, timeout: float = 0.35) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def running_processes() -> list[str]:
    try:
        if os_name() == "windows":
            raw = subprocess.check_output(
                ["tasklist", "/FO", "CSV", "/NH"],
                text=True,
                errors="ignore",
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            names = []
            for line in raw.splitlines():
                if line.startswith('"'):
                    names.append(line.split('","', 1)[0].strip('"'))
            return names
        raw = subprocess.check_output(["ps", "-axo", "comm="], text=True, errors="ignore")
        return [Path(line.strip()).name for line in raw.splitlines() if line.strip()]
    except (OSError, subprocess.CalledProcessError):
        return []


def detect_clients(proc_names: list[str]) -> list[str]:
    found: list[str] = []
    lower = [name.lower() for name in proc_names]
    for label, needles in PROCESS_HINTS:
        for needle in needles:
            if any(needle.lower() in item for item in lower):
                found.append(label)
                break
    return found


def clash_config_candidates() -> list[Path]:
    h = home()
    paths = [
        h / "Library/Application Support/io.github.clash-verge-rev.clash-verge-rev/clash-verge.yaml",
        h / "AppData/Roaming/io.github.clash-verge-rev.clash-verge-rev/clash-verge.yaml",
        h / "AppData/Roaming/clash/config.yaml",
        h / ".config/clash/config.yaml",
        h / ".config/mihomo/config.yaml",
        h / ".config/clash-verge/clash-verge.yaml",
    ]
    return [path for path in paths if path.is_file()]


def unix_socket_candidates() -> list[str]:
    if os_name() == "windows":
        return []
    current_uid = os.getuid()
    # Clash Verge service mode keeps each user's controller under that user's
    # numeric UID. Legacy globs are retained, but candidates owned by another
    # user are discarded before any controller probe can reach them.
    service_socket = f"/var/run/clash-verge-service/users/{current_uid}/verge-mihomo.sock"
    patterns = (
        service_socket,
        "/tmp/verge/verge-mihomo.sock",
        "/tmp/verge/*.sock",
        "/tmp/*clash*.sock",
        "/tmp/*mihomo*.sock",
        str(home() / ".config/clash/*.sock"),
        str(home() / ".config/mihomo/*.sock"),
    )
    found: list[str] = []
    for pattern in patterns:
        for item in glob(pattern):
            path = Path(item)
            try:
                is_current_user_socket = path.is_socket() and path.stat().st_uid == current_uid
            except OSError:
                # The socket may disappear between glob and stat, or be
                # unreadable. Detection is best-effort, so skip it safely.
                continue
            if item not in found and is_current_user_socket:
                found.append(item)
    return found


def http_get_json(url: str, secret: str = "", timeout: float = 1.5) -> dict[str, Any] | None:
    headers = {"Accept": "application/json"}
    if secret:
        headers["Authorization"] = f"Bearer {secret}"
    try:
        with urlopen(Request(url, headers=headers), timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8", "replace"))
    except (OSError, URLError, json.JSONDecodeError, TimeoutError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def unix_get_json(socket_path: str, endpoint: str, timeout: float = 2.5) -> dict[str, Any] | None:
    curl = shutil.which("curl")
    if curl:
        try:
            raw = subprocess.check_output(
                [
                    curl,
                    "--noproxy",
                    "*",
                    "--silent",
                    "--show-error",
                    "--max-time",
                    str(int(timeout) + 1),
                    "--unix-socket",
                    socket_path,
                    f"http://localhost{endpoint}",
                ],
                timeout=timeout + 1,
            )
            payload = json.loads(raw.decode("utf-8", "replace"))
            return payload if isinstance(payload, dict) else None
        except (OSError, subprocess.CalledProcessError, json.JSONDecodeError, subprocess.TimeoutExpired):
            pass
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect(socket_path)
        sock.sendall(
            f"GET {endpoint} HTTP/1.0\r\nHost: localhost\r\nConnection: close\r\n\r\n".encode("ascii")
        )
        chunks: list[bytes] = []
        while True:
            piece = sock.recv(65536)
            if not piece:
                break
            chunks.append(piece)
        sock.close()
    except OSError:
        return None
    raw = b"".join(chunks)
    _head, sep, body = raw.partition(b"\r\n\r\n")
    if not sep:
        return None
    try:
        payload = json.loads(body.decode("utf-8", "replace"))
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def probe_http_controller(port: int) -> dict[str, Any] | None:
    for secret in ("", os.environ.get("CLASH_SECRET", "")):
        version = http_get_json(f"http://127.0.0.1:{port}/version", secret=secret)
        if version and (version.get("version") or version.get("meta")):
            return {"kind": "http", "url": f"http://127.0.0.1:{port}", "secret": secret, "version": version}
    return None


def probe_unix_controller(socket_path: str) -> dict[str, Any] | None:
    version = unix_get_json(socket_path, "/version")
    if version and (version.get("version") or version.get("meta")):
        return {"kind": "unix", "path": socket_path, "secret": "", "version": version}
    return None


def controller_get(controller: dict[str, Any], endpoint: str) -> dict[str, Any] | None:
    if controller.get("kind") == "unix":
        return unix_get_json(str(controller["path"]), endpoint)
    url = str(controller.get("url", "")).rstrip("/") + endpoint
    return http_get_json(url, secret=str(controller.get("secret") or ""))


def controller_select_proxy(controller: dict[str, Any], group: str, node: str) -> bool:
    """Select one Mihomo group member without exposing controller credentials."""
    endpoint = f"/proxies/{quote(group, safe='')}"
    body = json.dumps({"name": node}, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    secret = str(controller.get("secret") or "")
    if secret:
        headers["Authorization"] = f"Bearer {secret}"

    if controller.get("kind") != "unix":
        url = str(controller.get("url", "")).rstrip("/") + endpoint
        try:
            with urlopen(Request(url, data=body, headers=headers, method="PUT"), timeout=3) as response:
                return 200 <= response.status < 300
        except (OSError, URLError, TimeoutError, ValueError):
            return False

    socket_path = str(controller.get("path") or "")
    if not socket_path:
        return False
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(3)
        sock.connect(socket_path)
        request = (
            f"PUT {endpoint} HTTP/1.0\r\n"
            "Host: localhost\r\n"
            "Content-Type: application/json\r\n"
            f"Content-Length: {len(body)}\r\n"
            "Connection: close\r\n\r\n"
        ).encode("ascii") + body
        sock.sendall(request)
        status_line = sock.recv(256).split(b"\r\n", 1)[0]
        sock.close()
    except OSError:
        return False
    parts = status_line.split()
    return len(parts) >= 2 and parts[1].isdigit() and 200 <= int(parts[1]) < 300


def walk_leaf(proxies: dict[str, Any], root: str) -> tuple[list[str], str]:
    chain: list[str] = []
    current = root
    seen: set[str] = set()
    while current and current not in seen:
        seen.add(current)
        chain.append(current)
        details = proxies.get(current)
        if not isinstance(details, dict):
            break
        if details.get("type") not in GROUP_TYPES:
            break
        selected = details.get("now")
        if not isinstance(selected, str) or not selected:
            break
        current = selected
    return chain, current or root


def classify_nodes(proxies: dict[str, Any]) -> dict[str, Any]:
    groups: list[dict[str, Any]] = []
    leaves: list[dict[str, Any]] = []
    for name, details in proxies.items():
        if not isinstance(details, dict):
            continue
        kind = str(details.get("type") or "")
        members = details.get("all")
        item = {
            "name": name,
            "type": kind,
            "now": details.get("now"),
            "all": list(members) if isinstance(members, list) else [],
        }
        if kind in GROUP_TYPES:
            chain, leaf = walk_leaf(proxies, name)
            item["leaf"] = leaf
            item["auto"] = any(hint.lower() in name.lower() for hint in AUTO_HINT)
            groups.append(item)
        elif kind and kind.lower() not in {
            "direct",
            "reject",
            "reject-drop",
            "compatible",
            "pass",
            "pass-rule",
        }:
            recommended = any(hint.lower() in name.lower() for hint in TW_HINT)
            leaves.append({**item, "recommended": recommended, "selectable": True})
    return {"groups": groups, "leaves": leaves}


def detect_proxy_ports() -> list[int]:
    return [port for port in COMMON_PROXY_PORTS if tcp_open("127.0.0.1", port)]


def pick_free_port(preferred: int, used: set[int]) -> int:
    if preferred not in used and not tcp_open("127.0.0.1", preferred):
        return preferred
    for port in range(preferred, preferred + 30):
        if port not in used and not tcp_open("127.0.0.1", port):
            return port
    raise RuntimeError("no free local port")


def detect() -> dict[str, Any]:
    system = os_name()
    procs = running_processes()
    clients = detect_clients(procs)
    configs = [str(path) for path in clash_config_candidates()]
    open_proxy_ports = detect_proxy_ports()

    controller = None
    for sock in unix_socket_candidates():
        controller = probe_unix_controller(sock)
        if controller:
            break
    if controller is None:
        for port in HTTP_CONTROLLER_PORTS:
            if tcp_open("127.0.0.1", port):
                controller = probe_http_controller(port)
                if controller:
                    break

    family = "unknown"
    mixed_port = None
    mode = None
    tun = None
    ipv6 = None
    nodes: dict[str, Any] = {"groups": [], "leaves": []}
    if controller:
        family = "clash-mihomo"
        configs_json = controller_get(controller, "/configs") or {}
        mixed_port = configs_json.get("mixed-port") or configs_json.get("port")
        mode = str(configs_json.get("mode") or "").lower() or None
        tun_obj = configs_json.get("tun")
        if isinstance(tun_obj, dict):
            tun = bool(tun_obj.get("enable"))
        ipv6 = configs_json.get("ipv6")
        proxies_json = controller_get(controller, "/proxies") or {}
        proxies = proxies_json.get("proxies")
        if isinstance(proxies, dict):
            nodes = classify_nodes(proxies)

    if family == "unknown":
        if any(name in clients for name in ("v2rayn", "sing-box", "nekoray")):
            family = "local-proxy"
        elif open_proxy_ports:
            family = "local-proxy"

    bind_port = None
    if isinstance(mixed_port, int) and mixed_port > 0:
        bind_port = mixed_port
    elif open_proxy_ports:
        bind_port = open_proxy_ports[0]

    used = set(open_proxy_ports)
    if isinstance(mixed_port, int):
        used.add(mixed_port)
    gate_port = pick_free_port(7899, used)
    used.add(gate_port)
    control_port = pick_free_port(7900, used)
    used.add(control_port)
    dedicated_port = pick_free_port(7898, used) if family == "clash-mihomo" else None

    recommended = [leaf["name"] for leaf in nodes["leaves"] if leaf.get("recommended")]
    return {
        "os": system,
        "clients": clients,
        "family": family,
        "controller": controller,
        "config_files": configs,
        "mixed_port": mixed_port,
        "open_proxy_ports": open_proxy_ports,
        "bind_port": bind_port,
        "dedicated_port": dedicated_port,
        "gate_port": gate_port,
        "control_port": control_port,
        "mode": mode,
        "tun": tun,
        "ipv6": ipv6,
        "nodes": nodes,
        "recommended_nodes": recommended,
        "can_list_nodes": bool(nodes["leaves"]),
        "sandbox_supported": system == "darwin",
        "notes": _notes(system, family, controller, recommended, bind_port, tun, mode, ipv6),
    }


def _notes(
    system: str,
    family: str,
    controller: dict[str, Any] | None,
    recommended: list[str],
    bind_port: int | None,
    tun: bool | None,
    mode: str | None,
    ipv6: Any,
) -> list[str]:
    notes: list[str] = []
    if system == "windows":
        notes.append("Windows 没有 Seatbelt，只能靠代理绑定 + Hook + 指纹浏览器，拦不住无视代理的直连。")
    if family == "clash-mihomo":
        notes.append("探测到 Clash/Mihomo 控制口，可以列出叶子并校验当前出口。")
        if tun is False:
            notes.append("TUN 未开，系统 DNS / 部分应用可能绕过代理。")
        if mode and mode != "rule":
            notes.append(f"当前模式是 {mode}，建议 Rule。")
        if ipv6 is True:
            notes.append("IPv6 已开，存在旁路风险，建议关掉。")
        if recommended:
            notes.append("名称里像台湾/家宽的叶子已标成推荐，仍须客户亲自点名。")
    elif family == "local-proxy":
        notes.append("没有 Clash API，列不出节点名。请客户先在自己的客户端里切到固定台湾节点，再绑定本地代理端口。")
        if bind_port:
            notes.append(f"将绑定本机已在听的代理端口 {bind_port}。")
    else:
        notes.append("没有发现可用的本地代理。先让客户打开梯子。")
    if controller is None and family == "clash-mihomo":
        notes.append("进程像 Clash，但控制口没通，无法校验叶子。")
    return notes


def print_node_menu(data: dict[str, Any] | None = None) -> int:
    data = data or detect()
    print(f"系统: {data['os']}  客户端: {', '.join(data['clients']) or '未知'}  类型: {data['family']}")
    if not data["can_list_nodes"]:
        print("列不出节点名。请客户在自己的梯子里选好一个固定节点，把完整名字发过来。不要用自动切换。")
        return 0
    recommended = data["recommended_nodes"]
    others = [leaf["name"] for leaf in data["nodes"]["leaves"] if leaf["name"] not in recommended]
    print("请客户选一个固定叶子节点（不要选自动/负载均衡组）。推荐台湾：")
    index = 1
    for name in recommended:
        print(f"  [{index}] {name}  ← 推荐")
        index += 1
    if others:
        print("其他叶子：")
        for name in others:
            print(f"  [{index}] {name}")
            index += 1
    print("停在这里。等客户回复完整节点名后再安装。")
    return 0


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] in {"--list", "list"}:
        return print_node_menu()
    print(json.dumps(detect(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
