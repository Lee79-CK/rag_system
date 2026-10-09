import type { ReactNode } from 'react';
import { useNavigate } from 'react-router-dom';
import { Surface } from '../components/ui';
import { useDocuments } from '../api/documents';
import { useChannels } from '../api/channels';
import { useChatJobs } from '../api/chatJobs';
import { useWhoami } from '../api/auth';
import { useIndexJobs } from '../api/indexJobs';
import { useFeedbackSummary } from '../api/feedback';

/**
 * Dashboard — imported design (Admin Console.dc.html §5.1):
 * dead-letter banner + 6 KPI cards + service strip + 2-col widgets.
 * Wired to real admin-api data where available; the 24h trend chart and
 * service latencies are illustrative (no timeseries/health metrics API yet).
 */

const DEAD_LETTER_STATUSES = new Set(['DEAD_LETTER', 'DEADLETTER', 'FAILED']);
const COMPLETED = new Set(['COMPLETED', 'SENT', 'SUCCEEDED', 'SUCCESS']);
const RUNNING = new Set(['RUNNING', 'QUEUED', 'INDEXING', 'PENDING', 'PROCESSING']);
const FAILED = new Set(['FAILED', 'PARSE_FAILED', 'INDEX_FAILED', 'ERROR']);

export function Dashboard() {
  const navigate = useNavigate();
  const docs = useDocuments();
  // 역할별로 허용된 API 만 호출 (채널 조회 SYS·DOC / 대화 작업 SYS·QE) — 403 카드 대신 해당 지표를 비워 둔다
  const roles = useWhoami().data?.roles ?? [];
  const channels = useChannels(roles.includes('SYS_ADMIN') || roles.includes('DOC_ADMIN'));
  const chatJobs = useChatJobs(undefined, roles.includes('SYS_ADMIN') || roles.includes('QUALITY_EVALUATOR'));
  const indexJobs = useIndexJobs();
  const feedback = useFeedbackSummary();

  const jobs = chatJobs.data ?? [];
  const todayQ = jobs.length;
  const completed = jobs.filter((j) => COMPLETED.has((j.status ?? '').toUpperCase())).length;
  const successRate = todayQ ? Math.round((completed / todayQ) * 1000) / 10 : null;
  const deadLetter = jobs.filter((j) => DEAD_LETTER_STATUSES.has((j.status ?? '').toUpperCase())).length;

  const channelList = channels.data ?? [];
  const totalChannels = channelList.length;
  const activeChannels = channelList.filter((c) => c.bindings?.some((b) => b.enabled)).length;

  const idx = indexJobs.data ?? [];
  const indexPending = idx.filter((j) => RUNNING.has((j.status ?? '').toUpperCase())).length;
  const indexFailed = idx.filter((j) => FAILED.has((j.status ?? '').toUpperCase())).length;
  const failedDocs = (docs.data ?? []).filter((d) => FAILED.has((d.status ?? '').toUpperCase()));

  const ratio = feedback.data?.satisfaction_ratio ?? null;
  const satisfaction = ratio === null ? null : Math.round(ratio * 100);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      {/* Conditional dead-letter banner */}
      {deadLetter > 0 && (
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 12,
            padding: '12px 16px',
            background: 'var(--tint-warning)',
            border: '1px solid #fde5bf',
            borderRadius: 8,
          }}
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#b45309" strokeWidth={2}>
            <path d="M10.3 3.9L1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z" />
            <line x1="12" y1="9" x2="12" y2="13" /><line x1="12" y1="17" x2="12.01" y2="17" />
          </svg>
          <div style={{ flex: 1, fontSize: 13.5, color: '#92400e' }}>
            <strong>미전송 답변 {deadLetter}건</strong> — Incoming Webhook 게시가 실패하여 Dead Letter로
            전환되었습니다.
          </div>
          <button className="btn-outline-warn" onClick={() => navigate('/chat-jobs')}>
            대화 작업에서 재시도
          </button>
        </div>
      )}

      {/* KPI cards */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(6,1fr)', gap: 16 }}>
        <Kpi label="오늘 질문 수" value={todayQ} loading={chatJobs.isLoading} sub="누적 수신 대화" />
        <Kpi
          label="답변 성공률"
          value={successRate === null ? '—' : `${successRate}%`}
          valueColor={successRate !== null && successRate >= 95 ? 'var(--success-fg)' : undefined}
          loading={chatJobs.isLoading}
          sub={`${completed} / ${todayQ}건 성공`}
        />
        <KpiGauge
          label="답변 p95"
          note="측정 데이터 없음 (health API 예정)"
        />
        <Kpi
          label="활성 Channel"
          value={
            <>
              {activeChannels}
              <span style={{ fontSize: 14, fontWeight: 600, color: 'var(--text-disabled)' }}>
                {' '}
                / {totalChannels}
              </span>
            </>
          }
          loading={channels.isLoading}
          sub={`전체 ${totalChannels}개 중 활성`}
        />
        <Kpi
          label="색인 대기 / 실패"
          onClick={() => navigate('/index-jobs')}
          value={
            <>
              {indexPending}
              <span style={{ color: 'var(--text-disabled)', fontWeight: 600 }}> / </span>
              <span style={{ color: 'var(--danger)' }}>{indexFailed}</span>
            </>
          }
          loading={indexJobs.isLoading}
          sub={
            failedDocs.length
              ? `✕ 색인 실패 문서 ${failedDocs.length}건`
              : '색인 실패 없음'
          }
          subColor={failedDocs.length ? 'var(--danger)' : undefined}
        />
        <Kpi
          label="만족률 (👍 · 24h)"
          onClick={() => navigate('/feedback')}
          value={satisfaction === null ? '—' : `${satisfaction}%`}
          loading={feedback.isLoading}
          sub={feedback.data ? `👍 ${feedback.data.up} · 👎 ${feedback.data.down}` : '피드백 없음'}
        />
      </div>

      {/* Service status strip (illustrative — no health API yet) */}
      <Surface padding="14px 16px" style={{ display: 'flex', alignItems: 'center', gap: 20, flexWrap: 'wrap' }}>
        <div style={{ fontSize: 12, color: 'var(--text-sub)', fontWeight: 700, flex: 'none' }}>서비스 상태</div>
        {SERVICES.map((s) => (
          <ServiceDot key={s.name} {...s} />
        ))}
        <span style={{ fontSize: 11, color: 'var(--text-disabled)' }}>지연시간은 예시값입니다</span>
      </Surface>

      {/* 2-column widgets */}
      <div style={{ display: 'grid', gridTemplateColumns: '1.6fr 1fr', gap: 16 }}>
        <Surface>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 10 }}>
            <div style={{ fontSize: 14, fontWeight: 700 }}>최근 24시간 질문 · 답변 추이</div>
            <div style={{ flex: 1 }} />
            <Legend color="var(--primary)" label="성공" />
            <Legend color="var(--danger)" label="실패" />
          </div>
          <svg viewBox="0 0 560 180" style={{ width: '100%', height: 180, display: 'block' }}>
            {[45, 90, 135].map((y) => (
              <line key={y} x1="0" y1={y} x2="560" y2={y} stroke="#eef0f3" strokeWidth={1} />
            ))}
            <polygon
              points="0,160 0,150 47,142 93,148 140,120 187,96 233,104 280,70 327,58 373,74 420,44 467,52 513,38 560,46 560,160"
              fill="rgba(37,99,235,.10)"
            />
            <polyline
              points="0,150 47,142 93,148 140,120 187,96 233,104 280,70 327,58 373,74 420,44 467,52 513,38 560,46"
              fill="none"
              stroke="var(--primary)"
              strokeWidth={2}
            />
            <polyline
              points="0,158 47,159 93,157 140,158 187,155 233,158 280,156 327,158 373,152 420,158 467,157 513,158 560,156"
              fill="none"
              stroke="var(--danger)"
              strokeWidth={1.5}
            />
            <text x="4" y="176" fontSize="10" fill="#9aa3af">14:00 (어제)</text>
            <text x="264" y="176" fontSize="10" fill="#9aa3af">02:00</text>
            <text x="522" y="176" fontSize="10" fill="#9aa3af">14:00</text>
          </svg>
          <div style={{ fontSize: 11, color: 'var(--text-disabled)', marginTop: 4 }}>
            추이 그래프는 예시 데이터입니다 (timeseries API 연동 예정).
          </div>
        </Surface>

        <Surface style={{ display: 'flex', flexDirection: 'column' }}>
          <div style={{ fontSize: 14, fontWeight: 700, marginBottom: 10 }}>최근 실패 이벤트</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {deadLetter > 0 && (
              <FailEvent
                dot="var(--danger)"
                title={`DEAD_LETTER · 미전송 ${deadLetter}건`}
                desc="답변 게시 실패 — 수동 재전송 대기"
                onClick={() => navigate('/chat-jobs')}
              />
            )}
            {failedDocs.slice(0, 3).map((d) => (
              <FailEvent
                key={d.id}
                dot="var(--danger)"
                title={`색인 실패 · ${d.title}`}
                desc={`상태 ${d.status} — 색인 작업에서 원인 확인`}
                onClick={() => navigate('/index-jobs')}
              />
            ))}
            {feedback.data && feedback.data.down > 0 && (
              <FailEvent
                dot="var(--warning)"
                title={`👎 피드백 ${feedback.data.down}건`}
                desc="품질 저하 여부 확인 권장"
                onClick={() => navigate('/feedback')}
              />
            )}
            {deadLetter === 0 && failedDocs.length === 0 && !(feedback.data && feedback.data.down > 0) && (
              <div style={{ fontSize: 13, color: 'var(--text-sub)', padding: '16px 4px' }}>
                최근 실패 이벤트가 없습니다.
              </div>
            )}
          </div>
        </Surface>
      </div>
    </div>
  );
}

