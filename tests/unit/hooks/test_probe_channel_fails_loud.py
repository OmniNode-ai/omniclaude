# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""A liveness probe that cannot run must not report "not failed" (OMN-15606).

The OMN-15600 fix folded alert-channel liveness into the session-start
hook-health probe. Its wrapper caught every exception — including the import of
``omniclaude.hooks.alert_channel`` itself — and returned the out-of-enum string
``"unknown"``. ``__main__`` only counted ``"dead"``, so the process exited 0,
and ``session-start.sh`` only logged on ``"dead"``, so nothing was written. A
probe that never executed was byte-identical to a probe that ran and found the
channel healthy.

RED at ``3138c2f0e`` (``origin/dev``), by construction:

* ``omniclaude.hooks.lib.hook_health_probe`` — the module ``session-start.sh``
  invokes with ``-m`` — **did not exist at all**. The implementation lived at
  ``plugins/onex/hooks/lib/hook_health_probe.py``, which the wheel does not
  package (``[tool.hatch.build.targets.wheel] packages = ["src/omniclaude"]``)
  and which no ``sys.path`` entry exposes under that dotted name. So every
  test here that runs ``-m`` failed with ``No module named ...`` at the base
  commit: the probe was not merely fail-open, it never ran.
* ``EnumChannelStatus`` had no member for the probe's own failure, so no
  in-enum value could be returned.

These tests bind to the artifact that runs: the ``-m`` module name is read out
of the shell that invokes it, not hardcoded here. Deleting or renaming the
implementation module breaks them (AC-5).
"""

from __future__ import annotations

import ast
import importlib
import importlib.util
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

from omniclaude.hooks.alert_channel import (
    EnumChannelStatus,
    ModelAlertChannelHealth,
    probe_channel_health,
)

_REPO_ROOT = Path(__file__).parents[3]
_SCRIPTS_DIR = _REPO_ROOT / "plugins" / "onex" / "hooks" / "scripts"

# Statuses under which a consumer is entitled to stay silent. Everything else —
# dead, probe_error, or an unrecognised string — must be loud.
_HEALTHY = frozenset({"live", "not_configured"})


def _invoked_probe_module() -> str:
    """Read the ``-m`` module name out of the shell that actually invokes it.

    Binding the test to the invocation string rather than to a literal is what
    makes AC-5 falsifiable: if the shell is pointed at a module that does not
    exist (the state at ``3138c2f0e``), these tests fail.
    """
    pattern = re.compile(r"-m\s+([A-Za-z_][\w.]*hook_health_probe)\b")
    found: set[str] = set()
    for script in sorted(_SCRIPTS_DIR.glob("*.sh")):
        found.update(pattern.findall(script.read_text(encoding="utf-8")))
    assert found, (
        "no hook script invokes a hook_health_probe module with -m; the "
        "session-start probe has been unwired"
    )
    assert len(found) == 1, f"hook scripts invoke divergent probe modules: {found}"
    return found.pop()


@dataclass
class _Run:
    returncode: int
    stdout: str
    stderr: str

    @property
    def payload(self) -> dict[str, object]:
        return json.loads(self.stdout)

    @property
    def channel_status(self) -> str:
        channel = self.payload["alert_channel"]
        assert isinstance(channel, dict)
        return str(channel["status"])


def _write_sitecustomize(directory: Path, body: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "sitecustomize.py").write_text(body, encoding="utf-8")


_BLOCK_IMPORT = """\
import sys


class _BlockAlertChannel:
    def find_spec(self, name, path=None, target=None):
        if name == "omniclaude.hooks.alert_channel":
            raise ImportError("forced: alert_channel unavailable (OMN-15606 test)")
        return None


sys.meta_path.insert(0, _BlockAlertChannel())
"""

_RAISING_PROBE = """\
import omniclaude.hooks.alert_channel as _ac


def _boom(*args, **kwargs):
    raise RuntimeError("forced probe failure (OMN-15606 test)")


_ac.probe_alert_channel = _boom
"""

# Fails *inside* ``probe_alert_channel``'s own try body rather than replacing
# the function. ``_write_cache`` is on the path of every uncached probe,
# including the unconfigured one, so this needs no channel env to be reached —
# and unconfigured is precisely the verdict the un-fixed handler collapsed it
# into. See ``TestProbeAlertChannelOwnBodyFailsLoud``.
_RAISING_INNER_WRITE = """\
import omniclaude.hooks.alert_channel as _ac


