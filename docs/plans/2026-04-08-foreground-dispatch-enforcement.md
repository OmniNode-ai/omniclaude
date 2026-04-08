# Foreground Dispatch Enforcement Hook Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use executing-plans to implement this plan phase-by-phase.

**Goal:** Enforce that all work goes through background agents using skills — no direct foreground tool calls except conversation and dispatch tools. Fully contract-driven: tool lists, skill routes, and enforcement mode all come from a YAML contract; Pydantic models gate every data boundary.

**Architecture (two-repo):** Business logic lives in an omnimarket node (`node_dispatch_enforcement`). The omniclaude hook is a thin shim (~20 lines of shell) that calls the omnimarket `cli_shim.py` via `$PYTHON_CMD`. This follows the "skills are wrappers, logic belongs in omnimarket node handlers" principle.

- **omnimarket** (Tasks 1–5): `node_dispatch_enforcement` owns the contract YAML, Pydantic models, handler logic, CLI shim, Kafka emission, and golden chain tests.
- **omniclaude** (Task 6): Single shell script + hooks.json registration. No Python. No business logic.

**Tech Stack:** omnimarket Pydantic v2 models, omnimarket contract YAML pattern, omnimarket golden chain tests (EventBusInmemory), existing `FrictionEvent`/`FrictionSeverity` API (omniclaude friction_recorder.py), bash shim in omniclaude hooks.

---

## Known Types Inventory

> Types discovered in the repository relevant to this plan. All new types are justified here.

- `EnforcementMode` — `plugins/onex/hooks/lib/hook_policy.py:55` — `hard`/`soft`/`advisory`/`disabled` (StrEnum). **Evaluated for reuse.** Surface-level overlap: both use hard/soft/advisory. **Not reused** for two reasons: (1) `hook_policy.EnforcementMode` is coupled to `HookPolicy` which models approval channels (flag files, Slack polling, one-time overrides) — importing it into omnimarket would pull omniclaude-specific concepts into the business logic layer; (2) it includes `DISABLED` which has no meaning in dispatch enforcement (enforcement is always active — the off state is removing the hook). `EnumEnforcementMode` in omnimarket is a pure severity ladder with no approval-channel coupling.
- `FrictionEvent` — `plugins/onex/skills/_shared/friction_recorder.py:89` — fields: `skill`, `surface`, `severity: FrictionSeverity`, `description`, `context_ticket_id`, `session_id`, `timestamp: datetime` (timezone-aware)
- `FrictionSeverity` — `plugins/onex/skills/_shared/friction_recorder.py:62` — StrEnum: LOW/MEDIUM/HIGH/CRITICAL
- `ModelBuildDispatchInput` — `omnimarket/.../model_build_dispatch_input.py` — frozen Pydantic with `ConfigDict(frozen=True, extra="forbid")`, `Field(...)` with descriptions. **Pattern reference** for new models.
- `HandlerBuildDispatch` — `omnimarket/.../handler_build_dispatch.py` — `handle()` async method, topic string loaded at module level from contract. **Pattern reference** for new handler.

**New types introduced by this plan (all in omnimarket):**

| Type | File | Justification |
|------|------|---------------|
| `ModelSkillRoute` | `node_dispatch_enforcement/models/model_skill_route.py` | No existing type maps tool+keywords→skill+message. New mapping model. |
| `ModelDispatchEnforcementInput` | `node_dispatch_enforcement/models/model_dispatch_enforcement_input.py` | No existing type captures tool_name + tool_input + session_id as a typed request to the enforcement handler. |
| `EnumEnforcementOutcome` | `node_dispatch_enforcement/models/model_enforcement_result.py` | No existing outcome enum for BLOCK/ALLOW/FALLBACK. Needed to type `ModelDispatchEnforcementResult`. |
| `EnumEnforcementMode` | `node_dispatch_enforcement/models/model_enforcement_result.py` | Pure severity ladder (advisory/soft/hard). Not reusing `hook_policy.EnforcementMode` — see above. |
| `ModelDispatchEnforcementResult` | `node_dispatch_enforcement/models/model_enforcement_result.py` | No existing frozen Pydantic type represents a block/allow/fallback enforcement result. `ModelSuppressionResult` is suppression-only with different field semantics. |

---

## Task 1: Create `node_dispatch_enforcement` scaffold in omnimarket

**Repo:** omnimarket worktree
**Files:**
- Create: `src/omnimarket/nodes/node_dispatch_enforcement/__init__.py`
- Create: `src/omnimarket/nodes/node_dispatch_enforcement/metadata.yaml`
- Create: `src/omnimarket/nodes/node_dispatch_enforcement/contract.yaml`
- Modify: `pyproject.toml` — add entry point

**Step 1: Create `__init__.py`**

```python
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""node_dispatch_enforcement — foreground dispatch enforcement for ONEX sessions."""
```

**Step 2: Create `metadata.yaml`**

```yaml
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
name: node_dispatch_enforcement
version: "1.0.0"
description: "Evaluates foreground tool calls against an enforcement contract and returns block/allow/fallback decisions."
capabilities:
  - foreground-dispatch-enforcement
  - friction-recording
  - skill-route-lookup
dependencies: []
compatibility:
  omnibase_core: ">=0.1.0"
```

**Step 3: Create `contract.yaml`**

