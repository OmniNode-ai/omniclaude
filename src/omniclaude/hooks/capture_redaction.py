# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Contract-resolved capture redaction for the hook fan-out (OMN-17959).

The posture lives in ``contracts/capture_redaction.yaml``. This module is the
resolver for it and holds **no policy of its own**: no field name, no topic
name, no secret pattern and no tool name appears here as a Python literal.
``tests/hooks/test_capture_redaction_omn17959.py::test_no_python_side_policy_constants``
scans this module's source and fails if one does -- OMN-17209's DoD probe 7,
"a committed-recipe gate rejects adding a regex to a Python constant as a
substitute for a contract entry", ported to this side of the seam.

Who owns the contract
---------------------
**omnimarket owns it.** The copy under ``contracts/`` is a byte-identical
mirror, held to that by ``scripts/validation/generate_event_registry.py
--check`` -- the same required ``registry-consistency`` job that already holds
``EVENT_REGISTRY`` to omnimarket's ``topics.yaml``. This is the OMN-15967
single-owner projection pattern, not a second source of truth: a divergent
byte fails the build.

A mirror rather than an import because omniclaude's ``omnimarket`` pin
predates the contract, and because the emit seam is a hot hook path -- the
resolver is stdlib plus a lazily imported YAML parse, with no Pydantic import
chain (the OMN-17224 constraint the emit hook was moved off this path for).

Why it is fail-closed in three directions
-----------------------------------------
The two governed topics were named by OMN-16019 as an information-disclosure
surface, and OMN-16979 widens them onto the cloud relay -- they cross the
trust boundary. So:

* a field nobody classified takes the contract's ``default_field_class``,
  which is the hashing one -- a field a future ticket adds cannot leak by
  being forgotten;
* a topic whose fan-out rule names this transform but which the contract does
  not govern raises :class:`UngovernedTopicError` -- falling back to "hash
  everything" would publish a record that looks reviewed and is not;
* a contract that is absent or will not parse raises
  :class:`MalformedRedactionContractError` -- nothing is published at all,
  which is strictly stronger than emitting a reduced record.

Determinism
-----------
Hashing is sha256 over the value's canonical JSON form, unsalted. Unsalted is
a requirement, not an oversight: a salt makes the record unreplayable, and
deterministic replay is the doctrine's proof surface. The consequence is that
a hash of a LOW-entropy value is brute-forceable, which is why hashing is the
fail-closed default for *unclassified* fields and never the protection for a
field known to hold content -- the contract classes those as the dropping one.

Related tickets:
    - OMN-16019: the disclosure finding these two topics carry
    - OMN-16979: the widening onto the cloud relay
    - OMN-17209: the contract itself (omnimarket half)
    - OMN-17959: this half -- registering the transform omniclaude never had
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache
from pathlib import Path

JsonDict = dict[str, object]

_CONTRACTS_DIRNAME = "contracts"
_CONTRACT_FILENAME = "capture_redaction.yaml"


class CaptureRedactionError(Exception):
    """Base class for every refusal raised by this resolver."""


class MalformedRedactionContractError(CaptureRedactionError):
    """The contract is absent, unparseable, or internally inconsistent.

    Deliberately carries the contract location and the structural detail, and
    never the payload under redaction -- an exception message is a log line.
    """

    def __init__(self, *, source: str, detail: str) -> None:
        self.source = source
        self.detail = detail
        super().__init__(f"malformed capture redaction contract {source}: {detail}")


class UngovernedTopicError(CaptureRedactionError):
    """A fan-out rule names this transform for a topic the contract omits."""

    def __init__(
        self, *, topic: str, governed: tuple[str, ...], contract_path: str
    ) -> None:
        self.topic = topic
        self.governed = governed
        self.contract_path = contract_path
        super().__init__(
            f"topic {topic!r} names the capture-redaction transform but declares "
            f"no policy in {contract_path} (governed: {list(governed)}). Refusing "
            "rather than defaulting, because a default posture reads identical "
            "to a reviewed one."
        )


class EnumCaptureClass(StrEnum):
    """The four capture classes the contract may assign to a field.

    Re-declared rather than imported so this module stays stdlib-only on the
    hook import path (OMN-17224).
    """

    CAPTURE_VERBATIM = "capture_verbatim"
    CAPTURE_HASHED = "capture_hashed"
    CAPTURE_SHAPE_ONLY = "capture_shape_only"
    NEVER_CAPTURE = "never_capture"


