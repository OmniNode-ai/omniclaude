# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-20001: every sibling-repo read in CI is at a pinned version, never a live branch.

Ruling 2026-10-01 (operator: "we can't have breaking changes without notifying
downstream"): each repo checks only itself, and any read of a sibling uses the
version this repo has PINNED (a lock rev, a release tag, a full commit sha),
never the sibling's live branch. A merge in one repo then cannot turn another
repo red; a new sibling version is integration-tested by the consumer before it
moves its pin.

These tests are the falsifier. A reusable-workflow ``uses:`` at ``@main``/``@dev``,
a sibling ``actions/checkout`` at a branch (or at no ref, which is the default
branch), a ``git clone`` of a sibling without a pin, and a producer reusable that
checks out omniclaude at a branch all fail here. The positive control proves the
detector flags a real violation rather than passing vacuously.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

pytestmark = pytest.mark.unit

_WORKFLOWS = Path(__file__).resolve().parents[2] / ".github" / "workflows"

_SIBLINGS = (
    "omnibase_core",
    "omnibase_compat",
    "omnibase_infra",
    "omnibase_spi",
    "omniintelligence",
    "omnimarket",
    "omnimemory",
    "onex_change_control",
)
_SIBLING_RE = "|".join(_SIBLINGS)
_FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
_RELEASE_TAG = re.compile(r"^v\d+\.\d+\.\d+$")
# A ref that is resolved from this repo's own uv.lock by an earlier step.
_LOCK_RESOLVED = re.compile(r"^\$\{\{\s*steps\.\w+_pin\.outputs\.(rev|tag)\s*\}\}$")
# OCC evidence DATA read at the exact commit a ticket's evidence names (a merge
# commit sha resolved and validated 40-hex by an earlier step), not sibling code.
_EVIDENCE_SHA = re.compile(
    r"^\$\{\{\s*steps\.(dod-evidence\.outputs\.source"
    r"|resolve_contract_compliance_evidence\.outputs\.occ_sha)\s*\}\}$"
)
_INPUT_REF = re.compile(r"^\$\{\{\s*inputs\.(?P<name>[\w-]+)\s*\}\}$")
_CLONE = re.compile(
    rf"git clone\b(?P<flags>[^\n]*?)https://github\.com/OmniNode-ai/(?P<repo>{_SIBLING_RE})\.git"
    r"(?:[^\n]*\\\n)*"
)

# Workflows that read a sibling's live branch on purpose, with the reason.
_EXEMPT = {
    # The sanctioned pin-mover: it reads omnimarket dev precisely to move the lock.
    "sibling-lock-refresh.yml": "moves the pin; reads the sibling's head by design",
}


def _jobs(doc: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    return list((doc.get("jobs") or {}).items())


def _violations(name: str, text: str) -> list[str]:
    if name in _EXEMPT:
        return []
    doc = yaml.safe_load(text)
    found: list[str] = []
    for job_id, job in _jobs(doc):
        uses = job.get("uses")
        if isinstance(uses, str):
            found += _check_uses(name, job_id, uses)
        for step in job.get("steps") or []:
            step_uses = step.get("uses")
            if isinstance(step_uses, str):
                found += _check_uses(name, job_id, step_uses)
                with_ = step.get("with") or {}
                repo = str(with_.get("repository", ""))
                short = repo.rsplit("/", maxsplit=1)[-1]
                if (
                    step_uses.startswith("actions/checkout")
                    and repo.startswith("OmniNode-ai/")
                    and short in _SIBLINGS
                ):
                    ref = str(with_.get("ref", "")).strip()
                    if not (
                        _FULL_SHA.match(ref)
                        or _LOCK_RESOLVED.match(ref)
                        or _EVIDENCE_SHA.match(ref)
                        or _input_defaults_to_sha(doc, ref)
                    ):
                        found.append(
                            f"{name}:{job_id}: checkout of {short} at ref {ref!r} "
                            "(not a full sha or a uv.lock-resolved pin step)"
                        )
                if (
                    repo == "OmniNode-ai/omniclaude"
                    and "workflow_call" in (doc.get("on") or doc.get(True) or {})
                    and not _FULL_SHA.match(str(with_.get("ref", "")))
                    and "steps.pin.outputs.sha" not in str(with_.get("ref", ""))
                ):
                    found.append(
                        f"{name}:{job_id}: producer reusable checks out omniclaude at "
                        f"{with_.get('ref')!r}, not job.workflow_sha"
                    )
            run = step.get("run")
            if isinstance(run, str):
                for m in _CLONE.finditer(run):
                    flags = m.group("flags")
                    pinned_tag = re.search(r'--branch\s+"?v[\w$.{}]+"?', flags)
                    if not pinned_tag and not re.search(
                        r"git -C [^\n]*fetch[^\n]*\"?\$\w+\"?", run
                    ):
                        found.append(
                            f"{name}:{job_id}: git clone of {m.group('repo')} "
                            f"without a version tag or fetched rev ({flags.strip()!r})"
                        )
    return found


def _input_defaults_to_sha(doc: dict[str, Any], ref: str) -> bool:
    """A reusable's ``inputs.<name>`` ref is a pin when its default is a full sha or a release tag."""
    m = _INPUT_REF.match(ref)
    if not m:
        return False
    on = doc.get("on") or doc.get(True) or {}
    inputs = ((on.get("workflow_call") or {}).get("inputs")) or {}
    default = str((inputs.get(m.group("name")) or {}).get("default", ""))
    return bool(_FULL_SHA.match(default) or _RELEASE_TAG.match(default))


def _check_uses(name: str, job_id: str, uses: str) -> list[str]:
    m = re.match(rf"OmniNode-ai/(?P<repo>{_SIBLING_RE})/[^@]+@(?P<ref>\S+)", uses)
    if m and not _FULL_SHA.match(m.group("ref")):
        return [f"{name}:{job_id}: uses {uses} (ref is not a full sha)"]
    return []


def test_no_workflow_reads_a_sibling_at_a_live_branch() -> None:
    violations: list[str] = []
    for path in sorted(_WORKFLOWS.glob("*.yml")):
        violations += _violations(path.name, path.read_text(encoding="utf-8"))
    assert not violations, "\n".join(violations)


def test_positive_control_a_live_branch_read_is_flagged() -> None:
    dirty = """
name: dirty
on: workflow_call
jobs:
  a:
    uses: OmniNode-ai/omnibase_core/.github/workflows/occ-preflight.yml@main
  b:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
        with:
          repository: OmniNode-ai/omnimarket
          ref: dev
      - uses: actions/checkout@v7
        with:
          repository: OmniNode-ai/onex_change_control
      - uses: actions/checkout@v7
        with:
          repository: OmniNode-ai/omniclaude
          ref: main
      - run: git clone --depth 1 --branch dev https://github.com/OmniNode-ai/omnibase_core.git ../c
"""
    found = _violations("dirty.yml", dirty)
    assert len(found) == 5, found


def test_positive_control_pinned_reads_pass() -> None:
    clean = """
name: clean
on: pull_request
jobs:
  b:
    uses: OmniNode-ai/omnibase_core/.github/workflows/occ-preflight.yml@52851458622f368c3b596c82bf810bc6acce1d5e
  c:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
        with:
          repository: OmniNode-ai/omnimarket
          ref: ${{ steps.om_pin.outputs.rev }}
"""
    assert _violations("clean.yml", clean) == []


def test_registry_gate_pins_omnimarket_to_the_lock_not_a_branch() -> None:
    """The finding's known positive: Registry Consistency read a feature branch."""
    doc = yaml.safe_load((_WORKFLOWS / "ci.yml").read_text(encoding="utf-8"))
    steps = doc["jobs"]["registry-consistency"]["steps"]
    checkout = next(
        s
        for s in steps
        if s.get("uses", "").startswith("actions/checkout")
        and (s.get("with") or {}).get("repository") == "OmniNode-ai/omnimarket"
    )
    assert checkout["with"]["ref"] == "${{ steps.om_pin.outputs.rev }}"
    resolver = next(s for s in steps if s.get("id") == "om_pin")
    assert "uv.lock" in resolver["run"]
