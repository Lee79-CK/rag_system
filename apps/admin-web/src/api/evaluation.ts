import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from './client';
import { qk } from './queryKeys';
import type {
  CandidateStatus,
  CandidateUpdate,
  EvaluationCandidate,
  EvaluationRun,
  EvaluationRunDetail,
  PromoteCandidateResult,
} from '../types';

export const CANDIDATE_STATUS_LABEL: Record<CandidateStatus, string> = {
  PENDING: '검토 대기',
  ACCEPTED: '채택',
  REJECTED: '제외',
};

/** 평가셋 후보 목록 — admin-api `/api/v1/evaluation/candidates` (TDD §7.5, §13.3). */
export function useEvaluationCandidates(status?: CandidateStatus) {
  return useQuery({
    queryKey: qk.evaluationCandidates(status),
    queryFn: () => api.get<EvaluationCandidate[]>('/evaluation/candidates', status ? { status } : undefined),
  });
}

/** 👎 답변 → 평가셋 후보 승격. 이미 승격된 답변이면 기존 후보를 돌려준다(created=false). */
export function usePromoteCandidate() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (messageId: string) =>
      api.post<PromoteCandidateResult>('/evaluation/candidates', { message_id: messageId }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['evaluation'] });
      qc.invalidateQueries({ queryKey: ['feedback', 'messages'] });
    },
  });
}

export function useUpdateCandidate() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...body }: CandidateUpdate & { id: string }) =>
      api.patch<EvaluationCandidate>(`/evaluation/candidates/${id}`, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['evaluation'] });
      qc.invalidateQueries({ queryKey: ['feedback', 'messages'] });
    },
  });
}

/** 채택(ACCEPTED) 후보 → runner 데이터셋 YAML 저장 (X-Auth-User 필요 → fetch → Blob). */
export async function downloadCandidatesYaml(): Promise<void> {
  const { blob, filename } = await api.blob('/evaluation/candidates/export');
  const url = URL.createObjectURL(blob);
  try {
    const a = document.createElement('a');
    a.href = url;
    a.download = filename ?? 'feedback-candidates.yaml';
    document.body.appendChild(a);
    a.click();
    a.remove();
  } finally {
    setTimeout(() => URL.revokeObjectURL(url), 0);
  }
}

/** 평가 실행 이력 — 실행 중(RUNNING)이 있으면 3초마다 진행률 갱신. */
export function useEvaluationRuns() {
  return useQuery({
    queryKey: qk.evaluationRuns,
    queryFn: () => api.get<EvaluationRun[]>('/evaluation/runs'),
    refetchInterval: (q) => (q.state.data?.some((r) => r.status === 'RUNNING') ? 3000 : false),
  });
}

export function useEvaluationRun(id: string | null) {
  return useQuery({
    queryKey: qk.evaluationRun(id ?? ''),
    queryFn: () => api.get<EvaluationRunDetail>(`/evaluation/runs/${id}`),
    enabled: !!id,
    refetchInterval: (q) => (q.state.data?.status === 'RUNNING' ? 3000 : false),
  });
}

/** 채택(ACCEPTED) 후보로 평가 실행 시작 (admin-api 가 백그라운드로 rag-api 에 질의). */
export function useStartEvaluationRun() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.post<EvaluationRun>('/evaluation/runs'),
    onSuccess: () => qc.invalidateQueries({ queryKey: qk.evaluationRuns }),
  });
}
