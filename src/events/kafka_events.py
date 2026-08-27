from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from src.core.config import get_settings


class KafkaPublisher:
    """Optional publisher; disabled mode keeps local development dependency-free."""

    def __init__(self):
        self.settings = get_settings()

    async def publish(self, event_type: str, aggregate_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.settings.KAFKA_ENABLED:
            return {"published": False, "reason": "disabled", "event_type": event_type}
        try:
            from aiokafka import AIOKafkaProducer
        except Exception as exc:
            return {"published": False, "reason": f"aiokafka unavailable: {exc}", "event_type": event_type}
        topic = f"{self.settings.KAFKA_TOPIC_PREFIX}.{event_type}"
        event = {"aggregate_id": aggregate_id, "payload": payload, "created_at": datetime.now(UTC).isoformat()}
        producer = AIOKafkaProducer(bootstrap_servers=self.settings.KAFKA_BOOTSTRAP_SERVERS)
        try:
            await producer.start()
            await producer.send_and_wait(topic, json.dumps(event, ensure_ascii=False).encode("utf-8"), key=aggregate_id.encode("utf-8"))
            return {"published": True, "topic": topic}
        finally:
            await producer.stop()


publisher = KafkaPublisher()
