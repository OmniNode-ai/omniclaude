# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Rule 15 of the ticket-creation guard: a defect binds to a diagnosis first.

Criteria authored before a diagnosis describe a defect that turns out not to
exist, and the work that fixes the real defect then matches no criterion, so the
ticket cannot close on its own evidence (81 of 1,122 terminal rows in 7 days,
7.2 %, reported a falsified premise). A create whose title or labels read as a
defect must therefore carry a ``Diagnosis:`` line, a line of its own, that
resolves to a durable artifact: a ledger line citation, a pull request or a
``file:line``.

The vocabulary and the citation forms are ``ticket_creation_policy.json``'s
``defect_diagnosis`` object; this module spells none of them. Ledger citations
are resolved against the rolling ledger and its rolled archive; a pull request
and a ``file:line`` are checked for shape only, because this hook runs without
GitHub or repository access.

Lifted out of ``plugins/onex/hooks/lib/ticket_creation_guard.py`` so the guard
script, a baselined mod file that may only shrink under the canonical-file-shape
ratchet, can take the rule without growing. The guard loads this module by path
and runs it under a bare interpreter with no ``omniclaude`` package, so it
imports the standard library only. The decisions are pure functions of what they
are handed; the filesystem is touched only by :func:`ledger_line_lookup`.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import NamedTuple

#: ``resolution`` values a citation form may declare.
_RESOLUTIONS = frozenset({"ledger", "shape"})

#: The resolved path and line a ledger citation names, answering whether that
#: line exists and is not blank. ``None`` seam means no ledger is readable.
LedgerLineLookup = Callable[[str, int], bool]


class CitationForm(NamedTuple):
    """One declared form a ``Diagnosis:`` citation may take."""

    id: str
    pattern: re.Pattern[str]
    example: str
    resolution: str


class DiagnosisPolicy(NamedTuple):
    """The ``defect_diagnosis`` object of the ticket-creation policy."""

    title_terms: tuple[str, ...]
    label_names: frozenset[str]
    line: re.Pattern[str]
    forms: tuple[CitationForm, ...]


def _strings(raw: object, key: str, source: Path, error: type[Exception]) -> list[str]:
    if not isinstance(raw, list) or not raw:
        raise error(f"{source}: 'defect_diagnosis.{key}' must be a non-empty list")
    out: list[str] = []
    for entry in raw:
        if not isinstance(entry, str) or not entry.strip():
            raise error(
                f"{source}: 'defect_diagnosis.{key}' has a blank or non-string "
                f"entry {entry!r}"
            )
        out.append(entry.strip())
    return out


def _pattern(
    raw: object, label: str, source: Path, error: type[Exception]
) -> re.Pattern[str]:
    if not isinstance(raw, str) or not raw:
        raise error(f"{source}: {label} must be a non-empty regex string, got {raw!r}")
    try:
        return re.compile(raw, re.MULTILINE)
    except re.error as exc:
        raise error(f"{source}: {label} {raw!r} is not a regex ({exc})") from exc


def load_policy(raw: object, source: Path, error: type[Exception]) -> DiagnosisPolicy:
    """Read the ``defect_diagnosis`` object, or raise ``error``.

    No default: a missing or malformed object refuses every create until it is
    repaired, rather than quietly retiring the rule.
    """
    if not isinstance(raw, dict):
        raise error(f"{source}: 'defect_diagnosis' must be an object, got {raw!r}")
    line = _pattern(
        raw.get("line_pattern"), "defect_diagnosis.line_pattern", source, error
    )
    if "citation" not in line.groupindex:
        raise error(
            f"{source}: 'defect_diagnosis.line_pattern' declares no 'citation' "
            "group, so a matching line names nothing to resolve"
        )
    raw_forms = raw.get("citation_forms")
    if not isinstance(raw_forms, list) or not raw_forms:
        raise error(
            f"{source}: 'defect_diagnosis.citation_forms' must be a non-empty "
            "list; a rule with no form refuses every defect create"
        )
    forms: list[CitationForm] = []
    for entry in raw_forms:
        if not isinstance(entry, dict):
            raise error(f"{source}: citation form {entry!r} is not an object")
        form_id = entry.get("id")
        example = entry.get("example")
        resolution = entry.get("resolution")
        if not isinstance(form_id, str) or not form_id:
            raise error(f"{source}: a citation form declares no id: {entry!r}")
        if not isinstance(example, str) or not example:
            raise error(f"{source}: citation form {form_id!r} declares no example")
        if resolution not in _RESOLUTIONS:
            raise error(
                f"{source}: citation form {form_id!r} resolution {resolution!r} "
                f"is not one of {sorted(_RESOLUTIONS)}"
            )
        pattern = _pattern(
            entry.get("pattern"), f"citation form {form_id!r} pattern", source, error
        )
        if resolution == "ledger" and not {"path", "line"} <= set(pattern.groupindex):
            raise error(
                f"{source}: ledger citation form {form_id!r} must declare 'path' "
                "and 'line' groups"
            )
        forms.append(CitationForm(form_id, pattern, example, resolution))
    return DiagnosisPolicy(
        title_terms=tuple(
            _strings(raw.get("defect_title_terms"), "defect_title_terms", source, error)
        ),
        label_names=frozenset(
            n.lower()
            for n in _strings(
                raw.get("defect_label_names"), "defect_label_names", source, error
            )
        ),
        line=line,
        forms=tuple(forms),
    )


