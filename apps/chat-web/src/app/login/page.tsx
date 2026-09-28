'use client';

import { useRouter } from 'next/navigation';
import { useEffect, useState, type FormEvent } from 'react';
import { ApiError, refreshAccess } from '@/lib/api';
import { login } from '@/lib/auth';
import { useAuthStore } from '@/lib/stores/auth';

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const user = useAuthStore((s) => s.user);

  useEffect(() => {
    // 이미 refresh 쿠키가 있으면 바로 앱으로
    refreshAccess().then((ok) => ok && router.replace('/'));
  }, [router]);
  useEffect(() => {
    if (user) router.replace('/');
  }, [user, router]);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(email, password);
      setPassword(''); // 6.1.1-6: 제출 후 상태 초기화
      router.replace(useAuthStore.getState().user?.must_change_password ? '/profile' : '/');
    } catch (err) {
      setPassword('');
      setError(err instanceof ApiError ? err.message : '로그인에 실패했습니다.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="min-h-screen grid bg-bg" style={{ gridTemplateColumns: 'minmax(0,1.1fr) minmax(0,1fr)' }}>
      {/* 좌측 히어로 (v2: 라벤더 그라데이션) */}
      <div className="relative overflow-hidden flex flex-col justify-between p-16" style={{ color: '#1D1D1F', background: 'linear-gradient(160deg,#EDE9FE 0%,#F5F5F7 60%,#FFFFFF 100%)' }}>
        <div className="flex items-center gap-2.5">
          <div className="w-7 h-7 rounded-lg" style={{ background: 'var(--lav3)' }} />
          <div className="font-bold text-[15px]">RAG Assistant</div>
          <div className="ml-auto mono text-[11px] font-medium px-2.5 py-[3px] rounded-full" style={{ border: '1px solid rgba(0,0,0,.15)' }}>
            Private Cloud · v2.0
          </div>
        </div>
        <div>
          <div className="font-semibold" style={{ fontSize: 'clamp(40px,5vw,68px)', lineHeight: 1.05, letterSpacing: '-.035em', maxWidth: '12ch', textWrap: 'pretty' }}>
            사내 문서에서,
            <br />
            근거와 함께
            <br />
            바로 답합니다.
          </div>
          <p className="mt-7 text-[16px] leading-[1.6]" style={{ maxWidth: '46ch', color: '#3A3A3C', textWrap: 'pretty' }}>
            채널마다 허용된 지식 범위 안에서만 검색해 답변하고, 참고한 문서와 위치를 함께 보여줍니다. 폐쇄망 안에서 동작하며 대화는 외부로 나가지 않습니다.
          </p>
        </div>
        <div className="flex gap-3 items-end">
          <div style={{ width: 120, height: 120, background: 'var(--lav3)', borderRadius: 32 }} />
          <div style={{ width: 80, height: 80, background: 'var(--lav)', borderRadius: 24 }} />
          <div style={{ width: 44, height: 44, background: '#1D1D1F', borderRadius: 14 }} />
          <div className="ml-auto mono text-[12px] leading-[1.6] font-medium text-right" style={{ color: '#6E6E73' }}>
            Hybrid Retrieval · Re-rank
            <br />Channel 격리 · 근거 인용
          </div>
        </div>
      </div>

      {/* 우측 폼 */}
      <div className="flex items-center justify-center p-12">
        <form onSubmit={submit} className="flex flex-col gap-[22px] animate-fade-up" style={{ width: 'min(400px,100%)' }} autoComplete="on">
          <div>
            <div className="font-semibold text-[30px] leading-[1.2]" style={{ letterSpacing: '-.03em' }}>
              로그인
            </div>
            <div className="mt-1.5 text-[13px] leading-[1.5] text-muted">
              관리자가 발급한 이메일 계정으로 로그인합니다.
            </div>
          </div>
          <label className="flex flex-col gap-1.5">
            <span className="text-[12px] font-semibold text-muted">이메일 (계정 ID)</span>
            <input type="email" required autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="hong@example.com" className="h-11 px-3 rounded-lg text-[14px] bg-surface text-ink outline-none border border-line focus:shadow-[0_0_0_3px_var(--lemon2)]" />
          </label>
          <label className="flex flex-col gap-1.5">
            <span className="text-[12px] font-semibold text-muted flex justify-between">
              <span>비밀번호</span>
              <span className="font-medium">최소 12자 · 3종 이상</span>
            </span>
            <input type="password" required autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="••••••••••••" className="h-11 px-3 rounded-lg text-[14px] bg-surface text-ink outline-none border border-line focus:shadow-[0_0_0_3px_var(--lemon2)]" />
          </label>
          {error && (
            <div className="text-[12px] px-3 py-2 rounded-lg" style={{ background: 'var(--peach2)', color: 'var(--coral)', border: '1px solid var(--line)' }}>
              {error}
            </div>
          )}
          <button type="submit" disabled={busy} className="h-[46px] rounded-[10px] text-[14px] font-semibold text-white disabled:opacity-60" style={{ background: busy ? 'var(--lav)' : 'var(--lav3)' }}>
            {busy ? '비밀번호 파생 중… (PBKDF2 600k)' : '로그인'}
          </button>
          <div className="mono text-[11px] leading-[1.5] text-muted p-2.5 rounded-[10px] bg-surface2">prehash = PBKDF2-HMAC-SHA256(pw, salt, 600k) · 원문 비밀번호는 브라우저를 떠나지 않습니다</div>
        </form>
      </div>
    </div>
  );
}
