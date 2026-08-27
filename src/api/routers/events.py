from __future__ import annotations

from fastapi import APIRouter, HTTPException

from src.core.config import get_settings
from src.engineering.schemas import BatchImportRequest
from src.engineering.storage import storage
from src.events.kafka_events import relay

router = APIRouter(prefix="/api/v1", tags=["batch-events"])


@router.post("/batch-imports", status_code=202)
async def create_batch_import(request: BatchImportRequest) -> dict:
    try:
        result = await storage.create_batch_import(
            request.document_ids,
            get_settings().KAFKA_TOPIC_PREFIX,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {**result, "status": "accepted", "relay_enabled": get_settings().KAFKA_ENABLED}


@router.post("/events/{event_id}/replay", status_code=202)
async def replay_event(event_id: str) -> dict:
    if not get_settings().KAFKA_ENABLED:
        raise HTTPException(status_code=409, detail="Kafka is disabled")
    try:
        return await relay.replay_event(event_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
