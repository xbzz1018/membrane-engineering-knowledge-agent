from __future__ import annotations

import hashlib
from typing import Any

import httpx

from src.core.config import get_settings


class ModelProvider:
    """Small OpenAI-compatible adapter with deterministic no-key fallback."""

    def __init__(self):
        self.settings = get_settings()
        self.provider = self._select_provider()
        self.model = self.settings.CHAT_MODEL

    def _select_provider(self) -> str:
        requested = self.settings.MODEL_PROVIDER.lower()
        if self.settings.MODEL_MODE.lower() == "fake" or requested == "fake":
            return "fake"
        if requested == "dashscope" or (requested == "auto" and self.settings.DASHSCOPE_API_KEY):
            return "dashscope"
        if requested == "deepseek" or (requested == "auto" and self.settings.DEEPSEEK_API_KEY):
            return "deepseek"
        if requested == "openai" or (requested == "auto" and self.settings.BASE_URL_CHAT):
            return "openai"
        return "fake"

    @property
    def metadata(self) -> dict[str, Any]:
        return {"provider": self.provider, "model": self.model, "mode": self.settings.MODEL_MODE}

    def langchain_model(self):
        """Build a LangChain model for the optional DeepAgents path."""
        if self.provider == "fake":
            raise RuntimeError("Fake mode does not provide a network chat model")
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=self.model,
            api_key=self._api_key(),
            base_url=self._base_url(),
            temperature=self.settings.MODEL_TEMPERATURE,
            max_tokens=self.settings.MODEL_MAX_TOKENS,
            timeout=self.settings.MODEL_TIMEOUT_SECONDS,
        )

    def _base_url(self) -> str:
        if self.provider == "dashscope":
            return self.settings.BASE_URL_CHAT or "https://dashscope.aliyuncs.com/compatible-mode/v1"
        if self.provider == "deepseek":
            return self.settings.BASE_URL_CHAT or "https://api.deepseek.com"
        return self.settings.BASE_URL_CHAT.rstrip("/")

    def _api_key(self) -> str:
        if self.provider == "dashscope":
            return self.settings.DASHSCOPE_API_KEY
        if self.provider == "deepseek":
            return self.settings.DEEPSEEK_API_KEY
        return self.settings.DASHSCOPE_API_KEY or self.settings.DEEPSEEK_API_KEY

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
        try:
            async with httpx.AsyncClient(timeout=self.settings.MODEL_TIMEOUT_SECONDS) as client:
                response = await client.post(f"{self._base_url()}/chat/completions", headers=headers, json=body)
                response.raise_for_status()
                payload = response.json()
            content = payload["choices"][0]["message"].get("content", "")
            return content, {"provider": self.provider, "model": self.model, "usage": payload.get("usage", {})}
        except Exception as exc:
            return self._fake_answer(user), {"provider": "fake-fallback", "error": str(exc)}

    async def embed(self, text: str) -> list[float]:
        if self.provider != "dashscope" or not self.settings.DASHSCOPE_API_KEY:
            return self._fake_embedding(text)
        body = {"model": self.settings.EMBEDDING_MODEL, "input": [text]}
        headers = {"Authorization": f"Bearer {self.settings.DASHSCOPE_API_KEY}", "Content-Type": "application/json"}
        try:
            async with httpx.AsyncClient(timeout=self.settings.MODEL_TIMEOUT_SECONDS) as client:
                response = await client.post(f"{self._base_url()}/embeddings", headers=headers, json=body)
                response.raise_for_status()
                return response.json()["data"][0]["embedding"]
        except Exception:
            return self._fake_embedding(text)

    @staticmethod
    def _fake_embedding(text: str) -> list[float]:
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        return [((byte / 255.0) * 2) - 1 for byte in digest]

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
