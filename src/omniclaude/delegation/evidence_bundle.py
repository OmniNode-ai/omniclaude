# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Evidence bundle writer for delegation runs.

Produces five immutable artifacts per delegation run, written atomically under
``$ONEX_STATE_DIR/delegation/bundles/<correlation_id>/``:

    run_manifest.json         — run metadata (correlation_id, ticket, timestamps)
    bifrost_response.json     — routing decision + LLM response
    quality_gate_result.json  — pass/fail + score + reasons
    cost_event.json           — counterfactual savings estimate
    receipt.json              — OCC-style receipt with SHA-256 over the four

The writer accepts plain dicts for each artifact so callers can compose it from
the in-process ``DelegationRunner`` (returns ``ModelDelegationResult``), the
Bifrost runner (returns ``ModelBifrostRunnerResult``), or the SQLite-backed
``SavingsCalculator`` (returns ``ModelSavingsEstimate``) without any of those
upstream models being import-required here.

Atomicity:
    Each artifact is written via ``tempfile`` + ``os.replace`` so a crash mid-
    write never leaves a half-formed JSON behind. The receipt is written LAST,
    so its presence is the signal that the bundle is complete.

Determinism:
    No ``datetime.now()`` defaults — every timestamp must be supplied by the
    caller. All Pydantic models are ``frozen=True``.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
import uuid
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

logger = logging.getLogger(__name__)


_BUNDLE_SCHEMA_VERSION = "1.0.0"
_RECEIPT_FILENAME = "receipt.json"
_RUN_MANIFEST_FILENAME = "run_manifest.json"
_BIFROST_RESPONSE_FILENAME = "bifrost_response.json"
_QUALITY_GATE_FILENAME = "quality_gate_result.json"
_COST_EVENT_FILENAME = "cost_event.json"


class EnumBundleArtifact(StrEnum):
    """The four artifacts the receipt covers."""

    RUN_MANIFEST = _RUN_MANIFEST_FILENAME
    BIFROST_RESPONSE = _BIFROST_RESPONSE_FILENAME
    QUALITY_GATE_RESULT = _QUALITY_GATE_FILENAME
    COST_EVENT = _COST_EVENT_FILENAME


class ModelRunManifest(BaseModel):
    """Run-level metadata for a single delegation run."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    correlation_id: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$",
        description=(
            "Path-safe identifier; must start with alphanumeric and contain only "
            "alphanumerics, dot, hyphen, underscore. Prevents directory traversal "
            "when joined into the bundle path."
        ),
    )
    bundle_id: str = Field(min_length=1, max_length=128)
    bundle_schema_version: str = _BUNDLE_SCHEMA_VERSION
    ticket_id: str | None = None
    session_id: str | None = None
    task_type: str
    prompt_hash: str = Field(
        min_length=64, max_length=64, description="SHA-256 hex of the user prompt"
    )
    started_at: datetime
    completed_at: datetime
    runner: str = Field(description="Runner identifier, e.g. 'inprocess' or 'bifrost'")

    @model_validator(mode="after")
    def _completed_after_started(self) -> ModelRunManifest:
        if self.completed_at < self.started_at:
            raise ValueError(
                f"completed_at ({self.completed_at.isoformat()}) must not be "
                f"before started_at ({self.started_at.isoformat()})"
            )
        return self


class ModelBifrostResponse(BaseModel):
    """Routing decision + LLM response surface."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    correlation_id: str
    backend_selected: str = Field(description="Endpoint URL or backend name")
    model_used: str
    rule_id: str | None = None
    config_version: str | None = None
    retry_count: int = 0
    latency_ms: int = Field(ge=0)
    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)
    response_content: str
    response_truncated: bool = False


class ModelQualityGateArtifact(BaseModel):
    """Quality gate verdict for the run."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    correlation_id: str
    passed: bool
    quality_score: float | None = None
    failure_reasons: tuple[str, ...] = ()
    fallback_to_claude: bool = False


class ModelCostEvent(BaseModel):
    """Counterfactual savings estimate for the run."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    correlation_id: str
    session_id: str | None = None
    model_local: str
    baseline_model: str
    local_cost_usd: float | None
    cloud_cost_usd: float | None
    savings_usd: float | None
    savings_method: str
    token_provenance: str
    pricing_manifest_version: str
    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)


