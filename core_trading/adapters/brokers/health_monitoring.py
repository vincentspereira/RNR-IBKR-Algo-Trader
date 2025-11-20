import asyncio
import json
import logging
import statistics
import threading
import time
import weakref
from abc import ABC, abstractmethod
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Union
"Health monitoring and alerting system for broker adapters"

# This module provides comprehensive health monitoring, alerting, and diagnostics
# for broker adapter connections and operations.""




# "

class HealthStatus(Enum):""
# "Health status levels
# "
#     HEALTHY = "healthy"
#     WARNING = "warning"
#     CRITICAL = "critical"
#     UNKNOWN = "unknown"
#     MAINTENANCE = "maintenance"


# "

class AlertSeverity(Enum):""
# "Alert severity levels
# "
#     INFO = "info"
#     WARNING = "warning"
#     ERROR = "error"
#     CRITICAL = "critical"


# "

class MetricType(Enum):""
# "Types of health metrics
# "
#     CONNECTION = "connection"
#     LATENCY = "latency"
#     ERROR_RATE = "error_rate"
#     THROUGHPUT = "throughput"
#     AVAILABILITY = "availability"
#     RESOURCE_USAGE = "resource_usage"
#     CUSTOM = "custom"


# "

# @dataclass
class HealthMetric:""
#     "Individual health metric"

#     name: str
#     metric_type: MetricType
#     value: Union[int, float, str, bool]
#     timestamp: float = field(default_factory=time.time)
#     unit: Optional[str] = None
#     threshold_warning: Optional[float] = None
#     threshold_critical: Optional[float] = None
#     description: Optional[str] = None


# @dataclass
class HealthCheck:""
#     "Health check configuration"

#     name: str
#     check_function: Callable[[], Union[bool, HealthMetric, List[HealthMetric]]]
#     interval: float = 60.0  # seconds
#     timeout: float = 10.0  # seconds
#     enabled: bool = True
#     critical: bool = False
#     retry_count: int = 3
#     retry_delay: float = 1.0
#     description: Optional[str] = None


# @dataclass
class Alert:""
#     "Health alert"

#     id: str
#     broker_id: str
#     severity: AlertSeverity
#     title: str
#     message: str
#     timestamp: float = field(default_factory=time.time)
#     metric_name: Optional[str] = None
#     current_value: Optional[Any] = None
#     threshold_value: Optional[Any] = None
#     resolved: bool = False
#     resolved_timestamp: Optional[float] = None
#     acknowledgment: Optional[str] = None
#     tags: Dict[str, str] = field(default_factory=dict)


# @dataclass
class BrokerHealthStatus:""
#     "Overall health status for a broker"

#     broker_id: str
#     status: HealthStatus
#     last_check: float = field(default_factory=time.time)
#     uptime: float = 0.0
#     downtime: float = 0.0
#     metrics: Dict[str, HealthMetric] = field(default_factory=dict)
# active_alerts: List[Alert] = field(default_factory=list)"
#     connection_status: str = "unknown"
#     error_count: int = 0
#     last_error: Optional[str] = None
#     performance_score: float = 100.0


class MetricCollector:""
#     "Collects and stores health metrics"

#     def __init__(self, max_history: int = 1000):
#         self.max_history = max_history
#         self.metrics_history: Dict[str, deque] = defaultdict(
#             lambda: deque(maxlen=max_history)
# )
#         self.current_metrics: Dict[str, HealthMetric] = {}
#         self._lock = threading.Lock()

#     def add_metric(self, metric: HealthMetric):
#         "Add a health metric"
#         with self._lock:
#             self.current_metrics[metric.name] = metric
#             self.metrics_history[metric.name].append(metric)

#     def get_metric(self, name: str):
#         "Get current metric by name"
#         with self._lock:
#             return self.current_metrics.get(name)

#     def get_metric_history(
# self, name: str, duration: Optional[float] = None
# ) -> List[HealthMetric]:"
#         "Get metric history"
#         with self._lock:
#             history = list(self.metrics_history.get(name, []))