```yaml
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# node_dispatch_enforcement contract
# All tool lists and skill routes live here. No Python changes needed to add/remove routes.

descriptor:
  name: node_dispatch_enforcement
  version: "1.0.0"

handler_routing:
  default: HandlerDispatchEnforcement

input_model: ModelDispatchEnforcementInput
output_model: ModelDispatchEnforcementResult

event_bus:
  publish_topics:
    - name: onex.evt.omnimarket.dispatch-enforcement-friction.v1
      description: "Emitted when a blocked or fallback tool call is evaluated"
    - name: onex.cmd.omnimarket.skill-generation-requested.v1
      description: "Emitted in hard mode when no skill route is found — triggers writing_skills"

# Enforcement configuration — source of truth for tool lists and routes
enforcement:
  # advisory | soft | hard
  # advisory: log only, never block
  # soft: block + friction event when skill match found
  # hard: block + friction + skill-gen dispatch when no match
  mode: advisory

  allowed_tools:
    - Agent
    - SendMessage
    - TeamCreate
    - TeamDelete
    - TaskCreate
    - TaskUpdate
    - TaskList
    - TaskGet
    - Skill
    - ToolSearch
    - AskUserQuestion

  blocked_tools:
    - Bash
    - Read
    - Write
    - Edit
    - Grep
    - Glob

  # First-match-wins. Keywords are case-insensitive substring matches against tool input JSON.
  skill_routes:
    - tool: Bash
      keywords: ["uv run pytest", "pytest tests", "python -m pytest"]
      skill: "onex:systematic_debugging"
      message: "Use skill: /onex:systematic_debugging via a background agent"

    - tool: Bash
      keywords: ["git worktree", "worktree add"]
      skill: "onex:using_git_worktrees"
      message: "Use skill: /onex:using_git_worktrees via a background agent"

    - tool: Bash
      keywords: ["gh pr create", "gh pr merge", "gh pr review"]
      skill: "onex:pr_polish"
      message: "Use skill: /onex:pr_polish via a background agent"

    - tool: Bash
      keywords: ["docker compose", "docker-compose up", "docker-compose down"]
      skill: "onex:start_environment"
      message: "Use skill: /onex:start_environment via a background agent"

    - tool: Bash
      keywords: ["ruff check", "mypy src", "pyright", "bandit -r"]
      skill: "onex:local_review"
      message: "Use skill: /onex:local_review via a background agent"

    - tool: Edit
      keywords: ["SKILL.md", "/skills/"]
      skill: "onex:writing_skills"
      message: "Use skill: /onex:writing_skills via a background agent"

    - tool: Write
      keywords: ["SKILL.md", "/skills/"]
      skill: "onex:writing_skills"
      message: "Use skill: /onex:writing_skills via a background agent"
```

**Step 4: Register entry point in `pyproject.toml`**

Under `[project.entry-points."onex.nodes"]`, add:

```toml
node_dispatch_enforcement = "omnimarket.nodes.node_dispatch_enforcement"
```

**Step 5: Commit**

```bash
git add src/omnimarket/nodes/node_dispatch_enforcement/ pyproject.toml
git commit -m "feat(enforcement): scaffold node_dispatch_enforcement with contract.yaml"
```

---

## Task 2: Define Pydantic models for enforcement input and result

**Repo:** omnimarket worktree
**Files:**
- Create: `src/omnimarket/nodes/node_dispatch_enforcement/models/__init__.py`
- Create: `src/omnimarket/nodes/node_dispatch_enforcement/models/model_skill_route.py`
- Create: `src/omnimarket/nodes/node_dispatch_enforcement/models/model_dispatch_enforcement_input.py`
- Create: `src/omnimarket/nodes/node_dispatch_enforcement/models/model_enforcement_result.py`
- Test: `tests/unit/test_dispatch_enforcement_models.py`

**Step 1: Write failing tests**

```python
# tests/unit/test_dispatch_enforcement_models.py
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
import pytest
from pydantic import ValidationError


def test_skill_route_requires_nonempty_keywords():
    from omnimarket.nodes.node_dispatch_enforcement.models.model_skill_route import ModelSkillRoute
    with pytest.raises(ValidationError):
        ModelSkillRoute(tool="Bash", keywords=[], skill="onex:foo", message="msg")


def test_skill_route_valid():
    from omnimarket.nodes.node_dispatch_enforcement.models.model_skill_route import ModelSkillRoute
    r = ModelSkillRoute(
        tool="Bash",
        keywords=["pytest"],
        skill="onex:systematic_debugging",
        message="Use skill: /onex:systematic_debugging via a background agent",
    )
    assert r.tool == "Bash"
    assert "pytest" in r.keywords


def test_skill_route_is_frozen():
    from omnimarket.nodes.node_dispatch_enforcement.models.model_skill_route import ModelSkillRoute
    r = ModelSkillRoute(tool="Bash", keywords=["x"], skill="onex:foo", message="msg")
    with pytest.raises(Exception):
        r.tool = "Edit"


def test_enforcement_input_valid():
    from omnimarket.nodes.node_dispatch_enforcement.models.model_dispatch_enforcement_input import (
        ModelDispatchEnforcementInput,
    )
    inp = ModelDispatchEnforcementInput(
        tool_name="Bash",
        tool_input={"command": "uv run pytest tests/ -v"},
        session_id="sess-1",
    )
    assert inp.tool_name == "Bash"


def test_enforcement_result_is_frozen():
    from omnimarket.nodes.node_dispatch_enforcement.models.model_enforcement_result import (
        EnumEnforcementOutcome,
        ModelDispatchEnforcementResult,
    )
    r = ModelDispatchEnforcementResult(
        outcome=EnumEnforcementOutcome.BLOCK,
        tool_name="Bash",
        session_id="sess-1",
        matched_skill="onex:foo",
        message="msg",
    )
    with pytest.raises(Exception):
        r.outcome = EnumEnforcementOutcome.ALLOW


def test_enforcement_mode_enum_values():
    from omnimarket.nodes.node_dispatch_enforcement.models.model_enforcement_result import (
        EnumEnforcementMode,
    )
    assert EnumEnforcementMode.ADVISORY == "advisory"
    assert EnumEnforcementMode.SOFT == "soft"
    assert EnumEnforcementMode.HARD == "hard"
```