def _boom(*args, **kwargs):
    raise OSError("forced: cache write failed inside probe body (OMN-15606 test)")


_ac._write_cache = _boom
"""


@pytest.fixture
def sandbox(tmp_path: Path) -> Path:
    """A HOME the probe can write its cache into without touching the operator's."""
    home = tmp_path / "home"
    (home / ".omnibase").mkdir(parents=True, exist_ok=True)
    return home


def _run_probe(*, home: Path, tmp_path: Path, sitecustomize: str | None = None) -> _Run:
    env = {
        **os.environ,
        "HOME": str(home),
        "ONEX_ALERT_LIVENESS_CACHE": str(tmp_path / "liveness.json"),
        "ONEX_ALERT_DELIVERY_LOG": str(tmp_path / "alert_delivery_failures.log"),
        "ONEX_ALERT_LOCAL_NOTIFY_CMD": str(_noop_notifier(tmp_path)),
        "SLACK_BOT_TOKEN": "",
        "SLACK_CHANNEL_ID": "",
    }
    if sitecustomize is not None:
        inject = tmp_path / "inject"
        _write_sitecustomize(inject, sitecustomize)
        env["PYTHONPATH"] = str(inject)
    else:
        env.pop("PYTHONPATH", None)

    completed = subprocess.run(
        [sys.executable, "-m", _invoked_probe_module()],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(_REPO_ROOT),
        timeout=120,
        check=False,
    )
    return _Run(completed.returncode, completed.stdout, completed.stderr)


def _code_lines(source: str) -> str:
    """Executable lines only — docstrings and comments describe the old defect.

    A prose reference to ``"unknown"`` in the module docstring is not a
    reintroduction of it; a string literal in code would be.
    """
    module = ast.parse(source)
    docstring_lines: set[int] = set()
    for node in ast.walk(module):
        body = getattr(node, "body", None)
        if not isinstance(body, list) or not body:
            continue
        first = body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
            and first.end_lineno is not None
        ):
            docstring_lines.update(range(first.lineno, first.end_lineno + 1))
    kept = [
        line
        for number, line in enumerate(source.splitlines(), start=1)
        if number not in docstring_lines and not line.strip().startswith("#")
    ]
    return "\n".join(kept)


def _noop_notifier(tmp_path: Path) -> Path:
    notifier = tmp_path / "notifier.sh"
    if not notifier.exists():
        notifier.write_text("#!/bin/bash\nexit 0\n", encoding="utf-8")
        notifier.chmod(0o755)
    return notifier


class TestProbeSelfFailureIsNotHealthy:
    """AC-1: probe self-failure is a distinct, non-healthy state."""

    def test_blocked_import_exits_nonzero(self, sandbox: Path, tmp_path: Path) -> None:
        """The ticket's scenario: alert_channel absent from the deployed venv."""
        run = _run_probe(home=sandbox, tmp_path=tmp_path, sitecustomize=_BLOCK_IMPORT)
        assert run.returncode != 0, (
            "a probe that could not import its own dependency exited 0 — "
            f"stdout={run.stdout!r} stderr={run.stderr!r}"
        )
        assert run.channel_status not in _HEALTHY
        assert run.channel_status == EnumChannelStatus.PROBE_ERROR.value

    def test_raising_probe_exits_nonzero(self, sandbox: Path, tmp_path: Path) -> None:
        run = _run_probe(home=sandbox, tmp_path=tmp_path, sitecustomize=_RAISING_PROBE)
        assert run.returncode != 0, (
            f"a raising probe exited 0 — stdout={run.stdout!r} stderr={run.stderr!r}"
        )
        assert run.channel_status == EnumChannelStatus.PROBE_ERROR.value

    def test_probe_failure_is_counted_as_a_failure(
        self, sandbox: Path, tmp_path: Path
    ) -> None:
        """The reported failure count is the number session-start branches on."""
        run = _run_probe(home=sandbox, tmp_path=tmp_path, sitecustomize=_BLOCK_IMPORT)
        assert int(run.payload["failures"]) >= 1  # type: ignore[arg-type]

    def test_unconfigured_channel_still_exits_zero(
        self, sandbox: Path, tmp_path: Path
    ) -> None:
        """Guard against over-correction: unset is quiet, it is not a failure."""
        run = _run_probe(home=sandbox, tmp_path=tmp_path)
        assert run.channel_status == EnumChannelStatus.NOT_CONFIGURED.value
        assert run.returncode == 0, f"stdout={run.stdout!r} stderr={run.stderr!r}"


