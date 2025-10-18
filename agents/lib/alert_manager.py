"""
Alert Management System

Provides advanced alert management capabilities including:
- Alert threshold configuration
- Alert routing and escalation
- Alert grouping and deduplication
- Alert history and analytics
- Integration with monitoring system

ONEX Pattern: Effect node (alert state management and notification)
Performance Target: <100ms alert processing, <200ms escalation
"""

import asyncio
import json
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
import yaml

from .monitoring import AlertSeverity, MonitoringAlert

logger = logging.getLogger(__name__)


class AlertStatus(Enum):
    """Alert lifecycle status."""

    ACTIVE = "active"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"
    SUPPRESSED = "suppressed"


class EscalationLevel(Enum):
    """Alert escalation levels."""

    LEVEL_1 = "level_1"  # Immediate notification
    LEVEL_2 = "level_2"  # Escalated after X minutes
    LEVEL_3 = "level_3"  # Critical escalation


@dataclass
class AlertRule:
    """Alert rule configuration."""

    name: str
    metric_name: str
    threshold: float
    severity: AlertSeverity
    comparison: str  # 'greater_than', 'less_than', 'equals'
    duration_seconds: int = 0  # Alert after sustained breach
    description: str = ""
    enabled: bool = True
    labels: Dict[str, str] = field(default_factory=dict)


@dataclass
class AlertChannel:
    """Alert notification channel."""

    name: str
    channel_type: str  # 'log', 'webhook', 'email', etc.
    config: Dict[str, Any] = field(default_factory=dict)
    severity_filter: Optional[Set[AlertSeverity]] = None
    enabled: bool = True


@dataclass
class EscalationPolicy:
    """Alert escalation policy."""

    name: str
    initial_delay_seconds: int = 300  # 5 minutes
    escalation_levels: List[Dict[str, Any]] = field(default_factory=list)
    repeat_interval_seconds: int = 1800  # 30 minutes
    max_escalations: int = 3