**Step 2: Run tests to verify they fail**

```bash
pytest tests/unit/test_dispatch_enforcement_models.py -v
```

Expected: ImportError.

**Step 3: Implement the models**

`models/__init__.py`:
```python
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
```

`models/model_skill_route.py`:
```python
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Pydantic model for a single tool→skill routing rule."""
from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator

__all__ = ["ModelSkillRoute"]


class ModelSkillRoute(BaseModel):
    """A single tool→skill routing rule loaded from the enforcement contract."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    tool: str = Field(..., description="Tool name this route applies to (e.g. 'Bash')")
    keywords: Annotated[list[str], Field(min_length=1)] = Field(
        ..., description="Case-insensitive substrings matched against tool input JSON"
    )
    skill: str = Field(..., description="Skill identifier to redirect to (e.g. 'onex:systematic_debugging')")
    message: str = Field(..., description="Human-readable block/redirect message shown to the agent")

    @field_validator("keywords")
    @classmethod
    def keywords_nonempty_strings(cls, v: list[str]) -> list[str]:
        if not all(isinstance(k, str) and k.strip() for k in v):
            raise ValueError("All keywords must be non-empty strings")
        return v
```

`models/model_dispatch_enforcement_input.py`:
```python
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Input model for the dispatch enforcement handler."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

__all__ = ["ModelDispatchEnforcementInput"]


class ModelDispatchEnforcementInput(BaseModel):
    """A single tool call to evaluate against the enforcement contract."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    tool_name: str = Field(..., description="Name of the tool being called (e.g. 'Bash')")
    tool_input: dict[str, Any] = Field(default_factory=dict, description="Raw tool input payload")
    session_id: str = Field(..., description="Claude Code session ID for correlation")
```

`models/model_enforcement_result.py`:
```python
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Result models and enums for the dispatch enforcement handler."""
from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "EnumEnforcementOutcome",
    "EnumEnforcementMode",
    "ModelDispatchEnforcementResult",
]


class EnumEnforcementOutcome(StrEnum):
    BLOCK = "block"       # skill match found — redirect to skill
    ALLOW = "allow"       # allowed tool (dispatch/conversation)
    FALLBACK = "fallback" # blocked tool, no skill match — allow + log friction


class EnumEnforcementMode(StrEnum):
    """Enforcement severity ladder.

    Intentionally separate from omniclaude's hook_policy.EnforcementMode which
    conflates policy mode with approval-channel concerns (flag files, Slack polling).
    """
    ADVISORY = "advisory"  # log only, never block
    SOFT = "soft"          # block with skill redirect when match found
    HARD = "hard"          # block + dispatch auto-skill generation


class ModelDispatchEnforcementResult(BaseModel):
    """Result of evaluating one tool call against the enforcement contract."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    outcome: EnumEnforcementOutcome = Field(..., description="Decision: block, allow, or fallback")
    tool_name: str = Field(..., description="Tool name that was evaluated")
    session_id: str = Field(..., description="Session ID for correlation")
    matched_skill: str | None = Field(None, description="Skill identifier if a route was matched, or None if no route matched")
    message: str | None = Field(None, description="Block/redirect message if applicable")
    # Enriched fields for downstream friction analysis
    timestamp: datetime = Field(default_factory=lambda: datetime.now(tz=timezone.utc), description="UTC timestamp of the enforcement decision")
    enforcement_mode: EnumEnforcementMode = Field(..., description="Enforcement mode active at time of decision")
    file_path: str | None = Field(None, description="File path touched by the tool call, if applicable (Edit/Write/Read)")
    project_context: str | None = Field(None, description="CLAUDE_PROJECT_DIR at time of evaluation, for repo-level friction analysis")
```

**Step 4: Run tests to verify they pass**

```bash
pytest tests/unit/test_dispatch_enforcement_models.py -v
```

Expected: PASS (6 tests).

**Step 5: Commit**

```bash
git add src/omnimarket/nodes/node_dispatch_enforcement/models/
git add tests/unit/test_dispatch_enforcement_models.py
git commit -m "feat(enforcement): add Pydantic models for dispatch enforcement node"
```

---

## Task 3: Write the enforcement handler (pure compute)

**Repo:** omnimarket worktree
**Files:**
- Create: `src/omnimarket/nodes/node_dispatch_enforcement/handlers/__init__.py`
- Create: `src/omnimarket/nodes/node_dispatch_enforcement/handlers/handler_dispatch_enforcement.py`
- Test: `tests/unit/test_dispatch_enforcement_handler.py`
- Test: `tests/test_golden_chain_dispatch_enforcement.py`

**Step 1: Write failing unit tests**

