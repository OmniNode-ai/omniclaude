# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for HookPolicy — reusable approval-gating abstraction."""

from __future__ import annotations

import importlib.util
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import pytest

_LIB_DIR = (
    pathlib.Path(__file__).parent.parent.parent / "plugins" / "onex" / "hooks" / "lib"
)
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

import hook_policy  # noqa: E402


class TestEnforcementMode(unittest.TestCase):
    def test_hard(self) -> None:
        self.assertEqual(hook_policy.EnforcementMode.HARD.value, "hard")

    def test_soft(self) -> None:
        self.assertEqual(hook_policy.EnforcementMode.SOFT.value, "soft")

    def test_advisory(self) -> None:
        self.assertEqual(hook_policy.EnforcementMode.ADVISORY.value, "advisory")

    def test_disabled(self) -> None:
        self.assertEqual(hook_policy.EnforcementMode.DISABLED.value, "disabled")


class TestApprovalChannel(unittest.TestCase):
    def test_terminal(self) -> None:
        self.assertEqual(hook_policy.ApprovalChannel.TERMINAL.value, "terminal")

    def test_chat(self) -> None:
        self.assertEqual(hook_policy.ApprovalChannel.CHAT.value, "chat")

    def test_slack_poll(self) -> None:
        self.assertEqual(hook_policy.ApprovalChannel.SLACK_POLL.value, "slack_poll")


class TestFlagFilePath(unittest.TestCase):
    def test_path_format(self) -> None:
        # First 12 chars of session_id used as prefix
        p = hook_policy.HookPolicy(name="no_verify").flag_file_path("abc123456789-rest")
        self.assertEqual(p, pathlib.Path("/tmp/onex-allow-no_verify-abc123456789.flag"))

    def test_uses_first_12_chars(self) -> None:
        p = hook_policy.HookPolicy(name="no_verify").flag_file_path("XYZWABCD1234-more")
        self.assertIn("XYZWABCD1234", str(p))

    def test_short_session_id(self) -> None:
        # session_id shorter than 12 chars uses what is available
        p = hook_policy.HookPolicy(name="no_verify").flag_file_path("abc")
        self.assertEqual(p, pathlib.Path("/tmp/onex-allow-no_verify-abc.flag"))


class TestFlagFileOverride(unittest.TestCase):
    def test_false_when_missing(self) -> None:
        policy = hook_policy.HookPolicy(name="no_verify")
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(hook_policy, "_FLAG_DIR", tmp):
                self.assertFalse(policy.is_override_active("no-such-session"))

    def test_true_when_flag_exists(self) -> None:
        policy = hook_policy.HookPolicy(name="no_verify")
        with tempfile.TemporaryDirectory() as tmp:
            (pathlib.Path(tmp) / "onex-allow-no_verify-abcdef123456.flag").write_text(
                "ok\n"
            )
            with patch.object(hook_policy, "_FLAG_DIR", tmp):
                self.assertTrue(policy.is_override_active("abcdef123456-rest"))

    def test_flag_consumed_after_read(self) -> None:
        policy = hook_policy.HookPolicy(name="no_verify", consume_flag=True)
        with tempfile.TemporaryDirectory() as tmp:
            flag = pathlib.Path(tmp) / "onex-allow-no_verify-abcdef123456.flag"
            flag.write_text("ok\n")
            with patch.object(hook_policy, "_FLAG_DIR", tmp):
                result = policy.is_override_active("abcdef123456-rest")
            self.assertTrue(result)
            self.assertFalse(flag.exists())  # consumed