class EnumRedactionState(StrEnum):
    """Redaction state stamped on every governed record.

    Values mirror ``omnibase_core``'s ``EnumArtifactRedactionState``
    (OMN-13152) exactly; the parity is asserted in the TEST by importing core
    there, so the runtime path stays free of that import.
    """

    RAW = "raw"
    REDACTED = "redacted"
    RESTRICTED = "restricted"
    # Suppressions below: this is the NAME OF A REDACTION STATE, not a credential.
    # The value is mirrored from omnibase_core's EnumArtifactRedactionState.
    SECRET_DETECTED = "secret_detected"  # noqa: S105  # pragma: allowlist secret


@dataclass(frozen=True)
class OutputClass:
    """One always-hashed output class: hashed for what it is, not what it says."""

    name: str
    tool_names: frozenset[str]
    command_pattern: re.Pattern[str]


@dataclass(frozen=True)
class DerivedField:
    """A field computed from a source field before that source is redacted.

    Redacting a field is the point; silently losing the aggregate that
    survived the redaction is a regression, so the derivation is declared in
    the contract rather than dropped.
    """

    target: str
    source: str
    derive: str


@dataclass(frozen=True)
class TopicPolicy:
    """The declared per-field capture classes for one governed topic."""

    topic: str
    fields: dict[str, EnumCaptureClass]
    derived: tuple[DerivedField, ...] = ()


@dataclass(frozen=True)
class RedactionContract:
    """The whole resolved contract."""

    default_field_class: EnumCaptureClass
    output_classes: tuple[OutputClass, ...]
    command_fields: tuple[str, ...]
    tool_name_field: str
    content_fields: frozenset[str]
    secret_patterns: tuple[tuple[str, re.Pattern[str]], ...]
    topics: dict[str, TopicPolicy]
    redaction_state_field: str


def default_contract_path() -> Path:
    """Resolve the mirrored contract beside this module, packaging-safe."""
    return Path(__file__).resolve().parent / _CONTRACTS_DIRNAME / _CONTRACT_FILENAME


# ---------------------------------------------------------------------------
# Contract parsing -- every branch here is a refusal, never a fallback
# ---------------------------------------------------------------------------

#: The closed set of derivations a contract may name. A derivation is an
#: AGGREGATE over a value being redacted -- never a projection of its content,
#: which would be a way to smuggle content past the capture class.
_DERIVATIONS: dict[str, Callable[[object], int]] = {
    "length": lambda value: (
        len(value) if isinstance(value, str | bytes | list | dict) else 0
    ),
}


def _require(raw: JsonDict, key: str, source: Path) -> object:
    if key not in raw:
        raise MalformedRedactionContractError(
            source=str(source), detail=f"missing required key {key!r}"
        )
    return raw[key]


def _require_list(raw: JsonDict, key: str, source: Path) -> list[object]:
    """Require a key whose value is a sequence.

    Split out from :func:`_require` so the contract's list-shaped keys are
    type-correct at their call sites without a bare ``Any``, and so a
    non-sequence value becomes a contract refusal naming the key rather than a
    ``TypeError`` from the iteration two frames away.
    """
    value = _require(raw, key, source)
    if not isinstance(value, list):
        raise MalformedRedactionContractError(
            source=str(source),
            detail=f"{key!r} must be a list, got {type(value).__name__}",
        )
    return list(value)


def _capture_class(value: object, *, source: Path, where: str) -> EnumCaptureClass:
    try:
        if not isinstance(value, str):
            raise ValueError(type(value).__name__)
        return EnumCaptureClass(value)
    except ValueError as exc:
        valid = ", ".join(c.value for c in EnumCaptureClass)
        raise MalformedRedactionContractError(
            source=str(source),
            detail=f"{where} declares unknown capture class {value!r} (valid: {valid})",
        ) from exc


def _compile(pattern: object, *, source: Path, where: str) -> re.Pattern[str]:
    if not isinstance(pattern, str):
        raise MalformedRedactionContractError(
            source=str(source), detail=f"{where} pattern must be a string"
        )
    try:
        return re.compile(pattern)
    except re.error as exc:
        raise MalformedRedactionContractError(
            source=str(source), detail=f"{where} pattern does not compile: {exc}"
        ) from exc


