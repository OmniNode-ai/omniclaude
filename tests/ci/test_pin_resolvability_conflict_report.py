# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The pin-resolvability report names the conflicting pins (OMN-19655).

``scripts/ci/verify_pypi_pin_resolvability.py`` is vendored byte-for-byte from
omnibase_infra, where it and these tests originate. It runs in this repo's
release workflow and, since OMN-19655, before merge in
``pin-resolvability-gate.yml``. A red verdict must say which pins collide.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import scripts.ci.verify_pypi_pin_resolvability as pin_gate

# ---------------------------------------------------------------------------
# OMN-19655 -- the failure names the conflicting pins, pre-merge and at release
# ---------------------------------------------------------------------------

#: uv's own explanation, captured verbatim from this script run against
#: omnimarket at the omnimarket#2896 merge commit (933d0ca8) with the index held
#: to 2026-09-25T18:00:00Z, the state that failed omnimarket Release on Merge on
#: every dev push that day.
_OMN_19655_UV_CONFLICT = """\
Using Python 3.13.12 environment at: /tmp/x/venv
  × No solution found when resolving dependencies:
  ╰─▶ Because omnibase-infra==0.38.36 depends on omnibase-core==0.47.18 and
      omnibase-infra>=0.38.51,<=0.38.56 depends on omnibase-core==0.47.20, we
      can conclude that omnibase-infra>=0.38.36,<=0.38.56 depends on one of:
          omnibase-core==0.47.18
          omnibase-core==0.47.20

      And because omnibase-infra>=0.38.57 depends on omnibase-core==0.47.22,
      we can conclude that omnibase-infra>=0.38.36 depends on one of:
          omnibase-core==0.47.18
          omnibase-core>=0.47.20,<=0.47.22

      And because omnimarket==0.4.218 depends on omnibase-core>=0.47.23 and
      omnibase-infra>=0.38.36, we can conclude that omnimarket==0.4.218 cannot
      be used.
      And because only omnimarket==0.4.218 is available and you require
      omnimarket, we can conclude that your requirements are unsatisfiable.
"""  # noqa: RUF001 - uv prints this sign; the capture is verbatim


@pytest.mark.unit
def test_conflicting_requirements_names_every_stated_pin_and_no_derived_one() -> None:
    """The report must say WHICH pins collide, in the words a reader acts on:
    the package's own floor and the exact pin every published sibling carries.
    uv's derived conclusions ("we can conclude that X depends on one of") are
    restatements, not pins anyone declared, and must not be listed as if they were.
    """
    found = pin_gate.conflicting_requirements(_OMN_19655_UV_CONFLICT)

    assert found == [
        "omnibase-infra==0.38.36 depends on omnibase-core==0.47.18",
        "omnibase-infra>=0.38.51,<=0.38.56 depends on omnibase-core==0.47.20",
        "omnibase-infra>=0.38.57 depends on omnibase-core==0.47.22",
        "omnimarket==0.4.218 depends on omnibase-core>=0.47.23 and omnibase-infra>=0.38.36",
    ]


@pytest.mark.unit
def test_conflicting_requirements_is_empty_for_a_log_with_no_conflict() -> None:
    """Negative control: a missing-version failure (the OMN-14064 shape) or a
    clean log carries no dependency statement, so nothing is invented."""
    assert pin_gate.conflicting_requirements("Resolved 3 packages in 10ms\n") == []


@pytest.mark.unit
def test_unresolvable_report_emits_an_error_annotation_and_step_summary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A red run must name the conflicting pins where a reviewer looks first: a
    GitHub error annotation and the step summary, not only line 400 of a log."""
    (tmp_path / "omnimarket-0.4.218-py3-none-any.whl").write_bytes(b"")
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    monkeypatch.setattr(
        pin_gate,
        "verify_pin_resolvability",
        lambda _wheel: (False, _OMN_19655_UV_CONFLICT),
    )

    assert pin_gate.main([str(tmp_path)]) == 1

    out = capsys.readouterr().out
    annotation = [line for line in out.splitlines() if line.startswith("::error")]
    assert len(annotation) == 1
    assert "omnimarket==0.4.218 depends on omnibase-core>=0.47.23" in annotation[0]
    assert "omnibase-infra>=0.38.57 depends on omnibase-core==0.47.22" in annotation[0]
    written = summary.read_text(encoding="utf-8")
    assert "omnibase-infra>=0.38.57 depends on omnibase-core==0.47.22" in written
    assert "do not resolve" in written


@pytest.mark.unit
def test_resolvable_report_writes_no_error_annotation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (tmp_path / "pkg-1.0-py3-none-any.whl").write_bytes(b"")
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    monkeypatch.setattr(
        pin_gate, "verify_pin_resolvability", lambda _wheel: (True, "installed\n")
    )

    assert pin_gate.main([str(tmp_path)]) == 0
    assert "::error" not in capsys.readouterr().out
