#!/usr/bin/env python3
"""PostToolUse Quality Enforcer - Auto-fix violations after file write."""

import asyncio
import sys
import time
from pathlib import Path
from typing import Dict, Optional

import yaml


# Define script directory
SCRIPT_DIR = Path(__file__).parent

# Add parent directory to sys.path for direct script execution
# This enables absolute imports when run as a standalone script
parent_dir = SCRIPT_DIR.parent
if str(parent_dir) not in sys.path:
    sys.path.insert(0, str(parent_dir))

# Import pattern tracker (supports both module and script execution)
try:
    # Try relative import first (when used as a module)
    from .lib.pattern_tracker_sync import PatternTrackerSync

    PATTERN_TRACKING_ENABLED = True
except ImportError:
    try:
        # Fall back to absolute import (when run as a script)
        from claude_hooks.lib.pattern_tracker_sync import PatternTrackerSync

        PATTERN_TRACKING_ENABLED = True
    except ImportError:
        # Pattern tracking unavailable
        PATTERN_TRACKING_ENABLED = False
        PatternTrackerSync = None


def load_config():
    """Load configuration from config.yaml."""
    config_path = SCRIPT_DIR / "config.yaml"
    with open(config_path, "r") as f:
        return yaml.safe_load(f)


def track_pattern_for_file(file_path: str, config: dict) -> bool:
    """
    Track pattern for a file independently of auto-fix.

    This runs FIRST, before auto-fix checks, to ensure pattern tracking
    happens even when auto-fix is disabled.

    Args:
        file_path: Path to file to track
        config: Configuration dict

    Returns:
        True if pattern tracking succeeded, False otherwise
    """
    file_path = Path(file_path)

    # Check if pattern tracking is enabled
    pattern_config = config.get("pattern_tracking", {})
    if not pattern_config.get("enabled", False):
        print("[PostToolUse] Pattern tracking: DISABLED in config", file=sys.stderr)
        return False

    # Check if pattern tracker is available
    if not PATTERN_TRACKING_ENABLED:
        print(
            "[PostToolUse] Pattern tracking: UNAVAILABLE (module not imported)",
            file=sys.stderr,
        )
        return False

    # Only process Python files
    if file_path.suffix != ".py":
        return False

    # Skip if file doesn't exist
    if not file_path.exists():
        print(
            f"[PostToolUse] Pattern tracking: File does not exist: {file_path}",
            file=sys.stderr,
        )
        return False

    print(f"[PostToolUse] Pattern tracking: Processing {file_path}", file=sys.stderr)

    # Initialize pattern tracker
    try:
        pattern_tracker = PatternTrackerSync()
        print(
            f"[PostToolUse] Pattern tracker: ENABLED (session: {pattern_tracker.session_id})",
            file=sys.stderr,
        )
    except Exception as e:
        print(f"[PostToolUse] Pattern tracker init failed: {e}", file=sys.stderr)
        return False

    # Determine language
    language_map = {".py": "python", ".ts": "typescript", ".js": "javascript"}
    language = language_map.get(file_path.suffix, "python")

    # Read content
    try:
        with open(file_path, "r") as f:
            content = f.read()
        print(
            f"[PostToolUse] Pattern tracking: Read {len(content)} chars",
            file=sys.stderr,
        )
    except Exception as e:
        print(
            f"[PostToolUse] Pattern tracking: Error reading file: {e}", file=sys.stderr
        )
        return False

    # Track pattern creation
    try:
        pattern_id = pattern_tracker.track_pattern_creation_sync(
            code=content,
            context={
                "event_type": "pattern_created",
                "tool": "Write",
                "language": language,
                "file_path": str(file_path),
                "session_id": pattern_tracker.session_id,
            },
        )
        if pattern_id:
            print(
                f"[PostToolUse] Pattern tracking: SUCCESS - {pattern_id}",
                file=sys.stderr,
            )
            return True
        else:
            print(
                "[PostToolUse] Pattern tracking: FAILED - returned None",
                file=sys.stderr,
            )
            return False
    except Exception as e:
        print(f"[PostToolUse] Pattern tracking: EXCEPTION - {e}", file=sys.stderr)
        if pattern_config.get("fail_gracefully", True):
            print(
                "[PostToolUse] Pattern tracking: Continuing despite failure",
                file=sys.stderr,
            )
            return False
        else:
            raise


