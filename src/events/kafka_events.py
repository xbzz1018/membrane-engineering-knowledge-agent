from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from src.core.config import get_settings
from src.engineering.storage import storage


class EventEnvelope(BaseModel):
    schema_version: str = "1.0"
    event_id: str
    event_type: str
    aggregate_type: str
    aggregate_id: str
    occurred_at: datetime
    producer: str = "membrane-engineering-agent"
    trace_id: str
    payload: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def create(
        cls,
        *,
        event_type: str,
        aggregate_type: str,
        aggregate_id: str,
        payload: dict[str, Any],
        trace_id: str | None = None,
    ) -> EventEnvelope:
        return cls(
            event_id=uuid.uuid4().hex,
            event_type=event_type,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            occurred_at=datetime.now(UTC),
            trace_id=trace_id or uuid.uuid4().hex,
            payload=payload,
        )


class OutboxPublisher:
    """Write events to PostgreSQL; Kafka publication belongs to the relay."""

    def __init__(self):
        self.settings = get_settings()

    async def publish(self, event_type: str, aggregate_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        envelope = EventEnvelope.create(
            event_type=event_type,
            aggregate_type=event_type.split(".", 1)[0],
            aggregate_id=aggregate_id,
            payload=payload,
        )
        topic = f"{self.settings.KAFKA_TOPIC_PREFIX}.{event_type}"
        event_id = await storage.add_outbox_event(envelope.model_dump(mode="json"), topic)
        return {
            "published": False,
            "queued": True,
            "event_id": event_id,
            "topic": topic,
            "relay_enabled": self.settings.KAFKA_ENABLED,
        }


class OutboxRelay:
    def __init__(self):
        self.settings = get_settings()

    async def _producer(self):
        from aiokafka import AIOKafkaProducer

        producer = AIOKafkaProducer(
            bootstrap_servers=self.settings.KAFKA_BOOTSTRAP_SERVERS,
            acks="all",
            enable_idempotence=True,
        )
        await producer.start()
        return producer

    async def send_envelope(self, producer, topic: str, envelope: EventEnvelope) -> None:
        await producer.send_and_wait(
            topic,
            envelope.model_dump_json().encode("utf-8"),
            key=envelope.event_id.encode("utf-8"),
            headers=[
                ("schema_version", envelope.schema_version.encode("ascii")),
                ("event_type", envelope.event_type.encode("utf-8")),
            ],
        )

    async def relay_once(self, limit: int = 100) -> dict[str, int]:
        rows = await storage.list_pending_outbox(limit)
        if not rows:
            return {"published": 0, "failed": 0}
        producer = await self._producer()
        published = 0
        failed = 0
        try:
            for row in rows:
                try:
                    envelope = EventEnvelope.model_validate(json.loads(row["payload"]))
                    await self.send_envelope(producer, row["topic"], envelope)
                    await storage.mark_outbox_published(row["id"])
                    published += 1
                except Exception as exc:
                    await storage.mark_outbox_failed(row["id"], type(exc).__name__)
                    failed += 1
        finally:
            await producer.stop()
        return {"published": published, "failed": failed}

    async def replay_event(self, event_id: str) -> dict[str, Any]:
        row = await storage.get_outbox_event(event_id)
        if row is None:
            raise ValueError(f"Outbox event not found: {event_id}")
        envelope = EventEnvelope.model_validate(json.loads(row["payload"]))
        envelope.metadata = {
            **envelope.metadata,
            "replayed_at": datetime.now(UTC).isoformat(),
        }
        producer = await self._producer()
        try:
            await self.send_envelope(producer, row["topic"], envelope)
        finally:
            await producer.stop()
        return {"event_id": event_id, "topic": row["topic"], "replayed": True}


publisher = OutboxPublisher()
relay = OutboxRelay()