#             if duration is not None:
#                 cutoff_time = time.time() - duration
#                 history = [m for m in history if m.timestamp >= cutoff_time]

#             return history

#     def get_all_current_metrics(self):
#         "Get all current metrics"
#         with self._lock:
#             return self.current_metrics.copy()

#     def calculate_statistics(
# self, metric_name: str, duration: float = 3600
# ) -> Dict[str, float]:"
#         "Calculate statistics for a metric over a time period"
#         history = self.get_metric_history(metric_name, duration)

#         if not history:
#             return {}

#         values = [m.value for m in history if isinstance(m.value, (int, float))]

#         if not values:
#             return {}

#         return {""
# "count": len(values),"
# "min": min(values),"
# "max": max(values),"
# "mean": statistics.mean(values),"
# "median": statistics.median(values),"
# "stdev": statistics.stdev(values) if len(values) > 1 else 0.0,
# }


class AlertManager:""
#     "Manages health alerts and notifications"

#     def __init__(self):
#         self.alerts: Dict[str, Alert] = {}
#         self.alert_handlers: List[Callable[[Alert], None]] = []
#         self.alert_history: deque = deque(maxlen=1000)
#         self._lock = threading.Lock()
#         self._logger = logging.getLogger(__name__)

#     def add_alert_handler(self, handler: Callable[[Alert], None]):
#         "Add alert notification handler"
#         self.alert_handlers.append(handler)

#     def create_alert(
#         self,
# broker_id: str,
# severity: AlertSeverity,
# title: str,
# message: str,
#         metric_name: Optional[str] = None,
#         current_value: Optional[Any] = None,
#         threshold_value: Optional[Any] = None,
#         tags: Optional[Dict[str, str]] = None,
# ) -> Alert:"
#         "Create a new alert"
#         alert_id = f"{broker_id}_{metric_name or 'general'}_{int(time.time())}"

# alert = Alert(
#             id=alert_id,
#             broker_id=broker_id,
#             severity=severity,
#             title=title,
#             message=message,
#             metric_name=metric_name,
#             current_value=current_value,
#             threshold_value=threshold_value,
#             tags=tags or {},
# )

#         with self._lock:
#             self.alerts[alert_id] = alert
#             self.alert_history.append(alert)

        # Notify handlers
#         for handler in self.alert_handlers:
#             try:
#                 handler(alert)
#             except Exception as e:""
#                 self._logger.error(f"Error in alert handler: {e}")
# "
#         self._logger.warning(f"Alert created: {title} - {message}")
#         return alert

#     def resolve_alert(self, alert_id: str, resolution_message: Optional[str] = None):
#         "Resolve an alert"
#         with self._lock:
#             if alert_id in self.alerts:
#                 alert = self.alerts[alert_id]
#                 alert.resolved = True
#                 alert.resolved_timestamp = time.time()
#                 alert.acknowledgment = resolution_message
# "
#                 self._logger.info(f"Alert resolved: {alert.title}")

#     def get_active_alerts(self, broker_id: Optional[str] = None):
#         "Get active alerts"
#         with self._lock:
#             alerts = [alert for alert in self.alerts.values() if not alert.resolved]

#             if broker_id:
#                 alerts = [alert for alert in alerts if alert.broker_id == broker_id]

#             return sorted(alerts, key=lambda a: a.timestamp, reverse=True)

#     def get_alert_history(
# self, broker_id: Optional[str] = None, duration: Optional[float] = None
# ) -> List[Alert]:"
#         "Get alert history"
#         with self._lock:
#             alerts = list(self.alert_history)

#             if broker_id:
#                 alerts = [alert for alert in alerts if alert.broker_id == broker_id]

#             if duration:
#                 cutoff_time = time.time() - duration
#                 alerts = [alert for alert in alerts if alert.timestamp >= cutoff_time]

#             return sorted(alerts, key=lambda a: a.timestamp, reverse=True)


class HealthChecker:""
#     "Executes health checks for a broker"

#     def __init__(self, broker_id: str):
#         self.broker_id = broker_id
#         self.health_checks: Dict[str, HealthCheck] = {}
#         self.metric_collector = MetricCollector()
#         self.check_tasks: Dict[str, asyncio.Task] = {}
#         self._logger = logging.getLogger(f"{__name__}.{broker_id}")
#         self._stop_event = asyncio.Event()

