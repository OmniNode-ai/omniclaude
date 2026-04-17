# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""env_sync_alert check — scans env-sync.log and critical logs for failures.

Run directly: uv run python -m plugins.onex.skills.env_sync_alert.check
Or invoked by the overseer tick cron prompt.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

_CRITICAL_PATTERN = re.compile(r"\b(ERROR|CRITICAL)\b", re.IGNORECASE)
_SUCCESS_PATTERN = re.compile(r"\bSUCCESS\b")
_FAILURE_PATTERN = re.compile(r"\bFAILURE\b")
_TIMESTAMP_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[^\s]*)")


@dataclass
class LogScanResult:
    log_path: Path
    matched_line: str
    pattern: str


@dataclass
class LogScanEnvResult:
    error_count: int
    last_success_age_seconds: float | None
    last_success_ts: str | None
    last_run_line: str | None


# Alias used by tests
ScanResult = LogScanEnvResult


@dataclass
class CheckResult:
    alert_fired: bool
    env_sync_result: LogScanEnvResult
    critical_log_findings: list[LogScanResult] = field(default_factory=list)
    friction_path: Path | None = None
    linear_ticket_id: str | None = None


@dataclass
class EnvSyncAlertConfig:
    state_dir: Path
    error_threshold: int = 0
    success_age_threshold_seconds: float = 3600.0
    create_linear_ticket: bool = True
    log_paths_extra: list[Path] = field(default_factory=list)


def _parse_timestamp(line: str) -> datetime | None:
    m = _TIMESTAMP_RE.match(line)
    if not m:
        return None
    ts_str = m.group(1)
    try:
        return datetime(
            int(ts_str[0:4]),
            int(ts_str[5:7]),
            int(ts_str[8:10]),
            int(ts_str[11:13]),
            int(ts_str[14:16]),
            int(ts_str[17:19]),
            tzinfo=UTC,
        )
    except (ValueError, IndexError):
        return None


def check_env_sync_log(log_path: Path, *, now: datetime) -> LogScanEnvResult:
    """Scan env-sync.log for error count since last success and success age."""
    if not log_path.exists():
        return LogScanEnvResult(
            error_count=1,
            last_success_age_seconds=None,
            last_success_ts=None,
            last_run_line=None,
        )

    lines = [ln.rstrip() for ln in log_path.read_text().splitlines() if ln.strip()]
    if not lines:
        return LogScanEnvResult(
            error_count=0,
            last_success_age_seconds=None,
            last_success_ts=None,
            last_run_line=None,
        )

    last_success_idx: int | None = None
    last_success_ts: str | None = None
    last_success_age: float | None = None

    for i, line in enumerate(reversed(lines)):
        if _SUCCESS_PATTERN.search(line):
            last_success_idx = len(lines) - 1 - i
            m = _TIMESTAMP_RE.match(line)
            last_success_ts = m.group(1) if m else line.split()[0]
            dt = _parse_timestamp(line)
            if dt:
                last_success_age = (now - dt).total_seconds()
            break

    if last_success_idx is None:
        # No success line at all — count all failure lines
        error_count = sum(1 for ln in lines if _FAILURE_PATTERN.search(ln))
        return LogScanEnvResult(
            error_count=error_count,
            last_success_age_seconds=None,
            last_success_ts=None,
            last_run_line=lines[-1] if lines else None,
        )

    # Count failures AFTER the last success
    errors_after_success = sum(
        1 for ln in lines[last_success_idx + 1 :] if _FAILURE_PATTERN.search(ln)
    )

    return LogScanEnvResult(
        error_count=errors_after_success,
        last_success_age_seconds=last_success_age,
        last_success_ts=last_success_ts,
        last_run_line=lines[-1],
    )


def check_critical_log_patterns(log_paths: list[Path]) -> list[LogScanResult]:
    """Scan logs for ERROR/CRITICAL pattern lines."""
    findings: list[LogScanResult] = []
    for path in log_paths:
        if not path.exists():
            continue
        try:
            for line in path.read_text().splitlines():
                if _CRITICAL_PATTERN.search(line):
                    findings.append(
                        LogScanResult(
                            log_path=path,
                            matched_line=line.strip(),
                            pattern="ERROR|CRITICAL",
                        )
                    )
        except OSError as exc:
            logger.warning("Could not read %s: %s", path, exc)
    return findings


