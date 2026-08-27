from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.core.config import get_settings
from src.engineering.storage import storage


async def main() -> None:
    from aiokafka import AIOKafkaConsumer

    settings = get_settings()
    topics = [
        f"{settings.KAFKA_TOPIC_PREFIX}.document.ingest.completed",
        f"{settings.KAFKA_TOPIC_PREFIX}.package.review.completed",
    ]
    consumer = AIOKafkaConsumer(
        *topics,
        bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
        group_id="membrane-audit",
        auto_offset_reset="earliest",
    )
    await consumer.start()
    try:
        async for message in consumer:
            event = json.loads(message.value.decode("utf-8"))
            event_id = event.get("event_id") or f"{message.topic}:{message.partition}:{message.offset}"
            if not await storage.claim_inbox_event(event_id, "membrane-audit"):
                continue
            print(json.dumps({"topic": message.topic, "event_id": event_id}, ensure_ascii=False))
    finally:
        await consumer.stop()


if __name__ == "__main__":
    asyncio.run(main())
