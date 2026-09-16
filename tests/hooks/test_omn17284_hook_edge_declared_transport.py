# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""The hook edge declares its broker TRANSPORT, not just its broker (OMN-17284).

WHAT WAS MISSING
----------------
``hook_edge_lane.yaml`` settled WHICH broker the local hook producer dials and
left HOW it authenticates undeclared. That was survivable only while every
lane in ``known_lanes`` spoke plaintext. On 2026-09-07 it stopped being
survivable: ``omnibase_infra#3276`` (squash ``d7c5585314a751689e705e09e32c9e4565671ef2``,
OMN-18012 phase B) flipped the lab dev-lane Redpanda EXTERNAL listener to
SASL/SCRAM-SHA-256 over plaintext and bound the credential on all fifteen
dev-lane compose services. The local hook producer is a sixteenth client, it
lives outside that compose project, and nothing brought it along.

The visible symptom is not an auth error. It is
``KafkaConnectionError: Unable to bootstrap from [(<the dev lane's host and
external port>, ...)]`` on a 30s loop, because a Redpanda that requires SASL closes the connection
rather than answering -- indistinguishable, in a log, from a broker that is
down. The same shape already cost this fleet twice: the gateway forwarder's
dev legs went dark from 2026-09-06 while still logging "delivered" (repaired
2026-09-10, recorded in the contract's own header), and the deploy agent
restarted 53 times by 2026-09-08T04:12Z.

THE RULE THIS PINS -- TRANSPORT IS DECLARED, NEVER INFERRED
-----------------------------------------------------------
Copied deliberately, vocabulary and all, from the two surfaces that already
settled it after the 2026-09-07 outage:

* ``omnimarket/config/ci_bus_lanes.yaml`` -- the CI publishers' lane map.
* ``omnibase_infra/scripts/deploy-agent/deploy_agent/kafka_config.py`` -- the
  deploy agent, which is the closest precedent to this producer: a host-level,
  non-compose Kafka client on a machine with an operator env file.

Both record the same lesson in the same words: *credential PRESENCE is not a
statement about transport; the lane is*. The old deploy-agent loader picked
``SASL_SSL`` whenever credentials happened to be in the environment, met a
listener with no TLS, and died on an SSL handshake. So ``security_protocol``
is REQUIRED on every lane and ``sasl_mechanism`` is required beside a SASL
protocol and REJECTED beside a non-SASL one. A contradiction fails the load
rather than reaching a client.

CONFIG HERE, SECRET ELSEWHERE
-----------------------------
``ci_bus_lanes.yaml`` states the split outright: "SASL credentials are NEVER
stored here". This contract holds the same line. What it declares is
``sasl_env_prefix`` -- a REFERENCE naming where the value lives, resolved at
run time -- exactly as the deploy agent's systemd unit declares a prefix
instead of copying a secret into a unit file. The value itself stays in the
operator env file (``OMNIBASE_OPERATOR_ENV_FILE``, default
``${HOME}/.omnibase/.env``), which is the surface ``deploy-runtime.sh`` already
resolves ``DEV_KAFKA_SASL_USERNAME`` / ``DEV_KAFKA_SASL_PASSWORD`` from on the
lab host.

Every credential in this module's fixtures is synthetic.
"""

from __future__ import annotations

import importlib.util
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
    """A minimal but structurally complete contract, for loader-refusal cases."""
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


# =============================================================================
# The shipped contract declares a transport for every lane it knows
# =============================================================================


def test_every_known_lane_declares_a_security_protocol() -> None:
    """No lane may leave transport to inference.

    A lane with no declared protocol is the pre-OMN-18012 deploy agent: it
    guesses from credential presence and is wrong the moment a listener moves.
    """
    lib = _load_lib()
    contract = lib.load_contract(_CONTRACT_PATH)

    assert contract.known_lanes, "positive control: the contract knows some lanes"
    for name, endpoint in contract.known_lanes.items():
        assert endpoint.security_protocol, (
            f"known_lanes.{name} declares no security_protocol; the producer "
            "would have to infer its transport, which is the exact shape that "
            "took the dev lane down on 2026-09-07 (OMN-18012)"
        )


def test_dev_lane_declares_the_transport_omn18012_actually_enabled() -> None:
    """SASL over PLAINTEXT with SCRAM-SHA-256 -- measured, not assumed.

    ``omnibase_infra/docker/docker-compose.dev-lane.yml`` binds exactly this
    pair on all fifteen dev-lane clients (``x-dev-lane-broker-auth-env``), and
    the listener on :19092 carries no TLS. Declaring ``SASL_SSL`` here would
    reproduce the CI publishers' 2026-09-07 failure verbatim.
    """
    lib = _load_lib()
    dev = lib.load_contract(_CONTRACT_PATH).known_lanes["dev"]

    assert dev.security_protocol == "SASL_PLAINTEXT"
    assert dev.sasl_mechanism == "SCRAM-SHA-256"
    assert dev.sasl_credential_source == "onex_lane_store", (
        "CORRECTED by OMN-18120: this assertion read sasl_env_prefix == 'DEV_' "
        "until the dev lane moved its declared credential surface to the "
        "~/.onex per-lane client store. The operator env file is the LAB "
        "HOST's surface; an operator workstation holds its bus identity in "
        "the store, which is also what `onex delegate --lane dev` reads. What "
        "the assertion pins is unchanged: the contract names a REFERENCE, so "
        "the value never has to be written down here"
    )
    assert dev.sasl_env_prefix is None


def test_a_plaintext_lane_declares_no_mechanism_and_no_prefix() -> None:
    """Negative control on the same shipped file.

    If every lane in the contract were SASL, the refusal tests below would
    prove nothing about this file -- they would only prove the loader refuses
    shapes the file never contains.
    """
    lib = _load_lib()
    lanes = lib.load_contract(_CONTRACT_PATH).known_lanes
    plaintext = {n: e for n, e in lanes.items() if e.security_protocol == "PLAINTEXT"}

    assert plaintext, (
        "expected at least one non-SASL lane in the shipped contract as a "
        "control; stability-test's :39092 listener takes an unauthenticated "
        "client today"
    )
    for name, endpoint in plaintext.items():
        assert endpoint.sasl_mechanism is None, (
            f"known_lanes.{name} names a SASL mechanism beside PLAINTEXT"
        )
        assert endpoint.sasl_env_prefix is None


def test_the_contract_declares_a_reference_and_never_a_credential() -> None:
    """CONFIG here, SECRET elsewhere -- the ci_bus_lanes.yaml line, enforced.

    A prefix is a pointer. A username or password key would make this
    checked-in, world-readable file a credential store.
    """
    text = _CONTRACT_PATH.read_text(encoding="utf-8").lower()
    for forbidden in ("sasl_username:", "sasl_password:", "kafka_sasl_password:"):
        assert forbidden not in text, (
            f"{_CONTRACT_PATH} spells {forbidden!r}; SASL credential VALUES are "
            "never stored in a checked-in lane declaration -- declare "
            "sasl_env_prefix and resolve the value at run time"
        )


# =============================================================================
# The loader refuses a contradictory transport rather than passing it to a client
# =============================================================================


def test_loader_rejects_a_mechanism_beside_a_non_sasl_protocol(tmp_path: Path) -> None:
    lib = _load_lib()
    path = _write_contract(
        tmp_path,
        _lane_block("dev", protocol="PLAINTEXT", mechanism="SCRAM-SHA-256"),
    )
    with pytest.raises(lib.HookEdgeLaneError) as exc:
        lib.load_contract(path)
    assert "sasl_mechanism" in str(exc.value)
    assert "PLAINTEXT" in str(exc.value)


def test_loader_rejects_a_sasl_protocol_with_no_mechanism(tmp_path: Path) -> None:
    lib = _load_lib()
    path = _write_contract(
        tmp_path,
        _lane_block(
            "dev", protocol="SASL_PLAINTEXT", prefix="DEV_", source="operator_env_file"
        ),
    )
    with pytest.raises(lib.HookEdgeLaneError) as exc:
        lib.load_contract(path)
    assert "sasl_mechanism" in str(exc.value)


def test_loader_rejects_a_sasl_protocol_with_no_env_prefix(tmp_path: Path) -> None:
    """A SASL lane that names no credential source is unresolvable at run time."""
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
    with pytest.raises(lib.HookEdgeLaneError) as exc:
        lib.load_contract(path)
    assert "sasl_env_prefix" in str(exc.value)


def test_loader_rejects_an_unknown_security_protocol(tmp_path: Path) -> None:
    lib = _load_lib()
    path = _write_contract(tmp_path, _lane_block("dev", protocol="SASL_TCP"))
    with pytest.raises(lib.HookEdgeLaneError) as exc:
        lib.load_contract(path)
    assert "SASL_TCP" in str(exc.value)


def test_loader_rejects_an_unknown_sasl_mechanism(tmp_path: Path) -> None:
    lib = _load_lib()
    path = _write_contract(
        tmp_path,
        _lane_block(
            "dev",
            protocol="SASL_PLAINTEXT",
            mechanism="SCRAM-SHA-999",
            prefix="DEV_",
            source="operator_env_file",
        ),
    )
    with pytest.raises(lib.HookEdgeLaneError) as exc:
        lib.load_contract(path)
    assert "SCRAM-SHA-999" in str(exc.value)


def test_loader_accepts_the_valid_sasl_shape(tmp_path: Path) -> None:
    """Positive control: the refusals above are about contradiction, not SASL."""
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
    endpoint = lib.load_contract(path).known_lanes["dev"]
    assert endpoint.security_protocol == "SASL_PLAINTEXT"
    assert endpoint.sasl_mechanism == "SCRAM-SHA-256"


# =============================================================================
# Resolution: the four names ModelKafkaEventBusConfig reads, from the declared
# prefix -- and a NAMED refusal when the value is not there
# =============================================================================


def test_resolve_transport_env_returns_the_four_declared_names(tmp_path: Path) -> None:
    """The prefix is stripped: the client reads the unprefixed names.

    ``ModelKafkaEventBusConfig.apply_environment_overrides()`` reads
    ``KAFKA_SECURITY_PROTOCOL`` / ``KAFKA_SASL_MECHANISM`` /
    ``KAFKA_SASL_USERNAME`` / ``KAFKA_SASL_PASSWORD`` and nothing else. The
    prefix governs only WHERE the value is stored on this host.
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
            "DEV_KAFKA_SASL_USERNAME": _FAKE_USER,
            "DEV_KAFKA_SASL_PASSWORD": _FAKE_PASS,
        },
    )

    assert resolved == {
        "KAFKA_SECURITY_PROTOCOL": "SASL_PLAINTEXT",
        "KAFKA_SASL_MECHANISM": "SCRAM-SHA-256",
        "KAFKA_SASL_USERNAME": _FAKE_USER,
        "KAFKA_SASL_PASSWORD": _FAKE_PASS,
    }


