import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from './client';
import { qk } from './queryKeys';
import type { ChatJobView, RetryDeliveryResult } from '../types';

export function useChatJobs(status?: string) {
  return useQuery({
    queryKey: qk.chatJobs(status),
    queryFn: () => api.get<ChatJobView[]>('/chat-jobs', { job_status: status }),
  });
}

export function useRetryDelivery() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (jobId: string) =>
      api.post<RetryDeliveryResult>(`/chat-jobs/${jobId}/retry-delivery`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['chatJobs'] }),
  });
}
