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
        enable_thinking: bool | None = False,
    ):
        self._client = AsyncOpenAI(base_url=base_url, api_key=api_key, timeout=timeout)
        self._model = model
        # vLLM OpenAI 서버는 extra_body.chat_template_kwargs 를 chat template 에 전달한다.
        # None 이면 전송하지 않음(모델 기본값). thinking 이 켜진 경우에도 vLLM `--reasoning-parser` 가
        # 추론 텍스트를 reasoning_content 로 분리하므로 본문(content)에는 답변만 담긴다.
        self._extra_body: dict | None = (
            None
            if enable_thinking is None
            else {"chat_template_kwargs": {"enable_thinking": enable_thinking}}
        )

    async def complete(
        self, messages: list[dict[str, str]], *, max_tokens: int, temperature: float
    ) -> LLMResult:
        resp = await self._client.chat.completions.create(
            model=self._model,
            messages=messages,  # type: ignore[arg-type]
            max_tokens=max_tokens,
            temperature=temperature,
            extra_body=self._extra_body,
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
            extra_body=self._extra_body,
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
