"""真实模型5/20文档多智能体审查、Groundedness与性能评测。"""

from __future__ import annotations

import asyncio
import json
import statistics
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.agents.review_agents import PackageReviewService
from src.core.config import get_settings
from src.documents.parsing import parse_document
from src.domain.schemas import PackageReviewRequest
from src.infrastructure.database import storage
from src.infrastructure.model_provider import ModelProvider
from src.main import app

RESULT = Path("data/eval/results/real_package_benchmark_v3.json")
RUN_DETAILS = Path("data/eval/results/real_package_benchmark_v3.runs.json")


def document_content(profile: str, index: int, paragraphs: int) -> str:
    thickness = "0.7" if index % 2 else "0.8"
    version = f"V{(index % 4) + 1}"
    lines = [
        f"资料编号 {profile}-{index:02d}。设计方案为交通雨棚，膜材型号PTFE-{index:02d}，"
        f"膜材厚度{thickness}毫米，设计版本{version}，日期2025-{(index % 9) + 1:02d}。"
        f"synthetic历史价格为{260 + index}至{300 + index}元/平方米，仅作评测，不是正式报价。"
    ]
    for number in range(paragraphs):
        lines.append(
            f"第{number + 1}段设计与膜材审查说明：项目场景、结构节点、膜材型号、规格单位、厚度、"
            f"版本日期和synthetic价格口径均以资料编号{profile}-{index:02d}为准；"
            "本段用于验证长文档Map-Reduce和Evidence覆盖，不构成工程安全结论。"
        )
    return "\n".join(lines)


async def ensure_profile_documents(profile: str, count: int, paragraphs: int, version_base: int) -> list[str]:
    settings = get_settings()
    document_ids = []
    for index in range(1, count + 1):
        content = document_content(profile, index, paragraphs)
        document = await storage.add_document(
            f"真实评测-{profile}-{index:02d}.txt",
            "text/plain",
            content.encode(),
            "pending",
            tenant_id=settings.DEFAULT_TENANT_ID,
            project_id=settings.DEFAULT_PROJECT_ID,
            data_classification="public",
            parse_method="text",
            version=version_base + index,
        )
        document_ids.append(document["id"])
        if document["status"] == "indexed" and await storage.count_document_chunks(document["id"]):
            continue
        if not await storage.acquire_document_ingest(document["id"]):
            raise RuntimeError(f"无法取得评测资料索引处理权: {document['id']}")
        local_path = await storage.resolve_document_path(document)
        chunks, parser = await parse_document(str(local_path), "text")
        await storage.save_chunks(document["id"], chunks, parser)
    return document_ids


def deterministic_metrics(result: dict) -> dict:
    workers = result["worker_results"]
    findings = result.get("issues") or [
        finding for worker in workers.values() for finding in worker["findings"]
    ]
    cited = [finding for finding in findings if finding["evidence_ids"]]
    source_ids = {source["source_id"] for source in result["sources"]}
    valid = [
        finding
        for finding in cited
        if all(evidence_id in source_ids for evidence_id in finding["evidence_ids"])
    ]
    processed = set()
    skipped = set()
    for worker in workers.values():
        processed.update(worker["processed_evidence_ids"])
        skipped.update(worker["skipped_evidence_ids"])
    return {
        "issue_count": len(findings),
        "finding_count": len(findings),
        "citation_coverage": len(cited) / len(findings) if findings else 1.0,
        "valid_citation_rate": len(valid) / len(cited) if cited else 1.0,
        "evidence_status_count": len(processed | skipped),
        "conflict_detected": bool(result["conflicts"]),
    }


async def judge_groundedness(judge_provider: ModelProvider, result: dict) -> float:
    evidence = {source["source_id"]: source["excerpt"] for source in result["sources"]}
    claims = []
    issues = result.get("issues") or [
        finding
        for worker_name, worker in result["worker_results"].items()
        for finding in worker["findings"]
    ]
    for issue in issues:
        claims.append({
            "worker": issue.get("domain", "cross_domain"),
            "summary": issue.get("summary", ""),
            "evidence": [evidence.get(item, "") for item in issue.get("evidence_ids", [])],
        })
    answer, _ = await judge_provider.chat(
        "你是离线评测裁判。判断每条审查发现是否被随附证据直接支持，只输出JSON。",
        (
            f"待评测发现：{json.dumps(claims, ensure_ascii=False)}\n"
            "输出格式：{\"supported\":支持数量,\"total\":总数量,\"unsupported_indexes\":[]}"
        ),
        json_mode=True,
    )
    normalized = answer.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    payload = json.loads(normalized)
    total = int(payload.get("total", len(claims)))
    supported = int(payload.get("supported", 0))
    return supported / total if total else 1.0


def percentile(values: list[float], ratio: float) -> float:
    ordered = sorted(values)
    return ordered[max(0, int(len(ordered) * ratio) - 1)]


