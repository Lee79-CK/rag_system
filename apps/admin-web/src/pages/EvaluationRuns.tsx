import { useState } from 'react';
import { Alert, App, Button, Card, Descriptions, Drawer, Progress, Space, Table, Tag, Tooltip, Typography } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { PlayCircleOutlined } from '@ant-design/icons';
import { QueryState, errorMessage } from '../components/QueryState';
import { useEvaluationRun, useEvaluationRuns, useStartEvaluationRun } from '../api/evaluation';
import type { EvaluationMetrics, EvaluationRun, EvaluationRunResult, EvaluationRunStatus } from '../types';

const { Text, Paragraph } = Typography;

type MetricKey = 'recall_at_10' | 'citation_precision' | 'no_answer_safety' | 'answerable_answered';

/** PRD §8.1 PoC 목표 — tools/evaluation/report.py TARGETS 와 동일 */
const METRICS: { key: MetricKey; label: string; target: number | null; help: string }[] = [
  { key: 'recall_at_10', label: 'Recall@10', target: 0.85, help: '기대 문서가 검색 결과(컨텍스트 선택 청크)에 포함된 비율 — 답할 수 있는 문항' },
  { key: 'citation_precision', label: 'Citation Precision', target: 0.9, help: '답변이 인용한 문서 중 기대 문서 비율 — 인용이 있는 답할 수 있는 문항' },
  { key: 'no_answer_safety', label: '무근거 안전응답률', target: 0.9, help: '답할 수 없는 문항에서 추측 없이 근거 부족을 안내한 비율' },
  { key: 'answerable_answered', label: '근거 응답률', target: null, help: '답할 수 있는 문항에서 근거 부족이 아니라 실제로 답한 비율' },
];

const STATUS: Record<EvaluationRunStatus, { color: string; label: string }> = {
  RUNNING: { color: 'processing', label: '실행 중' },
  COMPLETED: { color: 'success', label: '완료' },
  FAILED: { color: 'error', label: '실패' },
};

const pct = (v: number) => `${Math.round(v * 1000) / 10}%`;

function MetricTag({ m, k, target }: { m: EvaluationMetrics | null; k: MetricKey; target: number | null }) {
  if (!m) return <Text type="secondary">-</Text>;
  if (m.applicable && m.applicable[k] === 0) {
    return (
      <Tooltip title="해당 유형 문항이 없어 계산하지 않았습니다">
        <Text type="secondary">해당 없음</Text>
      </Tooltip>
    );
  }
  const v = m[k];
  if (target == null) return <Text>{pct(v)}</Text>;
  return <Tag color={v >= target ? 'success' : 'error'}>{pct(v)}</Tag>;
}

/** 문항별 지표: 1 ✓ / 0 ✗ / null – */
function Mark({ v }: { v: number | null }) {
  if (v == null) return <Text type="secondary">–</Text>;
  return v >= 1 ? <Text type="success">✓</Text> : v <= 0 ? <Text type="danger">✗</Text> : <Text>{pct(v)}</Text>;
}

export function EvaluationRunsPanel({ acceptedCount }: { acceptedCount: number }) {
  const { message } = App.useApp();
  const runs = useEvaluationRuns();
  const start = useStartEvaluationRun();
  const [openId, setOpenId] = useState<string | null>(null);
  const running = runs.data?.some((r) => r.status === 'RUNNING') ?? false;

  const onStart = async () => {
    try {
      await start.mutateAsync();
      message.success(`평가를 시작했습니다 (${acceptedCount}문항). 문항당 수십 초가 걸릴 수 있습니다.`);
    } catch (e) {
      message.error(errorMessage(e));
    }
  };

  const cols: ColumnsType<EvaluationRun> = [
    {
      title: '상태',
      key: 'status',
      width: 190,
      render: (_, r) => (
        <Space direction="vertical" size={2} style={{ width: '100%' }}>
          <Tag color={STATUS[r.status].color}>{STATUS[r.status].label}</Tag>
          {r.status === 'RUNNING' ? (
            <Progress percent={r.total ? Math.round((r.done / r.total) * 100) : 0} size="small" format={() => `${r.done}/${r.total}`} />
          ) : (
            <Text type="secondary" style={{ fontSize: 12 }}>
              {r.done}/{r.total}문항
            </Text>
          )}
        </Space>
      ),
    },
    ...METRICS.map((mt) => ({
      title: (
        <Tooltip title={`${mt.help}${mt.target != null ? ` · 목표 ${pct(mt.target)}` : ''}`}>
          {mt.label}
        </Tooltip>
      ),
      key: mt.key,
      render: (_: unknown, r: EvaluationRun) => <MetricTag m={r.metrics} k={mt.key} target={mt.target} />,
    })),
    {
      title: '실행',
      key: 'by',
      width: 190,
      render: (_, r) => (
        <Text type="secondary" style={{ fontSize: 12 }}>
          {r.started_by} · {r.created_at ? new Date(r.created_at).toLocaleString() : ''}
        </Text>
      ),
    },
  ];

  return (
    <Card
      size="small"
      extra={
        <Button
          type="primary"
          icon={<PlayCircleOutlined />}
          disabled={acceptedCount === 0 || running}
          loading={start.isPending}
          onClick={onStart}
        >
          {running ? '평가 실행 중…' : `평가 실행 (채택 ${acceptedCount}문항)`}
        </Button>
      }
    >
      {acceptedCount === 0 && (
        <Alert style={{ marginBottom: 12 }} type="warning" showIcon message="채택된 평가셋 후보가 없습니다. [평가셋 후보] 탭에서 후보를 채택하세요." />
      )}
      <QueryState
        isLoading={runs.isLoading}
        error={runs.error}
        isEmpty={(runs.data?.length ?? 0) === 0}
        emptyText="실행 결과가 없습니다."
      >
        <Table
          rowKey="id"
          size="small"
          columns={cols}
          dataSource={runs.data}
          pagination={{ pageSize: 20 }}
          onRow={(r) => ({ onClick: () => setOpenId(r.id), style: { cursor: 'pointer' } })}
        />
      </QueryState>
      <RunDrawer id={openId} onClose={() => setOpenId(null)} />
    </Card>
  );
}

