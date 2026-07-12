import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from './client';
import { qk } from './queryKeys';
import type { EvaluationDataset, EvaluationRun, PromoteCandidateResult } from '../types';

export function useEvaluationDatasets() {
  return useQuery({
    queryKey: qk.evaluationDatasets,
    queryFn: () => api.get<EvaluationDataset[]>('/evaluation/datasets'),
  });
}

export function useEvaluationRuns() {
  return useQuery({
    queryKey: qk.evaluationRuns,
    queryFn: () => api.get<EvaluationRun[]>('/evaluation/runs'),
  });
}

/**
 * Promote a 👎 answer into an evaluation-dataset candidate (§13.3 / §8.4).
 * NOTE (deviation): admin-api evaluation router is a read-only stub today; this
 * targets the expected `/api/v1/evaluation/candidates` write contract.
 */
export function usePromoteCandidate() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (messageId: string) =>
      api.post<PromoteCandidateResult>('/evaluation/candidates', { message_id: messageId }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['evaluation'] }),
  });
}
