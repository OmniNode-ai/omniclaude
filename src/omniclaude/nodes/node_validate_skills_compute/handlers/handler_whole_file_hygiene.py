# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Whole-file public-repo hygiene leg for a published plugin tree (OMN-22273).

The retirement plan's Gate (T2): the repository's hygiene gate runs in report mode and
fails five classes on added lines, so a tree copied in whole could pass it with every
finding in a line the change "did not add". This leg runs the gate's own scanner over
**every file** under one directory (``plugins/omni`` by default) and fails on all ten
content classes, then makes a second, targeted deployment-config run with the model
vocabulary. It passes the gate an explicit mode and class set (``--only-classes``
semantics), so the repository config's ``enforce_scope: added-lines`` neither refuses a
path-only run nor narrows the verdict. The gate script is loaded, not edited.

Exit codes, which the callers and the tests tell apart:

* 0 -- CLEAN: every file scanned, no finding.
* 1 -- DETECTED: at least one finding; each is reported as path, line and class with
  the scrub-map keys the class becomes. The line's text is never printed.
* 2 -- CONFIG_ERROR: the leg did not run to a verdict (missing vocabulary, missing or
  malformed scrub map, absent or empty scope, a gate refusal). Never a detection.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Final

import yaml
from pydantic import ValidationError

from omniclaude.nodes.node_validate_skills_compute.enums.enum_whole_file_hygiene_outcome import (
    EnumWholeFileHygieneOutcome,
)
from omniclaude.nodes.node_validate_skills_compute.models.model_whole_file_hygiene import (
    ModelScrubMap,
    ModelWholeFileFinding,
    ModelWholeFileHygieneRequest,
    ModelWholeFileHygieneResult,
)

#: The content classes the leg fails on (the plan's Gate T2 list). The informational
#: ``self-granted-annotation`` class is deliberately not among them.
WHOLE_FILE_CLASSES: Final[frozenset[str]] = frozenset(
    {
        "private-repo-name",
        "internal-kb-prose",
        "public-doc-private-repo",
        "lab-config",
        "person-name",
        "private-network",
        "machine-path",
        "cloud-identity",
        "secret-shaped",
        "tracker-url",
    }
)
DEPLOYMENT_CONFIG_CLASS: Final = "deployment-config"
VOCABULARY_ENV: Final = "OMNI_HYGIENE_VOCAB_PATH"
SCRUB_MAP_RELATIVE: Final = "config/public_repo_hygiene_scrub_map.yaml"
GATE_RELATIVE: Final = "scripts/public_repo_hygiene_gate.py"
_GATE_MODULE_NAME: Final = "omniclaude_whole_file_hygiene_gate"


class _LegConfigError(Exception):
    """The leg could not run to a verdict."""


