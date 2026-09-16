# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""The hook edge declares WHERE its credential is resolved from (OMN-18120 AC2).

WHAT WAS MISSING
----------------
OMN-17284 made the hook edge declare its TRANSPORT beside its broker, and
pointed the dev lane's credential at ``sasl_env_prefix: "DEV_"`` -- the
operator env file (``OMNIBASE_OPERATOR_ENV_FILE``, default
``${HOME}/.omnibase/.env``), because that is the surface ``deploy-runtime.sh``
resolves the lane principal from on the lab host.

That is the right surface on the lab host and the wrong one on the operator
Mac. This machine carries its dev-lane bus identity in the per-lane client
store under ``~/.onex`` -- ``config.yaml``'s ``lanes.<lane>`` block holding a
principal NAME and a REFERENCE, and ``credentials.json`` (mode 0600) holding
the value the reference points at. That is the store ``onex auth lane-login``
writes and ``onex delegate --lane <lane>`` reads, and it is deliberately not
the operator env file: a world-readable ``.env`` is exactly what the store
exists to stop a bus identity from living in.

So the drainer asked a file that does not hold the answer, got nothing, and
refused -- correctly and loudly, naming two variable names that were never
going to be set on this machine.

THE RULE THIS PINS -- THE CREDENTIAL SOURCE IS DECLARED, NEVER SEARCHED
-----------------------------------------------------------------------
The fix is NOT "try the store, then fall back to the env file". Resolution by
search order is the precise defect ``hook_edge_lane.yaml`` was created to
retire: before OMN-17204 the lane itself was decided by whichever of three
files ``set -a`` happened to source last. Re-introducing that shape one layer
down, for the credential instead of the broker, would trade a named refusal
for a silent wrong answer -- a machine holding two identities would
authenticate as whichever file was luckier.

So a SASL lane declares ``sasl_credential_source``, the loader refuses a lane
that declares none, and the resolver reads that one surface and no other. The
canonical store states the same line in its own words: a machine whose stored
identity is unreadable "must not silently authenticate as somebody else"
(``omnibase_infra`` ``cli/delegate_lane_credentials.py``).

