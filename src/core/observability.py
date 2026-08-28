from __future__ import annotations

from contextlib import nullcontext
from typing import Any

from src.core.config import get_settings

_configured = False


def configure_telemetry() -> None:
    global _configured
    settings = get_settings()
    if _configured or not settings.OTEL_ENABLED:
        return
    from opentelemetry import trace
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    provider = TracerProvider(resource=Resource.create({"service.name": settings.APP_NAME}))
    if settings.OTEL_EXPORTER_OTLP_ENDPOINT:
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(
            endpoint=settings.OTEL_EXPORTER_OTLP_ENDPOINT,
            insecure=settings.OTEL_EXPORTER_OTLP_ENDPOINT.startswith("http://"),
        )))
    trace.set_tracer_provider(provider)
    _configured = True


def span(name: str, attributes: dict[str, Any] | None = None):
    if not get_settings().OTEL_ENABLED:
        return nullcontext()
    from opentelemetry import trace

    safe_attributes = {
        key: value
        for key, value in (attributes or {}).items()
        if isinstance(value, str | bool | int | float)
    }
    return trace.get_tracer("membrane-engineering").start_as_current_span(
        name,
        attributes=safe_attributes,
    )
