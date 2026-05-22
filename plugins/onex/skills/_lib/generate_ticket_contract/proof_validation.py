# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Proof reference resolver library.

This module resolves proof references from ModelTicketContract YAML files.

SEMANTICS — this is a REFERENCE RESOLVER (v1), not a proof validator:
- RESOLVED: ref points to a plausibly real target (file exists, symbol in file text,
  check registered)
- WARN: target found with caveats (manual, symbol string not in file text)
- FAIL: ref cannot be resolved at all

v1 resolution for test refs: file exists AND symbol string found in file text
(plain string search). This is reference plausibility, NOT pytest collectability.
A symbol string match is not proof the test is collectible, syntactically valid, or
currently passing. Use --collect-only in v1.1.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

try:
    import yaml
except ModuleNotFoundError:  # pragma: no cover - exercised by CI runner import path
    yaml = None


class EnumRefStatus(StrEnum):
    RESOLVED = "RESOLVED"  # ref plausibly points to a real target (v1 semantics)
    WARN = "WARN"  # target found with caveats (manual, symbol not in file text)
    FAIL = "FAIL"  # ref cannot be resolved


@dataclass
class RefResolutionResult:
    kind: str
    criterion_id: str
    ref: str
    status: EnumRefStatus
    message: str

    @property
    def is_machine_verifiable(self) -> bool:
        return self.kind != "manual"


def _load_registry(registry_path: Path) -> set[str]:
    if not registry_path.exists():
        raise FileNotFoundError(f"Static checks registry not found: {registry_path}")
    text = registry_path.read_text()
    if yaml is None:
        return {
            match.group("id")
            for match in re.finditer(
                r"^\s*-\s*id:\s*(?P<id>['\"]?[^'\"\s#]+['\"]?)", text, re.MULTILINE
            )
        }
    data = yaml.safe_load(text)
    return {check["id"] for check in data.get("checks", [])}


def _clean_yaml_scalar(value: str) -> str:
    value = value.split(" #", 1)[0].strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _resolve_contract_without_yaml(
    contract_path: Path, resolver: ProofReferenceResolver
) -> list[RefResolutionResult]:
    """Resolve proof refs with a narrow parser for bare CI Python.

    The normal path uses PyYAML. This fallback intentionally handles only the
    `proof_requirements` list shape consumed by this helper, so contract schema
    validation remains owned by the dedicated validator.
    """
    results: list[RefResolutionResult] = []
    in_proof_requirements = False
    proof_requirements_indent = 0
    current: dict[str, str] | None = None

    def flush_current() -> None:
        nonlocal current
        if current is not None:
            results.append(
                resolver.resolve(
                    kind=current.get("kind", ""),
                    ref=current.get("ref", ""),
                    criterion_id=current.get("criterion_id", ""),
                )
            )
            current = None

    for raw_line in contract_path.read_text().splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        indent = len(raw_line) - len(raw_line.lstrip())
        if stripped == "proof_requirements:":
            flush_current()
            in_proof_requirements = True
            proof_requirements_indent = indent
            continue

        if not in_proof_requirements:
            continue

        if indent <= proof_requirements_indent:
            flush_current()
            in_proof_requirements = False
            continue

        item_match = re.match(r"-\s+kind:\s*(?P<value>.+)$", stripped)
        if item_match:
            flush_current()
            current = {"kind": _clean_yaml_scalar(item_match.group("value"))}
            continue

        field_match = re.match(r"(?P<key>ref|criterion_id):\s*(?P<value>.*)$", stripped)
        if current is not None and field_match:
            current[field_match.group("key")] = _clean_yaml_scalar(
                field_match.group("value")
            )

    flush_current()
    return results


class ProofReferenceResolver:
    def __init__(self, repo_root: Path, registry_path: Path) -> None:
        self.repo_root = repo_root
        self._registry: set[str] | None = None
        self._registry_path = registry_path

    @property
    def registry(self) -> set[str]:
        if self._registry is None:
            self._registry = _load_registry(self._registry_path)
        return self._registry

    def resolve(
        self, kind: str, ref: str, criterion_id: str = ""
    ) -> RefResolutionResult:
        if kind in ("unit_test", "integration_test"):
            return self._resolve_test(kind, ref, criterion_id)
        if kind == "static_check":
            return self._resolve_check(ref, criterion_id)
        if kind == "artifact":
            return self._resolve_artifact(ref, criterion_id)
        if kind == "manual":
            return RefResolutionResult(
                kind,
                criterion_id,
                ref,
                EnumRefStatus.WARN,
                "Manual proof: satisfies traceability only, not machine-verifiable proof",
            )
        return RefResolutionResult(
            kind, criterion_id, ref, EnumRefStatus.FAIL, f"Unknown kind: {kind!r}"
        )

    def _resolve_test(
        self, kind: str, ref: str, criterion_id: str
    ) -> RefResolutionResult:
        parts = ref.split("::")
        file_path = parts[0]
        symbol = parts[1] if len(parts) > 1 else None
        full = self.repo_root / file_path
        if not full.exists():
            return RefResolutionResult(
                kind,
                criterion_id,
                ref,
                EnumRefStatus.FAIL,
                f"Test file not found: {file_path}",
            )
        if symbol and symbol not in full.read_text():
            return RefResolutionResult(
                kind,
                criterion_id,
                ref,
                EnumRefStatus.WARN,
                f"v1 plausibility: file exists but symbol {symbol!r} not found in file text. "
                "Symbol may exist at runtime; use pytest --collect-only for v1.1 verification.",
            )
        msg = f"v1 plausibility: file found ({file_path})"
        if symbol:
            msg += f", symbol {symbol!r} in file text"
        return RefResolutionResult(kind, criterion_id, ref, EnumRefStatus.RESOLVED, msg)

    def _resolve_check(self, ref: str, criterion_id: str) -> RefResolutionResult:
        if ref in self.registry:
            return RefResolutionResult(
                "static_check",
                criterion_id,
                ref,
                EnumRefStatus.RESOLVED,
                f"Check registered: {ref}",
            )
        return RefResolutionResult(
            "static_check",
            criterion_id,
            ref,
            EnumRefStatus.FAIL,
            f"Unknown check: {ref!r}. See static_checks_registry.yaml for registered IDs.",
        )

    def _resolve_artifact(self, ref: str, criterion_id: str) -> RefResolutionResult:
        full = self.repo_root / ref
        if full.exists():
            return RefResolutionResult(
                "artifact",
                criterion_id,
                ref,
                EnumRefStatus.RESOLVED,
                f"Artifact found: {ref}",
            )
        return RefResolutionResult(
            "artifact",
            criterion_id,
            ref,
            EnumRefStatus.FAIL,
            f"Artifact not found: {ref}",
        )


def resolve_contract(
    contract_path: Path, resolver: ProofReferenceResolver
) -> list[RefResolutionResult]:
    """Load a contract YAML and resolve all proof_requirements.

    Returns empty list if no proof_requirements exist in the contract.
    """
    if yaml is None:
        return _resolve_contract_without_yaml(contract_path, resolver)

    data = yaml.safe_load(contract_path.read_text())
    results: list[RefResolutionResult] = []
    for req in data.get("requirements", []):
        for proof in req.get("proof_requirements", []):
            result = resolver.resolve(
                kind=proof.get("kind", ""),
                ref=proof.get("ref", ""),
                criterion_id=proof.get("criterion_id", ""),
            )
            results.append(result)
    return results


__all__ = [
    "EnumRefStatus",
    "ProofReferenceResolver",
    "RefResolutionResult",
    "resolve_contract",
]