```python
# tests/unit/test_dispatch_enforcement_handler.py
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
import pytest
from omnimarket.nodes.node_dispatch_enforcement.handlers.handler_dispatch_enforcement import (
    HandlerDispatchEnforcement,
)
from omnimarket.nodes.node_dispatch_enforcement.models.model_dispatch_enforcement_input import (
    ModelDispatchEnforcementInput,
)
from omnimarket.nodes.node_dispatch_enforcement.models.model_enforcement_result import (
    EnumEnforcementOutcome,
)


@pytest.fixture
def handler():
    return HandlerDispatchEnforcement()


def test_allowed_tool_returns_allow(handler):
    inp = ModelDispatchEnforcementInput(tool_name="Agent", tool_input={}, session_id="s1")
    result = handler.evaluate(inp)
    assert result.outcome == EnumEnforcementOutcome.ALLOW


def test_unknown_tool_returns_allow(handler):
    inp = ModelDispatchEnforcementInput(tool_name="SomeFutureTool", tool_input={}, session_id="s1")
    result = handler.evaluate(inp)
    assert result.outcome == EnumEnforcementOutcome.ALLOW


def test_advisory_mode_matched_tool_returns_fallback(handler):
    """Default mode is advisory — even matched tools get FALLBACK, not BLOCK."""
    inp = ModelDispatchEnforcementInput(
        tool_name="Bash",
        tool_input={"command": "uv run pytest tests/ -v"},
        session_id="s1",
    )
    result = handler.evaluate(inp)
    # advisory = never block
    assert result.outcome == EnumEnforcementOutcome.FALLBACK
    assert result.matched_skill == "onex:systematic_debugging"


def test_advisory_mode_unmatched_bash_returns_fallback(handler):
    inp = ModelDispatchEnforcementInput(
        tool_name="Bash",
        tool_input={"command": "cat /etc/hostname"},
        session_id="s1",
    )
    result = handler.evaluate(inp)
    assert result.outcome == EnumEnforcementOutcome.FALLBACK
    assert result.matched_skill is None


def test_result_is_frozen(handler):
    inp = ModelDispatchEnforcementInput(tool_name="Agent", tool_input={}, session_id="s1")
    result = handler.evaluate(inp)
    with pytest.raises(Exception):
        result.outcome = EnumEnforcementOutcome.BLOCK
```

**Step 2: Write failing golden chain test**

```python
# tests/test_golden_chain_dispatch_enforcement.py
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Golden chain test for node_dispatch_enforcement.

Uses EventBusInmemory — zero infrastructure required.
"""
import pytest
from omnibase_core.event_bus.inmemory import EventBusInmemory

from omnimarket.nodes.node_dispatch_enforcement.handlers.handler_dispatch_enforcement import (
    HandlerDispatchEnforcement,
)
from omnimarket.nodes.node_dispatch_enforcement.models.model_dispatch_enforcement_input import (
    ModelDispatchEnforcementInput,
)
from omnimarket.nodes.node_dispatch_enforcement.models.model_enforcement_result import (
    EnumEnforcementOutcome,
)

FRICTION_TOPIC = "onex.evt.omnimarket.dispatch-enforcement-friction.v1"


@pytest.fixture
def bus():
    return EventBusInmemory()


@pytest.fixture
def handler():
    return HandlerDispatchEnforcement()


@pytest.mark.unit
def test_golden_chain_allow_agent(handler, bus):
    inp = ModelDispatchEnforcementInput(tool_name="Agent", tool_input={}, session_id="gc-1")
    result = handler.evaluate(inp)
    assert result.outcome == EnumEnforcementOutcome.ALLOW
    assert len(bus.published(FRICTION_TOPIC)) == 0


@pytest.mark.unit
def test_golden_chain_fallback_bash(handler, bus):
    inp = ModelDispatchEnforcementInput(
        tool_name="Bash",
        tool_input={"command": "cat /etc/hostname"},
        session_id="gc-1",
    )
    result = handler.evaluate(inp)
    assert result.outcome == EnumEnforcementOutcome.FALLBACK


@pytest.mark.unit
def test_golden_chain_fallback_includes_matched_skill(handler, bus):
    inp = ModelDispatchEnforcementInput(
        tool_name="Bash",
        tool_input={"command": "uv run pytest tests/ -v"},
        session_id="gc-1",
    )
    result = handler.evaluate(inp)
    assert result.outcome == EnumEnforcementOutcome.FALLBACK
    assert result.matched_skill == "onex:systematic_debugging"
```

**Step 3: Run tests to verify they fail**

```bash
pytest tests/unit/test_dispatch_enforcement_handler.py \
       tests/test_golden_chain_dispatch_enforcement.py -v
```

Expected: ImportError.

**Step 4: Implement the handler**

`handlers/__init__.py`:
```python
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
```

