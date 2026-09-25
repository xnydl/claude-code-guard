#!/usr/bin/env python3
"""Offline regression tests: temporary fixtures and mocked sockets only."""

from __future__ import annotations

import ast
import copy
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import socket
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import ccg_audit
import ccg_detect
import ccg_failover
import ccg_gate
import ccg_guard
import ccg_install
import hook_request


class FakeSocket:
    def __init__(self, chunks):
        self.chunks = iter(chunks)
        self.timeouts = []
        self.sent = []
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.closed = True

    def settimeout(self, timeout):
        self.timeouts.append(timeout)

    def sendall(self, data):
        self.sent.append(data)

    def recv(self, size):
        value = next(self.chunks, b"")
        if isinstance(value, Exception):
            raise value
        return value[:size]

    def shutdown(self, _how):
        self.closed = True

    def close(self):
        self.closed = True


class HookTests(unittest.TestCase):
    def response(self, *chunks):
        sock = FakeSocket(chunks)
        with patch.object(hook_request.socket, "create_connection", return_value=sock):
            result = hook_request.check_via_gate(7900)
        self.assertTrue(sock.closed)
        self.assertEqual(sock.sent, [b"CHECK\n"])
        self.assertTrue(all(0 < n <= 32 for n in sock.timeouts))
        return result

    def test_fragmented_ok(self):
        self.assertEqual(self.response(b"O", b"K", b"\n"), (True, ""))

    def test_explicit_block(self):
        self.assertEqual(self.response(b"BLOCK\twrong region\n"), (False, "wrong region"))

    def test_block_reason_ok_is_not_authorization(self):
        self.assertEqual(self.response(b"BLOCK\tOK\n"), (False, "OK"))

    def test_incomplete_malformed_and_oversized_responses(self):
        for payload in (b"OK", b"", b"garbage\n", b"OK\nBLOCK\n", b"x" * 1024):
            with self.subTest(payload=payload[:20]):
                self.assertFalse(self.response(payload)[0])

    def test_read_timeout_blocks(self):
        self.assertFalse(self.response(socket.timeout())[0])

    def test_connection_failure_blocks_without_direct_fallback(self):
        with patch.object(hook_request.socket, "create_connection", side_effect=OSError):
            self.assertFalse(hook_request.check_via_gate(7900)[0])
        self.assertFalse(hasattr(hook_request, "subprocess"))

    def test_deadline_does_not_restart_per_receive(self):
        sock = FakeSocket([b"O", b"K\n"])
        with patch.object(hook_request.socket, "create_connection", return_value=sock), \
             patch.object(hook_request.time, "monotonic", side_effect=[0, 1, 2, 3, 33]):
            self.assertFalse(hook_request.check_via_gate(7900)[0])
        self.assertTrue(sock.closed)

    def test_main_blocks_invalid_state_without_connecting(self):
        for state in ({}, {"control_port": "bad"}, {"control_port": 0}):
            with patch.object(hook_request, "load_state", return_value=state), \
                 patch.object(hook_request, "check_via_gate") as check, \
                 contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(hook_request.main(), 0)
                self.assertEqual(json.loads(output.getvalue())["decision"], "block")
                check.assert_not_called()

    def test_hook_never_reads_prompt(self):
        class ForbiddenStdin:
            def read(self, *args):
                raise AssertionError("prompt read")
        with patch.object(hook_request, "load_state", return_value={"control_port": 7900}), \
             patch.object(hook_request, "check_via_gate", return_value=(True, "")), \
             patch.object(sys, "stdin", ForbiddenStdin()), \
             contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(hook_request.main(), 0)
            self.assertEqual(output.getvalue(), "")


class AuditTests(unittest.TestCase):
    def test_empty_home_stays_empty(self):
        with tempfile.TemporaryDirectory(prefix="ccg-audit-test-") as folder:
            home = Path(folder)
            report = ccg_audit.audit(home)
            self.assertFalse(report["settings"]["exists"])
            self.assertFalse(report["live_network_verified"])
            self.assertEqual(list(home.iterdir()), [])

    def test_only_sanitized_summary_and_no_writes(self):
        with tempfile.TemporaryDirectory(prefix="ccg-audit-test-") as folder:
            home = Path(folder)
            config = home / "custom-claude"
            config.mkdir()
            secret = "DO_NOT_EMIT_TEST_CREDENTIAL"
            target = config / "settings.json"
            data = {"env": {"ANTHROPIC_API_KEY": secret, "BROWSER": secret,
                            "HTTPS_PROXY": secret, "TZ": "Asia/Taipei"},
                    "permissions": {"defaultMode": "bypassPermissions"},
                    "hooks": {"UserPromptSubmit": [{"command": secret}]}}
            target.write_text(json.dumps(data), encoding="utf-8")
            before = target.read_bytes()
            report = ccg_audit.audit(home, config)
            self.assertNotIn(secret, json.dumps(report))
            self.assertTrue(report["settings"]["timezone_is_taipei"])
            self.assertTrue(report["settings"]["default_bypass_permissions"])
            self.assertFalse(report["settings"]["mouse_disable_variable_present"])
            self.assertEqual(target.read_bytes(), before)
            self.assertEqual(len(list(home.rglob("*"))), 2)

    def test_invalid_settings_fail_safely(self):
        with tempfile.TemporaryDirectory(prefix="ccg-audit-test-") as folder:
            path = Path(folder) / "settings.json"
            for data in ("broken", "[]", '{"env": []}'):
                path.write_text(data, encoding="utf-8")
                self.assertIn("error", ccg_audit.settings_summary(path))


