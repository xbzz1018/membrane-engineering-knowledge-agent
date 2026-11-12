from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from src.domain.chat_routing import ChatRoutingInfo


class SourceRef(BaseModel):
    model_config = ConfigDict(title="证据来源")
    content_sha256: str = Field(default="", description="完整证据文本SHA256，用于核对重新解析后的证据")
    document_sha256: str = Field(default="", description="原资料文件SHA256")
    source_id: str = Field(description="稳定证据ID")
    title: str = Field(description="文件或数据标题")
    source_type: str = Field(description="来源类型")
    location: str = Field(default="", description="页码、段落或工作表位置")
    url: str = Field(default="", description="公开来源URL")
    excerpt: str = Field(default="", description="证据摘要")
    date: str = Field(default="", description="资料日期或抓取日期")
    version: str = Field(default="", description="业务或来源版本")
    retrieval: list[dict] = Field(default_factory=list, description="检索通道、排名和分数")
    fusion_score: float | None = Field(default=None, description="融合得分")
    fusion_method: str = Field(default="", description="融合方法")


class IssueEvidenceRef(BaseModel):
    model_config = ConfigDict(title="问题证据定位")
    evidence_id: str = Field(description="证据ID")
    filename: str = Field(default="", description="证据文件名")
    location: str = Field(default="", description="页码或 Office 定位")
    version: str = Field(default="", description="业务版本")


class ChatRequest(BaseModel):
    model_config = ConfigDict(title="知识问答请求")
    user_id: str = Field(default="", max_length=64, description="已废弃；身份来自JWT")
    project_id: str = Field(default="demo-project", min_length=1, max_length=128, description="项目ID")
    session_id: str = Field(default="default", min_length=1, max_length=128, description="会话ID")
    message: str = Field(min_length=1, max_length=4000, description="用户问题")
    request_id: str | None = Field(default=None, min_length=8, max_length=128, description="动作请求幂等标识；重试复用")


class ChatResponse(BaseModel):
    model_config = ConfigDict(title="知识问答响应")
    answer: str
    session_id: str
    route: str
    answer_origin: Literal["general_knowledge", "project_evidence", "workflow_guidance", "clarification"] = "project_evidence"
    routing: ChatRoutingInfo | None = None
    agents_used: list[str] = Field(default_factory=list)
    sources: list[SourceRef] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    usage: dict = Field(default_factory=dict)
    memory_candidates: list[dict] = Field(default_factory=list)
    project_plan: dict | None = Field(default=None, description="受理的方案ID、版本、状态与工作流引用")


class DocumentResponse(BaseModel):
    model_config = ConfigDict(title="工程资料响应")
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
    model_config = ConfigDict(title="资料索引响应")
    document_id: str
    chunks: int
    parser: str
    status: str
    workflow_id: str = ""


class ReviewIssue(BaseModel):
    """工程资料审查问题单；结论必须能回指到证据片段。"""

    model_config = ConfigDict(title="工程审查问题单")
    issue_id: str = Field(default="", max_length=128, description="稳定问题编号")
    domain: Literal["retrieval", "material", "review", "design", "price", "cross_domain"] = Field(default="design", description="问题所属领域")
    issue_type: str = Field(default="finding", max_length=64, description="问题类型")
    summary: str = Field(default="", max_length=1000, description="问题摘要")
    severity: Literal["info", "warning", "conflict"] = "info"
    actual_value: str = Field(default="", max_length=1000, description="资料中的实际值")
    expected_value: str = Field(default="", max_length=1000, description="期望或比较基准")
    evidence_ids: list[str] = Field(default_factory=list, description="支持问题的证据ID")
    evidence_refs: list[IssueEvidenceRef] = Field(default_factory=list, description="证据文件、位置和版本")
    recommendation: str = Field(default="", max_length=1000, description="处理建议")
    status: Literal["open", "pending_human", "resolved", "dismissed"] = "open"
    requires_human: bool = False


