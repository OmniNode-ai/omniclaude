# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""session-start must not collapse "probe broken" into "channel fine" (OMN-15606).

AC-3 of the ticket. At ``3138c2f0e`` the consumption block was:

.. code-block:: sh

   PROBE_RESULT=$("$PYTHON_CMD" -m omniclaude.hooks.lib.hook_health_probe ...) || true
   PROBE_CHANNEL=$(... .get('alert_channel',{}).get('status','unknown')" 2>/dev/null || echo "unknown")
   if [[ "$PROBE_CHANNEL" == "dead" ]]; then ... ERROR ...

Four distinct conditions — probe crashed, probe emitted malformed JSON, probe
reported a status this shell does not recognise, and channel healthy — all
produced the same value and the same silence. These tests drive the real
consumption path and assert each condition produces its own non-silent line.

The consumption logic now lives in ``common.sh :: run_hook_health_probe`` so
this test can source and call the function that session-start calls, rather
than a re-implementation of it (``feedback_test_the_artifact_that_runs``). A
companion assertion pins session-start to that same function.

RED at ``3138c2f0e``: ``run_hook_health_probe`` did not exist, so every case
below failed with "command not found".
"""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).parents[4]
_PLUGIN_ROOT = _REPO_ROOT / "plugins" / "onex"
_SCRIPTS_DIR = _PLUGIN_ROOT / "hooks" / "scripts"

_DRIVER = """\
set -uo pipefail
source "${PLUGIN_ROOT}/hooks/scripts/common.sh"
run_hook_health_probe
echo "rc=$?"
"""


def _fake_probe(tmp_path: Path, *, stdout: str, exit_code: int = 0) -> Path:
    """A stand-in *interpreter* that scripts the ``-m`` probe outcome.

    ``run_hook_health_probe`` uses ``$PYTHON_CMD`` twice: once as
    ``-m <probe module>`` and again as ``-c <json expression>`` to read the
    verdict out of the payload. This stand-in must therefore behave like an
    interpreter for BOTH forms — ``-m`` emits the scripted payload, ``-c``
    delegates to the real interpreter.

    An earlier version answered every invocation with the payload. It passed on
    macOS only because the JSON parse there ran on ``$BREW_PY`` rather than on
    this stub, and failed on Linux CI where ``$BREW_PY`` does not exist — the
    stub then "parsed" the payload with itself and every outcome collapsed into
    ``unreadable``. A test fixture that is only faithful on one host produces
    exactly the environment-dependent green this ticket is about.
    """
    script = tmp_path / "fake_probe.sh"
    script.write_text(
        "#!/bin/bash\n"
        "# Interpreter stand-in: -m is the scripted probe, -c is a real parse.\n"
        'if [[ "$1" == "-c" ]]; then\n'
        f'    exec {shlex.quote(sys.executable)} "$@"\n'
        "fi\n"
        f"cat <<'PROBE_EOF'\n{stdout}\nPROBE_EOF\n"
        f"exit {exit_code}\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    return script


def _run(tmp_path: Path, probe: Path) -> subprocess.CompletedProcess[str]:
    fake_home = tmp_path / "home"
    (fake_home / ".omnibase").mkdir(parents=True, exist_ok=True)
    log_file = tmp_path / "hooks.log"
    log_file.touch()
    env = {
        **os.environ,
        "HOME": str(fake_home),
        "PLUGIN_ROOT": str(_PLUGIN_ROOT),
        "PROJECT_ROOT": "",
        "LOG_FILE": str(log_file),
        "OMNICLAUDE_MODE": "full",
        "PLUGIN_PYTHON_BIN": str(probe),
        "SLACK_WEBHOOK_URL": "",
        "SLACK_BOT_TOKEN": "",
        "SLACK_CHANNEL_ID": "",
    }
    return subprocess.run(
        ["bash", "-c", _DRIVER],
        capture_output=True,
        text=True,
        env=env,
        timeout=90,
        check=False,
    )


def _log(tmp_path: Path) -> str:
    return (tmp_path / "hooks.log").read_text(encoding="utf-8")


def _verdict_lines(tmp_path: Path) -> list[str]:
    """The probe-verdict lines only, timestamps and tmp paths stripped.

    ``common.sh`` writes an unrelated "Resolved python: <path>" line on source,
    and that path differs per test directory. Comparing whole logs would let
    two identical verdicts look distinct — a vacuous discriminator. Only
    WARNING/ERROR verdict lines are compared.
    """
    lines = []
    for raw in _log(tmp_path).splitlines():
        body = raw.split("] ", 1)[-1]
        if body.startswith(("WARNING:", "ERROR:")):
            lines.append(body.replace(str(tmp_path), "<TMP>"))
    return lines


_HEALTHY_PAYLOAD = (
    '{"hook_health": [], "alert_channel": {"status": "live"}, "failures": 0}'
)
_NOT_CONFIGURED_PAYLOAD = (
    '{"hook_health": [], "alert_channel": {"status": "not_configured"}, "failures": 0}'
)
_DEAD_PAYLOAD = (
    '{"hook_health": [], "alert_channel": {"status": "dead"}, "failures": 1}'
)
_PROBE_ERROR_PAYLOAD = (
    '{"hook_health": [], "alert_channel": {"status": "probe_error",'
    ' "error": "No module named omniclaude.hooks.alert_channel"}, "failures": 1}'
)
_OUT_OF_ENUM_PAYLOAD = (
    '{"hook_health": [], "alert_channel": {"status": "unknown"}, "failures": 0}'
)


class TestEachFailureModeIsLoudAndDistinct:
    def test_malformed_json_is_reported(self, tmp_path: Path) -> None:
        probe = _fake_probe(tmp_path, stdout="not json at all", exit_code=1)
        result = _run(tmp_path, probe)
        log = _log(tmp_path)
        assert "rc=1" in result.stdout, result.stdout
        assert "unreadable" in log.lower(), log

    def test_empty_output_is_reported(self, tmp_path: Path) -> None:
        """The probe crashing before it prints anything is the common case."""
        probe = _fake_probe(tmp_path, stdout="", exit_code=1)
        result = _run(tmp_path, probe)
        assert "rc=1" in result.stdout, result.stdout
        assert "unreadable" in _log(tmp_path).lower()

    def test_probe_error_status_is_reported(self, tmp_path: Path) -> None:
        probe = _fake_probe(tmp_path, stdout=_PROBE_ERROR_PAYLOAD, exit_code=1)
        result = _run(tmp_path, probe)
        log = _log(tmp_path)
        assert "rc=1" in result.stdout, result.stdout
        assert "UNVERIFIED" in log, log

    def test_dead_status_is_reported(self, tmp_path: Path) -> None:
        probe = _fake_probe(tmp_path, stdout=_DEAD_PAYLOAD, exit_code=1)
        result = _run(tmp_path, probe)
        log = _log(tmp_path)
        assert "rc=1" in result.stdout, result.stdout
        assert "DEAD" in log, log

    def test_out_of_enum_status_is_reported(self, tmp_path: Path) -> None:
        """A status this shell does not recognise is unverified, not healthy.

        ``unknown`` is the exact value the pre-fix probe emitted; if it ever
        reappears from any producer, the consumer must be loud about it.
        """
        probe = _fake_probe(tmp_path, stdout=_OUT_OF_ENUM_PAYLOAD, exit_code=0)
        result = _run(tmp_path, probe)
        log = _log(tmp_path)
        assert "rc=1" in result.stdout, result.stdout
        assert "unknown" in log, log

    @pytest.mark.parametrize(
        ("left", "right"),
        [
            ("not json at all", _PROBE_ERROR_PAYLOAD),
            (_PROBE_ERROR_PAYLOAD, _NOT_CONFIGURED_PAYLOAD),
            (_PROBE_ERROR_PAYLOAD, _DEAD_PAYLOAD),
            (_OUT_OF_ENUM_PAYLOAD, _PROBE_ERROR_PAYLOAD),
        ],
    )
    def test_the_log_lines_differ(self, tmp_path: Path, left: str, right: str) -> None:
        """AC-3: the cases must be distinguishable from each other."""
        left_dir = tmp_path / "left"
        right_dir = tmp_path / "right"
        left_dir.mkdir()
        right_dir.mkdir()
        _run(left_dir, _fake_probe(left_dir, stdout=left, exit_code=1))
        _run(right_dir, _fake_probe(right_dir, stdout=right, exit_code=1))
        left_lines = _verdict_lines(left_dir)
        right_lines = _verdict_lines(right_dir)
        # A healthy outcome is legitimately silent; a failing one never is.
        assert left_lines or right_lines, (
            f"neither outcome logged a verdict: {left!r} / {right!r}"
        )
        assert left_lines != right_lines, (
            f"two distinct probe outcomes produced the same verdict: {left_lines}"
        )


class TestHealthyPathStaysQuiet:
    @pytest.mark.parametrize("payload", [_HEALTHY_PAYLOAD, _NOT_CONFIGURED_PAYLOAD])
    def test_no_error_line_and_rc_zero(self, tmp_path: Path, payload: str) -> None:
        probe = _fake_probe(tmp_path, stdout=payload, exit_code=0)
        result = _run(tmp_path, probe)
        assert "rc=0" in result.stdout, f"{result.stdout!r} {result.stderr!r}"
        assert "ERROR" not in _log(tmp_path)
        assert not _verdict_lines(tmp_path), _log(tmp_path)


class TestDegradedChannelIsSurfaced:
    """A dead secondary masked by a live primary must not be silent.

    Alerting still works, so this is a WARNING and not a failure — but the dead
    webhook delivers nothing, and if the live channel later lapses it is all
    that is left. This is the live state on the operator's machine today:
    ``bot_token=ok; webhook=HTTP_404 no_service``.
    """

    _DEGRADED = (
        '{"hook_health": [], "alert_channel": {"status": "live",'
        ' "live_channels": ["bot_token"], "dead_channels": ["webhook"]},'
        ' "failures": 0}'
    )

    def test_dead_secondary_is_reported_without_failing(self, tmp_path: Path) -> None:
        probe = _fake_probe(tmp_path, stdout=self._DEGRADED, exit_code=0)
        result = _run(tmp_path, probe)
        log = _log(tmp_path)
        assert "rc=0" in result.stdout, f"{result.stdout!r} {result.stderr!r}"
        assert "degraded" in log, log
        assert "webhook" in log, log
        assert "ERROR" not in log, log


class TestSessionStartUsesTheSharedFunction:
    """The tested function must be the one session-start actually calls."""

    def test_session_start_delegates_to_run_hook_health_probe(self) -> None:
        source = (_SCRIPTS_DIR / "session-start.sh").read_text(encoding="utf-8")
        assert "run_hook_health_probe" in source, (
            "session-start.sh no longer routes through the tested consumption "
            "function — this suite would be testing a surrogate"
        )

    def test_no_script_defaults_the_channel_status_to_unknown(self) -> None:
        """The fail-open default this ticket removes must not come back.

        Scoped to the alert-channel extraction: ``session-start.sh`` uses
        ``|| echo "unknown"`` elsewhere for unrelated diagnostics (the stdin
        key list), and banning the token outright would be a matcher too broad
        to survive.
        """
        offenders = []
        for script in sorted(_SCRIPTS_DIR.glob("*.sh")):
            text = script.read_text(encoding="utf-8")
            for line in text.splitlines():
                if "alert_channel" in line and "unknown" in line:
                    offenders.append(f"{script.name}: {line.strip()}")
        assert not offenders, (
            f"alert-channel status still defaults to a fail-open value: {offenders}"
        )

    def test_no_script_branches_on_dead_alone(self) -> None:
        """Branching only on 'dead' is what made probe_error read as healthy."""
        for script in sorted(_SCRIPTS_DIR.glob("*.sh")):
            text = script.read_text(encoding="utf-8")
            if 'PROBE_CHANNEL" == "dead"' in text:
                pytest.fail(
                    f"{script.name} still branches on 'dead' alone; probe_error "
                    "and unrecognised statuses would be silent"
                )


def test_python_is_available_for_the_json_parse() -> None:
    """Sanity: the parse helper the function relies on exists on this host."""
    assert sys.executable
