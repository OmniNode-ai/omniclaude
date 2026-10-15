# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Hook and content capture stays raw: no redaction, no hashing (OMN-19513).

Operator RULING 2026-10-15T04:24:42Z (rolling work ledger): no redacted text goes on
the event bus; the ledger records everything, and encryption of the payload is an
option (one contract setting), never a scrub. The producer was changed to match; this
guard keeps it that way. It reads the capture producer's own surface and refuses a
change that brings a scrub, a content hash or a redaction field back:

* ``ModelHookContentRef`` and ``ModelHookContentRecord`` carry no digest or redaction
  field and carry ``value``;
* ``map_hook_stdin`` takes no scrubber or redaction parameter;
* ``hook_claude_capture`` and ``hook_content_capture`` use none of the retired scrub
  names;
* the capture contract's ``content_reference.fields`` lists ``value`` and no digest,
  and keeps the ``payload_encryption`` block with its ``enabled`` and
  ``key_secret_ref`` keys.

Every check takes source text, so each one has a negative control: the same check run on
a copy of the real source with the forbidden thing added must report it. The positive
control counts what each check inspected, so a check that matches nothing fails.

Paired with the pre-commit hook ``raw-capture-guard`` and the CI step in the Refusal
Surface job (a member of the required CI Summary umbrella).
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
MODEL_PATH = REPO / "src/omniclaude/hooks/model_claude_hook_event.py"
CONTRACT_PATH = (
    REPO / "src/omniclaude/hooks/contracts/contract_hook_claude_capture.yaml"
)
PRODUCER_PATHS = (
    REPO / "plugins/onex/hooks/lib/hook_claude_capture.py",
    REPO / "plugins/onex/hooks/lib/hook_content_capture.py",
)

CONTENT_MODELS = ("ModelHookContentRef", "ModelHookContentRecord")
#: A field of a content model that digests or marks redaction of the content.
FORBIDDEN_FIELDS = frozenset(
    {"sha256", "digest", "redaction_state", "matched_pattern_names"}
)
#: Names of the retired scrub path. Their return is the regression.
RETIRED_NAMES = frozenset(
    {
        "make_scrubber",
        "ContentScrubber",
        "ModelContentScrubResult",
        "redact_capture",
        "StoreSink",
    }
)
FORBIDDEN_PARAMETER_PARTS = ("scrub", "redact")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def content_model_findings(source: str) -> tuple[list[str], int]:
    """Digest or redaction fields on the content models, and the fields inspected."""
    findings: list[str] = []
    inspected = 0
    seen: set[str] = set()
    for node in ast.parse(source).body:
        if not isinstance(node, ast.ClassDef) or node.name not in CONTENT_MODELS:
            continue
        seen.add(node.name)
        names = {
            stmt.target.id
            for stmt in node.body
            if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name)
        }
        inspected += len(names)
        findings.extend(
            f"{node.name}.{name}: digest or redaction field"
            for name in sorted(names & FORBIDDEN_FIELDS)
        )
        if "value" not in names:
            findings.append(f"{node.name}: no raw 'value' field")
    findings.extend(
        f"{name}: class is missing" for name in CONTENT_MODELS if name not in seen
    )
    return findings, inspected


def mapper_findings(source: str) -> tuple[list[str], int]:
    """Scrub or redaction parameters of ``map_hook_stdin``, and parameters inspected."""
    for node in ast.parse(source).body:
        if isinstance(node, ast.FunctionDef) and node.name == "map_hook_stdin":
            args = node.args
            params = [a.arg for a in (*args.posonlyargs, *args.args, *args.kwonlyargs)]
            findings = [
                f"map_hook_stdin parameter '{p}': scrub or redaction input"
                for p in params
                if any(part in p.lower() for part in FORBIDDEN_PARAMETER_PARTS)
            ]
            return findings, len(params)
    return ["map_hook_stdin: function is missing"], 0


def retired_name_findings(source: str, label: str) -> tuple[list[str], int]:
    """Uses of the retired scrub names in one producer, and identifiers inspected."""
    tree = ast.parse(source)
    used: set[str] = set()
    inspected = 0
    for node in ast.walk(tree):
        names: list[str] = []
        if isinstance(node, ast.Name):
            names = [node.id]
        elif isinstance(node, ast.Attribute):
            names = [node.attr]
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names = [node.name]
        elif isinstance(node, ast.alias):
            names = [node.name.rsplit(".", 1)[-1], node.asname or node.name]
        inspected += len(names)
        used.update(n for n in names if n in RETIRED_NAMES)
    return [f"{label}: uses retired scrub name '{n}'" for n in sorted(used)], inspected