def _parse_output_classes(raw: JsonDict, *, source: Path) -> tuple[OutputClass, ...]:
    output_classes: list[OutputClass] = []
    for entry in _require_list(raw, "always_hashed_output_classes", source):
        if not isinstance(entry, dict):
            raise MalformedRedactionContractError(
                source=str(source),
                detail="always_hashed_output_classes entries must be mappings",
            )
        name = entry.get("name")
        if not isinstance(name, str) or not name:
            raise MalformedRedactionContractError(
                source=str(source), detail="output class has no 'name'"
            )
        reason = entry.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            raise MalformedRedactionContractError(
                source=str(source),
                detail=(
                    f"output class {name!r} has no 'reason'. Every always-hashed "
                    "class states why it is one; an unexplained class cannot be "
                    "reviewed or retired."
                ),
            )
        tool_names = entry.get("tool_names")
        if not isinstance(tool_names, list) or not tool_names:
            raise MalformedRedactionContractError(
                source=str(source),
                detail=f"output class {name!r} declares no 'tool_names'",
            )
        output_classes.append(
            OutputClass(
                name=name,
                tool_names=frozenset(str(t) for t in tool_names),
                command_pattern=_compile(
                    _require(entry, "command_pattern", source),
                    source=source,
                    where=f"output class {name!r}",
                ),
            )
        )
    return tuple(output_classes)


def _parse_secret_patterns(
    raw: JsonDict, *, source: Path
) -> tuple[tuple[str, re.Pattern[str]], ...]:
    patterns: list[tuple[str, re.Pattern[str]]] = []
    for entry in _require_list(raw, "secret_patterns", source):
        if not isinstance(entry, dict) or "name" not in entry:
            raise MalformedRedactionContractError(
                source=str(source), detail="secret_patterns entries need a 'name'"
            )
        patterns.append(
            (
                str(entry["name"]),
                _compile(
                    _require(entry, "pattern", source),
                    source=source,
                    where=f"secret pattern {entry['name']!r}",
                ),
            )
        )
    return tuple(patterns)


def _parse_derived(
    policy: JsonDict, *, topic: str, source: Path
) -> tuple[DerivedField, ...]:
    derived: list[DerivedField] = []
    raw_derived = policy.get("derived_fields") or {}
    if not isinstance(raw_derived, dict):
        raise MalformedRedactionContractError(
            source=str(source),
            detail=f"topic {topic!r} derived_fields must be a mapping",
        )
    for target, spec in raw_derived.items():
        if not isinstance(spec, dict) or "from" not in spec:
            raise MalformedRedactionContractError(
                source=str(source),
                detail=(
                    f"topic {topic!r} derived field {target!r} needs a 'from' "
                    "source field"
                ),
            )
        derive = spec.get("derive")
        if derive not in _DERIVATIONS:
            raise MalformedRedactionContractError(
                source=str(source),
                detail=(
                    f"topic {topic!r} derived field {target!r} declares unknown "
                    f"derivation {derive!r} (valid: "
                    f"{', '.join(sorted(_DERIVATIONS))})"
                ),
            )
        derived.append(
            DerivedField(
                target=str(target), source=str(spec["from"]), derive=str(derive)
            )
        )
    return tuple(derived)


def _parse_topics(raw: JsonDict, *, source: Path) -> dict[str, TopicPolicy]:
    topics: dict[str, TopicPolicy] = {}
    topics_raw = _require(raw, "topics", source)
    if not isinstance(topics_raw, dict) or not topics_raw:
        raise MalformedRedactionContractError(
            source=str(source), detail="'topics' must be a non-empty mapping"
        )
    for topic, policy in topics_raw.items():
        if not isinstance(policy, dict):
            raise MalformedRedactionContractError(
                source=str(source), detail=f"topic {topic!r} policy must be a mapping"
            )
        fields_raw = policy.get("fields")
        if not isinstance(fields_raw, dict) or not fields_raw:
            raise MalformedRedactionContractError(
                source=str(source),
                detail=(
                    f"topic {topic!r} declares no 'fields'. An empty policy means "
                    "'hash everything', which reads identical to a working one."
                ),
            )
        topics[str(topic)] = TopicPolicy(
            topic=str(topic),
            fields={
                str(f): _capture_class(
                    c, source=source, where=f"topic {topic!r} field {f!r}"
                )
                for f, c in fields_raw.items()
            },
            derived=_parse_derived(policy, topic=str(topic), source=source),
        )
    return topics