`handlers/handler_dispatch_enforcement.py`:
```python
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Pure-compute enforcement handler for node_dispatch_enforcement.

Reads contract.yaml at module level. evaluate() is synchronous and
side-effect-free — CLI shim handles Kafka emission separately.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import yaml

from omnimarket.nodes.node_dispatch_enforcement.models.model_dispatch_enforcement_input import (
    ModelDispatchEnforcementInput,
)
from omnimarket.nodes.node_dispatch_enforcement.models.model_enforcement_result import (
    EnumEnforcementMode,
    EnumEnforcementOutcome,
    ModelDispatchEnforcementResult,
)
from omnimarket.nodes.node_dispatch_enforcement.models.model_skill_route import ModelSkillRoute

# Contract path resolution: use CLAUDE_PLUGIN_ROOT env var (set by Claude Code's plugin system)
# to locate the contract YAML. Falls back to module-relative path for test environments where
# CLAUDE_PLUGIN_ROOT is not set.
#
# Config caching and reload semantics: the contract is cached at module level on first load.
# This means: config changes require a new process or session restart to take effect.
# There is no hot-reload mechanism — this is intentional (contracts are immutable within
# a session; mode changes are a deployment-time concern).
def _resolve_contract_path() -> Path:
    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if plugin_root:
        candidate = Path(plugin_root) / "nodes" / "node_dispatch_enforcement" / "contract.yaml"
        if candidate.exists():
            return candidate
    # Test fallback: resolve relative to module location
    return Path(__file__).resolve().parents[1] / "contract.yaml"


_contract: dict[str, Any] | None = None


def _get_contract() -> dict[str, Any]:
    global _contract
    if _contract is None:
        with open(_resolve_contract_path()) as f:
            _contract = yaml.safe_load(f) or {}
    return _contract


def _extract_file_path(tool_name: str, tool_input: dict[str, Any]) -> str | None:
    """Extract file path from tool input, if applicable."""
    if tool_name in ("Edit", "Write", "Read"):
        return tool_input.get("file_path") or tool_input.get("path") or None
    return None


def _extract_context_hint(tool_name: str, tool_input: dict[str, Any]) -> str:
    """Extract a representative string from tool input for keyword matching."""
    if tool_name == "Bash":
        return tool_input.get("command", "")
    if tool_name in ("Edit", "Write"):
        path = str(tool_input.get("file_path", tool_input.get("path", "")))
        content = str(tool_input.get("new_string", tool_input.get("content", "")))
        return f"{path} {content[:200]}"
    return json.dumps(tool_input)[:300]


def _lookup_skill(tool_name: str, context_hint: str) -> ModelSkillRoute | None:
    """First-match-wins keyword lookup from contract skill_routes."""
    cfg = _get_contract().get("enforcement", {})
    hint_lower = context_hint.lower()
    for raw_route in cfg.get("skill_routes", []):
        route = ModelSkillRoute.model_validate(raw_route)
        if route.tool != tool_name:
            continue
        for kw in route.keywords:
            if kw.lower() in hint_lower:
                return route
    return None


class HandlerDispatchEnforcement:
    """Evaluates a single tool call against the enforcement contract.

    Pure compute — no side effects. CLI shim owns Kafka emission.
    """

    def evaluate(self, inp: ModelDispatchEnforcementInput) -> ModelDispatchEnforcementResult:
        cfg = _get_contract().get("enforcement", {})
        allowed_tools: set[str] = set(cfg.get("allowed_tools", []))
        blocked_tools: set[str] = set(cfg.get("blocked_tools", []))
        # ONEX_DISPATCH_ENFORCEMENT_MODE env var overrides contract mode (test-only escape hatch)
        mode_str: str = os.environ.get("ONEX_DISPATCH_ENFORCEMENT_MODE") or cfg.get("mode", "advisory")
        try:
            mode = EnumEnforcementMode(mode_str)
        except ValueError:
            mode = EnumEnforcementMode.ADVISORY

        project_context = os.environ.get("CLAUDE_PROJECT_DIR")
        file_path = _extract_file_path(inp.tool_name, inp.tool_input)

        if inp.tool_name in allowed_tools or inp.tool_name not in blocked_tools:
            return ModelDispatchEnforcementResult(
                outcome=EnumEnforcementOutcome.ALLOW,
                tool_name=inp.tool_name,
                session_id=inp.session_id,
                enforcement_mode=mode,
                project_context=project_context,
                file_path=file_path,
            )

        context_hint = _extract_context_hint(inp.tool_name, inp.tool_input)
        route = _lookup_skill(inp.tool_name, context_hint)

        if route and mode in (EnumEnforcementMode.SOFT, EnumEnforcementMode.HARD):
            return ModelDispatchEnforcementResult(
                outcome=EnumEnforcementOutcome.BLOCK,
                tool_name=inp.tool_name,
                session_id=inp.session_id,
                matched_skill=route.skill,
                message=route.message,
                enforcement_mode=mode,
                project_context=project_context,
                file_path=file_path,
            )

        return ModelDispatchEnforcementResult(
            outcome=EnumEnforcementOutcome.FALLBACK,
            tool_name=inp.tool_name,
            session_id=inp.session_id,
            matched_skill=route.skill if route else None,
            message=route.message if route else None,
            enforcement_mode=mode,
            project_context=project_context,
            file_path=file_path,
        )
```

**Step 5: Run tests to verify they pass**

```bash
pytest tests/unit/test_dispatch_enforcement_handler.py \
       tests/test_golden_chain_dispatch_enforcement.py -v
```

Expected: PASS (5 unit + 3 golden chain = 8 tests).

**Step 6: Commit**

```bash
git add src/omnimarket/nodes/node_dispatch_enforcement/handlers/
git add tests/unit/test_dispatch_enforcement_handler.py
git add tests/test_golden_chain_dispatch_enforcement.py
git commit -m "feat(enforcement): add HandlerDispatchEnforcement with golden chain tests"
```

---

## Task 4: Write `cli_shim.py` (stdin→handler→stdout + Kafka fire-and-forget)

**Repo:** omnimarket worktree
**Files:**
- Create: `src/omnimarket/nodes/node_dispatch_enforcement/cli_shim.py`
- Test: `tests/unit/test_dispatch_enforcement_cli_shim.py`

**Step 1: Write failing tests**

