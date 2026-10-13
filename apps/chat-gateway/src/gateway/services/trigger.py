"""질문 트리거 판정 (docs/TDD.md §7.1.1 step6) — 순수 함수.

- 비활성/미등록 채널: 트리거 없음 (일반 채팅으로만 게시)
- DEDICATED_CHANNEL: 모든 메시지가 질문
- TRIGGER_WORD: trigger_word 로 시작하는 메시지만 (접두어 제거).
  단, 이미 Bot 이 답한 thread 의 답글은 trigger 없이도 후속 질문으로 본다.
- LLM 직접 대화 (FR-CHAT-014): binding.direct_llm_enabled 이면 `/` 로 시작하는 질문은 RAG(검색) 없이
  LLM 에 직접 보낸다(`/` 제거). TRIGGER_WORD 채널에서도 `/` 자체가 명시적 호출이라 trigger word 없이 답한다.
  꺼진 채널에서는 `/` 가 질문에 남은 채 기존 RAG 질문으로 처리된다.
- Bot/System 사용자의 Post 는 절대 트리거하지 않는다 (loop guard, FR-WEB-007).
"""

from __future__ import annotations

from dataclasses import dataclass

from rag_schemas import ChannelBinding, ChannelMode, ConversationMode

from gateway.repos import BOT_ROOT_SELF

DIRECT_PREFIX = "/"


@dataclass(frozen=True, slots=True)
class Trigger:
    question: str  # trigger word 제거된 질문
    bot_root_id: str | None  # Bot 답변이 달릴 thread root (BOT_ROOT_SELF = 질문 자신)
    direct: bool = False  # `/` 접두어 — RAG 없이 LLM 직접 대화


def resolve_trigger(
    binding: ChannelBinding | None,
    message: str,
    *,
    root_id: str | None,
    author_is_bot: bool,
    default_trigger_word: str,
    thread_has_bot: bool = False,
) -> Trigger | None:
    if author_is_bot or binding is None or not binding.enabled:
        return None

    text = message.strip()
    direct_on = binding.direct_llm_enabled
    if binding.mode == ChannelMode.TRIGGER_WORD:
        trigger = binding.trigger_word or default_trigger_word
        if text.startswith(trigger):
            text = text[len(trigger) :].strip()
        elif not ((root_id and thread_has_bot) or (direct_on and text.startswith(DIRECT_PREFIX))):
            return None
    direct = direct_on and text.startswith(DIRECT_PREFIX)
    if direct:
        text = text[len(DIRECT_PREFIX) :].strip()
    if not text:
        return None

    if root_id:  # thread 안의 질문 → 같은 thread 에 답변
        bot_root: str | None = root_id
    elif binding.conversation_mode == ConversationMode.THREAD:
        bot_root = BOT_ROOT_SELF  # 질문을 root 로 thread 를 연다 (thread 단위 컨텍스트)
    else:
        bot_root = None  # 채널 본문에 답변
    return Trigger(question=text, bot_root_id=bot_root, direct=direct)
