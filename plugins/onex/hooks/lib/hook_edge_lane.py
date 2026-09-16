#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Hook-edge bus lane resolution from the declared contract [OMN-17204].

The hook edge used to have no declared lane. Which .201 broker a
``*_bus_mirror.sh`` published to was decided, per invocation, by shell
sourcing order: ``common.sh`` sources ``~/.omnibase/.env`` under ``set -a``
*after* the Claude session env is in place, so that file beat
``~/.claude/settings.json``'s own ``KAFKA_BOOTSTRAP_SERVERS`` export — while
``omnibase_infra/config/overlays/mac-dev.yaml``, which the emit node's own
``contract.yaml`` names as the authority, carried a third value matching
neither. Three separate wrong conclusions were drawn from that one undeclared
fact (OMN-16162, OMN-16996, ``beta/GOAL.md`` row 0).

This module reads ``plugins/onex/hooks/contracts/hook_edge_lane.yaml`` — the
single authority — and exposes:

* :func:`load_contract` — parse and structurally validate the declaration.
* :func:`resolve_bootstrap_servers` — the publisher's answer.
* :func:`audit_surfaces` — which demoted host surfaces disagree, so a
  disagreement is *legible* rather than *decisive* (AC3).

Deliberately dependency-light and side-effect-free: the shell resolver
(``scripts/hook_edge_lane.sh``) does not call into Python at hook time at all,
so a broken interpreter can never cost the session a lane. This module is what
the tests and the CI gate read.
"""

from __future__ import annotations

import os
import stat
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

__all__ = [
    "CREDENTIAL_SOURCE_ONEX_LANE_STORE",
    "CREDENTIAL_SOURCE_OPERATOR_ENV_FILE",
    "DEFAULT_ONEX_HOME",
    "DEFAULT_OPERATOR_ENV_FILE",
    "HookEdgeLaneContract",
    "HookEdgeLaneCredentialError",
    "LaneEndpoint",
    "SurfaceFinding",
    "audit_surfaces",
    "load_contract",
    "onex_home_path",
    "operator_env_file_path",
    "read_lane_client_store",
    "read_operator_env_file",
    "resolve_credential_environment",
    "resolve_bootstrap_servers",
    "resolve_governed_event_types",
    "resolve_governed_topics",
    "resolve_transport_env",
]

# The four names ``ModelKafkaEventBusConfig.apply_environment_overrides()``
# reads, and no others. The prefix a lane declares governs only WHERE the
# credential is stored on this host; the client always reads the bare names.
ENV_SECURITY_PROTOCOL = "KAFKA_SECURITY_PROTOCOL"
ENV_SASL_MECHANISM = "KAFKA_SASL_MECHANISM"
ENV_SASL_USERNAME = "KAFKA_SASL_USERNAME"
ENV_SASL_PASSWORD = "KAFKA_SASL_PASSWORD"  # noqa: S105 - secret-ok: env var NAME

# Spelled as librdkafka spells them, same vocabulary as
# omnimarket/config/ci_bus_lanes.yaml and the deploy agent's
# ModelDeployAgentKafkaConfig, so a lane declaration reads identically
# wherever a reader meets one.
SASL_PROTOCOLS = frozenset({"SASL_PLAINTEXT", "SASL_SSL"})
NON_SASL_PROTOCOLS = frozenset({"PLAINTEXT", "SSL"})
VALID_SECURITY_PROTOCOLS = SASL_PROTOCOLS | NON_SASL_PROTOCOLS
VALID_SASL_MECHANISMS = frozenset({"PLAIN", "SCRAM-SHA-256", "SCRAM-SHA-512"})

# The surface deploy-runtime.sh already resolves the lane's SCRAM principal
# from on the lab host. Matching its name and its default is deliberate: one
# credential surface per host, not a second one invented for this producer.
DEFAULT_OPERATOR_ENV_FILE = "~/.omnibase/.env"
ENV_OPERATOR_ENV_FILE = "OMNIBASE_OPERATOR_ENV_FILE"

# WHERE a SASL lane's credential is resolved from, declared per lane and never
# searched for. The two surfaces are genuinely different machines' answers, not
# a preference order:
#
#   operator_env_file -> the lab host. `deploy-runtime.sh` resolves the dev
#       lane's principal from `${HOME}/.omnibase/.env`, which is also what the
#       fifteen dev-lane compose services bind from. A lane declaring this
#       source names the PREFIX its two variables carry there.
#   onex_lane_store   -> an operator workstation. `onex auth lane-login` writes
#       `~/.onex/config.yaml` `lanes.<lane>` (a principal NAME and a REFERENCE)
#       plus `~/.onex/credentials.json` (mode 0600, the value), and
#       `onex delegate --lane <lane>` reads exactly that pair. A lane declaring
#       this source needs no prefix: the entry is keyed by the lane itself.
#
# Declaring it, rather than trying one and falling back to the other, is the
# whole point. A fallback chain would restore resolution-by-search-order for
# the credential -- the defect this contract was created to retire for the
# broker -- and on a machine holding two identities it would silently
# authenticate as whichever file was read first.
CREDENTIAL_SOURCE_OPERATOR_ENV_FILE = "operator_env_file"
CREDENTIAL_SOURCE_ONEX_LANE_STORE = "onex_lane_store"
VALID_CREDENTIAL_SOURCES = frozenset(
    {CREDENTIAL_SOURCE_OPERATOR_ENV_FILE, CREDENTIAL_SOURCE_ONEX_LANE_STORE}
)

# The one place `~/.onex` is spelled. Matches `omnibase_infra`'s
# `cli/cli_auth.py`, which constructs `StoreLaneCredential(onex_home=
# Path.home() / ".onex")` -- one store per machine, two readers.
# The two *_KEY names below are YAML KEY names, never values. They keep the
# spelling omnibase_infra's StoreLaneCredential uses for the identical
# constants -- that spelling is load-bearing, since it is what the file on
# disk is keyed by -- so they carry the scanners' false-positive
# annotations rather than being renamed out of the way.
DEFAULT_ONEX_HOME = "~/.onex"
LANE_STORE_CONFIG_FILE = "config.yaml"
LANE_STORE_VALUE_FILE = "credentials.json"
LANE_STORE_LANES_BLOCK = "lanes"
LANE_STORE_USERNAME_KEY = "sasl_username"
LANE_STORE_PASSWORD_REF_KEY = "sasl_password_ref"  # noqa: S105 - secret-ok: key NAME  # pragma: allowlist secret
LANE_STORE_INLINE_PASSWORD_KEY = "sasl_password"  # noqa: S105 - secret-ok: key NAME  # pragma: allowlist secret


class HookEdgeLaneError(ValueError):
    """The declaration is structurally unusable.

    Raised, never swallowed: an unreadable lane declaration must fail the gate
    loudly. The *hook* path never imports this module, so raising here cannot
    break a user's session.
    """


class HookEdgeLaneCredentialError(HookEdgeLaneError):
    """The declared lane needs a credential this host does not hold.

    Distinct from :class:`HookEdgeLaneError` because the remedies are
    different and a caller should be able to tell them apart: a malformed
    contract is fixed in the repository, whereas this one is fixed by placing
    the value the lane's declared prefix points at into the operator env file
    on this machine.

    The message names the VARIABLES and the FILE. It never carries a value.
    """


@dataclass(frozen=True)
class LaneEndpoint:
    """One lane's host-side bus endpoint, container network, and transport.

    ``security_protocol`` and ``sasl_mechanism`` are the lane's TRANSPORT,
    declared here and never inferred by the producer. The distinction matters:
    the pre-OMN-18012 publishers chose their protocol from whether credentials
    happened to be present in the environment, so a listener that moved to
    SASL-over-plaintext met a client that had decided on TLS. Credential
    presence is not a statement about transport; the lane is.

    ``sasl_credential_source`` is the lane's declared answer to WHERE the
    credential is resolved from, and it is required on a SASL lane for the
    same reason ``security_protocol`` is: a producer that searches for its own
    identity is a producer whose identity depends on which file it read first.
    See ``VALID_CREDENTIAL_SOURCES`` for what the two values mean.

    ``sasl_env_prefix`` is a REFERENCE, not a value -- it names the prefix the
    credential is stored under on this host (``DEV_`` -> the operator env
    file's ``DEV_KAFKA_SASL_USERNAME`` / ``DEV_KAFKA_SASL_PASSWORD``), so a
    checked-in lane map never becomes a credential store. It belongs to the
    ``operator_env_file`` source ONLY: the client store is keyed by lane, so a
    prefix there would be a second, contradictory answer.
    """

    name: str
    compose_project: str
    network: str
    bootstrap_servers: str
    security_protocol: str
    sasl_mechanism: str | None = None
    sasl_env_prefix: str | None = None
    sasl_credential_source: str | None = None


@dataclass(frozen=True)
class HookEdgeLaneContract:
    """The declared hook-edge lane pairing.

    ``lane`` is the single field both sides read. ``bootstrap_servers`` and
    ``relay_required_network`` are *derived* from it, which is why a
    publisher/consumer split cannot be written down in the first place — the
    only way to express one is to make ``relay.required_network`` disagree with
    the lane's network, and that is precisely what the gate rejects.
    """

    path: Path
    lane: str
    known_lanes: dict[str, LaneEndpoint]
    relay_container: str
    relay_required_network: str
    topic_registry: str
    governed_topics: tuple[str, ...]
    non_authoritative_surfaces: tuple[str, ...]

    @property
    def bootstrap_servers(self) -> str:
        return self.known_lanes[self.lane].bootstrap_servers

    @property
    def network(self) -> str:
        return self.known_lanes[self.lane].network


@dataclass(frozen=True)
class SurfaceFinding:
    """What one demoted host surface says, and whether it matches the contract."""

    surface: str
    observed: str | None
    expected: str
    agrees: bool


def _require(mapping: dict[str, Any], key: str, where: str) -> Any:
    """Fetch a required key, or fail loudly.

    No defaults: a missing field in the one file that settles the lane must
    surface as an error, not as a quietly-chosen fallback. Silent defaults are
    the exact failure mode this ticket exists to retire.
    """
    if key not in mapping:
        raise HookEdgeLaneError(f"{where}: missing required key {key!r}")
    return mapping[key]


def _parse_transport(
    entry: dict[str, Any], scope: str
) -> tuple[str, str | None, str | None, str | None]:
    """Validate one lane's declared transport, or refuse it.

    Two contradictions are refused rather than passed to a client, because
    both of them fail at a socket in a way that reads like a broker outage:

    * a SASL protocol with no mechanism -- the client cannot negotiate;
    * a mechanism beside a non-SASL protocol -- the declaration says two
      different things and whichever the client believes, the other reader is
      wrong.

    A SASL lane must also name ``sasl_credential_source``, and -- when that
    source is the operator env file -- a ``sasl_env_prefix``. Without them the
    lane declares that authentication is required and gives no way to resolve
    it, which is a run-time failure disguised as a complete declaration.

    A lane that names the client store AND a prefix is refused rather than
    resolved by precedence. Two declared sources is not a declaration, and
    picking one silently is how a machine ends up authenticating as an
    identity nobody chose.
    """
    protocol_raw = _require(entry, "security_protocol", scope)
    if not isinstance(protocol_raw, str) or not protocol_raw.strip():
        raise HookEdgeLaneError(
            f"{scope}: security_protocol must name a librdkafka security "
            f"protocol; valid values: {sorted(VALID_SECURITY_PROTOCOLS)}"
        )
    protocol = protocol_raw.strip().upper()
    if protocol not in VALID_SECURITY_PROTOCOLS:
        raise HookEdgeLaneError(
            f"{scope}: {protocol_raw!r} is not a librdkafka security protocol; "
            f"valid values: {sorted(VALID_SECURITY_PROTOCOLS)}"
        )

    mechanism_raw = entry.get("sasl_mechanism")
    mechanism: str | None = None
    if mechanism_raw is not None:
        if not isinstance(mechanism_raw, str) or not mechanism_raw.strip():
            raise HookEdgeLaneError(
                f"{scope}: sasl_mechanism must name a mechanism when declared; "
                f"valid values: {sorted(VALID_SASL_MECHANISMS)}"
            )
        mechanism = mechanism_raw.strip().upper()
        if mechanism not in VALID_SASL_MECHANISMS:
            raise HookEdgeLaneError(
                f"{scope}: {mechanism_raw!r} is not a supported SASL mechanism; "
                f"valid values: {sorted(VALID_SASL_MECHANISMS)}"
            )

    prefix_raw = entry.get("sasl_env_prefix")
    prefix: str | None = None
    if prefix_raw is not None:
        if not isinstance(prefix_raw, str) or not prefix_raw.strip():
            raise HookEdgeLaneError(
                f"{scope}: sasl_env_prefix must be a non-empty string when "
                "declared -- it names where this host holds the credential"
            )
        prefix = prefix_raw.strip()

    source_raw = entry.get("sasl_credential_source")
    source: str | None = None
    if source_raw is not None:
        if not isinstance(source_raw, str) or not source_raw.strip():
            raise HookEdgeLaneError(
                f"{scope}: sasl_credential_source must name a surface when "
                f"declared; valid values: {sorted(VALID_CREDENTIAL_SOURCES)}"
            )
        source = source_raw.strip()
        if source not in VALID_CREDENTIAL_SOURCES:
            raise HookEdgeLaneError(
                f"{scope}: {source_raw!r} is not a credential source this "
                f"resolver knows; valid values: {sorted(VALID_CREDENTIAL_SOURCES)}"
            )

    if protocol in SASL_PROTOCOLS:
        if mechanism is None:
            raise HookEdgeLaneError(
                f"{scope}: security_protocol {protocol} requires a "
                "sasl_mechanism; a SASL client with no mechanism cannot "
                "negotiate and fails at the socket like a broker outage"
            )
        if source is None:
            raise HookEdgeLaneError(
                f"{scope}: security_protocol {protocol} requires a "
                "sasl_credential_source naming WHERE this host resolves the "
                f"identity from; valid values: {sorted(VALID_CREDENTIAL_SOURCES)}. "
                "A producer that searches instead of reading a declaration "
                "authenticates as whichever surface it happened to read first"
            )
        if source == CREDENTIAL_SOURCE_OPERATOR_ENV_FILE and prefix is None:
            raise HookEdgeLaneError(
                f"{scope}: sasl_credential_source {source!r} requires a "
                "sasl_env_prefix naming where this host holds the credential; "
                "the VALUE is never written into this contract"
            )
        if source == CREDENTIAL_SOURCE_ONEX_LANE_STORE and prefix is not None:
            raise HookEdgeLaneError(
                f"{scope}: sasl_env_prefix is declared beside "
                f"sasl_credential_source {source!r}, which keys the identity "
                "by lane and needs no prefix; two declared sources is not a "
                "declaration"
            )
    else:
        if mechanism is not None:
            raise HookEdgeLaneError(
                f"{scope}: sasl_mechanism {mechanism!r} is declared beside "
                f"security_protocol {protocol}, which speaks no SASL; a "
                "declaration that says two things is not a declaration"
            )
        if prefix is not None:
            raise HookEdgeLaneError(
                f"{scope}: sasl_env_prefix is declared beside security_protocol "
                f"{protocol}, which needs no credential"
            )
        if source is not None:
            raise HookEdgeLaneError(
                f"{scope}: sasl_credential_source is declared beside "
                f"security_protocol {protocol}, which needs no credential"
            )

    return protocol, mechanism, prefix, source


def operator_env_file_path() -> Path:
    """Where this host holds its lane credentials.

    ``OMNIBASE_OPERATOR_ENV_FILE`` with the same default
    ``deploy-runtime.sh`` uses. A path, not a secret -- so a default here is
    a pointer to the fleet's one credential surface, not the silent wrong
    value rule 8 forbids.
    """
    declared = os.environ.get(ENV_OPERATOR_ENV_FILE)
    return (
        Path(declared).expanduser()
        if declared
        else Path(DEFAULT_OPERATOR_ENV_FILE).expanduser()
    )


def read_operator_env_file(path: Path) -> dict[str, str]:
    """Parse ``KEY=VALUE`` rows out of the operator env file.

    Read, never exported wholesale: this returns a mapping the caller picks
    named keys out of. Sourcing the whole file into the process environment is
    what made ``.env`` sourcing order decide the lane in the first place --
    the defect OMN-17204 exists to retire.

    An absent or unreadable file yields ``{}``. The refusal belongs to
    :func:`resolve_transport_env`, which can name the variable it wanted; a
    reader that raised here would produce a traceback naming only a path.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}

    parsed: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        if stripped.startswith("export "):
            stripped = stripped[len("export ") :].lstrip()
        key, _, value = stripped.partition("=")
        key = key.strip()
        if not key or not key.replace("_", "").isalnum():
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        parsed[key] = value
    return parsed


