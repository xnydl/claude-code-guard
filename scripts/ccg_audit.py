#!/usr/bin/env python3
"""Read-only file inventory, not a live network/identity audit. Never runs targets."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

MAX_FILE_BYTES = 2 * 1024 * 1024


def file_summary(path: Path) -> dict:
    if not path.is_file():
        return {"exists": False}
    try:
        # Bounded read; do not follow configuration references or invoke scripts.
        with path.open("rb") as handle:
            content = handle.read(MAX_FILE_BYTES + 1)
        if len(content) > MAX_FILE_BYTES:
            return {"exists": True, "hash_skipped": "file_too_large"}
        return {"exists": True, "sha256": hashlib.sha256(content).hexdigest()}
    except OSError:
        return {"exists": True, "error": "unreadable"}


def settings_summary(path: Path) -> dict:
    result = file_summary(path)
    if not result.get("sha256"):
        return result
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("expected_object")
        env = data.get("env", {})
        permissions = data.get("permissions", {})
        hooks = data.get("hooks", {})
        if not all(isinstance(v, dict) for v in (env, permissions, hooks)):
            raise ValueError("invalid_sections")
    except (OSError, ValueError, UnicodeError):
        result["error"] = "invalid_or_unreadable_settings"
        return result
    result.update({
        "browser_configured": bool(env.get("BROWSER")),
        "proxy_variable_names": sorted(k for k in env if k.upper() in {
            "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY"
        }),
        "timezone_is_taipei": env.get("TZ") == "Asia/Taipei",
        "mouse_disable_variable_present": "CLAUDE_CODE_DISABLE_MOUSE" in env,
        "default_bypass_permissions": permissions.get("defaultMode") == "bypassPermissions",
        # Do not output commands, custom event names, env values or credentials.
        "known_hook_group_counts": {
            event: len(hooks[event]) if isinstance(hooks.get(event), list) else 0
            for event in ("UserPromptSubmit", "PostToolBatch", "PreToolUse")
        },
    })
    return result


def audit(home: Path, claude_dir: Path | None = None,
          browser_launcher: Path | None = None) -> dict:
    claude_dir = claude_dir if claude_dir is not None else home / ".claude"
    local = home / ".local/claude-guard"
    portable = home / ".claude-guard"
    files = {}
    for name in ("bin/claude", "bin/claude-camoufox", "bin/claude-network-gate.py",
                 "claude-network.sb"):
        files["local/" + name] = file_summary(local / name)
    for name in ("ccg_guard.py", "ccg_gate.py", "wrapper.sh", "wrapper.ps1",
                 "hook_request.py", "claude-network.sb"):
        files["portable/" + name] = file_summary(portable / name)
    for name in ("network-killswitch.sh", "network-request-hook.sh", "system-info-guard.sh",
                 "hook_request.py", "hook_sysinfo.py"):
        files["hooks/" + name] = file_summary(claude_dir / "hooks" / name)
    if browser_launcher is not None:
        files["browser_launcher"] = file_summary(browser_launcher)
    return {
        "schema": 1,
        "read_only": True,
        "live_network_verified": False,
        "local_layout_present": local.is_dir(),
        "portable_layout_present": portable.is_dir(),
        "native_cli_file_present": (home / ".local/bin/claude").is_file(),
        "files": files,
        "settings": settings_summary(claude_dir / "settings.json"),
        "limits": ["file_presence_is_not_process_state", "hashes_need_a_before_snapshot",
                   "no_network_or_account_access", "no_proxy_or_sandbox_guarantee"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", type=Path, help="explicit home for offline fixtures")
    parser.add_argument("--claude-dir", type=Path)
    parser.add_argument("--browser-launcher", type=Path)
    args = parser.parse_args()
    home = args.home if args.home is not None else Path.home()
    claude_dir = args.claude_dir
    if claude_dir is None and args.home is None and os.environ.get("CLAUDE_CONFIG_DIR"):
        claude_dir = Path(os.environ["CLAUDE_CONFIG_DIR"])
    print(json.dumps(audit(home, claude_dir, args.browser_launcher),
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
