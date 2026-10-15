import { useEffect, useState } from 'react';
import {
  Alert,
  App,
  Button,
  Card,
  Descriptions,
  Drawer,
  Form,
  Input,
  Segmented,
  Select,
  Space,
  Switch,
  Table,
  Tabs,
  Tag,
  Typography,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { DownloadOutlined } from '@ant-design/icons';
import { Link, useSearchParams } from 'react-router-dom';
import { PageHeader } from '../components/PageHeader';
import { QueryState, errorMessage } from '../components/QueryState';
import { useChannels } from '../api/channels';
import {
  CANDIDATE_STATUS_LABEL,
  downloadCandidatesYaml,
  useEvaluationCandidates,
  useUpdateCandidate,
} from '../api/evaluation';
import { EvaluationRunsPanel } from './EvaluationRuns';
import type { CandidateStatus, CandidateUpdate, EvalCaseType, EvaluationCandidate } from '../types';

const { Text, Paragraph } = Typography;

const STATUS_COLOR: Record<CandidateStatus, string> = { PENDING: 'gold', ACCEPTED: 'green', REJECTED: 'default' };

/** tools/evaluation CaseType (§13.3) */
const CASE_TYPES: { value: EvalCaseType; label: string }[] = [
  { value: 'single_doc', label: '단일 문서' },
  { value: 'multi_doc', label: '복수 문서' },
  { value: 'table', label: '표' },
  { value: 'definition', label: '정의' },
  { value: 'no_answer', label: '답 없음' },
  { value: 'ambiguous', label: '모호한 질문' },
];
const caseTypeLabel = (v: EvalCaseType) => CASE_TYPES.find((t) => t.value === v)?.label ?? v;

type Filter = 'ALL' | CandidateStatus;

/**
 * 품질 평가 — 👎 답변에서 승격한 평가셋 후보를 검토(정답 요지·기대 문서 입력 → 채택/제외)하고,
 * 채택 문항을 `tools/evaluation` runner 데이터셋 YAML(§13.3)로 내보낸다. 평가 실행은 `make evaluate`.
 */
export function Evaluation() {
  const { message } = App.useApp();
  const [filter, setFilter] = useState<Filter>('PENDING');
  const candidates = useEvaluationCandidates(filter === 'ALL' ? undefined : filter);
  const accepted = useEvaluationCandidates('ACCEPTED');
  const channels = useChannels();
  const [editing, setEditing] = useState<EvaluationCandidate | null>(null);
  const [searchParams, setSearchParams] = useSearchParams();
  const chName = (id: string) => {
    const c = channels.data?.find((x) => x.id === id);
    return c ? `#${c.name}` : `${id.slice(0, 8)}…`;
  };
  const acceptedCount = accepted.data?.length ?? 0;

  const onExport = async () => {
    try {
      await downloadCandidatesYaml();
    } catch (e) {
      message.error(errorMessage(e));
    }
  };

  const cols: ColumnsType<EvaluationCandidate> = [
    {
      title: '질문',
      dataIndex: 'question',
      render: (v: string) => (v ? <Text>{v}</Text> : <Text type="secondary">(질문을 찾지 못함)</Text>),
    },
    { title: '채널', dataIndex: 'channel_id', width: 140, render: (v: string) => <code title={v}>{chName(v)}</code> },
    { title: '유형', dataIndex: 'case_type', width: 110, render: (v: EvalCaseType) => <Tag>{caseTypeLabel(v)}</Tag> },
    {
      title: '상태',
      dataIndex: 'status',
      width: 100,
      render: (v: CandidateStatus) => <Tag color={STATUS_COLOR[v]}>{CANDIDATE_STATUS_LABEL[v]}</Tag>,
    },
    {
      title: '승격',
      key: 'promoted',
      width: 170,
      render: (_, r) => (
        <Text type="secondary" style={{ fontSize: 12 }}>
          {r.promoted_by} · {r.created_at ? new Date(r.created_at).toLocaleString() : ''}
        </Text>
      ),
    },
    {
      title: '',
      key: 'action',
      width: 80,
      render: (_, r) => (
        <Button size="small" onClick={() => setEditing(r)}>
          검토
        </Button>
      ),
    },
  ];

  const tab = searchParams.get('tab') === 'runs' ? 'runs' : 'candidates';
  const setTab = (key: string) => setSearchParams(key === 'runs' ? { tab: 'runs' } : {}, { replace: true });

  return (
    <>
      <PageHeader
        title="품질 평가"
        subtitle="👎 답변 → 평가셋 후보 검토·채택 → 평가 실행·결과 (§13.3)"
        extra={
          <Button icon={<DownloadOutlined />} disabled={acceptedCount === 0} onClick={onExport}>
            채택 문항 YAML 내보내기 ({acceptedCount})
          </Button>
        }
      />
      <Alert
        style={{ marginBottom: 16 }}
        type="info"
        showIcon
        message="평가 순서"
        description={
          <ol style={{ margin: 0, paddingLeft: 18 }}>
            <li>
              <Link to="/feedback">피드백</Link> 화면의 👎 목록에서 [평가셋 승격]
            </li>
            <li>[평가셋 후보] 탭에서 [검토] → 유형·정답 요지·기대 문서/쪽 입력 → [채택] (평가에 쓰지 않을 문항은 [제외])</li>
            <li>[실행 결과] 탭에서 [평가 실행] → 채택 문항 전체를 현재 RAG 로 질의해 지표·문항별 결과를 저장</li>
          </ol>
        }
      />
      <Tabs
        activeKey={tab}
        onChange={setTab}
        items={[
          {
            key: 'candidates',
            label: '평가셋 후보',
            children: (
              <Card
                size="small"
                extra={
                  <Segmented<Filter>
                    value={filter}
                    onChange={setFilter}
                    options={[
                      { value: 'PENDING', label: '검토 대기' },
                      { value: 'ACCEPTED', label: '채택' },
                      { value: 'REJECTED', label: '제외' },
                      { value: 'ALL', label: '전체' },
                    ]}
                  />
                }
              >
                <QueryState
                  isLoading={candidates.isLoading}
                  error={candidates.error}
                  isEmpty={(candidates.data?.length ?? 0) === 0}
                  emptyText={filter === 'PENDING' ? '검토할 후보가 없습니다. 피드백 화면에서 👎 답변을 승격하세요.' : '후보가 없습니다.'}
                >
                  <Table rowKey="id" size="small" columns={cols} dataSource={candidates.data} pagination={{ pageSize: 20 }} />
                </QueryState>
              </Card>
            ),
          },
          { key: 'runs', label: '실행 결과', children: <EvaluationRunsPanel acceptedCount={acceptedCount} /> },
        ]}
      />
      <CandidateDrawer candidate={editing} channelLabel={editing ? chName(editing.channel_id) : ''} onClose={() => setEditing(null)} />
    </>
  );
}

interface FormValues {
  case_type: EvalCaseType;
  answerable: boolean;
  answer_gist: string;
  expected_documents: string[];
  expected_pages: string[];
  note: string;
}

function CandidateDrawer({
  candidate,
  channelLabel,
  onClose,
}: {
  candidate: EvaluationCandidate | null;
  channelLabel: string;
  onClose: () => void;
}) {
  const { message } = App.useApp();
  const [form] = Form.useForm<FormValues>();
  const update = useUpdateCandidate();

  useEffect(() => {
    if (!candidate) return;
    form.setFieldsValue({
      case_type: candidate.case_type,
      answerable: candidate.answerable,
      answer_gist: candidate.answer_gist,
      expected_documents: candidate.expected_documents,
      expected_pages: candidate.expected_pages.map(String),
      note: candidate.note ?? '',
    });
  }, [candidate, form]);

  const save = async (status?: CandidateStatus) => {
    if (!candidate) return;
    const v = form.getFieldsValue();
    const pages = (v.expected_pages ?? []).map((p) => Number(p)).filter((n) => Number.isInteger(n) && n > 0);
    const body: CandidateUpdate = {
      case_type: v.case_type,
      answerable: v.answerable,
      answer_gist: v.answer_gist ?? '',
      expected_documents: v.expected_documents ?? [],
      expected_pages: pages,
      note: v.note || null,
      ...(status ? { status } : {}),
    };
    try {
      await update.mutateAsync({ id: candidate.id, ...body });
      message.success(status ? `${CANDIDATE_STATUS_LABEL[status]} 처리했습니다.` : '저장했습니다.');
      onClose();
    } catch (e) {
      message.error(errorMessage(e));
    }
  };

  return (
    <Drawer
      title="평가셋 후보 검토"
      width={720}
      open={!!candidate}
      onClose={onClose}
      destroyOnClose
      extra={
        candidate && (
          <Space>
            <Button onClick={() => save('REJECTED')} loading={update.isPending}>
              제외
            </Button>
            <Button onClick={() => save()} loading={update.isPending}>
              저장
            </Button>
            <Button type="primary" onClick={() => save('ACCEPTED')} loading={update.isPending}>
              채택
            </Button>
          </Space>
        )
      }
    >
      {candidate && (
        <>
          <Descriptions size="small" column={1} bordered style={{ marginBottom: 16 }}>
            <Descriptions.Item label="질문">{candidate.question || <Text type="secondary">(없음)</Text>}</Descriptions.Item>
            <Descriptions.Item label="👎 받은 답변">
              <Paragraph style={{ margin: 0, whiteSpace: 'pre-wrap' }} ellipsis={{ rows: 6, expandable: true }}>
                {candidate.answer}
              </Paragraph>
            </Descriptions.Item>
            <Descriptions.Item label="답변이 인용한 문서">
              {candidate.cited_documents.length ? candidate.cited_documents.map((d) => <Tag key={d}>{d}</Tag>) : '-'}
            </Descriptions.Item>
            <Descriptions.Item label="채널 · 상태">
              <code>{channelLabel}</code> · <Tag color={STATUS_COLOR[candidate.status]}>{CANDIDATE_STATUS_LABEL[candidate.status]}</Tag>
            </Descriptions.Item>
          </Descriptions>
          <Form form={form} layout="vertical">
            <Space size="large" align="start">
              <Form.Item label="유형" name="case_type" style={{ width: 200 }}>
                <Select options={CASE_TYPES} />
              </Form.Item>
              <Form.Item
                label="문서로 답할 수 있는 질문"
                name="answerable"
                valuePropName="checked"
                tooltip="끄면 '근거 없음으로 안전하게 답해야 하는 문항'(무근거 안전응답률)으로 평가합니다."
              >
                <Switch />
              </Form.Item>
            </Space>
            <Form.Item
              label="정답 요지"
              name="answer_gist"
              tooltip="올바른 답의 핵심. 답할 수 있는 문항은 채택 시 필수입니다."
            >
              <Input.TextArea rows={3} placeholder="예: 2025년 연간 매출은 분기 합계 약 2.6조 원" />
            </Form.Item>
            <Form.Item
              label="기대 문서 (검색·인용돼야 하는 문서 제목)"
              name="expected_documents"
              tooltip="Recall@10·Citation Precision 계산에 쓰입니다. 입력 후 Enter."
            >
              <Select mode="tags" tokenSeparators={[',']} placeholder="문서 제목" />
            </Form.Item>
            <Form.Item label="기대 쪽(page)" name="expected_pages">
              <Select mode="tags" tokenSeparators={[',', ' ']} placeholder="예: 3, 4" />
            </Form.Item>
            <Form.Item label="메모" name="note">
              <Input.TextArea rows={2} />
            </Form.Item>
          </Form>
        </>
      )}
    </Drawer>
  );
}
