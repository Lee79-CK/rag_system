"""OpenAI-compatible mock LLM (:8010). `/v1/chat/completions` 고정/에코 응답 (§5.4).

`stream: true` 이면 OpenAI SSE 형식(chunk delta → usage chunk → `[DONE]`)으로 흘려보낸다.
실 GPU(vLLM) 환경으로 교체 시 VLLM_API_URL만 바꾸면 된다.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from collections.abc import AsyncIterator

import uvicorn
from fastapi import FastAPI
from fastapi.responses import ORJSONResponse, StreamingResponse
from pydantic import BaseModel

# 토큰 간 지연(ms) — 스트리밍 UI 확인용. 0 이면 지연 없음.
STREAM_DELAY_MS = int(os.environ.get("MOCK_LLM_STREAM_DELAY_MS", "30"))

app = FastAPI(title="mock-llm", default_response_class=ORJSONResponse)


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatCompletionRequest(BaseModel):
    model: str
    messages: list[ChatMessage]
    max_tokens: int | None = None
    temperature: float | None = None
    stream: bool = False
    stream_options: dict | None = None
    # vLLM 확장 필드 — 실제 템플릿 적용은 하지 않고 수용만 한다 (enable_thinking 등)
    chat_template_kwargs: dict | None = None


def _mock_answer(messages: list[ChatMessage]) -> str:
    """근거 문서가 프롬프트에 있으면 [1] 인용을 포함한 고정 한국어 답변을 만든다."""
    user = next((m.content for m in reversed(messages) if m.role == "user"), "")
    has_evidence = "[근거 문서]" in user
    cite = " [1]" if has_evidence else ""
    return f"(mock) 요청하신 내용에 대한 답변입니다.{cite} 실제 배포에서는 vLLM이 생성합니다."


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


def _usage(body: ChatCompletionRequest, answer: str) -> dict:
    prompt_tokens = sum(len(m.content) for m in body.messages) // 3
    completion_tokens = max(1, len(answer) // 3)
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
    }


def _chunks(answer: str, size: int = 4) -> list[str]:
    return [answer[i : i + size] for i in range(0, len(answer), size)]


async def _sse(body: ChatCompletionRequest, answer: str) -> AsyncIterator[str]:
    base = {
        "id": "chatcmpl-mock",
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": body.model,
    }

    def frame(obj: dict) -> str:
        return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"

    yield frame(
        {**base, "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]}
    )
    for piece in _chunks(answer):
        if STREAM_DELAY_MS:
            await asyncio.sleep(STREAM_DELAY_MS / 1000)
        yield frame(
            {**base, "choices": [{"index": 0, "delta": {"content": piece}, "finish_reason": None}]}
        )
    yield frame({**base, "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]})
    if (body.stream_options or {}).get("include_usage"):
        yield frame({**base, "choices": [], "usage": _usage(body, answer)})
    yield "data: [DONE]\n\n"


@app.post("/v1/chat/completions", response_model=None)
async def chat_completions(body: ChatCompletionRequest) -> dict | StreamingResponse:
    answer = _mock_answer(body.messages)
    if body.stream:
        return StreamingResponse(_sse(body, answer), media_type="text/event-stream")
    return {
        "id": "chatcmpl-mock",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": body.model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": answer},
                "finish_reason": "stop",
            }
        ],
        "usage": _usage(body, answer),
    }


def main() -> None:
    uvicorn.run(app, host="0.0.0.0", port=8010)


if __name__ == "__main__":
    main()
