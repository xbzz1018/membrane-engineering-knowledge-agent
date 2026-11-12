"""Versioned preliminary proposals: declared requirements are never source evidence."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


def canonical(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def material_matches(preference: str, text: str) -> bool:
    if not preference:
        return True
    # A specified product identifier must not match its longer near neighbour.
    if re.fullmatch(r"(?:PTFE|PVDF|PVC|ETFE)(?:[-_][A-Z0-9]+)+", preference, re.I):
        return bool(re.search(r"(?<![A-Z0-9_-])" + re.escape(preference) + r"(?![A-Z0-9_-])", text, re.I))
    return preference.casefold() in text.casefold()


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class PlanRequirements(StrictModel):
    project_name: str = Field(min_length=1, max_length=160)
    building_area_m2: float | None = Field(default=None, gt=0, le=1_000_000, allow_inf_nan=False)
    location: str = Field(default="", max_length=300)
    purpose: str = Field(default="停车棚", min_length=1, max_length=200)
    preferred_membrane: str = Field(default="", max_length=100)
    applicable_revision: str = Field(default="", max_length=100)
    notes: str = Field(default="", max_length=4000)


class PlanSection(StrictModel):
    section_id: Literal["overview", "technical", "implementation", "boundaries"]
    title: str = Field(min_length=1, max_length=100)
    content: str = Field(min_length=1, max_length=4000)
    origin: Literal["proposed"] = "proposed"


class PlanQuotation(StrictModel):
    purpose: Literal["history", "material"]
    evidence_id: str = Field(min_length=1, max_length=128)
    quote: str = Field(min_length=1, max_length=1200)


class PlanContent(StrictModel):
    requirements: PlanRequirements
    sections: list[PlanSection] = Field(min_length=1, max_length=4)
    source_quotes: list[PlanQuotation] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def unique_sections(self):
        ids = [section.section_id for section in self.sections]
        if len(ids) != len(set(ids)):
            raise ValueError("章节ID不能重复")
        return self


class CreatePlanRequest(StrictModel):
    request_id: str = Field(min_length=8, max_length=128)
    requirements: PlanRequirements


class RevisionRequest(StrictModel):
    request_id: str = Field(min_length=8, max_length=128)
    base_version: int = Field(ge=1)
    expected_lock_version: int = Field(ge=1)
    content: PlanContent
    reason: str = Field(min_length=1, max_length=1000)


class PlanDecisionRequest(StrictModel):
    command_id: str = Field(min_length=8, max_length=128)
    expected_lock_version: int = Field(ge=1)
    review_id: str = Field(min_length=1, max_length=64)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    manifest_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    decision: Literal["approved", "rejected"]
    reason: str = Field(min_length=1, max_length=1000)


class PlanExportRequest(StrictModel):
    formats: list[Literal["md", "docx"]] = Field(default_factory=lambda: ["md", "docx"], min_length=1, max_length=2)


def requirements_from_chat(message: str) -> PlanRequirements:
    """Extract explicit surface values only. Unknown engineering inputs stay blank."""
    area = re.search(r"(?P<area>\d+(?:\.\d+)?)\s*(?:平方米|平米|m²|m2|㎡)", message, re.I)
    membrane = re.search(r"(?:PTFE|PVDF|PVC|ETFE)(?:[-_][A-Z0-9]+)?", message, re.I)
    location = re.search(r"(?:项目地点|地点|位置)\s*[:：]\s*([^，,；;。\n]{1,100})", message)
    return PlanRequirements(
        project_name="膜结构停车棚初步方案", building_area_m2=float(area["area"]) if area else None,
        preferred_membrane=membrane.group().upper() if membrane else "",
        location=location[1].strip() if location else "", notes=message,
    )


def plan_gate(content: PlanContent, manifest: dict) -> list[dict]:
    """Hard gates apply to structured requirements/quotes; narrative remains proposed."""
    issues = []

    def add(path, message):
        issues.append({"target_path": path, "message": message, "blocking": True})

    required = {"overview", "technical", "implementation", "boundaries"}
    if required != {section.section_id for section in content.sections}:
        add("sections", "缺少概况、技术建议、实施安排或适用边界章节")
    for field in ("building_area_m2", "location", "preferred_membrane", "purpose"):
        if not getattr(content.requirements, field):
            add("requirements." + field, "用户尚未声明该必需需求；需完善后重新审查")
    evidence = {item["evidence_id"]: item for item in manifest.get("evidence", [])}
    roles = manifest.get("role_evidence_ids", {})
    covered = set()
    for index, quote in enumerate(content.source_quotes):
        path = f"source_quotes.{index}"
        source = evidence.get(quote.evidence_id)
        if not source or quote.evidence_id not in roles.get(quote.purpose, []):
            add(path, "引用不在本版本对应角色的原始依据范围内")
        elif quote.quote not in source["text"]:
            add(path, "引文并非来源原文，不能确认引用")
        else:
            covered.add(quote.purpose)
    for role in ("history", "material"):
        if role not in covered:
            add("source_quotes", f"缺少{role}的有效原文依据")
    for item in manifest.get("evidence", []):
        business = item.get("business_metadata") or {}
        revision = content.requirements.applicable_revision
        if revision and business and business.get("applicable_revision") != revision:
            add("source_quotes", "资料声明的适用版次与当前方案需求不同")
        for field, expired in (("effective_from", False), ("effective_to", True)):
            value = business.get(field)
            if value:
                effective = date.fromisoformat(str(value)[:10])
                today = date.today()
                if (expired and effective < today) or (not expired and effective > today):
                    add("source_quotes", "来源声明的业务有效期不覆盖审查日期")
    # Proposed prose is deliberately not a new channel for exact specifications.
    # Exact values belong in requirements or literal source quotations.
    precise = re.compile(r"\d|(?:PTFE|PVDF|PVC|ETFE)[-_][A-Z0-9]+|(?:保证|确保).{0,8}(?:安全|合格)", re.I)
    for index, section in enumerate(content.sections):
        if precise.search(section.content) or precise.search(section.title):
            add(f"sections.{index}.content", "建议正文含精确数值、型号或保证性结论；请放入声明需求/逐字依据，避免未经核验参数")
    return issues
