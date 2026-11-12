"""Strict claim-level judge contract: the evaluator owns denominator and IDs."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, StrictBool


class ClaimVerdict(BaseModel):
    model_config = ConfigDict(extra="forbid")
    claim_id: str
    supported: StrictBool
    reason: str = Field(min_length=1, max_length=2000)


class JudgeVerdicts(BaseModel):
    model_config = ConfigDict(extra="forbid")
    verdicts: list[ClaimVerdict]


def validate_judge(answer: str, claim_ids: list[str]) -> dict:
    normalized = answer.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    parsed = JudgeVerdicts.model_validate_json(normalized)
    received = [item.claim_id for item in parsed.verdicts]
    if len(received) != len(set(received)) or set(received) != set(claim_ids):
        raise ValueError("Judge must return each expected claim exactly once")
    supported = sum(item.supported for item in parsed.verdicts)
    return {
        "supported": supported,
        "total": len(claim_ids),
        "score": supported / len(claim_ids) if claim_ids else None,
        "verdicts": [item.model_dump() for item in parsed.verdicts],
    }