def load_scrub_map(path: Path) -> ModelScrubMap:
    """Parse the scrub map data file; any defect is a configuration error."""
    if not path.is_file():
        raise _LegConfigError(f"scrub map not found at {path}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("version") != 1:
            raise _LegConfigError(f"{path}: expected a mapping with 'version: 1'")
        scrub_map = ModelScrubMap.model_validate({"rows": data.get("rows")})
    except (yaml.YAMLError, ValidationError, OSError, UnicodeError) as exc:
        raise _LegConfigError(f"{path}: not a valid scrub map ({exc})") from exc
    if not scrub_map.rows:
        raise _LegConfigError(f"{path}: the scrub map has no rows")
    ids = [row.row_id for row in scrub_map.rows]
    if len(set(ids)) != len(ids):
        raise _LegConfigError(f"{path}: duplicate row_id in the scrub map")
    unknown = sorted(
        {c for row in scrub_map.rows for c in row.finding_classes} - WHOLE_FILE_CLASSES
    )
    if unknown:
        raise _LegConfigError(f"{path}: row names unknown finding class(es) {unknown}")
    return scrub_map


def _load_gate(path: Path) -> ModuleType:
    if not path.is_file():
        raise _LegConfigError(f"hygiene gate not found at {path}")
    spec = importlib.util.spec_from_file_location(_GATE_MODULE_NAME, path)
    if spec is None or spec.loader is None:
        raise _LegConfigError(f"hygiene gate at {path} cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[_GATE_MODULE_NAME] = module
    spec.loader.exec_module(module)
    return module


def _scope_files(repo_root: Path, scope_dir: str) -> list[str]:
    scope = repo_root / scope_dir
    if not scope.is_dir():
        raise _LegConfigError(
            f"scope directory {scope_dir} does not exist under {repo_root}; "
            "a leg pointed at nothing is not a pass"
        )
    files = sorted(
        p.relative_to(repo_root).as_posix()
        for p in scope.rglob("*")
        if p.is_file() and ".git" not in p.relative_to(scope).parts
    )
    if not files:
        raise _LegConfigError(f"scope directory {scope_dir} holds no file to scan")
    return files


def _vocabulary_path(request: ModelWholeFileHygieneRequest) -> Path:
    path = request.vocabulary
    if path is None:
        env = os.environ.get(VOCABULARY_ENV)
        if not env:
            raise _LegConfigError(
                f"no --vocabulary and {VOCABULARY_ENV} is not set, so the private "
                "denylist vocabulary cannot be located"
            )
        path = Path(env)
    if not path.is_file():
        raise _LegConfigError(f"vocabulary not found at {path}")
    return path


def _beside(vocab: Path, given: Path | None, basename: str, label: str) -> Path:
    path = given if given is not None else vocab.parent / basename
    if not path.is_file():
        raise _LegConfigError(
            f"{label} not found at {path}; the leg refuses rather than skipping the class"
        )
    return path


def _run(request: ModelWholeFileHygieneRequest) -> ModelWholeFileHygieneResult:
    repo_root = request.repo_root.resolve()
    scrub_map = load_scrub_map(request.scrub_map or repo_root / SCRUB_MAP_RELATIVE)
    gate = _load_gate(request.gate_script or repo_root / GATE_RELATIVE)
    vocab = _vocabulary_path(request)
    lab_vocab = _beside(
        vocab, request.lab_vocabulary, gate.LAB_VOCABULARY_BASENAME, "lab vocabulary"
    )
    model_vocab = _beside(
        vocab,
        request.model_vocabulary,
        gate.MODEL_VOCABULARY_BASENAME,
        "model vocabulary",
    )
    paths = _scope_files(repo_root, request.scope_dir)

    try:
        _, blocking, _ = gate.run(
            repo_root,
            vocab,
            "enforce",
            paths,
            lab_vocab_path=lab_vocab,
            only_classes=WHOLE_FILE_CLASSES,
            added_lines=None,
        )
        deployment_vocab = gate.build_deployment_vocabulary(vocab, model_vocab)
        _, _, deployment_failing = gate.run_deployment_config(
            repo_root,
            "enforce",
            paths,
            enforce_scope=gate.WHOLE_TREE_SCOPE,
            added_lines=None,
            vocab=deployment_vocab,
        )
    except gate.ConfigError as exc:
        raise _LegConfigError(str(exc)) from exc
    except subprocess.CalledProcessError as exc:
        raise _LegConfigError(f"git failed: {exc}") from exc

    findings = tuple(
        ModelWholeFileFinding(
            path=f.path,
            line_no=f.line_no,
            class_name=f.class_name,
            becomes=scrub_map.keys_for_class(f.class_name),
        )
        for f in [*blocking, *deployment_failing]
    )
    return ModelWholeFileHygieneResult(
        outcome=(
            EnumWholeFileHygieneOutcome.DETECTED
            if findings
            else EnumWholeFileHygieneOutcome.CLEAN
        ),
        files_scanned=len(paths),
        findings=findings,
    )


class HandlerWholeFileHygiene:
    """Run both legs over ``request.scope_dir``; never raises for a leg failure."""

    def handle(
        self, request: ModelWholeFileHygieneRequest
    ) -> ModelWholeFileHygieneResult:
        try:
            return _run(request)
        except (_LegConfigError, OSError, UnicodeError) as exc:
            return ModelWholeFileHygieneResult(
                outcome=EnumWholeFileHygieneOutcome.CONFIG_ERROR, error=str(exc)
            )
