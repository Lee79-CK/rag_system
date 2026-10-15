import {
  App,
  Button,
  Card,
  Col,
  List,
  Popconfirm,
  Progress,
  Row,
  Statistic,
  Table,
  Tag,
  Typography,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { DislikeOutlined, LikeOutlined, RiseOutlined } from '@ant-design/icons';
import { PageHeader } from '../components/PageHeader';
import { QueryState, errorMessage } from '../components/QueryState';
import { BarChart, type BarDatum } from '../components/BarChart';
import { useFeedbackByChannel, useFeedbackMessages, useFeedbackSummary } from '../api/feedback';
import { useChannels } from '../api/channels';
import { CANDIDATE_STATUS_LABEL, usePromoteCandidate } from '../api/evaluation';
import { Link } from 'react-router-dom';
import type { FeedbackByChannel, FeedbackMessage } from '../types';

const { Text, Paragraph } = Typography;

export function FeedbackDashboard() {
  const { message } = App.useApp();
  const summary = useFeedbackSummary();
  const byChannel = useFeedbackByChannel();
  const channels = useChannels();
  // channel_id(chat_channels.id) → #name 표시. 삭제/과거 채널은 id 앞 8자리
  const chName = (id: string) => {
    const c = channels.data?.find((x) => x.id === id);
    return c ? `#${c.name}` : `${id.slice(0, 8)}…`;
  };
  const downMessages = useFeedbackMessages('DOWN');
  const promote = usePromoteCandidate();

  const ratio = summary.data?.satisfaction_ratio ?? null;

  const chartData: BarDatum[] = (byChannel.data ?? []).map((c: FeedbackByChannel) => ({
    label: chName(c.channel_id),
    value: c.up,
    secondary: c.down,
    caption:
      c.satisfaction_ratio === null ? '-' : `${Math.round(c.satisfaction_ratio * 100)}%`,
  }));

  const onPromote = async (messageId: string) => {
    try {
      const r = await promote.mutateAsync(messageId);
      message.success(
        r.created ? '평가셋 후보로 승격했습니다. 품질 평가 화면에서 정답을 입력하세요.' : '이미 승격된 답변입니다.',
      );
    } catch (e) {
      message.error(errorMessage(e));
    }
  };

  const channelCols: ColumnsType<FeedbackByChannel> = [
    { title: 'Channel', dataIndex: 'channel_id', render: (v: string) => <code title={v}>{chName(v)}</code> },
    { title: '👍', dataIndex: 'up', width: 80 },
    { title: '👎', dataIndex: 'down', width: 80 },
    { title: '합계', dataIndex: 'total', width: 80 },
    {
      title: '만족률',
      dataIndex: 'satisfaction_ratio',
      render: (v: number | null) =>
        v === null ? (
          <Text type="secondary">-</Text>
        ) : (
          <Tag color={v >= 0.7 ? 'success' : v >= 0.4 ? 'warning' : 'error'}>
            {Math.round(v * 1000) / 10}%
          </Tag>
        ),
    },
  ];

  return (
    <>
      <PageHeader
        title="Feedback Dashboard"
        subtitle="답변 피드백 집계 · Channel별 만족률 · 👎 사례 → 평가셋 승격 (v1.1, §7.5/§8.4)"
      />

      {/* Summary */}
      <Row gutter={[16, 16]}>
        <Col xs={24} sm={8}>
          <Card>
            <Statistic
              title="👍 도움됨"
              value={summary.data?.up ?? 0}
              prefix={<LikeOutlined />}
              loading={summary.isLoading}
            />
          </Card>
        </Col>
        <Col xs={24} sm={8}>
          <Card>
            <Statistic
              title="👎 아쉬움"
              value={summary.data?.down ?? 0}
              prefix={<DislikeOutlined />}
              loading={summary.isLoading}
            />
          </Card>
        </Col>
        <Col xs={24} sm={8}>
          <Card>
            <Text type="secondary">만족률 UP / (UP+DOWN)</Text>
            <div style={{ marginTop: 8 }}>
              {ratio === null ? (
                <Text type="secondary">피드백 없음</Text>
              ) : (
                <Progress
                  percent={Math.round(ratio * 1000) / 10}
                  status={ratio >= 0.7 ? 'success' : ratio >= 0.4 ? 'normal' : 'exception'}
                />
              )}
            </div>
          </Card>
        </Col>
      </Row>

      {/* By-channel chart + table */}
      <Row gutter={[16, 16]} style={{ marginTop: 16 }}>
        <Col xs={24} lg={12}>
          <Card title="Channel별 피드백" size="small">
            <QueryState
              isLoading={byChannel.isLoading}
              error={byChannel.error}
              isEmpty={chartData.length === 0}
              emptyText="Channel별 집계 없음"
            >
              <BarChart data={chartData} primaryLabel="👍 UP" secondaryLabel="👎 DOWN" />
            </QueryState>
          </Card>
        </Col>
        <Col xs={24} lg={12}>
          <Card title="Channel별 상세" size="small">
            <QueryState
              isLoading={byChannel.isLoading}
              error={byChannel.error}
              isEmpty={(byChannel.data?.length ?? 0) === 0}
              emptyText="집계 없음"
            >
              <Table
                rowKey="channel_id"
                size="small"
                columns={channelCols}
                dataSource={byChannel.data}
                pagination={false}
              />
            </QueryState>
          </Card>
        </Col>
      </Row>

      {/* 👎 answer list with citations + promote */}
      <Card
        title="👎 답변 목록 (질문/답변/Citation) — 품질 개선 분석"
        size="small"
        style={{ marginTop: 16 }}
      >
        <QueryState
          isLoading={downMessages.isLoading}
          error={downMessages.error}
          isEmpty={(downMessages.data?.length ?? 0) === 0}
          emptyText="👎 피드백이 없습니다."
        >
          <List
            itemLayout="vertical"
            dataSource={downMessages.data}
            pagination={{ pageSize: 10 }}
            renderItem={(m: FeedbackMessage) => (
              <List.Item
                key={m.message_id}
                extra={
                  m.candidate_status ? (
                    <Link to="/evaluation">
                      <Button icon={<RiseOutlined />}>승격됨 · {CANDIDATE_STATUS_LABEL[m.candidate_status]}</Button>
                    </Link>
                  ) : (
                    <Popconfirm
                      title="이 답변을 평가셋 후보로 승격하시겠습니까?"
                      onConfirm={() => onPromote(m.message_id)}
                    >
                      <Button
                        type="primary"
                        icon={<RiseOutlined />}
                        loading={promote.isPending && promote.variables === m.message_id}
                      >
                        평가셋 승격
                      </Button>
                    </Popconfirm>
                  )
                }
              >
                <List.Item.Meta
                  title={
                    <span>
                      <Tag color="volcano">DOWN</Tag>
                      <code>{m.message_id.slice(0, 8)}…</code>{' '}
                      <Text type="secondary" style={{ fontSize: 12 }}>
                        channel {chName(m.channel_id)} ·{' '}
                        {m.created_at ? new Date(m.created_at).toLocaleString() : ''}
                      </Text>
                    </span>
                  }
                />
                {m.question && (
                  <Paragraph style={{ marginBottom: 4 }} ellipsis={{ rows: 2, expandable: true }}>
                    <Text strong>Q. </Text>
                    {m.question}
                  </Paragraph>
                )}
                <Paragraph style={{ marginBottom: 8 }} ellipsis={{ rows: 4, expandable: true }}>
                  {m.question && <Text strong>A. </Text>}
                  {m.content}
                </Paragraph>
                {m.citations.length > 0 && (
                  <div>
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      Citations:{' '}
                    </Text>
                    {m.citations.map((c, i) => (
                      <Tag key={`${m.message_id}-${i}`}>
                        #{c.rank ?? i + 1} {c.chunk_id ? `${c.chunk_id.slice(0, 8)}…` : ''}
                        {c.score != null ? ` (${c.score.toFixed(3)})` : ''}
                      </Tag>
                    ))}
                  </div>
                )}
              </List.Item>
            )}
          />
        </QueryState>
      </Card>
    </>
  );
}