def onex_home_path() -> Path:
    """The per-lane client store root on this machine.

    One spelling of ``~/.onex``, matching ``omnibase_infra``'s
    ``cli/cli_auth.py``, which constructs its store as
    ``StoreLaneCredential(onex_home=Path.home() / ".onex")``. A path, not a
    secret, so resolving it here is a pointer to the machine's one identity
    store rather than the silent wrong value rule 8 forbids.
    """
    return Path(DEFAULT_ONEX_HOME).expanduser()


def read_lane_client_store(lane: str, *, onex_home: Path) -> dict[str, str]:
    """Resolve one lane's bus identity out of the ``~/.onex`` client store.

    Returns the two bare names ``ModelKafkaEventBusConfig`` reads, or ``{}``
    when this machine simply holds no identity for this lane. Absence is not
    corruption: the refusal for an absent identity belongs to
    :func:`resolve_transport_env`, which can name the lane, the file and the
    remedy, whereas a reader that raised here would produce a traceback naming
    only a path.

    What it DOES raise on is a store that is present and wrong, because each
    of those states resolves to an anonymous or mistaken connect against an
    auth-required listener:

    * a value spelled inline in ``config.yaml`` -- that file is world-readable
      by default and is what operators paste into issues, which is precisely
      why the canonical store refuses an inline password outright instead of
      accepting it with a warning;
    * a ``credentials.json`` any group or other identity can read. Enforced on
      READ, not only on write: the file survives ``chmod``, backup/restore and
      ``scp``, so a write-time check proves nothing about the file actually
      being loaded;
    * a reference with no value behind it, or a half-written entry.

    This is a narrow reader of the shape ``StoreLaneCredential`` owns, not a
    second implementation of it. It is deliberately not an import of that
    class: the hook edge must stay resolvable by the stdlib plus a YAML parse,
    because the CI gate that validates this contract runs where
    ``omnibase_infra`` is not installed, and the drainer's own venv currently
    carries a build that predates the class.
    """
    import yaml

    config_path = onex_home / LANE_STORE_CONFIG_FILE
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return {}
    if not isinstance(raw, dict):
        return {}

    block = raw.get(LANE_STORE_LANES_BLOCK)
    if not isinstance(block, dict):
        return {}
    entry = block.get(lane)
    if not isinstance(entry, dict):
        return {}

    if LANE_STORE_INLINE_PASSWORD_KEY in entry:
        raise HookEdgeLaneCredentialError(
            f"{config_path}: lanes.{lane} carries an inline "
            f"{LANE_STORE_INLINE_PASSWORD_KEY}. That file is world-readable by "
            f"default; the value belongs in {LANE_STORE_VALUE_FILE} behind a "
            f"{LANE_STORE_PASSWORD_REF_KEY}. Re-place it with "
            f"{_lane_login_remediation(lane)}"
        )

    username = entry.get(LANE_STORE_USERNAME_KEY)
    # password_ref holds the KEY the value is filed under in credentials.json,
    # read out of config.yaml. It is a reference; the value is never here.
    password_ref = entry.get(LANE_STORE_PASSWORD_REF_KEY)  # secret-ok: a ref key
    for key, value in (
        (LANE_STORE_USERNAME_KEY, username),
        (LANE_STORE_PASSWORD_REF_KEY, password_ref),
    ):
        if not isinstance(value, str) or not value.strip():
            raise HookEdgeLaneCredentialError(
                f"{config_path}: lanes.{lane} is a half-written identity -- "
                f"{key} is missing or blank. A partially resolved bus identity "
                "becomes an anonymous connect against an auth-required "
                f"listener. Re-place it with {_lane_login_remediation(lane)}"
            )
    assert isinstance(username, str) and isinstance(password_ref, str)

    secrets_path = onex_home / LANE_STORE_VALUE_FILE

    import json

    # The mode is read from the OPEN DESCRIPTOR, and the bytes are read from
    # that same descriptor, so the file whose permissions were checked is
    # necessarily the file that was read. A path-based `stat()` followed by a
    # separate `read_text()` leaves a window between the two in which the mode
    # can change, which is a check that proves nothing about the read.
    try:
        with secrets_path.open("r", encoding="utf-8") as handle:
            mode = stat.S_IMODE(os.fstat(handle.fileno()).st_mode)
            if mode & 0o077:
                raise HookEdgeLaneCredentialError(
                    f"{secrets_path} is mode {mode:04o}; a bus credential "
                    "readable by any other identity on this machine is "
                    f"refused. Fix it with 'chmod 600 {secrets_path}'"
                )
            value_file_text = handle.read()
    except OSError as exc:
        raise HookEdgeLaneCredentialError(
            f"{config_path}: lanes.{lane} points at {password_ref!r} but "
            f"{secrets_path} cannot be read ({exc.strerror}). Re-place the "
            f"identity with {_lane_login_remediation(lane)}"
        ) from exc

    try:
        secrets = json.loads(value_file_text)  # secret-ok: file bytes, not a literal
    except ValueError as exc:
        raise HookEdgeLaneCredentialError(
            f"{secrets_path} does not parse as JSON ({exc}); re-place the "
            f"identity with {_lane_login_remediation(lane)}"
        ) from exc
    if not isinstance(secrets, dict):
        raise HookEdgeLaneCredentialError(
            f"{secrets_path} is not a JSON object of reference -> value"
        )

    secret = secrets.get(password_ref)
    if not isinstance(secret, str) or not secret:
        raise HookEdgeLaneCredentialError(
            f"{config_path}: lanes.{lane} names {password_ref!r} and "
            f"{secrets_path} holds no value under it. Re-place the identity "
            f"with {_lane_login_remediation(lane)}"
        )

    return {ENV_SASL_USERNAME: username.strip(), ENV_SASL_PASSWORD: secret}


