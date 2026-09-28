'use client';

import { useUiStore } from '@/lib/stores/ui';

/** 하단 중앙 pill 토스트 (v2) */
export function Toast() {
  const toast = useUiStore((s) => s.toast);
  if (!toast) return null;
  return (
    <div className="fixed left-1/2 bottom-6 -translate-x-1/2 z-[60] flex items-center gap-2.5 rounded-full px-[18px] py-3 text-[13px] font-medium animate-fade-up" style={{ background: 'var(--ink)', color: 'var(--bg)', boxShadow: '0 10px 30px rgba(0,0,0,.2)' }}>
      <span className="dot" style={{ background: 'var(--lemon)' }} />
      {toast}
    </div>
  );
}