def _label_names(tool_input: Mapping[str, object]) -> set[str]:
    raw = tool_input.get("labels", tool_input.get("label"))
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        return set()
    return {x.strip().lower() for x in raw if isinstance(x, str) and x.strip()}


def defect_signals(
    title: str, tool_input: Mapping[str, object], policy: DiagnosisPolicy
) -> list[str]:
    """What makes this create defect-shaped: title terms (word-bounded) and labels."""
    hits = [
        term
        for term in policy.title_terms
        if re.search(rf"(?<!\w){re.escape(term)}(?!\w)", title, re.IGNORECASE)
    ]
    hits.extend(sorted(_label_names(tool_input) & policy.label_names))
    return hits


def _citations(description: str, policy: DiagnosisPolicy) -> list[str]:
    cited: list[str] = []
    for match in policy.line.finditer(description):
        text = match.group("citation").replace("`", "").strip()
        if text:
            cited.append(text)
    return cited


def _resolves(
    citation: str, policy: DiagnosisPolicy, ledger: LedgerLineLookup | None
) -> bool:
    for form in policy.forms:
        match = form.pattern.match(citation)
        if match is None:
            continue
        if form.resolution == "shape":
            return True
        return ledger is not None and ledger(
            match.group("path"), int(match.group("line"))
        )
    return False


def _spellings(policy: DiagnosisPolicy) -> str:
    return " | ".join(f"'{form.example}'" for form in policy.forms)


def findings(
    tool_input: Mapping[str, object],
    title: str,
    description: str,
    policy: DiagnosisPolicy,
    ledger: LedgerLineLookup | None,
) -> list[dict[str, str]]:
    """Rule 15 for one create, as ``{code, field, reason, fix}`` dicts."""
    signals = defect_signals(title, tool_input, policy)
    if not signals:
        return []
    cited = _citations(description, policy)
    if any(_resolves(c, policy, ledger) for c in cited):
        return []
    if not cited:
        return [
            {
                "code": "missing_diagnosis",
                "field": "description",
                "reason": (
                    f"the create reads as a defect ({', '.join(signals)}) and "
                    "carries no Diagnosis: line, so its criteria are written "
                    "before the defect is understood and the work that fixes "
                    "the real defect may match none of them"
                ),
                "fix": (
                    "diagnose first, then add a line of its own, unbulleted, "
                    f"reading 'Diagnosis: <citation>' where the citation is one of "
                    f"{_spellings(policy)}"
                ),
            }
        ]
    return [
        {
            "code": "unresolvable_diagnosis",
            "field": "description",
            "reason": (
                "no Diagnosis: line resolves to a durable artifact; could not "
                "resolve " + ", ".join(f"'{c}'" for c in cited)
            ),
            "fix": (
                "cite an artifact that exists, spelled as one of "
                f"{_spellings(policy)}; a ledger citation must name a line that "
                "is present in the rolling ledger or its archive"
            ),
        }
    ]


def ledger_line_lookup(ledger: Path | None) -> LedgerLineLookup:
    """Bind a ledger citation to the rolling ledger and its rolled archive.

    A cited path resolves by file name: the live ledger itself, else the same
    name under its ``archive`` directory. Symlinks are never followed, and an
    unreadable file resolves nothing, so an unreadable ledger admits nothing.
    """

    def lookup(path: str, line: int) -> bool:
        if ledger is None or line < 1:
            return False
        name = Path(path).name
        candidates = [ledger] if name == ledger.name else []
        archive = ledger.parent / "archive"
        if archive.is_dir() and not archive.is_symlink():
            candidates.append(archive / name)
        for candidate in candidates:
            if candidate.is_symlink() or not candidate.is_file():
                continue
            try:
                lines = candidate.read_text(encoding="utf-8").splitlines()
            except OSError:
                continue
            return line <= len(lines) and bool(lines[line - 1].strip())
        return False

    return lookup