def apply_correction(content: str, correction: Dict) -> str:
    """
    Apply a single correction to content using AST-based approach.

    This replaces the old regex-based approach that caused false positives
    by renaming framework methods (visit_FunctionDef, save, get, etc.).

    The AST corrector:
    - Preserves framework method contracts (AST visitors, Django, FastAPI, pytest)
    - Only renames at specific line/column violations
    - Preserves all formatting and comments
    - Falls back to regex if libcst unavailable

    Args:
        content: Original content
        correction: Correction dict with old_name, new_name, line, column

    Returns:
        Modified content with correction applied, or original on error
    """
    try:
        # Try relative imports first (when used as a module)
        try:
            from .lib.correction.ast_corrector import apply_single_correction
            from .lib.correction.framework_detector import FrameworkMethodDetector
        except ImportError:
            # Fall back to absolute imports (when run as a script)
            from claude_hooks.lib.correction.ast_corrector import (
                apply_single_correction,
            )
            from claude_hooks.lib.correction.framework_detector import (
                FrameworkMethodDetector,
            )

        # Create framework detector
        detector = FrameworkMethodDetector()

        # Apply AST-based correction
        corrected = apply_single_correction(content, correction, detector)

        # Return corrected content or original on error
        return corrected if corrected is not None else content

    except Exception as e:
        print(f"[PostToolUse] AST correction failed: {e}", file=sys.stderr)
        print("[PostToolUse] Falling back to original content", file=sys.stderr)
        return content