def _lane_login_remediation(lane: str) -> str:
    """The exact command that places a lane identity on this machine.

    Spelled the way ``omnibase_infra``'s ``StoreLaneCredential`` spells it, so
    a refusal from either reader names the same fix.
    """
    return (
        f"'onex auth lane-login --lane {lane} --sasl-username <principal> "
        "--sasl-password-stdin'"
    )


def _declared_credential_surface(
    contract: HookEdgeLaneContract, *, onex_home: Path | None = None
) -> tuple[dict[str, str], str]:
    """Read the ONE surface this lane declares, and name it.

    Never a fallback chain. The declaration is the answer; if the declared
    surface is empty, that is a refusal with a remedy, not a reason to consult
    a different file.
    """
    endpoint = contract.known_lanes[contract.lane]
    if endpoint.sasl_credential_source == CREDENTIAL_SOURCE_ONEX_LANE_STORE:
        home = onex_home if onex_home is not None else onex_home_path()
        return (
            read_lane_client_store(contract.lane, onex_home=home),
            str(home / LANE_STORE_CONFIG_FILE),
        )
    env_file = operator_env_file_path()
    return read_operator_env_file(env_file), str(env_file)


def resolve_credential_environment(
    contract: HookEdgeLaneContract, *, onex_home: Path | None = None
) -> dict[str, str]:
    """The transport environment for the declared lane, credential included.

    The one entry point a publisher calls. It reads the surface the lane
    declares and nothing else, so the identity this process presents is a
    property of the contract rather than of the filesystem it happens to find.

    ``onex_home`` is injected rather than derived inside, for the same reason
    the canonical store injects it: a test must be able to drive a real
    directory without patching the home lookup.
    """
    endpoint = contract.known_lanes[contract.lane]
    if endpoint.security_protocol not in SASL_PROTOCOLS:
        return resolve_transport_env(contract, credential_source={})
    credentials, surface = _declared_credential_surface(contract, onex_home=onex_home)
    return resolve_transport_env(
        contract, credential_source=credentials, credential_source_name=surface
    )


