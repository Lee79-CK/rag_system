"""Mattermost 게시 어댑터 (§7.1.2, §7.2.5).

Incoming Webhook URL은 secret_ref → 파일 mount에서만 로딩한다 (§11 #2).
URL/token은 로그·반환에 남기지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from mattermost_adapter import build_feedback_attachment, deliver, render_answer
from mattermost_adapter.delivery import DeliveryResult
from rag_schemas import ChannelBinding, ChatRequest, IncomingWebhookMessage, RagCompletion


@dataclass(slots=True)
class DeliveryDeps:
    secret_dir: str
    signing_key: bytes
    action_url: str
    bot_username: str = "RAG Assistant"
    max_post_chars: int = 12000


class MattermostDelivery:
    def __init__(self, deps: DeliveryDeps) -> None:
        self._d = deps

    def _webhook_url(self, secret_ref: str) -> str:
        # secret_ref 이름의 파일에서 URL을 읽는다. 로그에는 ref 이름만 남긴다.
        path = Path(self._d.secret_dir) / secret_ref
        return path.read_text(encoding="utf-8").strip()

    async def deliver_answer(
        self,
        *,
        binding: ChannelBinding,
        request: ChatRequest,
        completion: RagCompletion,
        chat_job_id: str,
    ) -> DeliveryResult:
        text = render_answer(request.user_name, completion, mention=binding.mention_user)
        attachments: list[dict] = []
        # 정상 답변·근거부족 안내 모두 피드백 버튼 포함 (§7.2.5 MUST). 오류 Post는 제외.
        if binding.feedback_enabled and completion.message_id:
            attachments.append(
                build_feedback_attachment(
                    completion.message_id, chat_job_id, self._d.signing_key, self._d.action_url
                )
            )
        message = IncomingWebhookMessage(
            channel=request.channel_name,
            username=self._d.bot_username,
            text=text,
            attachments=attachments,
        )
        return await deliver(
            self._webhook_url(binding.incoming_webhook_secret_ref),
            message,
            secret_ref=binding.incoming_webhook_secret_ref,
        )

    async def deliver_error(
        self, *, binding: ChannelBinding, request: ChatRequest, text: str
    ) -> DeliveryResult:
        # 오류 Post에는 피드백 버튼을 포함하지 않는다 (§7.2.5 MUST).
        message = IncomingWebhookMessage(
            channel=request.channel_name, username=self._d.bot_username, text=text
        )
        return await deliver(
            self._webhook_url(binding.incoming_webhook_secret_ref),
            message,
            secret_ref=binding.incoming_webhook_secret_ref,
        )
