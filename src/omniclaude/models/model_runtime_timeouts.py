# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Runtime timeouts declared in the omniclaude runtime contract (OMN-21623).

The subprocess and HTTP timeouts of the trace frame assembler and replay engine,
the diagnostics and health-check tools and the coverage scanner used to be integer literals at each call
site. They are declared in ``contracts/contract_omniclaude_runtime.yaml`` under
``timeouts:`` with the ``${env.VAR:default}`` overlay convention, so a per-lane
operator overlay supplies the value, and reach their callers as an injected
:class:`ModelRuntimeTimeouts`. No field carries a default here: a field the
contract does not declare fails to load rather than passing.
"""

from __future__ import annotations

import os
import re
from functools import cache
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

# ``${env.VAR}`` / ``${env.VAR:default}`` -- the same env-overlay convention the
# aggregator and diagnostics descriptors use for the runtime contract.
_ENV_REF = re.compile(
    r"\$\{env\.(?P<name>[A-Za-z_][A-Za-z0-9_]*)(?::(?P<default>[^}]*))?\}"
)

_CONTRACT = (
    Path(__file__).resolve().parents[1]
    / "contracts"
    / "contract_omniclaude_runtime.yaml"
)


def _expand_contract_env_refs(value: str) -> str:
    """Expand ``${env.VAR}`` / ``${env.VAR:default}`` -- this module's one env boundary."""

    def _sub(match: re.Match[str]) -> str:
        default = match.group("default")
        return os.environ.get(
            match.group("name"), default if default is not None else ""
        )

    return _ENV_REF.sub(_sub, value)


@cache
def _load_timeouts_section(contract_path: Path) -> dict[str, object]:
    with contract_path.open(encoding="utf-8") as contract_file:
        raw = yaml.safe_load(contract_file)
    section = raw.get("timeouts") if isinstance(raw, dict) else None
    if not isinstance(section, dict):
        raise ValueError(
            f"contract {contract_path} must declare a 'timeouts' mapping with the "
            "runtime timeout fields"
        )
    return section


class ModelRuntimeTimeouts(BaseModel):
    """Timeouts, in seconds, for the trace, diagnostics, health-check and coverage tools.

    Build with :meth:`from_contract`, or inject an explicit instance in a test.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    trace_git_diff_seconds: float = Field(gt=0)
    trace_git_identity_seconds: float = Field(gt=0)
    trace_environment_hash_seconds: float = Field(gt=0)
    trace_lint_check_seconds: float = Field(gt=0)
    trace_type_check_seconds: float = Field(gt=0)
    diagnostics_curl_health_seconds: float = Field(gt=0)
    diagnostics_docker_seconds: float = Field(gt=0)
    diagnostics_http_seconds: float = Field(gt=0)
    health_check_httpx_seconds: float = Field(gt=0)
    health_check_base_seconds: float = Field(gt=0)
    health_check_pattern_seconds: float = Field(gt=0)
    health_check_post_seconds: float = Field(gt=0)
    replay_clone_seconds: float = Field(gt=0)
    replay_checkout_seconds: float = Field(gt=0)
    replay_apply_seconds: float = Field(gt=0)
    coverage_cache_ttl_seconds: float = Field(gt=0)
    coverage_pytest_seconds: float = Field(gt=0)
    coverage_git_log_seconds: float = Field(gt=0)

    @classmethod
    def from_contract(cls, contract_path: Path = _CONTRACT) -> ModelRuntimeTimeouts:
        """Build the timeouts from the runtime contract's ``timeouts:`` section.

        Each declared ``${env.VAR:default}`` value is overlay-resolved, then
        validated by pydantic. A field the contract does not declare, or a value
        that resolves empty, fails validation.
        """
        section = _load_timeouts_section(contract_path)
        resolved: dict[str, object] = {}
        for field_name in cls.model_fields:
            declared = section.get(field_name)
            if isinstance(declared, str):
                resolved[field_name] = _expand_contract_env_refs(declared).strip()
            elif declared is not None:
                resolved[field_name] = declared
        return cls.model_validate(resolved)