class ModelBundleReceipt(BaseModel):
    """OCC-style receipt covering the other four artifacts.

    The ``artifact_hashes`` map keys are the artifact filenames; values are
    the SHA-256 hex digest of the on-disk JSON bytes (as written, after
    canonical serialization).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    bundle_id: str
    correlation_id: str
    bundle_schema_version: str = _BUNDLE_SCHEMA_VERSION
    issued_at: datetime
    artifact_hashes: dict[str, str]
    bundle_root_hash: str = Field(
        min_length=64,
        max_length=64,
        description="SHA-256 over the sorted (filename, hash) pairs",
    )


def _canonical_json_bytes(
    payload: dict[str, Any],  # ONEX_EXCLUDE: dict_str_any - JSON serialization boundary
) -> bytes:
    """Serialize a JSON-able dict deterministically.

    sort_keys + no whitespace makes the on-disk byte sequence stable across
    runs with the same logical content, so the receipt hash is reproducible.
    """
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")


def _atomic_write(target: Path, data: bytes) -> str:
    """Write ``data`` to ``target`` atomically. Returns SHA-256 hex of bytes."""
    target.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(data).hexdigest()
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent)
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        tmp_path.replace(target)
    except Exception:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass
        raise
    return digest


def _bundle_root_hash(artifact_hashes: dict[str, str]) -> str:
    """Hash of the sorted (filename, hash) pairs."""
    h = hashlib.sha256()
    for name in sorted(artifact_hashes):
        h.update(name.encode("utf-8"))
        h.update(b"\x1f")
        h.update(artifact_hashes[name].encode("utf-8"))
        h.update(b"\x1e")
    return h.hexdigest()


class EvidenceBundleWriter:
    """Write a five-artifact evidence bundle for one delegation run."""

    def __init__(self, root_dir: Path) -> None:
        """Initialise the writer.

        Args:
            root_dir: Directory under which ``<correlation_id>/`` bundle
                subdirectories are created. Typically
                ``Path(os.environ["ONEX_STATE_DIR"]) / "delegation" / "bundles"``.
        """
        self._root_dir = root_dir

    def bundle_path(self, correlation_id: str) -> Path:
        """Return the directory the bundle for ``correlation_id`` lives in.

        Defence-in-depth against directory traversal: ``ModelRunManifest``
        already enforces a regex pattern on ``correlation_id``, but this
        method may be called with values that bypass model validation (e.g.
        callers passing a raw string). Reject anything that contains a path
        separator or is a relative-traversal segment.
        """
        if (
            "/" in correlation_id
            or "\\" in correlation_id
            or correlation_id in {".", ".."}
        ):
            raise ValueError(f"invalid correlation_id path segment: {correlation_id!r}")
        return self._root_dir / correlation_id

    def write(
        self,
        *,
        manifest: ModelRunManifest,
        bifrost_response: ModelBifrostResponse,
        quality_gate: ModelQualityGateArtifact,
        cost_event: ModelCostEvent,
        issued_at: datetime,
    ) -> ModelBundleReceipt:
        """Write all five artifacts and return the receipt.

        The receipt is written last; its presence on disk indicates the bundle
        is complete and verifiable.

        Args:
            manifest: Run manifest model.
            bifrost_response: Routing + LLM response model.
            quality_gate: Quality gate verdict model.
            cost_event: Cost / savings estimate model.
            issued_at: Receipt issuance timestamp (caller-supplied for
                deterministic testing).

        Returns:
            The persisted ``ModelBundleReceipt``.

        Raises:
            ValueError: If correlation_ids across artifacts do not all match
                ``manifest.correlation_id``.
            OSError: If atomic write fails (rare; partial bundle is cleaned up).
        """
        cid = manifest.correlation_id
        for label, value in (
            ("bifrost_response", bifrost_response.correlation_id),
            ("quality_gate", quality_gate.correlation_id),
            ("cost_event", cost_event.correlation_id),
        ):
            if value != cid:
                raise ValueError(
                    f"correlation_id mismatch: manifest={cid!r}, {label}={value!r}"
                )

        bundle_dir = self.bundle_path(cid)

        artifacts: list[tuple[str, BaseModel]] = [
            (_RUN_MANIFEST_FILENAME, manifest),
            (_BIFROST_RESPONSE_FILENAME, bifrost_response),
            (_QUALITY_GATE_FILENAME, quality_gate),
            (_COST_EVENT_FILENAME, cost_event),
        ]

        artifact_hashes: dict[str, str] = {}
        for filename, model in artifacts:
            payload = model.model_dump(mode="json")
            data = _canonical_json_bytes(payload)
            digest = _atomic_write(bundle_dir / filename, data)
            artifact_hashes[filename] = digest

        receipt = ModelBundleReceipt(
            bundle_id=manifest.bundle_id,
            correlation_id=cid,
            issued_at=issued_at,
            artifact_hashes=artifact_hashes,
            bundle_root_hash=_bundle_root_hash(artifact_hashes),
        )
        receipt_data = _canonical_json_bytes(receipt.model_dump(mode="json"))
        _atomic_write(bundle_dir / _RECEIPT_FILENAME, receipt_data)

        logger.info(
            "Wrote delegation evidence bundle",
            extra={
                "correlation_id": cid,
                "bundle_id": manifest.bundle_id,
                "bundle_dir": str(bundle_dir),
                "bundle_root_hash": receipt.bundle_root_hash,
            },
        )
        return receipt


def new_bundle_id() -> str:
    """Convenience helper: generate a fresh bundle id."""
    return str(uuid.uuid4())


def hash_prompt(prompt: str) -> str:
    """SHA-256 hex digest of a UTF-8-encoded prompt."""
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


__all__ = [
    "EnumBundleArtifact",
    "EvidenceBundleWriter",
    "ModelBifrostResponse",
    "ModelBundleReceipt",
    "ModelCostEvent",
    "ModelQualityGateArtifact",
    "ModelRunManifest",
    "hash_prompt",
    "new_bundle_id",
]
