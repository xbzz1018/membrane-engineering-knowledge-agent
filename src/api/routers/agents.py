from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from src.api.dependencies import current_principal, require_project_role
from src.core.security import Principal
from src.infrastructure.database import storage

router = APIRouter(tags=["智能体与执行轨迹"])


@router.get("/api/v1/agents", summary="查看多智能体拓扑与职责")
async def agent_topology(principal: Principal = Depends(current_principal)) -> dict:
    return {
        "orchestrator": {
            "name": "ReviewSupervisorAgent",
            "type": "langchain_supervisor_with_subagent_tools",
            "description": "规划领域并调用 review_retrieval/review_material/review_review 子Agent工具，服务端汇总证据结果。",
            "offline_model": "本地 Fake 模式使用显式脚本模型驱动真实 LangChain 工具调用。",
        },
        "knowledge_agent": {
            "name": "KnowledgeAgent",
            "framework": "LangChain create_agent + LangGraph Checkpointer",
            "responsibility": "项目知识问答、可追溯检索与会话上下文。",
        },
        "review_agents": [
            {
                "name": "RetrievalAgent",
                "domain": "retrieval",
                "tool": "review_retrieval",
                "responsibility": "冻结包内查询证据、整理型号版次与出处。",
            },
            {
                "name": "MaterialAgent",
                "domain": "material",
                "tool": "review_material",
                "responsibility": "膜材型号、规格、单位、日期和版本审查。",
            },
            {
                "name": "ReviewAgent",
                "domain": "review",
                "tool": "review_review",
                "responsibility": "等待检索与材料结果，核验原文、缺项、适用要求及跨文档冲突。",
            },
        ],
        "execution_graph": "retrieval || material -> review",
        "model_routes": {"supervisor": "strong", "retrieval": "light", "material": "light", "review": "strong"},
        "security": {
            "shell": False,
            "arbitrary_network": False,
            "file_write": False,
            "evidence_scope": "仅接收服务端按项目授权生成的 EvidenceUnit",
        },
    }


@router.get("/api/v1/agent-runs", summary="查询项目智能体运行记录")
async def list_agent_runs(
    project_id: str = Query(description="项目ID"),
    business_id: str = Query(default="", description="审查ID或会话ID"),
    limit: int = Query(default=50, ge=1, le=200, description="最多返回数量"),
    principal: Principal = Depends(current_principal),
) -> list[dict]:
    await require_project_role(project_id, principal)
    return await storage.list_agent_runs(
        tenant_id=principal.tenant_id,
        project_id=project_id,
        business_id=business_id,
        limit=limit,
    )


@router.get("/api/v1/agent-runs/{run_id}", summary="查看单次智能体运行与步骤")
async def get_agent_run(
    run_id: str,
    principal: Principal = Depends(current_principal),
) -> dict:
    result = await storage.get_agent_run(run_id, principal.tenant_id)
    if not result:
        raise HTTPException(status_code=404, detail="智能体运行记录不存在")
    await require_project_role(result["project_id"], principal)
    return result
