"""Validate Kafka outbox relay, inbox idempotency, DLQ and event-id replay."""

from __future__ import annotations

import asyncio
import json
import sys
import time
import uuid
from pathlib import Path

import httpx
from aiokafka import AIOKafkaConsumer
from aiokafka.admin import AIOKafkaAdminClient, NewTopic
from sqlalchemy import select
from temporalio.client import Client

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.validate_temporal import assert_worker_running, start_worker, stop_worker
from src.core.config import get_settings
from src.engineering.storage import SessionFactory, inbox_events, outbox_events
from src.events.kafka_consumer import KafkaEventConsumer
from src.events.kafka_events import EventEnvelope, publisher, relay
from src.main import app


async def wait_inbox(event_ids: list[str], consumer_name: str, timeout: float = 90) -> dict[str, str]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        async with SessionFactory() as session:
            result = await session.execute(
                select(inbox_events.c.event_id, inbox_events.c.status).where(
                    inbox_events.c.event_id.in_(event_ids),
                    inbox_events.c.consumer == consumer_name,
                )
            )
            statuses = {row.event_id: row.status for row in result}
        if len(statuses) == len(event_ids) and all(status in {"processed", "failed"} for status in statuses.values()):
            return statuses
        await asyncio.sleep(1)
    raise TimeoutError(f"Inbox events did not settle: {event_ids}")


async def read_dlq(expected_event_id: str, settings) -> EventEnvelope:
    consumer = AIOKafkaConsumer(
        f"{settings.KAFKA_TOPIC_PREFIX}.dlq",
        bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
        group_id=f"dlq-validation-{uuid.uuid4().hex}",
        auto_offset_reset="earliest",
    )
    await consumer.start()
    try:
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            message = await asyncio.wait_for(consumer.getone(), timeout=10)
            envelope = EventEnvelope.model_validate_json(message.value)
            if envelope.aggregate_id == expected_event_id:
                return envelope
    finally:
        await consumer.stop()
    raise TimeoutError(f"DLQ event not found for {expected_event_id}")


async def ensure_topics(settings) -> None:
    admin = AIOKafkaAdminClient(bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS)
    await admin.start()
    try:
        existing = await admin.list_topics()
        names = {
            f"{settings.KAFKA_TOPIC_PREFIX}.document.ingest.requested",
            f"{settings.KAFKA_TOPIC_PREFIX}.test.consumer.failure",
            f"{settings.KAFKA_TOPIC_PREFIX}.dlq",
        }
        missing = [
            NewTopic(name=name, num_partitions=1, replication_factor=1)
            for name in sorted(names - set(existing))
        ]
        if missing:
            await admin.create_topics(missing)
    finally:
        await admin.close()


async def main() -> None:
    settings = get_settings()
    if not (settings.KAFKA_ENABLED and settings.TEMPORAL_ENABLED and settings.RUNTIME_MODE.lower() == "full"):
        raise RuntimeError("validate_kafka.py requires Full mode with Kafka and Temporal enabled")
    worker = start_worker(delay_seconds=0)
    consumer_name = f"kafka-validation-{uuid.uuid4().hex[:10]}"
    consumer_task = None
    try:
        await asyncio.sleep(3)
        assert_worker_running(worker)
        await ensure_topics(settings)
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test", timeout=120) as client:
                document_ids = []
                for index in (1, 2):
                    uploaded = await client.post(
                        "/api/v1/documents/upload",
                        files={
                            "file": (
                                f"kafka-batch-{uuid.uuid4().hex[:8]}-{index}.txt",
                                f"Kafka batch document {index}".encode(),
                                "text/plain",
                            )
                        },
                    )
                    uploaded.raise_for_status()
                    document_ids.append(uploaded.json()["document_id"])

                batch = await client.post("/api/v1/batch-imports", json={"document_ids": document_ids})
                batch.raise_for_status()
                batch_payload = batch.json()
                failure = await publisher.publish(
                    "test.consumer.failure",
                    f"failure-{uuid.uuid4().hex[:8]}",
                    {"purpose": "dlq-validation"},
                )
                event_ids = batch_payload["event_ids"] + [failure["event_id"]]

                consumer_task = asyncio.create_task(
                    KafkaEventConsumer(
                        consumer_name=consumer_name,
                        auto_offset_reset="latest",
                    ).run(max_messages=4)
                )
                await asyncio.sleep(5)
                relay_result = await relay.relay_once(limit=100)
                if relay_result["published"] < 3 or relay_result["failed"] != 0:
                    raise AssertionError(f"Unexpected relay result: {relay_result}")
                statuses = await wait_inbox(event_ids, consumer_name)
                if [statuses[event_id] for event_id in batch_payload["event_ids"]] != ["processed", "processed"]:
                    raise AssertionError(f"Batch events were not processed: {statuses}")
                if statuses[failure["event_id"]] != "failed":
                    raise AssertionError(f"Failure event did not enter failed inbox state: {statuses}")

                replay = await client.post(f"/api/v1/events/{batch_payload['event_ids'][0]}/replay")
                replay.raise_for_status()
                consumer_stats = await asyncio.wait_for(consumer_task, timeout=60)
                if consumer_stats != {"processed": 2, "duplicates": 1, "failed": 1}:
                    raise AssertionError(f"Unexpected consumer stats: {consumer_stats}")

                dlq = await read_dlq(failure["event_id"], settings)
                if dlq.event_type != "system.event.dlq":
                    raise AssertionError(f"Unexpected DLQ event type: {dlq.event_type}")

                temporal = await Client.connect(settings.TEMPORAL_TARGET, namespace=settings.TEMPORAL_NAMESPACE)
                workflow_states = []
                for document_id in document_ids:
                    handle = temporal.get_workflow_handle(f"document-ingest:{document_id}")
                    workflow_states.append(await asyncio.wait_for(handle.result(), timeout=180))
                if any(state["status"] != "completed" for state in workflow_states):
                    raise AssertionError(f"Kafka-triggered Temporal workflows failed: {workflow_states}")

                async with SessionFactory() as session:
                    outbox_result = await session.execute(
                        select(outbox_events.c.id, outbox_events.c.published_at).where(
                            outbox_events.c.id.in_(event_ids)
                        )
                    )
                    published_rows = list(outbox_result)
                if len(published_rows) != 3 or any(row.published_at is None for row in published_rows):
                    raise AssertionError("Outbox rows were not marked published")

                summary = {
                    "batch_events": 2,
                    "relay_published": relay_result["published"],
                    "consumer": consumer_stats,
                    "dlq_event_type": dlq.event_type,
                    "replayed_event_id_preserved": replay.json()["event_id"] == batch_payload["event_ids"][0],
                    "temporal_workflows": [state["status"] for state in workflow_states],
                }
                print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    finally:
        if consumer_task is not None and not consumer_task.done():
            consumer_task.cancel()
            await asyncio.gather(consumer_task, return_exceptions=True)
        stop_worker(worker)


if __name__ == "__main__":
    asyncio.run(main())