Every credential in this module's fixtures is synthetic.
"""

from __future__ import annotations

import importlib.util
import json
import stat
import sys
from pathlib import Path
from types import ModuleType

import pytest

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).resolve().parents[2]
_HOOKS_DIR = _REPO_ROOT / "plugins" / "onex" / "hooks"
_LIB_DIR = _HOOKS_DIR / "lib"
_CONTRACT_PATH = _HOOKS_DIR / "contracts" / "hook_edge_lane.yaml"

# Synthetic throughout. Nothing here is a real principal.
_FAKE_USER = "synthetic-lane-principal"
_FAKE_PASS = "synthetic-not-a-real-secret"
_FAKE_REF = "dev-lane-sasl"


def _load_lib() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "hook_edge_lane", _LIB_DIR / "hook_edge_lane.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["hook_edge_lane"] = module
    spec.loader.exec_module(module)
    return module


def _write_contract(tmp_path: Path, lanes: str, lane: str = "dev") -> Path:
    path = tmp_path / "hook_edge_lane.yaml"
    path.write_text(
        "schema_version: '1.0.0'\n"
        "name: hook_edge_lane\n"
        f"lane: '{lane}'\n"
        "lane_host: 'test-broker.invalid'\n"
        f"known_lanes:\n{lanes}"
        "relay:\n"
        "  container: 'omninode-gateway-forwarder'\n"
        "  required_network: 'omnibase-infra-network'\n"
        "topic_registry: 'src/omniclaude/hooks/topic_registry.yaml'\n"
        "governed_topics:\n  - 'TOOL_EXECUTED'\n"
        "non_authoritative_surfaces:\n  - '~/.omnibase/.env'\n",
        encoding="utf-8",
    )
    return path


def _lane_block(
    name: str,
    *,
    protocol: str,
    mechanism: str | None = None,
    prefix: str | None = None,
    source: str | None = None,
    network: str = "omnibase-infra-network",
) -> str:
    block = (
        f"  {name}:\n"
        f"    compose_project: 'omnibase-infra'\n"
        f"    network: '{network}'\n"
        f"    bootstrap_servers: 'test-broker.invalid:19092'\n"
        f"    security_protocol: '{protocol}'\n"
    )
    if mechanism is not None:
        block += f"    sasl_mechanism: '{mechanism}'\n"
    if prefix is not None:
        block += f"    sasl_env_prefix: '{prefix}'\n"
    if source is not None:
        block += f"    sasl_credential_source: '{source}'\n"
    return block


def _write_store(
    onex_home: Path,
    *,
    lane: str = "dev",
    username: str | None = _FAKE_USER,
    password_ref: str | None = _FAKE_REF,
    secret: str | None = _FAKE_PASS,
    mode: int = 0o600,
    other_lanes: dict[str, str] | None = None,
) -> Path:
    """Write a synthetic ``~/.onex`` pair in the shape the canonical store writes."""
    onex_home.mkdir(parents=True, exist_ok=True)

    entry: dict[str, str] = {}
    if username is not None:
        entry["sasl_username"] = username
    if password_ref is not None:
        entry["sasl_password_ref"] = password_ref

    lines = ["gateway:", "  tenant_slug: 'synthetic-tenant'", "lanes:"]
    lines.append(f"  {lane}:")
    for key, value in entry.items():
        lines.append(f"    {key}: '{value}'")
    for other_name, other_user in (other_lanes or {}).items():
        lines.append(f"  {other_name}:")
        lines.append(f"    sasl_username: '{other_user}'")
        lines.append(f"    sasl_password_ref: '{other_name}-lane-sasl'")
    (onex_home / "config.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")

    secrets: dict[str, str] = {}
    if password_ref is not None and secret is not None:
        secrets[password_ref] = secret
    credentials = onex_home / "credentials.json"
    credentials.write_text(json.dumps(secrets), encoding="utf-8")
    credentials.chmod(mode)
    return onex_home


# =============================================================================
# The shipped contract declares the source the operator Mac actually holds
# =============================================================================


def test_dev_lane_declares_the_onex_lane_store_as_its_credential_source() -> None:
    """The dev lane resolves the identity ``onex delegate --lane dev`` resolves.

    Two clients on one machine dialling one lane must present one identity.
    Before this, the delegate CLI read ``~/.onex`` and the hook drainer read
    ``~/.omnibase/.env``, so the machine's answer to "who am I on the dev bus"
    depended on which process was asking.
    """
    lib = _load_lib()
    dev = lib.load_contract(_CONTRACT_PATH).known_lanes["dev"]

    assert dev.security_protocol == "SASL_PLAINTEXT"
    assert dev.sasl_credential_source == lib.CREDENTIAL_SOURCE_ONEX_LANE_STORE
    assert dev.sasl_env_prefix is None, (
        "a lane that names the client store must not also name an env prefix; "
        "two declared sources is not a declaration"
    )


def test_every_sasl_lane_in_the_shipped_contract_declares_a_source() -> None:
    """No SASL lane may leave its credential surface to inference."""
    lib = _load_lib()
    lanes = lib.load_contract(_CONTRACT_PATH).known_lanes
    sasl = {n: e for n, e in lanes.items() if e.security_protocol in lib.SASL_PROTOCOLS}

    assert sasl, "positive control: the shipped contract declares a SASL lane"
    for name, endpoint in sasl.items():
        assert endpoint.sasl_credential_source in lib.VALID_CREDENTIAL_SOURCES, (
            f"known_lanes.{name} declares {endpoint.security_protocol} and no "
            "sasl_credential_source; the producer would have to search for its "
            "own identity, which is the OMN-17204 defect one layer down"
        )


def test_a_plaintext_lane_declares_no_credential_source() -> None:
    """Negative control on the same shipped file.

    Without a non-SASL lane here the refusal cases below would only prove the
    loader rejects shapes this file never contains.
    """
    lib = _load_lib()
    lanes = lib.load_contract(_CONTRACT_PATH).known_lanes
    plaintext = {n: e for n, e in lanes.items() if e.security_protocol == "PLAINTEXT"}

    assert plaintext, "positive control: stability-test takes an unauthenticated client"
    for name, endpoint in plaintext.items():
        assert endpoint.sasl_credential_source is None, (
            f"known_lanes.{name} names a credential source beside PLAINTEXT"
        )


# =============================================================================
# The loader refuses every incomplete or self-contradicting declaration
# =============================================================================


def test_a_sasl_lane_with_no_declared_source_is_refused(tmp_path: Path) -> None:
    lib = _load_lib()
    path = _write_contract(
        tmp_path,
        _lane_block("dev", protocol="SASL_PLAINTEXT", mechanism="SCRAM-SHA-256"),
    )
    with pytest.raises(lib.HookEdgeLaneError) as excinfo:
        lib.load_contract(path)
    assert "sasl_credential_source" in str(excinfo.value)


def test_a_non_sasl_lane_that_names_a_source_is_refused(tmp_path: Path) -> None:
    lib = _load_lib()
    path = _write_contract(
        tmp_path,
        _lane_block(
            "dev",
            protocol="PLAINTEXT",
            source="onex_lane_store",
        ),
    )
    with pytest.raises(lib.HookEdgeLaneError) as excinfo:
        lib.load_contract(path)
    message = str(excinfo.value)
    assert "sasl_credential_source" in message
    assert "PLAINTEXT" in message


def test_a_lane_naming_two_sources_is_refused(tmp_path: Path) -> None:
    """The store source plus an env prefix is two answers, so it is no answer."""
    lib = _load_lib()
    path = _write_contract(
        tmp_path,
        _lane_block(
            "dev",
            protocol="SASL_PLAINTEXT",
            mechanism="SCRAM-SHA-256",
            prefix="DEV_",
            source="onex_lane_store",
        ),
    )
    with pytest.raises(lib.HookEdgeLaneError) as excinfo:
        lib.load_contract(path)
    assert "sasl_env_prefix" in str(excinfo.value)


def test_the_env_file_source_still_requires_its_prefix(tmp_path: Path) -> None:
    """The legacy surface keeps the rule OMN-17284 gave it."""
    lib = _load_lib()
    path = _write_contract(
        tmp_path,
        _lane_block(
            "dev",
            protocol="SASL_PLAINTEXT",
            mechanism="SCRAM-SHA-256",
            source="operator_env_file",
        ),
    )
    with pytest.raises(lib.HookEdgeLaneError) as excinfo:
        lib.load_contract(path)
    assert "sasl_env_prefix" in str(excinfo.value)


def test_an_unknown_source_is_refused(tmp_path: Path) -> None:
    lib = _load_lib()
    path = _write_contract(
        tmp_path,
        _lane_block(
            "dev",
            protocol="SASL_PLAINTEXT",
            mechanism="SCRAM-SHA-256",
            source="whatever_is_lying_around",
        ),
    )
    with pytest.raises(lib.HookEdgeLaneError) as excinfo:
        lib.load_contract(path)
    assert "whatever_is_lying_around" in str(excinfo.value)


# =============================================================================
# Reading the store
# =============================================================================


def test_the_store_resolves_the_lane_identity(tmp_path: Path) -> None:
    lib = _load_lib()
    onex_home = _write_store(tmp_path / ".onex")

    resolved = lib.read_lane_client_store("dev", onex_home=onex_home)

    assert resolved[lib.ENV_SASL_USERNAME] == _FAKE_USER
    assert resolved[lib.ENV_SASL_PASSWORD] == _FAKE_PASS


def test_the_store_reads_only_the_requested_lane(tmp_path: Path) -> None:
    """A machine holding several lane identities must not blend them."""
    lib = _load_lib()
    onex_home = _write_store(
        tmp_path / ".onex", other_lanes={"stability-test": "some-other-principal"}
    )

    resolved = lib.read_lane_client_store("dev", onex_home=onex_home)

    assert resolved[lib.ENV_SASL_USERNAME] == _FAKE_USER


def test_the_store_refuses_a_group_or_world_readable_secret_file(
    tmp_path: Path,
) -> None:
    """Enforced on READ, not only on write.

    The file survives ``chmod``, backup/restore and ``scp``, so a write-time
    check proves nothing about the file actually being loaded. The canonical
    store enforces the same mode on read for the same reason.
    """
    lib = _load_lib()
    onex_home = _write_store(tmp_path / ".onex", mode=0o644)

    with pytest.raises(lib.HookEdgeLaneCredentialError) as excinfo:
        lib.read_lane_client_store("dev", onex_home=onex_home)

    message = str(excinfo.value)
    assert "credentials.json" in message
    assert _FAKE_PASS not in message


def test_the_store_refuses_a_reference_with_no_value(tmp_path: Path) -> None:
    """A config naming a missing secret is the half-written state, and it fails."""
    lib = _load_lib()
    onex_home = _write_store(tmp_path / ".onex", secret=None)

    with pytest.raises(lib.HookEdgeLaneCredentialError) as excinfo:
        lib.read_lane_client_store("dev", onex_home=onex_home)
    assert _FAKE_REF in str(excinfo.value)


def test_the_store_refuses_an_inline_password(tmp_path: Path) -> None:
    """``config.yaml`` is the file operators paste into issues. No values in it."""
    lib = _load_lib()
    onex_home = tmp_path / ".onex"
    _write_store(onex_home)
    (onex_home / "config.yaml").write_text(
        "lanes:\n"
        "  dev:\n"
        f"    sasl_username: '{_FAKE_USER}'\n"
        f"    sasl_password: '{_FAKE_PASS}'\n",
        encoding="utf-8",
    )

    with pytest.raises(lib.HookEdgeLaneCredentialError) as excinfo:
        lib.read_lane_client_store("dev", onex_home=onex_home)

    message = str(excinfo.value)
    assert "sasl_password" in message
    assert _FAKE_PASS not in message


def test_a_machine_holding_no_entry_for_the_lane_yields_nothing(
    tmp_path: Path,
) -> None:
    """Absence is not corruption: the refusal belongs to the resolver.

    ``resolve_transport_env`` is the layer that can name the lane, the file
    and the remediation; a reader that raised here would produce a traceback
    naming only a path.
    """
    lib = _load_lib()
    onex_home = _write_store(tmp_path / ".onex", lane="stability-test")

    assert lib.read_lane_client_store("dev", onex_home=onex_home) == {}


def test_a_malformed_store_is_refused_rather_than_read_as_absent(
    tmp_path: Path,
) -> None:
    """ABSENT and MALFORMED are different answers.

    A machine holding no store yields ``{}`` and the caller turns that into a
    refusal naming ``onex auth lane-login``. A machine whose store is present
    but unparseable holds an identity the reader FAILED TO READ, and reporting
    that as "no identity" sends the operator to re-place a credential that is
    already there. The paired control is the test directly below: the same
    reader, an absent file, returns ``{}`` rather than raising.
    """
    lib = _load_lib()
    onex_home = _write_store(tmp_path / ".onex")
    (onex_home / "config.yaml").write_text(
        "lanes:\n  dev:\n    sasl_username: 'x'\n   bad_indent: [unclosed\n",
        encoding="utf-8",
    )

    with pytest.raises(lib.HookEdgeLaneCredentialError) as excinfo:
        lib.read_lane_client_store("dev", onex_home=onex_home)

    message = str(excinfo.value)
    assert "config.yaml" in message
    assert "does not parse as YAML" in message


def test_a_store_that_is_not_a_mapping_is_refused(tmp_path: Path) -> None:
    lib = _load_lib()
    onex_home = _write_store(tmp_path / ".onex")
    (onex_home / "config.yaml").write_text("- just\n- a\n- list\n", encoding="utf-8")

    with pytest.raises(lib.HookEdgeLaneCredentialError):
        lib.read_lane_client_store("dev", onex_home=onex_home)


def test_an_absent_store_yields_nothing(tmp_path: Path) -> None:
    lib = _load_lib()
    assert lib.read_lane_client_store("dev", onex_home=tmp_path / "nope") == {}


# =============================================================================
# Resolution is by declaration, never by search
# =============================================================================


def test_the_store_lane_resolves_its_four_transport_names(tmp_path: Path) -> None:
    lib = _load_lib()
    path = _write_contract(
        tmp_path,
        _lane_block(
            "dev",
            protocol="SASL_PLAINTEXT",
            mechanism="SCRAM-SHA-256",
            source="onex_lane_store",
        ),
    )
    contract = lib.load_contract(path)
    onex_home = _write_store(tmp_path / ".onex")

    resolved = lib.resolve_transport_env(
        contract,
        credential_source=lib.read_lane_client_store("dev", onex_home=onex_home),
        credential_source_name=str(onex_home),
    )

    assert resolved[lib.ENV_SECURITY_PROTOCOL] == "SASL_PLAINTEXT"
    assert resolved[lib.ENV_SASL_MECHANISM] == "SCRAM-SHA-256"
    assert resolved[lib.ENV_SASL_USERNAME] == _FAKE_USER
    assert resolved[lib.ENV_SASL_PASSWORD] == _FAKE_PASS


def test_a_store_lane_does_not_fall_back_to_the_operator_env_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The load-bearing test.

    A machine that holds the env-file names AND declares the store source must
    refuse, not quietly authenticate as the env file's principal. Falling back
    would restore resolution-by-search-order for the credential -- the shape
    OMN-17204 retired for the broker.
    """
    lib = _load_lib()
    env_file = tmp_path / "operator.env"
    env_file.write_text(
        f"DEV_KAFKA_SASL_USERNAME={_FAKE_USER}-from-the-env-file\n"
        f"DEV_KAFKA_SASL_PASSWORD={_FAKE_PASS}-from-the-env-file\n",
        encoding="utf-8",
    )
    monkeypatch.setenv(lib.ENV_OPERATOR_ENV_FILE, str(env_file))

    path = _write_contract(
        tmp_path,
        _lane_block(
            "dev",
            protocol="SASL_PLAINTEXT",
            mechanism="SCRAM-SHA-256",
            source="onex_lane_store",
        ),
    )
    contract = lib.load_contract(path)
    empty_store = tmp_path / "empty-onex"

    with pytest.raises(lib.HookEdgeLaneCredentialError) as excinfo:
        lib.resolve_credential_environment(contract, onex_home=empty_store)

    message = str(excinfo.value)
    assert "onex auth lane-login" in message, (
        "the refusal must name the command that fixes it on this machine"
    )
    assert "-from-the-env-file" not in message