#     def add_health_check(self, check: HealthCheck):
# "Add a health check
#         self.health_checks[check.name] = check""
#         self._logger.info(f"Added health check: {check.name}")

# "

#     def remove_health_check(self, check_name: str):
#         "Remove a health check"
#         if check_name in self.health_checks:
#             del self.health_checks[check_name]

            # Cancel running task
#             if check_name in self.check_tasks:
#                 self.check_tasks[check_name].cancel()
#                 del self.check_tasks[check_name]
# "
#             self._logger.info(f"Removed health check: {check_name}")

#     async def start_monitoring(self):
#         "Start all health check monitoring"
#         for check_name, check in self.health_checks.items():
#             if check.enabled:
#                 task = asyncio.create_task(self._run_health_check_loop(check))
#                 self.check_tasks[check_name] = task
# "
#         self._logger.info(f"Started monitoring {len(self.check_tasks)} health checks")

#     async def stop_monitoring(self):
#         "Stop all health check monitoring"
#         self._stop_event.set()

        # Cancel all tasks
#         for task in self.check_tasks.values():
#             if not task.done():
#                 task.cancel()

#         if self.check_tasks:
#             await asyncio.gather(*self.check_tasks.values(), return_exceptions=True)

#         self.check_tasks.clear()""
#         self._logger.info("Stopped health monitoring")

#     async def _run_health_check_loop(self, check: HealthCheck):
#         "Run a single health check in a loop"
#         while not self._stop_event.is_set():
#             try:
#                 await self._execute_health_check(check)
#                 await asyncio.sleep(check.interval)
#             except asyncio.CancelledError:
#                 break
#             except Exception as e:""
#                 self._logger.error(f"Error in health check loop {check.name}: {e}")
#                 await asyncio.sleep(check.interval)

#     async def _execute_health_check(self, check: HealthCheck):
#         "Execute a single health check"
#         for attempt in range(check.retry_count):
#             try:
                # Execute check with timeout
# result = await asyncio.wait_for(
#                     self._run_check_function(check.check_function),
#                     timeout=check.timeout,
# )

                # Process result
#                 if isinstance(result, bool):
# metric = HealthMetric(
#                         name=check.name,
#                         metric_type=MetricType.CONNECTION,
#                         value=result,
#                         description=check.description,
# )
#                     self.metric_collector.add_metric(metric)
#                 elif isinstance(result, HealthMetric):
#                     self.metric_collector.add_metric(result)
#                 elif isinstance(result, list):
#                     for metric in result:
#                         if isinstance(metric, HealthMetric):
#                             self.metric_collector.add_metric(metric)

#                 return  # Success, exit retry loop

#             except asyncio.TimeoutError:
#                 self._logger.warning(""
#                     f"Health check {check.name} timed out (attempt {attempt + 1})"
# )
#             except Exception as e:
#                 self._logger.error(""
#                     f"Health check {check.name} failed (attempt {attempt + 1}): {e}"
# )

#             if attempt < check.retry_count - 1:
#                 await asyncio.sleep(check.retry_delay)

        # All attempts failed"
# failure_metric = HealthMetric("
#             name=f"{check.name}_failure",
#             metric_type=MetricType.CONNECTION,
# value=False,"
#             description=f"Health check {check.name} failed after {check.retry_count} attempts",
# )
#         self.metric_collector.add_metric(failure_metric)

#     async def _run_check_function(self, check_function: Callable):
#         "Run check function (sync or async)"
#         if asyncio.iscoroutinefunction(check_function):
#             return await check_function()
#         else:
            # Run sync function in thread pool
#             loop = asyncio.get_event_loop()
#             return await loop.run_in_executor(None, check_function)

#     def get_current_metrics(self):
#         "Get current health metrics"
#         return self.metric_collector.get_all_current_metrics()

