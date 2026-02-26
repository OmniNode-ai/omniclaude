# _lib/run-state/helpers.md

**Shared state persistence helpers for long-running skills.**

Used by `/integration-gate`, `/release`, and other skills that need to persist
run state across interruptions and resumptions.

## Import

```
@_lib/run-state/helpers.md
```

---

## generate_run_id(prefix)

Generate a unique run identifier.

```python
import hashlib
from datetime import datetime, timezone


def generate_run_id(prefix: str = "run") -> str:
    """Generate a unique run identifier.

    Format: <prefix>-<YYYYMMDD>-<HHMMSS>-<short_hash>
    where short_hash = sha256(prefix + timestamp)[:6]

    Args:
        prefix: Skill name prefix (e.g., "integration-gate", "release").

    Returns:
        Unique run ID string.

    Examples:
        >>> generate_run_id("integration-gate")
        'integration-gate-20260226-143012-a3f7b2'
        >>> generate_run_id("release")
        'release-20260226-143012-c5e1d0'
    """
    now = datetime.now(timezone.utc)
    timestamp = now.strftime("%Y%m%d-%H%M%S")
    raw = f"{prefix}-{timestamp}-{now.isoformat()}"
    short_hash = hashlib.sha256(raw.encode()).hexdigest()[:6]
    return f"{prefix}-{timestamp}-{short_hash}"
```

---

## state_path(run_id, skill_name)

Return the canonical path for a run state file.

```python
from pathlib import Path


def state_path(run_id: str, skill_name: str) -> Path:
    """Return the canonical path for a skill run state file.

    State files are written to: ~/.claude/state/<skill_name>/<run_id>.json

    Args:
        run_id: The run identifier.
        skill_name: The skill name (e.g., "integration-gate").

    Returns:
        Path to the state file.

    Raises:
        ValueError: If run_id contains path traversal characters.
    """
    if not run_id or "/" in run_id or ".." in run_id:
        raise ValueError(f"state_path: invalid run_id '{run_id}'")
    return Path("~/.claude/state").expanduser() / skill_name / f"{run_id}.json"
```

---

## atomic_write(target_path, content, dry_run)

Write content to target_path atomically (tmp + fsync + rename).

```python
import os
import tempfile


class DryRunWriteError(Exception):
    """Raised when atomic_write() is called in dry_run mode."""
    def __init__(self, target_path: Path):
        self.target_path = target_path
        super().__init__(
            f"DryRunWriteError: atomic_write() called for '{target_path}' in dry_run mode."
        )


def atomic_write(target_path: Path, content: str, dry_run: bool = False) -> None:
    """Write content to target_path atomically using tmp + fsync + rename.

    Args:
        target_path: Destination file path.
        content: String content to write.
        dry_run: If True, raises DryRunWriteError immediately.

    Raises:
        DryRunWriteError: If dry_run is True.
        OSError: If the write or rename fails.
    """
    if dry_run:
        raise DryRunWriteError(target_path)

    target_path = Path(target_path)
    target_path.parent.mkdir(parents=True, exist_ok=True)

    tmp_fd, tmp_path = tempfile.mkstemp(
        dir=target_path.parent,
        prefix=".tmp.",
        suffix=".json",
    )
    try:
        with os.fdopen(tmp_fd, "w") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.rename(tmp_path, target_path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
```

---

## save_state(run_id, skill_name, state, dry_run)

Persist run state to disk.

```python
import json


def save_state(
    run_id: str,
    skill_name: str,
    state: dict,
    dry_run: bool = False,
) -> Path:
    """Persist run state to disk via atomic write.

    State file includes a metadata header with run_id, skill_name,
    and last_updated timestamp.

    Args:
        run_id: The run identifier.
        skill_name: The skill name.
        state: State dictionary to persist.
        dry_run: If True, raises DryRunWriteError.

    Returns:
        Path to the written state file.

    Raises:
        DryRunWriteError: If dry_run is True.
    """
    path = state_path(run_id, skill_name)
    payload = {
        "_meta": {
            "run_id": run_id,
            "skill_name": skill_name,
            "last_updated": datetime.now(timezone.utc).isoformat(),
        },
        **state,
    }
    atomic_write(path, json.dumps(payload, indent=2), dry_run=dry_run)
    return path
```

---

## load_state(run_id, skill_name)

Load run state from disk.

```python
def load_state(run_id: str, skill_name: str) -> dict | None:
    """Load run state from disk.

    Args:
        run_id: The run identifier.
        skill_name: The skill name.

    Returns:
        State dictionary if file exists and is valid JSON, else None.
    """
    path = state_path(run_id, skill_name)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None
```

---

## Usage Pattern

```python
# In a long-running skill:
run_id = generate_run_id("integration-gate")

# Save state at checkpoints
save_state(run_id, "integration-gate", {
    "phase": "enqueue",
    "enqueued": ["omniclaude#300", "omnibase_core#88"],
    "pending": ["omnibase_infra#42"],
})

# Resume from saved state
state = load_state(run_id, "integration-gate")
if state:
    phase = state.get("phase")
    enqueued = state.get("enqueued", [])
    # Continue from last checkpoint
```
