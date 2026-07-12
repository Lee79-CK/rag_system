import { useState } from 'react';
import { Button, DatePicker, Form, Input, Space, Table, Tag } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { SearchOutlined } from '@ant-design/icons';
import { PageHeader } from '../components/PageHeader';
import { QueryState } from '../components/QueryState';
import { useAuditLogs, type AuditFilters } from '../api/audit';
import type { AuditLogView } from '../types';

const METHOD_COLOR: Record<string, string> = {
  POST: 'green',
  PUT: 'blue',
  PATCH: 'gold',
  DELETE: 'red',
};

export function AuditLogs() {
  const [filters, setFilters] = useState<AuditFilters>({});
  const logs = useAuditLogs(filters);
  const [form] = Form.useForm();

  const onSearch = (values: Record<string, unknown>) => {
    const next: AuditFilters = {
      actor: (values.actor as string) || undefined,
      action: (values.action as string) || undefined,
      method: (values.method as string) || undefined,
    };
    const range = values.range as [{ toISOString(): string }, { toISOString(): string }] | undefined;
    if (range && range.length === 2) {
      next.from = range[0].toISOString();
      next.to = range[1].toISOString();
    }
    setFilters(next);
  };

  const columns: ColumnsType<AuditLogView> = [
    {
      title: '시각',
      dataIndex: 'created_at',
      render: (v: string | null | undefined) => (v ? new Date(v).toLocaleString() : '-'),
    },
    {
      title: '행위자',
      key: 'actor',
      render: (_, r) => r.actor_login_id ?? r.actor ?? '-',
    },
    {
      title: 'Method',
      dataIndex: 'method',
      render: (v: string | null | undefined) =>
        v ? <Tag color={METHOD_COLOR[v] ?? 'default'}>{v}</Tag> : '-',
    },
    { title: 'Path', dataIndex: 'path', render: (v) => (v ? <code>{v}</code> : '-') },
    { title: 'Action', dataIndex: 'action', render: (v) => v ?? '-' },
    { title: 'Target', dataIndex: 'target', render: (v) => (v ? <code>{v}</code> : '-') },
    {
      title: 'Status',
      dataIndex: 'status_code',
      render: (v: number | null | undefined) =>
        v == null ? '-' : <Tag color={v >= 400 ? 'error' : 'success'}>{v}</Tag>,
    },
  ];

  return (
    <>
      <PageHeader title="Audit Logs" subtitle="변경 이력 감사 로그 (FR-AUTH-005)" />
      <Form form={form} layout="inline" onFinish={onSearch} style={{ marginBottom: 16 }}>
        <Form.Item name="actor">
          <Input placeholder="행위자" allowClear />
        </Form.Item>
        <Form.Item name="action">
          <Input placeholder="action" allowClear />
        </Form.Item>
        <Form.Item name="method">
          <Input placeholder="method (POST/PUT/...)" allowClear />
        </Form.Item>
        <Form.Item name="range">
          <DatePicker.RangePicker showTime />
        </Form.Item>
        <Form.Item>
          <Space>
            <Button type="primary" htmlType="submit" icon={<SearchOutlined />}>
              검색
            </Button>
            <Button
              onClick={() => {
                form.resetFields();
                setFilters({});
              }}
            >
              초기화
            </Button>
          </Space>
        </Form.Item>
      </Form>
      <QueryState
        isLoading={logs.isLoading}
        error={logs.error}
        isEmpty={(logs.data?.length ?? 0) === 0}
        emptyText="감사 로그가 없습니다."
      >
        <Table
          rowKey="id"
          columns={columns}
          dataSource={logs.data}
          pagination={{ pageSize: 25 }}
        />
      </QueryState>
    </>
  );
}