def test_resolve_transport_env_on_a_plaintext_lane_sets_no_sasl_names(
    tmp_path: Path,
) -> None:
    """Control in the other direction: a plaintext lane must not go SASL.

    ``x-common-env`` is merged by four other lanes; binding SASL names on a
    listener that offers none is the mirror-image defect of leaving them off
    one that requires them.
    """
    lib = _load_lib()
    path = _write_contract(tmp_path, _lane_block("dev", protocol="PLAINTEXT"))
    contract = lib.load_contract(path)

    resolved = lib.resolve_transport_env(contract, credential_source={})

    assert resolved == {"KAFKA_SECURITY_PROTOCOL": "PLAINTEXT"}


def test_resolve_transport_env_names_the_missing_variables(tmp_path: Path) -> None:
    """The refusal must name the variable AND the file, not time out at a socket.

    This is the whole behavioural point. Without it the operator reads
    ``Unable to bootstrap from [...]`` every 30s and has no way to tell a
    broker that is down from a broker that refused an unauthenticated client.
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

    with pytest.raises(lib.HookEdgeLaneCredentialError) as exc:
        lib.resolve_transport_env(
            contract,
            credential_source={},
            credential_source_name="/somewhere/.omnibase/.env",
        )

    message = str(exc.value)
    assert "DEV_KAFKA_SASL_USERNAME" in message
    assert "DEV_KAFKA_SASL_PASSWORD" in message
    assert "/somewhere/.omnibase/.env" in message


def test_resolve_transport_env_refuses_a_half_present_credential(
    tmp_path: Path,
) -> None:
    """Username without password is not a usable client; it is a silent 401.

    Same rule the deploy agent's model enforces: the two are set together or
    neither is.
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

    with pytest.raises(lib.HookEdgeLaneCredentialError) as exc:
        lib.resolve_transport_env(
            contract, credential_source={"DEV_KAFKA_SASL_USERNAME": _FAKE_USER}
        )
    assert "DEV_KAFKA_SASL_PASSWORD" in str(exc.value)