def resolve_transport_env(
    contract: HookEdgeLaneContract,
    *,
    credential_source: Mapping[str, str],
    credential_source_name: str | None = None,
) -> dict[str, str]:
    """The environment the declared lane's transport requires.

    Returns the subset of the four ``ModelKafkaEventBusConfig`` names this
    lane actually needs: a plaintext lane gets only the protocol, and a SASL
    lane gets all four. Both directions matter -- binding SASL names on a
    listener that offers none is the mirror image of leaving them off one that
    requires them, and the first of those is what took the CI publishers down
    on 2026-09-07.

    ``credential_source`` is a plain mapping rather than ``os.environ`` so the
    caller decides where the value comes from and this function stays
    testable without a real credential anywhere near it.

    Raises :class:`HookEdgeLaneCredentialError`, naming the variables and the
    file but never a value, when a SASL lane's credential is absent or only
    half present.
    """
    endpoint = contract.known_lanes[contract.lane]
    resolved = {ENV_SECURITY_PROTOCOL: endpoint.security_protocol}
    if endpoint.security_protocol not in SASL_PROTOCOLS:
        return resolved

    # Guaranteed non-None by _parse_transport; asserted so a future edit that
    # loosens the loader fails here rather than emitting a half-built client.
    assert endpoint.sasl_mechanism is not None

    # The client always reads the bare names. A prefix, where one is declared,
    # governs only how the OPERATOR ENV FILE spells them on this host; the
    # client store is keyed by lane and declares no prefix, so its mapping
    # already arrives under the bare names.
    prefix = endpoint.sasl_env_prefix or ""
    user_name = f"{prefix}{ENV_SASL_USERNAME}"
    password_name = f"{prefix}{ENV_SASL_PASSWORD}"
    where = credential_source_name or str(operator_env_file_path())

    missing = [n for n in (user_name, password_name) if not credential_source.get(n)]
    if missing:
        if endpoint.sasl_credential_source == CREDENTIAL_SOURCE_ONEX_LANE_STORE:
            remedy = (
                f"This machine's identity for the lane is placed with "
                f"{_lane_login_remediation(contract.lane)}; the VALUE is never "
                "written into this contract, and this resolver reads the "
                "declared surface only -- it will not fall back to another "
                "file and authenticate as somebody else."
            )
        else:
            remedy = (
                "This is the value the dev lane's compose services resolve "
                "from the same file on the lab host (OMN-18012); it is not "
                "minted here."
            )
        raise HookEdgeLaneCredentialError(
            f"lane {contract.lane!r} declares {endpoint.security_protocol} with "
            f"{endpoint.sasl_mechanism}, so it cannot publish without a "
            f"credential, and {' and '.join(missing)} "
            f"{'is' if len(missing) == 1 else 'are'} not set in {where}. "
            f"Both {user_name} and {password_name} are required together. "
            f"{remedy}"
        )

    resolved[ENV_SASL_MECHANISM] = endpoint.sasl_mechanism
    resolved[ENV_SASL_USERNAME] = credential_source[user_name]
    resolved[ENV_SASL_PASSWORD] = credential_source[password_name]
    return resolved


