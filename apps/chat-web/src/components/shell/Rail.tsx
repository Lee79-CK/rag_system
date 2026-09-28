'use client';

import Link from 'next/link';
import { useState } from 'react';
import { Avatar, Dropdown, MenuItem } from '@/components/ui/primitives';
import { logout } from '@/lib/auth';
import { useSidebar } from '@/lib/query/hooks';
import { useAuthStore } from '@/lib/stores/auth';
import { useUiStore } from '@/lib/stores/ui';

const NAV = [
  { id: 'chat', glyph: 'CH', label: '채팅', href: '/', match: (p: string) => p === '/' || p.startsWith('/ch/') },
  { id: 'profile', glyph: 'ME', label: '내 정보', href: '/profile', match: (p: string) => p.startsWith('/profile') },
];

/** 72px 레일 — aiops_chatbot 이식. Threads/Events/관리/알림센터 제거 (RAG 관리는 admin-web) */
export function Rail({ pathname }: { pathname: string }) {
  const { theme, toggleTheme } = useUiStore();
  const user = useAuthStore((s) => s.user);
  const { data: sidebar } = useSidebar();
  const [menu, setMenu] = useState(false);
  const unreadChat = sidebar?.all.reduce((a, c) => a + c.unread, 0) ?? 0;
  const badges: Record<string, number> = { chat: unreadChat };

  return (
    <nav className="flex-none flex flex-col items-center py-3 gap-2.5 border-r border-line bg-bg" style={{ width: 72 }}>
      <Link href="/" className="w-8 h-8 rounded-[10px] mb-3 block" style={{ background: 'var(--lav3)' }} aria-label="RAG Assistant" />
      {NAV.map((n) => {
        const active = n.match(pathname);
        const b = badges[n.id] ?? 0;
        return (
          <Link key={n.id} href={n.href} title={n.label} className="relative flex flex-col items-center justify-center gap-1 rounded-[5px] hover:bg-lav2" style={{ width: 48, height: 52, background: active ? 'var(--surface)' : 'transparent', color: 'var(--ink)' }}>
            <span className="mono text-[12px] font-semibold">{n.glyph}</span>
            <span className="text-[10px] font-medium">{n.label}</span>
            {b > 0 && (
              <span className="absolute -top-1 -right-1 min-w-4 h-4 px-1 rounded-[5px] mono text-[10px] leading-4 font-bold text-white" style={{ background: 'var(--coral)', border: '2px solid var(--bg)' }}>
                {b}
              </span>
            )}
          </Link>
        );
      })}
      <div className="flex-1" />
      <button type="button" onClick={toggleTheme} title="라이트/다크" className="w-12 h-10 rounded-lg border border-line bg-surface mono text-[11px] font-semibold hover:bg-surface2">
        {theme === 'light' ? 'DARK' : 'LIGHT'}
      </button>
      <div className="relative mt-2">
        <button type="button" onClick={() => setMenu((v) => !v)} title={user?.display_name} className="block">
          <Avatar name={user?.display_name ?? '?'} size={36} color="var(--lav2)" />
        </button>
        <Dropdown open={menu} onClose={() => setMenu(false)} align="left" className="!left-0 !top-auto bottom-10 !w-[220px]">
          <div className="px-2.5 py-2 text-[12px]">
            <div className="font-semibold">{user?.display_name}</div>
            <div className="mono text-[11px] text-muted">{user?.email}</div>
            <div className="mono text-[10px] text-muted mt-1">{user?.role}</div>
          </div>
          <MenuItem onClick={() => { setMenu(false); window.location.href = '/profile'; }}>내 정보 · 비밀번호</MenuItem>
          <MenuItem danger onClick={() => logout().then(() => (window.location.href = '/login'))}>
            로그아웃
          </MenuItem>
        </Dropdown>
      </div>
    </nav>
  );
}
