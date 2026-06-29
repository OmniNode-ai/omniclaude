# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Writer for anchor-first resume manifests (OMN-13049).

Workers call :func:`write_resume_manifest` after every phase boundary to
persist a :class:`~omniclaude.hooks.model_resume_manifest.ModelResumeManifest`
under ``$ONEX_STATE_DIR/manifests/<ticket_id>/manifest.yaml``.

On auth or usage-limit errors, :func:`write_survivor_note` flushes a manifest
with ``auth_error_detected=True`` and a diagnostic ``survivor_note`` so the
defect retains identity even if the worker process dies before filing a PR.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from omniclaude.hooks.lib.onex_state import ensure_state_path, state_path
from omniclaude.hooks.model_resume_manifest import ModelResumeManifest


def _manifest_path(ticket_id: str) -> Path:
    """Return the canonical manifest path for *ticket_id* (no side effects)."""
    return state_path("manifests", ticket_id, "manifest.yaml")


def write_resume_manifest(manifest: ModelResumeManifest) -> Path:
    """Persist *manifest* to ``$ONEX_STATE_DIR/manifests/<ticket_id>/manifest.yaml``.

    The parent directory is created if missing.  Existing manifests are
    overwritten — each call represents the latest phase-boundary state.

    Args:
        manifest: The manifest to persist.

    Returns:
        Absolute path to the written file.
    """
    out_path = ensure_state_path("manifests", manifest.ticket_id, "manifest.yaml")
    payload = manifest.model_dump(mode="json")
    out_path.write_text(yaml.safe_dump(payload, sort_keys=True), encoding="utf-8")
    return out_path


def read_resume_manifest(ticket_id: str) -> ModelResumeManifest | None:
    """Read and deserialize the resume manifest for *ticket_id*.

    Returns ``None`` if no manifest file exists yet.

    Args:
        ticket_id: Linear ticket identifier (e.g., ``OMN-13049``).

    Returns:
        Deserialized :class:`ModelResumeManifest`, or ``None`` if not found.
    """
    path = _manifest_path(ticket_id)
    if not path.is_file():
        return None
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return ModelResumeManifest.model_validate(raw)


def write_survivor_note(
    manifest: ModelResumeManifest,
    *,
    detail: str,
    auth_error: bool = True,
) -> Path:
    """Flush *manifest* annotated with error context so the defect has identity.

    Constructs a new manifest with ``auth_error_detected`` set to *auth_error*
    and ``survivor_note=detail``, then persists it.  All other fields from
    *manifest* are preserved unchanged.

    Args:
        manifest: The in-progress manifest to annotate and persist.
        detail: Human-readable description of the error or diagnosed defect.
        auth_error: Whether the trigger was an auth or usage-limit error
            (default ``True``).

    Returns:
        Absolute path to the written file.
    """
    annotated = manifest.model_copy(
        update={
            "auth_error_detected": auth_error,
            "survivor_note": detail,
        }
    )
    return write_resume_manifest(annotated)
