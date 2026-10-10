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
import { PlusOutlined, ReloadOutlined, TeamOutlined } from '@ant-design/icons';
import { QueryState, errorMessage } from '../components/QueryState';
import { KnowledgeScopeEditor } from '../components/KnowledgeScopeEditor';
import { StatusBadge, Surface, Mono } from '../components/ui';
import { useWhoami } from '../api/auth';
import {
  useAddMembers,
  useChannelMembers,
  useChannels,
  useCreateBinding,
  useCreateChannel,
  useRemoveMember,
  useSetBindingEnabled,
  useUpdateBinding,
  useUpdateChannel,
} from '../api/channels';
import { useChatUsers } from '../api/chatUsers';
import type { BindingView, ChannelMode, ChannelView, KnowledgeScope, Role } from '../types';

const MODE_OPTIONS: { label: string; value: ChannelMode }[] = [
  { label: '전용 채널 — 모든 메시지에 응답 (DEDICATED_CHANNEL)', value: 'DEDICATED_CHANNEL' },
  { label: '트리거 단어 — 지정 접두어 메시지에만 응답 (TRIGGER_WORD)', value: 'TRIGGER_WORD' },
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

/**
 * Web Chat 채널 관리 (TDD §7.5, §9.6).
 * 채널 = chat-web 사용자 대화 공간 · Binding = 채널의 RAG 응답 설정 · 멤버십 = Channel 격리 경계.
 */
export function Channels() {
  const { message } = App.useApp();
  const channels = useChannels();
  const { data: me } = useWhoami();
  const setEnabled = useSetBindingEnabled();

  const roles = (me?.roles ?? []) as Role[];
  const canWrite = roles.includes('SYS_ADMIN'); // 쓰기 API 는 SYS_ADMIN 전용 (조회는 DOC_ADMIN 도 가능)

  const [q, setQ] = useState('');
  const [fStatus, setFStatus] = useState('');
  const [wizard, setWizard] = useState<
    | { mode: 'new-channel' }
    | { mode: 'new-binding'; channel: ChannelView }
    | { mode: 'edit'; channel: ChannelView; binding: BindingView }
    | null
  >(null);
  const [membersOf, setMembersOf] = useState<ChannelView | null>(null);
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
    const lq = q.toLowerCase();
    const matchesQ =
      !q || r.channel.name.toLowerCase().includes(lq) || r.channel.display_name.toLowerCase().includes(lq);
    const enabled = !!r.binding?.enabled;
    const matchesStatus = !fStatus || (fStatus === 'active' ? enabled : !enabled);
    return matchesQ && matchesStatus;
  });

  const toggle = (row: Row, next: boolean) => {
    if (!row.binding) return;
    if (next) {
      setActivate(row); // activation requires the confirm modal (§5.4)
      return;
    }
    Modal.confirm({
      title: `#${row.channel.name} Binding 비활성화`,
      content: '비활성화하면 이후 이 채널의 질문에 RAG 가 응답하지 않습니다 (일반 대화는 계속 가능).',
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
      title: '채널',
      key: 'channel',
      render: (_, r) => (
        <div>
          <Button
            type="link"
            style={{ padding: 0, fontWeight: 600 }}
            disabled={!r.binding || !canWrite}
            onClick={() => r.binding && setWizard({ mode: 'edit', channel: r.channel, binding: r.binding })}
          >
            #{r.channel.name}
          </Button>
          <div style={{ fontSize: 12, color: 'var(--text-sub)' }}>{r.channel.display_name}</div>
          <Mono style={{ fontSize: 11, color: 'var(--text-disabled)' }}>{r.channel.id}</Mono>
        </div>
      ),
    },
    {
      title: '공개',
      key: 'type',
      render: (_, r) => (
        <StatusBadge kind={r.channel.type === 'private' ? 'warning' : 'neutral'} label={r.channel.type} />
      ),
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
            {r.binding.mode === 'TRIGGER_WORD' ? `트리거 ${r.binding.trigger_word ?? ''}`.trim() : '전용'}
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
      render: (_, r) => (r.binding ? <Mono style={{ fontSize: 12.5 }}>{r.binding.history_turns}</Mono> : '-'),
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
      title: 'RAG 응답',
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
          <StatusBadge kind="warning" label="미설정" />
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
              onClick={() => setWizard({ mode: 'edit', channel: r.channel, binding: r.binding! })}
            >
              편집
            </Button>
          )}
          <Button size="small" icon={<TeamOutlined />} onClick={() => setMembersOf(r.channel)}>
            멤버
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
          읽기 전용 모드 — 채널 생성·Binding·멤버 관리에는 <strong>SYS_ADMIN</strong> 권한이 필요합니다.
        </div>
      )}

      <Surface padding="12px 16px" style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
        <Input placeholder="채널 검색" value={q} onChange={(e) => setQ(e.target.value)} allowClear style={{ width: 220 }} />
        <select style={filterSelectStyle} value={fStatus} onChange={(e) => setFStatus(e.target.value)}>
          <option value="">RAG 응답: 전체</option>
          <option value="active">활성</option>
          <option value="inactive">비활성</option>
        </select>
        <div style={{ flex: 1 }} />
        <Button icon={<ReloadOutlined />} onClick={() => channels.refetch()} title="새로고침" />
        <Tooltip title={canWrite ? undefined : '권한 필요: SYS_ADMIN'}>
          <Button type="primary" icon={<PlusOutlined />} disabled={!canWrite} onClick={() => setWizard({ mode: 'new-channel' })}>
            채널 만들기
          </Button>
        </Tooltip>
      </Surface>

      <QueryState
        isLoading={channels.isLoading}
        error={channels.error}
        isEmpty={rows.length === 0}
        emptyText="등록된 채널이 없습니다. [채널 만들기]로 시작하세요."
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

      {wizard && <BindingWizard state={wizard} onClose={() => setWizard(null)} />}
      {membersOf && <MembersDrawer channel={membersOf} canWrite={canWrite} onClose={() => setMembersOf(null)} />}
      {activate && (
        <ActivationModal
          row={activate}
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

/** 3-step wizard: 채널 정보 → 동작 설정 → 지식 범위 (§5.4). Mattermost Secret 단계는 제거됨. */
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
  const updateChannel = useUpdateChannel();
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
    security_levels: [],
    document_ids: [],
  });

  const submitting =
    createChannel.isPending || updateChannel.isPending || createBinding.isPending || updateBinding.isPending;

  const STEPS = ['채널 정보', '동작 설정', '지식 범위'];

  const next = async () => {
    const fieldsByStep: string[][] = [
      ['name', 'display_name', 'type', 'purpose'],
      ['mode', 'trigger_word', 'history_turns'],
      ['knowledge_scope_id'],
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
      if (channel && (values.display_name !== channel.display_name || values.purpose !== channel.purpose || values.type !== channel.type)) {
        await updateChannel.mutateAsync({
          channelId: channel.id,
          body: { display_name: values.display_name, purpose: values.purpose || null, type: values.type },
        });
      }
      if (isEdit && binding) {
        await updateBinding.mutateAsync({ bindingId: binding.id, body: bindingBody });
        message.success('Binding이 수정되었습니다.');
      } else {
        let channelId = channel?.id;
        if (state.mode === 'new-channel') {
          const created = await createChannel.mutateAsync({
            name: values.name,
            display_name: values.display_name,
            type: values.type,
            purpose: values.purpose || null,
          });
          channelId = created.id;
        }
        if (!channelId) throw new Error('채널을 확인할 수 없습니다.');
        await createBinding.mutateAsync({ channelId, body: { ...bindingBody, enabled: false } });
        message.success('채널/Binding이 생성되었습니다. (RAG 응답 비활성 — 멤버 추가 후 활성화하세요)');
      }
      onClose();
    } catch (e) {
      message.error(errorMessage(e));
    }
  };

  return (
    <Drawer
      title={isEdit ? `Binding 편집 — #${channel?.name}` : state.mode === 'new-channel' ? '채널 만들기' : `Binding 추가 — #${channel?.name}`}
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
      <Steps size="small" current={step} items={STEPS.map((t) => ({ title: t }))} style={{ marginBottom: 24 }} />
      <Form
        form={form}
        layout="vertical"
        initialValues={{
          name: channel?.name ?? '',
          display_name: channel?.display_name ?? '',
          type: channel?.type ?? 'public',
          purpose: channel?.purpose ?? '',
          mode: binding?.mode ?? 'DEDICATED_CHANNEL',
          trigger_word: binding?.trigger_word ?? '',
          history_turns: binding?.history_turns ?? 8,
          knowledge_scope_id: binding?.knowledge_scope_id ?? '',
          mention_user: binding?.mention_user ?? true,
          ack_message_enabled: binding?.ack_message_enabled ?? true,
          feedback_enabled: binding?.feedback_enabled ?? true,
        }}
      >
        {/* Step 1 — 채널 정보 */}
        <div style={{ display: step === 0 ? 'block' : 'none' }}>
          <Form.Item
            label="채널 이름 (URL slug)"
            name="name"
            rules={[
              { required: true, message: '채널 이름은 필수입니다.' },
              { pattern: /^[a-z0-9][a-z0-9_-]{1,79}$/, message: '소문자·숫자·-·_ 만 (2~80자)' },
            ]}
            tooltip="chat-web 주소가 됩니다: /ch/{이름}. 생성 후 변경할 수 없습니다."
          >
            <Input className="mono" disabled={state.mode !== 'new-channel'} placeholder="예: rag-cloud-ops" />
          </Form.Item>
          <Form.Item label="표시 이름" name="display_name" rules={[{ required: true, message: '표시 이름은 필수입니다.' }]}>
            <Input placeholder="예: Cloud 운영 Q&A" />
          </Form.Item>
          <Form.Item label="공개 범위" name="type" tooltip="어느 경우든 채널을 볼 수 있는 사람은 멤버뿐입니다.">
            <Select options={[{ label: 'public', value: 'public' }, { label: 'private', value: 'private' }]} />
          </Form.Item>
          <Form.Item label="설명" name="purpose">
            <Input.TextArea rows={2} maxLength={500} placeholder="채널 헤더에 표시됩니다" />
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
                <Form.Item label="트리거 단어" name="trigger_word" rules={[{ required: true, message: '트리거 단어를 입력하세요.' }]}>
                  <Input placeholder="예: !rag" />
                </Form.Item>
              ) : null
            }
          </Form.Item>
          <Form.Item label="대화 이력 turns (0–20)" name="history_turns">
            <Slider min={0} max={20} marks={{ 0: '0', 8: '8', 20: '20' }} />
          </Form.Item>
          <Form.Item label="답변에 질문자 멘션(mention_user)" name="mention_user" valuePropName="checked">
            <Switch />
          </Form.Item>
          <Form.Item label="접수 안내 표시(ack_message)" name="ack_message_enabled" valuePropName="checked" tooltip="답변 생성 전 '질문을 접수했습니다' 안내를 표시합니다.">
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
            tooltip="지정 시 해당 scope로 검색을 제한합니다. 비우면 채널 ACL 기본값 (conversation_mode 도 scope 에서 결정)."
          >
            <Input className="mono" placeholder="knowledge_scopes.id (UUID) — 비우면 전체" allowClear />
          </Form.Item>
          <KnowledgeScopeEditor value={scope} onChange={setScope} />
          <div style={{ fontSize: 12, color: 'var(--text-sub)', marginTop: 8 }}>
            아래 편집기는 검색 범위를 미리 구성/검토하기 위한 것입니다. 최종 반영은 Scope API 연동 후 지원됩니다
            (현재는 <code>knowledge_scope_id</code> 로 연결). 문서 노출 채널은 [문서 관리]의 허용 채널(ACL)로 지정합니다.
          </div>
        </div>
      </Form>
    </Drawer>
  );
}

