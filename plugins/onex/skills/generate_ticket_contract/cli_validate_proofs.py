# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""CLI wrapper for the proof reference resolver (OMN-4343).

Thin wrapper that delegates all logic to the proof_validation library.
No business logic duplication.

Usage::

    python cli_validate_proofs.py <contract.yaml> [--repo-root PATH] [--registry PATH] [--json]

Exit codes:

    0 — all refs RESOLVED or WARN
    1 — one or more refs FAIL
    2 — file not found / parse error
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# When run directly (python cli_validate_proofs.py), add the repo root to
# sys.path so the plugins package is importable. When imported as a module
# (e.g., in tests or via pytest), the root is already in pythonpath.
_REPO_ROOT = Path(__file__).resolve().parents[4]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from plugins.onex.skills.generate_ticket_contract.proof_validation import (  # noqa: E402
    EnumRefStatus,
    ProofReferenceResolver,
    RefResolutionResult,
    resolve_contract,
)

_DEFAULT_REGISTRY = Path(__file__).parent / "static_checks_registry.yaml"

_ICON = {
    EnumRefStatus.RESOLVED: "\u2705 RESOLVED",
    EnumRefStatus.WARN: "\u26a0\ufe0f  WARN",
    EnumRefStatus.FAIL: "\u274c FAIL",
}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cli_validate_proofs.py",
        description="Resolve proof references in a ticket contract YAML (v1 plausibility).",
    )
    parser.add_argument("contract", type=Path, help="Path to contract YAML file")
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path.cwd(),
        help="Repo root for resolving test/artifact paths (default: cwd)",
    )
    parser.add_argument(
        "--registry",
        type=Path,
        default=_DEFAULT_REGISTRY,
        help=f"Path to static_checks_registry.yaml (default: {_DEFAULT_REGISTRY})",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Output results as JSON (for CI baseline capture)",
    )
    return parser


def _results_to_dict(results: list[RefResolutionResult]) -> list[dict[str, str]]:
    return [
        {
            "criterion_id": r.criterion_id,
            "kind": r.kind,
            "ref": r.ref,
            "status": r.status.value,
            "message": r.message,
        }
        for r in results
    ]


def main(argv: list[str] | None = None) -> int:
    """Entry point. Returns exit code."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    contract_path: Path = args.contract
    repo_root: Path = args.repo_root
    registry: Path = args.registry
    json_output: bool = args.json_output

    if not contract_path.exists():
        msg = f"Contract file not found: {contract_path}"
        if json_output:
            print(json.dumps({"error": msg}))
        else:
            print(f"ERROR: {msg}", file=sys.stderr)
        return 2

    try:
        resolver = ProofReferenceResolver(repo_root=repo_root, registry_path=registry)
        results = resolve_contract(contract_path=contract_path, resolver=resolver)
    except Exception as exc:
        msg = f"Parse/resolution error: {exc}"
        if json_output:
            print(json.dumps({"error": msg}))
        else:
            print(f"ERROR: {msg}", file=sys.stderr)
        return 2

    if not results:
        advisory = "No proof_requirements found in contract — nothing to resolve."
        if json_output:
            print(json.dumps({"advisory": advisory, "results": []}))
        else:
            print(advisory)
        return 0

    if json_output:
        print(json.dumps({"results": _results_to_dict(results)}, indent=2))
    else:
        for r in results:
            icon = _ICON.get(r.status, r.status.value)
            print(f"  {icon}  [{r.criterion_id}] {r.kind}: {r.ref}")
            print(f"         {r.message}")

    fail_count = sum(1 for r in results if r.status == EnumRefStatus.FAIL)
    warn_count = sum(1 for r in results if r.status == EnumRefStatus.WARN)

    if not json_output:
        if fail_count:
            print(f"\nFAIL: {fail_count} ref(s) unresolvable.")
        else:
            suffix = f" ({warn_count} warning(s))" if warn_count else ""
            print(f"\nPASS{suffix}")

    return 1 if fail_count else 0


if __name__ == "__main__":
    sys.exit(main())