@dataclass
class ManagedAlert:
    """Alert with management metadata."""

    alert: MonitoringAlert
    status: AlertStatus
    acknowledged_by: Optional[str] = None
    acknowledged_at: Optional[datetime] = None
    resolved_at: Optional[datetime] = None
    escalation_level: EscalationLevel = EscalationLevel.LEVEL_1
    escalation_count: int = 0
    suppressed_until: Optional[datetime] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class AlertManager:
    """
    Advanced alert management system for Phase 7 monitoring.

    Features:
    - Alert rule configuration and evaluation
    - Alert grouping and deduplication
    - Multi-channel alert routing
    - Escalation policies and automation
    - Alert acknowledgement and resolution
    - Alert suppression and maintenance windows
    - Alert analytics and history

    Performance:
    - Alert processing: <100ms
    - Escalation: <200ms
    - Rule evaluation: <50ms
    """

    def __init__(self, config_path: Optional[Path] = None):
        """Initialize alert manager.

        Args:
            config_path: Optional path to alert configuration YAML
        """
        self.rules: Dict[str, AlertRule] = {}
        self.channels: Dict[str, AlertChannel] = {}
        self.policies: Dict[str, EscalationPolicy] = {}
        self.active_alerts: Dict[str, ManagedAlert] = {}
        self.alert_history: List[ManagedAlert] = []
        self._lock = asyncio.Lock()

        # Alert grouping (by metric + labels)
        self.alert_groups: Dict[str, List[str]] = defaultdict(list)

        # Maintenance windows
        self.maintenance_windows: List[Dict[str, Any]] = []

        # Load configuration if provided
        if config_path and config_path.exists():
            self._load_config(config_path)

        logger.info("AlertManager initialized")

    def _load_config(self, config_path: Path) -> None:
        """Load alert configuration from YAML file.

        Args:
            config_path: Path to configuration file
        """
        try:
            with open(config_path, "r") as f:
                config = yaml.safe_load(f)

            # Load alert rules
            if "rules" in config:
                for rule_config in config["rules"]:
                    rule = AlertRule(
                        name=rule_config["name"],
                        metric_name=rule_config["metric_name"],
                        threshold=rule_config["threshold"],
                        severity=AlertSeverity(rule_config["severity"]),
                        comparison=rule_config.get("comparison", "greater_than"),
                        duration_seconds=rule_config.get("duration_seconds", 0),
                        description=rule_config.get("description", ""),
                        enabled=rule_config.get("enabled", True),
                        labels=rule_config.get("labels", {}),
                    )
                    self.rules[rule.name] = rule

            # Load channels
            if "channels" in config:
                for channel_config in config["channels"]:
                    severity_filter = None
                    if "severity_filter" in channel_config:
                        severity_filter = {AlertSeverity(s) for s in channel_config["severity_filter"]}

                    channel = AlertChannel(
                        name=channel_config["name"],
                        channel_type=channel_config["type"],
                        config=channel_config.get("config", {}),
                        severity_filter=severity_filter,
                        enabled=channel_config.get("enabled", True),
                    )
                    self.channels[channel.name] = channel

            # Load escalation policies
            if "escalation_policies" in config:
                for policy_config in config["escalation_policies"]:
                    policy = EscalationPolicy(
                        name=policy_config["name"],
                        initial_delay_seconds=policy_config.get("initial_delay_seconds", 300),
                        escalation_levels=policy_config.get("escalation_levels", []),
                        repeat_interval_seconds=policy_config.get("repeat_interval_seconds", 1800),
                        max_escalations=policy_config.get("max_escalations", 3),
                    )
                    self.policies[policy.name] = policy

            logger.info(
                f"Loaded alert configuration: {len(self.rules)} rules, "
                f"{len(self.channels)} channels, {len(self.policies)} policies"
            )

        except Exception as e:
            logger.error(f"Failed to load alert configuration: {e}", exc_info=True)

    def add_rule(self, rule: AlertRule) -> None:
        """Add an alert rule.

        Args:
            rule: Alert rule to add
        """
        self.rules[rule.name] = rule
        logger.info(f"Added alert rule: {rule.name}")

    def remove_rule(self, rule_name: str) -> bool:
        """Remove an alert rule.

        Args:
            rule_name: Name of rule to remove

        Returns:
            True if rule was removed
        """
        if rule_name in self.rules:
            del self.rules[rule_name]
            logger.info(f"Removed alert rule: {rule_name}")
            return True
        return False

    def add_channel(self, channel: AlertChannel) -> None:
        """Add an alert notification channel.

        Args:
            channel: Alert channel to add
        """
        self.channels[channel.name] = channel
        logger.info(f"Added alert channel: {channel.name} ({channel.channel_type})")

    def add_escalation_policy(self, policy: EscalationPolicy) -> None:
        """Add an escalation policy.

        Args:
            policy: Escalation policy to add
        """
        self.policies[policy.name] = policy
        logger.info(f"Added escalation policy: {policy.name}")

    async def process_alert(self, alert: MonitoringAlert, escalation_policy: Optional[str] = None) -> ManagedAlert:
        """Process an incoming alert.

        Args:
            alert: Monitoring alert to process
            escalation_policy: Optional escalation policy name

        Returns:
            Managed alert with status
        """
        async with self._lock:
            # Check if this is a duplicate alert
            existing = self._find_duplicate_alert(alert)
            if existing:
                # Update existing alert
                existing.alert = alert
                existing.escalation_count += 1
                logger.debug(f"Updated existing alert: {alert.alert_id}")
                return existing

            # Create new managed alert
            managed_alert = ManagedAlert(alert=alert, status=AlertStatus.ACTIVE)

            # Add to active alerts
            self.active_alerts[alert.alert_id] = managed_alert

            # Group alert
            group_key = self._get_group_key(alert)
            self.alert_groups[group_key].append(alert.alert_id)

            logger.info(
                f"New alert: {alert.severity.value} - {alert.message}",
                extra={"alert_id": alert.alert_id, "component": alert.component},
            )

            # Route alert to channels
            await self._route_alert(managed_alert)

            # Start escalation if policy specified
            if escalation_policy and escalation_policy in self.policies:
                asyncio.create_task(self._handle_escalation(managed_alert, self.policies[escalation_policy]))

            return managed_alert

    def _find_duplicate_alert(self, alert: MonitoringAlert) -> Optional[ManagedAlert]:
        """Find duplicate alert based on metric and labels.

        Args:
            alert: Alert to check for duplicates

        Returns:
            Existing managed alert if duplicate found
        """
        for managed in self.active_alerts.values():
            if (
                managed.alert.metric_name == alert.metric_name
                and managed.alert.labels == alert.labels
                and managed.alert.severity == alert.severity
            ):
                return managed
        return None

    def _get_group_key(self, alert: MonitoringAlert) -> str:
        """Generate group key for alert grouping.

        Args:
            alert: Alert to generate key for

        Returns:
            Group key string
        """
        label_str = json.dumps(alert.labels, sort_keys=True)
        return f"{alert.metric_name}:{label_str}"

    async def _route_alert(self, managed_alert: ManagedAlert) -> None:
        """Route alert to appropriate channels.

        Args:
            managed_alert: Alert to route
        """
        alert = managed_alert.alert

        for channel in self.channels.values():
            if not channel.enabled:
                continue

            # Check severity filter
            if channel.severity_filter and alert.severity not in channel.severity_filter:
                continue

            # Send to channel
            try:
                await self._send_to_channel(channel, alert)
            except Exception as e:
                logger.error(f"Failed to send alert to channel {channel.name}: {e}", exc_info=True)

    async def _send_to_channel(self, channel: AlertChannel, alert: MonitoringAlert) -> None:
        """Send alert to a specific channel.

        Args:
            channel: Channel to send to
            alert: Alert to send
        """
        if channel.channel_type == "log":
            # Log channel - write to logger
            log_level = {
                AlertSeverity.CRITICAL: logging.CRITICAL,
                AlertSeverity.WARNING: logging.WARNING,
                AlertSeverity.INFO: logging.INFO,
            }.get(alert.severity, logging.INFO)

            logger.log(
                log_level,
                f"[ALERT] {alert.message}",
                extra={
                    "alert_id": alert.alert_id,
                    "severity": alert.severity.value,
                    "component": alert.component,
                    "metric": alert.metric_name,
                },
            )

        elif channel.channel_type == "webhook":
            # Webhook channel - send HTTP POST
            # This would require aiohttp or similar
            logger.info(f"Would send webhook to {channel.config.get('url')}: {alert.message}")

        elif channel.channel_type == "email":
            # Email channel - send email notification
            logger.info(f"Would send email to {channel.config.get('recipients')}: {alert.message}")

        else:
            logger.warning(f"Unknown channel type: {channel.channel_type}")

    async def _handle_escalation(self, managed_alert: ManagedAlert, policy: EscalationPolicy) -> None:
        """Handle alert escalation according to policy.

        Args:
            managed_alert: Alert to escalate
            policy: Escalation policy to follow
        """
        # Wait for initial delay
        await asyncio.sleep(policy.initial_delay_seconds)

        # Check if alert is still active
        if managed_alert.status != AlertStatus.ACTIVE:
            return

        # Escalate through levels
        for level_idx, level_config in enumerate(policy.escalation_levels):
            if managed_alert.escalation_count >= policy.max_escalations:
                break

            # Perform escalation
            managed_alert.escalation_level = EscalationLevel(f"level_{level_idx + 1}")
            managed_alert.escalation_count += 1

            logger.warning(
                f"Escalating alert {managed_alert.alert.alert_id} to level {level_idx + 1}",
                extra={"alert_id": managed_alert.alert.alert_id},
            )

            # Notify escalation channels
            for channel_name in level_config.get("channels", []):
                if channel_name in self.channels:
                    await self._send_to_channel(self.channels[channel_name], managed_alert.alert)

            # Wait for repeat interval
            if level_idx < len(policy.escalation_levels) - 1:
                await asyncio.sleep(policy.repeat_interval_seconds)

    async def acknowledge_alert(self, alert_id: str, acknowledged_by: str, note: Optional[str] = None) -> bool:
        """Acknowledge an alert.

        Args:
            alert_id: Alert ID to acknowledge
            acknowledged_by: User/system acknowledging
            note: Optional acknowledgement note

        Returns:
            True if alert was acknowledged
        """
        async with self._lock:
            if alert_id not in self.active_alerts:
                return False

            managed_alert = self.active_alerts[alert_id]
            managed_alert.status = AlertStatus.ACKNOWLEDGED
            managed_alert.acknowledged_by = acknowledged_by
            managed_alert.acknowledged_at = datetime.now(timezone.utc)

            if note:
                managed_alert.metadata["acknowledgement_note"] = note

            logger.info(f"Alert acknowledged by {acknowledged_by}: {alert_id}", extra={"alert_id": alert_id})

            return True

    async def resolve_alert(self, alert_id: str, resolution_note: Optional[str] = None) -> bool:
        """Resolve an alert.

        Args:
            alert_id: Alert ID to resolve
            resolution_note: Optional resolution note

        Returns:
            True if alert was resolved
        """
        async with self._lock:
            if alert_id not in self.active_alerts:
                return False

            managed_alert = self.active_alerts[alert_id]
            managed_alert.status = AlertStatus.RESOLVED
            managed_alert.resolved_at = datetime.now(timezone.utc)

            if resolution_note:
                managed_alert.metadata["resolution_note"] = resolution_note

            # Move to history
            self.alert_history.append(managed_alert)
            del self.active_alerts[alert_id]

            # Remove from group
            group_key = self._get_group_key(managed_alert.alert)
            if alert_id in self.alert_groups[group_key]:
                self.alert_groups[group_key].remove(alert_id)

            logger.info(f"Alert resolved: {alert_id}", extra={"alert_id": alert_id})

            return True

    async def suppress_alert(self, alert_id: str, duration_minutes: int, reason: Optional[str] = None) -> bool:
        """Suppress an alert for a specified duration.

        Args:
            alert_id: Alert ID to suppress
            duration_minutes: Suppression duration in minutes
            reason: Optional suppression reason

        Returns:
            True if alert was suppressed
        """
        async with self._lock:
            if alert_id not in self.active_alerts:
                return False

            managed_alert = self.active_alerts[alert_id]
            managed_alert.status = AlertStatus.SUPPRESSED
            managed_alert.suppressed_until = datetime.now(timezone.utc) + timedelta(minutes=duration_minutes)

            if reason:
                managed_alert.metadata["suppression_reason"] = reason

            logger.info(f"Alert suppressed for {duration_minutes} minutes: {alert_id}", extra={"alert_id": alert_id})

            return True

    def get_active_alerts(
        self,
        severity: Optional[AlertSeverity] = None,
        component: Optional[str] = None,
        status: Optional[AlertStatus] = None,
    ) -> List[ManagedAlert]:
        """Get active alerts with optional filtering.

        Args:
            severity: Filter by severity
            component: Filter by component
            status: Filter by status

        Returns:
            List of managed alerts
        """
        alerts = list(self.active_alerts.values())

        if severity:
            alerts = [a for a in alerts if a.alert.severity == severity]

        if component:
            alerts = [a for a in alerts if a.alert.component == component]

        if status:
            alerts = [a for a in alerts if a.status == status]

        return sorted(alerts, key=lambda a: a.alert.created_at, reverse=True)

    def get_alert_statistics(self, hours: int = 24) -> Dict[str, Any]:
        """Get alert statistics for the specified time window.

        Args:
            hours: Number of hours to look back

        Returns:
            Dictionary of alert statistics
        """
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

        # Count alerts from history
        recent_alerts = [a for a in self.alert_history if a.alert.created_at >= cutoff]

        # Add active alerts
        recent_alerts.extend(self.active_alerts.values())

        stats = {
            "total_alerts": len(recent_alerts),
            "active_alerts": len(self.active_alerts),
            "by_severity": {"critical": 0, "warning": 0, "info": 0},
            "by_component": defaultdict(int),
            "by_status": {"active": 0, "acknowledged": 0, "resolved": 0, "suppressed": 0},
            "avg_resolution_time_minutes": 0.0,
            "escalated_count": 0,
        }

        resolution_times = []

        for alert in recent_alerts:
            # Count by severity
            stats["by_severity"][alert.alert.severity.value] += 1

            # Count by component
            stats["by_component"][alert.alert.component] += 1

            # Count by status
            stats["by_status"][alert.status.value] += 1

            # Track resolution times
            if alert.resolved_at:
                resolution_time = (alert.resolved_at - alert.alert.created_at).total_seconds() / 60
                resolution_times.append(resolution_time)

            # Count escalations
            if alert.escalation_count > 0:
                stats["escalated_count"] += 1

        # Calculate average resolution time
        if resolution_times:
            stats["avg_resolution_time_minutes"] = sum(resolution_times) / len(resolution_times)

        return stats

    def export_config(self) -> Dict[str, Any]:
        """Export alert configuration.

        Returns:
            Dictionary of alert configuration
        """
        return {
            "rules": [
                {
                    "name": rule.name,
                    "metric_name": rule.metric_name,
                    "threshold": rule.threshold,
                    "severity": rule.severity.value,
                    "comparison": rule.comparison,
                    "duration_seconds": rule.duration_seconds,
                    "description": rule.description,
                    "enabled": rule.enabled,
                    "labels": rule.labels,
                }
                for rule in self.rules.values()
            ],
            "channels": [
                {
                    "name": channel.name,
                    "type": channel.channel_type,
                    "config": channel.config,
                    "severity_filter": [s.value for s in channel.severity_filter] if channel.severity_filter else None,
                    "enabled": channel.enabled,
                }
                for channel in self.channels.values()
            ],
            "escalation_policies": [
                {
                    "name": policy.name,
                    "initial_delay_seconds": policy.initial_delay_seconds,
                    "escalation_levels": policy.escalation_levels,
                    "repeat_interval_seconds": policy.repeat_interval_seconds,
                    "max_escalations": policy.max_escalations,
                }
                for policy in self.policies.values()
            ],
        }


