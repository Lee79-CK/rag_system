import { Alert, Card, Col, Row, Table, Tag, Typography } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { Link } from 'react-router-dom';
import { PageHeader } from '../components/PageHeader';
import { QueryState } from '../components/QueryState';
import { useEvaluationDatasets, useEvaluationRuns } from '../api/evaluation';
import type { EvaluationDataset, EvaluationRun } from '../types';

const { Text } = Typography;

export function Evaluation() {
  const datasets = useEvaluationDatasets();
  const runs = useEvaluationRuns();

  const datasetCols: ColumnsType<EvaluationDataset> = [
    { title: '이름', dataIndex: 'name' },
    { title: '문항 수', dataIndex: 'item_count', render: (v) => v ?? '-' },
    {
      title: '생성일',
      dataIndex: 'created_at',
      render: (v: string | null) => (v ? new Date(v).toLocaleString() : '-'),
    },
  ];

  const runCols: ColumnsType<EvaluationRun> = [
    { title: 'Run', dataIndex: 'id', render: (v: string) => <code>{v.slice(0, 8)}…</code> },
    {
      title: '상태',
      dataIndex: 'status',
      render: (v: string | undefined) => <Tag>{v ?? '-'}</Tag>,
    },
    {
      title: 'Recall@10',
      dataIndex: 'recall_at_10',
      render: (v: number | null | undefined) => (v == null ? '-' : v.toFixed(3)),
    },
    {
      title: 'Faithfulness',
      dataIndex: 'faithfulness',
      render: (v: number | null | undefined) => (v == null ? '-' : v.toFixed(3)),
    },
    {
      title: '실행일',
      dataIndex: 'created_at',
      render: (v: string | null | undefined) => (v ? new Date(v).toLocaleString() : '-'),
    },
  ];

  return (
    <>
      <PageHeader title="Evaluation" subtitle="품질 평가 데이터셋 / 실행 결과 (§13)" />
      <Alert
        style={{ marginBottom: 16 }}
        type="info"
        showIcon
        message="평가셋 후보 승격"
        description={
          <Text>
            👎 답변을 평가 데이터셋 후보(§13.3)로 승격하는 작업은{' '}
            <Link to="/feedback">Feedback Dashboard</Link>의 👎 목록에서 수행합니다.
          </Text>
        }
      />
      <Row gutter={[16, 16]}>
        <Col xs={24} lg={12}>
          <Card title="데이터셋" size="small">
            <QueryState
              isLoading={datasets.isLoading}
              error={datasets.error}
              isEmpty={(datasets.data?.length ?? 0) === 0}
              emptyText="데이터셋이 없습니다."
            >
              <Table
                rowKey="id"
                size="small"
                columns={datasetCols}
                dataSource={datasets.data}
                pagination={false}
              />
            </QueryState>
          </Card>
        </Col>
        <Col xs={24} lg={12}>
          <Card title="실행 결과" size="small">
            <QueryState
              isLoading={runs.isLoading}
              error={runs.error}
              isEmpty={(runs.data?.length ?? 0) === 0}
              emptyText="실행 결과가 없습니다."
            >
              <Table
                rowKey="id"
                size="small"
                columns={runCols}
                dataSource={runs.data}
                pagination={false}
              />
            </QueryState>
          </Card>
        </Col>
      </Row>
    </>
  );
}
