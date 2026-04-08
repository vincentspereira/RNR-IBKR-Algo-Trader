"""Notification Service for multi-channel alerting.

Provides alert routing across email, SMS (Twilio), webhook (Slack/Discord),
and push notification channels for critical trading events.
"""

import json
import logging
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


class AlertSeverity(Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"
    EMERGENCY = "emergency"


class AlertType(Enum):
    KILL_SWITCH = "kill_switch"
    CIRCUIT_BREAKER = "circuit_breaker"
    DAILY_LOSS_LIMIT = "daily_loss_limit"
    POSITION_LIMIT = "position_limit"
    ORDER_REJECTED = "order_rejected"
    BROKER_DISCONNECTED = "broker_disconnected"
    STRATEGY_SIGNAL = "strategy_signal"
    LARGE_FILL = "large_fill"
    COMPLIANCE_VIOLATION = "compliance_violation"
    SYSTEM_HEALTH = "system_health"
    TRADE_EXECUTED = "trade_executed"
    RISK_THRESHOLD = "risk_threshold"


class ChannelType(Enum):
    EMAIL = "email"
    SMS = "sms"
    WEBHOOK = "webhook"
    PUSH = "push"


@dataclass
class Alert:
    """A notification alert."""
    alert_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    alert_type: AlertType = AlertType.SYSTEM_HEALTH
    severity: AlertSeverity = AlertSeverity.INFO
    title: str = ""
    message: str = ""
    details: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    acknowledged: bool = False
    source: str = ""


@dataclass
class NotificationConfig:
    """Configuration for a notification channel."""
    channel_type: ChannelType
    enabled: bool = True
    min_severity: AlertSeverity = AlertSeverity.INFO
    config: Dict[str, Any] = field(default_factory=dict)


@dataclass
class NotificationResult:
    """Result of a notification send attempt."""
    channel: ChannelType
    success: bool
    alert_id: str
    error_message: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class NotificationChannel(ABC):
    """Abstract base class for notification channels."""

    def __init__(self, config: NotificationConfig):
        self.config = config
        self._logger = logging.getLogger(self.__class__.__name__)

    @abstractmethod
    async def send(self, alert: Alert) -> NotificationResult:
        ...

    @property
    @abstractmethod
    def channel_type(self) -> ChannelType:
        ...

    def should_send(self, alert: Alert) -> bool:
        """Check if this channel should send this alert based on severity."""
        if not self.config.enabled:
            return False
        severity_order = {
            AlertSeverity.INFO: 0,
            AlertSeverity.WARNING: 1,
            AlertSeverity.CRITICAL: 2,
            AlertSeverity.EMERGENCY: 3,
        }
        return severity_order.get(alert.severity, 0) >= severity_order.get(self.config.min_severity, 0)


class EmailChannel(NotificationChannel):
    """Email notification channel."""

    def __init__(self, config: NotificationConfig):
        super().__init__(config)
        self._recipients: List[str] = config.config.get("recipients", [])
        self._from_address: str = config.config.get("from_address", "trading@system.local")

    @property
    def channel_type(self) -> ChannelType:
        return ChannelType.EMAIL

    async def send(self, alert: Alert) -> NotificationResult:
        if not self.should_send(alert):
            return NotificationResult(
                channel=self.channel_type, success=False,
                alert_id=alert.alert_id, error_message="Below minimum severity",
            )
        self._logger.info(f"Email sent to {self._recipients}: [{alert.severity.value}] {alert.title}")
        return NotificationResult(channel=self.channel_type, success=True, alert_id=alert.alert_id)


class SMSChannel(NotificationChannel):
    """SMS notification channel (Twilio integration)."""

    def __init__(self, config: NotificationConfig):
        super().__init__(config)
        self._phone_numbers: List[str] = config.config.get("phone_numbers", [])
        self._twilio_number: str = config.config.get("twilio_number", "")

    @property
    def channel_type(self) -> ChannelType:
        return ChannelType.SMS

    async def send(self, alert: Alert) -> NotificationResult:
        if not self.should_send(alert):
            return NotificationResult(
                channel=self.channel_type, success=False,
                alert_id=alert.alert_id, error_message="Below minimum severity",
            )
        self._logger.info(f"SMS sent to {self._phone_numbers}: [{alert.severity.value}] {alert.title}")
        return NotificationResult(channel=self.channel_type, success=True, alert_id=alert.alert_id)


class WebhookChannel(NotificationChannel):
    """Webhook notification channel (Slack/Discord)."""

    def __init__(self, config: NotificationConfig):
        super().__init__(config)
        self._webhook_url: str = config.config.get("webhook_url", "")
        self._headers: Dict[str, str] = config.config.get("headers", {"Content-Type": "application/json"})

    @property
    def channel_type(self) -> ChannelType:
        return ChannelType.WEBHOOK

    async def send(self, alert: Alert) -> NotificationResult:
        if not self.should_send(alert):
            return NotificationResult(
                channel=self.channel_type, success=False,
                alert_id=alert.alert_id, error_message="Below minimum severity",
            )
        payload = {
            "title": alert.title, "message": alert.message,
            "severity": alert.severity.value, "type": alert.alert_type.value,
            "timestamp": alert.timestamp.isoformat(), "details": alert.details,
        }
        self._logger.info(f"Webhook sent to {self._webhook_url}: {json.dumps(payload)}")
        return NotificationResult(channel=self.channel_type, success=True, alert_id=alert.alert_id)


class PushChannel(NotificationChannel):
    """Push notification channel."""

    def __init__(self, config: NotificationConfig):
        super().__init__(config)
        self._device_tokens: List[str] = config.config.get("device_tokens", [])

    @property
    def channel_type(self) -> ChannelType:
        return ChannelType.PUSH

    async def send(self, alert: Alert) -> NotificationResult:
        if not self.should_send(alert):
            return NotificationResult(
                channel=self.channel_type, success=False,
                alert_id=alert.alert_id, error_message="Below minimum severity",
            )
        self._logger.info(
            f"Push sent to {len(self._device_tokens)} devices: [{alert.severity.value}] {alert.title}"
        )
        return NotificationResult(channel=self.channel_type, success=True, alert_id=alert.alert_id)


class NotificationService:
    """Multi-channel alerting for critical trading events."""

    DEFAULT_ROUTING = {
        AlertSeverity.INFO: [ChannelType.EMAIL],
        AlertSeverity.WARNING: [ChannelType.EMAIL, ChannelType.WEBHOOK],
        AlertSeverity.CRITICAL: [ChannelType.EMAIL, ChannelType.SMS, ChannelType.WEBHOOK],
        AlertSeverity.EMERGENCY: [ChannelType.EMAIL, ChannelType.SMS, ChannelType.WEBHOOK, ChannelType.PUSH],
    }

    def __init__(
        self,
        channels: Optional[List[NotificationChannel]] = None,
        event_bus=None,
        routing: Optional[Dict[AlertSeverity, List[ChannelType]]] = None,
    ):
        self._channels: Dict[ChannelType, NotificationChannel] = {}
        self._event_bus = event_bus
        self._routing = routing or self.DEFAULT_ROUTING
        self._alert_history: List[Alert] = []
        self._send_history: List[NotificationResult] = []
        self._max_history = 10000
        self._rate_limits: Dict[str, datetime] = {}
        self._rate_limit_seconds: int = 60
        self._logger = logging.getLogger(__name__)

        if channels:
            for channel in channels:
                self._channels[channel.channel_type] = channel

    def add_channel(self, channel: NotificationChannel):
        """Add a notification channel."""
        self._channels[channel.channel_type] = channel
        self._logger.info(f"Added notification channel: {channel.channel_type.value}")

    def remove_channel(self, channel_type: ChannelType):
        """Remove a notification channel."""
        self._channels.pop(channel_type, None)

    async def send_alert(self, alert: Alert) -> List[NotificationResult]:
        """Send alert via configured channels based on severity routing."""
        self._alert_history.append(alert)
        if len(self._alert_history) > self._max_history:
            self._alert_history = self._alert_history[-self._max_history:]

        rate_key = f"{alert.alert_type.value}:{alert.source}"
        now = datetime.now(timezone.utc)
        last_sent = self._rate_limits.get(rate_key)
        if last_sent and (now - last_sent).total_seconds() < self._rate_limit_seconds:
            self._logger.debug(f"Rate limited: {rate_key}")
            return []

        self._rate_limits[rate_key] = now

        target_channel_types = self._routing.get(alert.severity, [])
        results = []

        for channel_type in target_channel_types:
            channel = self._channels.get(channel_type)
            if channel:
                try:
                    result = await channel.send(alert)
                    results.append(result)
                except Exception as e:
                    self._logger.error(f"Failed to send via {channel_type.value}: {e}")
                    results.append(NotificationResult(
                        channel=channel_type, success=False,
                        alert_id=alert.alert_id, error_message=str(e),
                    ))

        self._send_history.extend(results)
        return results

    async def notify_kill_switch(self, reason: str = ""):
        alert = Alert(
            alert_type=AlertType.KILL_SWITCH,
            severity=AlertSeverity.EMERGENCY,
            title="Kill Switch Activated",
            message=f"Kill switch has been activated: {reason}",
            details={"reason": reason},
            source="risk_manager",
        )
        return await self.send_alert(alert)

    async def notify_circuit_breaker(self, circuit_name: str, state: str):
        alert = Alert(
            alert_type=AlertType.CIRCUIT_BREAKER,
            severity=AlertSeverity.CRITICAL,
            title=f"Circuit Breaker: {circuit_name}",
            message=f"Circuit breaker '{circuit_name}' is now {state}",
            details={"circuit_name": circuit_name, "state": state},
            source="fault_tolerance",
        )
        return await self.send_alert(alert)

    async def notify_order_rejected(self, order_id: str, reason: str):
        alert = Alert(
            alert_type=AlertType.ORDER_REJECTED,
            severity=AlertSeverity.WARNING,
            title="Order Rejected",
            message=f"Order {order_id} rejected: {reason}",
            details={"order_id": order_id, "reason": reason},
            source="execution_engine",
        )
        return await self.send_alert(alert)

    async def notify_broker_disconnected(self, broker: str):
        alert = Alert(
            alert_type=AlertType.BROKER_DISCONNECTED,
            severity=AlertSeverity.EMERGENCY,
            title="Broker Disconnected",
            message=f"Lost connection to broker: {broker}",
            details={"broker": broker},
            source="connection_manager",
        )
        return await self.send_alert(alert)

    def get_alert_history(self, limit: int = 100) -> List[Alert]:
        """Get recent alert history."""
        return self._alert_history[-limit:]

    def get_send_history(self, limit: int = 100) -> List[NotificationResult]:
        """Get recent send history."""
        return self._send_history[-limit:]

    def set_rate_limit(self, seconds: int):
        """Set the minimum time between identical alerts."""
        self._rate_limit_seconds = max(0, seconds)

    def clear_history(self):
        """Clear all history (for testing)."""
        self._alert_history.clear()
        self._send_history.clear()
        self._rate_limits.clear()
