# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Filesystem locations omniclaude code uses, read from the runtime contract (OMN-21728)."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

from omniclaude.models.model_model_routing_defaults import expand_overlay_value

_CONTRACT_PATH = (
    Path(__file__).resolve().parent.parent
    / "contracts"
    / "contract_omniclaude_runtime.yaml"
)


class ModelRuntimePaths(BaseModel):
    """The ``runtime_paths`` section of the runtime contract, overlay-resolved.

    Each location is declared in the contract with the ``${env.VAR:default}``
    overlay convention, so an operator overlay or the per-lane service env
    supplies it and code holds no path. A location its callers pass on as text is a
    ``str``, every other one a ``Path``. A leading ``~`` is expanded here,, and a
    location left empty by the overlay is absent (``registry_root`` alone may be, and
    resolves to ``None``; every other location fails validation).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    hook_socket: str = Field(description="Unix socket of the hook runtime")
    hook_pid: str = Field(description="PID file of the hook runtime")
    session_marker_dir: str = Field(description="Session-start marker file directory")
    usage_cache: Path = Field(description="Statusline OAuth usage cache file")
    linear_relay_dedup_db: Path = Field(description="Linear relay dedup SQLite file")
    opencode_db: Path = Field(description="opencode session SQLite database")
    store_reader_home: Path = Field(description="Home of the key store reader")
    onex_state_dir: str = Field(description="State root when ONEX_STATE_DIR is unset")
    pattern_tracking_log_dir: str = Field(description="Pattern tracking log directory")
    registry_root: Path | None = Field(
        default=None,
        description="Registry root the coupling check scans; unset when the overlay gives none",
    )

    @classmethod
    def from_contract(cls, path: Path | None = None) -> ModelRuntimePaths:
        """Resolve the contract's ``runtime_paths`` section against the overlay env."""
        with open(path or _CONTRACT_PATH, encoding="utf-8") as f:
            section = (yaml.safe_load(f) or {}).get("runtime_paths") or {}
        resolved = {
            key: expand_overlay_value(str(value)) for key, value in section.items()
        }
        # A value the overlay leaves empty is absent, so a required location fails validation.
        return cls.model_validate(
            {
                key: str(Path(value).expanduser())
                for key, value in resolved.items()
                if value
            }
        )

    def require_registry_root(self) -> Path:
        """The registry root, or a refusal when the overlay supplies none."""
        if self.registry_root is None:
            msg = "OMNI_HOME is not set: the registry root has no overlay value"
            raise ValueError(msg)
        return self.registry_root


def runtime_paths() -> ModelRuntimePaths:
    """The runtime contract's locations, resolved against the overlay env."""
    return ModelRuntimePaths.from_contract()