class PackageReviewRequest(BaseModel):
    model_config = ConfigDict(title="多智能体资料包审查请求")
    user_id: str = Field(default="", description="已废弃；身份来自JWT")
    project_id: str = Field(default="demo-project", description="项目ID")
    document_ids: list[str] = Field(min_length=1, max_length=20, description="1至20份已索引资料ID")
    question: str = Field(
        default="查找资料依据、核验材料参数并审查跨文档一致性",
        max_length=2000,
        description="审查目标",
    )
    review_mode: Literal["full", "focused"] = Field(
        default="full",
        description="full必须覆盖检索/材料/审查，focused由Supervisor受限选择；审查依赖前两角色",
    )


class PackageReviewResponse(BaseModel):
    model_config = ConfigDict(title="多智能体资料包审查响应")
    review_id: str
    status: str
    engine: str
    report: str
    sources: list[SourceRef] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    workflow: dict | None = None
    created_at: str = ""
    worker_results: dict = Field(default_factory=dict)
    issues: list[ReviewIssue] = Field(default_factory=list, description="结构化工程问题单")
    agents_used: list[str] = Field(default_factory=list, description="实际参与的业务智能体")
    orchestrator: str = Field(default="ReviewSupervisorAgent", description="审查计划智能体")
    review_plan: dict = Field(default_factory=dict, description="Supervisor 生成的审查计划")
    review_mode: Literal["full", "focused"] = Field(default="full", description="full三领域审查或focused专项审查")
    usage: dict = Field(default_factory=dict)
    human_review_required: bool = False
    lock_version: int = Field(default=1, ge=1, description="审查报告乐观锁版本")


class ReviewIssueStatusRequest(BaseModel):
    reason: str = Field(default="", max_length=1000, description="处理说明；忽略问题时必填")
    model_config = ConfigDict(title="审查问题处理请求")
    status: Literal["resolved", "dismissed", "pending_human"]
    expected_lock_version: int = Field(ge=1, description="读取报告时获得的乐观锁版本")


class ReviewDecisionRequest(BaseModel):
    decision: Literal["approved", "rejected"]
    expected_lock_version: int = Field(ge=1)
    reason: str = Field(default="", max_length=1000)


class MemoryItemResponse(BaseModel):
    model_config = ConfigDict(title="长期记忆")
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
    model_config = ConfigDict(title="长期记忆候选请求")
    project_id: str | None = Field(default=None, max_length=128)
    scope: str = Field(pattern="^(user|project)$")
    kind: str = Field(default="project_context", min_length=1, max_length=32)
    content: str = Field(min_length=1, max_length=4000)
    source_id: str = Field(default="", max_length=128)


class MemoryUpdateRequest(BaseModel):
    model_config = ConfigDict(title="长期记忆更新请求")
    content: str = Field(min_length=1, max_length=4000, description="更新后的记忆内容，需重新确认")


class WorkflowDecisionRequest(BaseModel):
    expected_lock_version: int = Field(ge=1, description="报告当前乐观锁版本")
    model_config = ConfigDict(title="工作流决定请求")
    reason: str = Field(default="", max_length=1000, description="退回原因")


class BatchImportRequest(BaseModel):
    model_config = ConfigDict(title="批量导入请求")
    document_ids: list[str] = Field(min_length=1, max_length=100, description="最多100份资料ID")
    project_id: str = Field(default="demo-project", min_length=1, max_length=128, description="项目ID")


class BudgetUpdateRequest(BaseModel):
    model_config = ConfigDict(title="项目预算更新请求")
    daily_token_limit: int = Field(ge=10_000)
    monthly_cost_limit_micros: int = Field(ge=0)
    max_concurrent_reviews: int = Field(ge=1, le=100)
    expected_lock_version: int = Field(ge=1)


class ArchiveRequest(BaseModel):
    model_config = ConfigDict(title="台账归档请求")
    expected_lock_version: int = Field(ge=1)


