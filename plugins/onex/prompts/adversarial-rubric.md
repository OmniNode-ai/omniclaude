# Adversarial Review Rubric

Anti-patterns to detect in any plan, design, or implementation proposal. Each entry is a blocking finding — a single occurrence counts toward the adversarial gate threshold.

---

## ONEX not Docker

**Flag**: Any plan that proposes running workloads as bare Docker containers, `docker compose` services, or raw container images when an ONEX node handler would be the correct primitive.

**Rule**: Workloads that process Kafka events, expose contract-declared capabilities, or participate in the runtime must be implemented as ONEX nodes registered via `onex.nodes` entry points. Docker is infrastructure; ONEX is the execution model.

**Signals to flag**:
- "Deploy a new Docker container for X"
- "Add a `docker-compose.yml` service to handle Y"
- "Run Z as a standalone process"

---

## Typed Pydantic not Strings

**Flag**: Any plan that proposes passing structured data as raw strings, dicts, `json.loads` output, or untyped payloads between nodes or across Kafka topics.

**Rule**: All inter-node data — event envelopes, command payloads, response objects — must be declared as Pydantic models in `omnibase_compat` or the owning repo's schema module. Type safety is enforced at the boundary; strings are not boundaries.

**Signals to flag**:
- "Parse the JSON payload with `json.loads`"
- "Pass a dict with keys X, Y, Z"
- "Deserialize the message body as a string"
- Using `Any` or `dict` as a type annotation for cross-boundary data

---

## Contracts not Hardcoding

**Flag**: Any plan that hardcodes Kafka topic names, model IDs, timeouts, service URLs, queue names, or configuration values directly in source code.

**Rule**: All runtime-variable values must be declared in `contract.yaml` and read via the contract resolver at startup. Hardcoded strings are a drift vector — when infra changes, the code silently breaks.

**Signals to flag**:
- Topic names as string literals in Python source (e.g., `"onex.cmd.deploy.rebuild-requested.v1"`)
- Model IDs hardcoded in LLM call sites (e.g., `model="claude-opus-4-6"`)
- Timeouts as magic numbers
- Service URLs in source files rather than resolved from config

---

## OAuth not SSO

**Flag**: Any plan that proposes implementing authentication via SSO, SAML, shared secrets, API keys passed in headers, or session-cookie-based auth when OAuth 2.0 / OIDC is the correct protocol.

**Rule**: All user-facing and service-to-service authentication in the ONEX platform uses OAuth 2.0 flows (PKCE for user-facing, client credentials for M2M). SSO federation is layered on top of OAuth — it is not a replacement.

**Signals to flag**:
- "Use SSO to authenticate users"
- "Share an API key between services"
- "Use a session cookie for service auth"
- SAML assertions as the primary auth mechanism

---

## Topics from contract.yaml not topics.py

**Flag**: Any plan that proposes defining, listing, or importing Kafka topic names from a Python module (e.g., `topics.py`, `constants.py`, `enums.py`) rather than reading them from `contract.yaml`.

**Rule**: Topic names are infrastructure declarations owned by `contract.yaml`. A Python module that enumerates topic strings is a shadow registry — it will diverge from the contract and create split-brain topic naming. The contract resolver is the single source of truth.

**Signals to flag**:
- "Add a `topics.py` with all topic constants"
- "Import `TOPIC_NAME` from `omnibase_infra.topics`"
- "Define an enum of Kafka topics"
- Any Python-side enumeration of topic strings outside of generated contract bindings

---

## Usage

This rubric is consumed by `hostile_reviewer --static` via `--rubric docs/plans/adversarial-rubric.md`. Each pattern match is a finding. The adversarial pipeline gate requires ≥3 findings before proceeding to ticket creation — if fewer are found, the pipeline escalates to the user rather than rubber-stamping the plan.