def test_the_env_file_lane_still_resolves(tmp_path: Path) -> None:
    """Positive control: declaring the legacy source keeps the legacy behaviour.

    The lab host resolves its lane principal from the operator env file and
    must keep doing so; this change adds a second declarable source, it does
    not replace the first.
    """
    lib = _load_lib()
    path = _write_contract(
        tmp_path,
        _lane_block(
            "dev",
            protocol="SASL_PLAINTEXT",
            mechanism="SCRAM-SHA-256",
            prefix="DEV_",
            source="operator_env_file",
        ),
    )
    contract = lib.load_contract(path)

    resolved = lib.resolve_transport_env(
        contract,
        credential_source={
            f"DEV_{lib.ENV_SASL_USERNAME}": _FAKE_USER,
            f"DEV_{lib.ENV_SASL_PASSWORD}": _FAKE_PASS,
        },
    )

    assert resolved[lib.ENV_SASL_USERNAME] == _FAKE_USER
    assert resolved[lib.ENV_SASL_PASSWORD] == _FAKE_PASS


def test_resolve_credential_environment_reads_the_declared_store(
    tmp_path: Path,
) -> None:
    """End to end through the one entry point the drainer calls."""
    lib = _load_lib()
    path = _write_contract(
        tmp_path,
        _lane_block(
            "dev",
            protocol="SASL_PLAINTEXT",
            mechanism="SCRAM-SHA-256",
            source="onex_lane_store",
        ),
    )
    contract = lib.load_contract(path)
    onex_home = _write_store(tmp_path / ".onex")

    resolved = lib.resolve_credential_environment(contract, onex_home=onex_home)

    assert resolved[lib.ENV_SASL_USERNAME] == _FAKE_USER
    assert resolved[lib.ENV_SASL_PASSWORD] == _FAKE_PASS


