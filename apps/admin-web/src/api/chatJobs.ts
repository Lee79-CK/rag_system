import { useQuery } from '@tanstack/react-query';
import { api } from './client';
import { qk } from './queryKeys';
import type { ChatJobView } from '../types';

export function useChatJobs(status?: string) {
  return useQuery({
    queryKey: qk.chatJobs(status),
    queryFn: () => api.get<ChatJobView[]>('/chat-jobs', { job_status: status }),
  });
}
