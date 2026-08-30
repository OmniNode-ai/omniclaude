#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Hook inventory parity [OMN-17020].

``hooks.json`` had no counterpart: nothing in the repo declared which hooks
were *supposed* to be registered, so unregistering one produced no signal at
all. OMN-13244 unregistered the whole surface and
``pre_tool_use_overseer_foreground_block.sh`` then sat on disk, dark, while the
rule it enforces was corrected by hand ~61 times over 16 of 18 days
(``docs/tracking/2026-08-29-beta-off-the-rails-analysis.md``, root cause RC-B).

This module reads ``plugins/onex/hooks/contracts/hook_inventory.yaml`` — the
declaration — and computes parity against two live surfaces:

* ``hooks.json``: what is actually registered, in what order, under which
  matcher.
* ``plugins/onex/hooks/scripts/``: what is actually on disk.

and, for the session-bootstrap caller only, a third:

* ``ONEX_HOOKS_MASK``: whether a registered hook's ``onex_hook_gate`` bit is
  cleared on THIS machine, which makes it a no-op with no repo-visible signal.
  That surface is per-machine, so it is never a merge gate — a runner has no
  ``~/.omnibase/.env``, and a check that passes because its input is absent is
  worse than no check.

Design constraints, in the order they mattered:

* **Typed, no defaults, fail fast.** A missing key raises
  :class:`HookInventoryError` rather than defaulting. An inventory that
  silently tolerates an absent ``review_by`` is the OMN-13244 failure written
  in Python.
* **Findings, not booleans.** Every disagreement is a :class:`Finding` naming
  the subject, so the gate output says *which* hook went dark rather than
  "parity failed".
* **No side effects and no imports beyond the stdlib plus PyYAML.** The
  bootstrap caller runs this on a user's machine at session start; it must not
  be able to cost the session anything.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, date
from pathlib import Path
from typing import Any, Final

__all__ = [
    "CanarySpec",
    "DisabledHook",
    "ExpectSpec",
    "ExpectedHook",
    "Finding",
    "HookInventory",
    "HookInventoryError",
    "MaskDeclaration",
    "Registration",
    "Restoration",
    "check_parity",
    "defined_mask_bits",
    "load_inventory",
    "load_registrations",
    "mask_findings",
    "mode_findings",
    "parse_mask",
]

#: Canary kinds. ``block`` = refuses the call (exit 2 + a block decision).
#: ``redact`` = rewrites the output in place (exit 0, secret gone).
#: ``pass_through`` = an observer proving it never refuses.
CANARY_KINDS: Final = frozenset({"block", "redact", "pass_through"})

#: Restoration kinds. ``re_register`` additionally requires the script to still
#: be on disk, so "put it back" is a config add rather than a rewrite.
RESTORATION_KINDS: Final = frozenset({"re_register", "delete", "repoint"})

_TICKET_RE: Final = re.compile(r"^OMN-\d+$")
_ISO_DATE_RE: Final = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_COMMAND_PREFIX: Final = "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/"
_GATE_CALL_RE: Final = re.compile(r"onex_hook_gate\s+([A-Z0-9_]+)")
#: The lite-mode early exit. ``mode.sh`` resolves "lite" for any cwd outside
#: omni_home/omni_worktrees with no local omnibase_core, which is the DEFAULT
#: on a CI runner and on any external repo — so a hook carrying this guard is
#: inert there no matter what hooks.json and ONEX_HOOKS_MASK say. Third disable
#: surface; declared per hook so it cannot be discovered by accident again.
#: Matches the early-exit COMPARISON (``"$(omniclaude_mode)" == "lite"``), not a
#: bare mention of the function — session_start_hook_parity.sh calls
#: ``omniclaude_mode`` to REPORT the mode and must not be counted as exiting on
#: it. Every hook that does exit writes the comparison on one line.
_LITE_MODE_RE: Final = re.compile(r"""\$\(omniclaude_mode\)"?\s*==\s*"?lite""")
_BIT_TABLE_RE: Final = re.compile(
    r"^\s+([A-Z0-9_]+)\)\s*echo\s+(0x[0-9a-fA-F]+)\s*;;", re.MULTILINE
)