interface KpiProps {
  label: string;
  value: ReactNode;
  sub?: ReactNode;
  subColor?: string;
  valueColor?: string;
  loading?: boolean;
  onClick?: () => void;
}

function Kpi({ label, value, sub, subColor, valueColor, loading, onClick }: KpiProps) {
  return (
    <Surface onClick={onClick} style={onClick ? { cursor: 'pointer' } : undefined}>
      <div style={{ fontSize: 12, color: 'var(--text-sub)', fontWeight: 600 }}>{label}</div>
      <div style={{ fontSize: 26, fontWeight: 800, marginTop: 6, color: valueColor }}>
        {loading ? '…' : value}
      </div>
      {sub && (
        <div style={{ fontSize: 11.5, marginTop: 4, color: subColor ?? 'var(--text-disabled)' }}>{sub}</div>
      )}
    </Surface>
  );
}

function KpiGauge({ label, note }: { label: string; note: string }) {
  return (
    <Surface>
      <div style={{ fontSize: 12, color: 'var(--text-sub)', fontWeight: 600 }}>{label}</div>
      <div style={{ fontSize: 26, fontWeight: 800, marginTop: 6, color: 'var(--text-disabled)' }}>—</div>
      <div style={{ marginTop: 6, height: 6, background: '#eef0f3', borderRadius: 3, overflow: 'hidden' }}>
        <div style={{ width: '0%', height: '100%', background: 'var(--success)' }} />
      </div>
      <div style={{ fontSize: 11, color: 'var(--text-disabled)', marginTop: 4 }}>{note}</div>
    </Surface>
  );
}