function ActivationModal({
  row,
  onClose,
  onConfirm,
  confirming,
}: {
  row: Row;
  onClose: () => void;
  onConfirm: () => void;
  confirming: boolean;
}) {
  const [checked, setChecked] = useState<boolean[]>([false, false]);
  const members = useChannelMembers(row.channel.id);
  const memberCount = members.data?.length ?? 0;
  const allChecked = checked.every(Boolean);
  const scopeLabel = row.binding?.knowledge_scope_id ? 'Scope 지정 범위' : '전체 ACL 범위';

  return (
    <Modal
      title="RAG 응답 활성화 확인"
      open
      onCancel={onClose}
      okText="활성화"
      cancelText="취소"
      okButtonProps={{ disabled: !allChecked, loading: confirming }}
      onOk={onConfirm}
    >
      <p style={{ color: 'var(--text-sub)', marginTop: 0 }}>
        활성화하면 <strong>#{row.channel.name}</strong> 채널의 질문에 RAG 가 사내 문서 근거로 답변합니다.
      </p>
      <div
        style={{
          padding: '10px 12px',
          borderRadius: 8,
          marginBottom: 12,
          background: memberCount > 0 ? 'var(--tint-success)' : 'var(--tint-warning)',
          border: `1px solid ${memberCount > 0 ? '#bbf7d0' : '#fde5bf'}`,
          fontSize: 13,
        }}
      >
        현재 멤버 <strong>{memberCount}</strong>명
        {memberCount === 0 && ' — 멤버가 없으면 아무도 이 채널을 사용할 수 없습니다. [멤버]에서 추가하세요.'}
      </div>
      <Space direction="vertical" size={10}>
        <Checkbox checked={checked[0]} onChange={(e) => setChecked((c) => [e.target.checked, c[1]])}>
          지식 범위(<strong>{scopeLabel}</strong>)가 이 채널 멤버에게 공개되어도 됩니다.
        </Checkbox>
        <Checkbox checked={checked[1]} onChange={(e) => setChecked((c) => [c[0], e.target.checked])}>
          대상 채널이 <strong>#{row.channel.name}</strong> (<Mono>{row.channel.id.slice(0, 8)}…</Mono>) 임을 확인했습니다.
        </Checkbox>
      </Space>
    </Modal>
  );
}

