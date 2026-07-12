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
import { Settings } from './pages/Settings';
import { Evaluation } from './pages/Evaluation';
import { AuditLogs } from './pages/AuditLogs';
import { FeedbackDashboard } from './pages/FeedbackDashboard';

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
        theme={{ algorithm: theme.defaultAlgorithm, token: { colorPrimary: '#1677ff' } }}
      >
        <AntdApp>
          <Router>
            <Routes>
              <Route element={<AppLayout />}>
                <Route index element={<Dashboard />} />
                <Route path="documents" element={<Documents />} />
                <Route path="index-jobs" element={<IndexJobs />} />
                <Route path="channels" element={<Channels />} />
                <Route path="chat-jobs" element={<ChatJobs />} />
                <Route path="settings" element={<Settings />} />
                <Route path="evaluation" element={<Evaluation />} />
                <Route path="feedback" element={<FeedbackDashboard />} />
                <Route path="audit" element={<AuditLogs />} />
                <Route path="*" element={<Navigate to="/" replace />} />
              </Route>
            </Routes>
          </Router>
        </AntdApp>
      </ConfigProvider>
    </QueryClientProvider>
  );
}
