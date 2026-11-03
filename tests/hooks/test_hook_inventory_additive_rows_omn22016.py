# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The additive binding rows are inventoried (OMN-22016, plan task TC.11, AC6)."""

from __future__ import annotations

import importlib.util
import re
from datetime import date
from enum import StrEnum
from pathlib import Path

import pytest
import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[2]
INVENTORY = REPO / "plugins/onex/hooks/contracts/hook_inventory.yaml"
TODAY = date(2026, 11, 3)
ROWS = {
    "session_start": ("SessionStart", 5000),
    "agent_spawn": ("SubagentStart", 3000),
    "per_prompt": ("UserPromptSubmit", 500),
}


class Code(StrEnum):
    """What the check found wrong."""

    ROW_UNINVENTORIED = "ADDITIVE_ROW_UNINVENTORIED"
    ENTRY_ROW_MISMATCH = "ADDITIVE_ENTRY_ROW_MISMATCH"
    REVIEW_LAPSED = "ADDITIVE_REVIEW_LAPSED"


class _Restoration(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: str = Field(min_length=1)
    reenable_ticket: str = Field(pattern=r"^OMN-\d+$")
    action: str = Field(min_length=1)


class _Canary(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    command: str = Field(min_length=1)
    expect: str = Field(min_length=1)


class _Entry(BaseModel):
    """One additive_bindings entry: a missing typed field is a validation error naming it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    binding: str = Field(min_length=1)
    event: str = Field(min_length=1)
    profile: str = Field(min_length=1)
    latency_budget_ms: int = Field(gt=0)
    owner: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    review_by: date
    restoration: _Restoration
    canary: _Canary


class _Finding(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    code: Code
    binding: str
    detail: str


class _Result(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    findings: tuple[_Finding, ...] = ()


def _additive_rows(contract: Path | None) -> dict[str, dict[str, object]]:
    if contract is None or not contract.is_file():
        return {}
    raw = yaml.safe_load(contract.read_text(encoding="utf-8"))
    rows = (((raw or {}).get("client_bindings") or {}).get("claude_code") or {}).get(
        "bindings"
    ) or []
    return {str(row["name"]): row for row in rows if row.get("kind") == "additive"}


def check_additive_inventory(
    inventory: Path, contract: Path | None, today: date
) -> _Result:
    """Every additive row has a current entry that agrees with it; no entry is past review_by.

    An entry whose row the installed omnimarket does not declare yet is not a finding, because
    a release that predates the rows declares none. This lives in a test and not in
    hook_inventory.py: that file is baselined under the canonical-file-shape ratchet and only shrinks.
    """
    declared = yaml.safe_load(inventory.read_text(encoding="utf-8"))
    entries = tuple(
        _Entry.model_validate(raw)
        for raw in (declared or {}).get("additive_bindings", [])
    )
    by_name = {entry.binding: entry for entry in entries}
    findings: list[_Finding] = []
    for name, row in _additive_rows(contract).items():
        entry = by_name.get(name)
        if entry is None:
            findings.append(
                _Finding(
                    code=Code.ROW_UNINVENTORIED,
                    binding=name,
                    detail="an additive row of the adapter contract has no additive_bindings entry",
                )
            )
            continue
        for field, declared_value, actual in (
            ("event", entry.event, row.get("hook_event")),
            ("profile", entry.profile, row.get("profile")),
            (
                "latency_budget_ms",
                entry.latency_budget_ms,
                row.get("latency_budget_ms"),
            ),
        ):
            if declared_value != actual:
                findings.append(
                    _Finding(
                        code=Code.ENTRY_ROW_MISMATCH,
                        binding=name,
                        detail=f"{field}: inventory {declared_value!r}, adapter contract {actual!r}",
                    )
                )
    findings.extend(
        _Finding(
            code=Code.REVIEW_LAPSED,
            binding=entry.binding,
            detail=f"review_by {entry.review_by.isoformat()} has passed (today is {today.isoformat()})",
        )
        for entry in entries
        if entry.review_by < today
    )
    return _Result(findings=tuple(findings))


def _contract(tmp_path: Path, **overrides: dict[str, object]) -> Path:
    rows = []
    for name, (event, budget) in ROWS.items():
        row: dict[str, object] = {
            "name": name,
            "kind": "additive",
            "hook_event": event,
            "profile": name,
            "latency_budget_ms": budget,
        }
        row.update(overrides.get(name, {}))
        rows.append(row)
    path = tmp_path / "adapter-contract.yaml"
    path.write_text(
        yaml.safe_dump({"client_bindings": {"claude_code": {"bindings": rows}}})
    )
    return path


def _check(contract: Path | None, today: date = TODAY, inventory: Path = INVENTORY):
    return check_additive_inventory(inventory, contract, today)


def _inventory_without(tmp_path: Path, field: str) -> Path:
    """The shipped inventory with `field` removed from the session_start additive entry."""
    text = INVENTORY.read_text(encoding="utf-8")
    start = text.index('  - binding: "session_start"')
    end = text.index('  - binding: "agent_spawn"')
    lines = text[start:end].splitlines(keepends=True)
    index = next(i for i, line in enumerate(lines) if re.match(rf"^ +{field}:", line))
    indent = len(lines[index]) - len(lines[index].lstrip())
    stop = index + 1
    while stop < len(lines) and (
        not lines[stop].strip() or len(lines[stop]) - len(lines[stop].lstrip()) > indent
    ):
        stop += 1
    stripped = "".join(lines[:index] + lines[stop:])
    path = tmp_path / "hook_inventory.yaml"
    path.write_text(text[:start] + stripped + text[end:], encoding="utf-8")
    return path


def test_hook_inventory_additive_rows_each_row_has_a_passing_entry(tmp_path) -> None:
    assert _check(_contract(tmp_path)).findings == ()


def test_hook_inventory_additive_rows_the_shipped_inventory_agrees_with_the_installed_contract() -> (
    None
):
    """Whatever omnimarket the environment carries: no rows, or rows that the entries match."""
    spec = importlib.util.find_spec(
        "omnimarket.nodes.node_claude_code_hook_adapter_effect"
    )
    contract = (
        Path(next(iter(spec.submodule_search_locations))) / "contract.yaml"
        if spec is not None and spec.submodule_search_locations
        else None
    )
    assert _check(contract).findings == ()


@pytest.mark.parametrize("field", ["review_by", "reenable_ticket"])
def test_hook_inventory_additive_rows_an_entry_missing_a_field_fails(
    tmp_path, field: str
) -> None:
    with pytest.raises(ValidationError, match=field):
        _check(_contract(tmp_path), inventory=_inventory_without(tmp_path, field))


@pytest.mark.parametrize("field", ["owner", "reason", "restoration", "canary"])
def test_hook_inventory_additive_rows_every_other_typed_field_is_required_too(
    tmp_path, field: str
) -> None:
    with pytest.raises(ValidationError, match=field):
        _check(_contract(tmp_path), inventory=_inventory_without(tmp_path, field))


def test_hook_inventory_additive_rows_a_row_with_no_entry_is_a_finding(
    tmp_path,
) -> None:
    contract = tmp_path / "ghost-contract.yaml"
    contract.write_text(
        yaml.safe_dump(
            {
                "client_bindings": {
                    "claude_code": {
                        "bindings": [
                            {
                                "name": "ghost_row",
                                "kind": "additive",
                                "hook_event": "SessionStart",
                                "profile": "session_start",
                                "latency_budget_ms": 5000,
                            }
                        ]
                    }
                }
            }
        )
    )
    findings = _check(contract).findings
    assert [(f.code, f.binding) for f in findings] == [
        (Code.ROW_UNINVENTORIED, "ghost_row")
    ]


def test_hook_inventory_additive_rows_an_entry_that_disagrees_with_its_row_is_a_finding(
    tmp_path,
) -> None:
    contract = _contract(
        tmp_path,
        agent_spawn={"latency_budget_ms": 2000},
        per_prompt={"hook_event": "PostToolUse"},
    )
    assert sorted((f.code, f.binding) for f in _check(contract).findings) == [
        (Code.ENTRY_ROW_MISMATCH, "agent_spawn"),
        (Code.ENTRY_ROW_MISMATCH, "per_prompt"),
    ]


def test_hook_inventory_additive_rows_a_lapsed_review_date_is_a_finding(
    tmp_path,
) -> None:
    findings = _check(_contract(tmp_path), today=date(2027, 1, 1)).findings
    assert sorted(f.binding for f in findings) == sorted(ROWS)
    assert {f.code for f in findings} == {Code.REVIEW_LAPSED}


def test_hook_inventory_additive_rows_an_entry_whose_row_is_not_declared_yet_is_clean() -> (
    None
):
    assert _check(None).findings == ()
