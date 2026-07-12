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
  SUCCEEDED: 'success',
  COMPLETED: 'success',
  FAILED: 'error',
};

const STAGES = ['PARSING', 'CHUNKING', 'EMBEDDING', 'UPSERTING', 'VALIDATING'];

export function IndexJobs() {
  const { message } = App.useApp();
  const [filter, setFilter] = useState<string | undefined>(undefined);
  const jobs = useIndexJobs(filter);
  const retry = useRetryIndexJob();

  const onRetry = async (id: string) => {
    try {
      await retry.mutateAsync(id);
      message.success('재시도 요청 완료');
    } catch (e) {
      message.error(errorMessage(e));
    }
  };

  const columns: ColumnsType<IndexJobView> = [
    {
      title: 'Job ID',
      dataIndex: 'id',
      render: (v: string) => <code>{v.slice(0, 8)}…</code>,
    },
    {
      title: '상태',
      dataIndex: 'status',
      render: (v: string) => <Tag color={STATUS_COLOR[v?.toUpperCase()] ?? 'default'}>{v}</Tag>,
    },
    {
      title: '단계(stage)',
      dataIndex: 'stage',
      render: (v: string | null) => (v ? <Tag color="blue">{v}</Tag> : <Text type="secondary">-</Text>),
    },
    {
      title: '진행률',
      dataIndex: 'progress',
      width: 200,
      render: (v: number | null | undefined) =>
        v === null || v === undefined ? (
          <Text type="secondary">-</Text>
        ) : (
          <Progress percent={Math.round(v * 100)} size="small" />
        ),
    },
    {
      title: '오류',
      dataIndex: 'error',
      render: (v: string | null) =>
        v ? (
          <Tooltip title={v}>
            <Text type="danger" style={{ maxWidth: 220, display: 'inline-block' }} ellipsis>
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
      render: (_, row) => (
        <Button
          size="small"
          icon={<ReloadOutlined />}
          loading={retry.isPending}
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
        title="Index Jobs"
        subtitle="색인 Job 진행 상태 / 재시도 (parser-indexer §7.7)"
        extra={
          <Segmented
            value={filter ?? 'ALL'}
            onChange={(v) => setFilter(v === 'ALL' ? undefined : String(v))}
            options={['ALL', 'PENDING', 'RUNNING', 'FAILED', 'SUCCEEDED']}
          />
        }
      />
      <Space direction="vertical" size="middle" style={{ width: '100%' }}>
        <Text type="secondary">
          단계 순서: {STAGES.join(' → ')}
        </Text>
        <QueryState
          isLoading={jobs.isLoading}
          error={jobs.error}
          isEmpty={(jobs.data?.length ?? 0) === 0}
          emptyText="색인 Job이 없습니다. (문서 재색인 시 생성됩니다)"
        >
          <Table
            rowKey="id"
            columns={columns}
            dataSource={jobs.data}
            pagination={{ pageSize: 20 }}
          />
        </QueryState>
      </Space>
    </>
  );
}
