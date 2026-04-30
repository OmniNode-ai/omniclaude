# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Validate that deterministic SKILL.md claims have backing-node behavior.

OMN-9075 first slice: extract high-signal receipt/artifact/event claims from
SKILL.md files and fail when the backing node has no corresponding behavior.
This intentionally starts with deterministic patterns instead of broad NLP.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from enum import StrEnum
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict

from plugins.onex.skills._lib.validate_skill_backing_node import (
    _omnimarket_available,
    _resolve_omnimarket_nodes_root,
    extract_backing_node,
    load_allowlist,
)

_CLAIM_SECTION_RE = re.compile(
    r"^#{2,3}\s+(?P<title>purpose|overview|what it does|behavior|outputs|dod|definition of done)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_ANY_SECTION_RE = re.compile(r"^#{2,3}\s+", re.MULTILINE)
_STRICT_NODE_RE = re.compile(
    r"(?:backing\s+node|dispatch(?:es)?\s+to)\s+`?(?P<name>node_[a-z_0-9]+)`?",
    re.IGNORECASE,
)
_TOPIC_RE = re.compile(r"\b(?P<topic>onex\.(?:evt|cmd)\.[a-z0-9_.-]+\.v\d+)\b")
_PATH_RE = re.compile(
    r"`(?P<path>[^`]*(?:receipt|evidence|artifact|report)[^`]*)`", re.IGNORECASE
)
_CLAIM_RE = re.compile(
    r"\b(?P<verb>writes?|persists?|generates?|creates?|emits?|publishes?)\b"
    r"(?P<object>[^.\n]*(?:receipt|terminal event|completion event|artifact\s+to)[^.\n]*)",
    re.IGNORECASE,
)
_WRITE_BEHAVIOR_RE = re.compile(
    r"\b(write_text|write_bytes|open\([^)]*['\"]w|mkdir|json\.dump|yaml\.safe_dump)\b"
)


class EnumSkillClaimKind(StrEnum):
    """Deterministic claim kinds enforced by this first slice."""

    RECEIPT = "receipt"
    ARTIFACT = "artifact"
    TERMINAL_EVENT = "terminal_event"


class ModelSkillClaim(BaseModel):
    """A structured SKILL.md capability claim."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    skill_name: str
    skill_path: str
    node_name: str
    kind: EnumSkillClaimKind
    action_verb: str
    claimed_object: str
    side_effect: str
    sentence: str


class ModelSkillClaimViolation(BaseModel):
    """A claim that did not map to backing-node behavior."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    claim: ModelSkillClaim
    detail: str

    def __str__(self) -> str:
        return (
            f"VIOLATION skill={self.claim.skill_name!r} node={self.claim.node_name!r} "
            f"kind={self.claim.kind.value!r}\n"
            f"  claim: {self.claim.sentence}\n"
            f"  {self.detail}"
        )


def _extract_claim_sections(text: str) -> list[str]:
    sections: list[str] = []
    matches = list(_CLAIM_SECTION_RE.finditer(text))
    for match in matches:
        start = match.end()
        next_section = _ANY_SECTION_RE.search(text, start)
        end = next_section.start() if next_section else len(text)
        sections.append(text[start:end])
    return sections or [text]


def _clean_sentence(raw: str) -> str:
    text = raw.strip()
    text = re.sub(r"^\s*[-*]\s*", "", text)
    text = re.sub(r"^\s*\d+\.\s*", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _infer_node_name(skill_md_path: Path, text: str) -> str | None:
    node_name = extract_backing_node(skill_md_path)
    if node_name:
        return node_name
    match = _STRICT_NODE_RE.search(text)
    if match:
        return match.group("name")
    return None


def _infer_kind(claimed_object: str) -> EnumSkillClaimKind:
    lowered = claimed_object.lower()
    if "terminal event" in lowered or "completion event" in lowered:
        return EnumSkillClaimKind.TERMINAL_EVENT
    if "receipt" in lowered or "evidence" in lowered:
        return EnumSkillClaimKind.RECEIPT
    return EnumSkillClaimKind.ARTIFACT


def extract_claims_from_skill(skill_md_path: Path) -> list[ModelSkillClaim]:
    """Extract deterministic receipt/artifact/event claims from one SKILL.md."""
    text = skill_md_path.read_text(encoding="utf-8")
    node_name = _infer_node_name(skill_md_path, text)
    if node_name is None:
        return []

    claims: list[ModelSkillClaim] = []
    seen: set[tuple[str, str, str]] = set()
    for section in _extract_claim_sections(text):
        for raw_line in section.splitlines():
            sentence = _clean_sentence(raw_line)
            if not sentence:
                continue
            match = _CLAIM_RE.search(sentence)
            if not match:
                continue
            action = match.group("verb").lower()
            claimed_object = _clean_sentence(match.group("object"))
            kind = _infer_kind(claimed_object)
            topic_match = _TOPIC_RE.search(sentence)
            path_match = _PATH_RE.search(sentence)
            side_effect = ""
            if topic_match:
                side_effect = topic_match.group("topic")
            elif path_match:
                side_effect = path_match.group("path")
            elif kind is EnumSkillClaimKind.TERMINAL_EVENT:
                side_effect = "terminal_event"
            else:
                side_effect = claimed_object

            key = (action, claimed_object, side_effect)
            if key in seen:
                continue
            seen.add(key)
            claims.append(
                ModelSkillClaim(
                    skill_name=skill_md_path.parent.name,
                    skill_path=str(skill_md_path),
                    node_name=node_name,
                    kind=kind,
                    action_verb=action,
                    claimed_object=claimed_object,
                    side_effect=side_effect,
                    sentence=sentence,
                )
            )
    return claims


def extract_skill_claims(repo_root: Path) -> list[ModelSkillClaim]:
    """Extract deterministic claims from all skills in *repo_root*."""
    skills_root = repo_root / "plugins" / "onex" / "skills"
    if not skills_root.is_dir():
        return []
    claims: list[ModelSkillClaim] = []
    for skill_md in sorted(skills_root.glob("*/SKILL.md")):
        claims.extend(extract_claims_from_skill(skill_md))
    return claims


def _resolve_node_dir(repo_root: Path, node_name: str) -> Path | None:
    for base in _resolve_omnimarket_nodes_root(repo_root):
        candidate = base / node_name
        if candidate.is_dir():
            return candidate
    return None


def _node_sources(node_dir: Path) -> str:
    chunks: list[str] = []
    for path in sorted(node_dir.rglob("*.py")) + sorted(node_dir.glob("*.yaml")):
        try:
            chunks.append(path.read_text(encoding="utf-8"))
        except OSError:
            continue
    return "\n".join(chunks)


def _claim_has_behavior(claim: ModelSkillClaim, node_dir: Path) -> tuple[bool, str]:
    source = _node_sources(node_dir)
    lowered_source = source.lower()
    side_effect = claim.side_effect.lower()

    if claim.kind is EnumSkillClaimKind.TERMINAL_EVENT:
        contract_path = node_dir / "contract.yaml"
        if not contract_path.is_file():
            return False, f"contract.yaml missing at {contract_path}"
        contract = yaml.safe_load(contract_path.read_text(encoding="utf-8")) or {}
        contract_text = contract_path.read_text(encoding="utf-8")
        if side_effect != "terminal_event" and side_effect in contract_text:
            return True, ""
        if isinstance(contract, dict) and contract.get("terminal_event"):
            return True, ""
        return False, "claimed event emission but contract has no terminal_event"

    has_claim_marker = any(
        marker in lowered_source
        for marker in {
            "receipt",
            "evidence",
            "artifact",
            "report",
            side_effect,
            Path(side_effect).name.lower(),
        }
        if marker
    )
    has_write_behavior = bool(_WRITE_BEHAVIOR_RE.search(source))
    if has_claim_marker and has_write_behavior:
        return True, ""
    return (
        False,
        "claimed receipt/artifact side effect but backing node sources do not "
        "contain both the claimed object token and write behavior",
    )


def scan(repo_root: Path) -> list[str]:
    """Return human-readable aspiration violations for *repo_root*."""
    if not _omnimarket_available(repo_root):
        print(
            "validate-skill-aspiration: SKIPPED locally - omnimarket not found. "
            "Set $OMNIMARKET_ROOT or $OMNI_HOME to enable local enforcement.",
            file=sys.stderr,
        )
        return []

    allowlist = load_allowlist(repo_root)
    violations: list[str] = []
    for claim in extract_skill_claims(repo_root):
        if claim.skill_name in allowlist:
            continue
        node_dir = _resolve_node_dir(repo_root, claim.node_name)
        if node_dir is None:
            violations.append(
                str(
                    ModelSkillClaimViolation(
                        claim=claim,
                        detail=f"backing node directory not found for {claim.node_name}",
                    )
                )
            )
            continue
        ok, detail = _claim_has_behavior(claim, node_dir)
        if not ok:
            violations.append(str(ModelSkillClaimViolation(claim=claim, detail=detail)))
    return violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo_root", nargs="?", default=".")
    parser.add_argument(
        "--json", action="store_true", help="Print extracted claims as JSON"
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Validate claims against backing-node behavior",
    )
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root).resolve()
    if args.json and not args.validate:
        claims = extract_skill_claims(repo_root)
        print(json.dumps([claim.model_dump(mode="json") for claim in claims], indent=2))
        return 0

    violations = scan(repo_root)
    if violations:
        print(
            "validate-skill-aspiration: FAILED - SKILL.md claims without backing behavior\n",
            file=sys.stderr,
        )
        for violation in violations:
            print(violation, file=sys.stderr)
        return 2

    if not args.json:
        print("validate-skill-aspiration: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