class HookInventoryError(ValueError):
    """The inventory, or a surface it is compared against, is unusable.

    Raised, never swallowed. Callers that must not fail a user's session (the
    bootstrap hook) catch it at their own boundary and degrade to a printed
    warning; the merge gate lets it propagate.
    """


# ---------------------------------------------------------------------------
# Typed records
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Registration:
    """One command as ``hooks.json`` actually registers it."""

    event: str
    matcher: str | None
    order: int
    command: str
    script: str


@dataclass(frozen=True)
class ExpectSpec:
    """What a canary run must observe for the hook to count as firing."""

    exit_code: int
    stdout_contains: tuple[str, ...]
    stdout_absent: tuple[str, ...]


@dataclass(frozen=True)
class CanarySpec:
    """One end-to-end negative test against the *registered* script.

    The whole point of A17 is that this runs the script, not the guard
    function it calls: the OMN-8928 claim gate's Python returned a correct
    deny while the registered hook exited 0, because the error-guard EXIT trap
    swallowed the ``exit 2``. A unit test on the function would have passed.
    """

    kind: str
    stdin: dict[str, Any]
    env: dict[str, str]
    fixtures: dict[str, Any]
    expect: ExpectSpec


@dataclass(frozen=True)
class MaskDeclaration:
    """The hook's relationship to the ``ONEX_HOOKS_MASK`` disable surface.

    ``bit_defined`` is a *declared* fact the validator checks against
    ``hook_bits.sh``. A ``gate_call`` naming an undefined bit is a gate that
    can never fire — ``hook_bits_bit_for_name`` returns non-zero and
    ``onex_hook_gate`` returns 0 — so the hook runs unconditionally. Recording
    that rather than rounding it to "ungated" is the point of the field.
    """

    gate_call: str | None
    bit_defined: bool


@dataclass(frozen=True)
class ExpectedHook:
    """One registration the inventory requires ``hooks.json`` to carry."""

    script: str
    event: str
    matcher: str | None
    order: int
    ticket: str
    owner: str
    purpose: str
    enforcement: bool
    lite_mode_exit: bool
    mask: MaskDeclaration
    canary: CanarySpec | None
    no_canary_reason: str | None


@dataclass(frozen=True)
class Restoration:
    """What automatically puts a disabled hook back, and who tracks it."""

    kind: str
    reenable_ticket: str
    action: str


@dataclass(frozen=True)
class DisabledHook:
    """A script deliberately on disk and unregistered.

    Carries the four OMN-17006 fields as typed data rather than prose:
    ``owner``, ``reason``, ``review_by`` (absolute, machine-compared against
    today) and ``restoration``.
    """

    script: str
    owner: str
    reason: str
    review_by: date
    restoration: Restoration


@dataclass(frozen=True)
class HookInventory:
    """The parsed declaration."""

    path: Path
    schema_version: str
    ticket_id: str
    hooks_json: str
    scripts_dir: str
    hook_bits: str
    expected: tuple[ExpectedHook, ...]
    disabled: tuple[DisabledHook, ...]


@dataclass(frozen=True)
class Finding:
    """One drift fact. ``subject`` is always the hook it is about."""

    code: str
    subject: str
    detail: str

    def render(self) -> str:
        return f"{self.code}: {self.subject} — {self.detail}"


# ---------------------------------------------------------------------------
# Strict extraction helpers. Every one of these raises rather than defaulting.
# ---------------------------------------------------------------------------


def _require(mapping: dict[str, Any], key: str, where: str) -> Any:
    if key not in mapping:
        raise HookInventoryError(f"{where}: missing required key {key!r}")
    return mapping[key]