def load_contract(path: Path) -> HookEdgeLaneContract:
    """Parse and structurally validate the hook-edge lane declaration."""
    import yaml

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise HookEdgeLaneError(f"no hook-edge lane contract at {path}") from exc
    if not isinstance(raw, dict):
        raise HookEdgeLaneError(f"{path}: contract must be a mapping")

    where = str(path)
    lanes_raw = _require(raw, "known_lanes", where)
    if not isinstance(lanes_raw, dict) or not lanes_raw:
        raise HookEdgeLaneError(f"{where}: known_lanes must be a non-empty mapping")

    known: dict[str, LaneEndpoint] = {}
    for name, entry in lanes_raw.items():
        if not isinstance(entry, dict):
            raise HookEdgeLaneError(f"{where}: known_lanes.{name} must be a mapping")
        scope = f"{where}: known_lanes.{name}"
        protocol, mechanism, prefix, source = _parse_transport(entry, scope)
        known[str(name)] = LaneEndpoint(
            name=str(name),
            compose_project=str(_require(entry, "compose_project", scope)),
            network=str(_require(entry, "network", scope)),
            bootstrap_servers=str(_require(entry, "bootstrap_servers", scope)),
            security_protocol=protocol,
            sasl_mechanism=mechanism,
            sasl_env_prefix=prefix,
            sasl_credential_source=source,
        )

    lane = str(_require(raw, "lane", where))
    if lane not in known:
        raise HookEdgeLaneError(
            f"{where}: declared lane {lane!r} is not in known_lanes ({sorted(known)})"
        )

    relay = _require(raw, "relay", where)
    if not isinstance(relay, dict):
        raise HookEdgeLaneError(f"{where}: relay must be a mapping")

    governed = _require(raw, "governed_topics", where)
    if not isinstance(governed, list) or not governed:
        raise HookEdgeLaneError(
            f"{where}: governed_topics must be a non-empty list of canonical "
            "topic-registry constant names"
        )

    demoted = _require(raw, "non_authoritative_surfaces", where)
    if not isinstance(demoted, list) or not demoted:
        raise HookEdgeLaneError(
            f"{where}: non_authoritative_surfaces must list the surfaces this "
            "contract demotes — an empty list would mean nothing was actually "
            "taken out of the resolution path"
        )

    return HookEdgeLaneContract(
        path=path,
        lane=lane,
        known_lanes=known,
        relay_container=str(_require(relay, "container", f"{where}: relay")),
        relay_required_network=str(
            _require(relay, "required_network", f"{where}: relay")
        ),
        topic_registry=str(_require(raw, "topic_registry", where)),
        governed_topics=tuple(str(name) for name in governed),
        non_authoritative_surfaces=tuple(str(s) for s in demoted),
    )


