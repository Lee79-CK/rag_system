"""OpenAI-compatible mock LLM (:8010). `/v1/chat/completions` 고정/에코 응답 (§5.4).

실 GPU(vLLM) 환경으로 교체 시 VLLM_API_URL만 바꾸면 된다.
"""

from __future__ import annotations

import time

import uvicorn
from fastapi import FastAPI
from fastapi.responses import ORJSONResponse
from pydantic import BaseModel

app = FastAPI(title="mock-llm", default_response_class=ORJSONResponse)


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatCompletionRequest(BaseModel):
    model: str
    messages: list[ChatMessage]
    max_tokens: int | None = None
    temperature: float | None = None


def _mock_answer(messages: list[ChatMessage]) -> str:
    """근거 문서가 프롬프트에 있으면 [1] 인용을 포함한 고정 한국어 답변을 만든다."""
    user = next((m.content for m in reversed(messages) if m.role == "user"), "")
    has_evidence = "[근거 문서]" in user
    cite = " [1]" if has_evidence else ""
    return f"(mock) 요청하신 내용에 대한 답변입니다.{cite} 실제 배포에서는 vLLM이 생성합니다."


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.post("/v1/chat/completions")
async def chat_completions(body: ChatCompletionRequest) -> dict:
    answer = _mock_answer(body.messages)
    prompt_tokens = sum(len(m.content) for m in body.messages) // 3
    completion_tokens = max(1, len(answer) // 3)
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
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    }


def main() -> None:
    uvicorn.run(app, host="0.0.0.0", port=8010)


if __name__ == "__main__":
    main()
