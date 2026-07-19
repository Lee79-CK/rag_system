import { useMemo, useState } from 'react';
import {
  App,
  Button,
  Checkbox,
  Drawer,
  Form,
  Input,
  Modal,
  Select,
  Slider,
  Space,
  Steps,
  Switch,
  Table,
  Tooltip,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { ApiOutlined, PlusOutlined, ReloadOutlined, ThunderboltOutlined } from '@ant-design/icons';
import { QueryState, errorMessage } from '../components/QueryState';
import { SecretField } from '../components/SecretField';
import { KnowledgeScopeEditor } from '../components/KnowledgeScopeEditor';
import { StatusBadge, Surface, Mono } from '../components/ui';
import { useWhoami } from '../api/auth';
import {
  useChannels,
  useCreateBinding,
  useCreateChannel,
  useSetBindingEnabled,
  useTestChannel,
  useUpdateBinding,
  useUpdateSecret,
} from '../api/channels';
import type {
  BindingView,
  ChannelMode,
  ChannelView,
  ConnectionTestResult,
  KnowledgeScope,
  Role,
} from '../types';

const MODE_OPTIONS: { label: string; value: ChannelMode }[] = [
  { label: '전용 Channel (DEDICATED_CHANNEL)', value: 'DEDICATED_CHANNEL' },
  { label: '트리거 단어 (TRIGGER_WORD)', value: 'TRIGGER_WORD' },
];

const filterSelectStyle: React.CSSProperties = {
  padding: '7px 10px',
  border: '1px solid var(--border)',
  borderRadius: 6,
  fontSize: 13,
  background: 'var(--surface)',
  color: 'var(--text)',
};

/** A flattened table row: a channel paired with one of its bindings (or none). */
interface Row {
  channel: ChannelView;
  binding: BindingView | null;
}

type TestMap = Record<string, ConnectionTestResult & { at: string }>;

function isSecretStale(updatedAt: string | null): boolean {
  if (!updatedAt) return false;
  const days = (Date.now() - new Date(updatedAt).getTime()) / 86_400_000;
  return days >= 90;
}

export function Channels() {
  const { message } = App.useApp();
  const channels = useChannels();
  const { data: me } = useWhoami();
  const setEnabled = useSetBindingEnabled();
  const test = useTestChannel();

  const roles = (me?.roles ?? []) as Role[];
  const canWrite = roles.length === 0 || roles.includes('SYS_ADMIN');

  const [q, setQ] = useState('');
  const [fStatus, setFStatus] = useState('');
  const [tests, setTests] = useState<TestMap>({});
  const [wizard, setWizard] = useState<
    | { mode: 'new-channel' }
    | { mode: 'new-binding'; channel: ChannelView }
    | { mode: 'edit'; channel: ChannelView; binding: BindingView }
    | null
  >(null);
  const [secretModal, setSecretModal] = useState<ChannelView | null>(null);
  const [activate, setActivate] = useState<Row | null>(null);

  const rows: Row[] = useMemo(() => {
    const list = channels.data ?? [];
    return list.flatMap<Row>((c) =>
      c.bindings?.length
        ? c.bindings.map((b) => ({ channel: c, binding: b }))
        : [{ channel: c, binding: null }],
    );
  }, [channels.data]);

  const filtered = rows.filter((r) => {
    const matchesQ =
      !q ||
      r.channel.channel_name.toLowerCase().includes(q.toLowerCase()) ||
      r.channel.channel_id.toLowerCase().includes(q.toLowerCase());
    const enabled = !!r.binding?.enabled;
    const matchesStatus =
      !fStatus || (fStatus === 'active' ? enabled : !enabled);
    return matchesQ && matchesStatus;
  });

  const runTest = async (channel: ChannelView) => {
    try {
      const res = await test.mutateAsync(channel.id);
      setTests((m) => ({ ...m, [channel.id]: { ...res, at: new Date().toISOString() } }));
      if (res.ok) message.success(`연결 테스트 성공${res.detail ? `: ${res.detail}` : ''}`);
      else message.warning(`연결 테스트 실패${res.detail ? `: ${res.detail}` : ''}`);
    } catch (e) {
      message.error(errorMessage(e));
    }
  };

  const toggle = (row: Row, next: boolean) => {
    if (!row.binding) return;
    if (next) {
      setActivate(row); // activation requires the confirm modal (§5.4)
      return;
    }
    Modal.confirm({
      title: `${row.channel.channel_name} Binding 비활성화`,
      content: '비활성화하면 이후 이 Channel의 질문에 응답하지 않습니다.',
      okText: '비활성화',
      okButtonProps: { danger: true },
      cancelText: '취소',
      onOk: () =>
        setEnabled
          .mutateAsync({ bindingId: row.binding!.id, enabled: false })
          .then(() => message.success('비활성화되었습니다.'))
          .catch((e) => message.error(errorMessage(e))),
    });
  };

  const columns: ColumnsType<Row> = [
    {
      title: 'Channel',
      key: 'channel',
      render: (_, r) => (
        <div>
          <Button
            type="link"
            style={{ padding: 0, fontWeight: 600 }}
            disabled={!r.binding || !canWrite}
            onClick={() =>
              r.binding &&
              setWizard({ mode: 'edit', channel: r.channel, binding: r.binding })
            }
          >
            {r.channel.channel_name}
          </Button>
          <div>
            <Mono style={{ fontSize: 11.5, color: 'var(--text-disabled)' }}>
              {r.channel.channel_id}
            </Mono>
          </div>
        </div>
      ),
    },
    {
      title: 'Team',
      key: 'team',
      render: (_, r) => <Mono style={{ fontSize: 12.5 }}>{r.channel.team_id}</Mono>,
    },
    {
      title: '모드',
      key: 'mode',
      render: (_, r) =>
        r.binding ? (
          <span
            style={{
              fontSize: 11.5,
              fontWeight: 700,
              padding: '2px 8px',
              borderRadius: 5,
              background: '#eff4ff',
              color: 'var(--primary-hover)',
            }}
          >
            {r.binding.mode === 'TRIGGER_WORD'
              ? `트리거 ${r.binding.trigger_word ?? ''}`.trim()
              : '전용'}
          </span>
        ) : (
          '-'
        ),
    },
    {
      title: '지식 범위',
      key: 'scope',
      render: (_, r) =>
        r.binding ? (
          <span
            style={{
              fontSize: 11.5,
              padding: '2px 8px',
              borderRadius: 5,
              background: 'var(--tint-neutral)',
              color: 'var(--text-sub)',
            }}
          >
            {r.binding.knowledge_scope_id ? 'Scope 지정' : '전체 ACL'}
          </span>
        ) : (
          '-'
        ),
    },
    {
      title: '이력(턴)',
      key: 'turns',
      align: 'right',
      render: (_, r) =>
        r.binding ? <Mono style={{ fontSize: 12.5 }}>{r.binding.history_turns}</Mono> : '-',
    },
    {
      title: '피드백',
      key: 'feedback',
      render: (_, r) =>
        r.binding ? (
          <StatusBadge
            kind={r.binding.feedback_enabled ? 'success' : 'neutral'}
            label={r.binding.feedback_enabled ? 'on' : 'off'}
          />
        ) : (
          '-'
        ),
    },
    {
      title: 'Secret',
      key: 'secret',
      render: (_, r) =>
        r.binding ? (
          <Space direction="vertical" size={2}>
            <SecretField secretRef={r.binding.secret_ref} updatedAt={r.binding.secret_updated_at} />
            {isSecretStale(r.binding.secret_updated_at) && (
              <StatusBadge kind="warning" label="90일 경과" />
            )}
          </Space>
        ) : (
          <StatusBadge kind="warning" label="미등록" />
        ),
    },
    {
      title: '연결 테스트',
      key: 'test',
      render: (_, r) => {
        const t = tests[r.channel.id];
        return (
          <Space direction="vertical" size={2}>
            {t ? (
              <StatusBadge
                kind={t.ok ? 'success' : 'danger'}
                label={`${t.ok ? '성공' : '실패'} ${new Date(t.at).toLocaleTimeString('ko-KR')}`}
              />
            ) : (
              <span style={{ fontSize: 12, color: 'var(--text-disabled)' }}>미실행</span>
            )}
            <Button
              size="small"
              icon={<ThunderboltOutlined />}
              loading={test.isPending}
              disabled={!r.binding}
              onClick={() => runTest(r.channel)}
            >
              테스트
            </Button>
          </Space>
        );
      },
    },
    {
      title: '활성',
      key: 'enabled',
      align: 'center',
      render: (_, r) =>
        r.binding ? (
          <Switch
            checked={r.binding.enabled}
            loading={setEnabled.isPending}
            disabled={!canWrite}
            onChange={(next) => toggle(r, next)}
          />
        ) : canWrite ? (
          <Button
            size="small"
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => setWizard({ mode: 'new-binding', channel: r.channel })}
          >
            Binding
          </Button>
        ) : (
          '-'
        ),
    },
    {
      title: '액션',
      key: 'actions',
      align: 'right',
      render: (_, r) => (
        <Space size="small" wrap>
          {r.binding && (
            <Button
              size="small"
              disabled={!canWrite}
              onClick={() =>
                setWizard({ mode: 'edit', channel: r.channel, binding: r.binding! })
              }
            >
              편집
            </Button>
          )}
          <Button size="small" disabled={!canWrite} onClick={() => setSecretModal(r.channel)}>
            Secret 교체
          </Button>
        </Space>
      ),
    },
  ];

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      {!canWrite && (
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 10,
            padding: '10px 16px',
            background: 'var(--tint-neutral)',
            border: '1px solid var(--border)',
            borderRadius: 8,
            fontSize: 13,
            color: 'var(--text-sub)',
          }}
        >
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#6b7280" strokeWidth={2}>
            <rect x="3" y="11" width="18" height="11" rx="2" />
            <path d="M7 11V7a5 5 0 0 1 10 0v4" />
          </svg>
          읽기 전용 모드 — Binding 등록·활성화·Secret 교체에는 <strong>SYS_ADMIN</strong> 권한이 필요합니다.
        </div>
      )}

      <Surface padding="12px 16px" style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
        <Input
          placeholder="Channel 검색"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          allowClear
          style={{ width: 220 }}
        />
        <select style={filterSelectStyle} value={fStatus} onChange={(e) => setFStatus(e.target.value)}>
          <option value="">상태: 전체</option>
          <option value="active">활성</option>
          <option value="inactive">비활성</option>
        </select>
        <div style={{ flex: 1 }} />
        <Button icon={<ReloadOutlined />} onClick={() => channels.refetch()} title="새로고침" />
        <Tooltip title={canWrite ? undefined : '권한 필요: SYS_ADMIN'}>
          <Button
            type="primary"
            icon={<ApiOutlined />}
            disabled={!canWrite}
            onClick={() => setWizard({ mode: 'new-channel' })}
          >
            Binding 등록
          </Button>
        </Tooltip>
      </Surface>

      <QueryState
        isLoading={channels.isLoading}
        error={channels.error}
        isEmpty={rows.length === 0}
        emptyText="등록된 Channel이 없습니다. [Binding 등록]으로 시작하세요."
      >
        <Surface padding={0} style={{ overflow: 'hidden' }}>
          <Table
            rowKey={(r) => `${r.channel.id}:${r.binding?.id ?? 'none'}`}
            columns={columns}
            dataSource={filtered}
            pagination={{ pageSize: 20, showTotal: (t) => `총 ${t}건 · 페이지당 20행` }}
          />
        </Surface>
      </QueryState>

      {wizard && (
        <BindingWizard state={wizard} onClose={() => setWizard(null)} />
      )}
      {secretModal && (
        <SecretModal channel={secretModal} onClose={() => setSecretModal(null)} />
      )}
      {activate && (
        <ActivationModal
          row={activate}
          test={tests[activate.channel.id]}
          onRunTest={() => runTest(activate.channel)}
          testing={test.isPending}
          onClose={() => setActivate(null)}
          onConfirm={async () => {
            try {
              await setEnabled.mutateAsync({ bindingId: activate.binding!.id, enabled: true });
              message.success('활성화되었습니다.');
              setActivate(null);
            } catch (e) {
              message.error(errorMessage(e));
            }
          }}
          confirming={setEnabled.isPending}
        />
      )}
    </div>
  );
}

