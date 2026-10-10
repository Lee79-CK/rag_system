import { useEffect, useMemo, useState } from 'react';
import {
  Alert,
  App,
  Button,
  Descriptions,
  Drawer,
  Empty,
  Input,
  InputNumber,
  Segmented,
  Select,
  Space,
  Spin,
  Switch,
  Table,
  Tag,
  Tooltip,
  Typography,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { CopyOutlined, ReloadOutlined } from '@ant-design/icons';
import { PageHeader } from '../components/PageHeader';
import { QueryState, errorMessage } from '../components/QueryState';
import { useErrorEvents, useErrorLogs } from '../api/errors';
import type { ErrorLogParams } from '../api/errors';
import type { ErrorEventView, ErrorSource, PodLogLine } from '../types';

const { Text } = Typography;

const SOURCE_LABEL: Record<ErrorSource, string> = { chat: '대화', index: '색인', admin: '관리 API' };
const SOURCE_COLOR: Record<ErrorSource, string> = { chat: 'volcano', index: 'gold', admin: 'blue' };
const STATUS_COLOR: Record<string, string> = {
  FAILED: 'error',
  DELIVERY_FAILED: 'warning',
  PENDING: 'warning',
  ERROR: 'error',
  DENIED: 'default',
};
const HOURS_OPTIONS = [
  { label: '1시간', value: 1 },
  { label: '24시간', value: 24 },
  { label: '7일', value: 24 * 7 },
];

function kst(iso: string | null): string {
  return iso ? new Date(iso).toLocaleString('ko-KR', { timeZone: 'Asia/Seoul' }) : '-';
}

/**
 * 시스템 › 오류 로그 (SYS_ADMIN, FR-OPS-011).
 * DB 에 기록된 오류(대화 작업·색인 작업·관리 API)를 모아 보고, 항목을 열면 그 시각 전후의
 * 관련 서비스 파드 로그(서버 allowlist·마스킹 적용)를 kubectl 없이 확인한다.
 */
export function ErrorLogs() {
  const [source, setSource] = useState<ErrorSource | 'all'>('all');
  const [hours, setHours] = useState(24);
  const [q, setQ] = useState('');
  const [autoRefresh, setAutoRefresh] = useState(false);
  const [selected, setSelected] = useState<ErrorEventView | undefined>();

  const events = useErrorEvents(
    { source: source === 'all' ? undefined : source, hours },
    autoRefresh ? 30_000 : undefined,
  );

  const rows = useMemo(() => {
    const items = events.data?.items ?? [];
    const k = q.trim().toLowerCase();
    return k
      ? items.filter((i) => `${i.summary} ${i.error ?? ''} ${i.service}`.toLowerCase().includes(k))
      : items;
  }, [events.data, q]);

  const columns: ColumnsType<ErrorEventView> = [
    {
      title: '시각 (KST)',
      dataIndex: 'occurred_at',
      width: 180,
      render: (v: string | null) => <Text style={{ fontSize: 12.5 }}>{kst(v)}</Text>,
    },
    {
      title: '출처',
      dataIndex: 'source',
      width: 90,
      render: (v: ErrorSource) => <Tag color={SOURCE_COLOR[v]}>{SOURCE_LABEL[v]}</Tag>,
    },
    {
      title: '상태',
      dataIndex: 'status',
      width: 140,
      render: (v: string) => <Tag color={STATUS_COLOR[v] ?? 'default'}>{v}</Tag>,
    },
    {
      title: '요약',
      dataIndex: 'summary',
      render: (v: string) => (
        <Text style={{ maxWidth: 320, display: 'inline-block' }} ellipsis={{ tooltip: v }}>
          {v}
        </Text>
      ),
    },
    {
      title: '오류',
      dataIndex: 'error',
      render: (v: string | null) =>
        v ? (
          <Tooltip title={v}>
            <Text type="danger" style={{ maxWidth: 340, display: 'inline-block' }} ellipsis>
              {v}
            </Text>
          </Tooltip>
        ) : (
          <Text type="secondary">-</Text>
        ),
    },
    { title: '관련 서비스', dataIndex: 'service', width: 130, render: (v: string) => <code>{v}</code> },
  ];

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <PageHeader
        title="오류 로그"
        subtitle="대화 답변 실패 · 색인 실패 · 관리 API 오류를 모아 봅니다. 항목을 누르면 그 시각 전후의 관련 서비스 로그를 확인할 수 있습니다."
        extra={
          <Space wrap>
            <Segmented
              value={source}
              onChange={(v) => setSource(v as ErrorSource | 'all')}
              options={[
                { label: '전체', value: 'all' },
                { label: '대화', value: 'chat' },
                { label: '색인', value: 'index' },
                { label: '관리 API', value: 'admin' },
              ]}
            />
            <Select value={hours} onChange={setHours} options={HOURS_OPTIONS} style={{ width: 100 }} />
            <Input
              placeholder="채널·문서·오류 검색"
              allowClear
              value={q}
              onChange={(e) => setQ(e.target.value)}
              style={{ width: 200 }}
            />
            <Tooltip title="자동갱신 30초">
              <Switch checked={autoRefresh} onChange={setAutoRefresh} size="small" />
            </Tooltip>
            <Button icon={<ReloadOutlined />} onClick={() => events.refetch()} />
          </Space>
        }
      />

      <QueryState
        isLoading={events.isLoading}
        error={events.error}
        isEmpty={rows.length === 0}
        emptyText="선택한 기간에 기록된 오류가 없습니다."
      >
        <Table
          rowKey="id"
          size="middle"
          columns={columns}
          dataSource={rows}
          pagination={{ pageSize: 20, showTotal: (t) => `총 ${t}건` }}
          onRow={(r) => ({ onClick: () => setSelected(r), style: { cursor: 'pointer' } })}
        />
      </QueryState>

      <ErrorDetail
        event={selected}
        services={events.data?.services ?? []}
        onClose={() => setSelected(undefined)}
      />
    </div>
  );
}

