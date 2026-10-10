import { useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import { Outlet, useLocation, useNavigate } from 'react-router-dom';
import { Result, Spin, Tooltip } from 'antd';
import { AuthUserSwitcher } from './AuthUserSwitcher';
import { useWhoami } from '../api/auth';
import { RECENT_FAILED_HOURS, useRecentFailedChatJobs } from '../api/chatJobs';
import { errorMessage } from './QueryState';
import type { Role } from '../types';

/**
 * Admin Console shell — imported design (Admin Console.dc.html):
 * classification banner + navy grouped sidebar + topbar.
 * IA & RBAC: docs/admin_console_design_script.md §2.1, §4.
 */

const ROLE_LABEL: Record<Role, string> = {
  SYS_ADMIN: '시스템 관리자',
  DOC_ADMIN: '문서 관리자',
  QUALITY_EVALUATOR: '품질 평가자',
  AUDITOR: '감사자',
};


type IconName =
  | 'dashboard'
  | 'documents'
  | 'index'
  | 'channels'
  | 'chat'
  | 'feedback'
  | 'evaluation'
  | 'settings'
  | 'audit'
  | 'errors';

function NavIcon({ name }: { name: IconName }) {
  const p = { width: 16, height: 16, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: 2 };
  switch (name) {
    case 'dashboard':
      return (
        <svg {...p}>
          <rect x="3" y="3" width="7" height="7" rx="1" /><rect x="14" y="3" width="7" height="7" rx="1" />
          <rect x="3" y="14" width="7" height="7" rx="1" /><rect x="14" y="14" width="7" height="7" rx="1" />
        </svg>
      );
    case 'documents':
      return (<svg {...p}><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><path d="M14 2v6h6" /></svg>);
    case 'index':
      return (<svg {...p}><path d="M12 2l9 5-9 5-9-5 9-5z" /><path d="M3 12l9 5 9-5" /><path d="M3 17l9 5 9-5" /></svg>);
    case 'channels':
      return (<svg {...p}><path d="M10 13a5 5 0 0 0 7.5.5l3-3a5 5 0 0 0-7-7l-1.7 1.7" /><path d="M14 11a5 5 0 0 0-7.5-.5l-3 3a5 5 0 0 0 7 7l1.7-1.7" /></svg>);
    case 'chat':
      return (<svg {...p}><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" /></svg>);
    case 'feedback':
      return (<svg {...p}><path d="M14 9V5a3 3 0 0 0-3-3l-4 9v11h11.3a2 2 0 0 0 2-1.7l1.4-9a2 2 0 0 0-2-2.3z" /><path d="M7 22H4a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2h3" /></svg>);
    case 'evaluation':
      return (<svg {...p}><path d="M3 3v18h18" /><path d="M7 14l4-4 3 3 5-6" /></svg>);
    case 'settings':
      return (
        <svg {...p}>
          <circle cx="12" cy="12" r="3" />
          <path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1-1.6 1.7 1.7 0 0 0-1.9.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.9 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.6-1 1.7 1.7 0 0 0-.3-1.9l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.9.3h0a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.9-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.9v0a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z" />
        </svg>
      );
    case 'audit':
      return (<svg {...p}><path d="M12 3l8 4v5c0 5-3.5 8-8 9-4.5-1-8-4-8-9V7l8-4z" /><path d="M9 12l2 2 4-4" /></svg>);
    case 'errors':
      return (<svg {...p}><path d="M10.3 3.9L1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z" /><path d="M12 9v4" /><path d="M12 17h.01" /></svg>);
  }
}

interface NavDef {
  path: string;
  label: string;
  icon: IconName;
  title: string;
  roles: Role[]; // roles that may access this screen
  badge?: 'dead';
}

interface NavGroup {
  group: string;
  items: NavDef[];
}

const NAV: NavGroup[] = [
  {
    group: '모니터링',
    items: [
      { path: '/', label: '대시보드', icon: 'dashboard', title: '대시보드', roles: ['SYS_ADMIN', 'DOC_ADMIN', 'QUALITY_EVALUATOR', 'AUDITOR'] },
    ],
  },
  {
    group: '지식 관리',
    items: [
      { path: '/documents', label: '문서 관리', icon: 'documents', title: '문서 관리', roles: ['SYS_ADMIN', 'DOC_ADMIN'] },
      { path: '/index-jobs', label: '색인 작업', icon: 'index', title: '색인 작업', roles: ['SYS_ADMIN', 'DOC_ADMIN'] },
    ],
  },
  {
    group: '서비스 운영',
    items: [
      { path: '/channels', label: '채널 관리', icon: 'channels', title: 'Web Chat 채널 · Binding · 멤버', roles: ['SYS_ADMIN', 'DOC_ADMIN'] },
      { path: '/chat-users', label: '채팅 사용자', icon: 'chat', title: '채팅 사용자', roles: ['SYS_ADMIN'] },
      { path: '/chat-jobs', label: '대화 작업', icon: 'chat', title: '대화 작업', roles: ['SYS_ADMIN', 'QUALITY_EVALUATOR'], badge: 'dead' },
    ],
  },
  {
    group: '품질',
    items: [
      { path: '/feedback', label: '피드백', icon: 'feedback', title: '피드백', roles: ['SYS_ADMIN', 'QUALITY_EVALUATOR'] },
      { path: '/evaluation', label: '품질 평가', icon: 'evaluation', title: '품질 평가', roles: ['SYS_ADMIN', 'QUALITY_EVALUATOR'] },
    ],
  },
  {
    group: '시스템',
    items: [
      { path: '/settings', label: '설정', icon: 'settings', title: '설정', roles: ['SYS_ADMIN'] },
      { path: '/audit', label: '감사 로그', icon: 'audit', title: '감사 로그', roles: ['SYS_ADMIN', 'AUDITOR'] },
      { path: '/errors', label: '오류 로그', icon: 'errors', title: '오류 로그', roles: ['SYS_ADMIN'] },
    ],
  },
];

const ALL_ITEMS = NAV.flatMap((g) => g.items);

function useNow() {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 30_000);
    return () => clearInterval(t);
  }, []);
  return now;
}

