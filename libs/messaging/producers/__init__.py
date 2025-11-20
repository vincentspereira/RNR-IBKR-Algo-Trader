"""Messaging producers module."""
from .kafka_producer import KafkaProducer, get_kafka_producer

__all__ = [
    "KafkaProducer",
    "get_kafka_producer",
]
