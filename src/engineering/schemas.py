from __future__ import annotations

from pydantic import BaseModel, Field


class SourceRef(BaseModel):
    source_id: str
    title: str
    source_type: str
    location: str = ""
    url: str = ""
    excerpt: str = ""
    date: str = ""
    version: str = ""
    retrieval: list[dict] = Field(default_factory=list)
    fusion_score: float | None = None
    fusion_method: str = ""


class ChatRequest(BaseModel):
    user_id: str = Field(default="", max_length=64, description="Deprecated; identity comes from JWT")
    project_id: str = Field(default="demo-project", min_length=1, max_length=128)
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
    memory_candidates: list[dict] = Field(default_factory=list)


class DocumentResponse(BaseModel):
    document_id: str
    filename: str
    version: int
    parser: str
    status: str
    project_id: str = ""
    sha256: str = ""
    data_classification: str = "public"
    parse_method: str = "auto"


class IndexResponse(BaseModel):
    document_id: str
    chunks: int
    parser: str
    status: str
    workflow_id: str = ""


class PackageReviewRequest(BaseModel):
    user_id: str = Field(default="", description="Deprecated; identity comes from JWT")
    project_id: str = "demo-project"
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
    created_at: str = ""
    worker_results: dict = Field(default_factory=dict)
    usage: dict = Field(default_factory=dict)
    human_review_required: bool = False


class MemoryItemResponse(BaseModel):
    memory_id: str
    user_id: str
    kind: str
    content: str
    source: str
    created_at: str
    project_id: str = ""
    scope: str = "user"
    status: str = "pending"


class MemoryCandidateRequest(BaseModel):
    project_id: str | None = Field(default=None, max_length=128)
    scope: str = Field(pattern="^(user|project)$")
    kind: str = Field(default="project_context", min_length=1, max_length=32)
    content: str = Field(min_length=1, max_length=4000)
    source_id: str = Field(default="", max_length=128)


class MemoryUpdateRequest(BaseModel):
    content: str = Field(min_length=1, max_length=4000)


class WorkflowDecisionRequest(BaseModel):
    reason: str = Field(default="", max_length=1000)


class BatchImportRequest(BaseModel):
    document_ids: list[str] = Field(min_length=1, max_length=100)
    project_id: str = Field(default="demo-project", min_length=1, max_length=128)
