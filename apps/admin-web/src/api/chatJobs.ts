import { useQuery } from '@tanstack/react-query';
import { api } from './client';
import { qk } from './queryKeys';
import type { ChatJobView } from '../types';

/** enabled=false 면 호출하지 않는다 — 권한 없는 역할의 사이드바 배지/대시보드가 403 을 내지 않게. */
export function useChatJobs(status?: string, enabled = true) {
  return useQuery({
    queryKey: qk.chatJobs(status),
    queryFn: () => api.get<ChatJobView[]>('/chat-jobs', { job_status: status }),
    enabled,
  });
}