async def apply_fixes_to_file_async(file_path: str, config: dict) -> bool:
    """
    Apply naming convention fixes to a file (async version).

    Args:
        file_path: Path to file to fix
        config: Configuration dict

    Returns:
        True if fixes were applied, False otherwise
    """
    start_time = time.time()
    file_path = Path(file_path)

    print(f"[PostToolUse] ===== START processing {file_path} =====", file=sys.stderr)

    # Only process Python files
    if file_path.suffix != ".py":
        print(f"[PostToolUse] Skipping non-Python file: {file_path}", file=sys.stderr)
        return False

    # Skip if file doesn't exist
    if not file_path.exists():
        print(f"[PostToolUse] File does not exist: {file_path}", file=sys.stderr)
        return False

    # Initialize pattern tracker if enabled
    pattern_tracker: Optional[PatternTrackerSync] = None
    if PATTERN_TRACKING_ENABLED:
        try:
            pattern_tracker = PatternTrackerSync()
            print(
                f"[PostToolUse] Pattern tracker: ENABLED (session: {pattern_tracker.session_id})",
                file=sys.stderr,
            )
        except Exception as e:
            print(f"[PostToolUse] Pattern tracker init failed: {e}", file=sys.stderr)
            pattern_tracker = None
    else:
        print("[PostToolUse] Pattern tracker: DISABLED", file=sys.stderr)

    # Determine language from file extension
    language_map = {".py": "python", ".ts": "typescript", ".js": "javascript"}
    language = language_map.get(file_path.suffix, "python")

    # Read current content
    try:
        with open(file_path, "r") as f:
            original_content = f.read()
        print(
            f"[PostToolUse] Read {len(original_content)} chars from {file_path}",
            file=sys.stderr,
        )
    except Exception as e:
        print(f"[PostToolUse] Error reading {file_path}: {e}", file=sys.stderr)
        return False

    # Track original pattern creation (synchronous, blocking)
    if pattern_tracker:
        print(
            "[PostToolUse] Attempting pattern tracking (original)...", file=sys.stderr
        )
        try:
            pattern_id = pattern_tracker.track_pattern_creation(
                code=original_content,
                context={
                    "event_type": "pattern_created",
                    "tool": "Write",
                    "language": language,
                    "file_path": str(file_path),
                    "session_id": pattern_tracker.session_id,
                },
            )
            if pattern_id:
                print(
                    f"[PostToolUse] Pattern tracking complete: {pattern_id}",
                    file=sys.stderr,
                )
            else:
                print(
                    "[PostToolUse] Pattern tracking returned None (check errors above)",
                    file=sys.stderr,
                )
        except Exception as e:
            print(f"[PostToolUse] Pattern tracking exception: {e}", file=sys.stderr)

    # Phase 1: Validate
    print("[PostToolUse] Starting validation...", file=sys.stderr)
    from validators.naming_validator import NamingValidator

    validator = NamingValidator()
    violations = validator.validate_content(original_content, str(file_path))

    if not violations:
        print("[PostToolUse] No violations found ✓", file=sys.stderr)
        elapsed_ms = (time.time() - start_time) * 1000
        print(
            f"[PostToolUse] Total processing time: {elapsed_ms:.1f}ms", file=sys.stderr
        )
        print(
            f"[PostToolUse] ===== END processing {file_path} (clean) =====",
            file=sys.stderr,
        )
        return False

    print(f"[PostToolUse] Found {len(violations)} violation(s):", file=sys.stderr)
    for v in violations[:3]:  # Show first 3
        print(
            f"  - {v.get('old_name', 'unknown')} (line {v.get('line', '?')})",
            file=sys.stderr,
        )
    if len(violations) > 3:
        print(f"  ... and {len(violations) - 3} more", file=sys.stderr)

    # Track pattern with violations context (synchronous)
    if pattern_tracker:
        print(
            "[PostToolUse] Attempting pattern tracking (violations)...", file=sys.stderr
        )
        try:
            quality_score = pattern_tracker.calculate_quality_score(violations)
            pattern_id = pattern_tracker.track_pattern_creation(
                code=original_content,
                context={
                    "event_type": "pattern_created",
                    "tool": "Write",
                    "language": language,
                    "file_path": str(file_path),
                    "session_id": pattern_tracker.session_id,
                    "violations_found": len(violations),
                    "quality_score": quality_score,
                    "reason": f"Code with {len(violations)} naming violations",
                },
            )
            if pattern_id:
                print(
                    f"[PostToolUse] Pattern tracking complete (quality: {quality_score:.2f})",
                    file=sys.stderr,
                )
        except Exception as e:
            print(
                f"[PostToolUse] Pattern tracking (violations) failed: {e}",
                file=sys.stderr,
            )

    # Phase 2: Generate corrections
    print("[PostToolUse] Generating corrections...", file=sys.stderr)

    # Import generator (supports both module and script execution)
    try:
        from .lib.correction.generator import CorrectionGenerator
    except ImportError:
        from claude_hooks.lib.correction.generator import CorrectionGenerator

    generator = CorrectionGenerator()

    corrections = await generator.generate_corrections(
        violations, original_content, str(file_path), language
    )

    if not corrections:
        print("[PostToolUse] No corrections generated", file=sys.stderr)
        elapsed_ms = (time.time() - start_time) * 1000
        print(
            f"[PostToolUse] Total processing time: {elapsed_ms:.1f}ms", file=sys.stderr
        )
        print(
            f"[PostToolUse] ===== END processing {file_path} (no corrections) =====",
            file=sys.stderr,
        )
        return False

    print(f"[PostToolUse] Generated {len(corrections)} correction(s)", file=sys.stderr)

    # Phase 3 & 4: AI Quorum (if enabled)
    quorum_enabled = config.get("quorum", {}).get("enabled", False)

    if quorum_enabled:
        print(f"[PostToolUse] Running AI Quorum for {len(corrections)} correction(s)")

        # Import quorum (supports both module and script execution)
        try:
            from .lib.consensus.quorum import AIQuorum
        except ImportError:
            from claude_hooks.lib.consensus.quorum import AIQuorum

        quorum = AIQuorum()  # AIQuorum loads config internally

        scored_corrections = []
        for correction in corrections:
            score = await quorum.score_correction(
                correction, original_content, str(file_path)
            )
            if score.should_apply:
                scored_corrections.append((correction, score))
                print(
                    f"[PostToolUse] ✓ {correction['old_name']} → {correction['new_name']} (score: {score.consensus_score:.2f})"
                )
            else:
                print(
                    f"[PostToolUse] ✗ {correction['old_name']} → {correction['new_name']} (score: {score.consensus_score:.2f}, below threshold)"
                )

        corrections = [c for c, s in scored_corrections]

    if not corrections:
        print("[PostToolUse] No corrections passed threshold", file=sys.stderr)
        elapsed_ms = (time.time() - start_time) * 1000
        print(
            f"[PostToolUse] Total processing time: {elapsed_ms:.1f}ms", file=sys.stderr
        )
        print(
            f"[PostToolUse] ===== END processing {file_path} (no passing corrections) =====",
            file=sys.stderr,
        )
        return False

    # Phase 5: Apply corrections
    print(
        f"[PostToolUse] Applying {len(corrections)} correction(s)...", file=sys.stderr
    )
    corrected_content = original_content
    for correction in corrections:
        corrected_content = apply_correction(corrected_content, correction)

    if corrected_content == original_content:
        print("[PostToolUse] No changes after correction attempt", file=sys.stderr)
        elapsed_ms = (time.time() - start_time) * 1000
        print(
            f"[PostToolUse] Total processing time: {elapsed_ms:.1f}ms", file=sys.stderr
        )
        print(
            f"[PostToolUse] ===== END processing {file_path} (no changes) =====",
            file=sys.stderr,
        )
        return False

    print(
        f"[PostToolUse] Applied corrections, {len(corrected_content)} chars",
        file=sys.stderr,
    )

    # Write corrected content back to file
    try:
        with open(file_path, "w") as f:
            f.write(corrected_content)
        print(
            f"[PostToolUse] ✓ Applied {len(corrections)} correction(s) to {file_path}"
        )

        # Track corrected pattern as modified version (synchronous)
        if pattern_tracker:
            print(
                "[PostToolUse] Attempting pattern tracking (corrected)...",
                file=sys.stderr,
            )
            try:
                corrected_quality_score = (
                    1.0  # After corrections, quality should be perfect
                )
                corrected_pattern_id = pattern_tracker.track_pattern_creation(
                    code=corrected_content,
                    context={
                        "event_type": "pattern_modified",
                        "tool": "Edit",
                        "language": language,
                        "file_path": str(file_path),
                        "session_id": pattern_tracker.session_id,
                        "violations_found": 0,
                        "corrections_applied": len(corrections),
                        "quality_score": corrected_quality_score,
                        "transformation_type": "quality_improvement",
                        "reason": f"Applied {len(corrections)} naming corrections",
                    },
                )
                if corrected_pattern_id:
                    print(
                        "[PostToolUse] Pattern tracking complete (corrected)",
                        file=sys.stderr,
                    )
            except Exception as e:
                print(
                    f"[PostToolUse] Corrected pattern tracking failed: {e}",
                    file=sys.stderr,
                )

        elapsed_ms = (time.time() - start_time) * 1000
        print(
            f"[PostToolUse] Total processing time: {elapsed_ms:.1f}ms", file=sys.stderr
        )
        print(
            f"[PostToolUse] ===== END processing {file_path} (success) =====",
            file=sys.stderr,
        )
        return True
    except Exception as e:
        print(f"[PostToolUse] Error writing {file_path}: {e}", file=sys.stderr)
        return False


