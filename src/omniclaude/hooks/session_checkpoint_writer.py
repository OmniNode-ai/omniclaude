# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Session checkpoint writer for limit-aware session continuity.

Persists ``ModelSessionCheckpoint`` to ``.onex_state/orchestrator/checkpoint.yaml``
using atomic writes (tmp + rename). The external CAIA watchdog process monitors
this file to resume work after limits reset.

Follows the same atomic-write pattern as ``PipelineCheckpointManager.save()``
in ``pipeline_checkpoint.py``.

See Also:
    - ``model_session_checkpoint.py`` for the data model (OMN-7283)
    - ``caia-watchdog.sh`` for the consumer of these checkpoint files (OMN-7288)
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import yaml

from omniclaude.hooks.model_session_checkpoint import ModelSessionCheckpoint

logger = logging.getLogger(__name__)

_DEFAULT_STATE_DIR = ".onex_state"
_SUBDIR = "orchestrator"
_CHECKPOINT_FILENAME = "checkpoint.yaml"


class SessionCheckpointWriter:
    """Writes and reads session checkpoints to .onex_state/orchestrator/.

    The checkpoint file signals the external watchdog process that a session
    has been gracefully wound down and provides the resume prompt and reset
    timestamp for relaunching.

    Args:
        state_dir: Root state directory. Defaults to ``ONEX_STATE_DIR`` env
            var, or ``.onex_state`` if not set.
    """

    def __init__(self, state_dir: Path | None = None) -> None:
        if state_dir is not None:
            self._state_dir = state_dir
        else:
            env_dir = os.getenv("ONEX_STATE_DIR")
            self._state_dir = Path(env_dir) if env_dir else Path(_DEFAULT_STATE_DIR)

    @property
    def checkpoint_path(self) -> Path:
        """Return the path to the checkpoint file."""
        return self._state_dir / _SUBDIR / _CHECKPOINT_FILENAME

    def write(self, checkpoint: ModelSessionCheckpoint) -> Path:
        """Atomic write checkpoint to disk.

        Writes to a temporary file first, then renames to the final path.
        This ensures the watchdog never reads a partial file.

        Args:
            checkpoint: The session checkpoint to persist.

        Returns:
            Path to the written checkpoint file.
        """
        path = self.checkpoint_path
        path.parent.mkdir(parents=True, exist_ok=True)

        tmp_path = path.with_suffix(".yaml.tmp")
        data = checkpoint.model_dump(mode="json")
        tmp_path.write_text(
            yaml.dump(data, default_flow_style=False, sort_keys=False),
            encoding="utf-8",
        )
        tmp_path.rename(path)

        logger.info("Session checkpoint written: %s", path)
        return path

    def read(self) -> ModelSessionCheckpoint | None:
        """Read checkpoint from disk.

        Returns:
            The loaded checkpoint, or None if missing or corrupt.
        """
        path = self.checkpoint_path
        if not path.exists():
            return None

        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            return ModelSessionCheckpoint.model_validate(data)
        except (yaml.YAMLError, ValueError, TypeError, OSError) as exc:
            logger.warning("Failed to load session checkpoint %s: %s", path, exc)
            return None

    def clear(self) -> None:
        """Remove checkpoint file after successful resume."""
        path = self.checkpoint_path
        if path.exists():
            path.unlink()
            logger.info("Session checkpoint cleared: %s", path)


__all__ = ["SessionCheckpointWriter"]