function fmtKst(d: Date): string {
  const p = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

export function AppLayout() {
  const location = useLocation();
  const navigate = useNavigate();
  const whoami = useWhoami();
  const me = whoami.data;
  const now = useNow();

  const roles = (me?.roles ?? []) as Role[];
  // 메뉴 roles 는 admin-api require_roles 와 같아야 한다. 신원 확인 전/실패 시에는 아무 메뉴도 열지 않는다.
  const canAccess = (item: NavDef) => item.roles.some((r) => roles.includes(r));
  const recentFailed = useRecentFailedChatJobs(
    roles.includes('SYS_ADMIN') || roles.includes('QUALITY_EVALUATOR'),
  );

  const active =
    ALL_ITEMS.map((n) => n.path)
      .filter((k) => (k === '/' ? location.pathname === '/' : location.pathname.startsWith(k)))
      .sort((a, b) => b.length - a.length)[0] ?? '/';

  const activeItem = ALL_ITEMS.find((n) => n.path === active);
  const screenTitle = activeItem?.title ?? '대시보드';

  // 최근 RECENT_FAILED_HOURS 시간 실패 건수 — 전체 이력을 세면 한 번 실패한 뒤 영영 줄지 않는다
  const deadCount = recentFailed.data?.length ?? 0;

  const userName = me?.display_name || me?.login_id || '관리자';
  const userInitial = userName.slice(0, 1).toUpperCase();
  const roleLabel = roles.length ? roles.map((r) => ROLE_LABEL[r] ?? r).join(' · ') : '역할 미지정';

  return (
    <div
      style={{
        minWidth: 1280,
        height: '100vh',
        display: 'flex',
        flexDirection: 'column',
        color: 'var(--text)',
        background: 'var(--bg)',
        overflow: 'hidden',
      }}
    >
      {/* Classification banner (§8 closed-network / air-gapped) */}
      <div
        style={{
          flex: 'none',
          height: 30,
          background: 'var(--banner-bg)',
          color: 'var(--banner-fg)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          gap: 14,
          fontSize: 12,
          letterSpacing: '.4px',
          fontWeight: 600,
        }}
      >
        <span>Ⅲ급 · 대외비</span>
        <span style={{ opacity: 0.55 }}>|</span>
        <span>내부 업무망 전용 시스템 — 승인된 관리자만 접근할 수 있습니다</span>
        <span style={{ opacity: 0.55 }}>|</span>
        <span className="mono">AIR-GAPPED</span>
      </div>

      <div style={{ flex: 1, minHeight: 0, display: 'flex' }}>
        {/* Sidebar */}
        <div
          style={{
            flex: 'none',
            width: 'var(--sidebar-w)',
            background: 'var(--nav-bg)',
            display: 'flex',
            flexDirection: 'column',
          }}
        >
          <div
            style={{
              padding: '18px 16px 14px',
              borderBottom: '1px solid rgba(255,255,255,.08)',
              display: 'flex',
              alignItems: 'center',
              gap: 10,
            }}
          >
            <div
              style={{
                width: 32,
                height: 32,
                borderRadius: 8,
                background: 'var(--nav-active-bg)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}
            >
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#ffffff" strokeWidth={2}>
                <path d="M12 3l8 4v5c0 5-3.5 8-8 9-4.5-1-8-4-8-9V7l8-4z" />
              </svg>
            </div>
            <div>
              <div style={{ color: '#fff', fontSize: 14, fontWeight: 700, lineHeight: 1.2 }}>RAG Platform</div>
              <div style={{ color: '#8494ab', fontSize: 11 }}>Admin Console</div>
            </div>
          </div>

          <div style={{ flex: 1, overflowY: 'auto', padding: '12px 10px', display: 'flex', flexDirection: 'column', gap: 2 }}>
            {NAV.map((g) => (
              <div key={g.group}>
                <div style={{ fontSize: 10.5, color: 'var(--nav-group)', fontWeight: 700, letterSpacing: '.8px', padding: '12px 12px 4px' }}>
                  {g.group}
                </div>
                {g.items.map((item) => {
                  const enabled = canAccess(item);
                  const isActive = active === item.path;
                  const showDead = item.badge === 'dead' && deadCount > 0;
                  const row = (
                    <div
                      key={item.path}
                      onClick={enabled ? () => navigate(item.path) : undefined}
                      className={enabled && !isActive ? 'nav-row' : undefined}
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: 10,
                        padding: '9px 12px',
                        borderRadius: 7,
                        cursor: enabled ? 'pointer' : 'not-allowed',
                        fontSize: 13.5,
                        fontWeight: 600,
                        color: isActive ? '#fff' : enabled ? 'var(--nav-fg)' : '#4a5876',
                        background: isActive ? 'var(--nav-active-bg)' : 'transparent',
                        opacity: enabled ? 1 : 0.55,
                      }}
                    >
                      <NavIcon name={item.icon} />
                      <span style={{ flex: 1 }}>{item.label}</span>
                      {showDead && (
                        <span
                          title={`최근 ${RECENT_FAILED_HOURS}시간 동안 실패한 대화 작업 ${deadCount}건`}
                          style={{
                            padding: '1px 7px',
                            borderRadius: 999,
                            background: 'var(--danger)',
                            color: '#fff',
                            fontSize: 10.5,
                            fontWeight: 700,
                          }}
                        >
                          {deadCount}
                        </span>
                      )}
                    </div>
                  );
                  return enabled ? (
                    row
                  ) : (
                    <Tooltip key={item.path} title={`권한 필요: ${item.roles.join(' / ')}`} placement="right">
                      {row}
                    </Tooltip>
                  );
                })}
              </div>
            ))}
          </div>

          <div
            style={{
              flex: 'none',
              padding: '14px 16px',
              borderTop: '1px solid rgba(255,255,255,.08)',
              display: 'flex',
              alignItems: 'center',
              gap: 10,
            }}
          >
            <div
              style={{
                width: 30,
                height: 30,
                borderRadius: '50%',
                background: '#22314a',
                color: '#c6cfdd',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                fontSize: 12,
                fontWeight: 700,
              }}
            >
              {userInitial}
            </div>
            <div style={{ minWidth: 0 }}>
              <div style={{ color: '#e6ebf2', fontSize: 12.5, fontWeight: 600 }}>{userName}</div>
              <div style={{ color: '#8494ab', fontSize: 11 }}>{roleLabel}</div>
            </div>
          </div>
        </div>

        {/* Main column */}
        <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column' }}>
          <div
            style={{
              flex: 'none',
              height: 56,
              background: 'var(--surface)',
              borderBottom: '1px solid var(--border)',
              display: 'flex',
              alignItems: 'center',
              padding: '0 24px',
              gap: 12,
            }}
          >
            <div style={{ fontSize: 20, fontWeight: 700 }}>{screenTitle}</div>
            <Pill bg="#fffbeb" fg="#d97706" border="#fde5bf">PoC</Pill>
            <Pill bg="#f3f4f6" fg="#6b7280">폐쇄망 · KST</Pill>
            <div style={{ flex: 1 }} />
            <div className="mono" style={{ fontSize: 12, color: 'var(--text-sub)' }}>{fmtKst(now)}</div>
            <AuthUserSwitcher />
          </div>

          <div style={{ flex: 1, minHeight: 0, overflowY: 'auto', padding: 24 }}>
            {/* 경로 가드 — 사이드바 비활성화만으로는 URL 직접 입력을 막지 못한다 */}
            {whoami.isLoading ? (
              <Spin style={{ display: 'block', marginTop: 80 }} />
            ) : whoami.error ? (
              <Result
                status="403"
                title="관리자 신원을 확인할 수 없습니다"
                subTitle={`${errorMessage(whoami.error)} — 우측 상단 접속 사용자를 확인하세요.`}
              />
            ) : activeItem && !canAccess(activeItem) ? (
              <Result
                status="403"
                title="이 화면에 접근할 권한이 없습니다"
                subTitle={`필요한 역할: ${activeItem.roles.join(' / ')}`}
              />
            ) : (
              <Outlet />
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function Pill({ children, bg, fg, border }: { children: ReactNode; bg: string; fg: string; border?: string }) {
  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        padding: '2px 8px',
        borderRadius: 6,
        background: bg,
        color: fg,
        fontSize: 11,
        fontWeight: 700,
        border: border ? `1px solid ${border}` : undefined,
      }}
    >
      {children}
    </span>
  );
}
