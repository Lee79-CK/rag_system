"""mock-llm 스트리밍 계약 — rag-api LLMClient.stream() 이 실제 openai SDK 로 소비 가능해야 한다."""

from __future__ import annotations

import httpx
from mock_llm import server
from openai import AsyncOpenAI
from rag.adapters.llm_client import LLMClient


async def test_stream_sse_consumed_by_llm_client(monkeypatch):
    monkeypatch.setattr(server, "STREAM_DELAY_MS", 0)
    transport = httpx.ASGITransport(app=server.app)
    client = LLMClient("http://mock/v1", "internal-rag-llm")
    client._client = AsyncOpenAI(
        base_url="http://mock/v1", api_key="x", http_client=httpx.AsyncClient(transport=transport)
    )
    messages = [{"role": "user", "content": "[근거 문서]\n[1] ...\n질문"}]
    deltas, usage = [], None
    async for ev in client.stream(messages, max_tokens=64, temperature=0.0):
        if ev.delta:
            deltas.append(ev.delta)
        if ev.usage:
            usage = ev.usage
    text = "".join(deltas)
    assert len(deltas) > 1 and "[1]" in text
    assert usage and usage["completion_tokens"] > 0
    full = await client.complete(messages, max_tokens=64, temperature=0.0)
    assert full.text == text


async def test_llm_client_sends_enable_thinking_kwarg():
    """thinking 모델(Qwen3.8 등)에서 RAG 는 추론을 끈다 — vLLM chat_template_kwargs 로 전달돼야 한다."""
    import json

    seen: list[dict] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return await httpx.ASGITransport(app=server.app).handle_async_request(request)

    client = LLMClient("http://mock/v1", "internal-rag-llm", enable_thinking=False)
    client._client = AsyncOpenAI(
        base_url="http://mock/v1",
        api_key="x",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    await client.complete([{"role": "user", "content": "q"}], max_tokens=8, temperature=0.0)
    assert seen[-1]["chat_template_kwargs"] == {"enable_thinking": False}

    default = LLMClient("http://mock/v1", "internal-rag-llm", enable_thinking=None)
    default._client = AsyncOpenAI(
        base_url="http://mock/v1",
        api_key="x",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    await default.complete([{"role": "user", "content": "q"}], max_tokens=8, temperature=0.0)
    assert "chat_template_kwargs" not in seen[-1]  # None = 모델 기본값 유지 (필드 미전송)