/** 채널 멤버 관리 — 멤버십이 곧 열람/질문 권한이며 Channel 격리 경계다. */
function MembersDrawer({ channel, canWrite, onClose }: { channel: ChannelView; canWrite: boolean; onClose: () => void }) {
  const { message } = App.useApp();
  const members = useChannelMembers(channel.id);
  const users = useChatUsers();
  const add = useAddMembers();
  const remove = useRemoveMember();
  const [picked, setPicked] = useState<string[]>([]);
  const memberIds = new Set((members.data ?? []).map((m) => m.user_id));
  const options = (users.data ?? [])
    .filter((u) => !u.is_bot && u.is_active && !memberIds.has(u.id))
    .map((u) => ({ label: `${u.display_name} <${u.email}>`, value: u.id }));

  const onAdd = async () => {
    try {
      const res = await add.mutateAsync({ channelId: channel.id, userIds: picked });
      message.success(`${res.added}명 추가되었습니다.`);
      setPicked([]);
      members.refetch();
    } catch (e) {
      message.error(errorMessage(e));
    }
  };

  return (
    <Drawer title={`멤버 — #${channel.name}`} width={560} open onClose={onClose}>
      {canWrite && (
        <Space.Compact style={{ width: '100%', marginBottom: 16 }}>
          <Select
            mode="multiple"
            style={{ width: '100%' }}
            placeholder="추가할 사용자 선택 (채팅 사용자 메뉴에서 생성)"
            options={options}
            value={picked}
            onChange={setPicked}
            loading={users.isLoading}
            optionFilterProp="label"
          />
          <Button type="primary" disabled={!picked.length} loading={add.isPending} onClick={onAdd}>
            추가
          </Button>
        </Space.Compact>
      )}
      <QueryState isLoading={members.isLoading} error={members.error} isEmpty={(members.data?.length ?? 0) === 0} emptyText="멤버가 없습니다.">
        <Table
          rowKey="user_id"
          size="small"
          pagination={false}
          dataSource={members.data}
          columns={[
            { title: '이름', dataIndex: 'display_name' },
            { title: '이메일', dataIndex: 'email', render: (v: string) => <Mono style={{ fontSize: 12 }}>{v}</Mono> },
            { title: '역할', dataIndex: 'role', render: (v: string) => <StatusBadge kind={v === 'channel_admin' ? 'info' : 'neutral'} label={v} /> },
            {
              title: '',
              key: 'x',
              align: 'right',
              render: (_, m) =>
                canWrite ? (
                  <Button
                    size="small"
                    danger
                    loading={remove.isPending}
                    onClick={() =>
                      remove
                        .mutateAsync({ channelId: channel.id, userId: m.user_id })
                        .then(() => {
                          message.success('제거되었습니다.');
                          members.refetch();
                        })
                        .catch((e) => message.error(errorMessage(e)))
                    }
                  >
                    제거
                  </Button>
                ) : null,
            },
          ]}
        />
      </QueryState>
    </Drawer>
  );
}