def _require_str(mapping: dict[str, Any], key: str, where: str) -> str:
    value = _require(mapping, key, where)
    if not isinstance(value, str) or not value.strip():
        raise HookInventoryError(f"{where}: {key!r} must be a non-empty string")
    return value.strip()


def _require_bool(mapping: dict[str, Any], key: str, where: str) -> bool:
    value = _require(mapping, key, where)
    if not isinstance(value, bool):
        raise HookInventoryError(f"{where}: {key!r} must be a boolean")
    return value


def _require_int(mapping: dict[str, Any], key: str, where: str) -> int:
    value = _require(mapping, key, where)
    if isinstance(value, bool) or not isinstance(value, int):
        raise HookInventoryError(f"{where}: {key!r} must be an integer")
    return value


def _require_mapping(mapping: dict[str, Any], key: str, where: str) -> dict[str, Any]:
    value = _require(mapping, key, where)
    if not isinstance(value, dict):
        raise HookInventoryError(f"{where}: {key!r} must be a mapping")
    return value


def _optional_str(mapping: dict[str, Any], key: str, where: str) -> str | None:
    value = _require(mapping, key, where)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise HookInventoryError(f"{where}: {key!r} must be null or a non-empty string")
    return value.strip()


def _require_str_tuple(
    mapping: dict[str, Any], key: str, where: str
) -> tuple[str, ...]:
    value = _require(mapping, key, where)
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise HookInventoryError(f"{where}: {key!r} must be a list of strings")
    return tuple(value)


def _require_ticket(mapping: dict[str, Any], key: str, where: str) -> str:
    value = _require_str(mapping, key, where)
    if not _TICKET_RE.match(value):
        raise HookInventoryError(
            f"{where}: {key!r} must be an OMN-XXXX ticket, got {value!r}. "
            "A disable or carve-out with no ticket is untrackable, which is "
            "exactly how OMN-13244 became indistinguishable from a decision."
        )
    return value


def _require_date(mapping: dict[str, Any], key: str, where: str) -> date:
    value = _require(mapping, key, where)
    # PyYAML parses an unquoted YYYY-MM-DD into datetime.date; both forms are
    # accepted, neither is guessed at.
    if isinstance(value, date):
        return value
    if isinstance(value, str) and _ISO_DATE_RE.match(value.strip()):
        return date.fromisoformat(value.strip())
    raise HookInventoryError(
        f"{where}: {key!r} must be an absolute ISO date (YYYY-MM-DD), got {value!r}. "
        "A relative or conditional expiry is not an expiry — it is the thing "
        "OMN-13244 already had."
    )


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def _parse_expect(raw: dict[str, Any], where: str) -> ExpectSpec:
    return ExpectSpec(
        exit_code=_require_int(raw, "exit_code", where),
        stdout_contains=_require_str_tuple(raw, "stdout_contains", where),
        stdout_absent=_require_str_tuple(raw, "stdout_absent", where),
    )


def _parse_canary(raw: Any, where: str) -> CanarySpec | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise HookInventoryError(f"{where}: canary must be a mapping or null")
    kind = _require_str(raw, "kind", where)
    if kind not in CANARY_KINDS:
        raise HookInventoryError(
            f"{where}: canary kind {kind!r} not one of {sorted(CANARY_KINDS)}"
        )
    env_raw = _require_mapping(raw, "env", where)
    if any(not isinstance(v, str) for v in env_raw.values()):
        raise HookInventoryError(f"{where}: canary env values must be strings")
    return CanarySpec(
        kind=kind,
        stdin=_require_mapping(raw, "stdin", where),
        env={str(k): str(v) for k, v in env_raw.items()},
        fixtures=_require_mapping(raw, "fixtures", where),
        expect=_parse_expect(_require_mapping(raw, "expect", where), where),
    )