function ErrorDetail({
  event,
  services,
  onClose,
}: {
  event?: ErrorEventView;
  services: string[];
  onClose: () => void;
}) {
  const { message } = App.useApp();
  const [service, setService] = useState<string>('');
  const [beforeMin, setBeforeMin] = useState(5);
  const [afterMin, setAfterMin] = useState(2);
  const [params, setParams] = useState<ErrorLogParams | null>(null);
  const logs = useErrorLogs(params);

  useEffect(() => {
    setService(event?.service ?? '');
    setParams(null);
  }, [event]);

  const canFetch = !!event?.occurred_at && !!service && (service !== 'parser-indexer' || event.source === 'index');

  const fetchLogs = () => {
    if (!event?.occurred_at) return;
    setParams({
      service,
      at: event.occurred_at,
      before_min: beforeMin,
      after_min: afterMin,
      index_job_id: service === 'parser-indexer' ? event.ref_id : undefined,
    });
  };

  const copy = async (text: string) => {
    try {
      await navigator.clipboard.writeText(text);
      message.success('복사됨');
    } catch {
      message.error('복사 실패');
    }
  };

  return (
    <Drawer title="오류 상세" width={960} open={!!event} onClose={onClose} destroyOnClose>
      {event && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <Descriptions column={2} bordered size="small">
            <Descriptions.Item label="시각 (KST)">{kst(event.occurred_at)}</Descriptions.Item>
            <Descriptions.Item label="출처 / 상태">
              <Space>
                <Tag color={SOURCE_COLOR[event.source]}>{SOURCE_LABEL[event.source]}</Tag>
                <Tag color={STATUS_COLOR[event.status] ?? 'default'}>{event.status}</Tag>
              </Space>
            </Descriptions.Item>
            <Descriptions.Item label="요약" span={2}>
              {event.summary}
            </Descriptions.Item>
            {Object.entries(event.context)
              .filter(([, v]) => v !== null && v !== '')
              .map(([k, v]) => (
                <Descriptions.Item key={k} label={k}>
                  {String(v)}
                </Descriptions.Item>
              ))}
            <Descriptions.Item label="ID" span={2}>
              <code>{event.ref_id}</code>
            </Descriptions.Item>
          </Descriptions>

          <div>
            <Space style={{ marginBottom: 6 }}>
              <Text strong>오류 내용</Text>
              {event.error && (
                <Button size="small" icon={<CopyOutlined />} onClick={() => copy(event.error ?? '')} />
              )}
            </Space>
            <pre className="mono" style={preStyle}>
              {event.error ?? '(오류 메시지 없음)'}
            </pre>
          </div>

          <div>
            <Text strong>관련 로그</Text>
            <Space wrap style={{ display: 'flex', margin: '8px 0' }}>
              <Select
                value={service}
                onChange={setService}
                style={{ width: 180 }}
                options={services.map((s) => ({ label: s, value: s }))}
              />
              <Space size={4}>
                <Text type="secondary">전</Text>
                <InputNumber min={0} max={60} value={beforeMin} onChange={(v) => setBeforeMin(v ?? 5)} style={{ width: 64 }} />
                <Text type="secondary">분 ~ 후</Text>
                <InputNumber min={0} max={60} value={afterMin} onChange={(v) => setAfterMin(v ?? 2)} style={{ width: 64 }} />
                <Text type="secondary">분</Text>
              </Space>
              <Button type="primary" disabled={!canFetch} loading={logs.isFetching} onClick={fetchLogs}>
                로그 조회
              </Button>
            </Space>
            {service === 'parser-indexer' && event.source !== 'index' && (
              <Text type="secondary">색인 로그는 색인 오류 항목에서만 조회할 수 있습니다.</Text>
            )}
            <LogResult params={params} logs={logs} onCopy={copy} />
          </div>
        </div>
      )}
    </Drawer>
  );
}