# Global alert manager instance
_alert_manager: Optional[AlertManager] = None


def get_alert_manager(config_path: Optional[Path] = None) -> AlertManager:
    """Get or create global alert manager instance.

    Args:
        config_path: Optional path to alert configuration

    Returns:
        AlertManager instance
    """
    global _alert_manager

    if _alert_manager is None:
        _alert_manager = AlertManager(config_path)

    return _alert_manager


# Convenience functions
async def process_alert(alert: MonitoringAlert, escalation_policy: Optional[str] = None) -> ManagedAlert:
    """Process an alert.

    Args:
        alert: Alert to process
        escalation_policy: Optional escalation policy

    Returns:
        Managed alert
    """
    manager = get_alert_manager()
    return await manager.process_alert(alert, escalation_policy)


async def acknowledge_alert(alert_id: str, acknowledged_by: str, note: Optional[str] = None) -> bool:
    """Acknowledge an alert.

    Args:
        alert_id: Alert ID
        acknowledged_by: Acknowledger
        note: Optional note

    Returns:
        True if acknowledged
    """
    manager = get_alert_manager()
    return await manager.acknowledge_alert(alert_id, acknowledged_by, note)


async def resolve_alert(alert_id: str, resolution_note: Optional[str] = None) -> bool:
    """Resolve an alert.

    Args:
        alert_id: Alert ID
        resolution_note: Optional note

    Returns:
        True if resolved
    """
    manager = get_alert_manager()
    return await manager.resolve_alert(alert_id, resolution_note)


def get_alert_statistics(hours: int = 24) -> Dict[str, Any]:
    """Get alert statistics.

    Args:
        hours: Hours to look back

    Returns:
        Alert statistics dictionary
    """
    manager = get_alert_manager()
    return manager.get_alert_statistics(hours)
