#!/usr/bin/env python3
"""Fail-closed checks. Reads ~/.claude-guard/state.json written after detect + node pick."""

from __future__ import annotations

import json
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from ccg_detect import controller_get, load_state, os_name, tcp_open, walk_leaf


def fail(message: str, as_hook: bool) -> int:
    if as_hook:
        print(json.dumps({"decision": "block", "reason": message}, ensure_ascii=False))
        return 0
    print(message, file=sys.stderr)
    return 1


def expected(state: dict) -> tuple[str, str]:
    node = str(state.get("expected_node") or "").strip()
    region = str(state.get("expected_region") or "TW").strip().upper()
    return node, region


def proxy_url(state: dict) -> str:
    port = state.get("upstream_port") or state.get("bind_port")
    if not port:
        raise RuntimeError("state 里没有可用的本地代理端口")
    return f"http://127.0.0.1:{int(port)}"


def check_fast(state: dict, *, allow_switching: bool = False) -> str | None:
    failover = state.get("failover")
    if isinstance(failover, dict) and failover.get("enabled"):
        failure_threshold = failover.get("failure_threshold", 3)
        probe_interval = failover.get("probe_interval_seconds", 10)
        if (
            isinstance(failure_threshold, bool)
            or not isinstance(failure_threshold, int)
            or isinstance(probe_interval, bool)
            or not isinstance(probe_interval, int)
        ):
            return "Claude 网络保护：主备探测参数无效，保持阻断。"
        if not 2 <= failure_threshold <= 5 or not 5 <= probe_interval <= 60:
            return "Claude 网络保护：主备探测参数超出安全边界，保持阻断。"
        role = str(failover.get("active_role") or "")
        primary = str(failover.get("primary_node") or "")
        secondary = str(failover.get("secondary_node") or "")
        expected_for_role = {"primary": primary, "secondary": secondary}.get(role)
        if role == "blocked":
            return "Claude 网络保护：主备状态已锁定为 blocked，保持强制阻断。"
        if not expected_for_role or str(state.get("expected_node") or "") != expected_for_role:
            return "Claude 网络保护：主备角色与唯一出口状态不一致，保持阻断。"
        if not allow_switching and failover.get("switching") is True:
            return "Claude 网络保护：出口正在受控切换并验证，保持阻断。"
    node, _region = expected(state)
    family = state.get("family")
    if family == "unknown":
        return "Claude 网络保护：没有探测到本地梯子，已拒绝。"
    upstream = state.get("upstream_port") or state.get("bind_port")
    if not upstream or not tcp_open("127.0.0.1", int(upstream)):
        return "Claude 网络保护：绑定的本地代理端口未监听，已拒绝。"

    controller = state.get("controller")
    if not isinstance(controller, dict):
        if family == "clash-mihomo":
            return "Claude 网络保护：Clash 控制口不可用，无法确认出口。"
        if not node:
            return "Claude 网络保护：尚未确认客户已切到固定节点。"
        return None

    configs = controller_get(controller, "/configs")
    if not isinstance(configs, dict):
        return "Claude 网络保护：Clash 控制口暂时无法读取运行配置。"
    mode = str(configs.get("mode") or "").lower()
    if mode and mode != "rule":
        return f"Claude 网络保护：Clash 当前不是 Rule 模式（{mode}），已拒绝。"
    tun = configs.get("tun")
    if isinstance(tun, dict) and tun.get("enable") is False and os_name() != "windows":
        return "Claude 网络保护：Clash TUN 当前未开启，已拒绝。"
    if configs.get("ipv6") is True:
        return "Claude 网络保护：Clash IPv6 当前已开启，已拒绝。"

    if node:
        proxies_json = controller_get(controller, "/proxies")
        if not isinstance(proxies_json, dict):
            return "Claude 网络保护：Clash 控制口暂时无法读取节点状态。"
        proxies = proxies_json.get("proxies")
        if not isinstance(proxies, dict):
            return "Claude 网络保护：Clash 控制口暂时无法读取节点状态。"
        if node not in proxies:
            return "Claude 网络保护：选定的出口节点不存在，已拒绝。"
        group = state.get("ai_group")
        if group and group in proxies:
            if isinstance(failover, dict) and failover.get("enabled"):
                group_details = proxies.get(str(group))
                members = group_details.get("all") if isinstance(group_details, dict) else None
                if (
                    not isinstance(group_details, dict)
                    or group_details.get("type") != "Selector"
                    or not isinstance(members, list)
                    or len(members) != 2
                    or set(members) != {primary, secondary}
                ):
                    return "Claude 网络保护：主备 Selector 不再严格等于指定的一主一备，已拒绝。"
            _chain, leaf = walk_leaf(proxies, str(group))
            if leaf != node:
                return f"Claude 网络保护：策略组 {group} 当前叶子不是已选定节点（实际：{leaf}）。"
        elif isinstance(failover, dict) and failover.get("enabled"):
            return "Claude 网络保护：主备 Selector 不存在，已拒绝。"
    return None


