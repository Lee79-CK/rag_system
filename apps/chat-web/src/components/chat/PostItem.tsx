'use client';

import clsx from 'clsx';
import { useState } from 'react';
import { BlockRenderer } from '@/components/blocks/BlockRenderer';
import { Avatar, Badge, Dropdown, MenuItem } from '@/components/ui/primitives';
import { fmtTime } from '@/lib/format';
import { useDeletePost, useWidgetAction, type EffectivePermissions, type PostDto } from '@/lib/query/hooks';
import { useAuthStore } from '@/lib/stores/auth';
import { useUiStore } from '@/lib/stores/ui';
import type { Block } from '@/shared';
import { Markdown } from './Markdown';

/**
 * 메시지 1건 — aiops_chatbot PostItem 이식.
 * 변경: 리액션/핀/이벤트·승인 카드 제거, RAG Bot 답변 상태(접수·스트리밍·오류) 표시,
 *       피드백 버튼은 Bot Post 의 feedback_token(HMAC) 을 value 로 전송 (TDD §7.1.4).
 */
export function PostItem({ post, me, onOpenThread, activeThread, inThread, compact }: { post: PostDto; me?: EffectivePermissions | null; onOpenThread?: (id: string) => void; activeThread?: string | null; inThread?: boolean; compact?: boolean }) {
  const user = useAuthStore((s) => s.user);
  const remove = useDeletePost();
  const act = useWidgetAction();
  const flash = useUiStore((s) => s.flash);
  const [menu, setMenu] = useState(false);
  const props = post.props;
  const size = inThread ? 32 : 36;

  // ---- system notice
  if (post.type === 'system') {
    return (
      <div className="self-stretch flex items-center gap-2 px-3 py-2 rounded-[10px] text-[12px] leading-[1.5] animate-fade-up" style={{ background: 'var(--surface2)', color: 'var(--ink)' }}>
        <span className="badge" style={{ background: 'var(--mint)', color: '#fff', fontSize: 9 }}>SYSTEM</span>
        <span className="min-w-0">{post.message}</span>
      </div>
    );
  }

  const isBot = post.type === 'bot' || !!post.user?.is_bot;
  const name = post.user?.display_name ?? (isBot ? 'RAG Assistant' : '알 수 없음');
  const isMine = post.user?.id === user?.id;
  const blocks = (post.blocks ?? []) as Block[];
  const isError = props.kind === 'error';
  const streaming = !!props.streaming;
  const canModerate = isMine || me?.permissions.moderate;
  const showFeedback = isBot && !streaming && !isError && !!props.feedback_token;
  const sendFeedback = (dir: 'up' | 'down') =>
    act.mutate(
      { post_id: post.id, block_id: 'fb', action_id: `feedback:${dir}`, value: props.feedback_token },
      { onSuccess: () => flash(dir === 'up' ? '피드백 감사합니다' : '피드백 기록됨 · 답변 품질 개선에 활용됩니다'), onError: (e) => flash((e as Error).message) },
    );

  return (
    <article className={clsx('grid gap-3 group relative', inThread ? 'gap-2.5' : '')} style={{ gridTemplateColumns: `${size}px 1fr` }} id={post.id}>
      <Avatar name={name} size={size} isBot={isBot} color={isBot ? 'var(--lav)' : undefined} />
      <div className="min-w-0">
        <div className="flex items-baseline gap-2 flex-wrap">
          <span className="font-bold text-[13px]">{name}</span>
          {isBot && <Badge tone="muted" className="!text-[9px]">BOT · RAG</Badge>}
          <span className="mono text-[11px] text-muted">{fmtTime(post.created_at)}</span>
          {post.edit_at && <span className="text-[10px] text-muted">(편집됨)</span>}
          {streaming && <span className="dot" style={{ background: 'var(--lav3)', animation: 'pulseDot 1s infinite' }} title="응답 생성 중" />}
          {/* hover actions */}
          <span className="ml-auto opacity-0 group-hover:opacity-100 flex gap-1 relative">
            {!inThread && onOpenThread && <button type="button" className="btn !h-6 !px-2 !text-[11px]" onClick={() => onOpenThread(post.id)}>답글</button>}
            <button type="button" className="btn !h-6 !px-2 !text-[11px]" onClick={() => setMenu((v) => !v)}>⋯</button>
            <Dropdown open={menu} onClose={() => setMenu(false)}>
              <MenuItem onClick={() => { navigator.clipboard?.writeText(`${location.origin}/ch/${location.pathname.split('/')[2]}/thread/${post.root_id ?? post.id}#${post.id}`); flash('링크 복사됨'); setMenu(false); }}>링크 복사</MenuItem>
              {!isBot && post.message && <MenuItem onClick={() => { navigator.clipboard?.writeText(post.message); flash('복사됨'); setMenu(false); }}>텍스트 복사</MenuItem>}
              {canModerate && !isBot && <MenuItem danger onClick={() => { remove.mutate(post.id); setMenu(false); }}>삭제</MenuItem>}
            </Dropdown>
          </span>
        </div>
        {post.message && (
          <div className={clsx('mt-1', inThread && '!text-[13px]', isError && 'pl-2.5 border-l-2')} style={isError ? { borderColor: 'var(--coral)' } : undefined}>
            <Markdown text={post.message} className={inThread ? '!text-[13px] !leading-[1.6]' : ''} />
          </div>
        )}
        {streaming && !post.message && <div className="mt-1 text-[12px] text-muted">{props.ack ? '질문을 접수했습니다. 근거 문서를 찾는 중…' : '생각 중…'}</div>}
        {blocks.length > 0 && <BlockRenderer blocks={blocks} ctx={{ postId: post.id, me, compact }} />}

        {/* feedback (v1.1) */}
        {showFeedback && (
          <div className="flex gap-1.5 mt-2 flex-wrap">
            <button type="button" disabled={act.isPending} onClick={() => sendFeedback('up')} className="btn !h-6 !px-2 !text-[11px] !rounded-[10px] !text-muted !font-medium">👍 도움됨{props.feedback?.['1'] ? ` ${props.feedback['1']}` : ''}</button>
            <button type="button" disabled={act.isPending} onClick={() => sendFeedback('down')} className="btn !h-6 !px-2 !text-[11px] !rounded-[10px] !text-muted !font-medium">👎 아쉬움{props.feedback?.['-1'] ? ` ${props.feedback['-1']}` : ''}</button>
          </div>
        )}

        {/* thread 요약 */}
        {!inThread && post.reply_count > 0 && onOpenThread && (
          <button type="button" onClick={() => onOpenThread(post.id)} className={clsx('mt-2 flex items-center gap-2 h-[30px] pl-1.5 pr-2.5 rounded-lg border text-[12px] font-semibold hover:border-ink hover:bg-lav2', activeThread === post.id ? 'border-ink bg-lav2' : 'border-line bg-surface')}>
            <span className="flex">
              {post.participants.slice(0, 3).map((p, i) => (
                <Avatar key={p.id} name={p.display_name} size={18} isBot={p.is_bot} className={clsx('!text-[8px]', i > 0 && '-ml-1')} />
              ))}
            </span>
            답글 {post.reply_count}개
            <span className="mono text-[11px] font-normal text-muted">· 마지막 {fmtTime(post.last_reply_at)}</span>
          </button>
        )}
      </div>
    </article>
  );
}
