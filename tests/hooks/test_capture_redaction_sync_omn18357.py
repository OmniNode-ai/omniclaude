# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""RED-first tests for the capture-redaction mirror SYNC path (OMN-18357).

OMN-17959 landed the drift GATE and stopped there. The gate resolves
omnimarket's owning contract from a live ``omnimarket@dev`` checkout, so the
moment an owning-side PR merges, every open omniclaude PR goes red with no
change to any omniclaude branch -- and the only documented remedy was prose
("copy the posture over rather than editing the mirror"), which in practice
means a human re-typing YAML into the file the gate explicitly forbids editing.

That is detection without a sanctioned repair. These tests pin the repair: one
command re-derives the mirror from whatever omnimarket checkout the caller
passes, and the drift check goes from failing to passing across it. The
before-assertion is what stops a sync that copies nothing from passing.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
GENERATOR = REPO_ROOT / "scripts" / "validation" / "generate_event_registry.py"

pytestmark = pytest.mark.unit


def _generator_module() -> Any:
    sys.path.insert(0, str(REPO_ROOT / "scripts" / "validation"))
    import generate_event_registry  # noqa: PLC0415

    return generate_event_registry


# A projection that DECLARES the transform, so the drift check is in force.
# The check returns clean without inspecting anything when the transform is
# absent from the projection, which would make every assertion below vacuous.
_TRANSFORM_IN_USE: dict[str, dict[str, Any]] = {
    "prompt.submitted": {
        "event_type": "prompt.submitted",
        "fan_out": [
            {
                "topic": "onex.evt.omniclaude.prompt-submitted.v1",
                "transform": "redact_capture",
            }
        ],
        "partition_key_field": "session_id",
        "required_fields": [],
    }
}


def _fake_omnimarket_checkout(tmp_path: Path, owner_contract: dict[str, Any]) -> Path:
    """Build the directory shape the generator resolves the owner from.

    ``nodes/<node>/registries/topics.yaml`` -> ``parents[2]`` is ``nodes/``,
    and the owning contract hangs off that. Getting this shape wrong is the
    difference between proving the sync and proving nothing, so it is built
    from the generator's own relative path constant rather than retyped.
    """
    gen = _generator_module()
    nodes = tmp_path / "nodes"
    registry = nodes / "node_emit_daemon" / "registries" / "topics.yaml"
    registry.parent.mkdir(parents=True, exist_ok=True)
    registry.write_text(yaml.safe_dump({"events": {}}), encoding="utf-8")

    owner = nodes / gen.OWNING_CAPTURE_CONTRACT_RELPATH
    owner.parent.mkdir(parents=True, exist_ok=True)
    owner.write_text(yaml.safe_dump(owner_contract, sort_keys=False), encoding="utf-8")
    return registry


def _committed_contract() -> dict[str, Any]:
    gen = _generator_module()
    return yaml.safe_load(gen.VENDORED_CAPTURE_CONTRACT.read_text(encoding="utf-8"))


def test_sync_repairs_a_mirror_that_the_drift_check_refuses(tmp_path: Path) -> None:
    """The whole point: check FAILS before the sync and PASSES after it.

    Asserting only the after-state would let a sync that copies nothing pass,
    because a mirror that was already correct also passes. The before-state is
    the control.
    """
    gen = _generator_module()

    owner_contract = _committed_contract()
    owner_contract["topics"]["onex.evt.omniclaude.session-started.v1"] = {
        "ticket": "OMN-18357",
        "fields": {"session_id": "capture_verbatim"},
    }
    registry = _fake_omnimarket_checkout(tmp_path, owner_contract)

    # The mirror under test is a COPY of what this repo has committed, i.e.
    # it lacks the topic the owner just gained -- the exact live drift shape.
    mirror = tmp_path / "mirror" / "capture_redaction.yaml"
    mirror.parent.mkdir(parents=True, exist_ok=True)
    mirror.write_text(
        gen.VENDORED_CAPTURE_CONTRACT.read_text(encoding="utf-8"), encoding="utf-8"
    )

    before = gen.check_vendored_capture_contract(
        _TRANSFORM_IN_USE, registry, mirror_path=mirror
    )
    assert before, "control failed: the drift check did not object to a drifted mirror"
    assert "topics" in before[0]

    gen.sync_vendored_capture_contract(registry, mirror_path=mirror)

    after = gen.check_vendored_capture_contract(
        _TRANSFORM_IN_USE, registry, mirror_path=mirror
    )
    assert after == [], f"sync did not resolve the drift: {after}"