class TestHandlerListIsReal:
    """A probe that always fails is a probe the operator learns to ignore."""

    def test_every_listed_handler_is_importable(self) -> None:
        """``HOOK_HANDLERS`` must not name modules that do not exist.

        ``omniclaude.hooks.handlers.dod_completion_guard`` was listed here and
        never importable, which would have made the probe report a permanent
        failure the moment the ``-m`` invocation was repaired.
        """
        module = importlib.import_module(_invoked_probe_module())
        unimportable = []
        for handler in module.HOOK_HANDLERS:
            try:
                importlib.import_module(handler)
            except ImportError as exc:  # noqa: PERF203 — per-entry attribution
                unimportable.append(f"{handler}: {exc}")
        assert not unimportable, (
            f"HOOK_HANDLERS names modules that do not exist: {unimportable}"
        )

    def test_handler_list_is_not_empty(self) -> None:
        module = importlib.import_module(_invoked_probe_module())
        assert module.HOOK_HANDLERS, "the handler-import half of the probe is a no-op"


class TestStatusVocabularyIsTyped:
    """AC-2: the status is drawn from the enum, not invented as a string."""

    def test_probe_error_is_a_declared_enum_member(self) -> None:
        assert "probe_error" in {member.value for member in EnumChannelStatus}

    def test_unknown_is_not_a_declared_member(self) -> None:
        assert "unknown" not in {member.value for member in EnumChannelStatus}

    def test_probe_error_is_not_healthy(self) -> None:
        health = ModelAlertChannelHealth(status=EnumChannelStatus.PROBE_ERROR)
        assert health.healthy is False

    @pytest.mark.parametrize("sitecustomize", [_BLOCK_IMPORT, _RAISING_PROBE, None])
    def test_reported_status_is_always_in_enum(
        self, sandbox: Path, tmp_path: Path, sitecustomize: str | None
    ) -> None:
        run = _run_probe(home=sandbox, tmp_path=tmp_path, sitecustomize=sitecustomize)
        assert run.channel_status in {member.value for member in EnumChannelStatus}

    def test_import_free_fallback_string_matches_the_enum(self) -> None:
        """The lib probe must name probe_error without importing the enum.

        It reports ``probe_error`` in exactly the case where
        ``omniclaude.hooks.alert_channel`` cannot be imported, so it cannot
        read the value off the enum at that moment. This asserts the literal it
        falls back to has not drifted from the declaration.
        """
        module = __import__(_invoked_probe_module(), fromlist=["_PROBE_ERROR_STATUS"])
        assert EnumChannelStatus.PROBE_ERROR.value == module._PROBE_ERROR_STATUS
        assert set(module.HEALTHY_CHANNEL_STATUSES) == _HEALTHY


