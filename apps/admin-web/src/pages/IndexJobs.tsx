import { App, Button, Progress, Segmented, Space, Table, Tag, Tooltip, Typography } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { ReloadOutlined } from '@ant-design/icons';
import { useState } from 'react';
import { PageHeader } from '../components/PageHeader';
import { QueryState, errorMessage } from '../components/QueryState';
import { useIndexJobs, useRetryIndexJob } from '../api/indexJobs';
import type { IndexJobView } from '../types';

const { Text } = Typography;

const STATUS_COLOR: Record<string, string> = {
  PENDING: 'default',
  RUNNING: 'processing',
  COMPLETED: 'success',
  FAILED: 'error',
  CANCELLED: 'warning',
};

const STATUS_LABEL: Record<string, string> = {
  PENDING: '대기',
  RUNNING: '실행 중',
  COMPLETED: '완료',
  FAILED: '실패',
  CANCELLED: '취소',
};

const STAGES = ['PARSING', 'CHUNKING', 'EMBEDDING', 'UPSERTING', 'VALIDATING'];

function kst(iso: string | null): string {
  return iso ? new Date(iso).toLocaleString('ko-KR', { timeZone: 'Asia/Seoul' }) : '-';
}

function duration(job: IndexJobView): string {
  if (!job.started_at) return '-';
  const end = job.completed_at ? new Date(job.completed_at) : new Date();
  const sec = Math.max(0, Math.round((end.getTime() - new Date(job.started_at).getTime()) / 1000));
  const text = sec < 60 ? `${sec}초` : `${Math.floor(sec / 60)}분 ${sec % 60}초`;
  return job.completed_at ? text : `${text} 경과`;
}

/** 서버 재시도 규칙과 동일: FAILED · CANCELLED · 트리거 실패로 남은 PENDING. */
function retryable(job: IndexJobView): boolean {
  if (job.status === 'FAILED' || job.status === 'CANCELLED') return true;
  return job.status === 'PENDING' && (job.error ?? '').startsWith('TRIGGER_FAILED');
}

export function IndexJobs() {
  const { message } = App.useApp();
  const [filter, setFilter] = useState<string | undefined>(undefined);
  const jobs = useIndexJobs(filter);
  const retry = useRetryIndexJob();

  const onRetry = async (id: string) => {
    try {
      const res = await retry.mutateAsync(id);
      message.success(`재시도 요청 완료 — 새 작업 ${res.index_job_id.slice(0, 8)}…`);
    } catch (e) {
      message.error(errorMessage(e));
    }
  };

  const columns: ColumnsType<IndexJobView> = [
    {
      title: '생성 시각',
      dataIndex: 'created_at',
      width: 190,
      render: (v: string | null) => <Text style={{ fontSize: 12.5 }}>{kst(v)}</Text>,
    },
    {
      title: '문서',
      dataIndex: 'document_title',
      render: (v: string, row) => (
        <Space size={6}>
          <Text strong>{v}</Text>
          <Tag>v{row.version}</Tag>
        </Space>
      ),
    },
    {
      title: '상태',
      dataIndex: 'status',
      width: 140,
      render: (v: string, row) => {
        if (row.stale) {
          return (
            <Tooltip title="오래 진행이 없습니다. 파드가 비정상 종료됐을 수 있습니다 — 문서 화면에서 재색인하면 정리됩니다.">
              <Tag color="warning">중단 의심</Tag>
            </Tooltip>
          );
        }
        if (v === 'PENDING' && row.stage === 'WAITING') {
          return (
            <Tooltip title="다른 문서 색인이 끝나기를 기다리는 중 (동시 색인 제한)">
              <Tag>대기(순서)</Tag>
            </Tooltip>
          );
        }
        return <Tag color={STATUS_COLOR[v] ?? 'default'}>{STATUS_LABEL[v] ?? v}</Tag>;
      },
    },
    {
      title: '단계',
      dataIndex: 'stage',
      width: 130,
      render: (v: string | null) =>
        v && v !== 'WAITING' ? <Tag color="blue">{v}</Tag> : <Text type="secondary">-</Text>,
    },
    {
      title: '진행률',
      dataIndex: 'progress',
      width: 170,
      render: (v: number | null, row) =>
        v === null || (row.status === 'PENDING' && !v) ? (
          <Text type="secondary">-</Text>
        ) : (
          <Progress
            percent={Math.round(v * 100)}
            size="small"
            status={row.status === 'FAILED' ? 'exception' : undefined}
          />
        ),
    },
    {
      title: '청크 / 벡터',
      key: 'counts',
      width: 120,
      render: (_, row) =>
        row.chunk_count == null ? (
          <Text type="secondary">-</Text>
        ) : (
          <Text>
            {row.chunk_count} / {row.vector_count ?? '-'}
          </Text>
        ),
    },
    {
      title: '소요 시간',
      key: 'duration',
      width: 130,
      render: (_, row) => <Text>{duration(row)}</Text>,
    },
    {
      title: '오류',
      dataIndex: 'error',
      render: (v: string | null) =>
        v ? (
          <Tooltip title={v}>
            <Text type="danger" style={{ maxWidth: 240, display: 'inline-block' }} ellipsis>
              {v}
            </Text>
          </Tooltip>
        ) : (
          <Text type="secondary">-</Text>
        ),
    },
    {
      title: '작업',
      key: 'actions',
      width: 110,
      render: (_, row) => (
        <Button
          size="small"
          icon={<ReloadOutlined />}
          disabled={!retryable(row)}
          loading={retry.isPending && retry.variables === row.id}
          onClick={() => onRetry(row.id)}
        >
          재시도
        </Button>
      ),
    },
  ];

  return (
    <>
      <PageHeader
        title="색인 작업"
        subtitle="문서 색인 Job 진행 상태 · 실패 작업 재시도 (진행 중이면 5초마다 자동 갱신)"
        extra={
          <Segmented
            value={filter ?? 'ALL'}
            onChange={(v) => setFilter(v === 'ALL' ? undefined : String(v))}
            options={[
              { label: '전체', value: 'ALL' },
              { label: '대기', value: 'PENDING' },
              { label: '실행 중', value: 'RUNNING' },
              { label: '완료', value: 'COMPLETED' },
              { label: '실패', value: 'FAILED' },
              { label: '취소', value: 'CANCELLED' },
            ]}
          />
        }
      />
      <Space direction="vertical" size="middle" style={{ width: '100%' }}>
        <Text type="secondary">단계 순서: {STAGES.join(' → ')}</Text>
        <QueryState
          isLoading={jobs.isLoading}
          error={jobs.error}
          isEmpty={(jobs.data?.length ?? 0) === 0}
          emptyText="색인 작업이 없습니다. 문서를 업로드하거나 재색인하면 생성됩니다."
        >
          <Table
            rowKey="id"
            columns={columns}
            dataSource={jobs.data}
            pagination={{ pageSize: 20 }}
            scroll={{ x: 1300 }}
          />
        </QueryState>
      </Space>
    </>
  );
}