async def benchmark_profile(
    service: PackageReviewService,
    judge_provider: ModelProvider,
    profile: str,
    document_ids: list[str],
    repeats: int,
    run_cache: dict[str, list[dict]],
) -> dict:
    settings = get_settings()
    runs = list(run_cache.get(profile, []))
    request = PackageReviewRequest(
        project_id=settings.DEFAULT_PROJECT_ID,
        document_ids=document_ids,
        question="审查设计、膜材型号、厚度、版本、日期和synthetic价格冲突，并逐条引用证据。",
    )
    for _ in range(len(runs), repeats):
        started = time.perf_counter()
        retry_count = 0
        while True:
            try:
                result = await service.run(
                    request,
                    tenant_id=settings.DEFAULT_TENANT_ID,
                    user_id="benchmark-user",
                )
                break
            except Exception as exc:
                transient = any(
                    marker in type(exc).__name__
                    for marker in ("Timeout", "APIError", "InternalServer")
                )
                if retry_count >= 2 or not transient:
                    raise
                retry_count += 1
                await asyncio.sleep(2 ** retry_count)
        latency_ms = (time.perf_counter() - started) * 1000
        deterministic = deterministic_metrics(result)
        groundedness = await judge_groundedness(judge_provider, result)
        input_tokens = sum(int(item.get("input_tokens", 0)) for item in result["usage"].values())
        output_tokens = sum(int(item.get("output_tokens", 0)) for item in result["usage"].values())
        calls = sum(int(item.get("calls", 0)) for item in result["usage"].values())
        total_tokens = input_tokens + output_tokens
        runs.append({
            **deterministic,
            "groundedness": groundedness,
            "latency_ms": latency_ms,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "model_calls": calls,
            "retry_count": retry_count,
            "estimated_cost_micros": (
                ((total_tokens + 999) // 1000) * settings.MODEL_ESTIMATED_COST_MICROS_PER_1K_TOKENS
            ),
        })
        run_cache[profile] = runs
        RUN_DETAILS.parent.mkdir(parents=True, exist_ok=True)
        RUN_DETAILS.write_text(json.dumps(run_cache, ensure_ascii=False, indent=2), encoding="utf-8")
    latencies = [item["latency_ms"] for item in runs]
    return {
        "profile": profile,
        "document_count": len(document_ids),
        "runs": len(runs),
        "groundedness": round(statistics.mean(item["groundedness"] for item in runs), 4),
        "citation_coverage": round(statistics.mean(item["citation_coverage"] for item in runs), 4),
        "valid_citation_rate": round(statistics.mean(item["valid_citation_rate"] for item in runs), 4),
        "conflict_recall": round(sum(item["conflict_detected"] for item in runs) / len(runs), 4),
        "latency_ms": {
            "p50": round(statistics.median(latencies), 2),
            "p95": round(percentile(latencies, 0.95), 2),
        },
        "tokens": {
            "input_mean": round(statistics.mean(item["input_tokens"] for item in runs), 2),
            "output_mean": round(statistics.mean(item["output_tokens"] for item in runs), 2),
        },
        "model_calls_mean": round(statistics.mean(item["model_calls"] for item in runs), 2),
        "retry_count": sum(item.get("retry_count", 0) for item in runs),
        "estimated_cost_micros_mean": round(
            statistics.mean(item["estimated_cost_micros"] for item in runs),
            2,
        ),
        "evidence_status_min": min(item["evidence_status_count"] for item in runs),
    }


async def main() -> None:
    settings = get_settings()
    if settings.RUNTIME_MODE.lower() != "full" or settings.MODEL_MODE.lower() != "api":
        raise RuntimeError("真实资料包评测要求Full/API模式")
    async with app.router.lifespan_context(app):
        service = PackageReviewService()
        judge_settings = settings.model_copy(update={
            "MODEL_PROVIDER": "dashscope",
            "DASHSCOPE_API_BASE": settings.EMBEDDING_API_BASE,
            "DASHSCOPE_API_KEY": settings.EMBEDDING_API_KEY,
            "DASHSCOPE_MODEL": "qwen3.8-max",
        })
        judge_provider = ModelProvider(judge_settings)
        five_ids = await ensure_profile_documents("5-doc", 5, 2, 6000)
        twenty_ids = await ensure_profile_documents("20-doc", 20, 10, 7000)
        run_cache = json.loads(RUN_DETAILS.read_text(encoding="utf-8")) if RUN_DETAILS.exists() else {}
        five = await benchmark_profile(
            service,
            judge_provider,
            "5-doc",
            five_ids,
            repeats=3,
            run_cache=run_cache,
        )
        twenty = await benchmark_profile(
            service,
            judge_provider,
            "20-doc",
            twenty_ids,
            repeats=3,
            run_cache=run_cache,
        )
    summary = {
        "dataset": "real_package_benchmark_v3",
        "generated_at": datetime.now(UTC).isoformat(),
        "model_provider": service.provider.provider,
        "model": service.provider.model,
        "judge_provider": judge_provider.provider,
        "judge_model": judge_provider.model,
        "review_supervisor_enabled": settings.REVIEW_SUPERVISOR_ENABLED,
        "profiles": [five, twenty],
    }
    RESULT.parent.mkdir(parents=True, exist_ok=True)
    RESULT.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    for profile in summary["profiles"]:
        if profile["groundedness"] < 0.90 or profile["citation_coverage"] < 0.90:
            raise AssertionError(json.dumps(summary, ensure_ascii=False))
        if profile["valid_citation_rate"] != 1.0 or profile["conflict_recall"] < 0.80:
            raise AssertionError(json.dumps(summary, ensure_ascii=False))
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    asyncio.run(main())
