# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Secure and mint on the broker onboarding runs, through its declared targets."""

from __future__ import annotations

import os
import random
import signal
import subprocess
import time
from pathlib import Path

import yaml
from pydantic import AnyHttpUrl, TypeAdapter

from omniclaude.nodes.node_skill_omninode_dev_setup_orchestrator.models.model_onboarding_bus_identity_request import (
    ModelOnboardingBusIdentityRequest,
)
from omniclaude.nodes.node_skill_omninode_dev_setup_orchestrator.models.model_onboarding_bus_identity_result import (
    ModelOnboardingBusIdentityResult,
)


class HandlerOnboardingBusIdentity:
    """Keep security repair before delegation, and mint after it, in both paths."""

    def handle(
        self, request: ModelOnboardingBusIdentityRequest
    ) -> ModelOnboardingBusIdentityResult:
        if not (Path(request.workspace) / "omnibase_infra").is_dir():
            return self._failure("workspace", 2, 0)
        if request.mode != "mint":
            rc, _ = self._make(request, "check-sasl-local")
            rebuilt = rc != 0
            if rc in (124, 127):
                return self._failure("check-sasl-local", rc, 1)
            if rebuilt:
                for attempt in range(1, request.retries + 1):
                    rc, _ = self._make(request, "up-local", nice=True)
                    if rc == 0:
                        break
                    if rc in (124, 127) or attempt == request.retries:
                        return self._failure("up-local", rc, attempt)
                    time.sleep(random.SystemRandom().randint(5, 10))
                if request.mode == "resume":
                    failure = self._wait_healthy(request)
                    if failure is not None:
                        return failure
        if request.mode != "secure":
            # A busy/refused mint is one call. Retrying could hide the refusal.
            rc, _ = self._make(request, "mint-local")
            if rc:
                return self._failure("mint-local", rc, 1)
        return ModelOnboardingBusIdentityResult(success=True)

    @staticmethod
    def _failure(
        target: str, rc: int, attempts: int
    ) -> ModelOnboardingBusIdentityResult:
        if target == "workspace":
            next_step = "check the selected workspace and dispatch Python installation"
        elif target == "health-contract":
            next_step = "restore the onboarding node contract health URLs, then rerun onboarding"
        else:
            next_step = (
                f"run 'make {target}' in omnibase_infra, then run onboarding again"
            )
        return ModelOnboardingBusIdentityResult(
            success=False,
            failed_step=target,
            returncode=rc,
            attempts=attempts,
            reason=f"{target} failed with status {rc}",
            next_step=next_step,
        )

    @staticmethod
    def _execute(
        request: ModelOnboardingBusIdentityRequest,
        argv: list[str],
        *,
        capture: bool = False,
        timeout: float | None = None,
    ) -> tuple[int, str]:
        try:
            with Path(request.log_path).open("a") as log:
                process = subprocess.Popen(
                    argv,
                    stdout=subprocess.PIPE if capture else log,
                    stderr=log,
                    text=True,
                    errors="replace",
                    start_new_session=True,
                )
                try:
                    output, _ = process.communicate(
                        timeout=timeout or request.command_timeout_seconds
                    )
                except subprocess.TimeoutExpired:
                    # End the command's children too; a timed-out boot never
                    # overlaps a retry or a later mint.
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    process.communicate()
                    return 124, ""
                return process.returncode, output or ""
        except OSError:
            return 127, ""

    def _make(
        self,
        request: ModelOnboardingBusIdentityRequest,
        target: str,
        *,
        nice: bool = False,
        capture: bool = False,
        timeout: float | None = None,
    ) -> tuple[int, str]:
        argv = ["make", "-C", str(Path(request.workspace) / "omnibase_infra"), target]
        if nice:
            argv = ["nice", "-n", "10", *argv]
        return self._execute(request, argv, capture=capture, timeout=timeout)

    def _wait_healthy(
        self, request: ModelOnboardingBusIdentityRequest
    ) -> ModelOnboardingBusIdentityResult | None:
        try:
            document = yaml.safe_load(
                Path(__file__).with_name("contract.yaml").read_text()
            )
            health_urls = TypeAdapter(tuple[AnyHttpUrl, AnyHttpUrl]).validate_python(
                document["config"]["onboarding_bus_identity"]["health_urls"]
            )
        except (OSError, KeyError, TypeError, ValueError, yaml.YAMLError):
            return self._failure("health-contract", 2, 0)
        deadline = time.monotonic() + request.health_timeout_seconds
        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            rc, status = self._make(
                request, "status-local", capture=True, timeout=min(30, remaining)
            )
            if rc in (124, 127):
                return self._failure("status-local", rc, 1)
            healthy = rc == 0 and "migration-gate: healthy" in status
            if healthy:
                for health_url in health_urls:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        return self._failure("status-local", 124, 1)
                    rc, body = self._execute(
                        request,
                        ["curl", "-fsS", "-m", "5", str(health_url)],
                        capture=True,
                        timeout=min(10, remaining),
                    )
                    if rc in (124, 127):
                        return self._failure("status-local", rc, 1)
                    if rc or '"healthy"' not in body:
                        healthy = False
                        break
            if healthy:
                return None
            time.sleep(min(15, max(0, deadline - time.monotonic())))
        return self._failure("status-local", 124, 1)
