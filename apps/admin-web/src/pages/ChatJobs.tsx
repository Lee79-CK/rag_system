import { useMemo, useState } from 'react';
import { Space, Switch, Table, Tag, Tooltip, Typography } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { PageHeader } from '../components/PageHeader';
import { QueryState } from '../components/QueryState';
import { useChatJobs } from '../api/chatJobs';
import type { ChatJobView } from '../types';

const { Text } = Typography;

// FAILED: 파이프라인/큐 실패 · DELIVERY_FAILED: 답변 생성 후 Bot Post 갱신/emit 실패 (채널 재조회 시 DB 기준 수렴)
const DEAD_LETTER = new Set(['FAILED', 'DELIVERY_FAILED']);

const STATUS_COLOR: Record<string, string> = {
  QUEUED: 'default',
  RUNNING: 'processing',
  COMPLETED: 'success',
  DELIVERY_FAILED: 'warning',
  FAILED: 'error',
};

export function ChatJobs() {
  const jobs = useChatJobs();
  const [deadOnly, setDeadOnly] = useState(false);

  const rows = useMemo(() => {
    const all = jobs.data ?? [];
    return deadOnly ? all.filter((j) => DEAD_LETTER.has((j.status ?? '').toUpperCase())) : all;
  }, [jobs.data, deadOnly]);

  const columns: ColumnsType<ChatJobView> = [
    { title: 'Job ID', dataIndex: 'id', render: (v: string) => <code>{v.slice(0, 8)}…</code> },
    {
      title: '질문 / 답변 Post',
      key: 'posts',
      render: (_, r) => (
        <span>
          <code>{r.post_id ? `${r.post_id.slice(0, 8)}…` : '-'}</code> → <code>{r.bot_post_id ? `${r.bot_post_id.slice(0, 8)}…` : '-'}</code>
        </span>
      ),
    },
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
            {DEAD_LETTER.has(up) && <Tag color="volcano">확인 필요</Tag>}
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
  ];

  return (
    <>
      <PageHeader
        title="Chat Jobs"
        subtitle="RAG 처리 Job 상태 (Web Chat 질문 → Bot 답변 스트리밍)"
        extra={
          <Space>
            <span>실패만 보기</span>
            <Switch checked={deadOnly} onChange={setDeadOnly} />
          </Space>
        }
      />
      <QueryState
        isLoading={jobs.isLoading}
        error={jobs.error}
        isEmpty={rows.length === 0}
        emptyText={deadOnly ? '실패한 Job이 없습니다.' : 'Chat Job이 없습니다.'}
      >
        <Table rowKey="id" columns={columns} dataSource={rows} pagination={{ pageSize: 20 }} />
      </QueryState>
    </>
  );
}
