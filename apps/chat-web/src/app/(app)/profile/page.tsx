'use client';

import { useState, type FormEvent } from 'react';
import { Avatar, Badge, Button, Card, Field, SectionHeader } from '@/components/ui/primitives';
import { changePassword } from '@/lib/auth';
import { useAuthStore } from '@/lib/stores/auth';
import { useUiStore } from '@/lib/stores/ui';

/**
 * 내 정보 · 비밀번호 변경 — aiops_chatbot profile 이식.
 * 제거: 표시명/타임존 편집, 세션 목록, 외부 계정 (계정 정보는 관리자가 admin-web 에서 관리).
 */
export default function ProfilePage() {
  const user = useAuthStore((s) => s.user);
  const setSession = useAuthStore((s) => s.setSession);
  const token = useAuthStore((s) => s.accessToken);
  const flash = useUiStore((s) => s.flash);
  const [cur, setCur] = useState('');
  const [nw, setNw] = useState('');
  const [nw2, setNw2] = useState('');
  const [pwMsg, setPwMsg] = useState<string | null>(null);
  const onPw = async (e: FormEvent) => {
    e.preventDefault();
    setPwMsg(null);
    if (nw !== nw2) return setPwMsg('새 비밀번호 확인이 일치하지 않습니다.');
    try {
      await changePassword(user!.email, cur, nw, user!.display_name);
      setCur(''); setNw(''); setNw2('');
      if (user && token) setSession(token, { ...user, must_change_password: false });
      flash('비밀번호가 변경되었습니다 · 다른 세션은 모두 종료됨');
    } catch (err) {
      setPwMsg(err instanceof Error ? err.message : '변경 실패');
    }
  };
  if (!user) return null;
  return (
    <div className="flex-1 overflow-auto scroll-thin px-7 py-6 flex flex-col gap-5" style={{ maxWidth: 960 }}>
      <header className="flex items-center gap-3">
        <Avatar name={user.display_name} size={44} color="var(--lav2)" />
        <div>
          <div className="font-semibold text-[24px] leading-[1.1]" style={{ letterSpacing: '-.03em' }}>{user.display_name}</div>
          <div className="mono text-[12px] text-muted flex items-center gap-2 mt-1">
            {user.email} <Badge tone="lav2">{user.role}</Badge>
          </div>
        </div>
      </header>
      {user.must_change_password && (
        <div className="px-4 py-3 rounded-[10px] text-[13px]" style={{ background: 'var(--lemon2)' }}>
          관리자가 발급한 임시 비밀번호로 로그인했습니다. 새 비밀번호로 변경해 주세요.
        </div>
      )}
      <div className="grid gap-4" style={{ gridTemplateColumns: 'minmax(0,480px)' }}>
        <Card>
          <SectionHeader title="비밀번호 변경" sub="현재 비밀번호 재확인" />
          <form onSubmit={onPw} className="p-4 flex flex-col gap-3">
            <Field label="현재 비밀번호"><input type="password" autoComplete="current-password" value={cur} onChange={(e) => setCur(e.target.value)} className="input" required /></Field>
            <Field label="새 비밀번호" hint="최소 12자 · 3종 이상"><input type="password" autoComplete="new-password" value={nw} onChange={(e) => setNw(e.target.value)} className="input" required /></Field>
            <Field label="새 비밀번호 확인"><input type="password" autoComplete="new-password" value={nw2} onChange={(e) => setNw2(e.target.value)} className="input" required /></Field>
            {pwMsg && <div className="text-[12px]" style={{ color: 'var(--coral)' }}>{pwMsg}</div>}
            <Button type="submit" variant="primary" className="!h-9 self-start">변경</Button>
            <div className="mono text-[11px] text-muted">prehash 만 전송 · 원문 비밀번호는 브라우저를 떠나지 않습니다</div>
          </form>
        </Card>
      </div>
    </div>
  );
}
