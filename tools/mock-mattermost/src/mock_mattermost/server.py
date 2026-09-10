"""Mattermost Incoming Webhook 수신 mock (:9099).

- `POST /hooks/{hook_id}` : Mattermost 와 동일하게 본문 `ok` 를 200 으로 반환하고 payload 를 메모리에 보관 + 로그 출력
- `GET  /posts?hook_id=`  : 최근 수신 payload 조회 (text / attachments / actions 확인용)
- `DELETE /posts`         : 초기화
- `/health/live|ready|startup` : K8s probe (chart appServices 규약)

bridge/rag-worker 의 `deliver()` 가 Incoming Webhook URL 로 실제 POST 하는 경로를 end-to-end 로 확인하기 위한 도구다.
Secret 파일 `mattermost-incoming-<channel>` 의 URL 을 `http://mock-mattermost.rag-app:9099/hooks/<any>` 로 두면 된다.
"""

from __future__ import annotations

import json
import sys
import time
from collections import deque
from typing import Any

import uvicorn
from fastapi import FastAPI, Query, Request, Response
from fastapi.responses import ORJSONResponse

MAX_POSTS = 200

app = FastAPI(title="mock-mattermost", default_response_class=ORJSONResponse)
_posts: deque[dict[str, Any]] = deque(maxlen=MAX_POSTS)


def _log(record: dict[str, Any]) -> None:
    print(json.dumps(record, ensure_ascii=False), file=sys.stdout, flush=True)


@app.get("/health/live")
@app.get("/health/ready")
@app.get("/health/startup")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/hooks/{hook_id}")
async def incoming(hook_id: str, request: Request) -> Response:
    raw = await request.body()
    try:
        payload: Any = json.loads(raw) if raw else {}
    except ValueError:
        payload = {"_raw": raw.decode("utf-8", errors="replace")}
    record = {
        "event": "mock_mattermost.post_received",
        "hook_id": hook_id,
        "received_at": time.time(),
        "channel": payload.get("channel") if isinstance(payload, dict) else None,
        "username": payload.get("username") if isinstance(payload, dict) else None,
        "text": payload.get("text") if isinstance(payload, dict) else None,
        "attachments": payload.get("attachments") if isinstance(payload, dict) else None,
    }
    _posts.append({**record, "payload": payload})
    _log(record)
    # Mattermost Incoming Webhook 은 성공 시 text/plain "ok"
    return Response(content="ok", media_type="text/plain", status_code=200)


@app.get("/posts")
async def list_posts(hook_id: str | None = Query(default=None), limit: int = 20) -> dict[str, Any]:
    items = [p for p in reversed(_posts) if hook_id is None or p["hook_id"] == hook_id][:limit]
    return {"count": len(items), "posts": items}


@app.delete("/posts")
async def clear_posts() -> dict[str, str]:
    _posts.clear()
    return {"status": "cleared"}


def main() -> None:
    uvicorn.run(app, host="0.0.0.0", port=9099)


if __name__ == "__main__":
    main()
