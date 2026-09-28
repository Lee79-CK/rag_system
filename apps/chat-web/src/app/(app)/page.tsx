'use client';

import { useRouter } from 'next/navigation';
import { useEffect } from 'react';
import { useSidebar } from '@/lib/query/hooks';

/** 루트 → 마지막 채널 또는 첫 채널로 */
export default function Home() {
  const router = useRouter();
  const { data } = useSidebar();
  useEffect(() => {
    if (!data) return;
    let last: string | null = null;
    try {
      last = localStorage.getItem('rag.lastChannel');
    } catch {
      /* ignore */
    }
    const target = data.all.find((c) => c.name === last) ?? data.all[0];
    if (target) router.replace(`/ch/${target.name}`);
  }, [data, router]);
  if (data && !data.all.length) {
    return <div className="flex-1 flex items-center justify-center text-muted text-[13px]">참여 중인 채널이 없습니다. 관리자에게 채널 초대를 요청하세요.</div>;
  }
  return <div className="flex-1 flex items-center justify-center text-muted text-[13px]">채널 불러오는 중…</div>;
}