class MaterialSpecCreateRequest(BaseModel):
    model_config = ConfigDict(title="膜材规格创建请求")
    manufacturer: str = Field(min_length=1, max_length=256)
    material: str = Field(min_length=1, max_length=256)
    product_reference: str = Field(min_length=1, max_length=128)
    specification: str = Field(min_length=1, max_length=4000)
    application: str = Field(default="", max_length=2000)
    source_url: str = Field(min_length=1, max_length=2000)
    source_version: str = Field(min_length=1, max_length=128)
    source_page: int | None = Field(default=None, ge=1)
    source_page_count: int | None = Field(default=None, ge=1)
    license: str = Field(min_length=1, max_length=1000)
    retrieved_at: str = Field(min_length=1, max_length=64)
    source_sha256: str = Field(pattern="^[A-Fa-f0-9]{64}$")
    visibility: Literal["public", "internal", "restricted"] = "public"
    synthetic: bool = False


class MaterialSpecUpdateRequest(BaseModel):
    model_config = ConfigDict(title="膜材规格更新请求")
    expected_lock_version: int = Field(ge=1)
    manufacturer: str | None = Field(default=None, min_length=1, max_length=256)
    material: str | None = Field(default=None, min_length=1, max_length=256)
    product_reference: str | None = Field(default=None, min_length=1, max_length=128)
    specification: str | None = Field(default=None, min_length=1, max_length=4000)
    application: str | None = Field(default=None, max_length=2000)
    source_url: str | None = Field(default=None, min_length=1, max_length=2000)
    source_version: str | None = Field(default=None, min_length=1, max_length=128)
    source_page: int | None = Field(default=None, ge=1)
    source_page_count: int | None = Field(default=None, ge=1)
    license: str | None = Field(default=None, min_length=1, max_length=1000)
    retrieved_at: str | None = Field(default=None, min_length=1, max_length=64)
    source_sha256: str | None = Field(default=None, pattern="^[A-Fa-f0-9]{64}$")
    visibility: Literal["public", "internal", "restricted"] | None = None
    synthetic: bool | None = None


class PriceRecordCreateRequest(BaseModel):
    model_config = ConfigDict(title="历史价格创建请求")
    project_id: str = Field(default="", max_length=128)
    material: str = Field(min_length=1, max_length=256)
    specification: str = Field(min_length=1, max_length=4000)
    unit: str = Field(min_length=1, max_length=64)
    min_price: float = Field(ge=0)
    max_price: float = Field(ge=0)
    currency: str = Field(min_length=1, max_length=16)
    region: str = Field(min_length=1, max_length=128)
    effective_date: str = Field(min_length=1, max_length=32)
    source_url: str = Field(min_length=1, max_length=2000)
    source_version: str = Field(min_length=1, max_length=128)
    license: str = Field(min_length=1, max_length=1000)
    retrieved_at: str = Field(min_length=1, max_length=64)
    source_sha256: str = Field(pattern="^[A-Fa-f0-9]{64}$")
    visibility: Literal["public", "internal", "restricted"] = "public"
    synthetic: bool = True
    disclaimer: str = Field(default="历史参考数据，不构成正式报价。", min_length=1, max_length=1000)


class PriceRecordUpdateRequest(BaseModel):
    model_config = ConfigDict(title="历史价格更新请求")
    expected_lock_version: int = Field(ge=1)
    project_id: str | None = Field(default=None, max_length=128)
    material: str | None = Field(default=None, min_length=1, max_length=256)
    specification: str | None = Field(default=None, min_length=1, max_length=4000)
    unit: str | None = Field(default=None, min_length=1, max_length=64)
    min_price: float | None = Field(default=None, ge=0)
    max_price: float | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, min_length=1, max_length=16)
    region: str | None = Field(default=None, min_length=1, max_length=128)
    effective_date: str | None = Field(default=None, min_length=1, max_length=32)
    source_url: str | None = Field(default=None, min_length=1, max_length=2000)
    source_version: str | None = Field(default=None, min_length=1, max_length=128)
    license: str | None = Field(default=None, min_length=1, max_length=1000)
    retrieved_at: str | None = Field(default=None, min_length=1, max_length=64)
    source_sha256: str | None = Field(default=None, pattern="^[A-Fa-f0-9]{64}$")
    visibility: Literal["public", "internal", "restricted"] | None = None
    synthetic: bool | None = None
    disclaimer: str | None = Field(default=None, min_length=1, max_length=1000)
