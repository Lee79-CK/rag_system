'use client';

import { useRouter } from 'next/navigation';
import { useEffect, useMemo, useRef } from 'react';
import { ChannelSidebar } from '@/components/shell/ChannelSidebar';
import { ThreadPanel } from '@/components/thread/ThreadPanel';
import { fmtDateLabel } from '@/lib/format';
import { useChannel, useMarkViewed, usePosts, useSidebar } from '@/lib/query/hooks';
import { useUiStore } from '@/lib/stores/ui';
import { ChannelHeader } from './ChannelHeader';
import { Composer } from './Composer';
import { PostItem } from './PostItem';

export function ChatView({ channelName, rootId }: { channelName: string; rootId: string | null }) {
  const router = useRouter();
  const { data: sidebar } = useSidebar();
  const { data: channel, error } = useChannel(channelName);
  const { data: posts, isLoading } = usePosts(channel?.id ?? null);
  const layout = useUiStore((s) => s.layout);
  const markViewed = useMarkViewed();
  const listRef = useRef<HTMLDivElement>(null);
  const threadOpen = !!rootId;

  useEffect(() => {
    try {
      localStorage.setItem('rag.lastChannel', channelName);
    } catch {
      /* ignore */
    }
  }, [channelName]);
  // 채널 진입/새 메시지 → 읽음 처리 (unread/mention 초기화)
  const postCount = posts?.items.length ?? 0;
  useEffect(() => {
    if (channel?.id) markViewed.mutate(channel.id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [channel?.id, postCount]);
  useEffect(() => {
    const el = listRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [postCount, channel?.id]);

  const openThread = (id: string) => router.push(`/ch/${channelName}/thread/${id}`);
  const closeThread = () => router.push(`/ch/${channelName}`);

  // 날짜 구분선 삽입
  const rows = useMemo(() => {
    const out: ({ kind: 'date'; label: string; key: string } | { kind: 'post'; post: NonNullable<typeof posts>['items'][number] })[] = [];
    let last = '';
    for (const p of posts?.items ?? []) {
      const d = fmtDateLabel(p.created_at);
      if (d !== last) {
        out.push({ kind: 'date', label: d, key: `d-${d}` });
        last = d;
      }
      out.push({ kind: 'post', post: p });
    }
    return out;
  }, [posts]);

  const firstRootId = [...(posts?.items ?? [])].reverse().find((p) => p.reply_count > 0)?.id ?? posts?.items[posts.items.length - 1]?.id ?? null;

  return (
    <div className="flex-1 flex min-w-0">
      <ChannelSidebar activeName={channelName} sidebar={sidebar} />
      <div className="flex-1 flex relative min-w-0">
        <section className="flex-1 flex flex-col min-w-0">
          <ChannelHeader channel={channel ?? null} name={channelName} threadOpen={threadOpen} onOpenThread={() => firstRootId && openThread(firstRootId)} />
          <div ref={listRef} className="flex-1 overflow-auto scroll-thin px-5 pt-5 pb-3 flex flex-col gap-[18px]">
            {error && <div className="text-[12px] text-muted">채널을 찾을 수 없거나 접근 권한이 없습니다.</div>}
            {(isLoading || (!channel && !error)) && <div className="text-[12px] text-muted">메시지 불러오는 중…</div>}
            {rows.map((r) =>
              r.kind === 'date' ? (
                <div key={r.key} className="self-center mono text-[11px] font-medium text-muted px-2.5 py-0.5 border border-line rounded-md">
                  {r.label}
                </div>
              ) : (
                <PostItem key={r.post.id} post={r.post} me={channel?.me} onOpenThread={openThread} activeThread={rootId} />
              ),
            )}
            {!isLoading && !!channel && !!posts && !rows.length && !error && <div className="text-[12px] text-muted">아직 메시지가 없습니다. 첫 질문을 남겨보세요.</div>}
          </div>
          {channel && <Composer channel={channel} rootId={null} />}
        </section>

        {/* Layout B 백드롭 */}
        {threadOpen && layout === 'B' && <div onClick={closeThread} className="absolute inset-0 z-[5]" style={{ background: 'rgba(30,27,46,.35)' }} />}
        {threadOpen && rootId && <ThreadPanel rootId={rootId} channel={channel ?? null} onClose={closeThread} />}
      </div>
    </div>
  );
}
