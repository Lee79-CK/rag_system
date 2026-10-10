import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from './client';
import { qk } from './queryKeys';
import type { IndexJobView, ReindexResult } from '../types';

const ACTIVE = new Set(['PENDING', 'RUNNING']);

/** GET /api/v1/index-jobs — 진행 중(PENDING/RUNNING) Job 이 있으면 5초마다 갱신. */
export function useIndexJobs(status?: string) {
  return useQuery({
    queryKey: qk.indexJobs(status),
    queryFn: () => api.get<IndexJobView[]>('/index-jobs', { status }),
    refetchInterval: (query) =>
      (query.state.data ?? []).some((j) => ACTIVE.has(j.status)) ? 5000 : false,
  });
}

/** POST /api/v1/index-jobs/{id}/retry — 실패·취소·트리거 실패 Job 을 새 Job 으로 재실행. */
export function useRetryIndexJob() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.post<ReindexResult>(`/index-jobs/${id}/retry`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['indexJobs'] });
      qc.invalidateQueries({ queryKey: qk.documents });
    },
  });
}