class DetectTests(unittest.TestCase):
    def test_current_user_service_socket_precedes_legacy_tmp_paths(self):
        service_socket = "/var/run/clash-verge-service/users/503/verge-mihomo.sock"
        seen_patterns = []

        def fake_glob(pattern):
            seen_patterns.append(pattern)
            return [pattern] if pattern == service_socket else []

        with patch.object(ccg_detect, "os_name", return_value="darwin"), \
             patch.object(ccg_detect.os, "getuid", return_value=503), \
             patch.object(ccg_detect, "glob", side_effect=fake_glob), \
             patch.object(ccg_detect.Path, "is_socket", return_value=True):
            candidates = ccg_detect.unix_socket_candidates()

        self.assertEqual(candidates, [service_socket])
        self.assertEqual(seen_patterns[0], service_socket)
        self.assertFalse(any("/users/*/" in pattern for pattern in seen_patterns))

    def test_windows_does_not_resolve_unix_uid(self):
        with patch.object(ccg_detect, "os_name", return_value="windows"), \
             patch.object(ccg_detect.os, "getuid", side_effect=AssertionError("unexpected UID lookup")):
            self.assertEqual(ccg_detect.unix_socket_candidates(), [])


class InstallerTests(unittest.TestCase):
    def test_existing_layout_or_hooks_refused(self):
        with tempfile.TemporaryDirectory(prefix="ccg-install-test-") as folder:
            home = Path(folder)
            config = home / ".claude"
            with patch.object(ccg_install.Path, "home", return_value=home), \
                 patch.object(ccg_install, "guard_home", return_value=home / ".claude-guard"), \
                 patch.object(ccg_install, "claude_home", return_value=config):
                self.assertEqual(ccg_install.existing_installation(), [])
                config.mkdir()
                settings = config / "settings.json"
                settings.write_text('{"hooks": {"Stop": []}}', encoding="utf-8")
                self.assertIn(str(settings), ccg_install.existing_installation())
                settings.write_text("{}", encoding="utf-8")
                self.assertEqual(ccg_install.existing_installation(), [])
                local = home / ".local/claude-guard"
                local.mkdir(parents=True)
                self.assertIn(str(local), ccg_install.existing_installation())

    def test_refusal_happens_before_detection_or_writes(self):
        with patch.object(ccg_install, "existing_installation", return_value=["existing"]), \
             patch.object(ccg_install, "detect") as detect, \
             patch.object(ccg_install, "copy_runtime") as copy, \
             patch.object(ccg_install, "save_state") as save, \
             patch.object(ccg_install, "write_settings") as write, \
             patch.object(sys, "argv", ["ccg_install.py", "--node", "fixture"]), \
             contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(ccg_install.main(), 73)
            for action in (detect, copy, save, write):
                action.assert_not_called()

    def test_runtime_package_contains_failover_controller(self):
        with tempfile.TemporaryDirectory(prefix="ccg-package-test-") as folder, \
             patch.object(ccg_install, "claude_home", return_value=Path(folder) / ".claude"):
            destination = Path(folder) / "runtime"
            ccg_install.copy_runtime(destination)
            self.assertTrue((destination / "ccg_failover.py").is_file())

    def test_default_single_node_state_has_no_failover(self):
        detected = {
            "os": "darwin", "clients": ["mihomo"], "family": "clash-mihomo",
            "controller": {"kind": "unix"}, "config_files": [], "mixed_port": 7890,
            "open_proxy_ports": [7890], "bind_port": 7890, "dedicated_port": 7898,
            "gate_port": 7899, "control_port": 7900, "mode": "rule", "tun": True,
            "ipv6": False, "nodes": {"groups": [], "leaves": [{"name": PRIMARY}]},
            "recommended_nodes": [], "can_list_nodes": True, "sandbox_supported": True,
            "notes": [],
        }
        saved = []
        with patch.object(ccg_install, "existing_installation", return_value=[]), \
             patch.object(ccg_install, "detect", return_value=detected), \
             patch.object(ccg_install, "copy_runtime"), \
             patch.object(ccg_install, "save_state", side_effect=lambda state: saved.append(copy.deepcopy(state))), \
             patch.object(ccg_install, "write_settings", return_value=Path("/tmp/settings.json")), \
             patch.object(ccg_install, "guard_home", return_value=Path("/tmp/guard")), \
             patch.object(sys, "argv", ["ccg_install.py", "--node", PRIMARY]), \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(ccg_install.main(), 0)
        self.assertNotIn("failover", saved[-1])

    def test_failover_installer_rejects_selector_without_both_members(self):
        detected = {
            "os": "darwin", "clients": ["mihomo"], "family": "clash-mihomo",
            "controller": {"kind": "unix"}, "config_files": [], "mixed_port": 7890,
            "open_proxy_ports": [7890], "bind_port": 7890, "dedicated_port": 7898,
            "gate_port": 7899, "control_port": 7900, "mode": "rule", "tun": True,
            "ipv6": False,
            "nodes": {
                "groups": [{"name": GROUP, "type": "Selector", "leaf": PRIMARY, "all": [PRIMARY]}],
                "leaves": [{"name": PRIMARY}, {"name": SECONDARY}],
            },
            "recommended_nodes": [], "can_list_nodes": True, "sandbox_supported": True,
            "notes": [],
        }
        with patch.object(ccg_install, "existing_installation", return_value=[]), \
             patch.object(ccg_install, "detect", return_value=detected), \
             patch.object(ccg_install, "copy_runtime") as copy_runtime, \
             patch.object(
                 sys,
                 "argv",
                 ["ccg_install.py", "--node", PRIMARY, "--secondary-node", SECONDARY, "--ai-group", GROUP],
             ), \
             contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(ccg_install.main(), 64)
        copy_runtime.assert_not_called()

    def test_failover_installer_rejects_third_selector_member(self):
        third = "third-leaf"
        detected = {
            "os": "darwin", "clients": ["mihomo"], "family": "clash-mihomo",
            "controller": {"kind": "unix"}, "config_files": [], "mixed_port": 7890,
            "open_proxy_ports": [7890], "bind_port": 7890, "dedicated_port": 7898,
            "gate_port": 7899, "control_port": 7900, "mode": "rule", "tun": True,
            "ipv6": False,
            "nodes": {
                "groups": [{
                    "name": GROUP, "type": "Selector", "leaf": PRIMARY,
                    "all": [PRIMARY, SECONDARY, third],
                }],
                "leaves": [{"name": PRIMARY}, {"name": SECONDARY}, {"name": third}],
            },
            "recommended_nodes": [], "can_list_nodes": True, "sandbox_supported": True,
            "notes": [],
        }
        with patch.object(ccg_install, "existing_installation", return_value=[]), \
             patch.object(ccg_install, "detect", return_value=detected), \
             patch.object(ccg_install, "copy_runtime") as copy_runtime, \
             patch.object(
                 sys,
                 "argv",
                 ["ccg_install.py", "--node", PRIMARY, "--secondary-node", SECONDARY,
                  "--ai-group", GROUP],
             ), \
             contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(ccg_install.main(), 64)
        copy_runtime.assert_not_called()

    def test_failover_installer_rejects_unbounded_probe_parameters(self):
        detected = {
            "os": "darwin", "clients": ["mihomo"], "family": "clash-mihomo",
            "controller": {"kind": "unix"}, "config_files": [], "mixed_port": 7890,
            "open_proxy_ports": [7890], "bind_port": 7890, "dedicated_port": 7898,
            "gate_port": 7899, "control_port": 7900, "mode": "rule", "tun": True,
            "ipv6": False,
            "nodes": {
                "groups": [{
                    "name": GROUP, "type": "Selector", "leaf": PRIMARY,
                    "all": [PRIMARY, SECONDARY],
                }],
                "leaves": [{"name": PRIMARY}, {"name": SECONDARY}],
            },
            "recommended_nodes": [], "can_list_nodes": True, "sandbox_supported": True,
            "notes": [],
        }
        with patch.object(ccg_install, "existing_installation", return_value=[]), \
             patch.object(ccg_install, "detect", return_value=detected), \
             patch.object(ccg_install, "controller_select_proxy", return_value=True), \
             patch.object(ccg_install, "controller_get", return_value=proxy_payload()), \
             patch.object(ccg_install, "copy_runtime") as copy_runtime, \
             patch.object(
                 sys,
                 "argv",
                 ["ccg_install.py", "--node", PRIMARY, "--secondary-node", SECONDARY,
                  "--ai-group", GROUP, "--failure-threshold", "6", "--probe-interval", "61"],
             ), \
             contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(ccg_install.main(), 64)
        copy_runtime.assert_not_called()