def _parse_expected(raw: Any, index: int) -> ExpectedHook:
    where = f"expected_hooks[{index}]"
    if not isinstance(raw, dict):
        raise HookInventoryError(f"{where}: entry must be a mapping")
    script = _require_str(raw, "script", where)
    where = f"expected_hooks[{index}] ({script})"
    mask_raw = _require_mapping(raw, "mask", where)
    canary = _parse_canary(_require(raw, "canary", where), where)
    no_canary_reason = (
        raw["no_canary_reason"].strip()
        if isinstance(raw.get("no_canary_reason"), str)
        and raw["no_canary_reason"].strip()
        else None
    )
    return ExpectedHook(
        script=script,
        event=_require_str(raw, "event", where),
        matcher=_optional_str(raw, "matcher", where),
        order=_require_int(raw, "order", where),
        ticket=_require_ticket(raw, "ticket", where),
        owner=_require_str(raw, "owner", where),
        purpose=_require_str(raw, "purpose", where),
        enforcement=_require_bool(raw, "enforcement", where),
        lite_mode_exit=_require_bool(raw, "lite_mode_exit", where),
        mask=MaskDeclaration(
            gate_call=_optional_str(mask_raw, "gate_call", where),
            bit_defined=_require_bool(mask_raw, "bit_defined", where),
        ),
        canary=canary,
        no_canary_reason=no_canary_reason,
    )


def _parse_disabled(raw: Any, index: int) -> DisabledHook:
    where = f"disabled_hooks[{index}]"
    if not isinstance(raw, dict):
        raise HookInventoryError(f"{where}: entry must be a mapping")
    script = _require_str(raw, "script", where)
    where = f"disabled_hooks[{index}] ({script})"
    restoration_raw = _require_mapping(raw, "restoration", where)
    kind = _require_str(restoration_raw, "kind", where)
    if kind not in RESTORATION_KINDS:
        raise HookInventoryError(
            f"{where}: restoration kind {kind!r} not one of {sorted(RESTORATION_KINDS)}"
        )
    return DisabledHook(
        script=script,
        owner=_require_str(raw, "owner", where),
        reason=_require_str(raw, "reason", where),
        review_by=_require_date(raw, "review_by", where),
        restoration=Restoration(
            kind=kind,
            reenable_ticket=_require_ticket(restoration_raw, "reenable_ticket", where),
            action=_require_str(restoration_raw, "action", where),
        ),
    )


def load_inventory(path: Path) -> HookInventory:
    """Parse and structurally validate the inventory declaration."""
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise HookInventoryError(
            "PyYAML is required to read the hook inventory "
            f"({path}); install it or run the gate from an environment that has it"
        ) from exc

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise HookInventoryError(
            f"cannot read hook inventory at {path}: {exc}"
        ) from exc
    except yaml.YAMLError as exc:
        raise HookInventoryError(
            f"hook inventory at {path} is not valid YAML: {exc}"
        ) from exc

    if not isinstance(raw, dict):
        raise HookInventoryError(f"hook inventory at {path} must be a mapping")

    where = str(path)
    expected_raw = _require(raw, "expected_hooks", where)
    if not isinstance(expected_raw, list) or not expected_raw:
        raise HookInventoryError(f"{where}: expected_hooks must be a non-empty list")
    disabled_raw = _require(raw, "disabled_hooks", where)
    if not isinstance(disabled_raw, list):
        raise HookInventoryError(f"{where}: disabled_hooks must be a list")

    return HookInventory(
        path=path,
        schema_version=_require_str(raw, "schema_version", where),
        ticket_id=_require_ticket(raw, "ticket_id", where),
        hooks_json=_require_str(raw, "hooks_json", where),
        scripts_dir=_require_str(raw, "scripts_dir", where),
        hook_bits=_require_str(raw, "hook_bits", where),
        expected=tuple(_parse_expected(item, i) for i, item in enumerate(expected_raw)),
        disabled=tuple(_parse_disabled(item, i) for i, item in enumerate(disabled_raw)),
    )