function LogResult({
  params,
  logs,
  onCopy,
}: {
  params: ErrorLogParams | null;
  logs: ReturnType<typeof useErrorLogs>;
  onCopy: (text: string) => void;
}) {
  if (!params) {
    return (
      <Text type="secondary">
        서비스와 시간 범위를 확인하고 [로그 조회] 를 누르세요. 추정 서비스는 오류 메시지의 대상 주소로 정합니다.
      </Text>
    );
  }
  if (logs.isFetching && !logs.data) return <Spin />;
  if (logs.error) {
    return (
      <Alert
        type="warning"
        showIcon
        message="로그를 가져오지 못했습니다"
        description={
          <>
            <div>{errorMessage(logs.error)}</div>
            <div style={{ marginTop: 4 }}>
              대안: <code>kubectl -n &lt;namespace&gt; logs -l app.kubernetes.io/name={params.service} --since=30m</code>
            </div>
          </>
        }
      />
    );
  }
  const data = logs.data;
  if (!data) return null;
  if (data.pods.length === 0) {
    return <Empty description={data.reason ?? '대상 Pod 가 없습니다.'} />;
  }
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <Text type="secondary" style={{ fontSize: 12 }}>
        {data.namespace} · {kst(data.since)} ~ {kst(data.until)} · 비밀값은 마스킹되어 표시됩니다
      </Text>
      {data.pods.map((p) => (
        <div key={`${p.pod}-${p.previous}`}>
          <Space style={{ marginBottom: 4 }}>
            <code>{p.pod}</code>
            {p.previous && <Tag color="orange">재시작 이전 컨테이너</Tag>}
            {p.truncated && <Tag>일부만 표시</Tag>}
            <Text type="secondary">{p.lines.length}줄</Text>
            <Button
              size="small"
              icon={<CopyOutlined />}
              onClick={() => onCopy(p.lines.map((l) => `${l.ts ?? ''} ${l.text}`).join('\n'))}
            />
          </Space>
          <pre className="mono" style={{ ...preStyle, maxHeight: 420 }}>
            {p.lines.length === 0 ? '(해당 시간 범위에 로그 없음)' : p.lines.map((l, i) => <LogRow key={i} line={l} />)}
          </pre>
        </div>
      ))}
    </div>
  );
}

const ERROR_LINE = /(Traceback|Error|Exception|"level":\s*"(error|critical)"|\bERROR\b|Timeout)/;

function LogRow({ line }: { line: PodLogLine }) {
  const isError = ERROR_LINE.test(line.text);
  const time = line.ts ? new Date(line.ts).toLocaleTimeString('ko-KR', { timeZone: 'Asia/Seoul' }) : '';
  return (
    <div style={{ color: isError ? '#dc2626' : undefined, whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>
      {time && <span style={{ color: '#94a3b8', marginRight: 8 }}>{time}</span>}
      {line.text}
    </div>
  );
}

const preStyle: React.CSSProperties = {
  margin: 0,
  padding: 12,
  background: 'var(--tint-neutral, #f6f7f9)',
  border: '1px solid var(--border, #e3e6ea)',
  borderRadius: 6,
  fontSize: 12,
  lineHeight: 1.55,
  overflow: 'auto',
  maxHeight: 200,
  whiteSpace: 'pre-wrap',
  wordBreak: 'break-all',
};
