#!/usr/bin/env python3
"""Legacy fresh-install template; never overwrite an existing guard or Claude hooks."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from ccg_detect import claude_home, detect, guard_home, os_name, save_state


def python_cmd() -> str:
    return sys.executable or "python3"


def existing_installation() -> list[str]:
    """Refuse implicit migrations before probing or writing anything."""
    conflicts = []
    for path in (Path.home() / ".local/claude-guard", guard_home()):
        if path.exists():
            conflicts.append(str(path))
    hooks = claude_home() / "hooks"
    for name in ("network-killswitch.sh", "network-request-hook.sh", "system-info-guard.sh",
                 "ccg_detect.py", "ccg_guard.py", "hook_request.py", "hook_sysinfo.py"):
        path = hooks / name
        if path.exists():
            conflicts.append(str(path))
    settings = claude_home() / "settings.json"
    if settings.exists():
        try:
            data = json.loads(settings.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or data.get("hooks"):
                conflicts.append(str(settings))
        except (OSError, ValueError, UnicodeError):
            conflicts.append(str(settings))
    return conflicts


def write_settings(state: dict) -> Path:
    path = claude_home() / "settings.json"
    data: dict = {}
    if path.is_file():
        data = json.loads(path.read_text(encoding="utf-8"))
    env = data.setdefault("env", {})
    gate = int(state["gate_port"])
    tz = state.get("timezone") or "Asia/Taipei"
    browser = str(Path(state["install_dir"]) / ("camoufox.ps1" if os_name() == "windows" else "camoufox.sh"))
    env.update(
        {
            "LANG": "en_US.UTF-8",
            "LC_ALL": "en_US.UTF-8",
            "TZ": tz,
            "HTTP_PROXY": f"http://localhost:{gate}",
            "HTTPS_PROXY": f"http://localhost:{gate}",
            "ALL_PROXY": f"http://localhost:{gate}",
            "http_proxy": f"http://localhost:{gate}",
            "https_proxy": f"http://localhost:{gate}",
            "all_proxy": f"http://localhost:{gate}",
            "NO_PROXY": "127.0.0.1,localhost,::1",
            "no_proxy": "127.0.0.1,localhost,::1",
            "BROWSER": browser,
        }
    )
    hook_dir = claude_home() / "hooks"
    py = python_cmd()
    request = str(hook_dir / "hook_request.py")
    sysinfo = str(hook_dir / "hook_sysinfo.py")
    data["hooks"] = {
        "UserPromptSubmit": [
            {"hooks": [{"type": "command", "command": f"{py} {request}", "timeout": 35}]}
        ],
        "PostToolBatch": [
            {"hooks": [{"type": "command", "command": f"{py} {request}", "timeout": 35}]}
        ],
        "PreToolUse": [
            {
                "matcher": "Bash|Read|Glob|Grep|Edit|Write|NotebookEdit",
                "hooks": [{"type": "command", "command": f"{py} {sysinfo}", "timeout": 3}],
            }
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def copy_runtime(dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    names = (
        "ccg_detect.py",
        "ccg_guard.py",
        "ccg_identity.py",
        "ccg_gate.py",
        "hook_request.py",
        "hook_sysinfo.py",
        "claude-network.sb",
        "wrapper.sh",
        "wrapper.ps1",
        "camoufox.sh",
        "camoufox.ps1",
    )
    for name in names:
        src = HERE / name
        if src.is_file():
            shutil.copy2(src, dest / name)
    hook_dir = claude_home() / "hooks"
    hook_dir.mkdir(parents=True, exist_ok=True)
    for name in ("ccg_detect.py", "ccg_guard.py", "hook_request.py", "hook_sysinfo.py"):
        shutil.copy2(HERE / name, hook_dir / name)


def listener_snippet(node: str, port: int) -> str:
    return (
        "listeners:\n"
        "  - name: claude-guard-upstream\n"
        "    type: mixed\n"
        f"    port: {port}\n"
        "    listen: 127.0.0.1\n"
        "    udp: false\n"
        f"    proxy: {node}\n"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--node", default="")
    parser.add_argument("--region", default="TW")
    parser.add_argument("--timezone", default="")
    parser.add_argument("--ai-group", default="")
    args = parser.parse_args()

    conflicts = existing_installation()
    if conflicts:
        print("拒绝覆盖已有保护部署或 Claude Hook；先按 references/maintenance.md 增量维护。",
              file=sys.stderr)
        for path in conflicts:
            print(f"  {path}", file=sys.stderr)
        return 73

    detected = detect()
    if detected["family"] == "unknown":
        print("拒绝安装：本机没有探测到可用梯子。请先打开客户自己的客户端。", file=sys.stderr)
        return 66

    node = args.node.strip()
    if not node:
        print("拒绝安装：必须由客户选定一个固定节点，再传 --node '完整名字'。", file=sys.stderr)
        print("先运行: python3 ccg_detect.py --list")
        return 64
    lowered = node.lower()
    if any(hint in lowered for hint in ("自动", "自動", "auto", "urltest", "loadbalance")):
        print("拒绝安装：这是自动/策略组，不是固定叶子。请客户另选一个具体节点。", file=sys.stderr)
        return 64
    if detected["can_list_nodes"]:
        names = {item["name"] for item in detected["nodes"]["leaves"]}
        groups = {item["name"] for item in detected["nodes"]["groups"]}
        if node in groups and node not in names:
            print("拒绝安装：选的是策略组。请客户选组下面的那个叶子节点全名。", file=sys.stderr)
            return 64
        if node not in names:
            print(f"拒绝安装：节点 {node!r} 不在当前客户端叶子列表里。", file=sys.stderr)
            return 64

    timezone = args.timezone or ("Asia/Taipei" if args.region.upper() == "TW" else "")
    if not timezone:
        print("非台湾节点必须同时传 --timezone（跟出口 GeoIP 一致）。", file=sys.stderr)
        return 64

    upstream = detected["dedicated_port"] if detected["family"] == "clash-mihomo" else detected["bind_port"]
    if detected["family"] != "clash-mihomo":
        upstream = detected["bind_port"]

    install_dir = guard_home()
    state = {
        **detected,
        "expected_node": node,
        "expected_region": args.region.upper(),
        "timezone": timezone,
        "ai_group": args.ai_group or None,
        "upstream_port": upstream,
        "probe_grace": 90,
        "install_dir": str(install_dir),
    }
    copy_runtime(install_dir)
    save_state(state)
    settings = write_settings(state)

    print(f"os={detected['os']} family={detected['family']} clients={detected['clients']}")
    print(f"node={node} region={args.region.upper()} tz={timezone}")
    print(f"upstream=127.0.0.1:{upstream} gate=127.0.0.1:{detected['gate_port']}")
    print(f"settings={settings}")
    print(f"state={install_dir / 'state.json'}")
    for note in detected["notes"]:
        print(f"note: {note}")

    if detected["family"] == "clash-mihomo" and detected["dedicated_port"]:
        print("\n若客户端支持 Mihomo listeners，把下面片段合并进当前配置（不要整文件覆盖）：")
        print(listener_snippet(node, int(detected["dedicated_port"])))
        print("合并后把 Claude 的 upstream_port 保持为这个专用端口。")
        print("若客户端不支持 listeners：把对应策略组切到同一叶子，upstream 会走 mixed-port。")
    else:
        print("\n当前只能绑定客户已经在听的本地代理端口。请确认客户端里此刻就是这个固定节点。")

    print("\n下一步：")
    print(f"1. 启动门：{python_cmd()} {install_dir / 'ccg_gate.py'}")
    if os_name() == "windows":
        print(f"2. 用 {install_dir / 'wrapper.ps1'} 启动 Claude（Windows 无进程沙箱）")
    else:
        print(f"2. 把 {install_dir / 'wrapper.sh'} 放到 PATH 里当作 claude")
    print("3. 登录只走指纹浏览器脚本，不要用系统 Chrome / Edge / Safari")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