def fetch_trace(url: str, proxy: str, dest: Path) -> bool:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
    try:
        with opener.open(url, timeout=7) as response:
            dest.write_bytes(response.read())
        return True
    except Exception:
        return False


def parse_trace(text: str) -> tuple[str, str]:
    ip = ""
    loc = ""
    for line in text.splitlines():
        key, _, value = line.partition("=")
        if key == "ip":
            ip = value.strip()
        elif key == "loc":
            loc = value.strip().upper()
    return ip, loc


def check_full(
    state: dict,
    *,
    use_cache: bool = True,
    require_anthropic: bool = False,
    allow_switching: bool = False,
) -> tuple[str | None, dict]:
    err = check_fast(state, allow_switching=allow_switching)
    if err:
        return err, {}
    _node, region = expected(state)
    proxy = proxy_url(state)
    grace = int(state.get("probe_grace") or 90)
    cache_path = Path(state.get("probe_state") or (Path(tempfile.gettempdir()) / "claude-network-guard.state"))
    now = int(time.time())
    if use_cache and cache_path.is_file():
        raw = cache_path.read_text(encoding="utf-8").strip()
        parts = raw.split("|")
        if len(parts) >= 3:
            try:
                age = now - int(parts[0])
            except ValueError:
                age = grace + 1
            if parts[2] == region and parts[1] and 0 <= age < grace:
                return None, {"ip": parts[1], "region": region, "http": parts[3] if len(parts) > 3 else "cached"}

    tmp = Path(tempfile.mkdtemp(prefix="claude-network-guard."))
    trace = ""
    for url in (
        "https://claude.ai/cdn-cgi/trace",
        "https://www.cloudflare.com/cdn-cgi/trace",
        "https://1.1.1.1/cdn-cgi/trace",
    ):
        dest = tmp / "trace"
        if fetch_trace(url, proxy, dest):
            trace = dest.read_text(encoding="utf-8", errors="replace")
            break
    ip, loc = parse_trace(trace)
    if loc and loc != region:
        try:
            cache_path.unlink()
        except OSError:
            pass
        return f"Claude 网络保护：实际出口不在选定地区（期望：{region} 实际：{loc}）。", {}
    if require_anthropic and loc != region:
        return "Claude 网络保护：出口探测没有返回明确的目标地区。", {}

    http_code = "000"
    try:
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": proxy, "https": proxy})
        )
        with opener.open("https://api.anthropic.com/", timeout=7) as response:
            http_code = str(response.status)
    except Exception as exc:
        http_code = getattr(getattr(exc, "code", None), "__str__", lambda: "000")()
        if not str(http_code).isdigit():
            http_code = "000"

    info = {"ip": ip, "region": loc or region, "http": http_code}
    accepted_anthropic_codes = {400, 401, 403, 404, 405, 409, 422, 429}
    try:
        numeric_http_code = int(http_code)
    except ValueError:
        numeric_http_code = 0
    if require_anthropic and not (
        200 <= numeric_http_code < 400 or numeric_http_code in accepted_anthropic_codes
    ):
        return f"Claude 网络保护：Anthropic 接口探测失败（HTTP {http_code}）。", {}
    if ip and loc == region:
        cache_path.write_text(f"{now}|{ip}|{region}|{http_code}", encoding="utf-8")
    elif not ip:
        return "Claude 网络保护：出口探测超时且没有近期选定地区缓存。", {}
    return None, info


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "--check"
    as_hook = mode == "--hook"
    if as_hook:
        mode = "--check"
    state = load_state()
    if not state:
        return fail("Claude 网络保护：尚未完成探测与选节点，已拒绝。", as_hook)
    if not state.get("expected_node") and state.get("family") == "clash-mihomo":
        return fail("Claude 网络保护：尚未选定固定出口节点，已拒绝。", as_hook)

    if mode == "--fast":
        err = check_fast(state)
        return fail(err, as_hook) if err else 0

    if mode == "--probe-switch":
        err, info = check_full(
            state,
            use_cache=False,
            require_anthropic=True,
            allow_switching=True,
        )
    elif mode == "--probe":
        err, info = check_full(state, use_cache=False, require_anthropic=True)
    else:
        err, info = check_full(state)
    if err:
        return fail(err, as_hook)
    if mode == "--status":
        node = state.get("expected_node") or "current-proxy"
        print(
            "OK"
            f" os={state.get('os')}"
            f" family={state.get('family')}"
            f" proxy=localhost:{state.get('gate_port')}"
            f" upstream=127.0.0.1:{state.get('upstream_port') or state.get('bind_port')}"
            f" node={node}"
            f" egress={info.get('ip')}/{info.get('region')}"
            f" HTTP={info.get('http')}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
