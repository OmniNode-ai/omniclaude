# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Typed contract-level fake for the skill-dispatch ``task_dispatcher`` seam.

``handle_skill_requested`` (``omniclaude.shared.handler_skill_requested``) depends
on an injected ``task_dispatcher`` matching the real contract::

    TaskDispatcher = Callable[[str], Awaitable[str]]

In production (``omniclaude.runtime.wiring_dispatchers``) that callable is a thin
closure that forwards the constructed prompt to a *concrete* inference backend —
either a caller-injected, duck-typed ``session_query`` backend (claude_code; no
in-repo implementation ships since OMN-15960 deleted the duplicate,
never-deployed ``node_claude_code_session_effect``) or ``VllmInferenceBackend.infer``
(local_llm) — and returns the backend's raw output string. The ``task_dispatcher``
itself is therefore a *contract seam* one level ABOVE the inference client, NOT the
HTTP inference boundary.

Why a typed fake here and NOT ``RecordedReplayInferenceTransport``
-----------------------------------------------------------------
The canonical recorded-replay harness (OMN-13499,
``omnibase_core.runtime.golden_chain.RecordedReplayInferenceTransport``) is an
``httpx.Client``-shaped transport: it intercepts a live ``post(url, json=payload)``
and replays recorded model *response bytes* only when the live-constructed request
hash matches a recorded fixture. It cannot be injected as a
``Callable[[str], Awaitable[str]]`` and there is NO ``httpx`` boundary inside
``handle_skill_requested`` to intercept — that boundary lives deep inside
``vllm_backend.infer`` / ``cc_backend.session_query``, which this shared-handler
unit test deliberately does not exercise. The recorded-replay harness is the right
tool for the vLLM httpx egress (cluster C4, ``test_backend_vllm_tools.py``), not
for this prompt-construction + RESULT-block-parsing unit.

Additionally, the scenarios this handler test covers are *synthetic parser
vectors* — a missing ``RESULT:`` block, an unrecognized ``status:`` value, trailing
noise after a blank line — that a live model cannot be made to emit deterministically
on demand, so ``OMN_RECORD_GOLDEN=1`` recording is not meaningful for them. They are
hand-authored contract fixtures for the parser, provenance-labeled as such.

``FakeTaskDispatcher`` implements the real ``TaskDispatcher`` call surface as an
ordinary object with a real ``async def __call__(self, prompt: str) -> str``:

* returns the configured ``output`` string (a parser test-vector), or
* raises the configured ``error`` — a real backend-shaped failure exercised through
  real ``__call__`` execution, mirroring the inference backend raising on e.g. a
  refused connection (replaces ``AsyncMock(side_effect=...)`` ad-hoc raising), and
* records every dispatched prompt on ``prompts`` so tests can assert on prompt
  construction without a mock spy (``last_prompt``, ``await_count``).

Because it is a real awaitable object (not an ``AsyncMock`` assigned to the dispatch
boundary), it satisfies the ``no_faked_boundary`` detector's
``mock_assigned_to_boundary`` rule (OMN-13500, cluster C2).
"""

from __future__ import annotations


class FakeTaskDispatcher:
    """Real, typed test double for the ``task_dispatcher`` seam.

    Attributes:
        output: Raw output string returned by ``__call__`` (a parser test-vector
            standing in for the backend's raw output text).
        error: If set, ``__call__`` raises this after recording the prompt,
            standing in for a real inference-backend failure.
        prompts: Every prompt string ``__call__`` was awaited with, in order.
    """

    def __init__(
        self,
        *,
        output: str = "",
        error: BaseException | None = None,
    ) -> None:
        self.output: str = output
        self.error: BaseException | None = error
        self.prompts: list[str] = []

    async def __call__(self, prompt: str) -> str:
        """Record the prompt then return ``output`` or raise ``error``.

        Matches the real ``TaskDispatcher = Callable[[str], Awaitable[str]]``
        contract that ``handle_skill_requested`` awaits.
        """
        self.prompts.append(prompt)
        if self.error is not None:
            raise self.error
        return self.output

    @property
    def await_count(self) -> int:
        """Number of times ``__call__`` has been awaited."""
        return len(self.prompts)

    @property
    def last_prompt(self) -> str:
        """The most recent prompt ``__call__`` was awaited with."""
        if not self.prompts:
            raise AssertionError("FakeTaskDispatcher was never awaited")
        return self.prompts[-1]


__all__ = ["FakeTaskDispatcher"]
