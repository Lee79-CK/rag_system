"""vLLM (OpenAI-compatible) 클라이언트 (LLMPort 구현) — ADR-006, §8.3."""

from __future__ import annotations

from collections.abc import AsyncIterator

from openai import AsyncOpenAI

from rag.domain.ports import LLMResult, LLMStreamEvent


class LLMClient:
    def __init__(
        self,
        base_url: str,
        model: str,
        *,
        api_key: str = "internal",
        timeout: float = 120.0,
    ):
        self._client = AsyncOpenAI(base_url=base_url, api_key=api_key, timeout=timeout)
        self._model = model

    async def complete(
        self, messages: list[dict[str, str]], *, max_tokens: int, temperature: float
    ) -> LLMResult:
        resp = await self._client.chat.completions.create(
            model=self._model,
            messages=messages,  # type: ignore[arg-type]
            max_tokens=max_tokens,
            temperature=temperature,
        )
        text = resp.choices[0].message.content or ""
        usage: dict = {}
        if resp.usage is not None:
            usage = {
                "prompt_tokens": resp.usage.prompt_tokens,
                "completion_tokens": resp.usage.completion_tokens,
            }
        return LLMResult(text=text, usage=usage)

    async def stream(
        self, messages: list[dict[str, str]], *, max_tokens: int, temperature: float
    ) -> AsyncIterator[LLMStreamEvent]:
        """SSE 스트리밍 (vLLM `stream=True`). 마지막 chunk 의 usage 를 별도 이벤트로 낸다."""
        resp = await self._client.chat.completions.create(  # type: ignore[call-overload]
            model=self._model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            stream=True,
            stream_options={"include_usage": True},
        )
        async for chunk in resp:
            if chunk.choices:
                delta = chunk.choices[0].delta.content
                if delta:
                    yield LLMStreamEvent(delta=delta)
            if chunk.usage is not None:
                yield LLMStreamEvent(
                    usage={
                        "prompt_tokens": chunk.usage.prompt_tokens,
                        "completion_tokens": chunk.usage.completion_tokens,
                    }
                )
