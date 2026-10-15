# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""The capture-redaction resolver's secret-reference rules (OMN-20926).

OMN-19513 removed the hook producer's use of these (content is captured raw);
the resolver functions below still serve the fan-out of the other topics.

Every planted value is built by concatenation and holds ``FAKE``, so no
credential-shaped literal sits in this file.
"""

from __future__ import annotations

import hashlib
import hmac
import importlib
import re
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

from omniclaude.hooks.capture_redaction import (
    default_contract_path,
    load_contract,
    plan_content_chunks,
    sub_keeping_references,
)

_LIB_DIR = Path(__file__).resolve().parents[3] / "plugins" / "onex" / "hooks" / "lib"
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

capture_mod = importlib.import_module("hook_content_capture")
health = importlib.import_module("hook_emit_health")
journal = importlib.import_module("hook_emit_journal")

pytestmark = pytest.mark.unit

SESSION = "0f0f0f0f-1111-2222-3333-444444444444"
GITHUB_FAKE = "gh" + "p_" + "FAKE" + "a1b2" * 9
LABELLED_FAKE = "FAKE" + "hunter22value"
REFERENCE_KEY = b"FAKE-reference-key"


def _reference() -> Any:
    reference = load_contract().reference
    assert reference is not None
    return reference


def _digest(value: str) -> str:
    return hmac.new(REFERENCE_KEY, value.encode(), hashlib.sha256).hexdigest()


def test_chunking_never_cuts_a_reference(tmp_path: Path) -> None:
    import yaml

    raw = yaml.safe_load(default_contract_path().read_text(encoding="utf-8"))
    topic = next(t for t, p in raw["topics"].items() if p.get("content_policy"))
    raw["topics"][topic]["content_policy"]["chunk_chars"] = 100
    raw["topics"][topic]["content_policy"]["max_content_chars"] = 250
    path = tmp_path / "capture_redaction.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")

    ref = _reference().reference_for(_digest(GITHUB_FAKE))
    text = "a" * 60 + " " + ref + " " + "b" * 70 + " " + ref + " " + "c" * 50
    plan = plan_content_chunks(text, topic, contract_path=path)
    joined = "".join(plan.chunks)
    assert all(len(chunk) <= 100 for chunk in plan.chunks)
    assert joined == text[: len(joined)]
    assert plan.truncated is True
    assert sum(chunk.count(ref) for chunk in plan.chunks) == 1
    assert joined.count("secret:") == 1


def test_a_match_starting_inside_a_reference_keeps_the_text_after_it() -> None:
    contract = load_contract()
    ref = _reference().reference_for(_digest(GITHUB_FAKE))
    text = "before " + ref + " TAIL after"
    # The pattern starts inside the reference and runs past its end.
    pattern = re.compile(re.escape(ref[5:]) + " TAIL")
    out = sub_keeping_references(pattern, text, contract, lambda m: "<hit>")
    assert out == text
    assert ref in out


def test_a_zero_width_pattern_terminates_and_leaves_references_standing() -> None:
    contract = load_contract()
    ref = _reference().reference_for(_digest(GITHUB_FAKE))
    text = "ab " + ref + " cd"
    out = sub_keeping_references(re.compile(r"x*"), text, contract, lambda m: "|")
    assert ref in out
    assert out.replace("|", "") == text


_REPO_ROOT = Path(__file__).resolve().parents[3]


def _generator() -> Any:
    scripts = str(_REPO_ROOT / "scripts" / "validation")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    return importlib.import_module("generate_event_registry")


def _check_against_owner(tmp_path: Path, owner_contract: dict[str, Any]) -> list[str]:
    gen = _generator()
    nodes = tmp_path / "nodes"
    registry = nodes / "node_emit_daemon" / "registries" / "topics.yaml"
    registry.parent.mkdir(parents=True, exist_ok=True)
    registry.write_text(yaml.safe_dump({"events": {}}), encoding="utf-8")
    owner = nodes / gen.OWNING_CAPTURE_CONTRACT_RELPATH
    owner.parent.mkdir(parents=True, exist_ok=True)
    owner.write_text(yaml.safe_dump(owner_contract, sort_keys=False), encoding="utf-8")
    mirror = tmp_path / "mirror" / "capture_redaction.yaml"
    mirror.parent.mkdir(parents=True, exist_ok=True)
    mirror.write_text(
        gen.VENDORED_CAPTURE_CONTRACT.read_text(encoding="utf-8"), encoding="utf-8"
    )
    in_use = {
        "prompt.submitted": {
            "fan_out": [{"topic": "t", "transform": gen.CAPTURE_REDACTION_TRANSFORM}]
        }
    }
    return list(
        gen.check_vendored_capture_contract(in_use, registry, mirror_path=mirror)
    )


def test_a_drifted_secret_reference_in_the_owning_contract_is_refused(
    tmp_path: Path,
) -> None:
    """AC4: the secret_reference block is mirror posture, and drift in it is caught.

    The control is the matching owner, which must pass; without it a check
    that objects to everything would satisfy the drifted case too.
    """
    gen = _generator()
    committed = yaml.safe_load(
        gen.VENDORED_CAPTURE_CONTRACT.read_text(encoding="utf-8")
    )
    assert committed["secret_reference"]["pattern"]

    assert _check_against_owner(tmp_path / "same", committed) == []

    drifted = yaml.safe_load(gen.VENDORED_CAPTURE_CONTRACT.read_text(encoding="utf-8"))
    drifted["secret_reference"]["store_key_template"] = "DRIFTED_{digest}"
    violations = _check_against_owner(tmp_path / "drift", drifted)
    assert violations, "the drift check did not object to a drifted secret_reference"
    assert "secret_reference" in violations[0]
