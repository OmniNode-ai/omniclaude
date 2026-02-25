# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Config loader with live-reload support.

Loads ``ModelLoggingConfig`` from a YAML file and watches for changes using
``watchfiles``. When the file changes, the config is reloaded and the
``PersonalityAdapter`` is updated — no service restart required.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Callable

import yaml

from omniclaude.nodes.node_personality_logging_effect.models.model_logging_config import (
    ModelLoggingConfig,
)
from omniclaude.nodes.node_personality_logging_effect.personality_adapter import (
    PersonalityAdapter,
    load_phrase_pack,
)

logger = logging.getLogger(__name__)


def load_config_from_yaml(path: Path) -> ModelLoggingConfig:
    """Load ``ModelLoggingConfig`` from a YAML file.

    Args:
        path: Path to the YAML configuration file.

    Returns:
        A validated ``ModelLoggingConfig`` instance.

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If the YAML is malformed or fails validation.
    """
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    raw: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"Config file must contain a YAML mapping: {path}")
    return ModelLoggingConfig.model_validate(raw)


def build_adapter_from_config(config: ModelLoggingConfig) -> PersonalityAdapter:
    """Build a ``PersonalityAdapter`` from a ``ModelLoggingConfig``.

    Loads any phrase packs listed in ``config.phrase_pack_paths`` and
    registers them with the adapter alongside the built-in profiles.

    Args:
        config: Active logging configuration.

    Returns:
        A ``PersonalityAdapter`` with all registered profiles.
    """
    extra_profiles = []
    for pack_path in config.phrase_pack_paths:
        try:
            profile = load_phrase_pack(pack_path)
            extra_profiles.append(profile)
            logger.info("Loaded phrase pack: %s (%s)", profile.name, pack_path)
        except Exception:
            logger.exception("Failed to load phrase pack: %s", pack_path)
    return PersonalityAdapter(extra_profiles=extra_profiles)


class LiveConfigLoader:
    """Watches a YAML config file and reloads on change.

    Usage::

        loader = LiveConfigLoader(path=Path("logging.yaml"))
        await loader.start()
        config = loader.config
        adapter = loader.adapter

    The loader fires an optional ``on_reload`` callback after each successful
    reload so dependents (e.g. sink instances) can be recreated.

    Args:
        path: Path to the YAML config file.
        on_reload: Optional async callback invoked after each reload
            with the new config and adapter.
    """

    def __init__(
        self,
        path: Path,
        on_reload: Callable[[ModelLoggingConfig, PersonalityAdapter], Any] | None = None,
    ) -> None:
        self._path = path
        self._on_reload = on_reload
        self._config: ModelLoggingConfig = ModelLoggingConfig()
        self._adapter: PersonalityAdapter = PersonalityAdapter()
        self._watcher_task: asyncio.Task[None] | None = None

    @property
    def config(self) -> ModelLoggingConfig:
        """Current active configuration."""
        return self._config

    @property
    def adapter(self) -> PersonalityAdapter:
        """Current active PersonalityAdapter."""
        return self._adapter

    async def start(self) -> None:
        """Load config immediately and start the file watcher."""
        await self._reload()
        self._watcher_task = asyncio.create_task(self._watch_loop())
        logger.info("LiveConfigLoader: watching %s", self._path)

    async def stop(self) -> None:
        """Cancel the file watcher."""
        if self._watcher_task is not None:
            self._watcher_task.cancel()
            try:
                await self._watcher_task
            except asyncio.CancelledError:
                pass
            self._watcher_task = None

    async def _reload(self) -> None:
        """Reload config from disk."""
        try:
            config = load_config_from_yaml(self._path)
            adapter = build_adapter_from_config(config)
            self._config = config
            self._adapter = adapter
            logger.info(
                "LiveConfigLoader: reloaded config (profile=%s)",
                config.personality_profile,
            )
            if self._on_reload is not None:
                result = self._on_reload(config, adapter)
                if asyncio.iscoroutine(result):
                    await result
        except Exception:
            logger.exception("LiveConfigLoader: reload failed, keeping previous config")

    async def _watch_loop(self) -> None:
        """Watch for file changes and reload on modification."""
        try:
            from watchfiles import awatch  # type: ignore[import-not-found]

            async for _ in awatch(str(self._path)):
                logger.info("LiveConfigLoader: detected change in %s", self._path)
                await self._reload()
        except asyncio.CancelledError:
            raise
        except ImportError:
            logger.warning(
                "LiveConfigLoader: watchfiles not installed; live reload disabled"
            )
        except Exception:
            logger.exception("LiveConfigLoader: watcher loop exited unexpectedly")


__all__ = [
    "LiveConfigLoader",
    "build_adapter_from_config",
    "load_config_from_yaml",
]
