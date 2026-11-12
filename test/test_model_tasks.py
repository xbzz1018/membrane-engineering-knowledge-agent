from __future__ import annotations

import copy
import json
from argparse import Namespace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage, ToolMessage

from scripts.serve_task_adapters import build_command
from src.agents.knowledge_agent import AgentProtocolError, KnowledgeAgent
from src.agents.review_agents import PackageReviewService
from src.application.model_tasks import TaskAdapterService
from src.core.config import Settings, get_settings
from src.core.security import Principal
from src.infrastructure.database import storage
from src.infrastructure.model_provider import (
    ProviderConfigurationError,
    ProviderRequestError,
    get_task_model_provider,
)


class TaskProvider:
    def __init__(self, text, **usage):
        self.text = text
        self.usage = {"input_tokens": 12, "output_tokens": 8, "finish_reason": "stop", **usage}
        self.calls = []

    async def chat(self, system, user):
        self.calls.append((system, user))
        return self.text, self.usage


def settings(**updates):
    return Settings(_env_file=None, **{
        "MODEL_MODE": "api", "LORA_TASKS_ENABLED": True,
        "LORA_API_BASE": "http://127.0.0.1:8000/v1", "LORA_API_KEY": "local-test",
        **updates,
    })


def test_task_routes_use_separate_model_aliases_on_one_endpoint():
    config = settings()
    query = get_task_model_provider("query_normalization", config)
    review = get_task_model_provider("review_organization", config)
    assert query.model == "user" and review.model == "shencha"
    assert query._base_url() == review._base_url() == config.LORA_API_BASE
    assert config.GATEWAY_MODEL == ""  # Agent base/role routes were not changed.


@pytest.mark.parametrize("updates", [
    {"LORA_TASKS_ENABLED": False}, {"MODEL_MODE": "fake"}, {"LORA_API_BASE": ""},
    {"LORA_API_KEY": ""}, {"LORA_REVIEW_MODEL": "user"},
])
def test_incomplete_or_fake_task_routes_fail_closed(updates):
    with pytest.raises(ProviderConfigurationError):
        get_task_model_provider("query_normalization", settings(**updates))


@pytest.mark.asyncio
async def test_query_rewrite_keeps_original_and_preserves_exact_identifiers():
    query = "帮我找历史停车棚 PVDF 1050 的 R2 版本资料"
    provider = TaskProvider("查询历史停车棚 PVDF 1050 的 R2 版本资料。")
    text, usage = await TaskAdapterService("query_normalization", provider).normalize(query)
    assert text.startswith(query + "\n")
    assert usage["status"] == "accepted_with_original" and usage["input_tokens"] == 12


@pytest.mark.asyncio
@pytest.mark.parametrize("rewritten", ["查询 PVDF 1050A", "查询 PVDF", "查询 PVDF 1050，预算 20000 元"])
async def test_invalid_rewrite_explicitly_reuses_original(rewritten):
    query = "查询 PVDF 1050"
    text, usage = await TaskAdapterService("query_normalization", TaskProvider(rewritten)).normalize(query)
    assert text == query and usage["status"] == "rejected_original_query"


def review_fixture():
    result = {"status": "awaiting_approval", "report": "原始报告", "issues": [{
        "issue_id": "issue-1", "summary": "参数不一致", "severity": "conflict",
        "actual_value": "3500", "expected_value": "4000", "evidence_ids": ["ev-1"],
    }], "usage": {}}
    evidence = [{"evidence_id": "ev-1", "text": "参数实际3500，要求4000。",
                 "filename": "synthetic.txt", "location": "第1段", "version": "1"}]
    return result, evidence


@pytest.mark.asyncio
async def test_review_adapter_only_adds_presentation_and_keeps_findings_immutable():
    result, evidence = review_fixture()
    before = copy.deepcopy(result)
    organized = await TaskAdapterService("review_organization", TaskProvider(
        "issue-1：实际值3500，要求4000，参数不一致，请人工复核 [ev-1]。",
    )).organize(result, evidence)
    assert result == before
    assert organized["status"] == before["status"] and organized["issues"] == before["issues"]
    assert organized["report"].startswith(before["report"])
    assert organized["usage"]["review_organization"]["task"] == "review_organization"


@pytest.mark.asyncio
@pytest.mark.parametrize("text", [
    "issue-1：3500，4000 [unknown]", "issue-1：3500，5000 [ev-1]",
    "3500，4000 [ev-1]", "issue-1：3500，4000，预算8000 [ev-1]",
    "issue-1：3500，4000，保证工程安全 [ev-1]",
])
async def test_review_rejects_unknown_citations_changed_values_and_conclusions(text):
    result, evidence = review_fixture()
    with pytest.raises(ProviderRequestError):
        await TaskAdapterService("review_organization", TaskProvider(text)).organize(result, evidence)


