"""Prometheus metrics and monitoring utilities."""
from typing import Callable
import time
import functools

from prometheus_client import Counter, Gauge, Histogram, Summary, Info


class MetricsCollector:
    """Centralized metrics collector for the trading system."""
    
    def __init__(self, service_name: str):
        """
        Initialize metrics collector.
        
        Args:
            service_name: Name of the service
        """
        self.service_name = service_name
        
        # Request metrics
        self.request_count = Counter(
            f'{service_name}_requests_total',
            'Total number of requests',
            ['method', 'endpoint', 'status']
        )
        
        self.request_duration = Histogram(
            f'{service_name}_request_duration_seconds',
            'Request duration in seconds',
            ['method', 'endpoint']
        )
        
        # Database metrics
        self.db_query_count = Counter(
            f'{service_name}_db_queries_total',
            'Total number of database queries',
            ['database', 'operation']
        )
        
        self.db_query_duration = Histogram(
            f'{service_name}_db_query_duration_seconds',
            'Database query duration in seconds',
            ['database', 'operation']
        )
        
        # Kafka metrics
        self.kafka_messages_produced = Counter(
            f'{service_name}_kafka_messages_produced_total',
            'Total Kafka messages produced',
            ['topic']
        )
        
        self.kafka_messages_consumed = Counter(
            f'{service_name}_kafka_messages_consumed_total',
            'Total Kafka messages consumed',
            ['topic']
        )
        
        # Trading metrics
        self.orders_created = Counter(
            f'{service_name}_orders_created_total',
            'Total orders created',
            ['symbol', 'side']
        )
        
        self.orders_filled = Counter(
            f'{service_name}_orders_filled_total',
            'Total orders filled',
            ['symbol', 'side']
        )
        
        self.positions_opened = Counter(
            f'{service_name}_positions_opened_total',
            'Total positions opened',
            ['symbol']
        )
        
        self.positions_closed = Counter(
            f'{service_name}_positions_closed_total',
            'Total positions closed',
            ['symbol']
        )
        
        # System metrics
        self.active_connections = Gauge(
            f'{service_name}_active_connections',
            'Number of active connections',
            ['connection_type']
        )
        
        self.errors_total = Counter(
            f'{service_name}_errors_total',
            'Total number of errors',
            ['error_type']
        )
        
        # Service info
        self.service_info = Info(
            f'{service_name}_info',
            'Service information'
        )
    
    def track_request(self, method: str, endpoint: str, status: int, duration: float):
        """Track HTTP request metrics."""
        self.request_count.labels(method=method, endpoint=endpoint, status=status).inc()
        self.request_duration.labels(method=method, endpoint=endpoint).observe(duration)
    
    def track_db_query(self, database: str, operation: str, duration: float):
        """Track database query metrics."""
        self.db_query_count.labels(database=database, operation=operation).inc()
        self.db_query_duration.labels(database=database, operation=operation).observe(duration)
    
    def track_kafka_produce(self, topic: str):
        """Track Kafka message production."""
        self.kafka_messages_produced.labels(topic=topic).inc()
    
    def track_kafka_consume(self, topic: str):
        """Track Kafka message consumption."""
        self.kafka_messages_consumed.labels(topic=topic).inc()
    
    def track_order_created(self, symbol: str, side: str):
        """Track order creation."""
        self.orders_created.labels(symbol=symbol, side=side).inc()
    
    def track_order_filled(self, symbol: str, side: str):
        """Track order fill."""
        self.orders_filled.labels(symbol=symbol, side=side).inc()
    
    def track_error(self, error_type: str):
        """Track error occurrence."""
        self.errors_total.labels(error_type=error_type).inc()


def track_time(metric: Histogram):
    """
    Decorator to track function execution time.
    
    Args:
        metric: Histogram metric to track
        
    Returns:
        Decorated function
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            start_time = time.time()
            try:
                return func(*args, **kwargs)
            finally:
                duration = time.time() - start_time
                metric.observe(duration)
        return wrapper
    return decorator


def track_async_time(metric: Histogram):
    """
    Decorator to track async function execution time.
    
    Args:
        metric: Histogram metric to track
        
    Returns:
        Decorated async function
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            start_time = time.time()
            try:
                return await func(*args, **kwargs)
            finally:
                duration = time.time() - start_time
                metric.observe(duration)
        return wrapper
    return decorator
