#!/usr/bin/env python3
"""Offline regression tests: temporary fixtures and mocked sockets only."""

from __future__ import annotations

import ast
import contextlib
import io
import json
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