function RunDrawer({ id, onClose }: { id: string | null; onClose: () => void }) {
  const run = useEvaluationRun(id);
  const r = run.data;

  const cols: ColumnsType<EvaluationRunResult> = [
    { title: '#', dataIndex: 'seq', width: 44, align: 'right' },
    {
      title: '질문',
      key: 'q',
      render: (_, x) => (
        <Space direction="vertical" size={2}>
          <Text>{x.question}</Text>
          <Space size={4} wrap>
            <Tag>{x.case_type}</Tag>
            {!x.answerable && <Tag color="purple">답할 수 없는 문항</Tag>}
            {x.insufficient_evidence && <Tag color="orange">근거 부족 응답</Tag>}
            {x.error && <Tag color="error">오류</Tag>}
          </Space>
        </Space>
      ),
    },
    ...METRICS.map((mt) => ({
      title: mt.label,
      key: mt.key,
      width: 96,
      align: 'center' as const,
      render: (_: unknown, x: EvaluationRunResult) => (
        <Mark v={mt.key === 'no_answer_safety' ? x.no_answer_safe : x[mt.key]} />
      ),
    })),
    {
      title: '응답',
      dataIndex: 'latency_ms',
      width: 72,
      align: 'right',
      render: (v: number | null) => (v == null ? '-' : `${(v / 1000).toFixed(1)}s`),
    },
  ];

  return (
    <Drawer title="평가 실행 결과" width={1100} open={!!id} onClose={onClose} destroyOnClose>
      <QueryState isLoading={run.isLoading} error={run.error} isEmpty={!r}>
        {r && (
          <>
            <Descriptions size="small" column={3} bordered style={{ marginBottom: 16 }}>
              <Descriptions.Item label="상태">
                <Tag color={STATUS[r.status].color}>{STATUS[r.status].label}</Tag> {r.done}/{r.total}문항
              </Descriptions.Item>
              <Descriptions.Item label="실행">{r.started_by}</Descriptions.Item>
              <Descriptions.Item label="시각">{r.created_at ? new Date(r.created_at).toLocaleString() : '-'}</Descriptions.Item>
              {METRICS.map((mt) => (
                <Descriptions.Item key={mt.key} label={mt.target != null ? `${mt.label} (목표 ${pct(mt.target)})` : mt.label}>
                  <MetricTag m={r.metrics} k={mt.key} target={mt.target} />
                </Descriptions.Item>
              ))}
              {r.error && (
                <Descriptions.Item label="오류" span={3}>
                  <Text type="danger">{r.error}</Text>
                </Descriptions.Item>
              )}
            </Descriptions>
            <Table
              rowKey="seq"
              size="small"
              columns={cols}
              dataSource={r.results}
              pagination={false}
              expandable={{
                expandedRowRender: (x) => (
                  <Descriptions size="small" column={1}>
                    <Descriptions.Item label="기대 문서">{x.expected_documents.map((d) => <Tag key={d}>{d}</Tag>)}</Descriptions.Item>
                    <Descriptions.Item label="검색 문서">{x.retrieved.length ? x.retrieved.map((d, i) => <Tag key={`${d}-${i}`}>{d}</Tag>) : '-'}</Descriptions.Item>
                    <Descriptions.Item label="인용 문서">{x.citations.length ? x.citations.map((d, i) => <Tag key={`${d}-${i}`}>{d}</Tag>) : '-'}</Descriptions.Item>
                    <Descriptions.Item label="답변">
                      <Paragraph style={{ margin: 0, whiteSpace: 'pre-wrap' }} ellipsis={{ rows: 6, expandable: true }}>
                        {x.answer || '-'}
                      </Paragraph>
                    </Descriptions.Item>
                    {x.error && (
                      <Descriptions.Item label="오류">
                        <Text type="danger">{x.error}</Text>
                      </Descriptions.Item>
                    )}
                  </Descriptions>
                ),
              }}
            />
          </>
        )}
      </QueryState>
    </Drawer>
  );
}