class TestFromConfig(unittest.TestCase):
    def test_defaults_hard_when_missing(self) -> None:
        p = hook_policy.HookPolicy.from_config({}, "no_verify")
        self.assertEqual(p.mode, hook_policy.EnforcementMode.HARD)

    def test_reads_soft_mode_and_terminal_channel(self) -> None:
        cfg = {"hook_policies": {"no_verify": {"mode": "soft", "channel": "terminal"}}}
        p = hook_policy.HookPolicy.from_config(cfg, "no_verify")
        self.assertEqual(p.mode, hook_policy.EnforcementMode.SOFT)
        self.assertEqual(p.channel, hook_policy.ApprovalChannel.TERMINAL)

    def test_invalid_mode_defaults_hard(self) -> None:
        cfg = {"hook_policies": {"no_verify": {"mode": "bogus"}}}
        p = hook_policy.HookPolicy.from_config(cfg, "no_verify")
        self.assertEqual(p.mode, hook_policy.EnforcementMode.HARD)

    def test_invalid_channel_defaults_terminal(self) -> None:
        cfg = {"hook_policies": {"no_verify": {"mode": "soft", "channel": "bogus"}}}
        p = hook_policy.HookPolicy.from_config(cfg, "no_verify")
        self.assertEqual(p.channel, hook_policy.ApprovalChannel.TERMINAL)

    def test_missing_channel_defaults_terminal(self) -> None:
        cfg = {"hook_policies": {"no_verify": {"mode": "soft"}}}
        p = hook_policy.HookPolicy.from_config(cfg, "no_verify")
        self.assertEqual(p.channel, hook_policy.ApprovalChannel.TERMINAL)

    def test_disabled_mode(self) -> None:
        cfg = {"hook_policies": {"no_verify": {"mode": "disabled"}}}
        p = hook_policy.HookPolicy.from_config(cfg, "no_verify")
        self.assertEqual(p.mode, hook_policy.EnforcementMode.DISABLED)

    def test_malformed_hook_policies_type_fails_closed(self) -> None:
        # hook_policies is a list, not a dict — must fail to HARD
        p = hook_policy.HookPolicy.from_config({"hook_policies": ["oops"]}, "no_verify")
        self.assertEqual(p.mode, hook_policy.EnforcementMode.HARD)

    def test_malformed_policy_entry_type_fails_closed(self) -> None:
        # policy entry is a string, not a dict
        p = hook_policy.HookPolicy.from_config(
            {"hook_policies": {"no_verify": "bad"}}, "no_verify"
        )
        self.assertEqual(p.mode, hook_policy.EnforcementMode.HARD)

    def test_list_mode_value_fails_closed(self) -> None:
        # mode is a list — coerced via str() → fails enum lookup → HARD
        p = hook_policy.HookPolicy.from_config(
            {"hook_policies": {"no_verify": {"mode": []}}}, "no_verify"
        )
        self.assertEqual(p.mode, hook_policy.EnforcementMode.HARD)

    def test_dict_channel_value_defaults_terminal(self) -> None:
        # channel is a dict — coerced via str() → fails enum lookup → TERMINAL
        p = hook_policy.HookPolicy.from_config(
            {"hook_policies": {"no_verify": {"mode": "soft", "channel": {"bad": 1}}}},
            "no_verify",
        )
        self.assertEqual(p.channel, hook_policy.ApprovalChannel.TERMINAL)


class TestLoadConfig(unittest.TestCase):
    def test_returns_empty_dict_when_file_missing(self) -> None:
        with patch(
            "hook_policy._CONFIG_PATH", pathlib.Path("/nonexistent/config.yaml")
        ):
            cfg = hook_policy.load_config()
        self.assertIsInstance(cfg, dict)
        self.assertEqual(cfg, {})

    def test_returns_empty_dict_on_invalid_yaml(self) -> None:
        import tempfile as _tmp

        with _tmp.NamedTemporaryFile(suffix=".yaml", mode="w", delete=False) as f:
            f.write(":::: not yaml ::::\n")
            bad = pathlib.Path(f.name)
        with patch("hook_policy._CONFIG_PATH", bad):
            cfg = hook_policy.load_config()
        bad.unlink()
        self.assertEqual(cfg, {})

    def test_returns_empty_dict_when_pyyaml_absent(self) -> None:
        import sys as _sys

        with patch.dict(_sys.modules, {"yaml": None}):
            with patch("hook_policy._CONFIG_PATH", pathlib.Path("/nonexistent/x.yaml")):
                cfg = hook_policy.load_config()
        self.assertEqual(cfg, {})


class TestTerminalCommand(unittest.TestCase):
    def test_includes_session_prefix(self) -> None:
        cmd = hook_policy.HookPolicy(name="no_verify").terminal_command(
            "abcdef123456-xyz"
        )
        self.assertIn("abcdef123456", cmd)
        self.assertIn("allow-no-verify", cmd)

    def test_includes_reason(self) -> None:
        cmd = hook_policy.HookPolicy(name="no_verify").terminal_command(
            "abcdef123456-xyz", reason="CI failure"
        )
        self.assertIn("CI failure", cmd)


# ---------------------------------------------------------------------------
# allow_flag.py CLI tests (Task 2)
# ---------------------------------------------------------------------------