def resolve_bootstrap_servers(contract: HookEdgeLaneContract) -> str:
    """The publisher's broker, from the contract and nothing else.

    Note what this function does NOT do: consult the environment. That is the
    whole point — an env var that disagrees is a finding (see
    :func:`audit_surfaces`), never an input.
    """
    return contract.bootstrap_servers


def audit_surfaces(
    contract: HookEdgeLaneContract,
    *,
    surfaces: dict[str, str | None],
) -> tuple[SurfaceFinding, ...]:
    """Report which demoted surfaces disagree with the contract (AC3).

    ``surfaces`` maps a surface label (``~/.omnibase/.env``,
    ``~/.claude/settings.json``, ...) to the broker value it currently sets, or
    ``None`` when it sets none. A surface that sets nothing is not a
    disagreement — silence is compatible with any lane.
    """
    expected = contract.bootstrap_servers
    return tuple(
        SurfaceFinding(
            surface=label,
            observed=observed,
            expected=expected,
            agrees=observed is None or observed == expected,
        )
        for label, observed in sorted(surfaces.items())
    )


def resolve_governed_topics(
    contract: HookEdgeLaneContract, *, repo_root: Path
) -> dict[str, str]:
    """Resolve the contract's governed-topic constants to topic strings.

    The topic string has exactly one home — ``src/omniclaude/hooks/topic_registry.yaml``,
    the file ``TopicBase`` and ``emit_client_wrapper`` already read. This
    contract names registry *constants* so it can never become a second place a
    topic is spelled, and so a rename in the registry surfaces here as a
    resolution failure instead of a stale literal that quietly governs nothing.

    Raises on an unknown constant: a lane policy that silently governs an empty
    topic set is the same class of un-noticed nothing this ticket exists to
    retire.
    """
    import yaml

    registry_path = repo_root / contract.topic_registry
    try:
        raw = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise HookEdgeLaneError(
            f"{contract.path}: topic_registry {registry_path} does not exist"
        ) from exc
    entries = (raw or {}).get("topics")
    if not isinstance(entries, list):
        raise HookEdgeLaneError(f"{registry_path}: no 'topics' list")

    by_constant: dict[str, str] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        constant = entry.get("topic_base_constant")
        topic = entry.get("topic")
        if isinstance(constant, str) and isinstance(topic, str):
            by_constant[constant] = topic

    resolved: dict[str, str] = {}
    for name in contract.governed_topics:
        if name not in by_constant:
            raise HookEdgeLaneError(
                f"{contract.path}: governed topic constant {name!r} is not in "
                f"{registry_path} — the lane policy would govern a topic that "
                "does not exist"
            )
        resolved[name] = by_constant[name]
    return resolved


def resolve_governed_event_types(
    contract: HookEdgeLaneContract, *, repo_root: Path
) -> dict[str, str]:
    """Resolve governed constants to semantic event types from the registry."""
    import yaml

    registry_path = repo_root / contract.topic_registry
    try:
        raw = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise HookEdgeLaneError(
            f"{contract.path}: topic_registry {registry_path} does not exist"
        ) from exc
    entries = (raw or {}).get("topics")
    if not isinstance(entries, list):
        raise HookEdgeLaneError(f"{registry_path}: no 'topics' list")

    by_constant: dict[str, str] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        constant = entry.get("topic_base_constant")
        event_type = entry.get("event_type")
        if isinstance(constant, str) and isinstance(event_type, str):
            by_constant[constant] = event_type

    resolved: dict[str, str] = {}
    for name in contract.governed_topics:
        if name not in by_constant:
            raise HookEdgeLaneError(
                f"{contract.path}: governed topic constant {name!r} is not in "
                f"{registry_path} — the lane policy would govern a topic that "
                "does not exist"
            )
        resolved[name] = by_constant[name]
    return resolved
