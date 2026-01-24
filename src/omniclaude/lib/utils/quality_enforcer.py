#!/usr/bin/env python3
"""
Main quality enforcement orchestrator.
Coordinates validation, RAG, AI consensus, and substitution.

This is the Phase 5 orchestrator that integrates all quality enforcement phases:
- Phase 1: Fast Validation (<100ms)
- Phase 2: RAG Intelligence (<500ms)
- Phase 3: Correction Generation
- Phase 4: AI Quorum Scoring (<1000ms)
- Phase 5: Decision & Substitution

Performance Budget: <2000ms total
"""

import asyncio
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

# Add project root to path for config import
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from config import settings

# Add lib directory to path
sys.path.insert(0, str(Path(__file__).parent / "lib"))


def load_config() -> dict[str, Any]:
    """Load configuration from config.yaml with environment variable overrides."""
    config_path = Path(__file__).parent / "config.yaml"
    config: dict[str, Any] = {}

    # Load from YAML if exists
    if config_path.exists():
        try:
            with open(config_path) as f:
                config = yaml.safe_load(f) or {}
        except Exception as e:
            print(f"Warning: Could not load config.yaml: {e}", file=sys.stderr)

    return config


def _get_safe_tool_metadata(tool_call: dict[str, Any]) -> dict[str, Any]:
    """Extract safe metadata from tool_call without exposing sensitive data.

    This function extracts only non-sensitive metadata from tool calls for logging,
    avoiding exposure of file contents, code snippets, commands with credentials,
    or other potentially sensitive user input.

    Args:
        tool_call: The raw tool call dictionary from Claude Code.

    Returns:
        A dictionary containing only safe metadata fields.
    """
    # Sensitive fields that should never be logged (may contain secrets/PII)
    sensitive_fields = {
        "content",  # Write tool - file contents
        "new_string",  # Edit tool - code to insert
        "old_string",  # Edit tool - code to replace
        "command",  # Bash tool - may contain credentials
        "prompt",  # WebFetch - user queries
        "query",  # Search tools - user queries
        "body",  # API calls - request bodies
        "message",  # Message content
        "text",  # Text content
        "data",  # Generic data field
        "input",  # Generic input field
    }

    tool_name = tool_call.get("tool_name", "unknown")
    params = tool_call.get("tool_input", tool_call.get("parameters", {}))

    # Build safe metadata
    safe_metadata: dict[str, Any] = {
        "tool_name": tool_name,
        "has_tool_input": "tool_input" in tool_call,
        "param_count": len(params) if isinstance(params, dict) else 0,
    }

    # Extract specific safe fields based on tool type
    if isinstance(params, dict):
        # File path is generally safe (already logged separately)
        if "file_path" in params:
            safe_metadata["file_path"] = params["file_path"]
        if "notebook_path" in params:
            safe_metadata["notebook_path"] = params["notebook_path"]

        # For Edit tool, log operation type without content
        if tool_name == "Edit":
            safe_metadata["has_old_string"] = "old_string" in params
            safe_metadata["has_new_string"] = "new_string" in params
            safe_metadata["replace_all"] = params.get("replace_all", False)

        # For Write tool, log content length without content
        if tool_name == "Write" and "content" in params:
            safe_metadata["content_length"] = len(params["content"])

        # For Bash tool, log command presence without the command itself
        if tool_name == "Bash":
            safe_metadata["has_command"] = "command" in params
            if "timeout" in params:
                safe_metadata["timeout"] = params["timeout"]

        # For Read tool, log offset/limit if present
        if tool_name == "Read":
            if "offset" in params:
                safe_metadata["offset"] = params["offset"]
            if "limit" in params:
                safe_metadata["limit"] = params["limit"]

        # Log param keys (excluding sensitive ones) for debugging
        safe_param_keys = [k for k in params.keys() if k not in sensitive_fields]
        if safe_param_keys:
            safe_metadata["param_keys"] = safe_param_keys

    return safe_metadata


# Load configuration
CONFIG = load_config()

# Configuration flags from Pydantic Settings (type-safe)
ENABLE_PHASE_1_VALIDATION = settings.enable_phase_1_validation
ENABLE_PHASE_2_RAG = settings.enable_phase_2_rag
ENABLE_PHASE_3_CORRECTION = settings.enable_phase_3_correction
ENABLE_PHASE_4_AI_QUORUM = settings.enable_phase_4_ai_quorum

