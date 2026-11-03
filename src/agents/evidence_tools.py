"""Read-only lookup inside an immutable, already authorized review snapshot.

Project-wide PostgreSQL/pgvector retrieval remains in RetrievalService. During
review, no tool may silently add live documents to a frozen evidence manifest.
"""

import json
import re

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, ConfigDict, Field


class EvidenceLookupInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=1, max_length=500)
    limit: int = Field(default=8, ge=1, le=20)


def frozen_evidence_tool(evidence: list[dict], *, material_only: bool = False) -> StructuredTool:
    if material_only:
        from src.domain.review_rules import evidence_role

        evidence = [row for row in evidence if evidence_role(row) == "material"]
    async def lookup(query: str, limit: int = 8) -> str:
        terms = set(re.findall(r"[\w-]+", query.lower()))
        ranked = []
        for row in evidence:
            body = " ".join(str(row.get(key, "")) for key in ("filename", "location", "text")).lower()
            score = sum(term in body for term in terms)
            if score:
                ranked.append((score, str(row["evidence_id"]), row))
        ranked.sort(key=lambda item: (-item[0], item[1]))
        return json.dumps({
            "scope": "frozen_review_snapshot", "backend": "snapshot_lexical",
            "query": query, "evidence": [row for _, _, row in ranked[:limit]],
            "missing_evidence_requires_new_review": True,
        }, ensure_ascii=False)

    return StructuredTool.from_function(
        coroutine=lookup, name="query_frozen_material_specs" if material_only else "search_frozen_evidence",
        description=("在冻结包的规格书中查询材料参数，逐字保留数值、单位、位置与引用。" if material_only else
                     "在本次授权且冻结的资料包内查找型号、版次、原文与位置；无结果须补证，不能扩大项目范围。"),
        args_schema=EvidenceLookupInput,
    )
