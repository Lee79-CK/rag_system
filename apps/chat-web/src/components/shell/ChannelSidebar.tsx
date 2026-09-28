'use client';

import clsx from 'clsx';
import Link from 'next/link';
import { useEffect, useRef, useState } from 'react';
import type { Sidebar, SidebarChannel } from '@/lib/query/hooks';

function Row({ c, active }: { c: SidebarChannel; active: boolean }) {
  const badgeBg = c.mention_count > 0 ? 'var(--coral)' : 'var(--lemon)';
  return (
    <Link href={`/ch/${c.name}`} title={c.display_name ?? c.name} className={clsx('flex items-center gap-2 px-2 py-1.5 rounded-lg text-[13px] font-medium hover:bg-surface2', c.is_muted && 'opacity-60')} style={{ background: active ? 'var(--lav2)' : 'transparent', color: 'var(--ink)' }}>
      <span className="mono text-[12px] text-muted font-medium w-2.5 text-center">{c.type === 'private' ? '⌂' : '#'}</span>
      <span className="truncate">{c.name}</span>
      {c.unread > 0 && (
        <span className="ml-auto mono text-[10px] font-semibold px-[5px] rounded-[5px]" style={{ background: badgeBg, color: c.mention_count > 0 ? '#fff' : '#1E1B2E' }}>
          {c.unread}
        </span>
      )}
    </Link>
  );
}

/**
 * 240px 사이드바 — aiops_chatbot 이식. 고객사 그룹/DM/채널 브라우저(참여 신청) 제거:
 * RAG 채널 멤버십은 관리자(admin-web)가 부여하므로 참여 중인 채널만 노출한다. ⌘K = 채널 필터.
 */
export function ChannelSidebar({ activeName, sidebar }: { activeName: string; sidebar?: Sidebar }) {
  const [q, setQ] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        inputRef.current?.focus();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);
  const match = (c: SidebarChannel) => !q || c.name.includes(q.toLowerCase()) || (c.display_name ?? '').toLowerCase().includes(q.toLowerCase());
  const favorites = sidebar?.favorites.filter(match) ?? [];
  const channels = sidebar?.other.filter(match) ?? [];
  return (
    <aside className="flex-none flex flex-col border-r border-line bg-surface" style={{ width: 240 }}>
      <div className="px-3.5 pt-3.5 pb-2.5 flex items-center gap-2 border-b border-line">
        <div className="font-bold text-[14px] truncate">{sidebar?.workspace.name ?? 'RAG Assistant'}</div>
        <span className="ml-auto mono text-[10px] font-semibold px-1.5 py-0.5 rounded-[5px]" style={{ background: 'var(--mint)', color: '#1E1B2E' }}>
          RAG
        </span>
      </div>
      <div className="px-3 py-2.5">
        <input ref={inputRef} value={q} onChange={(e) => setQ(e.target.value)} placeholder="채널 검색 · ⌘K" className="w-full h-8 px-2.5 rounded-[10px] border border-line bg-surface text-[12px] outline-none placeholder:text-muted focus:bg-surface2" />
      </div>
      <div className="flex-1 overflow-auto scroll-thin px-2 pb-3 flex flex-col gap-3.5">
        {!!favorites.length && (
          <div>
            <div className="px-2 py-1 mono text-[10px] font-semibold text-muted tracking-[.06em]">FAVORITES</div>
            {favorites.map((c) => <Row key={c.id} c={c} active={c.name === activeName} />)}
          </div>
        )}
        <div>
          <div className="px-2 py-1 mono text-[10px] font-semibold text-muted tracking-[.06em]">CHANNELS</div>
          {channels.map((c) => <Row key={c.id} c={c} active={c.name === activeName} />)}
          {sidebar && !channels.length && <div className="px-2 text-[11px] text-muted">{q ? '일치하는 채널 없음' : '참여 중인 채널이 없습니다'}</div>}
        </div>
      </div>
    </aside>
  );
}
