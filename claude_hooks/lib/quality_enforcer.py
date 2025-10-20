#!/usr/bin/env python3
"""
Main quality enforcement orchestrator with PostgreSQL tracing.

Coordinates validation, RAG, AI consensus, and substitution.
Enhanced with execution tracing for pattern learning and analytics.

This is the Phase 5 orchestrator that integrates all quality enforcement phases:
- Phase 1: Fast Validation (<100ms)
- Phase 2: RAG Intelligence (<500ms)
- Phase 3: Correction Generation
- Phase 4: AI Quorum Scoring (<1000ms)
- Phase 5: Decision & Substitution
- Phase 6: PostgreSQL Tracing (<2ms overhead)

Performance Budget: <2000ms total
"""

import asyncio
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import yaml

# Add lib directory to path
sys.path.insert(0, str(Path(__file__).parent / "lib"))

# Phase 4 Pattern Tracking Integration
try:
    from pattern_tracker import PatternTracker

    PATTERN_TRACKING_AVAILABLE = True
except ImportError:
    PATTERN_TRACKING_AVAILABLE = False
    print(
        "[Warning] Pattern tracking not available, Phase 4 integration disabled",
        file=sys.stderr,
    )

# Import tracing components
try:
    from lib.tracing.tracer import ExecutionTracer

    TRACING_AVAILABLE = True
except ImportError:
    TRACING_AVAILABLE = False
    print(
        "[Warning] Tracing components not available, tracing disabled", file=sys.stderr
    )


def load_config() -> Dict:
    """Load configuration from config.yaml with environment variable overrides."""
    config_path = Path(__file__).parent / "config.yaml"
    config = {}

    # Load from YAML if exists
    if config_path.exists():
        try:
            with open(config_path) as f:
                config = yaml.safe_load(f) or {}
        except Exception as e:
            print(f"Warning: Could not load config.yaml: {e}", file=sys.stderr)

    return config


# Load configuration
CONFIG = load_config()


def get_bool_config(env_var: str, yaml_path: List[str], default: bool) -> bool:
    """Get boolean config from env var (priority) or YAML config."""
    # Environment variable takes precedence
    env_value = os.getenv(env_var)
    if env_value is not None:
        return env_value.lower() == "true"

    # Check YAML config
    value = CONFIG
    for key in yaml_path:
        if isinstance(value, dict) and key in value:
            value = value[key]
        else:
            return default

    if isinstance(value, bool):
        return value
    return default


# Configuration flags for phased rollout (env var or config.yaml)
ENABLE_PHASE_1_VALIDATION = get_bool_config(
    "ENABLE_PHASE_1_VALIDATION", ["enforcement", "enabled"], True
)
ENABLE_PHASE_2_RAG = get_bool_config("ENABLE_PHASE_2_RAG", ["rag", "enabled"], False)
ENABLE_PHASE_3_CORRECTION = get_bool_config(
    "ENABLE_PHASE_3_CORRECTION", ["correction", "enabled"], False
)
ENABLE_PHASE_4_AI_QUORUM = get_bool_config(
    "ENABLE_PHASE_4_AI_QUORUM", ["quorum", "enabled"], False
)

# Performance budget (env var or config.yaml)
PERFORMANCE_BUDGET_SECONDS = float(
    os.getenv(
        "PERFORMANCE_BUDGET_SECONDS",
        str(CONFIG.get("enforcement", {}).get("performance_budget_seconds", 2.0)),
    )
)

# Enforcement mode: "warn" or "block"
ENFORCEMENT_MODE = os.getenv(
    "ENFORCEMENT_MODE", str(CONFIG.get("enforcement", {}).get("mode", "warn"))
).lower()


