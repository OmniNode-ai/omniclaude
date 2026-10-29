# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Read onboarding models and preserve user YAML while placing a local route."""

from __future__ import annotations

from pathlib import Path

import yaml

from omniclaude.nodes.node_skill_omninode_dev_setup_orchestrator.models.model_onboarding_model_config_request import (
    ModelOnboardingModelConfigRequest,
)
from omniclaude.nodes.node_skill_omninode_dev_setup_orchestrator.models.model_onboarding_model_config_result import (
    ModelOnboardingModelConfigResult,
)


class HandlerOnboardingModelConfig:
    """Own model configuration file reads and the atomic placement write."""

    def handle(
        self, request: ModelOnboardingModelConfigRequest
    ) -> ModelOnboardingModelConfigResult:
        """Perform the requested operation on the selected configuration file."""
        path = Path(request.path)
        if request.operation == "ollama_config":
            return ModelOnboardingModelConfigResult(output=self._ollama_config(request))
        if request.operation == "local_url_endpoint":
            data = yaml.safe_load(path.read_text()) or {}
            for backend in data.get("backends") or []:
                if (
                    isinstance(backend, dict)
                    and backend.get("backend_id") == "local-url"
                ):
                    return ModelOnboardingModelConfigResult(
                        output=backend["endpoint_url"]
                    )
            raise ValueError("no local-url backend in " + str(path))
        self._place_local_url(path)
        return ModelOnboardingModelConfigResult()

    @staticmethod
    def _ollama_config(request: ModelOnboardingModelConfigRequest) -> str:
        block = (yaml.safe_load(Path(request.path).read_text()) or {}).get(
            "ollama"
        ) or {}
        port, chat_path = block.get("port"), block.get("chat_path")
        models = block.get("models") or []
        if not port or not chat_path or not models:
            raise ValueError(
                "the model config has no complete ollama block (port, chat_path, models)"
            )
        models = sorted(
            models, key=lambda model: int(model["min_memory_gb"]), reverse=True
        )
        local: list[dict[str, str | int | float]] = []
        if request.catalogue_path and Path(request.catalogue_path).is_file():
            catalogue = yaml.safe_load(Path(request.catalogue_path).read_text()) or {}
            local = (catalogue.get("local") or {}).get("memory_classes") or []
        if request.model:
            size = next(
                (
                    m["download_gb"]
                    for m in [*models, *local]
                    if m["model"] == request.model
                ),
                max(m["download_gb"] for m in models),
            )
            return f"{port} {chat_path} {request.model} {size}"
        pick = next(
            (m for m in models if int(m["min_memory_gb"]) <= request.ram_gb), models[-1]
        )
        return f"{port} {chat_path} {pick['model']} {pick['download_gb']}"

    @staticmethod
    def _place_local_url(path: Path) -> None:
        text = path.read_text()
        data = yaml.safe_load(text)
        entry = next(b for b in data["backends"] if b.get("backend_id") == "local-url")
        if "placement" in entry:
            return
        placement = {
            "tier": "local",
            "fallback_for": ["local-coder", "local-heavy-reasoning"],
            "max_context_tokens": 8192,
        }
        # Source marks preserve comments and every unrelated route. Refuse a
        # layout that cannot accept the insertion before replacing any bytes.
        node = yaml.compose(text)
        if not isinstance(node, yaml.MappingNode):
            raise ValueError("expected a model configuration mapping in " + str(path))
        backends = next(value for key, value in node.value if key.value == "backends")
        item = next(
            item
            for item in backends.value
            if any(
                key.value == "backend_id" and value.value == "local-url"
                for key, value in item.value
            )
        )
        key, value = next(
            (key, value) for key, value in item.value if key.value == "backend_id"
        )
        lines = text.splitlines(keepends=True)
        block = yaml.safe_dump({"placement": placement}, sort_keys=False)
        lines.insert(
            value.end_mark.line + 1,
            "".join(
                " " * key.start_mark.column + line + "\n" for line in block.splitlines()
            ),
        )
        written = "".join(lines)
        entry["placement"] = placement
        if yaml.safe_load(written) != data:
            raise ValueError(
                "cannot place local-url without changing other routes; check "
                + str(path)
            )
        tmp = path.with_suffix(".tmp")
        tmp.write_text(written)
        tmp.replace(path)
