"""Tests for the Notification Service."""

import sys
import os

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "services", "notifications", "src"))

from notification_service import (
    Alert,
    AlertSeverity,
    AlertType,
    ChannelType,
    EmailChannel,
    NotificationChannel,
    NotificationConfig,
    NotificationResult,
    NotificationService,
    PushChannel,
    SMSChannel,
    WebhookChannel,
)


# ---------------------------------------------------------------------------
# Alert dataclass tests
# ---------------------------------------------------------------------------


class TestAlert:
    def test_alert_creation(self):
        alert = Alert(
            alert_type=AlertType.KILL_SWITCH,
            severity=AlertSeverity.EMERGENCY,
            title="Test Alert",
            message="Something happened",
        )
        assert alert.alert_type == AlertType.KILL_SWITCH
        assert alert.severity == AlertSeverity.EMERGENCY
        assert alert.title == "Test Alert"
        assert alert.message == "Something happened"

    def test_alert_defaults(self):
        alert = Alert()
        assert alert.alert_type == AlertType.SYSTEM_HEALTH
        assert alert.severity == AlertSeverity.INFO
        assert alert.title == ""
        assert alert.message == ""
        assert alert.details == {}
        assert alert.acknowledged is False
        assert alert.source == ""
        assert len(alert.alert_id) == 12

    def test_alert_custom_fields(self):
        alert = Alert(
            alert_id="custom123",
            alert_type=AlertType.TRADE_EXECUTED,
            severity=AlertSeverity.WARNING,
            title="Trade Executed",
            message="Buy 100 AAPL @ 150.00",
            details={"symbol": "AAPL", "qty": 100, "price": 150.0},
            source="execution_engine",
            acknowledged=True,
        )
        assert alert.alert_id == "custom123"
        assert alert.alert_type == AlertType.TRADE_EXECUTED
        assert alert.severity == AlertSeverity.WARNING
        assert alert.details["symbol"] == "AAPL"
        assert alert.source == "execution_engine"
        assert alert.acknowledged is True


# ---------------------------------------------------------------------------
# NotificationConfig tests
# ---------------------------------------------------------------------------


class TestNotificationConfig:
    def test_config_creation(self):
        config = NotificationConfig(
            channel_type=ChannelType.EMAIL,
            enabled=False,
            min_severity=AlertSeverity.CRITICAL,
            config={"recipients": ["admin@example.com"]},
        )
        assert config.channel_type == ChannelType.EMAIL
        assert config.enabled is False
        assert config.min_severity == AlertSeverity.CRITICAL
        assert config.config["recipients"] == ["admin@example.com"]

    def test_config_defaults(self):
        config = NotificationConfig(channel_type=ChannelType.SMS)
        assert config.enabled is True
        assert config.min_severity == AlertSeverity.INFO
        assert config.config == {}


# ---------------------------------------------------------------------------
# Channel tests
# ---------------------------------------------------------------------------


class TestEmailChannel:
    def setup_method(self):
        self.config = NotificationConfig(
            channel_type=ChannelType.EMAIL,
            config={"recipients": ["trader@example.com"], "from_address": "alerts@system.local"},
        )
        self.channel = EmailChannel(self.config)

    @pytest.mark.asyncio
    async def test_email_send_success(self):
        alert = Alert(severity=AlertSeverity.WARNING, title="Test Warning", message="Check this")
        result = await self.channel.send(alert)
        assert result.success is True
        assert result.channel == ChannelType.EMAIL
        assert result.alert_id == alert.alert_id

    @pytest.mark.asyncio
    async def test_email_send_below_severity(self):
        config = NotificationConfig(channel_type=ChannelType.EMAIL, min_severity=AlertSeverity.CRITICAL)
        channel = EmailChannel(config)
        alert = Alert(severity=AlertSeverity.INFO, title="Low priority")
        result = await channel.send(alert)
        assert result.success is False
        assert "Below minimum severity" in result.error_message

    def test_email_channel_type(self):
        assert self.channel.channel_type == ChannelType.EMAIL


