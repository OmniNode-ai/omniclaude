# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Workflow git pins govern the consumer baseline ratchet, which fails closed."""

from __future__ import annotations

import http.client
import io
import json
import subprocess
import urllib.error
from pathlib import Path
from unittest.mock import Mock, call

import pytest
import yaml

from scripts.ci import check_canonical_inference_baseline_growth as gate

pytestmark = pytest.mark.unit

BASE = "a" * 40
HEAD = "b" * 40


def _workflow(sha: str) -> str:
    return f'uv run --with "omnibase-core @ git+https://github.com/OmniNode-ai/omnibase_core.git@{sha}"'


def _pins(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    head_text: str = _workflow(HEAD),
    base_text: str | None = _workflow(BASE),
) -> Mock:
    monkeypatch.setattr(gate, "REPO_ROOT", tmp_path)
    workflow = tmp_path / gate.WORKFLOW_PATH
    workflow.parent.mkdir(parents=True)
    workflow.write_text(head_text, encoding="utf-8")
    git = Mock()
    if base_text is None:
        git.side_effect = [subprocess.CalledProcessError(128, "git show"), ""]
    else:
        git.return_value = base_text
    monkeypatch.setattr(gate.subprocess, "check_output", git)
    return git


def _baseline(fingerprints: set[str]) -> bytes:
    return json.dumps(
        {
            "violations": [
                {"repo": "omniclaude", "fingerprint": value}
                for value in sorted(fingerprints)
            ]
            + [{"repo": "other", "fingerprint": "ignored"}]
        }
    ).encode()


def _network(monkeypatch: pytest.MonkeyPatch, responses: list[object]) -> Mock:
    opener = Mock()
    opener.open.side_effect = responses
    monkeypatch.setattr(gate.urllib.request, "build_opener", Mock(return_value=opener))
    return opener.open


def test_unchanged_pin_passes_without_downloading(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    git = _pins(monkeypatch, tmp_path, head_text=_workflow(BASE))
    network = _network(monkeypatch, [AssertionError("must not download")])
    assert gate.check_growth("origin/dev") == 0
    network.assert_not_called()
    git.assert_called_once_with(
        ["git", "show", f"origin/dev:{gate.WORKFLOW_PATH}"],
        cwd=tmp_path,
        text=True,
        stderr=subprocess.PIPE,
        timeout=30,
    )
    assert "pin unchanged; the baseline cannot have grown" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("prior", "head", "expected"),
    [
        ({"old"}, {"old", "new"}, 1),
        ({"old", "removed"}, {"old"}, 0),
        ({"old"}, {"replacement"}, 1),
        ({"old"}, {"old"}, 0),
    ],
    ids=["grew", "shrank", "replaced", "same-fingerprints"],
)
def test_changed_pin_compares_fingerprints(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    prior: set[str],
    head: set[str],
    expected: int,
) -> None:
    _pins(monkeypatch, tmp_path)
    network = _network(
        monkeypatch, [io.BytesIO(_baseline(prior)), io.BytesIO(_baseline(head))]
    )
    assert gate.check_growth("origin/dev") == expected
    assert network.call_args_list == [
        call(gate.BASELINE_URL.format(sha=pin), timeout=gate.DOWNLOAD_TIMEOUT)
        for pin in (BASE, HEAD)
    ]
    output = capsys.readouterr()
    if expected:
        assert "BASELINE GREW" in output.err
        for fingerprint in head - prior:
            assert fingerprint in output.err.splitlines()
    else:
        assert "BASELINE OK" in output.out


@pytest.mark.parametrize("failed_pin", [BASE, HEAD], ids=["prior", "head"])
@pytest.mark.parametrize(
    "error", [urllib.error.URLError("offline"), http.client.IncompleteRead(b"partial")]
)
def test_changed_pin_unobtainable_baseline_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    failed_pin: str,
    error: Exception,
) -> None:
    _pins(monkeypatch, tmp_path)
    responses: list[object] = [error] * (gate.DOWNLOAD_RETRIES + 1)
    if failed_pin == HEAD:
        responses.insert(0, io.BytesIO(_baseline({"old"})))
    network = _network(monkeypatch, responses)
    assert gate.check_growth("origin/dev") == 1
    assert network.call_count == len(responses)
    assert f"baseline at omnibase_core {failed_pin}" in capsys.readouterr().err


@pytest.mark.parametrize("inconsistent_ref", ["HEAD", "base"])
def test_inconsistent_pins_fail(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    inconsistent_ref: str,
) -> None:
    inconsistent = _workflow(BASE) + "\n" + _workflow(HEAD)
    _pins(
        monkeypatch,
        tmp_path,
        head_text=inconsistent if inconsistent_ref == "HEAD" else _workflow(HEAD),
        base_text=inconsistent if inconsistent_ref == "base" else _workflow(BASE),
    )
    network = _network(monkeypatch, [AssertionError("must not download")])
    assert gate.check_growth("origin/dev") == 1
    assert "inconsistent omnibase_core SHAs" in capsys.readouterr().err
    network.assert_not_called()