PRIMARY = "primary-leaf"
SECONDARY = "secondary-leaf"
GROUP = "CC test"


class FakeResponse:
    def __init__(self, status):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class FakeOpener:
    def __init__(self, status):
        self.status = status

    def open(self, *_args, **_kwargs):
        return FakeResponse(self.status)


def failover_state():
    return {
        "expected_node": PRIMARY,
        "ai_group": GROUP,
        "controller": {"kind": "unix", "path": "/tmp/test.sock"},
        "failover": {
            "enabled": True,
            "primary_node": PRIMARY,
            "secondary_node": SECONDARY,
            "active_role": "primary",
            "failure_threshold": 3,
            "cooldown_seconds": 1800,
        },
    }


def proxy_payload(now=PRIMARY):
    return {
        "proxies": {
            GROUP: {"type": "Selector", "now": now, "all": [PRIMARY, SECONDARY]},
            PRIMARY: {"type": "Vless"},
            SECONDARY: {"type": "Vless"},
        }
    }


def mutable_controller(selection_results=None):
    current = {"leaf": PRIMARY}
    selected = []
    outcomes = iter(selection_results) if selection_results is not None else None

    def get(_controller, _endpoint):
        return proxy_payload(now=current["leaf"])

    def select(_controller, group, node):
        selected.append((group, node))
        ok = next(outcomes) if outcomes is not None else True
        if ok:
            current["leaf"] = node
        return ok

    return get, select, selected