# Performance budget from Pydantic Settings
PERFORMANCE_BUDGET_SECONDS = settings.performance_budget_seconds

# Enforcement mode from Pydantic Settings
ENFORCEMENT_MODE = settings.enforcement_mode


class ViolationsLogger:
    """Dedicated logger for tracking naming convention violations."""

    def __init__(self) -> None:
        """Initialize violations logger with configured paths."""
        log_config = CONFIG.get("logging", {})

        # Get log paths from config or use defaults
        self.violations_log = Path(
            os.path.expanduser(
                log_config.get("violations_log", "~/.claude/hooks/logs/violations.log")
            )
        )
        self.violations_summary = Path(
            os.path.expanduser(
                log_config.get(
                    "violations_summary", "~/.claude/hooks/logs/violations_summary.json"
                )
            )
        )
        self.max_violations_history = log_config.get("max_violations_history", 100)

        # Ensure log directory exists
        self.violations_log.parent.mkdir(parents=True, exist_ok=True)
        self.violations_summary.parent.mkdir(parents=True, exist_ok=True)

    def log_violations(self, file_path: str, violations: list[Any]) -> None:
        """
        Log violations to dedicated violations.log file.

        Format: [timestamp] file_path - N violations: name1 (line X), name2 (line Y), ...

        Args:
            file_path: Path to file with violations
            violations: List of Violation objects
        """
        if not violations:
            return

        try:
            timestamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

            # Get relative path if possible (cleaner display)
            try:
                display_path = str(Path(file_path).relative_to(Path.cwd()))
            except (ValueError, OSError):
                display_path = file_path

            # Format violation summary (show names and line numbers)
            violation_details = ", ".join(
                [f"{v.name} (line {v.line})" for v in violations[:5]]
            )
            if len(violations) > 5:
                violation_details += f", ... and {len(violations) - 5} more"

            # Write to violations.log
            log_line = (
                f"[{timestamp}] {display_path} - {len(violations)} violations: "
                f"{violation_details}\n"
            )

            with open(self.violations_log, "a", encoding="utf-8") as f:
                f.write(log_line)

            # Update summary JSON
            self._update_summary(display_path, violations, timestamp)

            # Rotate log if needed
            self._rotate_log_if_needed()

        except Exception as e:
            # Don't fail enforcement if logging fails
            print(f"[Warning] Failed to log violations: {e}", file=sys.stderr)

    def _update_summary(
        self, file_path: str, violations: list[Any], timestamp: str
    ) -> None:
        """Update violations_summary.json with new violation data."""
        try:
            # Load existing summary
            summary: dict[str, Any] = {
                "last_updated": "",
                "total_violations_today": 0,
                "files_with_violations": [],
            }

            if self.violations_summary.exists():
                try:
                    with open(self.violations_summary, encoding="utf-8") as f:
                        loaded = json.load(f)
                        if isinstance(loaded, dict):
                            summary = loaded
                except (json.JSONDecodeError, ValueError):
                    # Start fresh if corrupted
                    pass

            # Check if this is today's data (reset counter at midnight UTC)
            today = datetime.now(UTC).strftime("%Y-%m-%d")
            last_updated = summary.get("last_updated", "")
            last_update_date = str(last_updated)[:10] if last_updated else ""

            if last_update_date != today:
                # New day, reset counter
                summary["total_violations_today"] = 0
                summary["files_with_violations"] = []

            # Update summary
            summary["last_updated"] = timestamp
            total_today = summary.get("total_violations_today", 0)
            summary["total_violations_today"] = int(total_today) + len(violations)

            # Add file entry
            file_entry: dict[str, Any] = {
                "path": file_path,
                "violations": len(violations),
                "timestamp": timestamp,
                "suggestions": [v.suggestion or v.name for v in violations[:10]],
            }
            files_list = summary.get("files_with_violations", [])
            if isinstance(files_list, list):
                files_list.append(file_entry)
                summary["files_with_violations"] = files_list

            # Keep only recent entries (configurable limit)
            files_with_violations = summary.get("files_with_violations", [])
            if (
                isinstance(files_with_violations, list)
                and len(files_with_violations) > self.max_violations_history
            ):
                summary["files_with_violations"] = files_with_violations[
                    -self.max_violations_history :
                ]

            # Write updated summary with trailing newline
            with open(self.violations_summary, "w", encoding="utf-8") as f:
                json.dump(summary, f, indent=2)
                f.write("\n")  # Add trailing newline

        except Exception as e:
            print(
                f"[Warning] Failed to update violations summary: {e}", file=sys.stderr
            )

    def _rotate_log_if_needed(self) -> None:
        """Rotate violations.log if it exceeds size limit."""
        try:
            max_size_mb = CONFIG.get("logging", {}).get("max_size_mb", 10)
            max_size_bytes = max_size_mb * 1024 * 1024

            if self.violations_log.exists():
                size = self.violations_log.stat().st_size

                if size > max_size_bytes:
                    # Rotate: violations.log -> violations.log.1
                    backup_path = self.violations_log.with_suffix(".log.1")

                    # Remove old backup if exists
                    if backup_path.exists():
                        backup_path.unlink()

                    # Move current log to backup
                    self.violations_log.rename(backup_path)

                    print(
                        f"[Info] Rotated violations.log ({size / 1024 / 1024:.1f}MB)",
                        file=sys.stderr,
                    )

        except Exception as e:
            print(f"[Warning] Failed to rotate violations log: {e}", file=sys.stderr)