def test_sync_copies_the_owner_body_and_re_headers_it(tmp_path: Path) -> None:
    """The sync copies the owner's BODY; it does not re-derive a posture.

    A sync that wrote back a normalised projection would launder away anything
    the resolver does not read -- the prose ``reason`` blocks that document why
    each field is classified as it is.

    The header is the deliberate exception: omnimarket opens with the document
    marker and stamps 2026, and this repo's SPDX hook requires the block at line
    1 stamped 2025, so a byte-verbatim copy would not be committable here and
    ``onex spdx fix`` refuses to repair that shape.
    """
    gen = _generator_module()

    owner_contract = _committed_contract()
    owner_contract["topics"]["onex.evt.omniclaude.session-started.v1"] = {
        "ticket": "OMN-18357",
        "reason": "prose the resolver never reads and the sync must not drop",
        "fields": {"session_id": "capture_verbatim"},
    }
    registry = _fake_omnimarket_checkout(tmp_path, owner_contract)
    owner = gen.owning_capture_contract(registry)
    # The fake owner is written in omnimarket's preamble shape, which is what
    # the re-header has to consume; without this the test proves nothing.
    owner.write_text(
        "---\n"
        "# SPDX-FileCopyrightText: 2026 OmniNode.ai Inc.\n"
        "# SPDX-License-Identifier: MIT\n"
        "#\n" + owner.read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    mirror = tmp_path / "mirror" / "capture_redaction.yaml"
    mirror.parent.mkdir(parents=True, exist_ok=True)
    mirror.write_text("topics: {}\n", encoding="utf-8")

    gen.sync_vendored_capture_contract(registry, mirror_path=mirror)
    written = mirror.read_text(encoding="utf-8")

    assert written.startswith("# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.\n")
    assert "2026 OmniNode.ai Inc." not in written
    assert "prose the resolver never reads" in written

    # Everything below the preamble is the owner's, byte for byte.
    owner_body = owner.read_text(encoding="utf-8").split("#\n", 1)[1]
    assert written.endswith(owner_body)


def test_sync_refuses_when_the_owner_cannot_be_resolved(tmp_path: Path) -> None:
    """Fail-closed: a sync with no owner must raise, never leave the mirror as-is.

    Silently succeeding here is worse than failing -- the caller would commit an
    unchanged mirror believing it had been re-derived.
    """
    gen = _generator_module()

    registry = tmp_path / "nodes" / "node_emit_daemon" / "registries" / "topics.yaml"
    registry.parent.mkdir(parents=True, exist_ok=True)
    registry.write_text(yaml.safe_dump({"events": {}}), encoding="utf-8")

    mirror = tmp_path / "mirror" / "capture_redaction.yaml"
    mirror.parent.mkdir(parents=True, exist_ok=True)
    mirror.write_text("topics: {}\n", encoding="utf-8")

    with pytest.raises(FileNotFoundError):
        gen.sync_vendored_capture_contract(registry, mirror_path=mirror)

    assert mirror.read_text(encoding="utf-8") == "topics: {}\n"


def test_sync_mode_is_reachable_from_the_command_line(tmp_path: Path) -> None:
    """The repair has to be one command, or the next lane hand-edits the mirror again."""
    gen = _generator_module()

    owner_contract = _committed_contract()
    registry = _fake_omnimarket_checkout(tmp_path, owner_contract)

    completed = subprocess.run(  # noqa: S603
        [
            sys.executable,
            str(GENERATOR),
            "--daemon-registry",
            str(registry),
            "--sync-capture-contract",
            "--mirror-out",
            str(tmp_path / "cli-mirror.yaml"),
        ],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        check=False,
    )

    assert completed.returncode == 0, (
        f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
    )
    written = tmp_path / "cli-mirror.yaml"
    assert written.is_file()
    owner_text = gen.owning_capture_contract(registry).read_text(encoding="utf-8")
    written_text = written.read_text(encoding="utf-8")
    assert written_text.startswith("# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.\n")
    assert written_text.endswith(owner_text), (
        "the CLI mode must write the owner's body, not a re-emitted projection"
    )
