import { useState } from 'react';
import { Alert, Button, DatePicker, Form, Input, Select, Space, Table, Tag, Tooltip, Typography } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { SearchOutlined } from '@ant-design/icons';
import { PageHeader } from '../components/PageHeader';
import { QueryState } from '../components/QueryState';
import { Surface } from '../components/ui';
import { useAuditLogs, type AuditFilters } from '../api/audit';
import type { AuditLogView } from '../types';

const METHOD_COLOR: Record<string, string> = {
  POST: 'green',
  PUT: 'blue',
  PATCH: 'gold',
  DELETE: 'red',
};

const RESULT_META: Record<string, { color: string; label: string }> = {
  OK: { color: 'success', label: '성공' },
  DENIED: { color: 'warning', label: '권한 거부' },
  ERROR: { color: 'error', label: '오류' },
};

const { Text } = Typography;

function kst(iso: string | null): string {
  return iso ? new Date(iso).toLocaleString('ko-KR', { timeZone: 'Asia/Seoul' }) : '-';
}

/** status_code 외의 detail(예: DOCUMENT_ACL_UPDATE 의 before/after) — 툴팁으로 원문 표시 */
function extraDetail(d: Record<string, unknown> | null): string | null {
  if (!d) return null;
  const rest = Object.fromEntries(Object.entries(d).filter(([k]) => k !== 'status_code'));
  return Object.keys(rest).length ? JSON.stringify(rest, null, 2) : null;
}

// 필터 바 한 줄 안에서 칸이 줄바꿈되거나 폭이 들쭉날쭉하지 않게 — Form.Item 기본 여백 제거, 칸마다 폭 고정
const ITEM_STYLE = { margin: 0 };

export function AuditLogs() {
  const [filters, setFilters] = useState<AuditFilters>({});
  const logs = useAuditLogs(filters);
  const [form] = Form.useForm();

  const onSearch = (values: Record<string, unknown>) => {
    const next: AuditFilters = {
      actor: (values.actor as string) || undefined,
      action: (values.action as string) || undefined,
      method: (values.method as string) || undefined,
      result: (values.result as string) || undefined,
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
      width: 190,
      render: (v: string | null) => <Text style={{ fontSize: 12.5 }}>{kst(v)}</Text>,
    },
    { title: '행위자', dataIndex: 'actor', width: 150 },
    {
      title: '결과',
      dataIndex: 'result',
      width: 140,
      render: (v: string, r) => {
        const meta = RESULT_META[v] ?? { color: 'default', label: v };
        return (
          <Space size={4}>
            <Tag color={meta.color}>{meta.label}</Tag>
            {r.status_code != null && <Text type="secondary">{r.status_code}</Text>}
          </Space>
        );
      },
    },
    {
      title: '작업',
      key: 'action',
      render: (_, r) =>
        r.method ? (
          <Space size={6}>
            <Tag color={METHOD_COLOR[r.method] ?? 'default'}>{r.method}</Tag>
            <code>{r.path}</code>
          </Space>
        ) : (
          <Space size={6}>
            <Tag>{r.action}</Tag>
            {r.target && <code>{r.target}</code>}
          </Space>
        ),
    },
    {
      title: '상세',
      key: 'detail',
      width: 90,
      render: (_, r) => {
        const extra = extraDetail(r.detail);
        return extra ? (
          <Tooltip
            title={<pre style={{ margin: 0, fontSize: 12, whiteSpace: 'pre-wrap' }}>{extra}</pre>}
          >
            <Text underline style={{ cursor: 'help' }}>
              보기
            </Text>
          </Tooltip>
        ) : (
          <Text type="secondary">-</Text>
        );
      },
    },
  ];

  return (
    <>
      <PageHeader title="감사 로그" subtitle="관리 API 변경 이력 (FR-AUTH-005)" />
      <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
        <Surface padding="12px 16px">
          <Form
            form={form}
            onFinish={onSearch}
            style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}
          >
            <Form.Item name="actor" style={ITEM_STYLE}>
              <Input placeholder="행위자" allowClear style={{ width: 160 }} />
            </Form.Item>
            <Form.Item name="action" style={ITEM_STYLE}>
              <Input placeholder="Action / Path" allowClear style={{ width: 220 }} />
            </Form.Item>
            <Form.Item name="method" style={ITEM_STYLE}>
              <Select
                placeholder="Method: 전체"
                allowClear
                style={{ width: 150 }}
                options={Object.keys(METHOD_COLOR).map((m) => ({ label: m, value: m }))}
              />
            </Form.Item>
            <Form.Item name="result" style={ITEM_STYLE}>
              <Select
                placeholder="결과: 전체"
                allowClear
                style={{ width: 140 }}
                options={Object.entries(RESULT_META).map(([value, m]) => ({ label: m.label, value }))}
              />
            </Form.Item>
            <Form.Item name="range" style={ITEM_STYLE}>
              <DatePicker.RangePicker
                showTime={{ format: 'HH:mm' }}
                format="YYYY-MM-DD HH:mm"
                placeholder={['시작 시각', '종료 시각']}
                style={{ width: 360 }}
              />
            </Form.Item>
            <div style={{ flex: 1 }} />
            <Button
              onClick={() => {
                form.resetFields();
                setFilters({});
              }}
            >
              초기화
            </Button>
            <Button type="primary" htmlType="submit" icon={<SearchOutlined />}>
              검색
            </Button>
          </Form>
        </Surface>
        {logs.data?.truncated && (
          <Alert
            type="info"
            showIcon
            message={`조건에 맞는 기록 중 최근 ${logs.data.limit}건만 표시합니다. 기간이나 조건을 좁혀 검색하세요.`}
          />
        )}
        <QueryState
          isLoading={logs.isLoading}
          error={logs.error}
          isEmpty={(logs.data?.items.length ?? 0) === 0}
          emptyText="조건에 맞는 감사 로그가 없습니다."
        >
          <Surface padding={0} style={{ overflow: 'hidden' }}>
            <Table
              rowKey="id"
              columns={columns}
              dataSource={logs.data?.items}
              pagination={{ pageSize: 25, showTotal: (t) => `총 ${t}건` }}
              scroll={{ x: 1100 }}
            />
          </Surface>
        </QueryState>
      </div>
    </>
  );
}
