'use client';

import { useEffect, useRef, useState } from 'react';
import { Composer } from '@/components/chat/Composer';
import { PostItem } from '@/components/chat/PostItem';
import { Badge, Dropdown, MenuItem } from '@/components/ui/primitives';
import { fmtTime } from '@/lib/format';
import { useThread, type ChannelDetail } from '@/lib/query/hooks';
import { useUiStore } from '@/lib/stores/ui';

/**
 * 스레드 패널 · 레이아웃 A(사이드) / B(오버레이) — aiops_chatbot ThreadPanel 이식.
 * 제거: 인시던트 상태/담당자/심각도/LLM 요약/메일. RAG 스레드는 질문→답변→후속 질문의 대화 단위.
 */
export function ThreadPanel({ rootId, channel, onClose }: { rootId: string; channel: ChannelDetail | null; onClose: () => void }) {
  const { layout, flash } = useUiStore();
  const { data, isLoading, error } = useThread(rootId);
  const [menu, setMenu] = useState(false);
  const bodyRef = useRef<HTMLDivElement>(null);
  const replyCount = data?.replies.length ?? 0;
  const lastLen = data?.replies[replyCount - 1]?.message.length ?? 0;
  useEffect(() => {
    const el = bodyRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [replyCount, lastLen, rootId]);

  const style: React.CSSProperties = layout === 'A' ? { position: 'relative', width: 'clamp(380px,36%,460px)' } : { position: 'absolute', inset: '0 0 0 14%', width: 'auto' };
  const me = data?.me ?? channel?.me;
  const root = data?.root;
  const threadCtx = channel?.binding?.conversation_mode === 'THREAD';

  return (
    <aside className="flex flex-col bg-surface border-l border-line z-[6] animate-slide-in" style={style} data-screen-label="Thread">
      <header className="flex-none px-4 py-3 border-b border-line flex flex-col gap-2.5 bg-surface">
        <div className="flex items-center gap-2">
          <span className="font-bold text-[14px] whitespace-nowrap">Thread</span>
          {threadCtx && <Badge tone="lav2" title="이 스레드의 대화만 답변 컨텍스트로 사용됩니다">스레드 컨텍스트</Badge>}
          <div className="ml-auto flex gap-1.5 relative flex-none">
            <button type="button" onClick={() => setMenu((v) => !v)} className="btn !w-7 !h-7 !px-0 !text-[13px] !font-bold" aria-label="스레드 메뉴">⋯</button>
            <button type="button" onClick={onClose} className="btn !w-7 !h-7 !px-0 !text-[14px]" aria-label="닫기">×</button>
            <Dropdown open={menu} onClose={() => setMenu(false)}>
              <MenuItem onClick={() => { navigator.clipboard?.writeText(location.href); flash('링크 복사됨'); setMenu(false); }}>링크 복사</MenuItem>
            </Dropdown>
          </div>
        </div>
        <div className="flex gap-4 text-[12px] text-muted items-center flex-wrap">
          <span>답글 <b className="text-ink">{data?.thread.reply_count ?? 0}</b></span>
          <span>참여자 <b className="text-ink">{data?.thread.participant_count ?? 0}</b></span>
          <span className="ml-auto mono truncate">/ch/{channel?.name}/thread/{rootId.slice(0, 4)}</span>
        </div>
      </header>

      <div ref={bodyRef} className="flex-1 overflow-auto scroll-thin p-4 flex flex-col gap-4">
        {isLoading && <div className="text-[12px] text-muted">스레드 불러오는 중…</div>}
        {error && <div className="text-[12px] text-muted">스레드를 열 수 없습니다.</div>}
        {root && (
          <>
            <div className="flex gap-2.5 px-3 py-2.5 text-[12px] leading-[1.5]" style={{ background: 'var(--peach2)', borderLeft: '2px solid var(--lav3)' }}>
              <Badge tone="lav3" className="self-start !text-[10px] !font-bold">ROOT</Badge>
              <span className="min-w-0">
                <b>{root.user?.display_name ?? 'system'}</b> · {root.message.split('\n')[0].slice(0, 140)} · {fmtTime(root.created_at)}
              </span>
            </div>
            <PostItem post={root} me={me} inThread />
            {data.replies.map((r) => (
              <PostItem key={r.id} post={r} me={me} inThread />
            ))}
            {!data.replies.length && <div className="text-[12px] text-muted">아직 답글이 없습니다.</div>}
          </>
        )}
      </div>
      {channel && <Composer channel={channel} rootId={rootId} />}
    </aside>
  );
}
