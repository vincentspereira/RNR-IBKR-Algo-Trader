"""Kafka producer utilities."""
from typing import Optional, Dict, Any
from confluent_kafka import Producer
from confluent_kafka.admin import AdminClient

from libs.common.config import get_config
from libs.common.logging import get_logger
from libs.common.events import BaseEvent, JSONSerializer
from libs.common.errors import ProducerException

logger = get_logger(__name__)


class KafkaProducer:
    """Kafka producer with event serialization."""
    
    def __init__(self, bootstrap_servers: Optional[str] = None):
        """
        Initialize Kafka producer.
        
        Args:
            bootstrap_servers: Kafka bootstrap servers (uses config if not provided)
        """
        config = get_config()
        self.bootstrap_servers = bootstrap_servers or config.kafka.bootstrap_servers
        
        # Producer configuration
        producer_config = {
            'bootstrap.servers': self.bootstrap_servers,
            'client.id': 'trading-system-producer',
            'compression.type': 'lz4',
            'linger.ms': 10,
            'batch.size': 32768,
        }
        
        self.producer = Producer(producer_config)
        self.serializer = JSONSerializer()
        
        logger.info("kafka_producer_initialized", servers=self.bootstrap_servers)
    
    def produce_event(
        self,
        topic: str,
        event: BaseEvent,
        key: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None
    ):
        """
        Produce event to Kafka topic.
        
        Args:
            topic: Kafka topic name
            event: Event to produce
            key: Message key (optional)
            headers: Message headers (optional)
        """
        try:
            # Serialize event
            value = self.serializer.serialize(event)
            
            # Convert headers to bytes
            kafka_headers = None
            if headers:
                kafka_headers = [(k, v.encode('utf-8')) for k, v in headers.items()]
            
            # Produce message
            self.producer.produce(
                topic=topic,
                value=value,
                key=key.encode('utf-8') if key else None,
                headers=kafka_headers,
                callback=self._delivery_callback
            )
            
            # Trigger delivery
            self.producer.poll(0)
            
            logger.debug("event_produced", topic=topic, event_type=event.event_type)
            
        except Exception as e:
            logger.error("produce_error", topic=topic, error=str(e))
            raise ProducerException(f"Failed to produce event: {str(e)}")
    
    def _delivery_callback(self, err, msg):
        """Delivery report callback."""
        if err:
            logger.error("delivery_failed", error=str(err), topic=msg.topic())
        else:
            logger.debug("delivery_success", topic=msg.topic(), partition=msg.partition())
    
    def flush(self, timeout: float = 10.0):
        """
        Flush pending messages.
        
        Args:
            timeout: Flush timeout in seconds
        """
        remaining = self.producer.flush(timeout)
        if remaining > 0:
            logger.warning("flush_incomplete", remaining_messages=remaining)
    
    def close(self):
        """Close producer."""
        self.flush()
        logger.info("kafka_producer_closed")


# Global producer instance
_kafka_producer: Optional[KafkaProducer] = None


def get_kafka_producer() -> KafkaProducer:
    """Get Kafka producer singleton."""
    global _kafka_producer
    if _kafka_producer is None:
        _kafka_producer = KafkaProducer()
    return _kafka_producer
