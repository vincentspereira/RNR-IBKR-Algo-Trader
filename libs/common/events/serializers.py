"""Event serialization utilities.

Two serializers are provided:

* :class:`JSONSerializer` -- self-contained, schema-less JSON wire format. Good
  for local development, intra-service Python-to-Python communication, and
  Kafka topics that do not require schema validation.

* :class:`AvroSerializer` -- Confluent Schema Registry-backed Avro encoding,
  the standard Kafka serialization format for cross-language interoperability
  and schema evolution. Uses ``confluent_kafka.schema_registry`` which ships
  with the ``confluent-kafka[avro]`` extra already pinned in pyproject.toml.

Both serializers consume and produce subclasses of :class:`BaseEvent` and are
fully implemented (no stubs).
"""
from __future__ import annotations

import json
from typing import Any, Type

from confluent_kafka.schema_registry import SchemaRegistryClient
from confluent_kafka.schema_registry.avro import AvroDeserializer, AvroSerializer as _CKAvroSerializer
from confluent_kafka.serialization import MessageField, SerializationContext

from .base import BaseEvent


class JSONSerializer:
    """JSON event serializer.

    Self-contained, schema-less. Use this for development and for topics where
    schema evolution is managed at the application layer rather than at the
    broker.
    """

    @staticmethod
    def serialize(event: BaseEvent) -> bytes:
        """Serialise ``event`` to UTF-8 encoded JSON bytes."""
        return json.dumps(event.model_dump(mode="json"), default=str).encode("utf-8")

    @staticmethod
    def deserialize(data: bytes, event_class: Type[BaseEvent]) -> BaseEvent:
        """Decode ``data`` (UTF-8 JSON bytes) into an instance of ``event_class``."""
        payload = json.loads(data.decode("utf-8"))
        return event_class(**payload)


class AvroSerializer:
    """Avro event serializer with Confluent Schema Registry integration.

    Each event class registered with this serializer must have a corresponding
    Avro schema string. Schemas are passed in via :meth:`register_schema` or
    derived automatically from the Pydantic model via
    :meth:`schema_from_event_class`.

    Wire format follows the Confluent Schema Registry convention: a 0x00 magic
    byte, a 4-byte big-endian schema ID, then the Avro-encoded payload.

    Parameters
    ----------
    schema_registry_url:
        Base URL for the Schema Registry (e.g. ``http://schema-registry:8081``).
    schema_registry_auth:
        Optional ``("user", "password")`` tuple for basic auth.
    """

    def __init__(
        self,
        schema_registry_url: str,
        schema_registry_auth: tuple[str, str] | None = None,
    ) -> None:
        config: dict[str, Any] = {"url": schema_registry_url}
        if schema_registry_auth is not None:
            user, pw = schema_registry_auth
            config["basic.auth.user.info"] = f"{user}:{pw}"
        self._registry = SchemaRegistryClient(config)
        self._serializers: dict[Type[BaseEvent], _CKAvroSerializer] = {}
        self._deserializers: dict[Type[BaseEvent], AvroDeserializer] = {}
        self._schemas: dict[Type[BaseEvent], str] = {}

    def register_schema(self, event_class: Type[BaseEvent], schema: str) -> None:
        """Associate an Avro schema string with an event class.

        Call this once per event type before :meth:`serialize` / :meth:`deserialize`.
        Subsequent calls overwrite prior registrations.
        """
        self._schemas[event_class] = schema
        self._serializers[event_class] = _CKAvroSerializer(
            schema_registry_client=self._registry,
            schema_str=schema,
            to_dict=lambda evt, ctx: evt.model_dump(mode="json"),
        )
        self._deserializers[event_class] = AvroDeserializer(
            schema_registry_client=self._registry,
            schema_str=schema,
            from_dict=lambda data, ctx, cls=event_class: cls(**data) if data is not None else None,
        )

    def serialize(self, event: BaseEvent, topic: str) -> bytes:
        """Encode ``event`` using its registered Avro schema for ``topic``."""
        cls = type(event)
        serializer = self._serializers.get(cls)
        if serializer is None:
            raise KeyError(
                f"No Avro schema registered for event class {cls.__name__}. "
                f"Call register_schema({cls.__name__}, schema_str) first."
            )
        ctx = SerializationContext(topic, MessageField.VALUE)
        return serializer(event, ctx)

    def deserialize(
        self, data: bytes, event_class: Type[BaseEvent], topic: str
    ) -> BaseEvent | None:
        """Decode Schema Registry-framed Avro ``data`` into ``event_class``."""
        deserializer = self._deserializers.get(event_class)
        if deserializer is None:
            raise KeyError(
                f"No Avro schema registered for event class {event_class.__name__}. "
                f"Call register_schema({event_class.__name__}, schema_str) first."
            )
        ctx = SerializationContext(topic, MessageField.VALUE)
        return deserializer(data, ctx)

    @staticmethod
    def schema_from_event_class(event_class: Type[BaseEvent], namespace: str) -> str:
        """Derive an Avro schema string from a Pydantic event class.

        This is a pragmatic auto-mapper covering the field types currently used
        by :mod:`libs.common.events.base`: ``str``, ``int``, ``float``,
        ``bool``, ``datetime``, ``UUID``, ``dict``, and ``Optional`` of those.
        Anything more exotic should be registered with an explicit schema via
        :meth:`register_schema`.
        """
        schema = {
            "type": "record",
            "name": event_class.__name__,
            "namespace": namespace,
            "fields": [
                _field_to_avro(name, field) for name, field in event_class.model_fields.items()
            ],
        }
        return json.dumps(schema)


def _python_to_avro_type(py_type: Any) -> Any:
    """Map a Python / Pydantic field type to an Avro type or union."""
    import datetime as _dt
    import uuid as _uuid
    from typing import get_args, get_origin

    origin = get_origin(py_type)
    if origin is None:
        if py_type is str:
            return "string"
        if py_type is int:
            return "long"
        if py_type is float:
            return "double"
        if py_type is bool:
            return "boolean"
        if py_type is _dt.datetime:
            return {"type": "long", "logicalType": "timestamp-micros"}
        if py_type is _uuid.UUID:
            return {"type": "string", "logicalType": "uuid"}
        if py_type is dict:
            return {"type": "map", "values": "string"}
        return "string"

    args = get_args(py_type)
    if origin is dict:
        value_type = args[1] if len(args) > 1 else str
        return {"type": "map", "values": _python_to_avro_type(value_type)}
    if origin is list:
        item_type = args[0] if args else str
        return {"type": "array", "items": _python_to_avro_type(item_type)}
    if type(None) in args:
        non_none = [a for a in args if a is not type(None)]
        if len(non_none) == 1:
            return ["null", _python_to_avro_type(non_none[0])]
    return "string"


def _field_to_avro(name: str, field: Any) -> dict[str, Any]:
    """Build an Avro field descriptor for one Pydantic model field."""
    avro_type = _python_to_avro_type(field.annotation)
    descriptor: dict[str, Any] = {"name": name, "type": avro_type}
    if isinstance(avro_type, list) and "null" in avro_type:
        descriptor["default"] = None
    return descriptor
