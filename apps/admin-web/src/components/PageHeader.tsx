import type { ReactNode } from 'react';
import { Space, Typography } from 'antd';

const { Title, Text } = Typography;

export function PageHeader({
  title,
  subtitle,
  extra,
}: {
  title: string;
  subtitle?: string;
  extra?: ReactNode;
}) {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'flex-start',
        justifyContent: 'space-between',
        marginBottom: 20,
        gap: 16,
        flexWrap: 'wrap',
      }}
    >
      <div>
        <Title level={3} style={{ margin: 0 }}>
          {title}
        </Title>
        {subtitle && <Text type="secondary">{subtitle}</Text>}
      </div>
      {extra && <Space wrap>{extra}</Space>}
    </div>
  );
}
