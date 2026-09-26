#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Reject GitHub Actions contexts used where GitHub cannot resolve them."""

from __future__ import annotations

import re
import sys
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import NamedTuple, cast

import yaml

_WORKFLOWS_DIR = Path(".github/workflows")
_EXPRESSION_RE = re.compile(r"\$\{\{(?P<body>.*?)\}\}", re.DOTALL)
_STRING_LITERAL_RE = re.compile(r"'(?:[^']|'')*'|\"(?:\\.|[^\"\\])*\"", re.DOTALL)
_CONTEXT_RE = re.compile(r"(?<![\w.-])(?P<context>[A-Za-z_]\w*)(?=\.|\[)")

_WORKFLOW_CONTEXTS: dict[str, tuple[str, ...]] = {
    "env": ("github", "secrets", "inputs", "vars"),
    "run-name": ("github", "inputs", "vars"),
    "concurrency": ("github", "inputs", "vars"),
}

_JOB_BASE = ("github", "needs", "strategy", "matrix", "vars", "inputs")
_JOB_CONTEXTS: dict[str, tuple[str, ...]] = {
    "if": ("github", "needs", "vars", "inputs"),
    "env": ("github", "needs", "strategy", "matrix", "vars", "secrets", "inputs"),
    "runs-on": _JOB_BASE,
    "name": _JOB_BASE,
    "timeout-minutes": _JOB_BASE,
    "continue-on-error": _JOB_BASE,
    "concurrency": _JOB_BASE,
    "environment": _JOB_BASE,
    "container": (*_JOB_BASE, "secrets"),
    "services": (*_JOB_BASE, "secrets"),
    "strategy": _JOB_BASE,
    "outputs": (
        "github",
        "needs",
        "strategy",
        "matrix",
        "job",
        "runner",
        "env",
        "vars",
        "secrets",
        "steps",
        "inputs",
    ),
    "with": _JOB_BASE,
    "secrets": (*_JOB_BASE, "secrets"),
}


class Finding(NamedTuple):
    """One context used outside its documented availability surface."""

    path: Path
    key_path: str
    context: str
    allowed: tuple[str, ...]

    def render(self) -> str:
        allowed = ", ".join(self.allowed)
        return (
            f'{self.path.as_posix()}: {self.key_path}: context "{self.context}" '
            f"is not allowed here (allowed: {allowed})"
        )


def _mapping(value: object) -> Mapping[object, object] | None:
    return value if isinstance(value, Mapping) else None


def _strings(value: object) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for child in value.values():
            yield from _strings(child)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for child in value:
            yield from _strings(child)


def _body_contexts(body: str) -> set[str]:
    body = _STRING_LITERAL_RE.sub("", body)
    body = re.sub(r"\s*\.\s*", ".", body)
    return {match.group("context") for match in _CONTEXT_RE.finditer(body)}


def _contexts(value: object, *, bare_expression: bool = False) -> set[str]:
    contexts: set[str] = set()
    for text in _strings(value):
        expressions = [match.group("body") for match in _EXPRESSION_RE.finditer(text)]
        # A job-level `if:` is evaluated as an expression with or without the
        # ${{ }} delimiters, so an undelimited condition is its own body.
        if bare_expression and not expressions:
            expressions = [text]
        for body in expressions:
            contexts.update(_body_contexts(body))
    return contexts


def _find_invalid_contexts(
    *, path: Path, key_path: str, value: object, allowed: tuple[str, ...]
) -> list[Finding]:
    bare = key_path.endswith(".if")
    return [
        Finding(path, key_path, context, allowed)
        for context in sorted(_contexts(value, bare_expression=bare) - set(allowed))
    ]


def check_workflow(path: Path) -> list[Finding]:
    """Return invalid context references in one workflow."""
    loaded = cast("object", yaml.safe_load(path.read_text(encoding="utf-8")))
    workflow = _mapping(loaded)
    if workflow is None:
        raise ValueError(f"{path} must contain a YAML mapping")

    findings: list[Finding] = []
    for key, allowed in _WORKFLOW_CONTEXTS.items():
        if key in workflow:
            findings.extend(
                _find_invalid_contexts(
                    path=path, key_path=key, value=workflow[key], allowed=allowed
                )
            )

    jobs = _mapping(workflow.get("jobs"))
    if jobs is None:
        return findings

    for job_id, job_value in jobs.items():
        job = _mapping(job_value)
        if job is None:
            continue
        for key, allowed in _JOB_CONTEXTS.items():
            if key in job:
                findings.extend(
                    _find_invalid_contexts(
                        path=path,
                        key_path=f"jobs.{job_id}.{key}",
                        value=job[key],
                        allowed=allowed,
                    )
                )
    return findings


def check_workflows(paths: Sequence[Path]) -> list[Finding]:
    """Return findings from all supplied workflow paths."""
    return [finding for path in paths for finding in check_workflow(path)]


def _default_paths() -> list[Path]:
    return sorted({*_WORKFLOWS_DIR.glob("*.yml"), *_WORKFLOWS_DIR.glob("*.yaml")})


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    paths = [Path(arg) for arg in args] if args else _default_paths()
    findings = check_workflows(paths)
    if findings:
        for finding in findings:
            print(finding.render())
        return 1

    print(f"workflow expression contexts: {len(paths)} files, 0 findings")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