class TestAllowFlagCLI(unittest.TestCase):
    _SCRIPT = _LIB_DIR / "allow_flag.py"

    def test_creates_flag_file_via_hook_policy(self) -> None:
        """allow_flag.py must delegate to HookPolicy.create_flag(), not duplicate logic."""
        with tempfile.TemporaryDirectory() as tmp:
            r = subprocess.run(
                [
                    sys.executable,
                    str(self._SCRIPT),
                    "--policy",
                    "no_verify",
                    "--session-prefix",
                    "abcdef123456",
                    "--reason",
                    "urgent hotfix",
                    "--flag-dir",
                    tmp,
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(r.returncode, 0, msg=r.stderr)
            # Path must match HookPolicy.flag_file_path() semantics exactly
            flag = pathlib.Path(tmp) / "onex-allow-no_verify-abcdef123456.flag"
            self.assertTrue(flag.exists(), msg="flag file not created at expected path")
            self.assertIn("urgent hotfix", flag.read_text())

    def test_exits_1_without_required_args(self) -> None:
        r = subprocess.run(
            [sys.executable, str(self._SCRIPT)], capture_output=True, check=False
        )
        self.assertNotEqual(r.returncode, 0)

    def test_output_confirms_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            r = subprocess.run(
                [
                    sys.executable,
                    str(self._SCRIPT),
                    "--policy",
                    "no_verify",
                    "--session-prefix",
                    "abcdef123456",
                    "--reason",
                    "test",
                    "--flag-dir",
                    tmp,
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertIn("onex-allow-no_verify-abcdef123456.flag", r.stdout)


# ---------------------------------------------------------------------------
# slack_approval_listener.py stub tests (Task 3)
# ---------------------------------------------------------------------------


class TestSlackApprovalListenerStub(unittest.TestCase):
    def _import(self) -> object:
        spec = importlib.util.spec_from_file_location(
            "slack_approval_listener", _LIB_DIR / "slack_approval_listener.py"
        )
        assert spec is not None
        mod = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        return mod

    def test_importable(self) -> None:
        mod = self._import()
        self.assertTrue(hasattr(mod, "SlackApprovalListener"))

    def test_start_raises_not_implemented(self) -> None:
        mod = self._import()
        with pytest.raises(NotImplementedError):
            mod.SlackApprovalListener(policy="no_verify", channel_id="C123").start()  # type: ignore[union-attr]

    def test_not_implemented_message_mentions_follow_up(self) -> None:
        mod = self._import()
        try:
            mod.SlackApprovalListener(policy="no_verify", channel_id="C123").start()  # type: ignore[union-attr]
        except NotImplementedError as e:
            self.assertIn("follow-up", str(e).lower())


# ---------------------------------------------------------------------------
# config.yaml integration tests (Task 4)
# ---------------------------------------------------------------------------


class TestConfigYamlHasPolicies(unittest.TestCase):
    """Integration test against actual config.yaml on disk."""

    def test_hook_policies_key_exists(self) -> None:
        cfg = hook_policy.load_config()
        self.assertIn(
            "hook_policies",
            cfg,
            msg="config.yaml must have 'hook_policies' top-level key",
        )

    def test_no_verify_policy_exists(self) -> None:
        cfg = hook_policy.load_config()
        self.assertIn("no_verify", cfg.get("hook_policies", {}))

    def test_no_verify_mode_is_valid_enum_value(self) -> None:
        cfg = hook_policy.load_config()
        raw_mode = cfg["hook_policies"]["no_verify"].get("mode", "hard")
        valid = {m.value for m in hook_policy.EnforcementMode}
        self.assertIn(raw_mode, valid)

    def test_no_verify_channel_is_valid_enum_value(self) -> None:
        cfg = hook_policy.load_config()
        raw_channel = cfg["hook_policies"]["no_verify"].get("channel", "terminal")
        valid = {c.value for c in hook_policy.ApprovalChannel}
        self.assertIn(raw_channel, valid)


# ---------------------------------------------------------------------------
# pytest markers — wrap all test classes
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestEnforcementModeUnit(TestEnforcementMode):
    pass


@pytest.mark.unit
class TestApprovalChannelUnit(TestApprovalChannel):
    pass


@pytest.mark.unit
class TestFlagFilePathUnit(TestFlagFilePath):
    pass


@pytest.mark.unit
class TestFlagFileOverrideUnit(TestFlagFileOverride):
    pass


@pytest.mark.unit
class TestFromConfigUnit(TestFromConfig):
    pass


@pytest.mark.unit
class TestLoadConfigUnit(TestLoadConfig):
    pass


@pytest.mark.unit
class TestTerminalCommandUnit(TestTerminalCommand):
    pass


@pytest.mark.unit
class TestAllowFlagCLIUnit(TestAllowFlagCLI):
    pass


@pytest.mark.unit
class TestSlackApprovalListenerStubUnit(TestSlackApprovalListenerStub):
    pass


@pytest.mark.unit
class TestConfigYamlHasPoliciesUnit(TestConfigYamlHasPolicies):
    pass


if __name__ == "__main__":
    unittest.main()