def test_credential_error_message_never_contains_the_value(tmp_path: Path) -> None:
    """A refusal that leaks the credential into a log is worse than the outage."""
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

    with pytest.raises(lib.HookEdgeLaneCredentialError) as exc:
        lib.resolve_transport_env(
            contract, credential_source={"DEV_KAFKA_SASL_USERNAME": _FAKE_USER}
        )
    assert _FAKE_USER not in str(exc.value)


# =============================================================================
# The operator env file is READ, never exported wholesale
# =============================================================================


def test_read_operator_env_file_parses_names_and_ignores_comments(
    tmp_path: Path,
) -> None:
    lib = _load_lib()
    env_file = tmp_path / ".env"
    env_file.write_text(
        "# a comment\n"
        "\n"
        f"DEV_KAFKA_SASL_USERNAME={_FAKE_USER}\n"
        f'DEV_KAFKA_SASL_PASSWORD="{_FAKE_PASS}"\n'
        "export KAFKA_BOOTSTRAP_SERVERS=test-broker.invalid:19092\n"
        "not a pair\n",
        encoding="utf-8",
    )

    parsed = lib.read_operator_env_file(env_file)

    assert parsed["DEV_KAFKA_SASL_USERNAME"] == _FAKE_USER
    assert parsed["DEV_KAFKA_SASL_PASSWORD"] == _FAKE_PASS
    assert parsed["KAFKA_BOOTSTRAP_SERVERS"] == "test-broker.invalid:19092"
    assert "not a pair" not in parsed


