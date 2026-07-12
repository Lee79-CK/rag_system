import { useState } from 'react';
import {
  App,
  Button,
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
  Upload,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import type { UploadFile } from 'antd/es/upload/interface';
import { InboxOutlined, PlusOutlined, ReloadOutlined } from '@ant-design/icons';
import { PageHeader } from '../components/PageHeader';
import { QueryState, errorMessage } from '../components/QueryState';
import {
  useDeactivateDocument,
  useDeleteDocument,
  useDocumentVersions,
  useDocuments,
  useReindexDocument,
  useUploadDocument,
} from '../api/documents';
import { useChannels } from '../api/channels';
import type { DocumentView, SecurityLevel } from '../types';

const SECURITY_LEVELS: SecurityLevel[] = ['PUBLIC', 'INTERNAL', 'CONFIDENTIAL', 'SECRET'];

const STATUS_COLOR: Record<string, string> = {
  UPLOADED: 'default',
  INDEXING: 'processing',
  ACTIVE: 'success',
  INACTIVE: 'warning',
  DELETED: 'error',
  FAILED: 'error',
};

export function Documents() {
  const { message } = App.useApp();
  const docs = useDocuments();
  const channels = useChannels();
  const upload = useUploadDocument();
  const reindex = useReindexDocument();
  const deactivate = useDeactivateDocument();
  const remove = useDeleteDocument();

  const [uploadOpen, setUploadOpen] = useState(false);
  const [detailId, setDetailId] = useState<string | undefined>();
  const [fileList, setFileList] = useState<UploadFile[]>([]);
  const [form] = Form.useForm();

  const submitUpload = async () => {
    const values = await form.validateFields();
    const file = fileList[0]?.originFileObj;
    if (!file) {
      message.error('업로드할 파일을 선택하세요.');
      return;
    }
    try {
      await upload.mutateAsync({
        file: file as File,
        title: values.title,
        category: values.category,
        department: values.department,
        security_level: values.security_level,
        allowed_channel_ids: values.allowed_channel_ids,
      });
      message.success('업로드 완료');
      setUploadOpen(false);
      setFileList([]);
      form.resetFields();
    } catch (e) {
      message.error(errorMessage(e));
    }
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
      render: (v: string, row) => (
        <Button type="link" style={{ padding: 0 }} onClick={() => setDetailId(row.id)}>
          {v}
        </Button>
      ),
    },
    { title: '분류', dataIndex: 'category', render: (v) => v ?? '-' },
    { title: '부서', dataIndex: 'department', render: (v) => v ?? '-' },
    {
      title: '보안등급',
      dataIndex: 'security_level',
      render: (v: string) => <Tag>{v}</Tag>,
    },
    {
      title: '상태',
      dataIndex: 'status',
      render: (v: string) => <Tag color={STATUS_COLOR[v] ?? 'default'}>{v}</Tag>,
    },
    {
      title: '등록일',
      dataIndex: 'created_at',
      render: (v: string | null) => (v ? new Date(v).toLocaleString() : '-'),
    },
    {
      title: '작업',
      key: 'actions',
      render: (_, row) => (
        <Space size="small" wrap>
          <Button
            size="small"
            icon={<ReloadOutlined />}
            loading={reindex.isPending}
            onClick={() => runAction('재색인 요청', () => reindex.mutateAsync(row.id))}
          >
            재색인
          </Button>
          <Popconfirm
            title="비활성화하시겠습니까?"
            onConfirm={() => runAction('비활성화', () => deactivate.mutateAsync(row.id))}
          >
            <Button size="small">비활성화</Button>
          </Popconfirm>
          <Popconfirm
            title="삭제(논리)하시겠습니까?"
            onConfirm={() => runAction('삭제', () => remove.mutateAsync(row.id))}
          >
            <Button size="small" danger>
              삭제
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <>
      <PageHeader
        title="Documents"
        subtitle="문서 등록 / 색인 / 버전 관리 (FR-DOC)"
        extra={
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setUploadOpen(true)}>
            문서 업로드
          </Button>
        }
      />

      <QueryState
        isLoading={docs.isLoading}
        error={docs.error}
        isEmpty={(docs.data?.length ?? 0) === 0}
        emptyText="등록된 문서가 없습니다."
      >
        <Table rowKey="id" columns={columns} dataSource={docs.data} pagination={{ pageSize: 20 }} />
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
        <Form form={form} layout="vertical" initialValues={{ security_level: 'INTERNAL' }}>
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
              <p className="ant-upload-hint">pdf, docx, pptx, xlsx, txt, md, html</p>
            </Upload.Dragger>
          </Form.Item>
          <Form.Item label="제목" name="title">
            <Input placeholder="미입력 시 파일명 사용" />
          </Form.Item>
          <Form.Item label="분류(category)" name="category">
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
            tooltip="이 문서를 검색에 노출할 Channel을 선택합니다 (Channel 격리)."
          >
            <Select
              mode="multiple"
              allowClear
              loading={channels.isLoading}
              placeholder="전체 허용은 비워두기"
              options={(channels.data ?? []).map((c) => ({
                label: `${c.channel_name} (${c.channel_id})`,
                value: c.channel_id,
              }))}
            />
          </Form.Item>
        </Form>
      </Modal>

      <DocumentDetail id={detailId} onClose={() => setDetailId(undefined)} docs={docs.data} />
    </>
  );
}

function DocumentDetail({
  id,
  onClose,
  docs,
}: {
  id?: string;
  onClose: () => void;
  docs?: DocumentView[];
}) {
  const versions = useDocumentVersions(id);
  const doc = docs?.find((d) => d.id === id);

  const versionColumns: ColumnsType<NonNullable<typeof versions.data>[number]> = [
    { title: 'v', dataIndex: 'version', width: 60 },
    { title: '상태', dataIndex: 'status', render: (v: string) => <Tag>{v}</Tag> },
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
      render: (v: string | null) => (v ? new Date(v).toLocaleString() : '-'),
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
          <Descriptions.Item label="분류">{doc.category ?? '-'}</Descriptions.Item>
          <Descriptions.Item label="부서">{doc.department ?? '-'}</Descriptions.Item>
          <Descriptions.Item label="보안등급">{doc.security_level}</Descriptions.Item>
          <Descriptions.Item label="상태">
            <Tag color={STATUS_COLOR[doc.status] ?? 'default'}>{doc.status}</Tag>
          </Descriptions.Item>
        </Descriptions>
      )}
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
