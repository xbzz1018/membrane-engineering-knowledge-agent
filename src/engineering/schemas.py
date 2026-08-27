from __future__ import annotations

from pydantic import BaseModel, Field


class SourceRef(BaseModel):
    source_id: str
    title: str
    source_type: str
    location: str = ""
    url: str = ""
    excerpt: str = ""


class ChatRequest(BaseModel):
    user_id: str = Field(default="anonymous", min_length=1, max_length=64)
    session_id: str = Field(default="default", min_length=1, max_length=128)
    message: str = Field(min_length=1, max_length=4000)


class ChatResponse(BaseModel):
    answer: str
    session_id: str
    route: str
    agents_used: list[str] = Field(default_factory=list)
    sources: list[SourceRef] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    usage: dict = Field(default_factory=dict)


class DocumentResponse(BaseModel):
    document_id: str
    filename: str
    version: int
    parser: str
    status: str


class IndexResponse(BaseModel):
    document_id: str
    chunks: int
    parser: str
    status: str


class PackageReviewRequest(BaseModel):
    user_id: str = "anonymous"
    project_id: str = "default"
    document_ids: list[str] = Field(min_length=1, max_length=20)
    question: str = Field(default="比较资料中的设计方案、膜材规格和价格差异", max_length=2000)


class PackageReviewResponse(BaseModel):
    review_id: str
    status: str
    engine: str
    report: str
    sources: list[SourceRef] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    workflow: dict | None = None
