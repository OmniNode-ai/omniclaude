# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""RED-first tests for the omniclaude half of the capture-redaction contract.

OMN-17959 (parent OMN-17209). omnimarket's ``topics.yaml`` declares
``transform: redact_capture`` on the ``prompt.submitted`` and ``tool.executed``
fan-out rules; omniclaude never registered the name, so the required
``registry-consistency`` -> ``Tests Gate`` -> ``CI Summary`` chain failed on
every PR.

These tests are written against the CONTRACT
(``src/omniclaude/hooks/contracts/capture_redaction.yaml``, a byte-identical
mirror of omnimarket's owning copy), not against the implementation. Every
expectation below is traceable to a clause in that file -- the posture is
omnimarket's, not this module's.

The two topics under test are the ones OMN-16019 named as an
information-disclosure surface and that OMN-16979 widens onto the cloud relay,
so the transform is FAIL-CLOSED by construction: a field nobody classified is
hashed, a topic nobody governed is refused, and a contract that will not load
is refused rather than passed through.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

from omniclaude.hooks.capture_redaction import (
    EnumCaptureClass,
    EnumRedactionState,
    MalformedRedactionContractError,
    UngovernedTopicError,
    default_contract_path,
    load_contract,
    redact_capture,
)
from omniclaude.hooks.event_registry import EVENT_REGISTRY
from omniclaude.hooks.topics import TopicBase

REPO_ROOT = Path(__file__).resolve().parents[2]
GENERATOR = REPO_ROOT / "scripts" / "validation" / "generate_event_registry.py"

PROMPT_TOPIC = TopicBase.PROMPT_SUBMITTED.value
TOOL_TOPIC = TopicBase.TOOL_EXECUTED.value

SHA256_FIELD = re.compile(r"^sha256:[0-9a-f]{64}$")

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Canonical omnimarket registry / contract resolution
# ---------------------------------------------------------------------------


def _omnimarket_root() -> Path | None:
    """Resolve a canonical omnimarket checkout, or None.

    CI checks out omnimarket@dev at ``_registry/omnimarket``; locally the
    canonical clone sits beside this repo. Both are tried; neither is
    fabricated with a default path (Operating Rule 8).
    """
    candidates = [
        REPO_ROOT / "_registry" / "omnimarket",
        REPO_ROOT.parent / "omnimarket",
    ]
    # The canonical registry clone, when this machine declares one. Read only
    # if set -- never defaulted to a guessed path (Operating Rule 8).
    omni_home = os.environ.get("OMNI_HOME")
    if omni_home:
        candidates.append(Path(omni_home) / "omnimarket")
    for candidate in candidates:
        if (candidate / "src" / "omnimarket").is_dir():
            return candidate
    return None


def _daemon_registry_path() -> Path | None:
    root = _omnimarket_root()
    if root is None:
        return None
    path = (
        root
        / "src"
        / "omnimarket"
        / "nodes"
        / "node_emit_daemon"
        / "registries"
        / "topics.yaml"
    )
    return path if path.is_file() else None


# ---------------------------------------------------------------------------
# 1. Registration under the exact contract name
# ---------------------------------------------------------------------------


def test_generator_maps_the_exact_daemon_transform_name() -> None:
    """The daemon YAML spells ``redact_capture``; the generator must map it.

    This is the literal failure OMN-17959 records:
    ``ValueError: prompt.submitted: unknown daemon transform 'redact_capture'``.
    """
    sys.path.insert(0, str(REPO_ROOT / "scripts" / "validation"))
    from generate_event_registry import (  # noqa: PLC0415
        TRANSFORM_NAME_TO_CALLABLE,
    )

    assert "redact_capture" in TRANSFORM_NAME_TO_CALLABLE
    assert TRANSFORM_NAME_TO_CALLABLE["redact_capture"] == "redact_capture"


def test_prompt_submitted_evt_rule_uses_redact_capture() -> None:
    """The OMN-16019 disclosure surface now carries the contract transform."""
    rules = {
        rule.topic_base: rule for rule in EVENT_REGISTRY["prompt.submitted"].fan_out
    }
    assert rules[TopicBase.PROMPT_SUBMITTED].transform is redact_capture


def test_tool_executed_rule_uses_redact_capture() -> None:
    """The OMN-16979 relay-crossing topic is no longer transform-less."""
    rules = {rule.topic_base: rule for rule in EVENT_REGISTRY["tool.executed"].fan_out}
    assert rules[TopicBase.TOOL_EXECUTED].transform is redact_capture


def test_fan_out_rule_applies_the_topic_scoped_transform() -> None:
    """``apply_transform`` must hand the transform its own rule's topic.

    A topic-blind call cannot select the right per-topic policy, and the two
    governed topics have materially different ones (``prompt_preview`` is
    shape-only on one and undeclared on the other).
    """
    rules = {
        rule.topic_base: rule for rule in EVENT_REGISTRY["prompt.submitted"].fan_out
    }
    result = rules[TopicBase.PROMPT_SUBMITTED].apply_transform(
        {"session_id": "s-1", "prompt": "hello world", "prompt_preview": "hello world"}
    )
    assert "prompt" not in result
    assert result["session_id"] == "s-1"
    assert result["prompt_preview"] == {"type": "str", "length": 11}


# ---------------------------------------------------------------------------
# 2. Each contract rule is actually applied
# ---------------------------------------------------------------------------


def test_capture_verbatim_fields_cross_unchanged() -> None:
    payload: dict[str, object] = {
        "session_id": "s-1",
        "tool_name": "Bash",
        "duration_ms": 12,
        "interrupted": False,
        "hook_source": "post-tool-use",
        "working_directory": "/w",
        "correlation_id": "c-1",
        "causation_id": "c-0",
        "emitted_at": "2026-09-05T00:00:00Z",
        "entity_id": "e-1",
        "schema_version": "1.0.0",
    }
    result = redact_capture(dict(payload), topic=TOOL_TOPIC)
    for field, value in payload.items():
        assert result[field] == value, field


def test_never_capture_fields_are_dropped_not_hashed() -> None:
    """``prompt`` / ``prompt_b64`` are dropped outright.

    The contract's stated reason: a hash of a short prompt is a lookup handle,
    so hashing is not the protection for a field known to carry content.
    """
    result = redact_capture(
        {"session_id": "s", "prompt": "secret question", "prompt_b64": "c2VjcmV0"},
        topic=PROMPT_TOPIC,
    )
    assert "prompt" not in result
    assert "prompt_b64" not in result
    assert "secret question" not in str(result)
    assert "c2VjcmV0" not in str(result)


def test_prompt_preview_is_reduced_to_shape_only() -> None:
    """OMN-16019's disclosure surface keeps no content and no hash."""
    result = redact_capture(
        {"session_id": "s", "prompt_preview": "rotate the prod database password"},
        topic=PROMPT_TOPIC,
    )
    assert result["prompt_preview"] == {"type": "str", "length": 33}
    assert "rotate" not in str(result["prompt_preview"])


def test_unknown_field_is_hashed_by_the_fail_closed_default() -> None:
    """``default_field_class: capture_hashed`` -- a forgotten field cannot leak."""
    result = redact_capture(
        {"session_id": "s", "some_future_field": "verbatim-content"},
        topic=PROMPT_TOPIC,
    )
    hashed = result["some_future_field"]
    assert isinstance(hashed, str)
    assert SHA256_FIELD.match(hashed)
    assert "verbatim-content" not in str(result)


def test_prompt_length_is_derived_from_the_prompt_before_it_is_dropped() -> None:
    """The signal that survived ``strip_prompt``'s redaction is not lost."""
    result = redact_capture(
        {"session_id": "s", "prompt": "0123456789"}, topic=PROMPT_TOPIC
    )
    assert result["prompt_length"] == 10


def test_producer_supplied_prompt_length_wins_over_the_derivation() -> None:
    """Matches ``strip_prompt``'s own ``if "prompt_length" not in result`` guard."""
    result = redact_capture(
        {"session_id": "s", "prompt": "0123456789", "prompt_length": 4},
        topic=PROMPT_TOPIC,
    )
    assert result["prompt_length"] == 4


def test_always_hashed_output_class_beats_the_per_field_class() -> None:
    """DoD probe 4: an SSM result with no secret-shaped text is still hashed.

    ``tool_response`` is a declared ``content_field``; the record matches the
    ``ssm_send_command`` output class on tool name + command shape. No secret
    pattern fires here, and that is the point -- a class does not need to
    recognise the secret to refuse it.
    """
    result = redact_capture(
        {
            "session_id": "s",
            "tool_name": "Bash",
            "command": "aws ssm send-command --comment lane",
            "tool_response": "hello, nothing secret-shaped here at all",
        },
        topic=TOOL_TOPIC,
    )
    response = result["tool_response"]
    assert isinstance(response, str)
    assert SHA256_FIELD.match(response)
    assert "nothing secret-shaped" not in str(result)


def test_secret_scrub_runs_on_top_of_capture_verbatim() -> None:
    """A verbatim field matching a secret pattern is hashed and escalates state."""
    result = redact_capture(
        {
            "session_id": "s",
            "working_directory": "postgresql://svc:hunter2@db.example.invalid/x",
        },
        topic=TOOL_TOPIC,
    )
    working_directory = result["working_directory"]
    assert isinstance(working_directory, str)
    assert SHA256_FIELD.match(working_directory)
    assert "hunter2" not in str(result)
    assert result["redaction_state"] == EnumRedactionState.SECRET_DETECTED.value


def test_redaction_state_is_always_stamped() -> None:
    """An unstamped record must not exist -- downstream refuses one."""
    result = redact_capture({"session_id": "s"}, topic=TOOL_TOPIC)
    assert result["redaction_state"] == EnumRedactionState.RAW.value

    redacted = redact_capture({"session_id": "s", "prompt": "x"}, topic=PROMPT_TOPIC)
    assert redacted["redaction_state"] == EnumRedactionState.REDACTED.value


def test_producer_supplied_redaction_state_is_not_honoured() -> None:
    """A producer does not get to declare its own posture."""
    result = redact_capture(
        {"session_id": "s", "redaction_state": "raw", "prompt_preview": "x"},
        topic=PROMPT_TOPIC,
    )
    assert result["redaction_state"] == EnumRedactionState.REDACTED.value


def test_transform_is_deterministic_and_side_effect_free() -> None:
    """Deterministic replay is the doctrine's proof surface (unsalted hashing)."""
    payload: dict[str, object] = {
        "session_id": "s",
        "prompt": "hello",
        "unclassified": "value",
    }
    snapshot = dict(payload)
    first = redact_capture(payload, topic=PROMPT_TOPIC)
    second = redact_capture(payload, topic=PROMPT_TOPIC)
    assert first == second
    assert payload == snapshot, "transform mutated its input"


# ---------------------------------------------------------------------------
# 3. Fail-closed behaviour
# ---------------------------------------------------------------------------


def test_ungoverned_topic_is_refused_not_passed_through() -> None:
    """A rule naming this transform on an unlisted topic is a hard refusal.

    Falling back to "hash everything" would publish a record that looks
    redacted while nobody has ever reviewed what it carries.
    """
    with pytest.raises(UngovernedTopicError):
        redact_capture(
            {"session_id": "s", "prompt": "leak me"},
            topic="onex.evt.omniclaude.session-started.v1",
        )


def test_missing_contract_fails_closed(tmp_path: Path) -> None:
    """No contract, no publish. The payload is never returned unredacted."""
    absent = tmp_path / "does-not-exist.yaml"
    with pytest.raises(MalformedRedactionContractError) as excinfo:
        redact_capture(
            {"session_id": "s", "prompt": "leak me"},
            topic=PROMPT_TOPIC,
            contract_path=absent,
        )
    assert "leak me" not in str(excinfo.value)


def test_malformed_contract_fails_closed(tmp_path: Path) -> None:
    malformed = tmp_path / "capture_redaction.yaml"
    malformed.write_text("topics: []\n", encoding="utf-8")
    with pytest.raises(MalformedRedactionContractError):
        redact_capture(
            {"session_id": "s", "prompt": "leak me"},
            topic=PROMPT_TOPIC,
            contract_path=malformed,
        )


def test_contract_declaring_an_unknown_capture_class_is_refused(
    tmp_path: Path,
) -> None:
    raw = yaml.safe_load(default_contract_path().read_text(encoding="utf-8"))
    raw["topics"][PROMPT_TOPIC]["fields"]["session_id"] = "capture_whatever"
    broken = tmp_path / "capture_redaction.yaml"
    broken.write_text(yaml.safe_dump(raw), encoding="utf-8")
    with pytest.raises(MalformedRedactionContractError):
        redact_capture({"session_id": "s"}, topic=PROMPT_TOPIC, contract_path=broken)


def test_contract_with_an_empty_field_policy_is_refused(tmp_path: Path) -> None:
    """An empty policy means "hash everything", which reads identical to a
    working one -- so it is refused rather than accepted."""
    raw = yaml.safe_load(default_contract_path().read_text(encoding="utf-8"))
    raw["topics"][PROMPT_TOPIC]["fields"] = {}
    broken = tmp_path / "capture_redaction.yaml"
    broken.write_text(yaml.safe_dump(raw), encoding="utf-8")
    with pytest.raises(MalformedRedactionContractError):
        redact_capture({"session_id": "s"}, topic=PROMPT_TOPIC, contract_path=broken)


# ---------------------------------------------------------------------------
# 4. The contract is the posture; the module holds none of it
# ---------------------------------------------------------------------------


def test_no_python_side_policy_constants() -> None:
    """OMN-17209 DoD probe 7, ported: adding a regex or a field name to a
    Python constant is not a substitute for a contract entry."""
    source = (
        Path(
            __import__(
                "omniclaude.hooks.capture_redaction", fromlist=["__file__"]
            ).__file__
            or ""
        )
    ).read_text(encoding="utf-8")
    forbidden = [
        "prompt_preview",
        "prompt_b64",
        "tool_response",
        "onex.evt.omniclaude.",
        "AKIA",
        "BEGIN ",
        "requirepass",
        "kubectl",
        "send-command",
    ]
    hits = [needle for needle in forbidden if needle in source]
    assert not hits, f"policy literals leaked into the resolver: {hits}"


def test_governed_topics_are_exactly_the_two_relay_topics() -> None:
    contract = load_contract()
    assert set(contract.topics) == {PROMPT_TOPIC, TOOL_TOPIC}
    assert contract.default_field_class is EnumCaptureClass.CAPTURE_HASHED


def test_mirrored_contract_posture_matches_the_omnimarket_owner() -> None:
    """omnimarket owns the contract; this repo carries a verified mirror.

    Same single-owner posture as EVENT_REGISTRY itself (OMN-15967): the copy
    here is a projection with a mechanical drift gate, not a second source of
    truth.

    The comparison is of the RESOLVED POSTURE, not of bytes. This repo's own
    mandated pre-commit hooks rewrite the file on arrival -- the SPDX stamper
    normalises the copyright year and moves the YAML document marker, and
    detect-secrets appends an allowlist pragma to the prose line quoting the
    2026-08-19 incident URL. Neither can change what is captured, so a byte
    gate would fail builds for a reason unrelated to disclosure and the
    pressure would be to weaken it. What must not drift is the posture.
    """
    root = _omnimarket_root()
    if root is None:
        pytest.skip(
            "no canonical omnimarket checkout resolvable; the drift gate that "
            "actually blocks merge is generate_event_registry.py --check, which "
            "CI runs against a fresh omnimarket@dev checkout"
        )
    owner = (
        root
        / "src"
        / "omnimarket"
        / "nodes"
        / "node_event_emit_effect"
        / "contracts"
        / "capture_redaction.yaml"
    )
    assert owner.is_file(), f"owning contract missing at {owner}"

    sys.path.insert(0, str(REPO_ROOT / "scripts" / "validation"))
    from generate_event_registry import _resolved_posture  # noqa: PLC0415

    assert _resolved_posture(default_contract_path()) == _resolved_posture(owner), (
        "the mirrored capture-redaction posture has drifted from omnimarket's "
        "owning copy"
    )


def test_posture_comparison_detects_a_real_policy_change(tmp_path: Path) -> None:
    """Positive control: the comparison above is capable of failing.

    An equality assertion that can only pass proves nothing. This flips one
    field's capture class and requires the comparison to notice.
    """
    sys.path.insert(0, str(REPO_ROOT / "scripts" / "validation"))
    from generate_event_registry import _resolved_posture  # noqa: PLC0415

    raw = yaml.safe_load(default_contract_path().read_text(encoding="utf-8"))
    raw["topics"][PROMPT_TOPIC]["fields"]["prompt"] = (
        EnumCaptureClass.CAPTURE_VERBATIM.value
    )
    tampered = tmp_path / "capture_redaction.yaml"
    tampered.write_text(yaml.safe_dump(raw), encoding="utf-8")

    assert _resolved_posture(tampered) != _resolved_posture(default_contract_path())


# ---------------------------------------------------------------------------
# 5. The projection regenerates with no drift, and no OTHER name is missing
# ---------------------------------------------------------------------------


def _run_generator(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        [sys.executable, str(GENERATOR), *args],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        check=False,
    )


def test_projection_drift_check_passes_against_the_canonical_registry() -> None:
    """The exact command ci.yml:1512 runs."""
    registry = _daemon_registry_path()
    if registry is None:
        pytest.skip("no canonical omnimarket checkout resolvable")
    completed = _run_generator("--daemon-registry", str(registry), "--check")
    assert completed.returncode == 0, (
        f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
    )
    assert "projection check passed" in completed.stdout


def test_every_daemon_transform_name_is_mapped() -> None:
    """DoD 5: this does not recur one transform name at a time."""
    registry = _daemon_registry_path()
    if registry is None:
        pytest.skip("no canonical omnimarket checkout resolvable")
    sys.path.insert(0, str(REPO_ROOT / "scripts" / "validation"))
    from generate_event_registry import (  # noqa: PLC0415
        NON_CANONICAL_DAEMON_TOPICS,
        TRANSFORM_NAME_TO_CALLABLE,
    )

    raw: dict[str, Any] = yaml.safe_load(registry.read_text(encoding="utf-8"))
    declared: set[str] = set()
    for event_def in raw["events"].values():
        for rule in event_def.get("fan_out", []) or []:
            if rule["topic"] in NON_CANONICAL_DAEMON_TOPICS:
                continue
            declared.add(rule.get("transform", "passthrough"))
    unmapped = sorted(declared - set(TRANSFORM_NAME_TO_CALLABLE))
    assert not unmapped, (
        f"daemon transform names with no omniclaude callable: {unmapped}"
    )