def test_repeated_consistent_pins_pass(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    workflow = _workflow(BASE) + "\n" + _workflow(BASE.upper())
    _pins(monkeypatch, tmp_path, head_text=workflow, base_text=workflow)
    network = _network(monkeypatch, [AssertionError("must not download")])
    assert gate.check_growth("origin/dev") == 0
    network.assert_not_called()


def test_absent_base_workflow_passes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    git = _pins(monkeypatch, tmp_path, base_text=None)
    network = _network(monkeypatch, [AssertionError("must not download")])
    assert gate.check_growth("origin/dev") == 0
    assert "nothing to compare (new gate)" in capsys.readouterr().out
    network.assert_not_called()
    assert git.call_args_list[-1].args[0] == [
        "git",
        "ls-tree",
        "--name-only",
        "origin/dev",
        "--",
        gate.WORKFLOW_PATH,
    ]


@pytest.mark.parametrize(
    "base_text",
    ["", "name: existing gate without a core pin", _workflow("a" * 39)],
    ids=["empty", "missing-pin", "short-pin"],
)
def test_existing_base_workflow_without_valid_pin_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    base_text: str,
) -> None:
    _pins(monkeypatch, tmp_path, base_text=base_text)
    network = _network(monkeypatch, [AssertionError("must not download")])
    assert gate.check_growth("origin/dev") == 1
    assert "origin/dev:" in capsys.readouterr().err
    network.assert_not_called()


def test_unobtainable_base_ref_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    git = _pins(monkeypatch, tmp_path)
    git.side_effect = subprocess.CalledProcessError(128, "git")
    network = _network(monkeypatch, [AssertionError("must not download")])
    assert gate.check_growth("origin/dev") == 1
    assert "CHECK FAILED" in capsys.readouterr().err
    network.assert_not_called()


def test_missing_head_pin_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _pins(monkeypatch, tmp_path, head_text="no git pin")
    assert gate.check_growth("origin/dev") == 1


@pytest.mark.parametrize(
    "content",
    [
        b"not json",
        b"{}",
        b'{"violations": {}}',
        b'{"violations": [null]}',
        b'{"violations": [{"repo": "omniclaude", "fingerprint": 123}]}',
    ],
)
@pytest.mark.parametrize("failed_pin", [BASE, HEAD])
def test_malformed_baseline_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    content: bytes,
    failed_pin: str,
) -> None:
    _pins(monkeypatch, tmp_path)
    responses: list[object] = [io.BytesIO(content)]
    if failed_pin == HEAD:
        responses.insert(0, io.BytesIO(_baseline({"old"})))
    _network(monkeypatch, responses)
    assert gate.check_growth("origin/dev") == 1
    assert f"baseline at omnibase_core {failed_pin}" in capsys.readouterr().err


def test_transient_download_failure_retries_and_passes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _pins(monkeypatch, tmp_path)
    network = _network(
        monkeypatch,
        [
            urllib.error.URLError("temporary"),
            io.BytesIO(_baseline({"old"})),
            io.BytesIO(_baseline({"old"})),
        ],
    )
    assert gate.check_growth("origin/dev") == 0
    assert network.call_count == 3


def test_workflow_keeps_the_pinned_validator_and_fetches_base() -> None:
    root = Path(__file__).resolve().parents[2]
    workflow = yaml.safe_load((root / gate.WORKFLOW_PATH).read_text())
    steps = workflow["jobs"]["canonical-inference-gate"]["steps"]
    checkout = next(step for step in steps if step["name"] == "Checkout")
    assert checkout["with"]["fetch-depth"] == 0
    validator = next(
        step
        for step in steps
        if step["name"].startswith("Run canonical-inference gate")
    )
    assert validator["run"] == (
        'uv run --with "omnibase-core @ git+https://github.com/OmniNode-ai/'
        'omnibase_core.git@940d2f2ab44d2f455a607926674b90ecbc9b74ba" \\\n'
        "  python -m omnibase_core.validation.validator_canonical_inference \\\n"
        "  --all --repo omniclaude --repo-root .\n"
    )
    assert all(step["name"] != "Install locked dependencies" for step in steps)
    growth = next(
        step
        for step in steps
        if step["name"] == "Assert baseline did not grow (anti-growth)"
    )
    assert growth["env"]["BASE_REF"] == "origin/${{ github.base_ref || 'dev' }}"
    assert growth["run"] == (
        'python3 scripts/ci/check_canonical_inference_baseline_growth.py --base-ref "$BASE_REF"'
    )