def load_registrations(hooks_json_path: Path) -> tuple[Registration, ...]:
    """Flatten ``hooks.json`` into one record per registered command."""
    try:
        data = json.loads(hooks_json_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise HookInventoryError(f"cannot read {hooks_json_path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise HookInventoryError(f"{hooks_json_path} is not valid JSON: {exc}") from exc

    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        raise HookInventoryError(f"{hooks_json_path}: 'hooks' must be a mapping")

    out: list[Registration] = []
    for event, groups in hooks.items():
        if not isinstance(groups, list):
            raise HookInventoryError(f"{hooks_json_path}: {event!r} must be a list")
        order = 0
        for group in groups:
            if not isinstance(group, dict):
                raise HookInventoryError(
                    f"{hooks_json_path}: {event!r} group must be a mapping"
                )
            matcher = group.get("matcher")
            if matcher is not None and not isinstance(matcher, str):
                raise HookInventoryError(
                    f"{hooks_json_path}: {event!r} matcher must be a string or absent"
                )
            entries = group.get("hooks")
            if not isinstance(entries, list):
                raise HookInventoryError(
                    f"{hooks_json_path}: {event!r} group has no 'hooks' list"
                )
            for entry in entries:
                if not isinstance(entry, dict):
                    raise HookInventoryError(
                        f"{hooks_json_path}: {event!r} hook entry must be a mapping"
                    )
                command = entry.get("command")
                if not isinstance(command, str) or not command:
                    raise HookInventoryError(
                        f"{hooks_json_path}: {event!r} hook entry has no command"
                    )
                out.append(
                    Registration(
                        event=event,
                        matcher=matcher,
                        order=order,
                        command=command,
                        script=command.rsplit("/", 1)[-1],
                    )
                )
                order += 1
    return tuple(out)


def defined_mask_bits(hook_bits_path: Path) -> dict[str, int]:
    """Bit names defined in ``hook_bits.sh``, mapped to their bit value."""
    try:
        text = hook_bits_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise HookInventoryError(f"cannot read {hook_bits_path}: {exc}") from exc
    return {name: int(value, 16) for name, value in _BIT_TABLE_RE.findall(text)}


def parse_mask(raw: str) -> int:
    """Parse an ``ONEX_HOOKS_MASK`` literal the way ``hook_bits.sh`` does."""
    value = raw.strip()
    try:
        if value.lower().startswith("0x"):
            return int(value, 16)
        if value.lower().startswith("0b"):
            return int(value[2:], 2)
        return int(value, 10)
    except ValueError as exc:
        raise HookInventoryError(f"unparseable ONEX_HOOKS_MASK: {raw!r}") from exc


# ---------------------------------------------------------------------------
# Parity
# ---------------------------------------------------------------------------


def check_parity(
    inventory: HookInventory, repo_root: Path, today: date
) -> tuple[Finding, ...]:
    """Every disagreement between the inventory, hooks.json and the disk.

    Returns findings rather than raising, so the caller decides the posture:
    the merge gate fails on any finding, the bootstrap hook prints them and
    exits 0.
    """
    findings: list[Finding] = []
    hooks_json_path = repo_root / inventory.hooks_json
    scripts_dir = repo_root / inventory.scripts_dir
    registrations = load_registrations(hooks_json_path)
    registered_by_script: dict[str, list[Registration]] = {}
    for reg in registrations:
        registered_by_script.setdefault(reg.script, []).append(reg)

    declared_scripts = {hook.script for hook in inventory.expected}

    # 1. Every expected hook is registered, at the declared event/matcher/order.
    for hook in inventory.expected:
        matches = registered_by_script.get(hook.script, [])
        if not matches:
            findings.append(
                Finding(
                    "UNREGISTERED_EXPECTED",
                    hook.script,
                    f"declared under {hook.ticket} ({hook.owner}) as a registered "
                    f"{hook.event} hook, but {inventory.hooks_json} does not register "
                    "it. This is the OMN-13244 shape: enforcement switched off with "
                    "no record. Re-register it, or move it to disabled_hooks with "
                    "owner/reason/review_by/restoration.",
                )
            )
            continue
        if len(matches) > 1:
            findings.append(
                Finding(
                    "DUPLICATE_REGISTRATION",
                    hook.script,
                    f"registered {len(matches)} times "
                    f"({', '.join(f'{m.event}#{m.order}' for m in matches)}); the "
                    "inventory declares exactly one registration per script.",
                )
            )
            continue
        reg = matches[0]
        if reg.event != hook.event:
            findings.append(
                Finding(
                    "EVENT_MISMATCH",
                    hook.script,
                    f"declared under {hook.event}, registered under {reg.event}.",
                )
            )
        if reg.matcher != hook.matcher:
            findings.append(
                Finding(
                    "MATCHER_MISMATCH",
                    hook.script,
                    f"declared matcher {hook.matcher!r}, registered matcher "
                    f"{reg.matcher!r}. A widened matcher silently changes what the "
                    "guard sees; a narrowed one silently stops enforcing.",
                )
            )
        if reg.order != hook.order:
            findings.append(
                Finding(
                    "ORDER_MISMATCH",
                    hook.script,
                    f"declared order {hook.order} within {hook.event}, registered at "
                    f"{reg.order}. Order is behaviour, not cosmetics.",
                )
            )
        if not (scripts_dir / hook.script).is_file():
            findings.append(
                Finding(
                    "MISSING_SCRIPT",
                    hook.script,
                    f"registered and declared, but absent from {inventory.scripts_dir}. "
                    "A registration pointing at nothing fails at hook time, not here.",
                )
            )

    # 2. Nothing is registered that the inventory does not declare.
    for reg in registrations:
        if reg.script not in declared_scripts:
            findings.append(
                Finding(
                    "UNDECLARED_REGISTRATION",
                    reg.script,
                    f"registered under {reg.event} (matcher {reg.matcher!r}) but absent "
                    f"from expected_hooks in {inventory.path.name}. Add it with owner, "
                    "ticket, purpose and either a canary or a no_canary_reason — an "
                    "inventory nobody updates is the inventory OMN-13244 did not have.",
                )
            )

    # 3. Enforcement mechanisms carry an end-to-end canary; observers say why not.
    for hook in inventory.expected:
        if hook.enforcement and hook.canary is None:
            findings.append(
                Finding(
                    "ENFORCEMENT_WITHOUT_CANARY",
                    hook.script,
                    "declared enforcement: true with no canary. A17 requires every "
                    "enforcement mechanism to prove end to end that a synthetic "
                    "violation is refused by the REGISTERED hook — the OMN-8928 gate "
                    "returned a correct deny while its hook exited 0.",
                )
            )
        if (
            hook.enforcement
            and hook.canary is not None
            and hook.canary.kind == "pass_through"
        ):
            findings.append(
                Finding(
                    "ENFORCEMENT_CANARY_IS_PASSTHROUGH",
                    hook.script,
                    "declared enforcement: true but its canary only proves the hook "
                    "does nothing. A pass_through canary cannot witness a refusal.",
                )
            )
        if (
            not hook.enforcement
            and hook.canary is None
            and hook.no_canary_reason is None
        ):
            findings.append(
                Finding(
                    "OBSERVER_WITHOUT_REASON",
                    hook.script,
                    "declared enforcement: false with neither a pass_through canary "
                    "nor a no_canary_reason. 'It only observes' is a claim; it needs "
                    "either a proof or a stated reason one cannot be run.",
                )
            )

    # 4. The mask surface, statically: does the declared gate call exist, and is
    #    the bit it names actually defined?
    bits = defined_mask_bits(repo_root / inventory.hook_bits)
    for hook in inventory.expected:
        script_path = scripts_dir / hook.script
        if not script_path.is_file():
            continue
        source = script_path.read_text(encoding="utf-8")
        actual_lite = _LITE_MODE_RE.search(source) is not None
        if actual_lite != hook.lite_mode_exit:
            findings.append(
                Finding(
                    "LITE_MODE_EXIT_MISMATCH",
                    hook.script,
                    f"declares lite_mode_exit={hook.lite_mode_exit}, but the script "
                    f"{'does' if actual_lite else 'does not'} carry the mode.sh "
                    "lite-mode early exit. mode.sh resolves 'lite' for any cwd "
                    "outside omni_home/omni_worktrees with no local omnibase_core "
                    "— the default on a CI runner and in every external repo — so "
                    "this bit decides whether the hook exists there at all.",
                )
            )
        found = _GATE_CALL_RE.search(source)
        actual_call = found.group(1) if found else None
        if actual_call != hook.mask.gate_call:
            findings.append(
                Finding(
                    "MASK_GATE_CALL_MISMATCH",
                    hook.script,
                    f"declares mask.gate_call {hook.mask.gate_call!r}, script calls "
                    f"{actual_call!r}. The mask is a second disable surface; a "
                    "declaration that does not match it cannot report darkness.",
                )
            )
            continue
        expected_defined = actual_call is not None and actual_call in bits
        if expected_defined != hook.mask.bit_defined:
            findings.append(
                Finding(
                    "MASK_BIT_DEFINED_MISMATCH",
                    hook.script,
                    f"declares mask.bit_defined={hook.mask.bit_defined}, but "
                    f"{hook.mask.gate_call!r} is "
                    f"{'defined' if expected_defined else 'NOT defined'} in "
                    f"{inventory.hook_bits}. An undefined bit means onex_hook_gate "
                    "always returns 0 and the hook is ungated in practice.",
                )
            )

    # 5. Disabled hooks: still on disk, still unregistered, still within review.
    for disabled in inventory.disabled:
        if disabled.script in registered_by_script:
            findings.append(
                Finding(
                    "DISABLED_BUT_REGISTERED",
                    disabled.script,
                    f"listed as a deliberate disable owned by {disabled.owner}, but "
                    f"{inventory.hooks_json} registers it. The two halves of the "
                    "inventory contradict each other; one of them is a lie.",
                )
            )
        if not (scripts_dir / disabled.script).is_file():
            findings.append(
                Finding(
                    "DISABLED_SCRIPT_DELETED",
                    disabled.script,
                    f"declared restoration kind {disabled.restoration.kind!r} under "
                    f"{disabled.restoration.reenable_ticket}, but the script is gone "
                    "from disk. Deleting it is the expiry branch and must close the "
                    "re-enable ticket in the same change, not happen silently.",
                )
            )
        elif disabled.review_by < today:
            findings.append(
                Finding(
                    "DISABLE_REVIEW_LAPSED",
                    disabled.script,
                    f"review_by {disabled.review_by.isoformat()} has passed (today is "
                    f"{today.isoformat()}). Owner: {disabled.owner}. Re-enable ticket: "
                    f"{disabled.restoration.reenable_ticket}. Declared restoration "
                    f"({disabled.restoration.kind}): "
                    f"{disabled.restoration.action.strip()} — do that, or move the "
                    "date with a stated reason. A disable that outlives its own "
                    "review date is the OMN-13244 defect, not a decision.",
                )
            )

    return tuple(findings)


def mode_findings(inventory: HookInventory, mode: str | None) -> tuple[Finding, ...]:
    """Registered hooks that this session's OMNICLAUDE_MODE switches off.

    The third disable surface, and the least visible of the three, because it
    is not written down anywhere: ``mode.sh`` resolves "lite" by *default* for
    any cwd outside omni_home/omni_worktrees with no local ``omnibase_core``.
    Found while building this inventory — three registered ENFORCEMENT guards
    (done-flip, lane-liveness, secret-redaction) exit 0 silently under lite,
    which is why their canaries passed on the operator Mac and failed on a CI
    runner. Per-session, therefore never a merge gate.
    """
    if mode is None or mode.strip().lower() != "lite":
        return ()
    return tuple(
        Finding(
            "DARK_IN_LITE_MODE",
            hook.script,
            "registered, but this session resolved OMNICLAUDE_MODE=lite and the "
            "script exits early under lite mode, so it does nothing here"
            + (
                ". It is an ENFORCEMENT hook: the control it provides is absent."
                if hook.enforcement
                else "."
            )
            + " mode.sh defaults to lite outside omni_home/omni_worktrees; set "
            "OMNICLAUDE_MODE=full or ~/.config/omniclaude/mode to change it.",
        )
        for hook in inventory.expected
        if hook.lite_mode_exit
    )


def mask_findings(
    inventory: HookInventory, repo_root: Path, mask_literal: str | None
) -> tuple[Finding, ...]:
    """Registered hooks this machine's ``ONEX_HOOKS_MASK`` switches off.

    Per-machine, therefore never a merge gate. This is the surface that had
    ``pre_tool_use_worktree_guard.sh`` registered under the OMN-14330 carve-out
    and dark in practice on the operator Mac.
    """
    if mask_literal is None:
        return ()
    bits = defined_mask_bits(repo_root / inventory.hook_bits)
    mask = parse_mask(mask_literal)
    out: list[Finding] = []
    for hook in inventory.expected:
        call = hook.mask.gate_call
        if call is None or call not in bits:
            continue
        if not mask & bits[call]:
            out.append(
                Finding(
                    "MASKED_OFF",
                    hook.script,
                    f"registered, but its {call} bit ({bits[call]:#x}) is cleared in "
                    f"ONEX_HOOKS_MASK={mask_literal}. The hook is dark on this "
                    "machine. Clear the stale literal in ~/.omnibase/.env or run "
                    f"`onex hooks enable {call}`.",
                )
            )
    return tuple(out)


# ---------------------------------------------------------------------------
# Session-bootstrap entry point (DoD 3): parity + live mask, WARN ONLY.
# ---------------------------------------------------------------------------
# Deliberately separate from scripts/validation/validate_hook_inventory.py.
# The logic is shared; the POSTURE is the difference, and the posture is the
# whole point: CI fails closed on drift, the bootstrap never does. Blocking a
# session start because an inventory disagrees would be a larger outage than
# the one it reports, so this path exits 0 on every outcome including its own
# failure to run.


def _bootstrap_main() -> int:
    import os
    from datetime import datetime

    root_env = os.environ.get("ONEX_HOOK_INVENTORY_REPO_ROOT")
    if not root_env:
        print(
            "[hook-inventory] SKIPPED: ONEX_HOOK_INVENTORY_REPO_ROOT not set by the "
            "caller; nothing to compare against."
        )
        return 0
    repo_root = Path(root_env)
    try:
        inventory = load_inventory(
            repo_root / "plugins/onex/hooks/contracts/hook_inventory.yaml"
        )
        today = datetime.now(UTC).date()
        findings = list(check_parity(inventory, repo_root, today))
        findings.extend(
            mask_findings(inventory, repo_root, os.environ.get("ONEX_HOOKS_MASK"))
        )
        findings.extend(
            mode_findings(inventory, os.environ.get("ONEX_HOOK_INVENTORY_MODE"))
        )
    except Exception as exc:  # noqa: BLE001 - never cost the session a start
        print(f"[hook-inventory] SKIPPED: {exc}")
        return 0

    if not findings:
        return 0

    print(f"[hook-inventory] WARNING: {len(findings)} hook-inventory finding(s).")
    for finding in findings:
        print(f"[hook-inventory]   {finding.render()}")
    print(
        "[hook-inventory] Authority: plugins/onex/hooks/contracts/hook_inventory.yaml "
        "(OMN-17020). This is a warning: session start is never blocked on it."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(_bootstrap_main())