# ONEX: exempt - pipeline orchestrator
# Rationale: QualityEnforcer has 19 methods because it orchestrates a 5-phase
# validation pipeline (validation, RAG, correction, AI quorum, decision).
# The methods are private helpers for the main enforce() workflow and splitting
# them would create unnecessary indirection without improving cohesion.
# Phases: Phase 1 (<100ms), Phase 2 (<500ms), Phase 3, Phase 4 (<1000ms), Phase 5
class QualityEnforcer:
    """Main orchestrator for quality enforcement."""

    def __init__(self) -> None:
        self.start_time = time.time()
        self.performance_budget = PERFORMANCE_BUDGET_SECONDS
        self.violations_logger = ViolationsLogger()
        self.system_message: str | None = None  # For Claude Code systemMessage field
        self.stats: dict[str, float] = {
            "phase_1_time": 0.0,
            "phase_2_time": 0.0,
            "phase_3_time": 0.0,
            "phase_4_time": 0.0,
            "phase_5_time": 0.0,
            "violations_found": 0.0,
            "corrections_applied": 0.0,
            "corrections_suggested": 0.0,
            "corrections_skipped": 0.0,
        }

        # Enhanced metadata for decision intelligence
        self.tool_selection_metadata: dict[str, Any] | None = None
        self.quality_check_metadata: dict[str, Any] | None = None

    async def enforce(self, tool_call: dict[str, Any]) -> dict[str, Any]:
        """
        Main enforcement workflow with decision intelligence capture.

        Args:
            tool_call: Tool call dict with tool_name and parameters

        Returns:
            Modified tool_call with corrections applied or original if no changes
        """
        try:
            # Extract tool info (Claude Code uses "tool_input" not "parameters")
            tool_name = tool_call.get("tool_name", "unknown")
            params = tool_call.get("tool_input", tool_call.get("parameters", {}))
            file_path = params.get("file_path", "")
            content = self._extract_content(tool_call)

            # Capture tool selection intelligence (target: <10ms)
            self._capture_tool_selection_metadata(tool_name, params)

            if not content or not file_path:
                self._log("No content or file path found, skipping")
                return tool_call

            # Detect language
            language = self._detect_language(file_path)
            if not language:
                self._log(f"Unsupported language for {file_path}, skipping")
                return tool_call

            # Phase 1: Fast validation (target: <100ms)
            if not ENABLE_PHASE_1_VALIDATION:
                self._log("Phase 1 disabled, skipping validation")
                return tool_call

            phase_start = time.time()
            self._log("[Phase 1] Running fast validation...")

            violations = await self._run_phase_1_validation(
                content, file_path, language
            )

            self.stats["phase_1_time"] = time.time() - phase_start
            self.stats["violations_found"] = len(violations)

            # Update quality check metadata after validation
            self._update_quality_check_metadata(violations)

            if not violations:
                self._log(f"[Phase 1] No violations found - {self._elapsed():.3f}s")
                return tool_call

            self._log(
                f"[Phase 1] Found {len(violations)} violations - {self._elapsed():.3f}s"
            )

            # Log violations to dedicated log files
            self.violations_logger.log_violations(file_path, violations)

            # Check performance budget before continuing
            if self._elapsed() > self.performance_budget * 0.5:
                self._log("[Warning] Already used 50% of budget, skipping AI analysis")
                # Build system message and block (no time for corrections)
                self.system_message = self._build_violations_system_message(
                    violations, file_path, mode=ENFORCEMENT_MODE
                )
                return tool_call

            # Phase 2-5: Intelligent correction pipeline (if enabled)
            if (
                ENABLE_PHASE_2_RAG
                or ENABLE_PHASE_3_CORRECTION
                or ENABLE_PHASE_4_AI_QUORUM
            ):
                try:
                    corrected_tool_call = await self._intelligent_correction_pipeline(
                        tool_call, violations, content, file_path, language
                    )

                    # If corrections were auto-applied, clear system message (allow write)
                    # If only suggested, keep system message (block write)
                    if self.stats["corrections_applied"] > 0:
                        self._log(
                            f"[Phase 5] Auto-applied {self.stats['corrections_applied']} corrections, allowing write"
                        )
                        self.system_message = None  # Clear - all violations fixed
                    else:
                        # No auto-apply, violations remain - build system message to block
                        self._log(
                            "[Phase 5] No auto-apply, violations remain - blocking"
                        )
                        self.system_message = self._build_violations_system_message(
                            violations, file_path, mode=ENFORCEMENT_MODE
                        )

                    return corrected_tool_call
                except Exception as e:
                    self._log(f"[Error] Pipeline failed: {e} - {self._elapsed():.3f}s")
                    # Build system message and block on error
                    self.system_message = self._build_violations_system_message(
                        violations, file_path, mode=ENFORCEMENT_MODE
                    )
                    return tool_call  # Fallback to original
            else:
                # Phase 1 only mode - just report violations and block
                self._log(
                    "[Phase 1 Only] Violations detected but correction phases disabled"
                )
                self.system_message = self._build_violations_system_message(
                    violations, file_path, mode=ENFORCEMENT_MODE
                )
                return tool_call

        except Exception as e:
            self._log(f"[Fatal Error] Enforcement failed: {e}")
            return tool_call  # Always return original on error

    async def _run_phase_1_validation(
        self, content: str, file_path: str, language: str
    ) -> list[Any]:
        """
        Run Phase 1: Fast local validation.

        Returns:
            List of Violation objects
        """
        try:
            from .lib.validators.naming_validator import NamingValidator

            # Use auto-detection mode to apply appropriate conventions
            validator = NamingValidator(language=language, validation_mode="auto")
            violations = validator.validate_content(content, file_path)

            # Log detected repository type for debugging
            is_omninode = NamingValidator.is_omninode_repo(file_path)
            repo_type = "Omninode" if is_omninode else "Standard PEP 8"
            self._log(f"[Phase 1] Detected repository type: {repo_type}")

            return list(violations)

        except ImportError as e:
            self._log(f"[Phase 1] Validator not available: {e}")
            return []
        except Exception as e:
            self._log(f"[Phase 1] Validation failed: {e}")
            return []

    async def _intelligent_correction_pipeline(
        self,
        tool_call: dict[str, Any],
        violations: list[Any],
        content: str,
        file_path: str,
        language: str,
    ) -> dict[str, Any]:
        """
        Run the intelligent correction pipeline (Phases 2-5).

        Phase 2: RAG intelligence
        Phase 3: Correction generation
        Phase 4: AI quorum scoring
        Phase 5: Decision and substitution
        """
        corrections = []

        # Phase 2: RAG intelligence (target: <500ms)
        if ENABLE_PHASE_2_RAG:
            phase_start = time.time()
            self._log("[Phase 2] Querying RAG intelligence...")

            try:
                from .lib.correction.generator import CorrectionGenerator

                # Get RAG config from CONFIG
                rag_config = CONFIG.get("rag", {})
                archon_url = rag_config.get("base_url", "http://localhost:8181")
                timeout = rag_config.get("timeout_seconds", 0.5)

                generator = CorrectionGenerator(archon_url=archon_url, timeout=timeout)
                corrections = await generator.generate_corrections(
                    violations, content, file_path, language
                )

                await generator.close()

                self.stats["phase_2_time"] = time.time() - phase_start
                self._log(
                    f"[Phase 2] Generated {len(corrections)} corrections - {self._elapsed():.3f}s"
                )

            except ImportError as e:
                self._log(f"[Phase 2] RAG client not available: {e}")
                # Fallback to simple corrections
                corrections = self._generate_simple_corrections(violations)
            except Exception as e:
                self._log(f"[Phase 2] RAG query failed: {e}")
                corrections = self._generate_simple_corrections(violations)
        else:
            # Phase 2 disabled, use simple corrections
            corrections = self._generate_simple_corrections(violations)

        if not corrections:
            self._log("[Phase 2/3] No corrections generated")
            return tool_call

        # Phase 4: AI Quorum (target: <1000ms)
        scored_corrections = []

        if ENABLE_PHASE_4_AI_QUORUM:
            phase_start = time.time()
            self._log("[Phase 4] Running AI quorum...")

            try:
                from .lib.consensus.quorum import AIQuorum

                quorum = AIQuorum()

                for correction in corrections:
                    # Check budget before each scoring
                    if self._elapsed() > self.performance_budget * 0.9:
                        self._log(
                            "[Warning] Approaching budget limit, skipping remaining corrections"
                        )
                        break

                    score = await quorum.score_correction(
                        correction,
                        content,
                        file_path,
                    )
                    scored_corrections.append(
                        {"correction": correction, "score": score}
                    )

                self.stats["phase_4_time"] = time.time() - phase_start
                self._log(
                    f"[Phase 4] Scored {len(scored_corrections)} corrections - {self._elapsed():.3f}s"
                )

            except ImportError as e:
                self._log(f"[Phase 4] AI Quorum not available: {e}")
                # Fallback to accepting all corrections with medium confidence
                scored_corrections = self._create_fallback_scores(corrections)
            except Exception as e:
                self._log(f"[Phase 4] AI Quorum failed: {e}")
                scored_corrections = self._create_fallback_scores(corrections)
        else:
            # Phase 4 disabled, use fallback scores
            scored_corrections = self._create_fallback_scores(corrections)

        # Phase 5: Decision and substitution
        phase_start = time.time()
        result = self._apply_decisions(tool_call, scored_corrections, content)
        self.stats["phase_5_time"] = time.time() - phase_start

        return result

    def _generate_simple_corrections(
        self, violations: list[Any]
    ) -> list[dict[str, Any]]:
        """
        Generate simple corrections without RAG intelligence.
        Fallback when Phase 2 is disabled or fails.
        """
        corrections = []

        for violation in violations:
            corrections.append(
                {
                    "violation": violation,
                    "old_name": violation.name,
                    "new_name": violation.suggestion or violation.name,
                    "rag_context": {},
                    "confidence": 0.6,  # Lower confidence without RAG
                    "explanation": violation.rule,
                }
            )

        return corrections

    def _create_fallback_scores(
        self, corrections: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """
        Create fallback scores when AI Quorum is disabled or fails.
        Use medium confidence scores that won't trigger auto-apply.
        """
        from dataclasses import dataclass, field

        @dataclass
        class FallbackScore:
            consensus_score: float = 0.65
            individual_scores: dict[str, Any] = field(default_factory=dict)
            individual_explanations: dict[str, Any] = field(default_factory=dict)
            confidence: float = 0.60
            should_apply: bool = False

        scored = []
        for correction in corrections:
            scored.append({"correction": correction, "score": FallbackScore()})

        return scored

    def _apply_decisions(
        self,
        tool_call: dict[str, Any],
        scored_corrections: list[dict[str, Any]],
        content: str,
    ) -> dict[str, Any]:
        """
        Apply corrections based on AI consensus scores.

        Decision thresholds:
        - Score >= 0.80 + Confidence >= 0.70: Auto-apply
        - Score >= 0.60: Suggest to user (log only)
        - Score < 0.60: Skip
        """
        self._log("[Phase 5] Applying decisions...")

        auto_applied = 0
        suggested = 0
        skipped = 0

        modified_content = content

        # Sort by line number in reverse to avoid offset issues
        sorted_corrections = sorted(
            scored_corrections,
            key=lambda x: getattr(x["correction"]["violation"], "line", 0),
            reverse=True,
        )

        for item in sorted_corrections:
            correction = item["correction"]
            score = item["score"]

            # Auto-apply threshold
            if score.should_apply or (
                score.consensus_score >= 0.80 and score.confidence >= 0.70
            ):
                # Auto-apply
                modified_content = self._apply_correction(modified_content, correction)
                auto_applied += 1
                self._log(
                    f"  ✓ Auto-applied: {correction['old_name']} → {correction['new_name']} (score: {score.consensus_score:.2f})"
                )

            elif score.consensus_score >= 0.60:
                # Log suggestion for user review
                suggested += 1
                self._log(
                    f"  ? Suggested: {correction['old_name']} → {correction['new_name']} (score: {score.consensus_score:.2f})"
                )

            else:
                # Skip
                skipped += 1
                self._log(
                    f"  ✗ Skipped: {correction['old_name']} (score: {score.consensus_score:.2f})"
                )

        self.stats["corrections_applied"] = auto_applied
        self.stats["corrections_suggested"] = suggested
        self.stats["corrections_skipped"] = skipped

        self._log(
            f"[Phase 5] Complete: {auto_applied} applied, {suggested} suggested, {skipped} skipped - {self._elapsed():.3f}s"
        )

        # Update tool call with modified content
        if auto_applied > 0:
            tool_call = self._update_tool_content(tool_call, modified_content)

            # Add comment about changes
            summary = f"\n\n# AI Quality Enforcer: {auto_applied} naming correction(s) applied automatically"
            tool_call = self._append_comment(tool_call, summary)

        return tool_call

    def _apply_correction(self, content: str, correction: dict[str, Any]) -> str:
        """
        Apply a single correction to content using word boundary regex.
        """
        import re

        old_name = correction["old_name"]
        new_name = correction["new_name"]

        # Use word boundaries to avoid partial matches
        pattern = r"\b" + re.escape(old_name) + r"\b"
        modified = re.sub(pattern, new_name, content)

        return modified

    def _extract_content(self, tool_call: dict[str, Any]) -> str:
        """Extract content from tool call (Claude Code uses 'tool_input')."""
        params = tool_call.get("tool_input", tool_call.get("parameters", {}))

        # Handle different tool types
        if "content" in params:
            return str(params["content"])
        elif "new_string" in params:
            return str(params["new_string"])
        elif "edits" in params:
            # MultiEdit case
            return "\n".join(
                str(edit.get("new_string", "")) for edit in params["edits"]
            )

        return ""

    def _update_tool_content(
        self, tool_call: dict[str, Any], new_content: str
    ) -> dict[str, Any]:
        """Update tool call with corrected content (Claude Code uses 'tool_input')."""
        params_key = "tool_input" if "tool_input" in tool_call else "parameters"
        params = tool_call.get(params_key, {})

        if "content" in params:
            params["content"] = new_content
        elif "new_string" in params:
            params["new_string"] = new_content

        return tool_call

    def _append_comment(
        self, tool_call: dict[str, Any], comment: str
    ) -> dict[str, Any]:
        """Append a comment to the content (Claude Code uses 'tool_input')."""
        params_key = "tool_input" if "tool_input" in tool_call else "parameters"
        params = tool_call.get(params_key, {})

        if "content" in params:
            params["content"] += comment
        elif "new_string" in params:
            params["new_string"] += comment

        return tool_call

    def _detect_language(self, file_path: str) -> str | None:
        """Detect programming language from file extension."""
        ext = Path(file_path).suffix.lower()

        mapping = {
            ".py": "python",
            ".ts": "typescript",
            ".tsx": "typescript",
            ".js": "javascript",
            ".jsx": "javascript",
        }

        return mapping.get(ext)

    def _build_violations_system_message(
        self, violations: list[Any], file_path: str, mode: str = "warn"
    ) -> str:
        """
        Build system message for Claude Code with violation warnings.

        Args:
            violations: List of violations found
            file_path: Path to the file being checked
            mode: "warn" for warnings only, "block" for blocking mode

        Returns a formatted string that will be displayed to the user via
        the systemMessage field in the hook's JSON output.
        """
        lines = []
        lines.append("=" * 70)

        if mode == "block":
            lines.append("🚫 NAMING CONVENTION VIOLATIONS - WRITE BLOCKED")
        else:
            lines.append("⚠️  NAMING CONVENTION WARNINGS")

        lines.append("=" * 70)
        lines.append(f"File: {file_path}")
        lines.append(f"Found {len(violations)} naming violation(s)")
        lines.append("")

        # Group violations by type for better readability
        violations_by_type: dict[str, list[Any]] = {}
        for v in violations:
            vtype = v.violation_type
            if vtype not in violations_by_type:
                violations_by_type[vtype] = []
            violations_by_type[vtype].append(v)

        # Display violations grouped by type
        for vtype, violations_list in violations_by_type.items():
            lines.append(f"{vtype.upper()} VIOLATIONS ({len(violations_list)}):")
            for v in violations_list[:5]:  # Limit to 5 per type to avoid spam
                lines.append(
                    f"  • Line {v.line}: '{v.name}' should be '{v.expected_format}'"
                )
                if v.suggestion and v.suggestion != v.expected_format:
                    lines.append(f"    Suggestion: {v.suggestion}")

            if len(violations_list) > 5:
                lines.append(
                    f"  ... and {len(violations_list) - 5} more {vtype} violation(s)"
                )
            lines.append("")

        # Footer with guidance based on mode
        lines.append("─" * 70)
        if mode == "block":
            lines.append("🚫 WRITE BLOCKED: Please fix violations before saving")
            lines.append("   Fix the violations above and try again.")
        else:
            lines.append("💡 Recommendation: Fix violations to maintain code quality")
            lines.append("   Write will proceed, but please address these issues.")
        lines.append("   See naming conventions: docs/OMNINODE_NAMING_CONVENTIONS.md")
        lines.append("=" * 70)

        return "\n".join(lines)

    def _elapsed(self) -> float:
        """Get elapsed time in seconds."""
        return time.time() - self.start_time

    def _log(self, message: str) -> None:
        """Log message to stderr."""
        print(message, file=sys.stderr)

    def _capture_tool_selection_metadata(
        self, tool_name: str, tool_input: dict[str, Any]
    ) -> None:
        """
        Capture tool selection intelligence metadata.

        Uses heuristic-based analysis from tool_selection_intelligence module.
        Target: <10ms overhead.

        Args:
            tool_name: Name of the tool being invoked
            tool_input: Tool input parameters
        """
        try:
            from lib.tool_selection_intelligence import (
                create_enhanced_metadata,
            )

            # Generate enhanced metadata (includes tool selection + context)
            self.tool_selection_metadata = create_enhanced_metadata(
                tool_name=tool_name,
                tool_input=tool_input,
                quality_checks=None,  # Will be updated after validation
            )

            self._log(
                f"[Intelligence] Tool selection captured: {tool_name} "
                f"(reason: {self.tool_selection_metadata['tool_selection']['selection_reason']}, "
                f"analysis: {self.tool_selection_metadata['performance']['analysis_time_ms']:.2f}ms)"
            )

        except Exception as e:
            # Don't fail enforcement if metadata capture fails
            self._log(f"[Warning] Failed to capture tool selection metadata: {e}")
            self.tool_selection_metadata = None

    def _update_quality_check_metadata(self, violations: list[Any]) -> None:
        """
        Update quality check metadata after validation.

        Args:
            violations: List of violations found during validation
        """
        try:
            from lib.tool_selection_intelligence import QualityCheckMetadata

            # Categorize checks
            checks_passed: list[str] = ["syntax_validation"] if not violations else []
            checks_warnings: list[str] = []
            checks_failed: list[str] = []

            # Analyze violations
            if violations:
                violation_types = {v.violation_type for v in violations}
                checks_failed.extend(
                    [f"{vtype}_convention" for vtype in violation_types]
                )

            # Create quality check metadata
            quality_metadata = QualityCheckMetadata(
                checks_passed=checks_passed,
                checks_warnings=checks_warnings,
                checks_failed=checks_failed,
                violations_found=len(violations),
                corrections_suggested=self.stats.get("corrections_suggested", 0),
                enforcement_mode=ENFORCEMENT_MODE,
            )

            # Update tool selection metadata with quality checks
            if self.tool_selection_metadata:
                self.tool_selection_metadata["quality_checks"] = {
                    "checks_passed": quality_metadata.checks_passed,
                    "checks_warnings": quality_metadata.checks_warnings,
                    "checks_failed": quality_metadata.checks_failed,
                    "violations_found": quality_metadata.violations_found,
                    "corrections_suggested": quality_metadata.corrections_suggested,
                    "enforcement_mode": quality_metadata.enforcement_mode,
                }

            self.quality_check_metadata = quality_metadata

            self._log(
                f"[Intelligence] Quality checks updated: "
                f"{len(checks_passed)} passed, {len(checks_warnings)} warnings, "
                f"{len(checks_failed)} failed"
            )

        except Exception as e:
            # Don't fail enforcement if metadata update fails
            self._log(f"[Warning] Failed to update quality check metadata: {e}")

    def get_enhanced_metadata(self) -> dict[str, Any]:
        """
        Get complete enhanced metadata for logging.

        Returns:
            Combined tool selection and quality check metadata
        """
        return self.tool_selection_metadata or {}

    def print_stats(self) -> None:
        """Print performance statistics."""
        self._log("\n" + "=" * 60)
        self._log("Quality Enforcer Statistics")
        self._log("=" * 60)
        self._log(
            f"Total Time: {self._elapsed():.3f}s (budget: {self.performance_budget}s)"
        )
        self._log(f"Phase 1 (Validation): {self.stats['phase_1_time']:.3f}s")
        self._log(f"Phase 2 (RAG): {self.stats['phase_2_time']:.3f}s")
        self._log("Phase 3 (Correction): Included in Phase 2")
        self._log(f"Phase 4 (AI Quorum): {self.stats['phase_4_time']:.3f}s")
        self._log(f"Phase 5 (Decision): {self.stats['phase_5_time']:.3f}s")
        self._log("-" * 60)
        self._log(f"Violations Found: {self.stats['violations_found']}")
        self._log(f"Corrections Applied: {self.stats['corrections_applied']}")
        self._log(f"Corrections Suggested: {self.stats['corrections_suggested']}")
        self._log(f"Corrections Skipped: {self.stats['corrections_skipped']}")
        self._log("=" * 60)


async def main() -> int:
    """
    Main entry point.

    Reads tool call JSON from stdin, runs enforcement, outputs result to stdout.

    Exit codes:
    - 0: Success (with or without corrections)
    - 1: Fatal error (original tool call passed through)
    """
    # Log hook execution immediately (before any processing)
    hook_exec_log = Path.home() / ".claude" / "hooks" / "logs" / "hook_executions.log"
    hook_exec_log.parent.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    with open(hook_exec_log, "a") as f:
        f.write(f"[{timestamp}] Hook triggered\n")

    try:
        # Read tool call from stdin
        input_data = sys.stdin.read()

        # Log what we received
        with open(hook_exec_log, "a") as f:
            f.write(f"[{timestamp}] Received {len(input_data)} bytes of input\n")

        if not input_data.strip():
            with open(hook_exec_log, "a") as f:
                f.write(f"[{timestamp}] Empty input, returning empty JSON\n")
            print("{}", file=sys.stdout)
            return 0

        tool_call = json.loads(input_data)

        # Log tool name and file path (Claude Code uses 'tool_input' not 'parameters')
        tool_name = tool_call.get("tool_name", "unknown")
        params = tool_call.get("tool_input", tool_call.get("parameters", {}))
        file_path = params.get("file_path", "unknown")
        with open(hook_exec_log, "a") as f:
            f.write(f"[{timestamp}] Tool: {tool_name}, File: {file_path}\n")
            # Log safe metadata only (avoid exposing secrets/PII in raw payloads)
            safe_metadata = _get_safe_tool_metadata(tool_call)
            f.write(f"[{timestamp}] Tool metadata: {json.dumps(safe_metadata)}\n")

        # Run enforcement
        enforcer = QualityEnforcer()
        result = await enforcer.enforce(tool_call)

        # Print statistics to stderr
        enforcer.print_stats()

        # Get enhanced metadata for logging
        enhanced_metadata = enforcer.get_enhanced_metadata()

        # Check if we have violations
        if enforcer.system_message:
            # Choose permission decision based on enforcement mode
            if ENFORCEMENT_MODE == "block":
                # Block mode: prevent write execution
                permission_decision = "deny"
                exit_code = 1  # Bash wrapper converts to exit 2
            else:
                # Warn mode: allow write but show warning
                permission_decision = "allow"
                exit_code = 0

            # Use OFFICIAL Claude Code blocking/warning mechanism
            output = {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": permission_decision,
                    "permissionDecisionReason": enforcer.system_message,
                },
                "enhanced_metadata": enhanced_metadata,  # Add for logging
            }

            # Output result to stdout
            json.dump(output, sys.stdout, indent=2)
            print()  # Add newline

            return exit_code
        else:
            # No violations, allow the operation
            output = result

            # Add enhanced metadata for logging
            if enhanced_metadata:
                output["enhanced_metadata"] = enhanced_metadata

            # Output result to stdout
            json.dump(output, sys.stdout, indent=2)
            print()  # Add newline

            return 0

    except json.JSONDecodeError as e:
        print(f"[Fatal Error] Invalid JSON input: {e}", file=sys.stderr)
        # Try to pass through original input
        print(input_data if "input_data" in locals() else "{}", file=sys.stdout)
        return 1
    except Exception as e:
        print(f"[Fatal Error] {e}", file=sys.stderr)
        import traceback

        traceback.print_exc(file=sys.stderr)

        # On error, pass through original
        if "tool_call" in locals():
            json.dump(tool_call, sys.stdout, indent=2)
        else:
            print("{}", file=sys.stdout)
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