class ViolationsLogger:
    """Dedicated logger for tracking naming convention violations."""

    def __init__(self):
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

    def log_violations(self, file_path: str, violations: List) -> None:
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
            timestamp = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

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

    def _update_summary(self, file_path: str, violations: List, timestamp: str) -> None:
        """Update violations_summary.json with new violation data."""
        try:
            import subprocess
            import uuid

            # Get git info
            try:
                commit_sha = subprocess.check_output(
                    ["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL, text=True
                ).strip()[:40]
            except Exception:
                commit_sha = "0000000"

            try:
                branch = subprocess.check_output(
                    ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                    stderr=subprocess.DEVNULL,
                    text=True,
                ).strip()
            except Exception:
                branch = "unknown"

            # Detect environment
            env = "ci" if os.getenv("CI") else "local"

            # Generate run ID
            run_id = str(uuid.uuid4())

            # Load existing summary or create new one with all required fields
            summary = {
                "schema_version": "1.0.0",
                "run_id": run_id,
                "commit_sha": commit_sha,
                "branch": branch,
                "env": env,
                "last_updated": timestamp,
                "window_start": timestamp,
                "window_end": timestamp,
                "total_violations_today": 0,
                "files_with_violations": [],
            }

            if self.violations_summary.exists():
                try:
                    with open(self.violations_summary, "r", encoding="utf-8") as f:
                        existing = json.load(f)
                        # Preserve window_start if it exists and is from today
                        today = datetime.utcnow().strftime("%Y-%m-%d")
                        existing_date = existing.get("last_updated", "")[:10]
                        if existing_date == today:
                            summary["window_start"] = existing.get(
                                "window_start", timestamp
                            )
                            summary["total_violations_today"] = existing.get(
                                "total_violations_today", 0
                            )
                            summary["files_with_violations"] = existing.get(
                                "files_with_violations", []
                            )
                except (json.JSONDecodeError, ValueError):
                    # Start fresh if corrupted
                    pass

            # Check if this is today's data (reset counter at midnight UTC)
            today = datetime.utcnow().strftime("%Y-%m-%d")
            last_update_date = summary.get("last_updated", "")[:10]

            if last_update_date != today:
                # New day, reset counter and window
                summary["total_violations_today"] = 0
                summary["files_with_violations"] = []
                summary["window_start"] = timestamp

            # Update summary
            summary["run_id"] = run_id  # New run ID for this update
            summary["commit_sha"] = commit_sha  # Current commit
            summary["branch"] = branch  # Current branch
            summary["env"] = env  # Current environment
            summary["last_updated"] = timestamp
            summary["window_end"] = timestamp
            summary["total_violations_today"] += len(violations)

            # Add file entry
            file_entry = {
                "path": file_path,
                "violations": len(violations),
                "timestamp": timestamp,
                "suggestions": [v.suggestion or v.name for v in violations[:10]],
            }
            summary["files_with_violations"].append(file_entry)

            # Keep only recent entries (configurable limit)
            if len(summary["files_with_violations"]) > self.max_violations_history:
                summary["files_with_violations"] = summary["files_with_violations"][
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


class QualityEnforcer:
    """Main orchestrator for quality enforcement with tracing."""

    def __init__(self):
        self.start_time = time.time()
        self.performance_budget = PERFORMANCE_BUDGET_SECONDS
        self.violations_logger = ViolationsLogger()
        self.system_message = None  # For Claude Code systemMessage field
        self.stats = {
            "phase_1_time": 0,
            "phase_2_time": 0,
            "phase_3_time": 0,
            "phase_4_time": 0,
            "phase_5_time": 0,
            "violations_found": 0,
            "corrections_applied": 0,
            "corrections_suggested": 0,
            "corrections_skipped": 0,
        }

        # Tracing support
        self.tracer: Optional[ExecutionTracer] = None
        self.tracing_enabled = TRACING_AVAILABLE
        self.correlation_id = os.getenv("CORRELATION_ID")

    async def enforce(self, tool_call: Dict) -> Dict:
        """
        Main enforcement workflow with tracing.

        Args:
            tool_call: Tool call dict with tool_name and parameters

        Returns:
            Modified tool_call with corrections applied or original if no changes
        """
        try:
            # Extract file info (Claude Code uses "tool_input" not "parameters")
            params = tool_call.get("tool_input", tool_call.get("parameters", {}))
            file_path = params.get("file_path", "")
            content = self._extract_content(tool_call)

            # Store file_path for pattern tracking
            self._current_file_path = file_path

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
    ) -> List:
        """
        Run Phase 1: Fast local validation.

        Returns:
            List of Violation objects
        """
        try:
            from validators.naming_validator import NamingValidator

            # Use auto-detection mode to apply appropriate conventions
            validator = NamingValidator(language=language, validation_mode="auto")
            violations = validator.validate_content(content, file_path)

            # Log detected repository type for debugging
            is_omninode = NamingValidator.is_omninode_repo(file_path)
            repo_type = "Omninode" if is_omninode else "Standard PEP 8"
            self._log(f"[Phase 1] Detected repository type: {repo_type}")

            return violations

        except ImportError as e:
            self._log(f"[Phase 1] Validator not available: {e}")
            return []
        except Exception as e:
            self._log(f"[Phase 1] Validation failed: {e}")
            return []

    async def _intelligent_correction_pipeline(
        self,
        tool_call: Dict,
        violations: List,
        content: str,
        file_path: str,
        language: str,
    ) -> Dict:
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
                from correction.generator import CorrectionGenerator

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
                from consensus.quorum import AIQuorum

                quorum = AIQuorum()

                for correction in corrections:
                    # Check budget before each scoring
                    if self._elapsed() > self.performance_budget * 0.9:
                        self._log(
                            "[Warning] Approaching budget limit, skipping remaining corrections"
                        )
                        break

                    score = await quorum.score_correction(
                        correction, content, file_path
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

    def _generate_simple_corrections(self, violations: List) -> List[Dict]:
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

    def _create_fallback_scores(self, corrections: List[Dict]) -> List[Dict]:
        """
        Create fallback scores when AI Quorum is disabled or fails.
        Use medium confidence scores that won't trigger auto-apply.
        """
        from dataclasses import dataclass

        @dataclass
        class FallbackScore:
            consensus_score: float = 0.65
            individual_scores: dict = None
            individual_explanations: dict = None
            confidence: float = 0.60
            should_apply: bool = False

            def __post_init__(self):
                if self.individual_scores is None:
                    self.individual_scores = {}
                if self.individual_explanations is None:
                    self.individual_explanations = {}

        scored = []
        for correction in corrections:
            scored.append({"correction": correction, "score": FallbackScore()})

        return scored

    def _apply_decisions(
        self, tool_call: Dict, scored_corrections: List[Dict], content: str
    ) -> Dict:
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

        # Track pattern execution metrics to Phase 4 (fire-and-forget)
        if PATTERN_TRACKING_AVAILABLE and (auto_applied > 0 or suggested > 0):
            asyncio.create_task(
                self._track_pattern_execution_to_phase4(
                    content=content,
                    auto_applied=auto_applied,
                    suggested=suggested,
                    violations=len(scored_corrections),
                    language=self._detect_language(
                        self._get_current_file_path()
                        if hasattr(self, "_current_file_path")
                        else ""
                    )
                    or "unknown",
                )
            )

        # Update tool call with modified content
        if auto_applied > 0:
            tool_call = self._update_tool_content(tool_call, modified_content)

            # Add comment about changes
            summary = f"\n\n# AI Quality Enforcer: {auto_applied} naming correction(s) applied automatically"
            tool_call = self._append_comment(tool_call, summary)

        return tool_call

    def _apply_correction(self, content: str, correction: Dict) -> str:
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

    def _extract_content(self, tool_call: Dict) -> str:
        """Extract content from tool call (Claude Code uses 'tool_input')."""
        params = tool_call.get("tool_input", tool_call.get("parameters", {}))

        # Handle different tool types
        if "content" in params:
            return params["content"]
        elif "new_string" in params:
            return params["new_string"]
        elif "edits" in params:
            # MultiEdit case
            return "\n".join(edit.get("new_string", "") for edit in params["edits"])

        return ""

    def _update_tool_content(self, tool_call: Dict, new_content: str) -> Dict:
        """Update tool call with corrected content (Claude Code uses 'tool_input')."""
        params_key = "tool_input" if "tool_input" in tool_call else "parameters"
        params = tool_call.get(params_key, {})

        if "content" in params:
            params["content"] = new_content
        elif "new_string" in params:
            params["new_string"] = new_content

        return tool_call

    def _append_comment(self, tool_call: Dict, comment: str) -> Dict:
        """Append a comment to the content (Claude Code uses 'tool_input')."""
        params_key = "tool_input" if "tool_input" in tool_call else "parameters"
        params = tool_call.get(params_key, {})

        if "content" in params:
            params["content"] += comment
        elif "new_string" in params:
            params["new_string"] += comment

        return tool_call

    def _detect_language(self, file_path: str) -> Optional[str]:
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
        self, violations: List, file_path: str, mode: str = "warn"
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
        violations_by_type = {}
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

    def _log(self, message: str):
        """Log message to stderr."""
        print(message, file=sys.stderr)

    def _get_current_file_path(self) -> str:
        """Get the current file path being processed."""
        return getattr(self, "_current_file_path", "")

    async def _track_pattern_execution_to_phase4(
        self,
        content: str,
        auto_applied: int,
        suggested: int,
        violations: int,
        language: str,
    ) -> None:
        """
        Track pattern execution metrics to Phase 4 analytics engine.

        This method integrates quality enforcement results with Phase 4 pattern
        traceability system for learning and optimization.

        Args:
            content: The code content that was analyzed
            auto_applied: Number of corrections automatically applied
            suggested: Number of corrections suggested but not applied
            violations: Total number of violations found
            language: Programming language

        Performance: Fire-and-forget async task, non-blocking
        """
        try:
            tracker = PatternTracker()

            # Calculate pattern ID from content hash
            pattern_id = tracker._generate_pattern_id(content)

            # Calculate quality score from violation density
            total_lines = max(len(content.split("\n")), 1)
            quality_score = 1.0 - (violations / total_lines)

            # Track execution metrics
            await tracker.track_pattern_execution(
                pattern_id=pattern_id,
                metrics={
                    "execution_success": auto_applied > 0,
                    "quality_score": round(quality_score, 4),
                    "violations_found": violations,
                    "corrections_applied": auto_applied,
                    "corrections_suggested": suggested,
                    "phase_timings": {
                        "phase_1": self.stats.get("phase_1_time", 0),
                        "phase_2": self.stats.get("phase_2_time", 0),
                        "phase_4": self.stats.get("phase_4_time", 0),
                        "phase_5": self.stats.get("phase_5_time", 0),
                        "total": self._elapsed(),
                    },
                    "enforcement_mode": ENFORCEMENT_MODE,
                    "language": language,
                    "file_path": self._get_current_file_path(),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
            )

            self._log(f"[Phase 4] Pattern execution tracked: {pattern_id[:16]}...")

        except Exception as e:
            # Silent failure - never break enforcement pipeline
            self._log(f"[Warning] Phase 4 tracking failed: {e}")

    async def _send_performance_baseline(
        self, pattern_id: str, stats: Dict[str, float]
    ) -> None:
        """
        Send performance baseline data to Phase 4 for optimization tracking.

        Args:
            pattern_id: Pattern identifier
            stats: Performance statistics dictionary
        """
        try:
            tracker = PatternTracker()

            # Send performance data for baseline tracking
            await tracker.track_performance_baseline(
                pattern_id=pattern_id,
                performance_data={
                    "phase_1_time_ms": stats.get("phase_1_time", 0) * 1000,
                    "phase_2_time_ms": stats.get("phase_2_time", 0) * 1000,
                    "phase_4_time_ms": stats.get("phase_4_time", 0) * 1000,
                    "phase_5_time_ms": stats.get("phase_5_time", 0) * 1000,
                    "total_time_ms": sum(
                        [
                            stats.get("phase_1_time", 0),
                            stats.get("phase_2_time", 0),
                            stats.get("phase_4_time", 0),
                            stats.get("phase_5_time", 0),
                        ]
                    )
                    * 1000,
                    "violations_found": stats.get("violations_found", 0),
                    "corrections_applied": stats.get("corrections_applied", 0),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
            )

        except Exception as e:
            # Silent failure
            self._log(f"[Warning] Performance baseline tracking failed: {e}")

    def print_stats(self):
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

        # Send performance baseline to Phase 4 (fire-and-forget)
        if PATTERN_TRACKING_AVAILABLE and hasattr(self, "_current_file_path"):
            try:
                # Generate pattern ID for performance tracking
                PatternTracker()
                # Use file path as pattern identifier for performance tracking
                pattern_id = f"quality_enforcer_{self._detect_language(self._current_file_path) or 'unknown'}"

                # Create async task for performance baseline tracking
                asyncio.create_task(
                    self._send_performance_baseline(pattern_id, self.stats)
                )
            except Exception as e:
                # Silent failure - never break stats printing
                self._log(f"[Warning] Performance baseline scheduling failed: {e}")


async def main():
    """
    Main entry point with PostgreSQL tracing integration.

    Reads tool call JSON from stdin, runs enforcement, outputs result to stdout.

    Exit codes:
    - 0: Success (with or without corrections)
    - 1: Fatal error (original tool call passed through)
    """
    # Get correlation ID from environment
    correlation_id = os.getenv("CORRELATION_ID")

    # Initialize tracer if available
    tracer = None
    if TRACING_AVAILABLE and correlation_id:
        try:
            tracer = await ExecutionTracer.get_instance()
        except Exception as e:
            print(f"[Warning] Failed to initialize tracer: {e}", file=sys.stderr)

    # Log hook execution immediately (before any processing)
    hook_exec_log = Path.home() / ".claude" / "hooks" / "logs" / "hook_executions.log"
    hook_exec_log.parent.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with open(hook_exec_log, "a") as f:
        f.write(f"[{timestamp}] Hook triggered\n")

    # Track start time for duration calculation
    start_time = time.time()
    exit_code = 0
    success = True

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
            # Debug: log full tool call structure (first 500 chars)
            tool_call_str = json.dumps(tool_call, indent=2)
            f.write(
                f"[{timestamp}] Tool call structure (first 500 chars): {tool_call_str[:500]}\n"
            )

        # Run enforcement
        enforcer = QualityEnforcer()
        result = await enforcer.enforce(tool_call)

        # Print statistics to stderr
        enforcer.print_stats()

        # Calculate duration
        duration_ms = (time.time() - start_time) * 1000

        # Check if we have violations
        if enforcer.system_message:
            # Choose permission decision based on enforcement mode
            if ENFORCEMENT_MODE == "block":
                # Block mode: prevent write execution
                permission_decision = "deny"
                exit_code = 1  # Bash wrapper converts to exit 2
                success = False
            else:
                # Warn mode: allow write but show warning
                permission_decision = "allow"
                exit_code = 0
                success = True

            # Use OFFICIAL Claude Code blocking/warning mechanism
            output = {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": permission_decision,
                    "permissionDecisionReason": enforcer.system_message,
                }
            }

            # Output result to stdout
            json.dump(output, sys.stdout, indent=2)
            print()  # Add newline

        else:
            # No violations, allow the operation
            output = result

            # Output result to stdout
            json.dump(output, sys.stdout, indent=2)
            print()  # Add newline

        # Track execution with PostgreSQL tracing (fire-and-forget)
        if tracer and correlation_id:
            try:
                asyncio.create_task(
                    tracer.track_hook_execution(
                        correlation_id=correlation_id,
                        hook_name="pre-tool-use-quality",
                        tool_name=tool_name,
                        duration_ms=duration_ms,
                        success=success,
                        metadata={
                            "violations_found": enforcer.stats.get(
                                "violations_found", 0
                            ),
                            "corrections_applied": enforcer.stats.get(
                                "corrections_applied", 0
                            ),
                            "corrections_suggested": enforcer.stats.get(
                                "corrections_suggested", 0
                            ),
                            "file_path": file_path,
                            "language": enforcer._detect_language(file_path),
                        },
                    )
                )
            except Exception as e:
                # Silent failure - never break hook execution
                print(f"[Tracing] Failed to track execution: {e}", file=sys.stderr)

        return exit_code

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
