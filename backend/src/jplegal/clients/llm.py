"""LLM qua LiteLLM – 1 interface cho vLLM/Ollama on-prem, OpenAI, Anthropic, OpenRouter, ...

Đổi model chỉ bằng biến môi trường:
    LLM_MODEL=openai/Qwen/Qwen3-32B   LLM_API_BASE=http://vllm:8000/v1   LLM_API_KEY=dummy   (vLLM on-prem)
    LLM_MODEL=ollama_chat/qwen3:14b   LLM_API_BASE=http://ollama:11434                         (Ollama)
    LLM_MODEL=openrouter/deepseek/deepseek-chat  LLM_API_KEY=sk-or-...                          (cloud)
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from jplegal.core.config import Settings


class LLMClient:
    def __init__(self, settings: Settings):
        self.s = settings

    @property
    def enabled(self) -> bool:
        return bool(self.s.llm_model)

    def _kwargs(self) -> dict:
        kw: dict = {
            "model": self.s.llm_model,
            "temperature": self.s.llm_temperature,
            "max_tokens": self.s.llm_max_tokens,
            "timeout": self.s.llm_timeout,
            "num_retries": 2,
        }
        if self.s.llm_api_base:
            kw["api_base"] = self.s.llm_api_base
        if self.s.llm_api_key:
            kw["api_key"] = self.s.llm_api_key
        return kw

    async def stream(self, messages: list[dict]) -> AsyncIterator[str]:
        import litellm

        resp = await litellm.acompletion(messages=messages, stream=True, **self._kwargs())
        async for part in resp:
            delta = part.choices[0].delta.content if part.choices else None
            if delta:
                yield delta

    async def complete(self, messages: list[dict]) -> str:
        import litellm

        resp = await litellm.acompletion(messages=messages, **self._kwargs())
        return resp.choices[0].message.content or ""