def test_a_plaintext_lane_needs_no_store_at_all(tmp_path: Path) -> None:
    """Binding SASL names on a listener that offers none is the mirror defect."""
    lib = _load_lib()
    path = _write_contract(
        tmp_path,
        _lane_block("stability-test", protocol="PLAINTEXT"),
        lane="stability-test",
    )
    contract = lib.load_contract(path)

    resolved = lib.resolve_credential_environment(
        contract, onex_home=tmp_path / "does-not-exist"
    )

    assert resolved == {lib.ENV_SECURITY_PROTOCOL: "PLAINTEXT"}


# =============================================================================
# The refusal is legible and carries no value
# =============================================================================


def test_the_store_refusal_names_the_lane_the_file_and_the_remedy(
    tmp_path: Path,
) -> None:
    lib = _load_lib()
    path = _write_contract(
        tmp_path,
        _lane_block(
            "dev",
            protocol="SASL_PLAINTEXT",
            mechanism="SCRAM-SHA-256",
            source="onex_lane_store",
        ),
    )
    contract = lib.load_contract(path)

    with pytest.raises(lib.HookEdgeLaneCredentialError) as excinfo:
        lib.resolve_credential_environment(contract, onex_home=tmp_path / "absent")

    message = str(excinfo.value)
    assert "dev" in message
    assert "config.yaml" in message
    assert "onex auth lane-login --lane dev" in message