```python
# tests/unit/test_dispatch_enforcement_cli_shim.py
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
import json
from unittest.mock import patch


def _run(payload: dict) -> tuple[int, dict]:
    from omnimarket.nodes.node_dispatch_enforcement.cli_shim import run_shim
    return run_shim(payload)


def test_allowed_tool_exits_0_clean():
    code, out = _run({"tool_name": "Agent", "tool_input": {}, "session_id": "s1"})
    assert code == 0
    assert "_enforcement_result" not in out


def test_advisory_mode_matched_exits_0_with_tag(monkeypatch):
    code, out = _run({
        "tool_name": "Bash",
        "tool_input": {"command": "uv run pytest tests/ -v"},
        "session_id": "s1",
    })
    assert code == 0
    assert "_enforcement_result" in out
    assert out["_enforcement_result"]["outcome"] == "fallback"
    assert out["_enforcement_result"]["matched_skill"] == "onex:systematic_debugging"


def test_invalid_input_fails_open():
    from omnimarket.nodes.node_dispatch_enforcement.cli_shim import run_shim
    code, out = run_shim(None)
    assert code == 0


def test_bad_json_env_fails_open():
    from omnimarket.nodes.node_dispatch_enforcement.cli_shim import run_shim
    code, out = run_shim({})  # empty dict — tool_name missing
    assert code == 0


def test_emit_is_fire_and_forget():
    """Verify Kafka emit errors do not propagate to exit code."""
    with patch(
        "omnimarket.nodes.node_dispatch_enforcement.cli_shim._emit_friction",
        side_effect=RuntimeError("kafka down"),
    ):
        code, out = _run({
            "tool_name": "Bash",
            "tool_input": {"command": "cat /etc/hostname"},
            "session_id": "s1",
        })
    assert code == 0  # fail open
```

**Step 2: Run tests to verify they fail**

```bash
pytest tests/unit/test_dispatch_enforcement_cli_shim.py -v
```

Expected: ImportError.

**Step 3: Implement `cli_shim.py`**

```python
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""CLI shim for node_dispatch_enforcement.

stdin → HandlerDispatchEnforcement.evaluate() → stdout
Kafka emission is fire-and-forget via EmitClient (omniclaude pattern).
Never raises — always exits 0 on error (fail-open).

Exit codes:
    0 — allow (clean pass-through or fallback with _enforcement_result tag)
    2 — block (soft/hard mode with skill match)
"""
from __future__ import annotations

import json
import sys
from typing import Any

from omnimarket.nodes.node_dispatch_enforcement.handlers.handler_dispatch_enforcement import (
    HandlerDispatchEnforcement,
)
from omnimarket.nodes.node_dispatch_enforcement.models.model_dispatch_enforcement_input import (
    ModelDispatchEnforcementInput,
)
from omnimarket.nodes.node_dispatch_enforcement.models.model_enforcement_result import (
    EnumEnforcementOutcome,
    ModelDispatchEnforcementResult,
)

_handler = HandlerDispatchEnforcement()

# Topic strings declared in contract.yaml — loaded once at module level
import yaml
from pathlib import Path

_contract = yaml.safe_load((Path(__file__).parent / "contract.yaml").read_text()) or {}
_FRICTION_TOPIC: str = _contract["event_bus"]["publish_topics"][0]["name"]
_SKILL_GEN_TOPIC: str = _contract["event_bus"]["publish_topics"][1]["name"]


def _emit_friction(result: ModelDispatchEnforcementResult) -> None:
    """Fire-and-forget Kafka emit. Mirrors emit_client_wrapper.py pattern."""
    try:
        from omnimarket.nodes.node_emit_daemon.client import EmitClient  # type: ignore[import]
        client = EmitClient()
        client.emit(_FRICTION_TOPIC, result.model_dump())
    except ImportError:
        pass  # emit daemon not available — silently skip
    except Exception:
        pass  # Kafka unavailable — silently skip


def run_shim(payload: dict[str, Any] | None) -> tuple[int, dict[str, Any]]:
    if not payload or not isinstance(payload, dict):
        return 0, payload or {}

    tool_name = payload.get("tool_name", "")
    if not tool_name:
        return 0, payload

    try:
        inp = ModelDispatchEnforcementInput(
            tool_name=tool_name,
            tool_input=payload.get("tool_input") or {},
            session_id=payload.get("session_id", payload.get("sessionId", "unknown")),
        )
        result = _handler.evaluate(inp)
    except Exception:
        return 0, payload  # fail open

    if result.outcome == EnumEnforcementOutcome.BLOCK:
        _emit_friction(result)
        return 2, {
            "decision": "block",
            "reason": result.message or f"Use a background agent for {result.tool_name}",
            "tool_name": result.tool_name,
            "matched_skill": result.matched_skill,
        }

    if result.outcome == EnumEnforcementOutcome.FALLBACK:
        _emit_friction(result)
        out = dict(payload)
        out["_enforcement_result"] = result.model_dump()
        return 0, out

    return 0, payload


def main() -> None:
    raw = sys.stdin.read().strip()
    try:
        payload = json.loads(raw) if raw else None
    except json.JSONDecodeError:
        payload = None
    code, output = run_shim(payload)
    print(json.dumps(output))
    sys.exit(code)


if __name__ == "__main__":
    main()
```

**Step 4: Run tests to verify they pass**

```bash
pytest tests/unit/test_dispatch_enforcement_cli_shim.py -v
```

Expected: PASS (5 tests).

**Step 5: Run all omnimarket tests**

```bash
pytest tests/ -v --tb=short
```

Expected: all existing tests pass, zero regressions.

**Step 6: Run linters**

```bash
uv run ruff check src/omnimarket/nodes/node_dispatch_enforcement/
uv run mypy src/omnimarket/nodes/node_dispatch_enforcement/ --strict
```

Expected: no errors. Fix any issues before proceeding.