class FailoverTests(unittest.TestCase):
    def strict_probe(self, trace, status):
        state = failover_state()
        state.update({"upstream_port": 7898, "expected_region": "TW"})
        with tempfile.TemporaryDirectory() as folder:
            state["probe_state"] = str(Path(folder) / "probe")

            def write_trace(_url, _proxy, dest):
                dest.write_text(trace, encoding="utf-8")
                return True

            with patch.object(ccg_guard, "check_fast", return_value=None), \
                 patch.object(ccg_guard, "fetch_trace", side_effect=write_trace), \
                 patch.object(ccg_guard.urllib.request, "build_opener", return_value=FakeOpener(status)):
                return ccg_guard.check_full(
                    state,
                    use_cache=False,
                    require_anthropic=True,
                )

    def test_strict_probe_requires_explicit_region(self):
        error, _info = self.strict_probe("ip=192.0.2.1\n", 404)
        self.assertIn("明确的目标地区", error)

    def test_strict_probe_rejects_gateway_error(self):
        error, _info = self.strict_probe("ip=192.0.2.1\nloc=TW\n", 503)
        self.assertIn("HTTP 503", error)

    def test_strict_probe_accepts_anthropic_root_not_found(self):
        error, info = self.strict_probe("ip=192.0.2.1\nloc=TW\n", 404)
        self.assertIsNone(error)
        self.assertEqual(info["http"], "404")

    def test_normal_guard_blocks_during_unverified_switch(self):
        state = failover_state()
        state["failover"]["switching"] = True
        self.assertIn("保持阻断", ccg_guard.check_fast(state))

    def test_blocked_role_is_rejected_even_without_switching_marker(self):
        state = failover_state()
        state["failover"]["active_role"] = "blocked"
        state["failover"]["switching"] = False
        self.assertIn("强制阻断", ccg_guard.check_fast(state))

    def test_role_expected_node_mismatch_is_rejected(self):
        state = failover_state()
        state["expected_node"] = SECONDARY
        self.assertIn("状态不一致", ccg_guard.check_fast(state))

    def test_validate_rejects_automatic_mihomo_group(self):
        state = failover_state()
        payload = proxy_payload()
        payload["proxies"][GROUP]["type"] = "Fallback"
        with patch.object(ccg_failover, "controller_get", return_value=payload):
            self.assertIn("必须是 Selector", ccg_failover.validate_config(state))

    def test_validate_rejects_third_selector_member(self):
        state = failover_state()
        payload = proxy_payload()
        payload["proxies"][GROUP]["all"].append("third-leaf")
        payload["proxies"]["third-leaf"] = {"type": "Vless"}
        with patch.object(ccg_failover, "controller_get", return_value=payload):
            self.assertIn("必须且只能", ccg_failover.validate_config(state))

    def test_validate_rejects_blocked_or_switching_reentry(self):
        for updates in (
            {"active_role": "blocked", "switching": True},
            {"active_role": "primary", "switching": True},
        ):
            state = failover_state()
            state["failover"].update(updates)
            with self.subTest(updates=updates):
                self.assertIn("拒绝重入", ccg_failover.validate_config(state))

    def test_validate_requires_selector_to_resolve_to_primary(self):
        state = failover_state()
        with patch.object(
            ccg_failover,
            "controller_get",
            return_value=proxy_payload(now=SECONDARY),
        ):
            self.assertIn("真实叶子不是主节点", ccg_failover.validate_config(state))

    def test_success_promotes_secondary_to_only_expected_node(self):
        state = failover_state()
        saved = []
        get, select, selected = mutable_controller()
        with patch.object(ccg_failover, "load_state", return_value=copy.deepcopy(state)), \
             patch.object(ccg_failover, "controller_get", side_effect=get), \
             patch.object(ccg_failover, "controller_select_proxy", side_effect=select), \
             patch.object(
                 ccg_failover,
                 "atomic_save_state",
                 side_effect=lambda value: saved.append(copy.deepcopy(value)),
             ), \
             patch.object(ccg_failover, "clear_probe_cache"), \
             patch.object(ccg_failover, "fresh_probe", return_value=(True, "OK")):
            ok, _message = ccg_failover._switch_to_secondary(now=2_000)
        self.assertTrue(ok)
        self.assertEqual(selected, [(GROUP, SECONDARY)])
        self.assertEqual(saved[-1]["expected_node"], SECONDARY)
        self.assertEqual(saved[-1]["failover"]["active_role"], "secondary")
        self.assertFalse(saved[-1]["failover"]["switching"])
        self.assertGreaterEqual(
            len([value for value in saved if value["failover"].get("switching")]),
            2,
        )

    def test_failed_secondary_and_failed_rollback_stays_blocked(self):
        state = failover_state()
        saved = []
        get, select, _selected = mutable_controller([True, False])
        with patch.object(ccg_failover, "load_state", return_value=copy.deepcopy(state)), \
             patch.object(ccg_failover, "controller_get", side_effect=get), \
             patch.object(ccg_failover, "controller_select_proxy", side_effect=select), \
             patch.object(
                 ccg_failover,
                 "atomic_save_state",
                 side_effect=lambda value: saved.append(copy.deepcopy(value)),
             ), \
             patch.object(ccg_failover, "clear_probe_cache"), \
             patch.object(ccg_failover, "fresh_probe", return_value=(False, "probe failed")):
            ok, message = ccg_failover._switch_to_secondary(now=2_000)
        self.assertFalse(ok)
        self.assertIn("强制阻断", message)
        self.assertEqual(saved[-1]["failover"]["active_role"], "blocked")
        self.assertTrue(saved[-1]["failover"]["switching"])

    def test_selector_write_failure_persists_blocked_state(self):
        state = failover_state()
        saved = []
        with patch.object(ccg_failover, "load_state", return_value=copy.deepcopy(state)), \
             patch.object(ccg_failover, "controller_get", return_value=proxy_payload()), \
             patch.object(ccg_failover, "controller_select_proxy", return_value=False), \
             patch.object(
                 ccg_failover,
                 "atomic_save_state",
                 side_effect=lambda value: saved.append(copy.deepcopy(value)),
             ):
            ok, message = ccg_failover._switch_to_secondary(now=2_000)
        self.assertFalse(ok)
        self.assertIn("强制阻断", message)
        self.assertEqual(saved[-1]["failover"]["active_role"], "blocked")
        self.assertTrue(saved[-1]["failover"]["switching"])

    def test_successful_rollback_requires_strict_primary_probe(self):
        state = failover_state()
        saved = []
        get, select, selected = mutable_controller()
        with patch.object(ccg_failover, "load_state", return_value=copy.deepcopy(state)), \
             patch.object(ccg_failover, "controller_get", side_effect=get), \
             patch.object(ccg_failover, "controller_select_proxy", side_effect=select), \
             patch.object(
                 ccg_failover,
                 "atomic_save_state",
                 side_effect=lambda value: saved.append(copy.deepcopy(value)),
             ), \
             patch.object(ccg_failover, "clear_probe_cache"), \
             patch.object(
                 ccg_failover,
                 "fresh_probe",
                 side_effect=[(False, "secondary failed"), (True, "primary restored")],
             ) as probe:
            ok, message = ccg_failover._switch_to_secondary(now=2_000)
        self.assertFalse(ok)
        self.assertIn("严格复验恢复", message)
        self.assertEqual(probe.call_count, 2)
        self.assertEqual(selected, [(GROUP, SECONDARY), (GROUP, PRIMARY)])
        self.assertEqual(saved[-1]["failover"]["active_role"], "primary")
        self.assertFalse(saved[-1]["failover"]["switching"])

    def test_secondary_write_readback_mismatch_stays_blocked(self):
        state = failover_state()
        saved = []
        with patch.object(ccg_failover, "load_state", return_value=copy.deepcopy(state)), \
             patch.object(ccg_failover, "controller_get", return_value=proxy_payload(now=PRIMARY)), \
             patch.object(ccg_failover, "controller_select_proxy", return_value=True), \
             patch.object(
                 ccg_failover,
                 "atomic_save_state",
                 side_effect=lambda value: saved.append(copy.deepcopy(value)),
             ), \
             patch.object(ccg_failover, "fresh_probe") as probe:
            ok, message = ccg_failover._switch_to_secondary(now=2_000)
        self.assertFalse(ok)
        self.assertIn("读回不符", message)
        self.assertEqual(saved[-1]["failover"]["active_role"], "blocked")
        self.assertTrue(saved[-1]["failover"]["switching"])
        probe.assert_not_called()

    def test_concurrent_transition_is_refused(self):
        with patch.object(ccg_failover, "acquire_transition_lock", return_value=None), \
             patch.object(ccg_failover, "_switch_to_secondary") as transition:
            ok, message = ccg_failover.switch_to_secondary(now=2_000)
        self.assertFalse(ok)
        self.assertIn("正在执行", message)
        transition.assert_not_called()

    def test_advisory_lock_releases_when_owning_descriptor_closes(self):
        with tempfile.TemporaryDirectory() as folder, \
             patch.object(ccg_failover, "HERE", Path(folder)):
            first = ccg_failover.acquire_transition_lock()
            self.assertIsNotNone(first)
            self.assertIsNone(ccg_failover.acquire_transition_lock())
            os.close(first)
            recovered = ccg_failover.acquire_transition_lock()
            self.assertIsNotNone(recovered)
            ccg_failover.release_transition_lock(recovered)


