import { Space, Tag, Tooltip, Typography } from 'antd';
import { LockOutlined } from '@ant-design/icons';

const { Text } = Typography;

/**
 * Renders the STATUS of a secret — never its value (FR-OPS-010, NFR-SEC-006).
 * Shows the K8s Secret ref (a NAME, not the URL) and when it was last rotated.
 * There is deliberately no code path that could display the underlying URL/token.
 */
export function SecretField({
  secretRef,
  updatedAt,
}: {
  secretRef?: string | null;
  updatedAt?: string | null;
}) {
  if (!secretRef) {
    return <Tag color="warning">미등록</Tag>;
  }
  return (
    <Space size={6} wrap>
      <Tooltip title="K8s Secret 이름입니다. 실제 값(Webhook URL)은 절대 표시되지 않습니다.">
        <Tag icon={<LockOutlined />} color="blue">
          {secretRef}
        </Tag>
      </Tooltip>
      {updatedAt ? (
        <Text type="secondary" style={{ fontSize: 12 }}>
          교체: {new Date(updatedAt).toLocaleString()}
        </Text>
      ) : (
        <Text type="secondary" style={{ fontSize: 12 }}>
          교체 이력 없음
        </Text>
      )}
    </Space>
  );
}
