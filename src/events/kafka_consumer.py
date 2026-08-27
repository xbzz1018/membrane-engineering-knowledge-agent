from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from src.core.config import get_settings
from src.engineering.storage import storage
from src.events.kafka_events import EventEnvelope
from src.workflows.temporal_app import submit_document_ingest


async def process_event(envelope: EventEnvelope) -> dict[str, Any]:
    if envelope.event_type == "document.ingest.requested":
        document_id = str(envelope.payload.get("document_id") or envelope.aggregate_id)
        workflow = await submit_document_ingest(document_id)
        if not workflow.get("enabled"):
            raise RuntimeError("Temporal must be enabled for document ingest events")
        return {"action": "temporal_document_ingest", "workflow_id": workflow["workflow_id"]}
    if envelope.event_type == "test.consumer.failure":
        raise RuntimeError("Intentional consumer failure for DLQ validation")
    return {"action": "audit_only"}


class KafkaEventConsumer:
    def __init__(self, consumer_name: str = "membrane-audit", auto_offset_reset: str = "earliest"):
        self.settings = get_settings()
        self.consumer_name = consumer_name
        self.auto_offset_reset = auto_offset_reset

    async def _send_dlq(self, producer, message, envelope: EventEnvelope | None, exc: Exception) -> None:
        original_event_id = envelope.event_id if envelope else f"{message.topic}:{message.partition}:{message.offset}"
        dlq = EventEnvelope.create(
            event_type="system.event.dlq",
            aggregate_type="event",
            aggregate_id=original_event_id,
            payload={
                "original_event": envelope.model_dump(mode="json") if envelope else None,
                "source_topic": message.topic,
                "source_partition": message.partition,
                "source_offset": message.offset,
                "error_type": type(exc).__name__,
                "failed_at": datetime.now(UTC).isoformat(),
            },
        )
        await producer.send_and_wait(
            f"{self.settings.KAFKA_TOPIC_PREFIX}.dlq",
            dlq.model_dump_json().encode("utf-8"),
            key=original_event_id.encode("utf-8"),
        )

    async def run(self, max_messages: int | None = None) -> dict[str, int]:
        from aiokafka import AIOKafkaConsumer, AIOKafkaProducer

        consumer = AIOKafkaConsumer(
            bootstrap_servers=self.settings.KAFKA_BOOTSTRAP_SERVERS,
            group_id=self.consumer_name,
            auto_offset_reset=self.auto_offset_reset,
            enable_auto_commit=False,
        )
        consumer.subscribe(pattern=rf"^{re.escape(self.settings.KAFKA_TOPIC_PREFIX)}\.(?!dlq$).+")
        producer = AIOKafkaProducer(
            bootstrap_servers=self.settings.KAFKA_BOOTSTRAP_SERVERS,
            acks="all",
            enable_idempotence=True,
        )
        stats = {"processed": 0, "duplicates": 0, "failed": 0}
        await consumer.start()
        await producer.start()
        try:
            async for message in consumer:
                envelope: EventEnvelope | None = None
                try:
                    envelope = EventEnvelope.model_validate_json(message.value)
                    should_process = await storage.begin_inbox_event(
                        envelope.model_dump(mode="json"),
                        self.consumer_name,
                    )
                    if not should_process:
                        stats["duplicates"] += 1
                    else:
                        await process_event(envelope)
                        await storage.complete_inbox_event(envelope.event_id, self.consumer_name)
                        stats["processed"] += 1
                except Exception as exc:
                    if envelope is not None:
                        await storage.fail_inbox_event(envelope.event_id, self.consumer_name, type(exc).__name__)
                    await self._send_dlq(producer, message, envelope, exc)
                    stats["failed"] += 1
                await consumer.commit()
                if max_messages is not None and sum(stats.values()) >= max_messages:
                    break
        finally:
            await consumer.stop()
            await producer.stop()
        return stats
