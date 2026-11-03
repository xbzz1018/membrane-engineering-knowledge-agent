"""Model proposes cited leads; application owns report IDs, status and provenance."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class CitedQuote(BaseModel):
    model_config = ConfigDict(extra="forbid")
    evidence_id: str
    quote: str = Field(min_length=1, max_length=1000)


class ModelFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    check: Literal["version", "thickness", "material_reference", "price_basis", "other"]
    summary: str = Field(min_length=1, max_length=1000)
    severity: Literal["info", "warning", "conflict"] = "warning"
    actual_value: str = Field(default="", max_length=1000)
    expected_value: str = Field(default="", max_length=1000)
    evidence_ids: list[str] = Field(min_length=1)
    quotes: list[CitedQuote] = Field(min_length=1)
    recommendation: str = Field(default="", max_length=1000)


class ModelBlockingGap(BaseModel):
    model_config = ConfigDict(extra="forbid")
    check: Literal["version", "thickness", "material_reference", "price_basis", "other"]
    required_fact: str = Field(min_length=1, max_length=1000)
    reason: str = Field(min_length=1, max_length=1000)
    evidence_ids: list[str] = Field(min_length=1)


class ModelWorkerReview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    worker: Literal["design", "material", "price"]
    findings: list[ModelFinding] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    blocking_gaps: list[ModelBlockingGap] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    processed_evidence_ids: list[str] = Field(default_factory=list)
    skipped_evidence_ids: list[str] = Field(default_factory=list)
    skipped_reasons: dict[str, str] = Field(default_factory=dict)