def contract_findings(text: str) -> tuple[list[str], int]:
    """Digest fields in the content reference, a missing encryption block, and keys read."""
    contract = yaml.safe_load(text)
    findings: list[str] = []
    fields = contract.get("content_reference", {}).get("fields", [])
    if "value" not in fields:
        findings.append("content_reference.fields: no raw 'value'")
    findings.extend(
        f"content_reference.fields: '{f}' is a digest or redaction field"
        for f in fields
        if f in FORBIDDEN_FIELDS
    )
    block = contract.get("payload_encryption")
    if not isinstance(block, dict) or not {"enabled", "key_secret_ref"} <= set(block):
        findings.append(
            "payload_encryption: block with enabled and key_secret_ref is missing"
        )
    return findings, len(fields) + (len(block) if isinstance(block, dict) else 0)


def all_findings() -> list[str]:
    findings: list[str] = []
    model_source = _read(MODEL_PATH)
    findings += content_model_findings(model_source)[0]
    findings += mapper_findings(model_source)[0]
    for path in PRODUCER_PATHS:
        findings += retired_name_findings(_read(path), path.name)[0]
    findings += contract_findings(_read(CONTRACT_PATH))[0]
    return findings


def test_capture_is_raw_today() -> None:
    assert all_findings() == []


def test_every_check_inspects_something() -> None:
    """Positive control: a check that matched nothing would pass on any tree."""
    model_source = _read(MODEL_PATH)
    assert content_model_findings(model_source)[1] >= 8
    assert mapper_findings(model_source)[1] >= 5
    for path in PRODUCER_PATHS:
        assert retired_name_findings(_read(path), path.name)[1] > 500
    assert contract_findings(_read(CONTRACT_PATH))[1] >= 6


def test_digest_field_on_content_ref_is_refused() -> None:
    mutated = _read(MODEL_PATH).replace(
        "    content_record_id: UUID\n\n\nclass ModelHookContentRecord",
        "    content_record_id: UUID\n    sha256: str\n\n\nclass ModelHookContentRecord",
        1,
    )
    assert mutated != _read(MODEL_PATH)
    assert content_model_findings(mutated)[0] == [
        "ModelHookContentRef.sha256: digest or redaction field"
    ]


@pytest.mark.parametrize("field", sorted(FORBIDDEN_FIELDS))
def test_each_forbidden_field_on_content_record_is_refused(field: str) -> None:
    source = _read(MODEL_PATH)
    marker = "class ModelHookContentRecord(BaseModel):\n"
    mutated = source.replace(marker, marker + f"    {field}: str | None = None\n", 1)
    assert mutated != source
    assert content_model_findings(mutated)[0] == [
        f"ModelHookContentRecord.{field}: digest or redaction field"
    ]


def test_value_field_dropped_from_content_ref_is_refused() -> None:
    source = _read(MODEL_PATH)
    mutated = source.replace(
        "    value: str\n    length: int = Field(ge=0)\n    content_record_id",
        "    length: int = Field(ge=0)\n    content_record_id",
        1,
    )
    assert mutated != source
    assert (
        "ModelHookContentRef: no raw 'value' field"
        in content_model_findings(mutated)[0]
    )


def test_scrubber_parameter_on_mapper_is_refused() -> None:
    source = _read(MODEL_PATH)
    mutated = source.replace(
        "    host: str | None = None,\n) -> ModelHookCaptureResult:",
        "    host: str | None = None,\n    scrubber: object | None = None,\n) -> ModelHookCaptureResult:",
        1,
    )
    assert mutated != source
    assert mapper_findings(mutated)[0] == [
        "map_hook_stdin parameter 'scrubber': scrub or redaction input"
    ]


@pytest.mark.parametrize("path", PRODUCER_PATHS, ids=lambda p: p.name)
@pytest.mark.parametrize("name", sorted(RETIRED_NAMES))
def test_retired_scrub_name_in_a_producer_is_refused(path: Path, name: str) -> None:
    mutated = _read(path) + f"\n\ndef _regression(value):\n    return {name}(value)\n"
    assert retired_name_findings(mutated, path.name)[0] == [
        f"{path.name}: uses retired scrub name '{name}'"
    ]
    mutated_import = f"from omniclaude.hooks.capture_redaction import {name}\n" + _read(
        path
    )
    assert retired_name_findings(mutated_import, path.name)[0] == [
        f"{path.name}: uses retired scrub name '{name}'"
    ]


def test_digest_in_contract_content_reference_is_refused() -> None:
    source = _read(CONTRACT_PATH)
    mutated = source.replace(
        "fields: [field, value, length, content_record_id]",
        "fields: [field, value, length, content_record_id, sha256]",
        1,
    )
    assert mutated != source
    assert contract_findings(mutated)[0] == [
        "content_reference.fields: 'sha256' is a digest or redaction field"
    ]


def test_missing_encryption_block_is_refused() -> None:
    source = _read(CONTRACT_PATH)
    mutated = source.replace(
        "payload_encryption:\n", "payload_encryption_removed:\n", 1
    )
    assert mutated != source
    assert contract_findings(mutated)[0] == [
        "payload_encryption: block with enabled and key_secret_ref is missing"
    ]