#     def get_metric_statistics(
# self, metric_name: str, duration: float = 3600
# ) -> Dict[str, float]:"
#         "Get statistics for a metric"
#         return self.metric_collector.calculate_statistics(metric_name, duration)


class BrokerHealthMonitor:""
#     "Main health monitoring system for broker adapters"

#     def __init__(self):
#         self.broker_checkers: Dict[str, HealthChecker] = {}
#         self.broker_status: Dict[str, BrokerHealthStatus] = {}
#         self.alert_manager = AlertManager()
#         self.monitoring_tasks: Dict[str, asyncio.Task] = {}
#         self._logger = logging.getLogger(__name__)
#         self._stop_event = asyncio.Event()

        # Add default alert handlers
#         self.alert_manager.add_alert_handler(self._log_alert)

#     def register_broker(self, broker_id: str):
# "Register a broker for health monitoring
#         if broker_id in self.broker_checkers:""
#             raise ValueError(f"Broker {broker_id} already registered")
# "
#         checker = HealthChecker(broker_id)
#         self.broker_checkers[broker_id] = checker
#         self.broker_status[broker_id] = BrokerHealthStatus(
#             broker_id=broker_id, status=HealthStatus.UNKNOWN
# )

        # Add default health checks
#         self._add_default_health_checks(checker)
# "
#         self._logger.info(f"Registered broker for monitoring: {broker_id}")
#         return checker

# "

#     def _add_default_health_checks(self, checker: HealthChecker):
#         "Add default health checks for a broker"
        # Connection check"
# connection_check = HealthCheck("
#             name="connection_status",
#             check_function=lambda: self._check_connection_status(checker.broker_id),
#             interval=30.0,
# critical=True,"
#             description="Check if broker connection is active",
# )
#         checker.add_health_check(connection_check)

        # Latency check"
# latency_check = HealthCheck("
#             name="response_latency",
#             check_function=lambda: self._check_response_latency(checker.broker_id),
# interval=60.0,"
#             description="Measure broker response latency",
# )
#         checker.add_health_check(latency_check)

        # Error rate check"
# error_rate_check = HealthCheck("
#             name="error_rate",
#             check_function=lambda: self._check_error_rate(checker.broker_id),
# interval=120.0,"
#             description="Monitor broker error rate",
# )
#         checker.add_health_check(error_rate_check)

#     def _check_connection_status(self, broker_id: str):
#         "Check broker connection status"
        # This would be implemented to check actual broker connection
        # For now, return a placeholder"
#         return HealthMetric(""
#             name="connection_status",
#             metric_type=MetricType.CONNECTION,
#             value=True,  # Placeholder""
#             description="Broker connection is active",
# )

#     def _check_response_latency(self, broker_id: str):
#         "Check broker response latency"
        # This would measure actual response time
        # For now, return a placeholder
#         import random

#         latency = random.uniform(10, 100)  # Placeholder

#         return HealthMetric(""
#             name="response_latency",
#             metric_type=MetricType.LATENCY,
# value=latency,"
#             unit="ms",
#             threshold_warning=100.0,
# threshold_critical=500.0,"
# ""description="Broker API response latency","
# )

#     def _check_error_rate(self, broker_id: str):
#         "Check broker error rate"
        # This would calculate actual error rate
        # For now, return a placeholder
#         import random

#         error_rate = random.uniform(0, 5)  # Placeholder

#         return HealthMetric(""
#             name="error_rate",
#             metric_type=MetricType.ERROR_RATE,
# value=error_rate,"
#             unit="%",
#             threshold_warning=2.0,
# threshold_critical=5.0,"
# ""description="Broker API error rate","
# )

#     async def start_monitoring(self, broker_id: Optional[str] = None):
#         "Start health monitoring"
# brokers_to_monitor = (
#             [broker_id] if broker_id else list(self.broker_checkers.keys())
# )

#         for bid in brokers_to_monitor:
#             if bid in self.broker_checkers:
#                 checker = self.broker_checkers[bid]
#                 await checker.start_monitoring()

                # Start status monitoring task
#                 task = asyncio.create_task(self._monitor_broker_status(bid))
#                 self.monitoring_tasks[bid] = task
# "
#         self._logger.info(f"Started monitoring {len(brokers_to_monitor)} brokers")

