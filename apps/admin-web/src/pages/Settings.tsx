import { useMemo } from 'react';
import { App, Button, Form, Input, InputNumber, Space, Table, Tag, Typography } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { SaveOutlined } from '@ant-design/icons';
import { PageHeader } from '../components/PageHeader';
import { QueryState, errorMessage } from '../components/QueryState';
import { useSettings, useUpdateSetting } from '../api/settings';
import type { SettingView } from '../types';

const { Text } = Typography;

/** Well-known operational tuning keys (docs/TDD.md §5.1 / §10). Shown even if unset. */
const KNOWN_NUMERIC_KEYS = [
  'VECTOR_TOP_K',
  'RERANK_TOP_N',
  'SIMILARITY_THRESHOLD',
  'RERANK_SCORE_THRESHOLD',
  'CHUNK_SIZE',
  'CHUNK_OVERLAP',
  'HISTORY_TURNS',
  'SAFETY_MARGIN_TOKENS',
];

interface Row extends SettingView {
  known: boolean;
}

export function Settings() {
  const { message } = App.useApp();
  const settings = useSettings();
  const update = useUpdateSetting();

  const rows = useMemo<Row[]>(() => {
    const map = new Map<string, Row>();
    for (const key of KNOWN_NUMERIC_KEYS) {
      map.set(key, { key, value: null, version: 0, updated_by: null, updated_at: null, known: true });
    }
    for (const s of settings.data ?? []) {
      map.set(s.key, { ...s, known: KNOWN_NUMERIC_KEYS.includes(s.key) });
    }
    return [...map.values()].sort((a, b) => a.key.localeCompare(b.key));
  }, [settings.data]);

  const save = async (key: string, raw: unknown) => {
    // numeric keys → number; else attempt JSON, fall back to string.
    let value: unknown = raw;
    if (KNOWN_NUMERIC_KEYS.includes(key)) {
      value = typeof raw === 'number' ? raw : Number(raw);
      if (Number.isNaN(value)) {
        message.error('숫자 값을 입력하세요.');
        return;
      }
    } else if (typeof raw === 'string') {
      try {
        value = JSON.parse(raw);
      } catch {
        value = raw;
      }
    }
    try {
      await update.mutateAsync({ key, value });
      message.success(`${key} 저장 완료`);
    } catch (e) {
      message.error(errorMessage(e));
    }
  };

  const columns: ColumnsType<Row> = [
    {
      title: 'Key',
      dataIndex: 'key',
      render: (v: string, row) => (
        <Space>
          <code>{v}</code>
          {row.known && <Tag color="geekblue">tuning</Tag>}
        </Space>
      ),
    },
    {
      title: '값',
      key: 'value',
      render: (_, row) => <EditableValue row={row} onSave={save} saving={update.isPending} />,
    },
    { title: 'ver', dataIndex: 'version', width: 60 },
    {
      title: '수정',
      dataIndex: 'updated_at',
      render: (v: string | null) => (v ? new Date(v).toLocaleString() : <Text type="secondary">-</Text>),
    },
  ];

  return (
    <>
      <PageHeader
        title="Settings"
        subtitle="RAG 검색/색인 튜닝 파라미터 (FR-OPS-004). 변경은 audit_logs에 기록됩니다."
      />
      <QueryState isLoading={settings.isLoading} error={settings.error} isEmpty={false}>
        <Table rowKey="key" columns={columns} dataSource={rows} pagination={false} />
      </QueryState>
    </>
  );
}

function EditableValue({
  row,
  onSave,
  saving,
}: {
  row: Row;
  onSave: (key: string, value: unknown) => void;
  saving: boolean;
}) {
  const [form] = Form.useForm();
  const isNumeric = row.known;
  const initial = isNumeric
    ? typeof row.value === 'number'
      ? row.value
      : undefined
    : row.value === null || row.value === undefined
      ? ''
      : typeof row.value === 'string'
        ? row.value
        : JSON.stringify(row.value);

  return (
    <Form
      form={form}
      layout="inline"
      initialValues={{ v: initial }}
      onFinish={(values) => onSave(row.key, values.v)}
    >
      <Form.Item name="v" style={{ marginBottom: 0, flex: 1 }}>
        {isNumeric ? (
          <InputNumber style={{ width: 200 }} placeholder="숫자" step={0.01} />
        ) : (
          <Input style={{ width: 280 }} placeholder="문자열 또는 JSON" />
        )}
      </Form.Item>
      <Form.Item style={{ marginBottom: 0 }}>
        <Button size="small" icon={<SaveOutlined />} htmlType="submit" loading={saving}>
          저장
        </Button>
      </Form.Item>
    </Form>
  );
}