def apply_fixes_to_file(file_path: str, config: dict) -> bool:
    """Synchronous wrapper for async apply_fixes_to_file_async."""
    return asyncio.run(apply_fixes_to_file_async(file_path, config))


def main():
    """Main entry point for PostToolUse enforcer."""
    print("[PostToolUse] ===== HOOK STARTED =====", file=sys.stderr)

    if len(sys.argv) < 2:
        print("[PostToolUse] No file paths provided", file=sys.stderr)
        sys.exit(1)

    # Get file paths (could be comma-separated or multiple args)
    file_paths_str = sys.argv[1]
    file_paths = [p.strip() for p in file_paths_str.split(",")]
    print(f"[PostToolUse] Processing {len(file_paths)} file(s)", file=sys.stderr)

    # Load config
    try:
        config = load_config()
        print("[PostToolUse] Configuration loaded:", file=sys.stderr)
        print(
            f"  - PostToolUse enabled: {config.get('enforcement', {}).get('post_tool_use_enabled', True)}",
            file=sys.stderr,
        )
        print(
            f"  - Pattern tracking enabled: {config.get('pattern_tracking', {}).get('enabled', False)}",
            file=sys.stderr,
        )
        print(
            f"  - Pattern tracking available: {PATTERN_TRACKING_ENABLED}",
            file=sys.stderr,
        )
        print(
            f"  - Quorum enabled: {config.get('quorum', {}).get('enabled', False)}",
            file=sys.stderr,
        )
    except Exception as e:
        print(f"[PostToolUse] Error loading config: {e}", file=sys.stderr)
        sys.exit(1)

    # PHASE 1: Pattern tracking (runs independently, before auto-fix check)
    pattern_tracking_enabled = config.get("pattern_tracking", {}).get("enabled", False)
    if pattern_tracking_enabled:
        print("[PostToolUse] === PHASE 1: Pattern Tracking ===", file=sys.stderr)
        patterns_tracked = 0
        for file_path in file_paths:
            if track_pattern_for_file(file_path, config):
                patterns_tracked += 1
        print(
            f"[PostToolUse] Pattern tracking: {patterns_tracked}/{len(file_paths)} file(s) tracked",
            file=sys.stderr,
        )
    else:
        print(
            "[PostToolUse] Pattern tracking: SKIPPED (disabled in config)",
            file=sys.stderr,
        )

    # PHASE 2: Auto-fix (only if enabled)
    auto_fix_enabled = config.get("enforcement", {}).get("post_tool_use_enabled", True)
    if not auto_fix_enabled:
        print("[PostToolUse] === PHASE 2: Auto-fix ===", file=sys.stderr)
        print("[PostToolUse] Auto-fix: SKIPPED (disabled in config)", file=sys.stderr)
        print("[PostToolUse] ===== HOOK COMPLETED =====", file=sys.stderr)
        sys.exit(0)

    print("[PostToolUse] === PHASE 2: Auto-fix ===", file=sys.stderr)
    # Process each file for auto-fix
    fixes_applied = 0
    for file_path in file_paths:
        if apply_fixes_to_file(file_path, config):
            fixes_applied += 1

    if fixes_applied > 0:
        print(
            f"[PostToolUse] Auto-fix: {fixes_applied} file(s) corrected",
            file=sys.stderr,
        )
    else:
        print("[PostToolUse] Auto-fix: No corrections needed", file=sys.stderr)

    print("[PostToolUse] ===== HOOK COMPLETED =====", file=sys.stderr)
    sys.exit(0)


if __name__ == "__main__":
    main()
