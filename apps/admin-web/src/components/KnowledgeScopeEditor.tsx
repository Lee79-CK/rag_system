import { Card, Select, Space, Typography } from 'antd';
import type { KnowledgeScope } from '../types';

const { Text } = Typography;

const SECURITY_LEVELS = ['PUBLIC', 'INTERNAL', 'CONFIDENTIAL', 'SECRET'];

/**
 * Composes a rag_schemas.KnowledgeScope (categories/departments/security_levels/document_ids).
 * NOTE: admin-api persists a binding via `knowledge_scope_id` (FK to knowledge_scopes);
 * there is no scope-create endpoint yet, so this editor composes the scope object for
 * review/preview. Persisting it end-to-end requires a scopes API (deviation flagged).
 */
export function KnowledgeScopeEditor({
  value,
  onChange,
}: {
  value: KnowledgeScope;
  onChange: (next: KnowledgeScope) => void;
}) {
  const tagsSelect = (
    placeholder: string,
    key: keyof KnowledgeScope,
    options?: string[],
  ) => (
    <Select
      mode={options ? 'multiple' : 'tags'}
      value={value[key]}
      placeholder={placeholder}
      style={{ width: '100%' }}
      allowClear
      options={options?.map((o) => ({ label: o, value: o }))}
      onChange={(v) => onChange({ ...value, [key]: v })}
    />
  );

  return (
    <Card size="small" title="Knowledge Scope 편집기 (검색 범위)" style={{ marginBottom: 16 }}>
      <Space direction="vertical" size="small" style={{ width: '100%' }}>
        <div>
          <Text type="secondary">카테고리</Text>
          {tagsSelect('categories (입력 후 Enter)', 'categories')}
        </div>
        <div>
          <Text type="secondary">부서</Text>
          {tagsSelect('departments (입력 후 Enter)', 'departments')}
        </div>
        <div>
          <Text type="secondary">보안등급</Text>
          {tagsSelect('security_levels', 'security_levels', SECURITY_LEVELS)}
        </div>
        <div>
          <Text type="secondary">문서 ID (명시 지정)</Text>
          {tagsSelect('document_ids (입력 후 Enter)', 'document_ids')}
        </div>
      </Space>
    </Card>
  );
}