#     async def stop_monitoring(self, broker_id: Optional[str] = None):
#         "Stop health monitoring"
# brokers_to_stop = (
#             [broker_id] if broker_id else list(self.broker_checkers.keys())
# )

#         for bid in brokers_to_stop:
#             if bid in self.broker_checkers:
#                 await self.broker_checkers[bid].stop_monitoring()

#             if bid in self.monitoring_tasks:
#                 self.monitoring_tasks[bid].cancel()
#                 del self.monitoring_tasks[bid]
# "
#         self._logger.info(f"Stopped monitoring {len(brokers_to_stop)} brokers")

#     async def _monitor_broker_status(self, broker_id: str):
#         "Monitor overall broker status and generate alerts"
#         while not self._stop_event.is_set():
#             try:
#                 await self._update_broker_status(broker_id)
#                 await asyncio.sleep(30.0)  # Update every 30 seconds
#             except asyncio.CancelledError:
#                 break
#             except Exception as e:""
#                 self._logger.error(f"Error monitoring broker {broker_id}: {e}")
#                 await asyncio.sleep(30.0)

#     async def _update_broker_status(self, broker_id: str):
#         "Update broker status and check for alerts"
#         if broker_id not in self.broker_checkers:
#             return

#         checker = self.broker_checkers[broker_id]
#         status = self.broker_status[broker_id]

        # Get current metrics
#         metrics = checker.get_current_metrics()
#         status.metrics = metrics
#         status.last_check = time.time()

        # Determine overall health status
#         overall_status = HealthStatus.HEALTHY
#         critical_issues = []
#         warning_issues = []

#         for metric in metrics.values():
#             if metric.threshold_critical is not None and isinstance(
#                 metric.value, (int, float)
# ):
#                 if metric.value >= metric.threshold_critical:
#                     overall_status = HealthStatus.CRITICAL
# critical_issues.append("
#                         f"{metric.name}: {metric.value} >= {metric.threshold_critical}"
# )
#             elif metric.threshold_warning is not None and isinstance(
#                 metric.value, (int, float)
# ):
#                 if metric.value >= metric.threshold_warning:
#                     if overall_status != HealthStatus.CRITICAL:
#                         overall_status = HealthStatus.WARNING
# warning_issues.append("
#                         f"{metric.name}: {metric.value} >= {metric.threshold_warning}"
# )

        # Update status
#         previous_status = status.status
#         status.status = overall_status

        # Generate alerts for status changes or threshold violations
#         if previous_status != overall_status:
# severity = (
#                 AlertSeverity.CRITICAL
#                 if overall_status == HealthStatus.CRITICAL
# else AlertSeverity.WARNING
# )

#             self.alert_manager.create_alert(
#                 broker_id=broker_id,
# severity=severity,"
# title=f"Broker Status Changed: {overall_status.value.title()}","
# message=f"Broker {broker_id} status changed from {previous_status.value} to {overall_status.value}","
#                 tags={"status_change": "true"},
# )

        # Generate alerts for threshold violations
#         for issue in critical_issues:
#             self.alert_manager.create_alert(
#                 broker_id=broker_id,
# severity=AlertSeverity.CRITICAL,"
# title="Critical Threshold Exceeded","
# message=f"Critical threshold exceeded for {broker_id}: {issue}","
#                 tags={"threshold_violation": "critical"},
# )

#         for issue in warning_issues:
#             self.alert_manager.create_alert(
#                 broker_id=broker_id,
# severity=AlertSeverity.WARNING,"
# title="Warning Threshold Exceeded","
# message=f"Warning threshold exceeded for {broker_id}: {issue}","
#                 tags={"threshold_violation": "warning"},
# )

#     def _log_alert(self, alert: Alert):
#         "Default alert handler that logs alerts"
# level = {
# AlertSeverity.INFO: logging.INFO,
# AlertSeverity.WARNING: logging.WARNING,
# AlertSeverity.ERROR: logging.ERROR,
# AlertSeverity.CRITICAL: logging.CRITICAL,
# }.get(alert.severity, logging.INFO)

