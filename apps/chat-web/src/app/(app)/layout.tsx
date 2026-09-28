'use client';

import { usePathname, useRouter } from 'next/navigation';
import { useEffect, type ReactNode } from 'react';
import { Rail } from '@/components/shell/Rail';
import { refreshAccess } from '@/lib/api';
import { useAuthStore } from '@/lib/stores/auth';
import { useRealtime } from '@/lib/useRealtime';

/** 인증 가드 + 레일 + WS 연결 */
export default function AppLayout({ children }: { children: ReactNode }) {
  const { user, hydrated } = useAuthStore();
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    if (!hydrated) refreshAccess().then((ok) => !ok && router.replace('/login'));
    else if (!user) router.replace('/login');
  }, [hydrated, user, router]);

  useRealtime();

  if (!user) {
    return (
      <div className="h-screen flex items-center justify-center bg-bg text-muted text-[13px]">
        <span className="inline-block w-4 h-4 rounded-full border-2 border-line border-t-lav3 animate-spin mr-2" /> 세션 확인 중…
      </div>
    );
  }
  return (
    <div className="h-screen flex bg-bg overflow-hidden" style={{ minWidth: 1280 }}>
      <Rail pathname={pathname} />
      {children}
    </div>
  );
}