def _write_friction_yaml(
    friction_dir: Path, data: dict[str, object], now: datetime
) -> Path:
    friction_dir.mkdir(parents=True, exist_ok=True)
    ts = now.strftime("%Y-%m-%d-%H-%M-%S")
    path = friction_dir / f"env-sync-alert-{ts}.yaml"
    tmp = path.with_suffix(".yaml.tmp")
    tmp.write_text(yaml.dump(data, default_flow_style=False, allow_unicode=True))
    tmp.rename(path)
    return path


def _should_alert(
    env_result: LogScanEnvResult,
    config: EnvSyncAlertConfig,
) -> bool:
    if env_result.last_success_age_seconds is None:
        return env_result.error_count > config.error_threshold
    age_exceeded = (
        env_result.last_success_age_seconds > config.success_age_threshold_seconds
    )
    errors_present = env_result.error_count > config.error_threshold
    return errors_present and age_exceeded


def run_alert_check(
    config: EnvSyncAlertConfig, *, now: datetime | None = None
) -> CheckResult:
    """Run the full alert check. Write friction YAML if alert fires."""
    if now is None:
        now = datetime.now(UTC)

    env_sync_log = config.state_dir / "logs" / "env-sync.log"
    env_result = check_env_sync_log(env_sync_log, now=now)

    extra_logs = [
        config.state_dir / "logs" / "hooks.log",
        config.state_dir / "logs" / "pipeline-trace.log",
        *config.log_paths_extra,
    ]
    critical_findings = check_critical_log_patterns(extra_logs)

    should_fire = _should_alert(env_result, config)

    if not should_fire:
        return CheckResult(
            alert_fired=False,
            env_sync_result=env_result,
            critical_log_findings=critical_findings,
        )

    severity = "critical" if env_result.error_count >= 5 else "high"
    friction_data: dict[str, object] = {
        "surface": "config/env-sync-infisical",
        "severity": severity,
        "skill": "env_sync_alert",
        "description": (
            f"seed-infisical has {env_result.error_count} error(s) since last success. "
            f"Last success: {env_result.last_success_ts or 'NEVER'}. "
            f"Last run: {env_result.last_run_line or 'unknown'}."
        ),
        "timestamp": now.isoformat(),
        "session_id": os.environ.get("CLAUDE_SESSION_ID", "unknown"),
        "context_ticket_id": "OMN-8868",
    }

    friction_dir = config.state_dir / "friction"
    friction_path = _write_friction_yaml(friction_dir, friction_data, now)
    logger.warning("env_sync_alert: alert fired, friction written to %s", friction_path)

    linear_ticket_id: str | None = None
    if config.create_linear_ticket:
        linear_ticket_id = _create_or_update_linear_ticket(friction_data, env_result)

    return CheckResult(
        alert_fired=True,
        env_sync_result=env_result,
        critical_log_findings=critical_findings,
        friction_path=friction_path,
        linear_ticket_id=linear_ticket_id,
    )


def _create_or_update_linear_ticket(
    friction_data: dict[str, object],
    env_result: LogScanEnvResult,
) -> str | None:
    """Create a Linear ticket for the env-sync failure. Returns ticket ID or None."""
    try:
        import subprocess

        title = f"env-sync.log: {env_result.error_count} failures, last success {env_result.last_success_ts or 'NEVER'}"
        body = friction_data.get("description", "")
        result = subprocess.run(
            ["gh", "api", "graphql", "--silent"],
            input=f'mutation {{ createIssue(input: {{ title: "{title}", description: "{body}", teamId: "OMN" }}) {{ issue {{ identifier }} }} }}',
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        if result.returncode == 0:
            import json as _json

            data = _json.loads(result.stdout)
            return (
                data.get("data", {})
                .get("createIssue", {})
                .get("issue", {})
                .get("identifier")
            )
    except Exception as exc:
        logger.warning("env_sync_alert: linear ticket creation failed: %s", exc)
    return None


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO)
    raw_state_dir = os.environ.get("ONEX_STATE_DIR")
    if not raw_state_dir:
        raise SystemExit("ONEX_STATE_DIR env var is required — set it in ~/.omnibase/.env")
    state_dir = Path(raw_state_dir)
    config = EnvSyncAlertConfig(state_dir=state_dir)
    result = run_alert_check(config)
    if result.alert_fired:
        print(f"ALERT: friction written to {result.friction_path}")
        sys.exit(1)
    else:
        print("OK: no env-sync failures requiring alert")
        sys.exit(0)
