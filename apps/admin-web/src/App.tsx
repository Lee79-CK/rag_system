import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { App as AntdApp, ConfigProvider, theme } from 'antd';
import koKR from 'antd/locale/ko_KR';
import { Navigate, Route, BrowserRouter as Router, Routes } from 'react-router-dom';
import { AppLayout } from './components/AppLayout';
import { Dashboard } from './pages/Dashboard';
import { Documents } from './pages/Documents';
import { IndexJobs } from './pages/IndexJobs';
import { Channels } from './pages/Channels';
import { ChatJobs } from './pages/ChatJobs';
import { ChatUsers } from './pages/ChatUsers';
import { Settings } from './pages/Settings';
import { Evaluation } from './pages/Evaluation';
import { AuditLogs } from './pages/AuditLogs';
import { FeedbackDashboard } from './pages/FeedbackDashboard';
import { ErrorLogs } from './pages/ErrorLogs';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false,
      staleTime: 15 * 1000,
    },
  },
});

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ConfigProvider
        locale={koKR}
        theme={{
          algorithm: theme.defaultAlgorithm,
          token: {
            colorPrimary: '#2563eb',
            colorInfo: '#2563eb',
            colorSuccess: '#16a34a',
            colorWarning: '#d97706',
            colorError: '#dc2626',
            colorLink: '#1d4ed8',
            colorBorder: '#e3e6ea',
            colorBorderSecondary: '#eef0f3',
            colorBgLayout: '#f7f8fa',
            colorText: '#1a1f27',
            colorTextSecondary: '#5b6472',
            borderRadius: 8,
            fontSize: 14,
            fontFamily:
              "'Pretendard', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Apple SD Gothic Neo', 'Malgun Gothic', 'Noto Sans KR', sans-serif",
          },
          components: {
            Table: { headerBg: '#ffffff', headerColor: '#5b6472', rowHoverBg: '#f7f8fa' },
            Card: { boxShadow: '0 1px 2px rgba(16,24,40,.06)' },
          },
        }}
      >
        <AntdApp>
          <Router>
            <Routes>
              <Route element={<AppLayout />}>
                <Route index element={<Dashboard />} />
                <Route path="documents" element={<Documents />} />
                <Route path="index-jobs" element={<IndexJobs />} />
                <Route path="channels" element={<Channels />} />
                <Route path="chat-users" element={<ChatUsers />} />
                <Route path="chat-jobs" element={<ChatJobs />} />
                <Route path="settings" element={<Settings />} />
                <Route path="evaluation" element={<Evaluation />} />
                <Route path="feedback" element={<FeedbackDashboard />} />
                <Route path="audit" element={<AuditLogs />} />
                <Route path="errors" element={<ErrorLogs />} />
                <Route path="*" element={<Navigate to="/" replace />} />
              </Route>
            </Routes>
          </Router>
        </AntdApp>
      </ConfigProvider>
    </QueryClientProvider>
  );
}
