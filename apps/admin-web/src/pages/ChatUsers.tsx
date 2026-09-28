import { useState } from 'react';
import { App, Button, Form, Input, Modal, Select, Space, Switch, Table, Tooltip, Typography } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { KeyOutlined, ReloadOutlined, UserAddOutlined } from '@ant-design/icons';
import { PageHeader } from '../components/PageHeader';
import { QueryState, errorMessage } from '../components/QueryState';
import { Mono, StatusBadge } from '../components/ui';
import { useWhoami } from '../api/auth';
import { useChatUsers, useCreateChatUser, useResetChatUserPassword, useUpdateChatUser } from '../api/chatUsers';
import type { ChatUserView, ChatUserWithTempPassword, Role } from '../types';

const { Paragraph } = Typography;

/**
 * Web Chat 사용자 관리 (TDD §7.5).
 * 임시 비밀번호는 생성/재설정 직후 한 번만 표시된다 — 서버는 해시만 저장한다.
 * 사용자는 chat-web 첫 로그인 후 [내 정보]에서 비밀번호를 변경한다.
 */
export function ChatUsers() {
  const { message } = App.useApp();
  const users = useChatUsers();
  const create = useCreateChatUser();
  const update = useUpdateChatUser();
  const reset = useResetChatUserPassword();
  const { data: me } = useWhoami();
  const roles = (me?.roles ?? []) as Role[];
  const canWrite = roles.length === 0 || roles.includes('SYS_ADMIN');
  const [createOpen, setCreateOpen] = useState(false);
  const [issued, setIssued] = useState<ChatUserWithTempPassword | null>(null);
  const [form] = Form.useForm();

  const onCreate = async () => {
    const values = await form.validateFields();
    try {
      const res = await create.mutateAsync(values);
      setCreateOpen(false);
      form.resetFields();
      setIssued(res);
    } catch (e) {
      message.error(errorMessage(e));
    }
  };

  const onReset = (u: ChatUserView) =>
    Modal.confirm({
      title: `${u.display_name} 비밀번호 재설정`,
      content: '새 임시 비밀번호를 발급합니다. 기존 비밀번호로는 더 이상 로그인할 수 없습니다.',
      okText: '재설정',
      cancelText: '취소',
      onOk: () =>
        reset
          .mutateAsync(u.id)
          .then(setIssued)
          .catch((e) => message.error(errorMessage(e))),
    });

  const columns: ColumnsType<ChatUserView> = [
    { title: '이름', dataIndex: 'display_name', render: (v: string, u) => (<span>{v}{u.is_bot && <StatusBadge kind="info" label="BOT" />}</span>) },
    { title: '이메일', dataIndex: 'email', render: (v: string) => <Mono style={{ fontSize: 12.5 }}>{v}</Mono> },
    { title: '역할', dataIndex: 'role', render: (v: string) => <StatusBadge kind={v === 'admin' ? 'info' : 'neutral'} label={v} /> },
    {
      title: '상태',
      key: 'state',
      render: (_, u) => (
        <Space size={4}>
          <StatusBadge kind={u.is_active ? 'success' : 'neutral'} label={u.is_active ? 'active' : 'inactive'} />
          {u.must_change_password && !u.is_bot && <StatusBadge kind="warning" label="임시 비밀번호" />}
        </Space>
      ),
    },
    { title: '생성', dataIndex: 'created_at', render: (v: string | null) => (v ? new Date(v).toLocaleString('ko-KR') : '-') },
    {
      title: '활성',
      key: 'active',
      align: 'center',
      render: (_, u) =>
        u.is_bot ? '-' : (
          <Switch
            checked={u.is_active}
            disabled={!canWrite}
            loading={update.isPending}
            onChange={(v) => update.mutateAsync({ id: u.id, body: { is_active: v } }).catch((e) => message.error(errorMessage(e)))}
          />
        ),
    },
    {
      title: '액션',
      key: 'actions',
      align: 'right',
      render: (_, u) =>
        u.is_bot ? null : (
          <Button size="small" icon={<KeyOutlined />} disabled={!canWrite} onClick={() => onReset(u)}>
            비밀번호 재설정
          </Button>
        ),
    },
  ];

  return (
    <>
      <PageHeader
        title="채팅 사용자"
        subtitle="Web Chat(chat-web) 로그인 계정 · 채널 멤버십은 [채널 연동 › 멤버]에서 부여"
        extra={
          <Space>
            <Button icon={<ReloadOutlined />} onClick={() => users.refetch()} />
            <Tooltip title={canWrite ? undefined : '권한 필요: SYS_ADMIN'}>
              <Button type="primary" icon={<UserAddOutlined />} disabled={!canWrite} onClick={() => setCreateOpen(true)}>
                사용자 추가
              </Button>
            </Tooltip>
          </Space>
        }
      />
      <QueryState isLoading={users.isLoading} error={users.error} isEmpty={(users.data?.length ?? 0) === 0} emptyText="사용자가 없습니다.">
        <Table rowKey="id" columns={columns} dataSource={users.data} pagination={{ pageSize: 20 }} />
      </QueryState>

      <Modal title="채팅 사용자 추가" open={createOpen} onOk={onCreate} confirmLoading={create.isPending} onCancel={() => setCreateOpen(false)} okText="추가" cancelText="취소">
        <Form form={form} layout="vertical" initialValues={{ role: 'user' }}>
          <Form.Item label="이메일 (로그인 ID)" name="email" rules={[{ required: true, type: 'email', message: '이메일을 입력하세요.' }]}>
            <Input className="mono" placeholder="hong@example.com" />
          </Form.Item>
          <Form.Item label="표시 이름" name="display_name" rules={[{ required: true, message: '표시 이름을 입력하세요.' }]}>
            <Input placeholder="홍길동" />
          </Form.Item>
          <Form.Item label="역할" name="role" tooltip="admin: 모든 채널에서 메시지 삭제(moderate) 가능">
            <Select options={[{ label: 'user', value: 'user' }, { label: 'admin', value: 'admin' }]} />
          </Form.Item>
        </Form>
      </Modal>

      <Modal title="임시 비밀번호 발급" open={!!issued} onOk={() => setIssued(null)} onCancel={() => setIssued(null)} okText="확인 (다시 볼 수 없음)" cancelButtonProps={{ style: { display: 'none' } }}>
        {issued && (
          <>
            <p>
              <strong>{issued.display_name}</strong> (<Mono>{issued.email}</Mono>) 의 임시 비밀번호입니다. 안전한 경로로 전달하세요.
              이 창을 닫으면 <strong>다시 확인할 수 없습니다</strong>.
            </p>
            <Paragraph copyable={{ text: issued.temporary_password }} style={{ fontSize: 16 }}>
              <Mono>{issued.temporary_password}</Mono>
            </Paragraph>
            <p style={{ color: 'var(--text-sub)', fontSize: 12.5 }}>첫 로그인 시 chat-web [내 정보]에서 비밀번호 변경이 요구됩니다.</p>
          </>
        )}
      </Modal>
    </>
  );
}
