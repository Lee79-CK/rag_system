import { Card, Col, Progress, Row, Statistic, Typography } from 'antd';
import {
  ApiOutlined,
  DislikeOutlined,
  FileTextOutlined,
  LikeOutlined,
  MessageOutlined,
  WarningOutlined,
} from '@ant-design/icons';
import { PageHeader } from '../components/PageHeader';
import { useDocuments } from '../api/documents';
import { useChannels } from '../api/channels';
import { useChatJobs } from '../api/chatJobs';
import { useFeedbackSummary } from '../api/feedback';

const { Text } = Typography;

const DEAD_LETTER_STATUSES = new Set(['DEAD_LETTER', 'DEADLETTER', 'FAILED']);

export function Dashboard() {
  const docs = useDocuments();
  const channels = useChannels();
  const chatJobs = useChatJobs();
  const feedback = useFeedbackSummary();

  const docCount = docs.data?.length ?? 0;
  const activeDocs = docs.data?.filter((d) => d.status === 'ACTIVE').length ?? 0;
  const channelCount = channels.data?.length ?? 0;
  const enabledBindings =
    channels.data?.reduce(
      (acc, c) => acc + (c.bindings?.filter((b) => b.enabled).length ?? 0),
      0,
    ) ?? 0;
  const chatJobCount = chatJobs.data?.length ?? 0;
  const deadLetter =
    chatJobs.data?.filter((j) => DEAD_LETTER_STATUSES.has((j.status ?? '').toUpperCase())).length ??
    0;

  const ratio = feedback.data?.satisfaction_ratio ?? null;

  return (
    <>
      <PageHeader title="Dashboard" subtitle="플랫폼 운영 상태 요약" />
      <Row gutter={[16, 16]}>
        <Col xs={24} sm={12} lg={8}>
          <Card>
            <Statistic
              title="문서"
              value={docCount}
              prefix={<FileTextOutlined />}
              loading={docs.isLoading}
            />
            <Text type="secondary">활성 {activeDocs}건</Text>
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={8}>
          <Card>
            <Statistic
              title="Channel"
              value={channelCount}
              prefix={<ApiOutlined />}
              loading={channels.isLoading}
            />
            <Text type="secondary">활성 Binding {enabledBindings}건</Text>
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={8}>
          <Card>
            <Statistic
              title="Chat Job"
              value={chatJobCount}
              prefix={<MessageOutlined />}
              loading={chatJobs.isLoading}
            />
            <Text type={deadLetter ? 'danger' : 'secondary'}>
              <WarningOutlined /> Dead Letter {deadLetter}건
            </Text>
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={8}>
          <Card>
            <Statistic
              title="👍 도움됨"
              value={feedback.data?.up ?? 0}
              prefix={<LikeOutlined />}
              loading={feedback.isLoading}
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={8}>
          <Card>
            <Statistic
              title="👎 아쉬움"
              value={feedback.data?.down ?? 0}
              prefix={<DislikeOutlined />}
              loading={feedback.isLoading}
            />
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={8}>
          <Card>
            <Text type="secondary">만족률 (UP / (UP+DOWN))</Text>
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
    </>
  );
}