/** 4-step wizard for registering / editing a Channel Binding (§5.4). */
function BindingWizard({
  state,
  onClose,
}: {
  state:
    | { mode: 'new-channel' }
    | { mode: 'new-binding'; channel: ChannelView }
    | { mode: 'edit'; channel: ChannelView; binding: BindingView };
  onClose: () => void;
}) {
  const { message } = App.useApp();
  const createChannel = useCreateChannel();
  const createBinding = useCreateBinding();
  const updateBinding = useUpdateBinding();

  const isEdit = state.mode === 'edit';
  const channel = 'channel' in state ? state.channel : undefined;
  const binding = state.mode === 'edit' ? state.binding : undefined;

  const [step, setStep] = useState(0);
  const [form] = Form.useForm();
  const [scope, setScope] = useState<KnowledgeScope>({
    categories: [],
    departments: [],
    security_levels: ['INTERNAL'],
    document_ids: [],
  });

  const submitting = createChannel.isPending || createBinding.isPending || updateBinding.isPending;

  const STEPS = ['Channel 정보', '동작 설정', '지식 범위', 'Secret'];

  const next = async () => {
    // Validate only the fields visible on the current step.
    const fieldsByStep: string[][] = [
      ['team_id', 'channel_id', 'channel_name'],
      ['mode', 'trigger_word', 'history_turns'],
      ['knowledge_scope_id'],
      ['secret_ref'],
    ];
    try {
      await form.validateFields(fieldsByStep[step]);
      setStep((s) => Math.min(s + 1, STEPS.length - 1));
    } catch {
      /* validation errors are shown inline */
    }
  };

  const finish = async () => {
    let values;
    try {
      values = await form.validateFields();
    } catch {
      return;
    }
    const bindingBody = {
      mode: values.mode,
      trigger_word: values.mode === 'TRIGGER_WORD' ? values.trigger_word || null : null,
      history_turns: values.history_turns,
      knowledge_scope_id: values.knowledge_scope_id || null,
      mention_user: values.mention_user,
      ack_message_enabled: values.ack_message_enabled,
      feedback_enabled: values.feedback_enabled,
    };
    try {
      if (isEdit && binding) {
        await updateBinding.mutateAsync({ bindingId: binding.id, body: bindingBody });
        message.success('Binding이 수정되었습니다.');
      } else {
        let channelId = channel?.id;
        if (state.mode === 'new-channel') {
          const created = await createChannel.mutateAsync({
            team_id: values.team_id,
            channel_id: values.channel_id,
            channel_name: values.channel_name,
          });
          channelId = created.id;
        }
        if (!channelId) throw new Error('Channel을 확인할 수 없습니다.');
        await createBinding.mutateAsync({
          channelId,
          body: { ...bindingBody, enabled: false, secret_ref: values.secret_ref },
        });
        message.success('Binding이 생성되었습니다. (비활성 상태 — 연결 테스트 후 활성화하세요)');
      }
      onClose();
    } catch (e) {
      message.error(errorMessage(e));
    }
  };

  const channelReadonly = state.mode !== 'new-channel';

  return (
    <Drawer
      title={isEdit ? `Binding 편집 — ${channel?.channel_name}` : 'Binding 등록'}
      width={640}
      open
      onClose={onClose}
      footer={
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
          <Button onClick={onClose}>취소</Button>
          {step > 0 && <Button onClick={() => setStep((s) => s - 1)}>이전</Button>}
          {step < STEPS.length - 1 ? (
            <Button type="primary" onClick={next}>
              다음
            </Button>
          ) : (
            <Button type="primary" loading={submitting} onClick={finish}>
              {isEdit ? '저장' : '등록'}
            </Button>
          )}
        </div>
      }
    >
      <Steps
        size="small"
        current={step}
        items={STEPS.map((t) => ({ title: t }))}
        style={{ marginBottom: 24 }}
      />
      <Form
        form={form}
        layout="vertical"
        initialValues={{
          team_id: channel?.team_id ?? '',
          channel_id: channel?.channel_id ?? '',
          channel_name: channel?.channel_name ?? '',
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
        {/* Step 1 — Channel 정보 */}
        <div style={{ display: step === 0 ? 'block' : 'none' }}>
          <Form.Item
            label="Team ID"
            name="team_id"
            rules={[{ required: true, message: 'team_id는 필수입니다.' }]}
            tooltip="Mattermost에서 복사한 team_id를 붙여넣으세요."
          >
            <Input className="mono" disabled={channelReadonly} placeholder="예: cloud-team" />
          </Form.Item>
          <Form.Item
            label="Channel ID"
            name="channel_id"
            rules={[{ required: true, message: 'channel_id는 필수입니다.' }]}
          >
            <Input className="mono" disabled={channelReadonly} placeholder="예: rag-cloud-ops" />
          </Form.Item>
          <Form.Item
            label="Channel 이름"
            name="channel_name"
            rules={[{ required: true, message: 'channel_name은 필수입니다.' }]}
          >
            <Input disabled={channelReadonly} placeholder="예: rag-cloud-ops" />
          </Form.Item>
        </div>

        {/* Step 2 — 동작 설정 */}
        <div style={{ display: step === 1 ? 'block' : 'none' }}>
          <Form.Item label="모드" name="mode" rules={[{ required: true }]}>
            <Select options={MODE_OPTIONS} />
          </Form.Item>
          <Form.Item noStyle shouldUpdate={(p, c) => p.mode !== c.mode}>
            {({ getFieldValue }) =>
              getFieldValue('mode') === 'TRIGGER_WORD' ? (
                <Form.Item
                  label="트리거 단어"
                  name="trigger_word"
                  rules={[{ required: true, message: '트리거 단어를 입력하세요.' }]}
                >
                  <Input placeholder="예: !rag" />
                </Form.Item>
              ) : null
            }
          </Form.Item>
          <Form.Item label="대화 이력 turns (0–20)" name="history_turns">
            <Slider min={0} max={20} marks={{ 0: '0', 8: '8', 20: '20' }} />
          </Form.Item>
          <Form.Item label="멘션 사용자(mention_user)" name="mention_user" valuePropName="checked">
            <Switch />
          </Form.Item>
          <Form.Item label="접수 메시지(ack_message)" name="ack_message_enabled" valuePropName="checked">
            <Switch />
          </Form.Item>
          <Form.Item label="피드백 수집(feedback)" name="feedback_enabled" valuePropName="checked">
            <Switch />
          </Form.Item>
        </div>

        {/* Step 3 — 지식 범위 */}
        <div style={{ display: step === 2 ? 'block' : 'none' }}>
          <Form.Item
            label="Knowledge Scope ID"
            name="knowledge_scope_id"
            tooltip="지정 시 해당 scope로 검색을 제한합니다. 비우면 Channel ACL 기본값."
          >
            <Input className="mono" placeholder="knowledge_scopes.id (UUID) — 비우면 전체" allowClear />
          </Form.Item>
          <KnowledgeScopeEditor value={scope} onChange={setScope} />
          <div style={{ fontSize: 12, color: 'var(--text-sub)', marginTop: 8 }}>
            아래 편집기는 검색 범위를 미리 구성/검토하기 위한 것입니다. 최종 반영은 Scope API 연동 후
            지원됩니다 (현재는 <code>knowledge_scope_id</code> 로 연결).
          </div>
        </div>

        {/* Step 4 — Secret */}
        <div style={{ display: step === 3 ? 'block' : 'none' }}>
          {isEdit ? (
            <div>
              <div style={{ fontSize: 13, color: 'var(--text-sub)', marginBottom: 12 }}>
                현재 Secret 참조:
              </div>
              <SecretField secretRef={binding?.secret_ref} updatedAt={binding?.secret_updated_at} />
              <div style={{ fontSize: 12, color: 'var(--text-disabled)', marginTop: 12 }}>
                Secret 값 교체는 목록의 [Secret 교체]에서 수행합니다. 여기서는 동작/범위 설정만
                저장됩니다.
              </div>
            </div>
          ) : (
            <Form.Item
              label="Secret Ref (K8s Secret 이름)"
              name="secret_ref"
              rules={[{ required: true, message: 'secret_ref는 필수입니다.' }]}
              tooltip="Incoming Webhook URL 값이 아니라 K8s Secret의 '이름'만 입력합니다 (FR-OPS-010)."
              extra="실제 Webhook URL은 K8s Secret으로만 저장되며 어떤 응답/화면에도 노출되지 않습니다."
            >
              <Input className="mono" placeholder="예: mattermost-incoming-rag-cloud-ops" />
            </Form.Item>
          )}
        </div>
      </Form>
    </Drawer>
  );
}

function ActivationModal({
  row,
  test,
  onRunTest,
  testing,
  onClose,
  onConfirm,
  confirming,
}: {
  row: Row;
  test?: ConnectionTestResult & { at: string };
  onRunTest: () => void;
  testing: boolean;
  onClose: () => void;
  onConfirm: () => void;
  confirming: boolean;
}) {
  const [checked, setChecked] = useState<boolean[]>([false, false, false]);
  const testOk = !!test?.ok;
  const allChecked = checked.every(Boolean);
  const scopeLabel = row.binding?.knowledge_scope_id ? 'Scope 지정 범위' : '전체 ACL 범위';

  return (
    <Modal
      title="Binding 활성화 확인"
      open
      onCancel={onClose}
      okText="활성화"
      cancelText="취소"
      okButtonProps={{ disabled: !testOk || !allChecked, loading: confirming }}
      onOk={onConfirm}
    >
      <p style={{ color: 'var(--text-sub)', marginTop: 0 }}>
        활성화하면 <strong>{row.channel.channel_name}</strong> Channel의 질문에 실제로 답변이
        게시됩니다. 아래를 확인하세요.
      </p>

      <div
        style={{
          padding: '10px 12px',
          borderRadius: 8,
          marginBottom: 12,
          background: testOk ? 'var(--tint-success)' : 'var(--tint-warning)',
          border: `1px solid ${testOk ? '#bbf7d0' : '#fde5bf'}`,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <StatusBadge
            kind={testOk ? 'success' : 'warning'}
            label={testOk ? `연결 테스트 성공 (${new Date(test!.at).toLocaleTimeString('ko-KR')})` : '연결 테스트 미완료'}
          />
          <div style={{ flex: 1 }} />
          {!testOk && (
            <Button size="small" icon={<ThunderboltOutlined />} loading={testing} onClick={onRunTest}>
              연결 테스트 실행
            </Button>
          )}
        </div>
        {!testOk && (
          <div style={{ fontSize: 12, color: 'var(--warning-fg)', marginTop: 6 }}>
            연결 테스트가 성공해야 활성화할 수 있습니다.
          </div>
        )}
      </div>

      <Space direction="vertical" size={10}>
        <Checkbox
          checked={checked[0]}
          onChange={(e) => setChecked((c) => [e.target.checked, c[1], c[2]])}
        >
          연결 테스트 결과를 확인했습니다.
        </Checkbox>
        <Checkbox
          checked={checked[1]}
          onChange={(e) => setChecked((c) => [c[0], e.target.checked, c[2]])}
        >
          지식 범위(<strong>{scopeLabel}</strong>)가 이 Channel에 적절합니다.
        </Checkbox>
        <Checkbox
          checked={checked[2]}
          onChange={(e) => setChecked((c) => [c[0], c[1], e.target.checked])}
        >
          대상 Channel이 <strong>{row.channel.channel_name}</strong> (
          <Mono>{row.channel.channel_id}</Mono>) 임을 확인했습니다.
        </Checkbox>
      </Space>
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
      <p style={{ color: 'var(--text-sub)' }}>
        실제 값(Webhook URL)은 K8s Secret으로만 관리됩니다. 여기서는 Secret의 <b>이름</b>만
        등록/갱신하며, 값은 어떤 응답에도 노출되지 않습니다 (FR-OPS-010).
      </p>
      <Form form={form} layout="vertical">
        <Form.Item
          label="Secret Ref"
          name="secret_ref"
          rules={[{ required: true, message: 'secret_ref는 필수입니다.' }]}
        >
          <Input className="mono" placeholder="예: mattermost-incoming-rag-cloud-ops" />
        </Form.Item>
      </Form>
    </Modal>
  );
}