const SERVICES = [
  { name: 'chat-gateway', latency: '12ms' },
  { name: 'chat-web', latency: '6ms' },
  { name: 'rag-worker', latency: '8ms' },
  { name: 'embedding', latency: '41ms' },
  { name: 'reranker', latency: '88ms' },
  { name: 'vLLM-0', gpu: 72 },
  { name: 'vLLM-1', gpu: 65 },
  { name: 'qdrant', latency: '6ms' },
  { name: 'postgres', latency: '3ms' },
] as const;

function ServiceDot({ name, latency, gpu }: { name: string; latency?: string; gpu?: number }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
      <span style={{ width: 8, height: 8, borderRadius: '50%', background: 'var(--success)' }} />
      <span style={{ fontSize: 12.5, fontWeight: 600 }}>{name}</span>
      {gpu !== undefined ? (
        <>
          <span style={{ fontSize: 11, color: 'var(--text-disabled)' }}>GPU</span>
          <span style={{ display: 'inline-block', width: 44, height: 5, background: '#eef0f3', borderRadius: 3, overflow: 'hidden' }}>
            <span style={{ display: 'block', width: `${gpu}%`, height: '100%', background: 'var(--info)' }} />
          </span>
          <span className="mono" style={{ fontSize: 11.5, color: 'var(--text-disabled)' }}>{gpu}%</span>
        </>
      ) : (
        <span className="mono" style={{ fontSize: 11.5, color: 'var(--text-disabled)' }}>{latency}</span>
      )}
    </div>
  );
}

function Legend({ color, label }: { color: string; label: string }) {
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 11.5, color: 'var(--text-sub)' }}>
      <span style={{ width: 10, height: 3, background: color, borderRadius: 2 }} />
      {label}
    </span>
  );
}

function FailEvent({ dot, title, desc, onClick }: { dot: string; title: string; desc: string; onClick: () => void }) {
  return (
    <div
      className="nav-row-light"
      onClick={onClick}
      style={{
        display: 'flex',
        gap: 10,
        padding: '10px 12px',
        border: '1px solid var(--border)',
        borderRadius: 7,
        cursor: 'pointer',
        alignItems: 'flex-start',
      }}
    >
      <span style={{ flex: 'none', marginTop: 3, width: 8, height: 8, borderRadius: '50%', background: dot }} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 12.5, fontWeight: 700 }}>{title}</div>
        <div style={{ fontSize: 12, color: 'var(--text-sub)', marginTop: 2 }}>{desc}</div>
      </div>
    </div>
  );
}