def _parse(raw: object, *, source: Path) -> RedactionContract:
    if not isinstance(raw, dict):
        raise MalformedRedactionContractError(
            source=str(source), detail="contract YAML must be a mapping"
        )

    state_field = _require(raw, "redaction_state_field", source)
    if not isinstance(state_field, str) or not state_field:
        raise MalformedRedactionContractError(
            source=str(source),
            detail="redaction_state_field must be a non-empty string",
        )

    return RedactionContract(
        default_field_class=_capture_class(
            _require(raw, "default_field_class", source),
            source=source,
            where="default_field_class",
        ),
        output_classes=_parse_output_classes(raw, source=source),
        command_fields=tuple(
            str(f) for f in _require_list(raw, "command_fields", source)
        ),
        tool_name_field=str(_require(raw, "tool_name_field", source)),
        content_fields=frozenset(
            str(f) for f in _require_list(raw, "content_fields", source)
        ),
        # The scanner matches the NAME. `secret_patterns` is the contract's own
        # key for the pattern SET this resolver scrubs WITH -- there is no value
        # here, and renaming it would fork the contract's vocabulary.
        secret_patterns=_parse_secret_patterns(  # secret-ok: contract field name
            raw, source=source
        ),
        topics=_parse_topics(raw, source=source),
        redaction_state_field=state_field,
    )


@lru_cache(maxsize=4)
def _load(path_str: str) -> RedactionContract:
    # Imported lazily: `omniclaude.hooks.event_registry` is on the hook import
    # path and must not pay a YAML parse at import time (OMN-17224).
    import yaml  # noqa: PLC0415

    path = Path(path_str)
    if not path.is_file():
        raise MalformedRedactionContractError(
            source=path_str, detail="capture redaction contract not found"
        )
    try:
        parsed = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise MalformedRedactionContractError(
            source=path_str, detail=f"contract YAML does not parse: {exc}"
        ) from exc
    return _parse(parsed, source=path)


def load_contract(path: Path | None = None) -> RedactionContract:
    """Load and cache the capture redaction contract."""
    return _load(str(path if path is not None else default_contract_path()))


# ---------------------------------------------------------------------------
# Value operations
# ---------------------------------------------------------------------------


def _canonical(value: object) -> str:
    """Canonical JSON form -- the hash input, and the thing replay reproduces."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def hash_value(value: object) -> str:
    """``sha256:<64 hex>`` over the value's canonical JSON form."""
    return "sha256:" + hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def shape_of(value: object) -> JsonDict:
    """Type + size, with no content and no hash."""
    shape: JsonDict = {"type": type(value).__name__}
    if isinstance(value, str | bytes | list | tuple | dict):
        shape["length"] = len(value)
    return shape


_STATE_RANK: dict[str, int] = {
    EnumRedactionState.RAW.value: 0,
    EnumRedactionState.RESTRICTED.value: 1,
    EnumRedactionState.REDACTED.value: 2,
    EnumRedactionState.SECRET_DETECTED.value: 3,
}


def _state_rank(state: EnumRedactionState) -> int:
    return _STATE_RANK[state.value]