class TestTheTwoProbesAgree:
    """AC-4: the plugin-lib probe and the src sibling classify identically."""

    def test_raising_probe_classified_identically(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        import omniclaude.hooks.alert_channel as alert_channel
        from omniclaude.hooks.hook_health_probe import probe_hook_health

        lib_probe = __import__(_invoked_probe_module(), fromlist=["probe_channel"])

        def _boom(*_args: object, **_kwargs: object) -> ModelAlertChannelHealth:
            raise RuntimeError("forced probe failure (OMN-15606 test)")

        monkeypatch.setattr(alert_channel, "probe_alert_channel", _boom)
        monkeypatch.setenv("ONEX_ALERT_LIVENESS_CACHE", str(tmp_path / "cache.json"))

        lib_status = str(lib_probe.probe_channel()["status"])
        src_status = str(probe_hook_health().alert_channel_status)

        assert lib_status == src_status, (
            f"the two hook-health probes disagree: lib={lib_status!r} "
            f"src={src_status!r}"
        )
        assert lib_status == EnumChannelStatus.PROBE_ERROR.value

    def test_src_probe_is_unhealthy_on_probe_error(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        import omniclaude.hooks.alert_channel as alert_channel
        from omniclaude.hooks.hook_health_probe import probe_hook_health

        def _boom(*_args: object, **_kwargs: object) -> ModelAlertChannelHealth:
            raise RuntimeError("forced probe failure (OMN-15606 test)")

        monkeypatch.setattr(alert_channel, "probe_alert_channel", _boom)
        monkeypatch.setenv("ONEX_ALERT_LIVENESS_CACHE", str(tmp_path / "cache.json"))

        result = probe_hook_health()
        assert result.alert_channel_status == EnumChannelStatus.PROBE_ERROR.value
        assert result.healthy is False
        assert any("LIVENESS UNVERIFIED" in warning for warning in result.warnings)


class TestSharedClassifier:
    """One implementation, not two: both probes route through this helper."""

    def test_probe_channel_health_never_raises(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        import omniclaude.hooks.alert_channel as alert_channel

        def _boom(*_args: object, **_kwargs: object) -> ModelAlertChannelHealth:
            raise RuntimeError("forced probe failure (OMN-15606 test)")

        monkeypatch.setattr(alert_channel, "probe_alert_channel", _boom)
        monkeypatch.setenv("ONEX_ALERT_LIVENESS_CACHE", str(tmp_path / "cache.json"))

        health = probe_channel_health()
        assert health.status is EnumChannelStatus.PROBE_ERROR
        assert health.healthy is False
        assert "forced probe failure" in health.detail

    def test_plugin_copy_carries_no_independent_logic(self) -> None:
        """AC-4/AC-5: the plugin-lib file delegates, it does not reimplement.

        Two copies that can drift is the defect. The file-path entry point is
        retained (callers exec it directly) but must import its behaviour.
        """
        source = (
            _REPO_ROOT / "plugins" / "onex" / "hooks" / "lib" / "hook_health_probe.py"
        ).read_text(encoding="utf-8")
        assert f"from {_invoked_probe_module()} import" in source, (
            "the plugin-lib probe does not delegate to the module session-start "
            "invokes — the two can diverge again"
        )
        code = _code_lines(source)
        assert "except Exception" not in code, (
            "the plugin-lib delegate reintroduced its own exception handling"
        )
        assert "unknown" not in code, (
            "the out-of-enum status this ticket removes reappeared in the "
            "delegate's executable code"
        )


class TestProbeAlertChannelOwnBodyFailsLoud:
    """The third fail-open: the guard inside ``probe_alert_channel`` itself.

    Every other test in this file forces the failure *outside*
    ``probe_alert_channel``. ``_BLOCK_IMPORT`` stops the module importing, which
    lands in ``probe_channel``'s handler; ``_RAISING_PROBE`` and the
    ``monkeypatch.setattr(..., "probe_alert_channel", _boom)`` fixtures replace
    the function wholesale, which lands in ``probe_channel_health``'s. None of
    them executes a single line of ``probe_alert_channel``'s own ``try`` body,
    so its ``except`` was asserted by nothing.

    Measured, not assumed: reverting that one line to ``NOT_CONFIGURED`` — the
    exact pre-OMN-15606 shape — left all 33 tests green. The mutant is
    behaviourally reachable (any exception escaping ``_probe_bot_token`` or ``_write_cache``: TLS, DNS, a read-only cache dir) and
    material: ``not_configured`` is silent and exits 0, ``probe_error`` is loud
    and exits 1. These tests bind that line.
    """

    def test_raising_bot_token_probe_is_probe_error(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """A TLS/DNS failure while probing Slack is UNVERIFIED, not "unset"."""
        import omniclaude.hooks.alert_channel as alert_channel

        def _boom(_token: str) -> tuple[bool, str]:
            raise OSError("forced: TLS handshake failed (OMN-15606 test)")

        monkeypatch.setattr(alert_channel, "_probe_bot_token", _boom)
        monkeypatch.setenv("ONEX_ALERT_LIVENESS_CACHE", str(tmp_path / "cache.json"))
        # Non-secret placeholders: the probe only tests these for truthiness
        # before entering the bot-token branch.
        monkeypatch.setenv("SLACK_BOT_TOKEN", "forced-test-value-not-a-credential")
        monkeypatch.setenv("SLACK_CHANNEL_ID", "forced-test-channel")

        health = alert_channel.probe_alert_channel(force=True)

        assert health.status is EnumChannelStatus.PROBE_ERROR, (
            "an exception raised inside probe_alert_channel's own body was "
            f"reported as {health.status.value!r}; a probe that could not run "
            "must never be indistinguishable from a healthy or unset channel"
        )
        assert health.healthy is False

    def test_raising_cache_write_is_not_reported_as_unconfigured(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """The collision case: the un-fixed handler returned the same verdict.

        With no channel configured the probe legitimately returns
        ``not_configured``. If the handler also returns ``not_configured`` when
        it *crashed*, the two are byte-identical and the operator cannot tell
        "nothing to check" from "could not check" — the whole defect class.
        """
        import omniclaude.hooks.alert_channel as alert_channel

        def _boom(_result: object) -> None:
            raise OSError("forced: cache write failed (OMN-15606 test)")

        monkeypatch.setattr(alert_channel, "_write_cache", _boom)
        monkeypatch.setenv("ONEX_ALERT_LIVENESS_CACHE", str(tmp_path / "cache.json"))
        monkeypatch.setenv("SLACK_BOT_TOKEN", "")
        monkeypatch.setenv("SLACK_CHANNEL_ID", "")

        health = alert_channel.probe_alert_channel(force=True)

        assert health.status is not EnumChannelStatus.NOT_CONFIGURED, (
            "a crashed probe reported not_configured — indistinguishable from "
            "the legitimate unset verdict, which is silent and exits 0"
        )
        assert health.status is EnumChannelStatus.PROBE_ERROR
        assert health.healthy is False

    def test_inner_failure_exits_nonzero_through_the_invoked_module(
        self, sandbox: Path, tmp_path: Path
    ) -> None:
        """End-to-end on the artifact that runs, not on an in-process import.

        Same forcing, driven through ``-m <the module session-start invokes>``:
        the observable the shell consumer branches on is the exit code, and an
        unconfigured channel exits 0, so this fails if the handler collapses an
        inner crash back into ``not_configured``.
        """
        run = _run_probe(
            home=sandbox, tmp_path=tmp_path, sitecustomize=_RAISING_INNER_WRITE
        )
        assert run.channel_status == EnumChannelStatus.PROBE_ERROR.value, (
            f"status={run.channel_status!r} stdout={run.stdout!r} stderr={run.stderr!r}"
        )
        assert run.returncode != 0, (
            "a probe that crashed inside its own body exited 0 — the shell "
            f"consumer stays silent on that; stdout={run.stdout!r}"
        )
        assert int(run.payload["failures"]) >= 1  # type: ignore[arg-type]


class TestInvokedModuleActuallyResolves:
    """Makes the contract's DoD check non-vacuous.

    ``contracts/OMN-15606.yaml`` verified this ticket by running
    ``python -m omniclaude.hooks.lib.hook_health_probe`` and accepting a
    returncode in ``(0, 1)``. A missing module exits **1**, so the check passed
    against the exact broken tree the ticket was filed about — the same vacuity
    class as the grep the ticket explicitly forbade, reached through exit-code
    width instead of substring width. The contract now runs these assertions.
    """

    def test_invoked_module_has_an_import_spec(self) -> None:
        """RED at ``3138c2f0e``: the module did not exist at all."""
        module = _invoked_probe_module()
        assert importlib.util.find_spec(module) is not None, (
            f"{module} is invoked by a hook script with -m but has no import "
            "spec; `python -m` on it exits 1, which a returncode-width check "
            "silently accepts as success"
        )

    def test_running_the_invoked_module_emits_an_in_enum_status(
        self, sandbox: Path, tmp_path: Path
    ) -> None:
        """Executing it must yield a parseable payload, not a traceback."""
        run = _run_probe(home=sandbox, tmp_path=tmp_path)
        assert run.returncode in (0, 1), (
            f"unexpected returncode {run.returncode}; stderr={run.stderr!r}"
        )
        assert "No module named" not in run.stderr, (
            f"the invoked module did not resolve: {run.stderr!r}"
        )
        assert run.channel_status in {member.value for member in EnumChannelStatus}