class TestSMSChannel:
    def setup_method(self):
        self.config = NotificationConfig(
            channel_type=ChannelType.SMS,
            config={"phone_numbers": ["+1234567890"], "twilio_number": "+0987654321"},
        )
        self.channel = SMSChannel(self.config)

    @pytest.mark.asyncio
    async def test_sms_send_success(self):
        alert = Alert(severity=AlertSeverity.CRITICAL, title="Critical Alert", message="Attention")
        result = await self.channel.send(alert)
        assert result.success is True
        assert result.channel == ChannelType.SMS

    @pytest.mark.asyncio
    async def test_sms_send_below_severity(self):
        config = NotificationConfig(channel_type=ChannelType.SMS, min_severity=AlertSeverity.EMERGENCY)
        channel = SMSChannel(config)
        alert = Alert(severity=AlertSeverity.WARNING, title="Not urgent")
        result = await channel.send(alert)
        assert result.success is False
        assert "Below minimum severity" in result.error_message

    def test_sms_channel_type(self):
        assert self.channel.channel_type == ChannelType.SMS


class TestWebhookChannel:
    def setup_method(self):
        self.config = NotificationConfig(
            channel_type=ChannelType.WEBHOOK,
            config={"webhook_url": "https://hooks.slack.example.com/abc"},
        )
        self.channel = WebhookChannel(self.config)

    @pytest.mark.asyncio
    async def test_webhook_send_success(self):
        alert = Alert(severity=AlertSeverity.WARNING, title="Webhook Test", message="Testing", details={"k": "v"})
        result = await self.channel.send(alert)
        assert result.success is True
        assert result.channel == ChannelType.WEBHOOK

    @pytest.mark.asyncio
    async def test_webhook_send_below_severity(self):
        config = NotificationConfig(channel_type=ChannelType.WEBHOOK, min_severity=AlertSeverity.CRITICAL)
        channel = WebhookChannel(config)
        alert = Alert(severity=AlertSeverity.INFO, title="FYI")
        result = await channel.send(alert)
        assert result.success is False

    def test_webhook_channel_type(self):
        assert self.channel.channel_type == ChannelType.WEBHOOK


class TestPushChannel:
    def setup_method(self):
        self.config = NotificationConfig(
            channel_type=ChannelType.PUSH,
            config={"device_tokens": ["token-abc-123"]},
        )
        self.channel = PushChannel(self.config)

    @pytest.mark.asyncio
    async def test_push_send_success(self):
        alert = Alert(severity=AlertSeverity.EMERGENCY, title="Emergency!", message="Act now")
        result = await self.channel.send(alert)
        assert result.success is True
        assert result.channel == ChannelType.PUSH

    @pytest.mark.asyncio
    async def test_push_send_below_severity(self):
        config = NotificationConfig(channel_type=ChannelType.PUSH, min_severity=AlertSeverity.EMERGENCY)
        channel = PushChannel(config)
        alert = Alert(severity=AlertSeverity.CRITICAL, title="Not emergency")
        result = await channel.send(alert)
        assert result.success is False

    def test_push_channel_type(self):
        assert self.channel.channel_type == ChannelType.PUSH


# ---------------------------------------------------------------------------
# NotificationService tests
# ---------------------------------------------------------------------------


def _make_all_channels():
    return [
        EmailChannel(NotificationConfig(channel_type=ChannelType.EMAIL, config={"recipients": ["admin@example.com"]})),
        SMSChannel(NotificationConfig(channel_type=ChannelType.SMS, config={"phone_numbers": ["+1234567890"]})),
        WebhookChannel(NotificationConfig(channel_type=ChannelType.WEBHOOK, config={"webhook_url": "https://hooks.example.com/test"})),
        PushChannel(NotificationConfig(channel_type=ChannelType.PUSH, config={"device_tokens": ["token-1"]})),
    ]