def _string_leaves(value: object) -> Iterator[str]:
    """Every string reachable inside a container, at any depth."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _string_leaves(item)
    elif isinstance(value, list | tuple):
        for item in value:
            yield from _string_leaves(item)


def _scrub_targets(value: object) -> Iterator[str]:
    """The texts the secret scrub must see for one field's value.

    A string is matched as itself. Anything else is matched BOTH as its
    canonical JSON form -- so key/value framing a pattern needs is visible
    even when the framing is structural rather than textual -- and leaf by
    leaf, so a leaf whose JSON escaping would break a pattern is still seen
    raw. A hit anywhere redacts the whole field: a container is redacted as a
    unit because splitting it would publish the clean half of a value the
    scrub has already refused.
    """
    if isinstance(value, str):
        yield value
        return
    yield _canonical(value)
    yield from _string_leaves(value)


def _matches_secret(value: object, contract: RedactionContract) -> str | None:
    for target in _scrub_targets(value):
        for name, pattern in contract.secret_patterns:
            if pattern.search(target):
                return name
    return None


def _matched_output_class(
    payload: JsonDict, contract: RedactionContract
) -> OutputClass | None:
    """Return the first always-hashed class this record belongs to, if any.

    Matching reads the contract's declared tool-name field plus its declared
    command fields. It never inspects the OUTPUT: an SSM result carrying no
    secret-shaped text at all must still be hashed, so a class that consulted
    the output would be a pattern match wearing a class's name.
    """
    tool = payload.get(contract.tool_name_field)
    tool_name = tool if isinstance(tool, str) else ""
    candidates = [
        payload[field] for field in contract.command_fields if field in payload
    ]
    for output_class in contract.output_classes:
        if tool_name not in output_class.tool_names:
            continue
        for candidate in candidates:
            text = candidate if isinstance(candidate, str) else _canonical(candidate)
            if output_class.command_pattern.search(text):
                return output_class
    return None


def redact_capture(
    payload: JsonDict, *, topic: str, contract_path: Path | None = None
) -> JsonDict:
    """Apply ``topic``'s declared capture policy and stamp the redaction state.

    Topic-scoped by signature because the contract is per topic: the two
    governed topics carry materially different field policies, so a
    topic-blind transform could not select the right one.

    Order, and why:

    1. Resolve the topic's policy. A topic naming this transform that the
       contract does not govern is a hard refusal.
    2. Match the always-hashed output classes on tool name + command shape. A
       match forces every declared content field to the hashing class,
       overriding its per-field class. Class beats field, always.
    3. Apply each field's class, with the contract's fail-closed default for
       any field nobody declared.
    4. Run the secret scrub over what survived verbatim. A hit hashes the
       value and escalates the record's state.
    5. Stamp the state field. Always -- a record with no state is refused
       downstream, so an unstamped record must not exist.

    Args:
        payload: The event payload. Never mutated.
        topic: The wire topic this fan-out rule targets.
        contract_path: Override for the contract location (tests).

    Returns:
        A new payload carrying only what the contract permits, plus the state.

    Raises:
        UngovernedTopicError: the topic names this transform but declares no
            field policy.
        MalformedRedactionContractError: the contract is absent or invalid.
    """
    contract = load_contract(contract_path)
    policy = contract.topics.get(topic)
    if policy is None:
        raise UngovernedTopicError(
            topic=topic,
            governed=tuple(sorted(contract.topics)),
            contract_path=str(
                contract_path if contract_path is not None else default_contract_path()
            ),
        )

    forced = _matched_output_class(payload, contract)
    state = EnumRedactionState.RAW
    result: JsonDict = {}

    # Derivations read the SOURCE before it is redacted, and only fill a
    # target the producer did not already supply.
    derived_values: JsonDict = {}
    for rule in policy.derived:
        if rule.target in payload or rule.source not in payload:
            continue
        derived_values[rule.target] = _DERIVATIONS[rule.derive](payload[rule.source])

    for field, value in list(payload.items()) + list(derived_values.items()):
        if field == contract.redaction_state_field:
            # A producer does not get to declare its own posture.
            state = max(state, EnumRedactionState.REDACTED, key=_state_rank)
            continue

        capture_class = policy.fields.get(field, contract.default_field_class)
        if forced is not None and field in contract.content_fields:
            capture_class = EnumCaptureClass.CAPTURE_HASHED

        if capture_class is EnumCaptureClass.NEVER_CAPTURE:
            state = max(state, EnumRedactionState.REDACTED, key=_state_rank)
            continue
        if capture_class is EnumCaptureClass.CAPTURE_HASHED:
            result[field] = hash_value(value)
            state = max(state, EnumRedactionState.REDACTED, key=_state_rank)
            continue
        if capture_class is EnumCaptureClass.CAPTURE_SHAPE_ONLY:
            result[field] = shape_of(value)
            state = max(state, EnumRedactionState.REDACTED, key=_state_rank)
            continue

        # The verbatim class -- still subject to the scrub.
        if _matches_secret(value, contract) is not None:
            result[field] = hash_value(value)
            state = EnumRedactionState.SECRET_DETECTED
        else:
            result[field] = value

    result[contract.redaction_state_field] = state.value
    return result


__all__: list[str] = [
    "CaptureRedactionError",
    "DerivedField",
    "EnumCaptureClass",
    "EnumRedactionState",
    "MalformedRedactionContractError",
    "OutputClass",
    "RedactionContract",
    "TopicPolicy",
    "UngovernedTopicError",
    "default_contract_path",
    "hash_value",
    "load_contract",
    "redact_capture",
    "shape_of",
]
