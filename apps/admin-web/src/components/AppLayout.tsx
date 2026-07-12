import { useState } from 'react';
import { Link, Outlet, useLocation } from 'react-router-dom';
import {
  ApiOutlined,
  AuditOutlined,
  DashboardOutlined,
  DeploymentUnitOutlined,
  ExperimentOutlined,
  FileTextOutlined,
  LikeOutlined,
  MessageOutlined,
  SettingOutlined,
} from '@ant-design/icons';
import { Layout, Menu, Space, Tag, Typography } from 'antd';
import type { MenuProps } from 'antd';
import { AuthUserSwitcher } from './AuthUserSwitcher';

const { Header, Sider, Content } = Layout;
const { Text } = Typography;

interface NavItem {
  key: string;
  label: string;
  icon: React.ReactNode;
}

const NAV: NavItem[] = [
  { key: '/', label: 'Dashboard', icon: <DashboardOutlined /> },
  { key: '/documents', label: 'Documents', icon: <FileTextOutlined /> },
  { key: '/index-jobs', label: 'Index Jobs', icon: <DeploymentUnitOutlined /> },
  { key: '/channels', label: 'Channels', icon: <ApiOutlined /> },
  { key: '/chat-jobs', label: 'Chat Jobs', icon: <MessageOutlined /> },
  { key: '/settings', label: 'Settings', icon: <SettingOutlined /> },
  { key: '/evaluation', label: 'Evaluation', icon: <ExperimentOutlined /> },
  { key: '/feedback', label: 'Feedback', icon: <LikeOutlined /> },
  { key: '/audit', label: 'Audit Logs', icon: <AuditOutlined /> },
];

export function AppLayout() {
  const location = useLocation();
  const [collapsed, setCollapsed] = useState(false);

  // Longest matching prefix so nested routes keep the parent highlighted.
  const selected =
    NAV.map((n) => n.key)
      .filter((k) => (k === '/' ? location.pathname === '/' : location.pathname.startsWith(k)))
      .sort((a, b) => b.length - a.length)[0] ?? '/';

  const items: MenuProps['items'] = NAV.map((n) => ({
    key: n.key,
    icon: n.icon,
    label: <Link to={n.key}>{n.label}</Link>,
  }));

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Sider collapsible collapsed={collapsed} onCollapse={setCollapsed} theme="dark" width={220}>
        <div
          style={{
            height: 56,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: '#fff',
            fontWeight: 600,
            letterSpacing: 0.5,
          }}
        >
          {collapsed ? 'RAG' : 'RAG Admin'}
        </div>
        <Menu theme="dark" mode="inline" selectedKeys={[selected]} items={items} />
      </Sider>
      <Layout>
        <Header
          style={{
            background: '#fff',
            padding: '0 24px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            borderBottom: '1px solid #f0f0f0',
          }}
        >
          <Space>
            <Text strong>폐쇄망 RAG 관리 포털</Text>
            <Tag color="geekblue">M8</Tag>
          </Space>
          <AuthUserSwitcher />
        </Header>
        <Content style={{ padding: 24 }}>
          <div style={{ maxWidth: 1280, margin: '0 auto' }}>
            <Outlet />
          </div>
        </Content>
      </Layout>
    </Layout>
  );
}