@pytest.mark.asyncio
async def test_nonpublic_review_evidence_is_rejected_before_call():
    result, evidence = review_fixture()
    evidence[0]["data_classification"] = "internal"
    provider = TaskProvider("must not be called")
    with pytest.raises(ProviderRequestError):
        await TaskAdapterService("review_organization", provider).organize(result, evidence)
    assert not provider.calls


@pytest.mark.asyncio
async def test_truncated_output_is_a_failure_not_a_successful_rewrite():
    with pytest.raises(ProviderRequestError):
        await TaskAdapterService("query_normalization", TaskProvider("PVDF 1050", finish_reason="length")).normalize(
            "PVDF 1050",
        )


def test_launch_preflight_checks_base_and_selects_two_adapters(tmp_path):
    directories = [tmp_path / "query", tmp_path / "review"]
    for directory in directories:
        directory.mkdir()
        (directory / "adapter_model.safetensors").write_bytes(b"test existence only, not model weights")
        (directory / "adapter_config.json").write_text(json.dumps({
            "peft_type": "LORA", "task_type": "CAUSAL_LM", "r": 16, "base_model_name_or_path": "Qwen/example",
        }), encoding="utf-8")
    args = Namespace(query_name="user", review_name="shencha", base_name="membrane-base",
                     query_adapter=directories[0], review_adapter=directories[1], base="Qwen/example",
                     port=8000, max_model_len=4096, max_num_seqs=2, gpu_memory_utilization=0.8)
    command = build_command(args)
    assert command[command.index("--max-lora-rank") + 1] == "16"
    assert command[-2].startswith("user=") and command[-1].startswith("shencha=")
    args.base = "another/base"
    with pytest.raises(ValueError, match="base model"):
        build_command(args)


@pytest.mark.asyncio
@pytest.mark.parametrize("nonpublic", [False, True])
async def test_query_agent_adapter_is_after_visibility_gate_and_before_tools(monkeypatch, nonpublic):
    monkeypatch.setattr(get_settings(), "LORA_TASKS_ENABLED", True)
    task_provider = TaskProvider("查询历史停车棚 PVDF 1050 材料资料。")
    monkeypatch.setattr("src.application.model_tasks.get_task_model_provider", lambda _task: task_provider)
    monkeypatch.setattr(storage, "project_has_nonpublic_documents", AsyncMock(return_value=nonpublic))
    provider = SimpleNamespace(metadata={"mode": "api", "model": "test-base"}, langchain_model=lambda: object())
    agent = KnowledgeAgent(store=storage, provider=provider)
    model = AsyncMock(return_value={"messages": [
        ToolMessage(content=json.dumps({"tool": "search_project_documents", "evidence": [{"evidence_id": "e1"}]}),
                    tool_call_id="query-1"),
        AIMessage(content="历史停车棚的 PVDF 1050 资料 [e1]",
                  usage_metadata={"input_tokens": 3, "output_tokens": 2, "total_tokens": 5}),
    ]})
    monkeypatch.setattr("src.agents.knowledge_agent.create_agent", lambda **_kwargs: SimpleNamespace(ainvoke=model))
    query = "找历史停车棚 PVDF 1050 资料"
    args = (Principal("u", "n", "t", "admin"), "p", "s", query, [])
    if nonpublic:
        with pytest.raises(AgentProtocolError, match="非公开"):
            await agent._invoke_api(*args, role="retrieval")
        assert not task_provider.calls and model.await_count == 0
    else:
        result = await agent._invoke_api(*args, role="retrieval")
        content = model.call_args.args[0]["messages"][0]["content"]
        assert query in content and "规范检索表达：查询历史停车棚 PVDF 1050" in content
        assert result["usage"]["normalization"]["status"] == "accepted_with_original"
        assert result["usage"]["model_usage"] == {"input_tokens": 15, "output_tokens": 10}


@pytest.mark.asyncio
async def test_review_service_wires_organizer_without_changing_structured_findings(monkeypatch):
    monkeypatch.setattr(get_settings(), "LORA_TASKS_ENABLED", True)
    provider = TaskProvider("issue-1：实际3500，要求4000，需人工复核 [ev-1]。")
    monkeypatch.setattr("src.application.model_tasks.get_task_model_provider", lambda _task: provider)
    result, evidence = review_fixture()
    service = PackageReviewService()
    monkeypatch.setattr(service, "compose", lambda *_args, **_kwargs: copy.deepcopy(result))
    organized = await service.compose_and_organize([], [], evidence=evidence)
    assert organized["issues"] == result["issues"] and organized["status"] == result["status"]
    assert "辅助审查说明" in organized["report"]
    assert json.loads(provider.calls[0][1])["source_evidence"][0]["evidence_id"] == "ev-1"