def test_the_shipped_contract_carries_no_credential_value() -> None:
    """CONFIG here, SECRET elsewhere -- re-asserted on the edited file."""
    text = _CONTRACT_PATH.read_text(encoding="utf-8")
    for forbidden in ("sasl_password:", "sasl_plain_password", "SASL_PASSWORD="):
        assert forbidden not in text, (
            f"the lane contract must never carry a credential value ({forbidden})"
        )


def test_the_store_files_are_referenced_by_name_not_hardcoded_home() -> None:
    """``onex_home_path`` is the one place ``~/.onex`` is spelled.

    Takes no ``tmp_path``: it writes no store and reads no file. The parameter
    was unused, and an unused one here invites a reader to attribute a
    neighbouring test's deliberate bad-mode fixture to this one.

    The canonical store takes ``onex_home`` by injection for the same reason:
    a class that derived it from ``Path.home()`` internally cannot be driven
    by a test against a real directory.
    """
    lib = _load_lib()
    assert lib.onex_home_path().name == ".onex"
    assert lib.onex_home_path().is_absolute()


def test_the_secret_file_mode_check_uses_the_same_mask_as_the_canonical_store(
    tmp_path: Path,
) -> None:
    """0600 exactly -- any group or other bit is a refusal, not a warning.

    NEGATIVE CASE. The group-readable file below is this test's INPUT, not an
    artifact this code ever writes: the assertion being made is that
    ``read_lane_client_store`` REFUSES it. A fixture the production path
    rejects is the only way to prove the production path rejects it.

    ``0o640`` is chosen over ``0o644`` deliberately -- it sets a group bit and
    no other bit, so it also pins the MASK. A check written as ``mode != 0o600``
    or as ``mode & 0o007`` would pass a group-readable credential; ``0o077``
    is the mask the canonical ``StoreLaneCredential`` uses, and this is what
    holds the two readers to the same one.
    """
    lib = _load_lib()
    onex_home = _write_store(tmp_path / ".onex", mode=0o640)
    credentials = onex_home / "credentials.json"
    assert stat.S_IMODE(credentials.stat().st_mode) & 0o077, (
        "positive control: the fixture really is group readable, so the "
        "refusal below is about the mode and not about some other defect"
    )

    with pytest.raises(lib.HookEdgeLaneCredentialError):
        lib.read_lane_client_store("dev", onex_home=onex_home)