class GateSafetyTests(unittest.TestCase):
    def tearDown(self):
        ccg_gate.safe_event.clear()

    def test_control_blocks_when_gate_has_no_fresh_safe_route(self):
        sock = FakeSocket([b"CHECK\n"])
        ccg_gate.safe_event.clear()
        with patch.object(ccg_gate, "run_guard") as guard:
            ccg_gate.handle_control(sock)
        guard.assert_not_called()
        self.assertEqual(sock.sent, [b"BLOCK\tgate has no fresh validated-safe route\n"])

    def test_control_rechecks_safe_state_after_validation(self):
        sock = FakeSocket([b"CHECK\n"])
        ccg_gate.safe_event.set()

        def lose_route(*_args):
            ccg_gate.safe_event.clear()
            return True, "OK"

        with patch.object(ccg_gate, "run_guard", side_effect=lose_route):
            ccg_gate.handle_control(sock)
        self.assertEqual(sock.sent, [b"BLOCK\tgate route became unsafe during validation\n"])

    def test_only_availability_failures_are_transient(self):
        for reason in (
            "TimeoutExpired",
            "Claude 网络保护：Clash 控制口暂时无法读取运行配置。",
            "Claude 网络保护：Clash 控制口暂时无法读取节点状态。",
            "Claude 网络保护：Anthropic 接口探测失败（HTTP 000）。",
            "Claude 网络保护：出口探测没有返回明确的目标地区。",
            "Claude 网络保护：出口探测超时且没有近期选定地区缓存。",
        ):
            with self.subTest(reason=reason):
                self.assertTrue(ccg_gate.is_transient_failure(reason))
        for reason in (
            "OSError",
            "Claude 网络保护：实际出口不在选定地区（期望：TW 实际：US）。",
            "Claude 网络保护：策略组 CC 当前叶子不是已选定节点。",
            "Claude 网络保护：Clash TUN 当前未开启，已拒绝。",
            "Claude 网络保护：选定的出口节点不存在，已拒绝。",
        ):
            with self.subTest(reason=reason):
                self.assertFalse(ccg_gate.is_transient_failure(reason))

    def test_fast_check_fails_closed_but_classifies_controller_read_failure_as_transient(self):
        state = failover_state()
        state.update({"family": "clash-mihomo", "upstream_port": 7898})
        with patch.object(ccg_guard, "tcp_open", return_value=True), \
             patch.object(ccg_guard, "controller_get", return_value=None):
            reason = ccg_guard.check_fast(state)
        self.assertIn("控制口暂时无法读取", reason)
        self.assertTrue(ccg_gate.is_transient_failure(reason))

    def test_fast_check_does_not_classify_missing_expected_node_as_transient(self):
        state = failover_state()
        state.update({"family": "clash-mihomo", "upstream_port": 7898})
        payload = proxy_payload()
        del payload["proxies"][PRIMARY]
        with patch.object(ccg_guard, "tcp_open", return_value=True), \
             patch.object(
                 ccg_guard,
                 "controller_get",
                 side_effect=[{"mode": "rule", "tun": {"enable": True}, "ipv6": False}, payload],
             ):
            reason = ccg_guard.check_fast(state)
        self.assertIn("节点不存在", reason)
        self.assertFalse(ccg_gate.is_transient_failure(reason))

    def test_fast_check_rejects_unbounded_probe_parameters(self):
        state = failover_state()
        state["failover"]["failure_threshold"] = 6
        self.assertIn("超出安全边界", ccg_guard.check_fast(state))
        state["failover"]["failure_threshold"] = 0
        state["failover"]["probe_interval_seconds"] = 0
        self.assertIn("超出安全边界", ccg_guard.check_fast(state))
        state["failover"]["failure_threshold"] = "3"
        state["failover"]["probe_interval_seconds"] = 10
        self.assertIn("参数无效", ccg_guard.check_fast(state))

    def test_failover_validation_rejects_explicit_zero_probe_parameters(self):
        state = failover_state()
        state["failover"]["failure_threshold"] = 0
        state["failover"]["probe_interval_seconds"] = 0
        self.assertIn("超出安全边界", ccg_failover.validate_config(state))
        state["failover"]["failure_threshold"] = True
        state["failover"]["probe_interval_seconds"] = 10
        self.assertIn("参数无效", ccg_failover.validate_config(state))

    def test_fast_check_rejects_runtime_third_selector_member(self):
        state = failover_state()
        state.update({"family": "clash-mihomo", "upstream_port": 7898})
        payload = proxy_payload()
        payload["proxies"][GROUP]["all"].append("third-leaf")
        payload["proxies"]["third-leaf"] = {"type": "Vless"}
        with patch.object(ccg_guard, "tcp_open", return_value=True), \
             patch.object(
                 ccg_guard,
                 "controller_get",
                 side_effect=[{"mode": "rule", "tun": {"enable": True}, "ipv6": False}, payload],
             ):
            reason = ccg_guard.check_fast(state)
        self.assertIn("严格等于", reason)
        self.assertFalse(ccg_gate.is_transient_failure(reason))

    def test_single_transient_failure_may_retain_a_fresh_route(self):
        ccg_gate.safe_event.set()
        self.assertTrue(
            ccg_gate.may_retain_validated_route("TimeoutExpired", 1, 3, True)
        )
        self.assertFalse(
            ccg_gate.may_retain_validated_route("TimeoutExpired", 3, 3, True)
        )
        self.assertFalse(
            ccg_gate.may_retain_validated_route("TimeoutExpired", 1, 3, False)
        )
        self.assertFalse(
            ccg_gate.may_retain_validated_route(
                "Claude 网络保护：实际出口不在选定地区。",
                1,
                3,
                True,
            )
        )

    def test_monitor_retains_route_for_one_fast_timeout(self):
        waits = iter([False, False, True])
        config = {
            "enabled": True,
            "active_role": "secondary",
            "failure_threshold": 3,
            "probe_interval_seconds": 10,
        }
        with patch.object(ccg_gate.stop_event, "wait", side_effect=lambda _n: next(waits)), \
             patch.object(ccg_gate, "failover_config", return_value=config), \
             patch.object(
                 ccg_gate,
                 "run_guard",
                 side_effect=[(True, "OK"), (True, "OK"), (False, "TimeoutExpired")],
             ), \
             patch.object(ccg_gate.time, "monotonic", side_effect=[10, 11]), \
             patch.object(ccg_gate, "close_all_active") as close_all:
            ccg_gate.safety_monitor()
        self.assertTrue(ccg_gate.safe_event.is_set())
        close_all.assert_called_once()  # startup stays closed until the first strict probe

    def test_monitor_closes_after_bounded_fast_timeout_threshold(self):
        waits = iter([False, False, False, False, True])
        config = {
            "enabled": True,
            "active_role": "secondary",
            "failure_threshold": 3,
            "probe_interval_seconds": 10,
        }
        with patch.object(ccg_gate.stop_event, "wait", side_effect=lambda _n: next(waits)), \
             patch.object(ccg_gate, "failover_config", return_value=config), \
             patch.object(
                 ccg_gate,
                 "run_guard",
                 side_effect=[
                     (True, "OK"),
                     (True, "OK"),
                     (False, "TimeoutExpired"),
                     (False, "TimeoutExpired"),
                     (False, "TimeoutExpired"),
                 ],
             ), \
             patch.object(ccg_gate.time, "monotonic", side_effect=[10, 11, 12, 13]), \
             patch.object(ccg_gate, "close_all_active"):
            ccg_gate.safety_monitor()
        self.assertFalse(ccg_gate.safe_event.is_set())

    def test_monitor_retains_route_for_one_transient_probe_failure(self):
        waits = iter([False, False, True])
        config = {
            "enabled": True,
            "active_role": "secondary",
            "failure_threshold": 3,
            "probe_interval_seconds": 10,
        }
        with patch.object(ccg_gate.stop_event, "wait", side_effect=lambda _n: next(waits)), \
             patch.object(ccg_gate, "failover_config", return_value=config), \
             patch.object(
                 ccg_gate,
                 "run_guard",
                 side_effect=[
                     (True, "OK"),
                     (True, "OK"),
                     (True, "OK"),
                     (False, "Claude 网络保护：Anthropic 接口探测失败（HTTP 000）。"),
                 ],
             ), \
             patch.object(ccg_gate.time, "monotonic", side_effect=[10, 20]), \
             patch.object(ccg_gate, "close_all_active") as close_all:
            ccg_gate.safety_monitor()
        self.assertTrue(ccg_gate.safe_event.is_set())
        close_all.assert_called_once()

    def test_monitor_closes_immediately_on_explicit_unsafe_probe(self):
        waits = iter([False, False, True])
        config = {
            "enabled": True,
            "active_role": "secondary",
            "failure_threshold": 3,
            "probe_interval_seconds": 10,
        }
        with patch.object(ccg_gate.stop_event, "wait", side_effect=lambda _n: next(waits)), \
             patch.object(ccg_gate, "failover_config", return_value=config), \
             patch.object(
                 ccg_gate,
                 "run_guard",
                 side_effect=[
                     (True, "OK"),
                     (True, "OK"),
                     (True, "OK"),
                     (False, "Claude 网络保护：实际出口不在选定地区（期望：TW 实际：US）。"),
                 ],
             ), \
             patch.object(ccg_gate.time, "monotonic", side_effect=[10, 20]), \
             patch.object(ccg_gate, "close_all_active") as close_all:
            ccg_gate.safety_monitor()
        self.assertFalse(ccg_gate.safe_event.is_set())
        self.assertEqual(close_all.call_count, 2)

    def test_monitor_fails_closed_on_malformed_config(self):
        waits = iter([False, True])
        ccg_gate.safe_event.set()
        config = {
            "enabled": True,
            "active_role": "secondary",
            "failure_threshold": "not-an-integer",
            "probe_interval_seconds": 10,
        }
        with patch.object(ccg_gate.stop_event, "wait", side_effect=lambda _n: next(waits)), \
             patch.object(ccg_gate, "failover_config", return_value=config), \
             patch.object(ccg_gate, "run_guard", return_value=(True, "OK")), \
             patch.object(ccg_gate, "close_all_active") as close_all:
            ccg_gate.safety_monitor()
        self.assertFalse(ccg_gate.safe_event.is_set())
        close_all.assert_called_once()

    def test_monitor_fails_closed_on_explicit_zero_probe_parameters(self):
        waits = iter([False, True])
        ccg_gate.safe_event.set()
        config = {
            "enabled": True,
            "active_role": "secondary",
            "failure_threshold": 0,
            "probe_interval_seconds": 0,
        }
        with patch.object(ccg_gate.stop_event, "wait", side_effect=lambda _n: next(waits)), \
             patch.object(ccg_gate, "failover_config", return_value=config), \
             patch.object(ccg_gate, "run_guard", return_value=(False, "unsafe")), \
             patch.object(ccg_gate, "close_all_active") as close_all:
            ccg_gate.safety_monitor()
        self.assertFalse(ccg_gate.safe_event.is_set())
        close_all.assert_called_once()

    def test_strict_probe_success_resets_fast_timeout_streak(self):
        waits = iter([False, False, False, False, True])
        config = {
            "enabled": True,
            "active_role": "secondary",
            "failure_threshold": 3,
            "probe_interval_seconds": 10,
        }
        with patch.object(ccg_gate.stop_event, "wait", side_effect=lambda _n: next(waits)), \
             patch.object(ccg_gate, "failover_config", return_value=config), \
             patch.object(
                 ccg_gate,
                 "run_guard",
                 side_effect=[
                     (True, "OK"),
                     (True, "OK"),
                     (False, "TimeoutExpired"),
                     (True, "OK"),
                     (False, "TimeoutExpired"),
                     (False, "TimeoutExpired"),
                 ],
             ), \
             patch.object(ccg_gate.time, "monotonic", side_effect=[10, 20, 21, 22]), \
             patch.object(ccg_gate, "close_all_active"):
            ccg_gate.safety_monitor()
        self.assertTrue(ccg_gate.safe_event.is_set())


class GateRoutingTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location(
            "ccg_sample_gate", HERE / "claude-network-gate.py")
        self.gate = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.gate)

    def test_default_suffixes_empty_so_claude_stays_pinned(self):
        with patch.dict(os.environ, {"CCG_RULES_HOST_SUFFIXES": ""}, clear=False):
            os.environ.pop("CCG_RULES_HOST_SUFFIXES", None)
            self.assertFalse(self.gate.uses_clash_rules("api.anthropic.com"))
            self.assertFalse(self.gate.uses_clash_rules("claude.ai"))
            self.assertFalse(self.gate.uses_clash_rules("db.example.com"))

    def test_authorized_suffixes_do_not_match_sibling_domains(self):
        with patch.dict(os.environ, {"CCG_RULES_HOST_SUFFIXES": "example.com,corp.internal"}):
            self.assertTrue(self.gate.uses_clash_rules("db.example.com"))
            self.assertTrue(self.gate.uses_clash_rules("example.com"))
            self.assertFalse(self.gate.uses_clash_rules("evilexample.com"))
            self.assertFalse(self.gate.uses_clash_rules("api.anthropic.com"))


class PackageTests(unittest.TestCase):
    def test_all_python_syntax(self):
        for path in HERE.glob("*.py"):
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    def test_document_links_exist(self):
        for path in [HERE.parent / "SKILL.md", *HERE.parent.glob("references/*.md")]:
            for target in re.findall(r"\]\(([^)]+)\)", path.read_text(encoding="utf-8")):
                if "://" not in target:
                    self.assertTrue((path.parent / target).is_file(), (path, target))


if __name__ == "__main__":
    unittest.main(verbosity=2)
