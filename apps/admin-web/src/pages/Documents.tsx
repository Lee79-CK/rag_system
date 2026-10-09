import { useEffect, useMemo, useState } from 'react';
import {
  App,
  Button,
  Checkbox,
  Descriptions,
  Drawer,
  Form,
  Input,
  Modal,
  Popconfirm,
  Select,
  Space,
  Table,
  Tag,
  Tooltip,
  Upload,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import type { UploadFile } from 'antd/es/upload/interface';
import { InboxOutlined, LinkOutlined, PlusOutlined, ReloadOutlined } from '@ant-design/icons';
import { ApiError } from '../api/client';
import { QueryState, errorMessage } from '../components/QueryState';
import { StatusBadge, Surface, Mono } from '../components/ui';
import {
  useActivateDocument,
  useDeactivateDocument,
  useDeleteDocument,
  useDocumentVersions,
  useDocuments,
  useReindexDocument,
  useUpdateDocumentChannels,
  useUploadDocument,
} from '../api/documents';
import { useChannels } from '../api/channels';
import type {
  ChannelView,
  DocumentView,
  DuplicateDocumentDetail,
  SecurityLevel,
  UpdateDocumentChannelsResult,
} from '../types';

const SECURITY_LEVELS: SecurityLevel[] = ['PUBLIC', 'INTERNAL', 'CONFIDENTIAL', 'SECRET'];
const STATUS_OPTIONS = ['ACTIVE', 'INDEXING', 'UPLOADED', 'INACTIVE', 'FAILED', 'DELETED'];

const SKIP_REASON: Record<string, string> = {
  NO_ACTIVE_VERSION: '활성 버전이 없어 재색인하지 않았습니다.',
  STATUS_UPLOADED: '아직 색인 전 문서라 재색인하지 않았습니다. 색인 시 새 채널이 적용됩니다.',
  STATUS_INACTIVE: '비활성 문서라 채널만 저장했습니다. [활성화] 하면 새 채널로 다시 색인됩니다.',
  PENDING_JOB_REUSED: '대기 중인 색인 Job 이 실행될 때 새 채널이 반영됩니다.',
};

/** PATCH 결과를 사용자 메시지로. 검색 반영은 재색인 완료 후라는 점을 함께 알린다. */
function channelUpdateMessage(r: UpdateDocumentChannelsResult): string {
  if (!r.changed) return '변경 사항이 없습니다.';
  const diff = `채널 +${r.added.length} / -${r.removed.length}`;
  if (r.reindex_skipped_reason) {
    return `${diff} 저장 · ${SKIP_REASON[r.reindex_skipped_reason] ?? r.reindex_skipped_reason}`;
  }
  if (r.index_job?.error) return `${diff} 저장 · 재색인 트리거 실패: ${r.index_job.error}`;
  return `${diff} 저장 · 재색인 시작 (완료 후 검색에 반영)`;
}

function channelOptions(channels: ChannelView[] | undefined) {
  return (channels ?? []).map((c) => ({
    label: `#${c.name} · ${c.display_name}`,
    value: c.id, // chat_channels.id = Qdrant allowed_channel_ids (Channel 격리 키)
  }));
}

function ChannelTags({ ids, channels }: { ids: string[]; channels?: ChannelView[] }) {
  if (ids.length === 0) return <span style={{ color: 'var(--text-sub)' }}>-</span>;
  return (
    <Space size={4} wrap>
      {ids.map((id) => {
        const c = channels?.find((ch) => ch.id === id);
        return c ? (
          <Tag key={id} color="blue">
            #{c.name}
          </Tag>
        ) : (
          <Tag key={id} title={id}>
            삭제된 채널
          </Tag>
        );
      })}
    </Space>
  );
}

const filterSelectStyle: React.CSSProperties = {
  padding: '7px 10px',
  border: '1px solid var(--border)',
  borderRadius: 6,
  fontSize: 13,
  background: 'var(--surface)',
  color: 'var(--text)',
};

export function Documents() {
  const { message, modal } = App.useApp();
  const docs = useDocuments();
  const channels = useChannels();
  const upload = useUploadDocument();
  const reindex = useReindexDocument();
  const deactivate = useDeactivateDocument();
  const activate = useActivateDocument();
  const remove = useDeleteDocument();
  const updateChannels = useUpdateDocumentChannels();

  const [uploadOpen, setUploadOpen] = useState(false);
  const [detailId, setDetailId] = useState<string | undefined>();
  const [channelsDoc, setChannelsDoc] = useState<DocumentView | undefined>();
  const [fileList, setFileList] = useState<UploadFile[]>([]);
  const [form] = Form.useForm();

  // Filter bar state (client-side filtering over the loaded list).
  const [q, setQ] = useState('');
  const [fCat, setFCat] = useState('');
  const [fDept, setFDept] = useState('');
  const [fLevel, setFLevel] = useState('');
  const [fStatus, setFStatus] = useState('');
  const [autoRefresh, setAutoRefresh] = useState(false);

  useEffect(() => {
    if (!autoRefresh) return;
    const t = setInterval(() => docs.refetch(), 10_000);
    return () => clearInterval(t);
  }, [autoRefresh, docs]);

  const data = useMemo(() => docs.data ?? [], [docs.data]);
  const categories = useMemo(
    () => [...new Set(data.map((d) => d.category).filter(Boolean))] as string[],
    [data],
  );
  const departments = useMemo(
    () => [...new Set(data.map((d) => d.department).filter(Boolean))] as string[],
    [data],
  );

  const filtered = useMemo(
    () =>
      data.filter(
        (d) =>
          (!q || d.title.toLowerCase().includes(q.toLowerCase())) &&
          (!fCat || d.category === fCat) &&
          (!fDept || d.department === fDept) &&
          (!fLevel || d.security_level === fLevel) &&
          (!fStatus || d.status === fStatus),
      ),
    [data, q, fCat, fDept, fLevel, fStatus],
  );

  const submitUpload = async () => {
    const values = await form.validateFields();
    const file = fileList[0]?.originFileObj;
    if (!file) {
      message.error('업로드할 파일을 선택하세요.');
      return;
    }
    try {
      const r = await upload.mutateAsync({
        file: file as File,
        title: values.title,
        category: values.category,
        department: values.department,
        security_level: values.security_level,
        allowed_channel_ids: values.allowed_channel_ids,
        start_indexing: values.start_indexing,
      });
      message.success(
        r.index_job_id
          ? '업로드 완료 · 색인 시작 (완료되면 상태가 ACTIVE 로 바뀝니다)'
          : '업로드 완료 · 색인하려면 [재색인] 을 누르세요',
      );
      closeUpload();
    } catch (e) {
      if (e instanceof ApiError && e.code === 'DUPLICATE_DOCUMENT') {
        offerLinkExisting(e.detail as unknown as DuplicateDocumentDetail, values.allowed_channel_ids ?? []);
        return;
      }
      message.error(errorMessage(e));
    }
  };

  const closeUpload = () => {
    setUploadOpen(false);
    setFileList([]);
    form.resetFields();
  };

  /** FR-DOC-003 해시 중복 → 재업로드 대신 기존 문서에 선택 채널을 추가 연결 (기존 ACL ∪ 선택). */
  const offerLinkExisting = (dup: DuplicateDocumentDetail, selected: string[]) => {
    const title = dup.existing_document_title ?? dup.existing_document_id;
    if (dup.existing_document_status === 'DELETED') {
      message.error(`동일한 내용의 삭제된 문서 '${title}' 가 있어 업로드할 수 없습니다.`);
      return;
    }
    const existing = data.find((d) => d.id === dup.existing_document_id);
    const merged = [...new Set([...(existing?.allowed_channel_ids ?? []), ...selected])];
    const newOnes = merged.filter((id) => !(existing?.allowed_channel_ids ?? []).includes(id));
    if (selected.length === 0 || newOnes.length === 0) {
      message.warning(
        `동일한 문서 '${title}' 가 이미 있습니다.${selected.length ? ' 선택한 채널에 이미 연결되어 있습니다.' : ''}`,
      );
      return;
    }
    modal.confirm({
      title: '이미 등록된 문서입니다',
      content: (
        <div>
          <p>
            동일한 내용의 문서 <b>{title}</b> 가 이미 있습니다. 다시 업로드하는 대신 선택한 채널을
            이 문서에 추가 연결할까요?
          </p>
          <ChannelTags ids={newOnes} channels={channels.data} />
        </div>
      ),
      okText: '채널 연결',
      cancelText: '취소',
      onOk: async () => {
        try {
          const r = await updateChannels.mutateAsync({
            id: dup.existing_document_id,
            channelIds: merged,
          });
          message.success(channelUpdateMessage(r));
          closeUpload();
        } catch (err) {
          message.error(errorMessage(err));
        }
      },
    });
  };

  const runAction = async (label: string, fn: () => Promise<unknown>) => {
    try {
      await fn();
      message.success(`${label} 완료`);
    } catch (e) {
      message.error(errorMessage(e));
    }
  };

  const columns: ColumnsType<DocumentView> = [
    {
      title: '제목',
      dataIndex: 'title',
      sorter: (a, b) => a.title.localeCompare(b.title),
      render: (v: string, row) => (
        <Button
          type="link"
          style={{ padding: 0, fontWeight: 600 }}
          onClick={() => setDetailId(row.id)}
        >
          {v}
        </Button>
      ),
    },
    { title: '카테고리', dataIndex: 'category', render: (v) => v ?? '-' },
    { title: '부서', dataIndex: 'department', render: (v) => v ?? '-' },
    {
      title: '보안등급',
      dataIndex: 'security_level',
      render: (v: string) => (
        <Mono
          style={{
            fontSize: 11.5,
            fontWeight: 700,
            color: 'var(--text-sub)',
            background: 'var(--tint-neutral)',
            padding: '2px 8px',
            borderRadius: 5,
          }}
        >
          {v}
        </Mono>
      ),
    },
    {
      title: '허용 채널',
      dataIndex: 'allowed_channel_ids',
      render: (ids: string[]) => <ChannelTags ids={ids ?? []} channels={channels.data} />,
    },
    {
      title: '상태',
      dataIndex: 'status',
      sorter: (a, b) => (a.status ?? '').localeCompare(b.status ?? ''),
      render: (v: string) => <StatusBadge status={v} />,
    },
    {
      title: '등록일',
      dataIndex: 'created_at',
      align: 'right',
      sorter: (a, b) => (a.created_at ?? '').localeCompare(b.created_at ?? ''),
      render: (v: string | null) => (
        <Mono style={{ fontSize: 12.5, color: 'var(--text-sub)' }}>
          {v ? new Date(v).toLocaleString('ko-KR') : '-'}
        </Mono>
      ),
    },
    {
      title: '액션',
      key: 'actions',
      align: 'right',
      render: (_, row) => (
        <Space size="small" wrap>
          <Button size="small" onClick={() => setDetailId(row.id)}>
            상세
          </Button>
          <Button
            size="small"
            icon={<LinkOutlined />}
            disabled={row.status === 'DELETED'}
            onClick={() => setChannelsDoc(row)}
          >
            채널
          </Button>
          {/* 재색인은 문서를 ACTIVE 로 되살리므로 비활성/삭제 문서에는 막는다 (비활성은 [활성화]) */}
          <Tooltip
            title={
              row.status === 'INACTIVE'
                ? '비활성 문서는 [활성화] 로 다시 색인합니다'
                : row.status === 'DELETED'
                  ? '삭제된 문서'
                  : undefined
            }
          >
            <Button
              size="small"
              icon={<ReloadOutlined />}
              loading={reindex.isPending}
              disabled={row.status === 'INACTIVE' || row.status === 'DELETED'}
              onClick={() => runAction('재색인 요청', () => reindex.mutateAsync(row.id))}
            >
              재색인
            </Button>
          </Tooltip>
          {row.status === 'INACTIVE' ? (
            <Popconfirm
              title="다시 활성화하시겠습니까?"
              description="현재 허용 채널로 다시 색인하며, 색인이 끝나면 검색에 포함됩니다."
              onConfirm={() => runAction('활성화(재색인) 요청', () => activate.mutateAsync(row.id))}
            >
              <Button size="small" loading={activate.isPending}>
                활성화
              </Button>
            </Popconfirm>
          ) : (
            <Popconfirm
              title="비활성화하시겠습니까?"
              description="검색에서 즉시 제외됩니다. [활성화] 로 되돌릴 수 있습니다."
              disabled={row.status === 'DELETED'}
              onConfirm={() => runAction('비활성화', () => deactivate.mutateAsync(row.id))}
            >
              <Button size="small" disabled={row.status === 'DELETED'}>
                비활성화
              </Button>
            </Popconfirm>
          )}
          <Popconfirm
            title="문서를 삭제하시겠습니까?"
            description="검색에서 즉시 제외되며 되돌릴 수 없습니다. 같은 파일은 다시 업로드할 수 없습니다."
            okButtonProps={{ danger: true }}
            disabled={row.status === 'DELETED'}
            onConfirm={() => runAction('삭제', () => remove.mutateAsync(row.id))}
          >
            <Button size="small" danger disabled={row.status === 'DELETED'}>
              삭제
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <Surface padding="12px 16px" style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
        <Input
          placeholder="제목 검색"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          allowClear
          style={{ width: 220 }}
        />
        <select style={filterSelectStyle} value={fCat} onChange={(e) => setFCat(e.target.value)}>
          <option value="">카테고리: 전체</option>
          {categories.map((c) => (
            <option key={c} value={c}>{c}</option>
          ))}
        </select>
        <select style={filterSelectStyle} value={fDept} onChange={(e) => setFDept(e.target.value)}>
          <option value="">부서: 전체</option>
          {departments.map((d) => (
            <option key={d} value={d}>{d}</option>
          ))}
        </select>
        <select style={filterSelectStyle} value={fLevel} onChange={(e) => setFLevel(e.target.value)}>
          <option value="">보안등급: 전체</option>
          {SECURITY_LEVELS.map((l) => (
            <option key={l} value={l}>{l}</option>
          ))}
        </select>
        <select style={filterSelectStyle} value={fStatus} onChange={(e) => setFStatus(e.target.value)}>
          <option value="">상태: 전체</option>
          {STATUS_OPTIONS.map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>
        <div style={{ flex: 1 }} />
        <Button icon={<ReloadOutlined />} onClick={() => docs.refetch()} title="새로고침" />
        <div
          onClick={() => setAutoRefresh((v) => !v)}
          style={{ display: 'flex', alignItems: 'center', gap: 7, cursor: 'pointer' }}
        >
          <span style={{ fontSize: 12, color: 'var(--text-sub)' }}>자동갱신 10s</span>
          <Toggle on={autoRefresh} />
        </div>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setUploadOpen(true)}>
          문서 업로드
        </Button>
      </Surface>

      <QueryState
        isLoading={docs.isLoading}
        error={docs.error}
        isEmpty={data.length === 0}
        emptyText="등록된 문서가 없습니다. 우측 상단의 [문서 업로드]로 시작하세요."
      >
        <Surface padding={0} style={{ overflow: 'hidden' }}>
          <Table
            rowKey="id"
            columns={columns}
            dataSource={filtered}
            pagination={{ pageSize: 20, showTotal: (t) => `총 ${t}건 · 페이지당 20행` }}
          />
        </Surface>
      </QueryState>

      <Modal
        title="문서 업로드"
        open={uploadOpen}
        onOk={submitUpload}
        confirmLoading={upload.isPending}
        onCancel={() => setUploadOpen(false)}
        okText="업로드"
        cancelText="취소"
      >
        <Form
          form={form}
          layout="vertical"
          initialValues={{ security_level: 'INTERNAL', start_indexing: true }}
        >
          <Form.Item label="파일" required>
            <Upload.Dragger
              multiple={false}
              maxCount={1}
              beforeUpload={() => false}
              fileList={fileList}
              onChange={({ fileList: fl }) => setFileList(fl.slice(-1))}
              accept=".pdf,.docx,.pptx,.xlsx,.txt,.md,.html"
            >
              <p className="ant-upload-drag-icon">
                <InboxOutlined />
              </p>
              <p className="ant-upload-text">클릭 또는 드래그하여 업로드</p>
              <p className="ant-upload-hint">pdf, docx, pptx, xlsx, txt, md, html (최대 100MB)</p>
            </Upload.Dragger>
          </Form.Item>
          <Form.Item label="제목" name="title">
            <Input placeholder="미입력 시 파일명 사용" />
          </Form.Item>
          <Form.Item label="카테고리(category)" name="category">
            <Input />
          </Form.Item>
          <Form.Item label="부서(department)" name="department">
            <Input />
          </Form.Item>
          <Form.Item label="보안등급(security_level)" name="security_level">
            <Select options={SECURITY_LEVELS.map((s) => ({ label: s, value: s }))} />
          </Form.Item>
          <Form.Item
            label="허용 Channel (ACL)"
            name="allowed_channel_ids"
            tooltip="이 문서를 검색에 노출할 Channel을 명시적으로 선택합니다 (Channel 격리)."
          >
            <Select
              mode="multiple"
              allowClear
              loading={channels.isLoading}
              placeholder="허용 Channel을 명시 선택하세요"
              options={channelOptions(channels.data)}
            />
          </Form.Item>
          <Form.Item name="start_indexing" valuePropName="checked" style={{ marginBottom: 0 }}>
            <Checkbox>업로드 후 바로 색인 (해제하면 나중에 [재색인] 으로 색인)</Checkbox>
          </Form.Item>
        </Form>
      </Modal>

      <DocumentChannelsModal
        doc={channelsDoc}
        channels={channels.data}
        channelsLoading={channels.isLoading}
        onClose={() => setChannelsDoc(undefined)}
      />

      <DocumentDetail
        id={detailId}
        onClose={() => setDetailId(undefined)}
        docs={docs.data}
        channels={channels.data}
      />
    </div>
  );
}

function Toggle({ on }: { on: boolean }) {
  return (
    <span
      style={{
        position: 'relative',
        display: 'inline-block',
        width: 34,
        height: 18,
        borderRadius: 999,
        background: on ? 'var(--primary)' : '#cbd2dc',
        transition: 'background .15s',
      }}
    >
      <span
        style={{
          position: 'absolute',
          top: 2,
          left: on ? 18 : 2,
          width: 14,
          height: 14,
          borderRadius: '50%',
          background: '#fff',
          transition: 'left .15s',
        }}
      />
    </span>
  );
}

/** 허용 채널 전체 교체 (PATCH /documents/{id}) — 변경 시 서버가 자동 재색인. */
function DocumentChannelsModal({
  doc,
  channels,
  channelsLoading,
  onClose,
}: {
  doc?: DocumentView;
  channels?: ChannelView[];
  channelsLoading: boolean;
  onClose: () => void;
}) {
  const { message } = App.useApp();
  const update = useUpdateDocumentChannels();
  const [selected, setSelected] = useState<string[]>([]);

  useEffect(() => {
    setSelected(doc?.allowed_channel_ids ?? []);
  }, [doc]);

  const save = async () => {
    if (!doc) return;
    try {
      const r = await update.mutateAsync({ id: doc.id, channelIds: selected });
      message.success(channelUpdateMessage(r));
      onClose();
    } catch (e) {
      message.error(errorMessage(e));
    }
  };

  return (
    <Modal
      title={`허용 채널 — ${doc?.title ?? ''}`}
      open={!!doc}
      onOk={save}
      confirmLoading={update.isPending}
      onCancel={onClose}
      okText="저장"
      cancelText="취소"
      destroyOnClose
    >
      <p style={{ fontSize: 13, color: 'var(--text-sub)' }}>
        선택한 채널에서만 이 문서가 검색됩니다. 변경하면 재색인 Job 이 생성되고, 재색인이 끝나야
        검색에 반영됩니다(제거한 채널도 그때까지는 검색됨).
      </p>
      <Select
        mode="multiple"
        allowClear
        style={{ width: '100%' }}
        loading={channelsLoading}
        value={selected}
        onChange={setSelected}
        placeholder="허용 Channel 선택"
        options={channelOptions(channels)}
      />
      {selected.length === 0 && (
        <p style={{ marginTop: 8, fontSize: 12.5, color: 'var(--danger, #d4380d)' }}>
          채널을 모두 비우면 어느 채널에서도 검색되지 않습니다.
        </p>
      )}
    </Modal>
  );
}

function DocumentDetail({
  id,
  onClose,
  docs,
  channels,
}: {
  id?: string;
  onClose: () => void;
  docs?: DocumentView[];
  channels?: ChannelView[];
}) {
  const versions = useDocumentVersions(id);
  const doc = docs?.find((d) => d.id === id);

  const versionColumns: ColumnsType<NonNullable<typeof versions.data>[number]> = [
    { title: 'v', dataIndex: 'version', width: 60 },
    { title: '상태', dataIndex: 'status', render: (v: string) => <StatusBadge status={v} /> },
    {
      title: '크기',
      dataIndex: 'file_size',
      render: (v: number) => `${(v / 1024).toFixed(1)} KB`,
    },
    {
      title: 'hash',
      dataIndex: 'hash',
      render: (v: string) => <code>{v.slice(0, 12)}…</code>,
    },
    {
      title: '생성',
      dataIndex: 'created_at',
      render: (v: string | null) => (v ? new Date(v).toLocaleString('ko-KR') : '-'),
    },
  ];

  return (
    <Drawer title="문서 상세" width={640} open={!!id} onClose={onClose} destroyOnClose>
      {doc && (
        <Descriptions column={1} bordered size="small" style={{ marginBottom: 24 }}>
          <Descriptions.Item label="ID">
            <code>{doc.id}</code>
          </Descriptions.Item>
          <Descriptions.Item label="제목">{doc.title}</Descriptions.Item>
          <Descriptions.Item label="카테고리">{doc.category ?? '-'}</Descriptions.Item>
          <Descriptions.Item label="부서">{doc.department ?? '-'}</Descriptions.Item>
          <Descriptions.Item label="보안등급">
            <Tag>{doc.security_level}</Tag>
          </Descriptions.Item>
          <Descriptions.Item label="상태">
            <StatusBadge status={doc.status} />
          </Descriptions.Item>
          <Descriptions.Item label="허용 채널">
            <ChannelTags ids={doc.allowed_channel_ids ?? []} channels={channels} />
          </Descriptions.Item>
        </Descriptions>
      )}
      <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 8 }}>버전 이력</div>
      <QueryState
        isLoading={versions.isLoading}
        error={versions.error}
        isEmpty={(versions.data?.length ?? 0) === 0}
        emptyText="버전 없음"
      >
        <Table
          rowKey="id"
          size="small"
          columns={versionColumns}
          dataSource={versions.data}
          pagination={false}
        />
      </QueryState>
    </Drawer>
  );
}
