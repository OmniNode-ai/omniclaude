# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for anchor-first resume manifest (OMN-13049).

Covers the ModelResumeManifest / EnumResumeManifestPhase Pydantic model,
the YAML writer, the reader, and the survivor-note helper.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from omniclaude.hooks.lib.resume_manifest_writer import (
    read_resume_manifest,
    write_resume_manifest,
    write_survivor_note,
)
from omniclaude.hooks.model_resume_manifest import (
    EnumResumeManifestPhase,
    ModelResumeManifest,
)

pytestmark = pytest.mark.unit

_TICKET = "OMN-13049"
_RUN_ID = "run-abc-123"
_TS = "2026-06-12T10:00:00Z"


def _make_manifest(
    phase: EnumResumeManifestPhase = EnumResumeManifestPhase.PHASE_0_ANCHOR,
    *,
    wip_branch: str | None = "jonah/omn-13049-anchor",
    wip_pushed_at: str | None = _TS,
) -> ModelResumeManifest:
    return ModelResumeManifest(
        ticket_id=_TICKET,
        run_id=_RUN_ID,
        linear_ticket_url="https://linear.app/omninode/issue/OMN-13049",
        wip_branch=wip_branch,
        wip_pushed_at=wip_pushed_at,
        phase=phase,
        phase_started_at=_TS,
    )


# ---------------------------------------------------------------------------
# Model construction and field constraints
# ---------------------------------------------------------------------------


def test_model_defaults() -> None:
    m = _make_manifest()
    assert m.schema_version == "1.0.0"
    assert m.auth_error_detected is False
    assert m.survivor_note is None
    assert m.phase_completed_at is None


def test_model_frozen_rejects_mutation() -> None:
    m = _make_manifest()
    with pytest.raises((TypeError, ValidationError)):
        m.ticket_id = "OMN-99999"  # type: ignore[misc]


def test_model_rejects_extra_field() -> None:
    with pytest.raises(ValidationError):
        ModelResumeManifest(  # type: ignore[call-arg]
            ticket_id=_TICKET,
            run_id=_RUN_ID,
            phase=EnumResumeManifestPhase.PHASE_0_ANCHOR,
            phase_started_at=_TS,
            unknown_field="oops",
        )


def test_model_rejects_empty_ticket_id() -> None:
    with pytest.raises(ValidationError):
        ModelResumeManifest(
            ticket_id="",
            run_id=_RUN_ID,
            phase=EnumResumeManifestPhase.PHASE_0_ANCHOR,
            phase_started_at=_TS,
        )


def test_model_rejects_ticket_id_too_long() -> None:
    with pytest.raises(ValidationError):
        ModelResumeManifest(
            ticket_id="X" * 65,
            run_id=_RUN_ID,
            phase=EnumResumeManifestPhase.PHASE_0_ANCHOR,
            phase_started_at=_TS,
        )


# ---------------------------------------------------------------------------
# EnumResumeManifestPhase values
# ---------------------------------------------------------------------------


def test_phase_enum_values() -> None:
    assert EnumResumeManifestPhase.PHASE_0_ANCHOR == "phase_0_anchor"
    assert EnumResumeManifestPhase.IMPLEMENT == "implement"
    assert EnumResumeManifestPhase.LOCAL_REVIEW == "local_review"
    assert EnumResumeManifestPhase.CREATE_PR == "create_pr"
    assert EnumResumeManifestPhase.DONE == "done"


# ---------------------------------------------------------------------------
# write_resume_manifest
# ---------------------------------------------------------------------------


def test_writer_creates_file_at_expected_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ONEX_STATE_DIR", str(tmp_path))
    manifest = _make_manifest()

    out = write_resume_manifest(manifest)

    assert out == tmp_path / "manifests" / _TICKET / "manifest.yaml"
    assert out.is_file()


def test_writer_creates_missing_parent_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ONEX_STATE_DIR", str(tmp_path))
    manifests_dir = tmp_path / "manifests" / _TICKET
    assert not manifests_dir.exists()

    write_resume_manifest(_make_manifest())

    assert manifests_dir.is_dir()


def test_writer_serializes_fields_to_yaml(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ONEX_STATE_DIR", str(tmp_path))
    manifest = _make_manifest()

    out = write_resume_manifest(manifest)
    body = out.read_text(encoding="utf-8")

    assert "ticket_id: OMN-13049" in body
    assert "run_id: run-abc-123" in body
    assert "phase: phase_0_anchor" in body
    assert "wip_branch: jonah/omn-13049-anchor" in body
    assert "auth_error_detected: false" in body


def test_writer_overwrites_on_second_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ONEX_STATE_DIR", str(tmp_path))
    first = _make_manifest(phase=EnumResumeManifestPhase.PHASE_0_ANCHOR)
    write_resume_manifest(first)

    second = _make_manifest(phase=EnumResumeManifestPhase.IMPLEMENT)
    out = write_resume_manifest(second)

    data = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert data["phase"] == "implement"


# ---------------------------------------------------------------------------
# read_resume_manifest
# ---------------------------------------------------------------------------


def test_reader_returns_none_for_missing_ticket(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ONEX_STATE_DIR", str(tmp_path))
    assert read_resume_manifest("OMN-99999") is None


def test_reader_round_trips_written_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ONEX_STATE_DIR", str(tmp_path))
    manifest = _make_manifest(phase=EnumResumeManifestPhase.CREATE_PR)
    write_resume_manifest(manifest)

    loaded = read_resume_manifest(_TICKET)

    assert loaded is not None
    assert loaded.ticket_id == _TICKET
    assert loaded.run_id == _RUN_ID
    assert loaded.phase == EnumResumeManifestPhase.CREATE_PR
    assert loaded.wip_branch == "jonah/omn-13049-anchor"
    assert loaded.auth_error_detected is False


# ---------------------------------------------------------------------------
# write_survivor_note
# ---------------------------------------------------------------------------


def test_survivor_note_sets_error_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ONEX_STATE_DIR", str(tmp_path))
    manifest = _make_manifest()
    detail = "401 Unauthorized on Linear API — ticket cannot be updated"

    write_survivor_note(manifest, detail=detail)

    loaded = read_resume_manifest(_TICKET)
    assert loaded is not None
    assert loaded.auth_error_detected is True
    assert loaded.survivor_note == detail


def test_survivor_note_preserves_other_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ONEX_STATE_DIR", str(tmp_path))
    manifest = _make_manifest(phase=EnumResumeManifestPhase.IMPLEMENT)

    write_survivor_note(manifest, detail="usage limit reached")

    loaded = read_resume_manifest(_TICKET)
    assert loaded is not None
    assert loaded.phase == EnumResumeManifestPhase.IMPLEMENT
    assert loaded.ticket_id == _TICKET
    assert loaded.wip_branch == "jonah/omn-13049-anchor"


def test_survivor_note_auth_error_false(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ONEX_STATE_DIR", str(tmp_path))
    manifest = _make_manifest()

    write_survivor_note(manifest, detail="non-auth diagnostic note", auth_error=False)

    loaded = read_resume_manifest(_TICKET)
    assert loaded is not None
    assert loaded.auth_error_detected is False
    assert loaded.survivor_note == "non-auth diagnostic note"


def test_survivor_note_returns_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ONEX_STATE_DIR", str(tmp_path))
    manifest = _make_manifest()

    out = write_survivor_note(manifest, detail="some error")

    assert out == tmp_path / "manifests" / _TICKET / "manifest.yaml"
    assert out.is_file()