**Step 7: Commit**

```bash
git add src/omnimarket/nodes/node_dispatch_enforcement/cli_shim.py
git add tests/unit/test_dispatch_enforcement_cli_shim.py
git commit -m "feat(enforcement): add cli_shim.py with Kafka fire-and-forget emit"
```

---

## Task 5: Open omnimarket PR

**Repo:** omnimarket worktree

```bash
gh pr create \
  --title "feat(enforcement): add node_dispatch_enforcement" \
  --body "Adds node_dispatch_enforcement with contract.yaml, Pydantic models, HandlerDispatchEnforcement, cli_shim.py, and golden chain tests. This is the business logic half of the foreground dispatch enforcement system (omniclaude hook is Task 6 in a separate PR)."
```

---

## Task 6: Add omniclaude thin shim and register hook

**Repo:** omniclaude worktree
**Files:**
- Create: `plugins/onex/hooks/scripts/pre_tool_use_foreground_enforcement.sh`
- Modify: `plugins/onex/hooks/hooks.json`

**Context:** This task depends on Task 5 being merged first (or at minimum the omnimarket branch being installed into the Python environment). The shim uses `try/except ImportError` to fail open if omnimarket is not installed.

**Step 1: Create the shell shim**

File: `plugins/onex/hooks/scripts/pre_tool_use_foreground_enforcement.sh`

```bash
#!/bin/bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
# PreToolUse Foreground Dispatch Enforcement — thin shim calling omnimarket node
# matcher: "^(Bash|Read|Write|Edit|Grep|Glob)$"
# Business logic lives in omnimarket: node_dispatch_enforcement.cli_shim

set -euo pipefail
_OMNICLAUDE_HOOK_NAME="$(basename "${BASH_SOURCE[0]}")"
source "$(dirname "${BASH_SOURCE[0]}")/error-guard.sh" 2>/dev/null || true
cd "$HOME" 2>/dev/null || cd /tmp || true

_SELF="$(realpath "${BASH_SOURCE[0]}" 2>/dev/null \
    || python3 -c "import os,sys; print(os.path.realpath(sys.argv[1]))" "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(cd "$(dirname "${_SELF}")" && pwd)"
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-$(cd "${SCRIPT_DIR}/../.." && pwd)}"
unset _SELF SCRIPT_DIR
source "$(dirname "${BASH_SOURCE[0]}")/onex-paths.sh" || { exit 0; }
LOG_FILE="${LOG_FILE:-${ONEX_HOOK_LOG}}"
mkdir -p "$(dirname "$LOG_FILE")"
source "${PLUGIN_ROOT}/hooks/scripts/common.sh"

TOOL_INFO=$(cat)
TOOL_NAME=$(echo "$TOOL_INFO" | jq -er '.tool_name // empty' 2>/dev/null) || {
    echo "$TOOL_INFO"; exit 0
}

# Fail open if omnimarket node is not installed in this Python environment
if ! $PYTHON_CMD -c \
    "import omnimarket.nodes.node_dispatch_enforcement.cli_shim" 2>/dev/null; then
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] [$_OMNICLAUDE_HOOK_NAME] WARN: omnimarket not installed; failing open for $TOOL_NAME" >> "$LOG_FILE"
    echo "$TOOL_INFO"; exit 0
fi

set +e
SHIM_OUTPUT=$(echo "$TOOL_INFO" | \
    CLAUDE_PLUGIN_ROOT="$PLUGIN_ROOT" \
    CLAUDE_PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}" \
    $PYTHON_CMD -m omnimarket.nodes.node_dispatch_enforcement.cli_shim 2>>"$LOG_FILE")
SHIM_EXIT=$?
set -e

if [[ $SHIM_EXIT -eq 2 ]]; then
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] [$_OMNICLAUDE_HOOK_NAME] BLOCKED $TOOL_NAME" >> "$LOG_FILE"
    printf '\a' >&2
    echo "$SHIM_OUTPUT"
    trap - EXIT; exit 2
else
    echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] [$_OMNICLAUDE_HOOK_NAME] ALLOWED $TOOL_NAME" >> "$LOG_FILE"
    echo "$SHIM_OUTPUT"; exit 0
fi
```

```bash
chmod +x plugins/onex/hooks/scripts/pre_tool_use_foreground_enforcement.sh
```

**Step 2: Register in hooks.json**

In the `PreToolUse` array, insert before the `pre_tool_use_model_router` entry:

```json
{
  "matcher": "^(Bash|Read|Write|Edit|Grep|Glob)$",
  "hooks": [
    {
      "type": "command",
      "command": "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/pre_tool_use_foreground_enforcement.sh"
    }
  ]
}
```

**Step 3: Validate hooks.json**

```bash
jq . plugins/onex/hooks/hooks.json > /dev/null && echo "JSON valid"
jq '[.hooks.PreToolUse[] | select(.hooks[].command | contains("foreground_enforcement"))] | length' \
  plugins/onex/hooks/hooks.json
# Expected: 1
```

**Step 4: Deploy and proof-of-life**

```bash
claude plugin marketplace update omninode-tools \
  && claude plugin uninstall onex@omninode-tools \
  && claude plugin install onex@omninode-tools
```

**Unit-level hook-chain verification (no live session required):**

Use an env var override to force a known enforcement mode, then feed a synthetic payload to the shim directly. This avoids manual cache editing and makes the test deterministic:

