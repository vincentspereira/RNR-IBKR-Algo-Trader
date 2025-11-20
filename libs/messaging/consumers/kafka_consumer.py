"""Kafka consumer utilities."""
from typing import Optional, Callable, Type
from confluent_kafka import Consumer, KafkaError

from libs.common.config import get_config
from libs.common.logging import get_logger
from libs.common.events import BaseEvent, JSONSerializer
from libs.common.errors import ConsumerException

logger = get_logger(__name__)


class KafkaConsumer:
    """Kafka consumer with event deserialization."""
    
    def __init__(
        self,
        topics: list[str],
        group_id: Optional[str] = None,
        bootstrap_servers: Optional[str] = None
    ):
        """
        Initialize Kafka consumer.
        
        Args:
            topics: List of topics to subscribe to
            group_id: Consumer group ID (uses config if not provided)
            bootstrap_servers: Kafka bootstrap servers (uses config if not provided)
        """
        config = get_config()
        self.topics = topics
        self.bootstrap_servers = bootstrap_servers or config.kafka.bootstrap_servers
        self.group_id = group_id or config.kafka.consumer_group_id
        
        # Consumer configuration
        consumer_config = {
            'bootstrap.servers': self.bootstrap_servers,
            'group.id': self.group_id,
            'auto.offset.reset': 'earliest',
            'enable.auto.commit': True,
            'auto.commit.interval.ms': 5000,
        }
        
        self.consumer = Consumer(consumer_config)
        self.consumer.subscribe(self.topics)
        self.serializer = JSONSerializer()
        
        logger.info(
            "kafka_consumer_initialized",
            topics=self.topics,
            group_id=self.group_id
        )
    
    def consume_events(
        self,
        event_class: Type[BaseEvent],
        handler: Callable[[BaseEvent], None],
        timeout: float = 1.0
    ):
        """
        Consume events from Kafka topics.
        
        Args:
            event_class: Event class to deserialize to
            handler: Function to handle events
            timeout: Poll timeout in seconds
        """
        try:
            while True:
                msg = self.consumer.poll(timeout)
                
                if msg is None:
                    continue
                
                if msg.error():
                    if msg.error().code() == KafkaError._PARTITION_EOF:
                        continue
                    else:
                        logger.error("consumer_error", error=str(msg.error()))
                        raise ConsumerException(f"Consumer error: {str(msg.error())}")
                
                try:
                    # Deserialize event
                    event = self.serializer.deserialize(msg.value(), event_class)
                    
                    # Handle event
                    handler(event)
                    
                    logger.debug(
                        "event_consumed",
                        topic=msg.topic(),
                        partition=msg.partition(),
                        offset=msg.offset()
                    )
                    
                except Exception as e:
                    logger.error("event_handling_error", error=str(e))
                    # Continue consuming even if handler fails
                    
        except KeyboardInterrupt:
            logger.info("consumer_interrupted")
        finally:
            self.close()
    
    def close(self):
        """Close consumer."""
        self.consumer.close()
        logger.info("kafka_consumer_closed")
