# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Contract-declared event registrations for the hook registry (OMN-21416).

``EVENT_REGISTRY`` in :mod:`omniclaude.hooks.event_registry` holds the events a
Claude Code hook emits. An event another repository publishes through the emit
daemon, such as omnimarket's ``delegation.usage_call`` and
``delegation.run_step``, is declared instead by a wire contract under
``hooks/contracts/wire/`` with an ``event_registration`` block, and the
registry lookup resolves it from there (ruling on OMN-21416, 2026-10-28:
contract-declared entries the hook registry reads, parsed by omnibase_core's
generic loader rather than by logic in this repository).

Every contract is parsed by omnibase_core's
``parse_registration_contract`` under the parameters of the core
event-registry drift validator's own contract (topic prefix, file globs, size
cap), so this handler and the core drift gate cannot disagree on what a
contract declares. Fails closed: a missing directory, an unreadable, oversized
or malformed contract, or two contracts declaring one event type raise
``ValueError`` naming every problem, never a partial result.

``event_registry`` imports this module inside ``get_registration`` only, on a
lookup the hook-emitted literal does not answer, so the hook import path pays
neither the import nor the YAML parse.
"""

from __future__ import annotations

import functools
from pathlib import Path
from typing import TYPE_CHECKING, cast

from omnibase_core.validation.checker_event_registry_drift_sources import (
    parse_registration_contract,
)
from omnibase_core.validation.checker_rule_parameters import (
    rule_int,
    rule_string,
    rule_strings,
)
from omnibase_core.validation.validator_event_registry_drift import (
    ValidatorEventDeclarationDrift,
)

from omniclaude.hooks.event_registry import EventRegistration, FanOutRule
from omniclaude.nodes.node_contract_event_registration_effect.models.model_contract_topic import (
    ModelContractTopic,
)

if TYPE_CHECKING:
    from omnibase_core.models.event_registry_drift.model_event_registration import (
        ModelEventRegistration,
    )

    from omniclaude.hooks.topics import TopicBase

__all__ = [
    "WIRE_CONTRACT_DIR",
    "HandlerContractEventRegistrations",
    "contract_event_registration",
    "contract_event_registrations",
]

WIRE_CONTRACT_DIR = Path(__file__).resolve().parents[3] / "hooks" / "contracts" / "wire"

# The core validator rule whose parameters say how a source is read.
_SOURCE_RULE_ID = "source_unreadable"


class HandlerContractEventRegistrations:
    """The registrations the wire contracts in one directory declare."""

    def load(self) -> dict[str, ModelEventRegistration]:
        """Every declared registration, by event type.

        A contract without an ``event_registration`` block declares none and
        is skipped. Raises ``ValueError`` when the directory is missing, a
        contract is oversized, unreadable or malformed, or two contracts
        declare one event type.
        """
        # Read at call time, so a test can repoint WIRE_CONTRACT_DIR.
        directory = WIRE_CONTRACT_DIR
        if not directory.is_dir():
            raise ValueError(f"{directory}: wire contract directory not found")
        rules = {
            rule.rule_id: rule
            for rule in ValidatorEventDeclarationDrift().contract.rules
        }
        source_rule = rules[_SOURCE_RULE_ID]
        max_bytes = rule_int(source_rule, "max_file_bytes")
        topic_prefix = rule_string(source_rule, "topic_prefix")
        paths = sorted(
            {
                path
                for pattern in rule_strings(source_rule, "contract_globs")
                for path in directory.glob(pattern)
            }
        )
        errors: list[str] = []
        registrations: dict[str, ModelEventRegistration] = {}
        for path in paths:
            try:
                if path.stat().st_size > max_bytes:
                    errors.append(f"{path}: exceeds max file size {max_bytes}")
                    continue
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                errors.append(f"{path}: cannot be read: {exc}")
                continue
            registration, parse_errors = parse_registration_contract(
                str(path), text, topic_prefix
            )
            errors.extend(parse_errors)
            if registration is None:
                continue
            earlier = registrations.get(registration.event_type)
            if earlier is not None:
                errors.append(
                    f"{path}: event type {registration.event_type!r} is already "
                    f"declared by {earlier.source}"
                )
                continue
            registrations[registration.event_type] = registration
        if errors:
            raise ValueError("; ".join(errors))
        return registrations

    def registrations(self) -> dict[str, EventRegistration]:
        """The declared registrations as hook ``EventRegistration`` values.

        Each fan-out rule carries the declared topic as a
        :class:`ModelContractTopic`, whose ``value`` is all ``FanOutRule``
        reads of ``topic_base``. No transform: the payload passes through as
        published.
        """
        return {
            event_type: EventRegistration(
                event_type=event_type,
                fan_out=[
                    FanOutRule(
                        topic_base=cast("TopicBase", ModelContractTopic(value=topic)),
                        description=f"contract-declared ({Path(reg.source).name})",
                    )
                    for topic in reg.topics
                ],
                partition_key_field=reg.partition_key_field,
                required_fields=list(reg.required_fields),
            )
            for event_type, reg in self.load().items()
        }


def contract_event_registrations() -> dict[str, EventRegistration]:
    """Every registration the packaged wire contracts declare, read afresh."""
    return HandlerContractEventRegistrations().registrations()


@functools.cache
def _packaged_contract_registrations() -> dict[str, EventRegistration]:
    return contract_event_registrations()


def contract_event_registration(event_type: str) -> EventRegistration | None:
    """The packaged wire contracts' registration for ``event_type``, if any."""
    return _packaged_contract_registrations().get(event_type)