def test_read_operator_env_file_returns_empty_when_absent(tmp_path: Path) -> None:
    """An absent operator env file is a resolvable state, not a crash.

    The refusal belongs to ``resolve_transport_env``, which can name the
    variable it wanted. A reader that raised here would produce a traceback
    naming only a path.
    """
    lib = _load_lib()
    assert lib.read_operator_env_file(tmp_path / "nope" / ".env") == {}
    # Positive control: the same reader does return rows for a file that exists.
    present = tmp_path / ".env"
    present.write_text("A=b\n", encoding="utf-8")
    assert lib.read_operator_env_file(present) == {"A": "b"}


# =============================================================================
# The drainer applies the declared transport before its first publish
# =============================================================================


def _load_drainer() -> ModuleType:
    if str(_LIB_DIR) not in sys.path:
        sys.path.insert(0, str(_LIB_DIR))
    spec = importlib.util.spec_from_file_location(
        "hook_emit_drainer", _LIB_DIR / "hook_emit_drainer.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["hook_emit_drainer"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def _clean_transport_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """No ambient transport may leak into or out of these tests."""
    for name in (
        "KAFKA_SECURITY_PROTOCOL",
        "KAFKA_SASL_MECHANISM",
        "KAFKA_SASL_USERNAME",
        "KAFKA_SASL_PASSWORD",
        "KAFKA_BOOTSTRAP_SERVERS",
        "KAFKA_BROKERS",
        "ONEX_HOOK_EDGE_LANE",
        "OMNIBASE_OPERATOR_ENV_FILE",
    ):
        monkeypatch.delenv(name, raising=False)


def test_drainer_applies_the_declared_sasl_transport(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The four names are in the environment BEFORE the emitter is built.

    ``_Emitter`` reads the broker and its auth out of the environment when it
    constructs its adapter, and it does that once per process. A transport
    applied after the first publish is a transport that never applied.
    """
    drainer = _load_drainer()
    contract = _write_contract(
        tmp_path,
        _lane_block(
            "dev",
            protocol="SASL_PLAINTEXT",
            mechanism="SCRAM-SHA-256",
            prefix="DEV_",
            source="operator_env_file",
        ),
    )
    env_file = tmp_path / ".env"
    env_file.write_text(
        f"DEV_KAFKA_SASL_USERNAME={_FAKE_USER}\nDEV_KAFKA_SASL_PASSWORD={_FAKE_PASS}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("OMNIBASE_OPERATOR_ENV_FILE", str(env_file))

    brokers = drainer.apply_declared_lane(contract_path=contract)

    assert brokers == "test-broker.invalid:19092"
    import os

    assert os.environ["KAFKA_SECURITY_PROTOCOL"] == "SASL_PLAINTEXT"
    assert os.environ["KAFKA_SASL_MECHANISM"] == "SCRAM-SHA-256"
    assert os.environ["KAFKA_SASL_USERNAME"] == _FAKE_USER
    assert os.environ["KAFKA_SASL_PASSWORD"] == _FAKE_PASS


def test_drainer_leaves_no_half_configured_sasl_client_when_the_value_is_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The load-bearing case on a host that does not hold the credential.

    Two things must be true at once. The drainer must NOT die -- it is a
    launchd KeepAlive agent, so exiting spins the restart loop and recreates
    the CPU burn OMN-17224 removed. And it must not leave a partially applied
    SASL environment, which would produce a different, more confusing failure
    than the one it is reporting.

    What it must do instead is say the name of the variable that is missing
    and the file it looked in, once, so the operator is not reading
    ``Unable to bootstrap from [...]`` every thirty seconds with no way to
    tell a refused client from a dead broker.
    """
    import logging
    import os

    drainer = _load_drainer()
    contract = _write_contract(
        tmp_path,
        _lane_block(
            "dev",
            protocol="SASL_PLAINTEXT",
            mechanism="SCRAM-SHA-256",
            prefix="DEV_",
            source="operator_env_file",
        ),
    )
    empty = tmp_path / "empty.env"
    empty.write_text("# no credential here\n", encoding="utf-8")
    monkeypatch.setenv("OMNIBASE_OPERATOR_ENV_FILE", str(empty))

    with caplog.at_level(logging.ERROR, logger="hook_emit_drainer"):
        result = drainer.apply_declared_lane(contract_path=contract)

    assert result is None, (
        "a lane whose credential cannot be resolved must not report a usable "
        "broker; returning one sends the emitter at a listener that will "
        "refuse it and report the refusal as a connection failure"
    )
    assert "KAFKA_SASL_USERNAME" not in os.environ
    assert "KAFKA_SASL_PASSWORD" not in os.environ
    assert "KAFKA_SECURITY_PROTOCOL" not in os.environ

    text = caplog.text
    assert "DEV_KAFKA_SASL_USERNAME" in text
    assert "DEV_KAFKA_SASL_PASSWORD" in text
    assert str(empty) in text


def test_drainer_applies_a_plaintext_lane_without_sasl_names(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Positive control: the refusal above is about SASL, not about the loader."""
    import os

    drainer = _load_drainer()
    contract = _write_contract(tmp_path, _lane_block("dev", protocol="PLAINTEXT"))
    monkeypatch.setenv("OMNIBASE_OPERATOR_ENV_FILE", str(tmp_path / "absent.env"))

    brokers = drainer.apply_declared_lane(contract_path=contract)

    assert brokers == "test-broker.invalid:19092"
    assert os.environ["KAFKA_SECURITY_PROTOCOL"] == "PLAINTEXT"
    assert "KAFKA_SASL_USERNAME" not in os.environ
    assert "KAFKA_SASL_MECHANISM" not in os.environ


def test_drainer_never_logs_the_credential_value(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The drainer's log is 75 MB and world-readable on the operator Mac."""
    import logging

    drainer = _load_drainer()
    contract = _write_contract(
        tmp_path,
        _lane_block(
            "dev",
            protocol="SASL_PLAINTEXT",
            mechanism="SCRAM-SHA-256",
            prefix="DEV_",
            source="operator_env_file",
        ),
    )
    env_file = tmp_path / ".env"
    env_file.write_text(
        f"DEV_KAFKA_SASL_USERNAME={_FAKE_USER}\nDEV_KAFKA_SASL_PASSWORD={_FAKE_PASS}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("OMNIBASE_OPERATOR_ENV_FILE", str(env_file))

    with caplog.at_level(logging.DEBUG, logger="hook_emit_drainer"):
        drainer.apply_declared_lane(contract_path=contract)

    assert _FAKE_PASS not in caplog.text
    assert _FAKE_USER not in caplog.text
    # Positive control: the drainer does log SOMETHING about this lane, so the
    # two absences above are not just an empty log.
    assert "dev" in caplog.text