```bash
# Set a known contract mode via env var (override, not cache mutation)
ONEX_DISPATCH_ENFORCEMENT_MODE=soft \
CLAUDE_PROJECT_DIR=/tmp/test-project \
CLAUDE_SESSION_ID=pol-test-$(date +%s) \
  echo '{"tool_name":"Bash","tool_input":{"command":"uv run pytest tests/ -v"},"session_id":"pol-test-1"}' \
  | python -m omnimarket.nodes.node_dispatch_enforcement.cli_shim
# Expected: exit 2 (soft mode, skill match found)

# Verify correlation: use a fixed session_id as the correlation key
ONEX_DISPATCH_ENFORCEMENT_MODE=advisory \
  echo '{"tool_name":"Bash","tool_input":{"command":"uv run pytest tests/ -v"},"session_id":"pol-test-2"}' \
  | python -m omnimarket.nodes.node_dispatch_enforcement.cli_shim
# Expected: exit 0, _enforcement_result.outcome == "fallback"
```

> Note: `ONEX_DISPATCH_ENFORCEMENT_MODE` overrides the `mode` field in `contract.yaml` for testing. The handler checks this env var before reading the contract. This is a test-only escape hatch — production mode is always set in `contract.yaml`.

In a live session: trigger a `Bash` call. Check the hook log:

```bash
grep "foreground_enforcement" "$ONEX_STATE_DIR/logs/hooks.log" | tail -3
```

Expected: `ALLOWED Bash` or `WARN: omnimarket not installed; failing open for Bash`.

**Hook-chain correlation:** The `session_id` field in the enforcement result is the correlation key linking hook logs to friction events. Use it (not timestamps) to trace a specific tool call through the chain:

```bash
SESSION_ID="pol-test-1"
grep "\"session_id\": \"$SESSION_ID\"" "$ONEX_STATE_DIR/friction/" -r
# Find all friction events for this session
```

**Step 5: Commit**

```bash
git add plugins/onex/hooks/scripts/pre_tool_use_foreground_enforcement.sh \
        plugins/onex/hooks/hooks.json
git commit -m "feat(enforcement): add thin shim hook for foreground dispatch enforcement"
```

**Step 6: Open omniclaude PR**

```bash
gh pr create \
  --title "feat(enforcement): add foreground dispatch enforcement hook shim" \
  --body "Adds pre_tool_use_foreground_enforcement.sh — a thin shim (~20 lines) calling omnimarket node_dispatch_enforcement.cli_shim. Fails open if omnimarket is not installed. All business logic is in omnimarket (see companion PR). Registers hook in hooks.json."
```

---

## Runtime Authority and Hook Precedence

This hook runs as a `PreToolUse` hook — it intercepts tool calls before they execute. Its position in the hook chain matters:

| Hook | Position | Purpose |
|------|----------|---------|
| `pre_tool_use_worktree_enforcement` | 1st | Prevents feature branches inside `omni_home/` (OMN-7018) |
| `pre_tool_use_bash_guard` | 2nd | Blocks destructive bash patterns (SOFT mode with flag-file override) |
| **`pre_tool_use_foreground_enforcement`** | **3rd** | **This hook: redirects foreground tool calls to background skills** |
| `pre_tool_use_model_router` | 4th | Routes tool calls to appropriate model variants |

**Authorization shim interaction:** This hook runs after the worktree enforcement hook and bash guard, but before model routing. If worktree enforcement blocks a tool call (exit 2), this hook never runs for that call.

**Dispatch guard interaction:** The dispatch guard (`UserPromptSubmit`) operates on prompts, not individual tool calls. This hook operates on tool calls. They are complementary, not overlapping.

**`_enforcement_result` tag lifecycle:** The `_fallback_event` / `_enforcement_result` key is an internal payload annotation added by `cli_shim.py` to the pass-through JSON in FALLBACK cases. It is consumed by PostToolUse hooks for friction recording. **It is removed before the payload leaves the hook chain** — the Claude Code runtime strips unknown keys from the tool input before executing the tool. Implementors: do not rely on this key being visible to the tool itself.

---

## Hard-Mode Auto-Dispatch Guard

Hard mode can optionally auto-dispatch `writing_skills` when a blocked tool call has no skill match. This is a **guarded path**, not a default behavior.

**Guards required before enabling hard-mode auto-dispatch:**

1. **Rate limiting**: Max 1 skill generation dispatch per session per tool pattern. Track in `$ONEX_STATE_DIR/enforcement/skill-gen-{session_id}.json`. If the session has already generated a skill for this tool pattern, emit friction and skip dispatch.
2. **Dedup check**: Before dispatching, check if a skill already exists (grep `plugins/onex/skills/*/SKILL.md` for the tool name) and if a PR is already open for skill generation (query `gh pr list --search "writing_skills {tool_name}"`). If either exists, emit friction and skip.
3. **Session-level suppression**: If the user has invoked `/authorize` or set `ONEX_UNSAFE_ALLOW_EDITS=1`, auto-dispatch is suppressed entirely — these signals indicate intentional foreground work.

These guards are validated before the `onex.cmd.omnimarket.skill-generation-requested.v1` event is emitted. Hard mode with auto-dispatch must be treated as a later, explicitly enabled path — not a consequence of setting `mode: hard` alone.

---

## Routing

```yaml
routing:
  strategy: plan-to-tickets + epic-team
  repos:
    - omnimarket   # Tasks 1–5
    - omniclaude   # Task 6
  reason: >
    Two-repo change: omnimarket owns all business logic (node, models, handler, tests).
    omniclaude owns the thin shim only. plan-to-tickets to create Linear tickets per task,
    then epic-team to dispatch in parallel across both repos.
```