class TestNotificationService:
    def test_initialization(self):
        svc = NotificationService()
        assert len(svc.get_alert_history()) == 0
        assert len(svc.get_send_history()) == 0

    def test_initialization_with_channels(self):
        svc = NotificationService(channels=_make_all_channels())
        assert len(svc._channels) == 4

    def test_add_channel(self):
        svc = NotificationService()
        svc.add_channel(EmailChannel(NotificationConfig(channel_type=ChannelType.EMAIL)))
        assert ChannelType.EMAIL in svc._channels

    def test_remove_channel(self):
        svc = NotificationService()
        svc.add_channel(EmailChannel(NotificationConfig(channel_type=ChannelType.EMAIL)))
        svc.remove_channel(ChannelType.EMAIL)
        assert ChannelType.EMAIL not in svc._channels

    @pytest.mark.asyncio
    async def test_send_alert_routes_by_severity(self):
        svc = NotificationService(channels=_make_all_channels())
        alert = Alert(severity=AlertSeverity.INFO, title="Info", source="test")
        results = await svc.send_alert(alert)
        assert len(results) == 1
        assert results[0].channel == ChannelType.EMAIL

    @pytest.mark.asyncio
    async def test_send_alert_info_uses_email(self):
        svc = NotificationService(channels=_make_all_channels())
        alert = Alert(severity=AlertSeverity.INFO, title="Info alert", source="test_info")
        results = await svc.send_alert(alert)
        channel_types = {r.channel for r in results}
        assert ChannelType.EMAIL in channel_types
        assert ChannelType.SMS not in channel_types

    @pytest.mark.asyncio
    async def test_send_alert_critical_uses_multiple(self):
        svc = NotificationService(channels=_make_all_channels())
        alert = Alert(severity=AlertSeverity.CRITICAL, title="Critical alert", source="test_crit")
        results = await svc.send_alert(alert)
        channel_types = {r.channel for r in results}
        assert ChannelType.EMAIL in channel_types
        assert ChannelType.SMS in channel_types
        assert ChannelType.WEBHOOK in channel_types
        assert ChannelType.PUSH not in channel_types

    @pytest.mark.asyncio
    async def test_send_alert_emergency_uses_all(self):
        svc = NotificationService(channels=_make_all_channels())
        alert = Alert(severity=AlertSeverity.EMERGENCY, title="Emergency!", source="test_emer")
        results = await svc.send_alert(alert)
        channel_types = {r.channel for r in results}
        assert len(results) == 4
        assert ChannelType.EMAIL in channel_types
        assert ChannelType.SMS in channel_types
        assert ChannelType.WEBHOOK in channel_types
        assert ChannelType.PUSH in channel_types

    @pytest.mark.asyncio
    async def test_send_alert_rate_limited(self):
        svc = NotificationService(channels=_make_all_channels())
        svc.set_rate_limit(60)
        alert1 = Alert(severity=AlertSeverity.INFO, title="First", alert_type=AlertType.SYSTEM_HEALTH, source="same")
        await svc.send_alert(alert1)
        alert2 = Alert(severity=AlertSeverity.INFO, title="Second", alert_type=AlertType.SYSTEM_HEALTH, source="same")
        results2 = await svc.send_alert(alert2)
        assert len(results2) == 0

    @pytest.mark.asyncio
    async def test_send_alert_rate_limit_expired(self):
        svc = NotificationService(channels=_make_all_channels())
        svc.set_rate_limit(0)
        alert1 = Alert(severity=AlertSeverity.INFO, title="First", alert_type=AlertType.SYSTEM_HEALTH, source="src")
        await svc.send_alert(alert1)
        alert2 = Alert(severity=AlertSeverity.INFO, title="Second", alert_type=AlertType.SYSTEM_HEALTH, source="src")
        results2 = await svc.send_alert(alert2)
        assert len(results2) >= 1

    @pytest.mark.asyncio
    async def test_notify_kill_switch(self):
        svc = NotificationService(channels=_make_all_channels())
        results = await svc.notify_kill_switch(reason="Max daily loss exceeded")
        assert len(results) == 4
        assert all(r.success for r in results)
        history = svc.get_alert_history()
        assert len(history) == 1
        assert history[0].alert_type == AlertType.KILL_SWITCH
        assert history[0].severity == AlertSeverity.EMERGENCY

    @pytest.mark.asyncio
    async def test_notify_circuit_breaker(self):
        svc = NotificationService(channels=_make_all_channels())
        results = await svc.notify_circuit_breaker("order_execution", "OPEN")
        assert len(results) == 3
        assert all(r.success for r in results)
        history = svc.get_alert_history()
        assert history[0].alert_type == AlertType.CIRCUIT_BREAKER

    @pytest.mark.asyncio
    async def test_notify_order_rejected(self):
        svc = NotificationService(channels=_make_all_channels())
        results = await svc.notify_order_rejected("ORD-12345", "Insufficient margin")
        assert len(results) == 2
        assert all(r.success for r in results)
        history = svc.get_alert_history()
        assert history[0].alert_type == AlertType.ORDER_REJECTED

    @pytest.mark.asyncio
    async def test_notify_broker_disconnected(self):
        svc = NotificationService(channels=_make_all_channels())
        results = await svc.notify_broker_disconnected("IBKR")
        assert len(results) == 4
        assert all(r.success for r in results)
        history = svc.get_alert_history()
        assert history[0].alert_type == AlertType.BROKER_DISCONNECTED

    @pytest.mark.asyncio
    async def test_get_alert_history(self):
        svc = NotificationService(channels=_make_all_channels())
        await svc.notify_kill_switch("test")
        await svc.notify_order_rejected("ORD-1", "test")
        assert len(svc.get_alert_history()) == 2

    @pytest.mark.asyncio
    async def test_get_alert_history_with_limit(self):
        svc = NotificationService()
        for i in range(5):
            svc._alert_history.append(Alert(title=f"Alert {i}"))
        history = svc.get_alert_history(limit=3)
        assert len(history) == 3
        assert history[0].title == "Alert 2"

    @pytest.mark.asyncio
    async def test_get_send_history(self):
        svc = NotificationService(channels=_make_all_channels())
        await svc.notify_order_rejected("ORD-1", "reason")
        assert len(svc.get_send_history()) == 2

    def test_set_rate_limit(self):
        svc = NotificationService()
        svc.set_rate_limit(120)
        assert svc._rate_limit_seconds == 120
        svc.set_rate_limit(0)
        assert svc._rate_limit_seconds == 0
        svc.set_rate_limit(-10)
        assert svc._rate_limit_seconds == 0

    @pytest.mark.asyncio
    async def test_clear_history(self):
        svc = NotificationService(channels=_make_all_channels())
        await svc.notify_kill_switch("test")
        assert len(svc.get_alert_history()) > 0
        svc.clear_history()
        assert len(svc.get_alert_history()) == 0
        assert len(svc.get_send_history()) == 0

    @pytest.mark.asyncio
    async def test_alert_history_bounded(self):
        svc = NotificationService(channels=_make_all_channels())
        svc._max_history = 5
        svc.set_rate_limit(0)
        for i in range(10):
            alert = Alert(
                title=f"Alert {i}", severity=AlertSeverity.INFO,
                alert_type=AlertType.SYSTEM_HEALTH, source=f"source_{i}",
            )
            await svc.send_alert(alert)
        assert len(svc._alert_history) <= 5
        assert svc._alert_history[0].title == "Alert 5"

    @pytest.mark.asyncio
    async def test_send_alert_no_channels_configured(self):
        svc = NotificationService()
        alert = Alert(severity=AlertSeverity.EMERGENCY, title="No channels", source="test")
        results = await svc.send_alert(alert)
        assert len(results) == 0
        assert len(svc.get_alert_history()) == 1

    @pytest.mark.asyncio
    async def test_send_alert_channel_exception_handled(self):
        class FailingChannel(NotificationChannel):
            @property
            def channel_type(self) -> ChannelType:
                return ChannelType.EMAIL

            async def send(self, alert: Alert) -> NotificationResult:
                raise ConnectionError("SMTP server unreachable")

        svc = NotificationService(channels=[FailingChannel(NotificationConfig(channel_type=ChannelType.EMAIL))])
        alert = Alert(severity=AlertSeverity.INFO, title="Will fail", source="test")
        results = await svc.send_alert(alert)
        assert len(results) == 1
        assert results[0].success is False
        assert "SMTP server unreachable" in results[0].error_message
