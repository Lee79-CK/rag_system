import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from './client';
import { qk } from './queryKeys';
import type { IndexJobView } from '../types';

/**
 * NOTE (deviation): admin-api does not yet expose a GET list / retry for index_jobs
 * (only documents/{id}/reindex INSERTs a row). This hook targets the expected
 * `/api/v1/index-jobs` contract and degrades gracefully to an empty list on 404/500.
 */
export function useIndexJobs(status?: string) {
  return useQuery({
    queryKey: qk.indexJobs(status),
    queryFn: async () => {
      try {
        return await api.get<IndexJobView[]>('/index-jobs', { status });
      } catch {
        return [] as IndexJobView[];
      }
    },
  });
}

export function useRetryIndexJob() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.post<IndexJobView>(`/index-jobs/${id}/retry`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['indexJobs'] }),
  });
}
