"""Write a structured draft, then adapt the existing ReviewAgent to that target."""

from __future__ import annotations

import json

from langchain.agents import create_agent
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, ConfigDict, ValidationError

from src.agents.conversation_supervisor import token_usage
from src.agents.knowledge_agent import AgentProtocolError, KnowledgeAgent
from src.agents.prompts import get_prompt
from src.agents.review_agents import PackageReviewService
from src.domain.project_plan import PlanContent, PlanQuotation, PlanRequirements, PlanSection, plan_gate
from src.infrastructure.model_provider import ProviderRequestError


class NoArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProjectPlanWriter:
    def __init__(self, provider):
        self.provider = provider

    async def generate(self, requirements: PlanRequirements, manifest: dict):
        if self.provider.metadata.get("mode") != "api":
            sections = [
                ("overview", "项目概况", "按用户声明的用途、面积、地点和材料偏好整理初步方案，需求与来源依据分别列示。"),
                ("technical", "技术建议", "建议将所列历史案例作为方案讨论参考，材料选用以引用规格和后续适用性确认为前提。"),
                ("implementation", "实施安排", "建议依次开展现场条件确认、方案深化、材料核验和实施交接，具体工期由业务人员补充确认。"),
                ("boundaries", "适用边界", "本文件为初步讨论方案，建议内容尚需专业人员确认；不包含结构计算、正式报价或工程合格性结论。"),
            ]
            by_id = {item["evidence_id"]: item for item in manifest.get("evidence", [])}
            quotes = []
            for role, ids in manifest.get("role_evidence_ids", {}).items():
                for evidence_id in ids[:2]:
                    quotes.append(PlanQuotation(purpose=role, evidence_id=evidence_id,
                                                quote=by_id[evidence_id]["text"][:1000]))
            content = PlanContent(
                requirements=requirements, source_quotes=quotes,
                sections=[PlanSection(section_id=key, title=title, content=text) for key, title, text in sections],
            )
            return content, {**self.provider.metadata, "input_tokens": 0, "output_tokens": 0, "calls": 0}
        prompt = get_prompt("project-plan-generation")
        agent = create_agent(
            model=self.provider.langchain_model(json_mode=True, enable_thinking=False),
            tools=[], system_prompt=prompt.text, name="project_plan_writer",
        )
        message = json.dumps({
            "user_declared_requirements": requirements.model_dump(mode="json"),
            "source_manifest": manifest, "schema": PlanContent.model_json_schema(),
        }, ensure_ascii=False)
        usage = {**self.provider.metadata, "input_tokens": 0, "output_tokens": 0, "calls": 0,
                 "prompt_version": prompt.version, "prompt_sha256": prompt.digest}
        for attempt in range(2):
            try:
                result = await agent.ainvoke({"messages": [{"role": "user", "content": message}]})
            except Exception as exc:
                raise ProviderRequestError(f"Project writer request failed ({type(exc).__name__})") from exc
            messages = result.get("messages", [])
            for key, value in token_usage(messages).items():
                usage[key] += value
            usage["calls"] += 1
            try:
                answer, _, _ = KnowledgeAgent._answer(messages)
                normalized = answer.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
                content = PlanContent.model_validate_json(normalized)
                if content.requirements != requirements:
                    raise ValueError("模型改写了用户声明需求")
                # Schema/invalid quotations are a protocol failure; legitimate
                # missing inputs remain a draft with explicit gate issues.
                bad_quotes = [issue for issue in plan_gate(content, manifest)
                              if issue["target_path"].startswith("source_quotes.")]
                if bad_quotes:
                    raise ValueError("模型引用未通过逐字/范围校验")
                return content, usage
            except (ValidationError, AgentProtocolError, ValueError):
                if attempt == 0:
                    message += "\n上次输出未通过校验。严格保留用户需求，仅逐字引用给定来源，按Schema输出完整JSON。"
        raise AgentProtocolError("方案模型连续两次返回无效内容，没有生成成功草稿")


class ProjectReviewAdapter:
    def __init__(self, service: PackageReviewService):
        self.service = service

    async def review(self, content: PlanContent, manifest: dict):
        issues = plan_gate(content, manifest)
        evidence = manifest.get("evidence", [])

        async def inspect():
            target = {
                "review_scope": "审查待审方案和给定原始依据之间的一致性。draft_target是待审对象，绝不是来源证据。"
                                "需求是用户声明；建议正文不是已确认工程参数；仅以source_evidence验证引用。",
                "draft_target": content.model_dump(mode="json"),
                "target_paths": ["requirements", "sections", "source_quotes"],
            }
            # The bounded manifest is already discovered/frozen by both query
            # roles. Reuse ReviewAgent's implementation, without rediscovery or
            # treating the generated draft as an uploaded evidence document.
            return await self.service._run_worker_batch(
                "review", json.dumps(target, ensure_ascii=False), evidence, [],
            )

        tool = StructuredTool.from_function(
            coroutine=inspect, name="review_project_plan", args_schema=NoArguments,
            description="审查服务端绑定的方案版本及原始来源，不允许指定身份或扩大数据范围。",
        )
        if evidence:
            worker, usage = await tool.ainvoke({})
            expected = {item["evidence_id"] for item in evidence}
            if expected - set(worker.processed_evidence_ids):
                issues.append({"target_path": "source_quotes", "blocking": True, "message": "综合审查未覆盖全部来源"})
            for finding in worker.findings:
                issues.append({"target_path": "source_quotes", "blocking": True,
                               "message": finding.summary, "finding": finding.model_dump(mode="json")})
            for gap in worker.blocking_gaps:
                issues.append({"target_path": "source_quotes", "blocking": True, "message": gap.reason})
            worker_result = worker.model_dump(mode="json")
        else:
            usage, worker_result = {}, None
        return {"issues": issues, "review_agent": worker_result, "usage": usage,
                "review_scope": "preliminary-plan-consistency-v1",
                "limitations": ["逐字引用及结构规则已检查；语义支持和工程适用性仍需业务人员复核。"]}
