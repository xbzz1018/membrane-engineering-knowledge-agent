from __future__ import annotations

import asyncio
import hashlib
import time
from typing import Any

import httpx

from src.core.config import Settings, get_settings


class ProviderConfigurationError(RuntimeError):
    """Raised when API mode has no complete provider configuration."""


class ProviderRequestError(RuntimeError):
    """Raised for a failed remote model request without exposing credentials."""


class ModelProvider:
    """OpenAI-compatible adapter with an explicit, isolated Fake mode."""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.provider = self._select_provider()
        self.model = self._chat_model()

    def _select_provider(self) -> str:
        mode = self.settings.MODEL_MODE.lower()
        requested = self.settings.MODEL_PROVIDER.lower()
        if mode == "fake":
            return "fake"
        if mode != "api":
            raise ProviderConfigurationError("MODEL_MODE must be 'fake' or 'api'")
        if requested == "fake":
            raise ProviderConfigurationError("MODEL_PROVIDER=fake is not allowed when MODEL_MODE=api")

        configured = {
            "deepseek": bool(self.settings.DEEPSEEK_API_KEY),
            "gateway": bool(self.settings.GATEWAY_API_KEY and self.settings.GATEWAY_API_BASE),
            "dashscope": bool(self.settings.DASHSCOPE_API_KEY),
        }
        if requested == "auto":
            for candidate in ("deepseek", "gateway", "dashscope"):
                if configured[candidate]:
                    return candidate
            raise ProviderConfigurationError("MODEL_MODE=api requires a configured chat provider")
        if requested not in configured:
            raise ProviderConfigurationError(f"Unsupported MODEL_PROVIDER: {requested}")
        if not configured[requested]:
            raise ProviderConfigurationError(f"Incomplete configuration for provider: {requested}")
        return requested

    def _chat_model(self) -> str:
        if self.provider == "deepseek":
            return self.settings.DEEPSEEK_MODEL or self.settings.CHAT_MODEL
        if self.provider == "gateway":
            return self.settings.GATEWAY_MODEL or self.settings.CHAT_MODEL
        if self.provider == "dashscope":
            return self.settings.DASHSCOPE_MODEL or self.settings.CHAT_MODEL
        return "deterministic"

    @property
    def metadata(self) -> dict[str, Any]:
        return {"provider": self.provider, "model": self.model, "mode": self.settings.MODEL_MODE}

    def langchain_model(
        self,
        *,
        json_mode: bool = False,
        enable_thinking: bool | None = None,
    ):
        """Build the configured LangChain chat model."""
        if self.provider == "fake":
            raise RuntimeError("Fake mode does not provide a network chat model")
        from langchain_openai import ChatOpenAI

        options: dict[str, Any] = {}
        if json_mode:
            options["model_kwargs"] = {"response_format": {"type": "json_object"}}
        if enable_thinking is not None:
            options["extra_body"] = {"enable_thinking": enable_thinking}
        return ChatOpenAI(
            model=self.model,
            api_key=self._api_key(),
            base_url=self._base_url(),
            temperature=self.settings.MODEL_TEMPERATURE,
            max_tokens=self.settings.MODEL_MAX_TOKENS,
            timeout=self.settings.MODEL_TIMEOUT_SECONDS,
            **options,
        )

    def _base_url(self) -> str:
        if self.provider == "dashscope":
            return self.settings.DASHSCOPE_API_BASE.rstrip("/")
        if self.provider == "deepseek":
            return self.settings.DEEPSEEK_API_BASE.rstrip("/")
        if self.provider == "gateway":
            return self.settings.GATEWAY_API_BASE.rstrip("/")
        raise ProviderConfigurationError("Fake mode has no remote base URL")

    def _api_key(self) -> str:
        if self.provider == "dashscope":
            return self.settings.DASHSCOPE_API_KEY
        if self.provider == "deepseek":
            return self.settings.DEEPSEEK_API_KEY
        if self.provider == "gateway":
            return self.settings.GATEWAY_API_KEY
        raise ProviderConfigurationError("Fake mode has no API key")

    def _embedding_config(self) -> tuple[str, str, str, str]:
        if self.settings.MODEL_MODE.lower() == "fake":
            return "fake", "", "", self.settings.EMBEDDING_MODEL
        requested = self.settings.EMBEDDING_PROVIDER.lower()
        if requested in {"local", "custom", "openai"}:
            requested = "embedding"
        options = {
            "embedding": (
                self.settings.EMBEDDING_API_BASE,
                self.settings.EMBEDDING_API_KEY,
                self.settings.EMBEDDING_MODEL,
            ),
            "gateway": (
                self.settings.GATEWAY_API_BASE,
                self.settings.GATEWAY_API_KEY,
                self.settings.GATEWAY_EMBEDDING_MODEL or self.settings.EMBEDDING_MODEL,
            ),
            "dashscope": (
                self.settings.DASHSCOPE_API_BASE,
                self.settings.DASHSCOPE_API_KEY,
                self.settings.EMBEDDING_MODEL,
            ),
        }
        if requested == "fake":
            raise ProviderConfigurationError("EMBEDDING_PROVIDER=fake is not allowed when MODEL_MODE=api")
        candidates = ("embedding", "gateway", "dashscope") if requested == "auto" else (requested,)
        for candidate in candidates:
            if candidate not in options:
                raise ProviderConfigurationError(f"Unsupported EMBEDDING_PROVIDER: {candidate}")
            base_url, api_key, model = options[candidate]
            if base_url and api_key and model:
                return candidate, base_url.rstrip("/"), api_key, model
        raise ProviderConfigurationError("MODEL_MODE=api requires a configured embedding provider")

    @property
    def embedding_model(self) -> str:
        """Configured embedding model name without exposing endpoint credentials."""
        return self._embedding_config()[3]

    async def chat(self, system: str, user: str, json_mode: bool = False) -> tuple[str, dict[str, Any]]:
        if self.provider == "fake":
            return self._fake_answer(user), {"provider": "fake", "model": "deterministic"}
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": self.settings.MODEL_TEMPERATURE,
            "max_tokens": self.settings.MODEL_MAX_TOKENS,
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        headers = {"Authorization": f"Bearer {self._api_key()}", "Content-Type": "application/json"}
        last_error: Exception | None = None
        for attempt in range(self.settings.MODEL_RETRY_ATTEMPTS):
            try:
                async with httpx.AsyncClient(timeout=self.settings.MODEL_TIMEOUT_SECONDS) as client:
                    response = await client.post(f"{self._base_url()}/chat/completions", headers=headers, json=body)
                    response.raise_for_status()
                    payload = response.json()
                content = payload["choices"][0]["message"].get("content", "")
                if not isinstance(content, str) or not content.strip():
                    raise ValueError("empty model content")
                choice = payload["choices"][0]
                usage = payload.get("usage", {})
                return content, {
                    "provider": self.provider,
                    "model": self.model,
                    "usage": usage,
                    "input_tokens": int(usage.get("prompt_tokens", usage.get("input_tokens", 0)) or 0),
                    "output_tokens": int(usage.get("completion_tokens", usage.get("output_tokens", 0)) or 0),
                    "finish_reason": str(choice.get("finish_reason", "")),
                    "attempts": attempt + 1,
                }
            except Exception as exc:
                last_error = exc
                if attempt + 1 < self.settings.MODEL_RETRY_ATTEMPTS:
                    await asyncio.sleep(self.settings.MODEL_RETRY_BACKOFF_SECONDS * (2 ** attempt))
        raise ProviderRequestError(
            f"{self.provider} chat request failed ({type(last_error).__name__})"
        ) from last_error

    async def embed(self, text: str) -> list[float]:
        provider, base_url, api_key, model = self._embedding_config()
        if provider == "fake":
            return self._fake_embedding(text)
        body: dict[str, Any] = {"model": model, "input": [text]}
        body["dimensions"] = self.settings.EMBEDDING_DIMENSIONS
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        last_error: Exception | None = None
        for attempt in range(self.settings.MODEL_RETRY_ATTEMPTS):
            try:
                async with httpx.AsyncClient(timeout=self.settings.MODEL_TIMEOUT_SECONDS) as client:
                    response = await client.post(f"{base_url}/embeddings", headers=headers, json=body)
                    response.raise_for_status()
                    vector = response.json()["data"][0]["embedding"]
                if not isinstance(vector, list) or not vector:
                    raise ValueError("empty embedding vector")
                return vector
            except Exception as exc:
                last_error = exc
                if attempt + 1 < self.settings.MODEL_RETRY_ATTEMPTS:
                    await asyncio.sleep(self.settings.MODEL_RETRY_BACKOFF_SECONDS * (2 ** attempt))
        raise ProviderRequestError(
            f"{provider} embedding request failed ({type(last_error).__name__})"
        ) from last_error

    async def rerank(self, query: str, candidates: list[dict[str, Any]], top_n: int | None = None) -> list[dict[str, Any]]:
        if not candidates:
            return []
        if not self.settings.RERANKER_ENABLED:
            return candidates[: top_n or self.settings.RERANKER_TOP_N]
        if not self.settings.RERANKER_API_BASE or not self.settings.RERANKER_API_KEY:
            raise ProviderConfigurationError("Reranker is enabled but its API configuration is incomplete")
        documents = [str(item.get("text") or item.get("excerpt") or item)[:12000] for item in candidates]
        body = {
            "model": self.settings.RERANKER_MODEL,
            "query": query,
            "documents": documents,
            "top_n": min(top_n or self.settings.RERANKER_TOP_N, len(documents)),
            "return_documents": False,
            "instruct": self.settings.RERANKER_INSTRUCT,
        }
        headers = {
            "Authorization": f"Bearer {self.settings.RERANKER_API_KEY}",
            "Content-Type": "application/json",
        }
        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=self.settings.MODEL_TIMEOUT_SECONDS) as client:
                response = await client.post(self.settings.RERANKER_API_BASE, headers=headers, json=body)
                response.raise_for_status()
                payload = response.json()
        except Exception as exc:
            raise ProviderRequestError(f"reranker request failed ({type(exc).__name__})") from exc
        results = payload.get("results") or payload.get("output", {}).get("results") or []
        reranked: list[dict[str, Any]] = []
        for rank, result in enumerate(results, 1):
            index = int(result["index"])
            if index < 0 or index >= len(candidates):
                continue
            item = dict(candidates[index])
            item["rerank"] = {
                "provider": self.settings.RERANKER_PROVIDER,
                "model": self.settings.RERANKER_MODEL,
                "rank": rank,
                "score": float(result.get("relevance_score", 0)),
                "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            }
            reranked.append(item)
        if not reranked:
            raise ProviderRequestError("reranker returned no valid candidates")
        return reranked

    async def discover_workspace_models(self) -> list[dict[str, Any]]:
        if not self.settings.EMBEDDING_API_BASE or not self.settings.EMBEDDING_API_KEY:
            raise ProviderConfigurationError("Alibaba workspace model discovery is not configured")
        suffix = "/compatible-mode/v1"
        base = self.settings.EMBEDDING_API_BASE.rstrip("/")
        workspace_root = base[:-len(suffix)] if base.endswith(suffix) else base
        headers = {"Authorization": f"Bearer {self.settings.EMBEDDING_API_KEY}"}
        try:
            async with httpx.AsyncClient(timeout=self.settings.MODEL_TIMEOUT_SECONDS) as client:
                response = await client.get(f"{workspace_root}/api/v1/models", headers=headers)
                response.raise_for_status()
                payload = response.json()
        except Exception as exc:
            raise ProviderRequestError(f"workspace model discovery failed ({type(exc).__name__})") from exc
        rows = payload.get("data") or payload.get("models") or payload.get("output", {}).get("models") or []
        return [
            {
                "model": str(row.get("model") or row.get("id") or row.get("model_code") or ""),
                "name": str(row.get("name") or row.get("model") or row.get("id") or ""),
                "capabilities": [str(item) for item in row.get("capabilities", [])],
            }
            for row in rows
            if isinstance(row, dict) and (row.get("model") or row.get("id") or row.get("model_code"))
        ]

    async def health(self) -> dict[str, Any]:
        if self.provider == "fake":
            return {"enabled": True, "healthy": True, "detail": "deterministic fake mode"}
        try:
            headers = {"Authorization": f"Bearer {self._api_key()}"}
            async with httpx.AsyncClient(timeout=self.settings.HEALTHCHECK_TIMEOUT_SECONDS) as client:
                response = await client.get(f"{self._base_url()}/models", headers=headers)
                response.raise_for_status()
            return {"enabled": True, "healthy": True, "detail": self.provider}
        except Exception as exc:
            return {"enabled": True, "healthy": False, "detail": type(exc).__name__}

    def _fake_embedding(self, text: str) -> list[float]:
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        dimensions = self.settings.EMBEDDING_DIMENSIONS
        return [((digest[index % len(digest)] / 255.0) * 2) - 1 for index in range(dimensions)]

    @staticmethod
    def _fake_answer(user: str) -> str:
        if "价格" in user or "报价" in user:
            return "已按材料、规格和资料日期检索价格记录。结果仅作为历史参考，缺少来源或日期的记录不会作为正式报价。"
        if "规格" in user or "膜材" in user:
            return "已检索膜材规格资料。请结合结构形式、使用环境和原文证据进行确认。"
        if "方案" in user or "案例" in user or "设计" in user:
            return "已检索相似工程方案和案例，并按结构形式、应用场景与膜材整理结果。"
        return "已完成工程资料检索。请根据返回的来源和不确定性确认最终工程结论。"


def get_model_provider() -> ModelProvider:
    return ModelProvider()


def get_role_model_provider(role: str, settings: Settings | None = None) -> ModelProvider:
    settings = settings or get_settings()
    if role not in {"supervisor", "review", "retrieval", "material"}:
        raise ProviderConfigurationError("Unknown Agent model role")
    if settings.ROLE_MODEL_ROUTING_ENABLED and settings.MODEL_MODE.lower() == "api":
        prefix = "STRONG" if role in {"supervisor", "review"} else "LIGHT"
        base, key, model = (getattr(settings, name) for name in (
            f"{prefix}_MODEL_API_BASE", f"{prefix}_MODEL_API_KEY", f"{prefix}_MODEL",
        ))
        if not all((base, key, model)):
            raise ProviderConfigurationError(f"Incomplete {prefix} model route for {role}")
        return ModelProvider(settings.model_copy(update={
            "MODEL_PROVIDER": "gateway", "GATEWAY_API_BASE": base,
            "GATEWAY_API_KEY": key, "GATEWAY_MODEL": model,
            "MODEL_MAX_TOKENS": settings.REVIEW_MAX_TOKENS,
        }))
    if not settings.REVIEW_API_BASE or not settings.REVIEW_API_KEY:
        return ModelProvider(settings)
    review_settings = settings.model_copy(update={
        "MODEL_PROVIDER": "dashscope",
        "DASHSCOPE_API_BASE": settings.REVIEW_API_BASE,
        "DASHSCOPE_API_KEY": settings.REVIEW_API_KEY,
        "DASHSCOPE_MODEL": settings.REVIEW_MODEL,
        "MODEL_MAX_TOKENS": settings.REVIEW_MAX_TOKENS,
    })
    return ModelProvider(review_settings)


def get_review_model_provider() -> ModelProvider:
    return get_role_model_provider("supervisor")
