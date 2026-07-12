import { useMemo, useState } from 'react';
import { App, Button, Space, Switch, Table, Tag, Tooltip, Typography } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { RedoOutlined } from '@ant-design/icons';
import { PageHeader } from '../components/PageHeader';
import { QueryState, errorMessage } from '../components/QueryState';
import { useChatJobs, useRetryDelivery } from '../api/chatJobs';
import type { ChatJobView } from '../types';

const { Text } = Typography;

const DEAD_LETTER = new Set(['DEAD_LETTER', 'DEADLETTER', 'FAILED', 'DELIVERY_FAILED']);

const STATUS_COLOR: Record<string, string> = {
  QUEUED: 'default',
  RUNNING: 'processing',
  COMPLETED: 'success',
  DELIVERED: 'success',
  DELIVERY_PENDING: 'warning',
  FAILED: 'error',
  DEAD_LETTER: 'error',
};

export function ChatJobs() {
  const { message } = App.useApp();
  const jobs = useChatJobs();
  const retry = useRetryDelivery();
  const [deadOnly, setDeadOnly] = useState(false);

  const rows = useMemo(() => {
    const all = jobs.data ?? [];
    return deadOnly ? all.filter((j) => DEAD_LETTER.has((j.status ?? '').toUpperCase())) : all;
  }, [jobs.data, deadOnly]);

  const onRetry = async (id: string) => {
    try {
      await retry.mutateAsync(id);
      message.success('재발송 대기 상태로 전환했습니다.');
    } catch (e) {
      message.error(errorMessage(e));
    }
  };

  const columns: ColumnsType<ChatJobView> = [
    { title: 'Job ID', dataIndex: 'id', render: (v: string) => <code>{v.slice(0, 8)}…</code> },
    {
      title: 'Conversation',
      dataIndex: 'conversation_id',
      render: (v: string | null) => (v ? <code>{v.slice(0, 8)}…</code> : '-'),
    },
    {
      title: '상태',
      dataIndex: 'status',
      render: (v: string) => {
        const up = (v ?? '').toUpperCase();
        return (
          <Space>
            <Tag color={STATUS_COLOR[up] ?? 'default'}>{v}</Tag>
            {DEAD_LETTER.has(up) && <Tag color="volcano">Dead Letter</Tag>}
          </Space>
        );
      },
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
      title: 'Queued',
      dataIndex: 'queued_at',
      render: (v: string | null) => (v ? new Date(v).toLocaleString() : '-'),
    },
    {
      title: '완료',
      dataIndex: 'completed_at',
      render: (v: string | null) => (v ? new Date(v).toLocaleString() : '-'),
    },
    {
      title: '작업',
      key: 'actions',
      render: (_, row) => (
        <Button
          size="small"
          icon={<RedoOutlined />}
          loading={retry.isPending}
          onClick={() => onRetry(row.id)}
        >
          재발송
        </Button>
      ),
    },
  ];

  return (
    <>
      <PageHeader
        title="Chat Jobs"
        subtitle="RAG 처리 Job / Dead Letter 재시도 (FR-MM-013)"
        extra={
          <Space>
            <span>Dead Letter만 보기</span>
            <Switch checked={deadOnly} onChange={setDeadOnly} />
          </Space>
        }
      />
      <QueryState
        isLoading={jobs.isLoading}
        error={jobs.error}
        isEmpty={rows.length === 0}
        emptyText={deadOnly ? 'Dead Letter Job이 없습니다.' : 'Chat Job이 없습니다.'}
      >
        <Table rowKey="id" columns={columns} dataSource={rows} pagination={{ pageSize: 20 }} />
      </QueryState>
    </>
  );
}