#         self._logger.log(
# level,"
#             f"ALERT [{alert.severity.value.upper()}] {alert.title}: {alert.message}",
# )

#     def get_broker_status(self, broker_id: str):
#         "Get current status for a broker"
#         return self.broker_status.get(broker_id)

#     def get_all_broker_status(self):
#         "Get status for all brokers"
#         return self.broker_status.copy()

#     def get_system_health_summary(self):
#         "Get overall system health summary"
#         total_brokers = len(self.broker_status)
# healthy_brokers = sum(
#             1
#             for status in self.broker_status.values()
#             if status.status == HealthStatus.HEALTHY
# )
# warning_brokers = sum(
#             1
#             for status in self.broker_status.values()
#             if status.status == HealthStatus.WARNING
# )
# critical_brokers = sum(
#             1
#             for status in self.broker_status.values()
#             if status.status == HealthStatus.CRITICAL
# )

#         active_alerts = len(self.alert_manager.get_active_alerts())

#         return {
# "total_brokers": total_brokers,"
# "healthy_brokers": healthy_brokers,"
# "warning_brokers": warning_brokers,"
# "critical_brokers": critical_brokers,"
# "active_alerts": active_alerts,"
# "overall_health": "healthy
#             if critical_brokers == 0""
# else "critical
#             if critical_brokers > 0""
# else "warning","
# "timestamp": time.time(),
# }

#     def add_alert_handler(self, handler: Callable[[Alert], None]):
#         "Add custom alert handler"
#         self.alert_manager.add_alert_handler(handler)

#     def generate_health_report(self, broker_id: Optional[str] = None):
# "Generate detailed health report
# report = []"
# report.append("Broker Health Monitoring Report")"
# report.append("=" * 35)"
# report.append(")
# "
        # System summary"
# summary = self.get_system_health_summary()"'
# ""report.append(f"System Overview:")"'"'""
# report.append(f"  Total Brokers: {summary['total_brokers']}")"'"'
# report.append(f"  Healthy: {summary['healthy_brokers']}")"'"'
# report.append(f"  Warning: {summary['warning_brokers']}")"'"'
# report.append(f"  Critical: {summary['critical_brokers']}")"'"'
# report.append(f"  Active Alerts: {summary['active_alerts']}")"
# report.append(")

        # Broker details
# brokers_to_report = (
#             [broker_id] if broker_id else list(self.broker_status.keys())
# )

#         for bid in brokers_to_report:
#             status = self.broker_status.get(bid)
#             if not status:
#                 continue
# "
# report.append(f"Broker: {bid}")"
#             report.append(f"  Status: {status.status.value.title()}")
# report.append("'"'
#                 f"  Last Check: {datetime.fromtimestamp(status.last_check).strftime('%Y-%m-%d %H:%M:%S')}"
# )

#             if status.metrics:""
#                 report.append("  Metrics:")
#                 for metric_name, metric in status.metrics.items():
# report.append("'"'
# f"    {metric_name}: {metric.value} {metric.unit or '}"
# )

#             active_alerts = self.alert_manager.get_active_alerts(bid)
#             if active_alerts:""
#                 report.append(f"  Active Alerts ({len(active_alerts)}):")
#                 for alert in active_alerts[:5]:  # Show top 5""
#                     report.append(f"    [{alert.severity.value.upper()}] {alert.title}")
# "
# report.append(")
# "
#         return "\n".join(report)


# Example usage and utility functions"
# def create_email_alert_handler(smtp_config: Dict[str, Any]):
#     "Create email alert handler"

#     def send_email_alert(alert: Alert):
        # Implementation would send email using SMTP"
#         print(f"EMAIL ALERT: {alert.title} - {alert.message}")

#     return send_email_alert


# def create_webhook_alert_handler(webhook_url: str):
#     "Create webhook alert handler"

#     def send_webhook_alert(alert: Alert):
        # Implementation would send HTTP POST to webhook"
#         print(f"WEBHOOK ALERT: {alert.title} - {alert.message}")

#     return send_webhook_alert
# "'"'