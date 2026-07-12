import { useState } from 'react';
import {
  App,
  Button,
  Card,
  Descriptions,
  Empty,
  Form,
  Input,
  InputNumber,
  Modal,
  Select,
  Space,
  Switch,
  Table,
  Tag,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { ApiOutlined, KeyOutlined, PlusOutlined, ThunderboltOutlined } from '@ant-design/icons';
import { PageHeader } from '../components/PageHeader';
import { QueryState, errorMessage } from '../components/QueryState';
import { SecretField } from '../components/SecretField';
import { KnowledgeScopeEditor } from '../components/KnowledgeScopeEditor';
import {
  useChannels,
  useCreateBinding,
  useCreateChannel,
  useSetBindingEnabled,
  useTestChannel,
  useUpdateBinding,
  useUpdateSecret,
} from '../api/channels';
import type { BindingView, ChannelMode, ChannelView, KnowledgeScope } from '../types';

const MODE_OPTIONS: { label: string; value: ChannelMode }[] = [
  { label: '전용 Channel (DEDICATED_CHANNEL)', value: 'DEDICATED_CHANNEL' },
  { label: '트리거 단어 (TRIGGER_WORD)', value: 'TRIGGER_WORD' },
];

export function Channels() {
  const { message } = App.useApp();
  const channels = useChannels();
  const createChannel = useCreateChannel();

  const [channelModalOpen, setChannelModalOpen] = useState(false);
  const [bindingModal, setBindingModal] = useState<{ channel: ChannelView } | null>(null);
  const [secretModal, setSecretModal] = useState<{ channel: ChannelView } | null>(null);
  const [channelForm] = Form.useForm();

  const submitChannel = async () => {
    const values = await channelForm.validateFields();
    try {
      await createChannel.mutateAsync(values);
      message.success('Channel 등록 완료');
      setChannelModalOpen(false);
      channelForm.resetFields();
    } catch (e) {
      message.error(errorMessage(e));
    }
  };

  const columns: ColumnsType<ChannelView> = [
    { title: 'Channel 이름', dataIndex: 'channel_name' },
    {
      title: 'Channel ID',
      dataIndex: 'channel_id',
      render: (v: string) => <code>{v}</code>,
    },
    { title: 'Team', dataIndex: 'team_id', render: (v: string) => <code>{v}</code> },
    {
      title: 'Binding',
      key: 'bindings',
      render: (_, row) => {
        const n = row.bindings?.length ?? 0;
        const enabled = row.bindings?.filter((b) => b.enabled).length ?? 0;
        return n ? (
          <Tag color={enabled ? 'success' : 'default'}>
            {enabled}/{n} 활성
          </Tag>
        ) : (
          <Tag>없음</Tag>
        );
      },
    },
    {
      title: '작업',
      key: 'actions',
      render: (_, row) => (
        <Space>
          <Button
            size="small"
            icon={<PlusOutlined />}
            onClick={() => setBindingModal({ channel: row })}
          >
            Binding 추가
          </Button>
          <Button
            size="small"
            icon={<KeyOutlined />}
            onClick={() => setSecretModal({ channel: row })}
          >
            Secret 교체
          </Button>
        </Space>
      ),
    },
  ];

  return (
    <>
      <PageHeader
        title="Channels"
        subtitle="Mattermost Channel Binding CRUD / 연결 테스트 / 활성화 (§7.5)"
        extra={
          <Button type="primary" icon={<ApiOutlined />} onClick={() => setChannelModalOpen(true)}>
            Channel 등록
          </Button>
        }
      />

      <QueryState
        isLoading={channels.isLoading}
        error={channels.error}
        isEmpty={(channels.data?.length ?? 0) === 0}
        emptyText="등록된 Channel이 없습니다."
      >
        <Table
          rowKey="id"
          columns={columns}
          dataSource={channels.data}
          pagination={{ pageSize: 20 }}
          expandable={{
            expandedRowRender: (row) => <BindingList channel={row} />,
            rowExpandable: () => true,
          }}
        />
      </QueryState>

      {/* Channel 등록 */}
      <Modal
        title="Channel 등록"
        open={channelModalOpen}
        onOk={submitChannel}
        confirmLoading={createChannel.isPending}
        onCancel={() => setChannelModalOpen(false)}
        okText="등록"
        cancelText="취소"
      >
        <Form form={channelForm} layout="vertical">
          <Form.Item label="Team ID" name="team_id" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item label="Channel ID" name="channel_id" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item label="Channel 이름" name="channel_name" rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item label="Team 도메인" name="team_domain">
            <Input />
          </Form.Item>
          <Form.Item label="표시 이름" name="display_name">
            <Input />
          </Form.Item>
        </Form>
      </Modal>

      {bindingModal && (
        <BindingModal
          channel={bindingModal.channel}
          onClose={() => setBindingModal(null)}
        />
      )}
      {secretModal && (
        <SecretModal channel={secretModal.channel} onClose={() => setSecretModal(null)} />
      )}
    </>
  );
}

function BindingList({ channel }: { channel: ChannelView }) {
  const { message } = App.useApp();
  const setEnabled = useSetBindingEnabled();
  const test = useTestChannel();
  const [editing, setEditing] = useState<BindingView | null>(null);

  if (!channel.bindings?.length) {
    return <Empty description="Binding 없음" image={Empty.PRESENTED_IMAGE_SIMPLE} />;
  }

  const onTest = async () => {
    try {
      const res = await test.mutateAsync(channel.id);
      if (res.ok) message.success(`연결 테스트 성공: ${res.detail ?? ''}`);
      else message.warning(`연결 테스트 실패: ${res.detail ?? ''}`);
    } catch (e) {
      message.error(errorMessage(e));
    }
  };

  return (
    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      {channel.bindings.map((b) => (
        <Card key={b.id} size="small" title={`Binding ${b.id.slice(0, 8)}…`}>
          <Descriptions column={2} size="small">
            <Descriptions.Item label="모드">
              <Tag color="blue">{b.mode}</Tag>
            </Descriptions.Item>
            <Descriptions.Item label="트리거 단어">{b.trigger_word ?? '-'}</Descriptions.Item>
            <Descriptions.Item label="history_turns">{b.history_turns}</Descriptions.Item>
            <Descriptions.Item label="knowledge_scope_id">
              {b.knowledge_scope_id ? <code>{b.knowledge_scope_id}</code> : '전체'}
            </Descriptions.Item>
            <Descriptions.Item label="mention_user">{b.mention_user ? 'Y' : 'N'}</Descriptions.Item>
            <Descriptions.Item label="ack_message">
              {b.ack_message_enabled ? 'Y' : 'N'}
            </Descriptions.Item>
            <Descriptions.Item label="feedback">
              {b.feedback_enabled ? 'Y' : 'N'}
            </Descriptions.Item>
            <Descriptions.Item label="Secret" span={2}>
              <SecretField secretRef={b.secret_ref} updatedAt={b.secret_updated_at} />
            </Descriptions.Item>
          </Descriptions>
          <Space style={{ marginTop: 12 }} wrap>
            <span>
              활성화{' '}
              <Switch
                checked={b.enabled}
                loading={setEnabled.isPending}
                onChange={(checked) =>
                  setEnabled
                    .mutateAsync({ bindingId: b.id, enabled: checked })
                    .then(() => message.success(checked ? '활성화' : '비활성화'))
                    .catch((e) => message.error(errorMessage(e)))
                }
              />
            </span>
            <Button size="small" onClick={() => setEditing(b)}>
              편집
            </Button>
            <Button
              size="small"
              icon={<ThunderboltOutlined />}
              loading={test.isPending}
              onClick={onTest}
            >
              연결 테스트
            </Button>
          </Space>
        </Card>
      ))}
      {editing && (
        <BindingModal channel={channel} binding={editing} onClose={() => setEditing(null)} />
      )}
    </Space>
  );
}

function BindingModal({
  channel,
  binding,
  onClose,
}: {
  channel: ChannelView;
  binding?: BindingView;
  onClose: () => void;
}) {
  const { message } = App.useApp();
  const create = useCreateBinding();
  const update = useUpdateBinding();
  const [form] = Form.useForm();
  const [scope, setScope] = useState<KnowledgeScope>({
    categories: [],
    departments: [],
    security_levels: ['INTERNAL'],
    document_ids: [],
  });
  const isEdit = !!binding;

  const submit = async () => {
    const values = await form.validateFields();
    try {
      if (isEdit && binding) {
        await update.mutateAsync({
          bindingId: binding.id,
          body: {
            mode: values.mode,
            trigger_word: values.trigger_word || null,
            history_turns: values.history_turns,
            knowledge_scope_id: values.knowledge_scope_id || null,
            mention_user: values.mention_user,
            ack_message_enabled: values.ack_message_enabled,
            feedback_enabled: values.feedback_enabled,
          },
        });
        message.success('Binding 수정 완료');
      } else {
        await create.mutateAsync({
          channelId: channel.id,
          body: {
            mode: values.mode,
            trigger_word: values.trigger_word || null,
            enabled: false,
            knowledge_scope_id: values.knowledge_scope_id || null,
            history_turns: values.history_turns,
            mention_user: values.mention_user,
            ack_message_enabled: values.ack_message_enabled,
            feedback_enabled: values.feedback_enabled,
            secret_ref: values.secret_ref,
          },
        });
        message.success('Binding 생성 완료 (비활성 상태로 생성됨)');
      }
      onClose();
    } catch (e) {
      message.error(errorMessage(e));
    }
  };

  return (
    <Modal
      title={isEdit ? 'Binding 편집' : `Binding 추가 — ${channel.channel_name}`}
      open
      width={640}
      onOk={submit}
      confirmLoading={create.isPending || update.isPending}
      onCancel={onClose}
      okText="저장"
      cancelText="취소"
    >
      <Form
        form={form}
        layout="vertical"
        initialValues={{
          mode: binding?.mode ?? 'DEDICATED_CHANNEL',
          trigger_word: binding?.trigger_word ?? '',
          history_turns: binding?.history_turns ?? 8,
          knowledge_scope_id: binding?.knowledge_scope_id ?? '',
          mention_user: binding?.mention_user ?? true,
          ack_message_enabled: binding?.ack_message_enabled ?? true,
          feedback_enabled: binding?.feedback_enabled ?? true,
          secret_ref: '',
        }}
      >
        <Form.Item label="트리거 모드" name="mode" rules={[{ required: true }]}>
          <Select options={MODE_OPTIONS} />
        </Form.Item>
        <Form.Item
          noStyle
          shouldUpdate={(prev, cur) => prev.mode !== cur.mode}
        >
          {({ getFieldValue }) =>
            getFieldValue('mode') === 'TRIGGER_WORD' ? (
              <Form.Item
                label="트리거 단어"
                name="trigger_word"
                rules={[{ required: true, message: '트리거 단어를 입력하세요.' }]}
              >
                <Input placeholder="예: @rag" />
              </Form.Item>
            ) : null
          }
        </Form.Item>
        <Form.Item label="history_turns" name="history_turns">
          <InputNumber min={0} max={50} style={{ width: '100%' }} />
        </Form.Item>
        <Form.Item label="mention_user" name="mention_user" valuePropName="checked">
          <Switch />
        </Form.Item>
        <Form.Item label="ack_message_enabled" name="ack_message_enabled" valuePropName="checked">
          <Switch />
        </Form.Item>
        <Form.Item label="feedback_enabled (v1.1)" name="feedback_enabled" valuePropName="checked">
          <Switch />
        </Form.Item>

        <Form.Item
          label="Knowledge Scope ID"
          name="knowledge_scope_id"
          tooltip="지정 시 해당 scope로 검색을 제한합니다. 비우면 Channel ACL 기본값."
        >
          <Input placeholder="knowledge_scopes.id (UUID) — 비우면 전체" allowClear />
        </Form.Item>

        <KnowledgeScopeEditor value={scope} onChange={setScope} />

        {!isEdit && (
          <Form.Item
            label="Secret Ref (K8s Secret 이름)"
            name="secret_ref"
            rules={[{ required: true, message: 'secret_ref는 필수입니다.' }]}
            tooltip="Incoming Webhook URL 값이 아니라 K8s Secret의 '이름'만 입력합니다 (FR-OPS-010)."
          >
            <Input placeholder="예: mm-webhook-teamA-general" />
          </Form.Item>
        )}
      </Form>
    </Modal>
  );
}

function SecretModal({ channel, onClose }: { channel: ChannelView; onClose: () => void }) {
  const { message } = App.useApp();
  const updateSecret = useUpdateSecret();
  const [form] = Form.useForm();

  const submit = async () => {
    const values = await form.validateFields();
    try {
      const res = await updateSecret.mutateAsync({
        channelId: channel.id,
        secretRef: values.secret_ref,
      });
      message.success(`Secret 교체 완료 (${res.secret_ref})`);
      onClose();
    } catch (e) {
      message.error(errorMessage(e));
    }
  };

  return (
    <Modal
      title={`Secret 교체 — ${channel.channel_name}`}
      open
      onOk={submit}
      confirmLoading={updateSecret.isPending}
      onCancel={onClose}
      okText="교체"
      cancelText="취소"
    >
      <p style={{ color: '#8c8c8c' }}>
        실제 값(Webhook URL)은 K8s Secret으로만 관리됩니다. 여기서는 Secret의 <b>이름</b>만
        등록/갱신하며, 값은 어떤 응답에도 노출되지 않습니다 (FR-OPS-010).
      </p>
      <Form form={form} layout="vertical">
        <Form.Item
          label="Secret Ref"
          name="secret_ref"
          rules={[{ required: true, message: 'secret_ref는 필수입니다.' }]}
        >
          <Input placeholder="예: mm-webhook-teamA-general" />
        </Form.Item>
      </Form>
    </Modal>
  );
}
