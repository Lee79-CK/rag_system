'use client';

import clsx from 'clsx';
import { useRouter } from 'next/navigation';
import { useRef, useState, type KeyboardEvent } from 'react';
import { ApiError } from '@/lib/api';
import { useCreatePost, type ChannelDetail } from '@/lib/query/hooks';
import { useUiStore } from '@/lib/stores/ui';

/**
 * 컴포저 — aiops_chatbot Composer 이식.
 * 변경: 슬래시 커맨드/멘션 자동완성/메일/Action Tier 제거 → 채널 Binding(RAG 응답 모드) 안내로 대체.
 * Enter 전송(IME 조합 중 제외), Shift+Enter 줄바꿈, 전송마다 client_id(UUID) — 재전송 중복 방지(FR-WEB-006).
 */
export function Composer({ channel, rootId, placeholder }: { channel: ChannelDetail; rootId: string | null; placeholder?: string }) {
  const [text, setText] = useState('');
  const ref = useRef<HTMLTextAreaElement>(null);
  const create = useCreatePost();
  const flash = useUiStore((s) => s.flash);
  const router = useRouter();
  const canPost = rootId ? channel.me.permissions.reply : channel.me.permissions.post;
  const binding = channel.binding;
  const botOn = !!binding?.enabled && !!channel.me.permissions.use_bot;
  const trigger = binding?.mode === 'TRIGGER_WORD' ? binding.trigger_word ?? '!rag' : null;

  const send = async () => {
    const body = text.trim();
    if (!body || create.isPending) return;
    try {
      const created = await create.mutateAsync({ channel_id: channel.id, root_id: rootId, message: body, client_id: crypto.randomUUID() });
      setText('');
      // THREAD 컨텍스트 채널: 답변이 질문 스레드로 스트리밍되므로 스레드를 바로 연다
      const triggered = botOn && (!trigger || body.startsWith(trigger));
      if (!rootId && triggered && binding?.conversation_mode === 'THREAD') router.push(`/ch/${channel.name}/thread/${created.id}`);
    } catch (e) {
      flash(e instanceof ApiError ? e.message : '전송 실패');
    }
  };

  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      void send();
    }
  };

  const hint = !botOn
    ? 'RAG 응답 꺼짐 · 일반 대화만 게시됩니다'
    : trigger
      ? rootId
        ? `답글은 이어서 질문 · 새 질문은 ${trigger} 로 시작`
        : `${trigger} 로 시작하는 메시지에 RAG 가 답합니다`
      : '모든 메시지에 RAG 가 사내 문서 근거로 답합니다';
  const defaultPlaceholder = rootId
    ? '스레드에 답글 · 컨텍스트는 이 스레드에만 유지됩니다'
    : trigger
      ? `#${channel.name}에 메시지 · ${trigger} 질문`
      : `#${channel.name}에 질문하기`;

  return (
    <div className={clsx('flex-none', rootId ? 'px-4 py-3 border-t border-line' : 'px-5 pb-4')}>
      <div className="relative card" style={{ background: rootId ? 'var(--bg)' : 'var(--surface)' }}>
        <textarea
          ref={ref}
          value={text}
          disabled={!canPost}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={onKey}
          rows={rootId ? 1 : 2}
          maxLength={12000}
          placeholder={!canPost ? `이 채널에서 ${rootId ? '답글' : '게시'} 권한이 없습니다 (${channel.me.role ?? '비멤버'})` : placeholder ?? defaultPlaceholder}
          className="w-full resize-none bg-transparent px-3.5 py-3 text-[14px] outline-none placeholder:text-muted disabled:opacity-60"
          style={{ minHeight: rootId ? 40 : 48, boxShadow: 'none' }}
        />
        <div className="flex items-center gap-1.5 px-2.5 py-2 border-t border-line">
          {trigger && botOn && (
            <button type="button" onClick={() => { setText((t) => (t.startsWith(trigger) ? t : `${trigger} ${t}`)); ref.current?.focus(); }} className="mono text-[11px] font-semibold px-[7px] py-[3px] rounded-lg hover:opacity-80" style={{ background: 'var(--lav2)' }} disabled={!canPost}>
              {trigger}
            </button>
          )}
          <span className="ml-auto text-[11px] text-muted whitespace-nowrap truncate" title={hint}>
            {hint}
          </span>
          <button type="button" onClick={send} disabled={!canPost || !text.trim() || create.isPending} className="h-[30px] px-3.5 rounded-lg text-[12px] font-semibold text-white disabled:opacity-50" style={{ background: 'var(--lav3)' }}>
            보내기
          </button>
        </div>
      </div>
    </div>
  );
}
