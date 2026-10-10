import { useQuery } from '@tanstack/react-query';
import { api } from './client';
import { qk } from './queryKeys';
import type { ErrorEventView, ErrorLogsResult, ErrorSource } from '../types';

export interface ErrorFilters {
  source?: ErrorSource;
  hours: number;
}

/** 오류 통합 목록 (SYS_ADMIN). meta.services = 로그 조회 가능한 서비스 allowlist. */
export function useErrorEvents(filters: ErrorFilters, refetchInterval?: number) {
  return useQuery({
    queryKey: qk.errors(filters),
    queryFn: async () => {
      const { data, meta } = await api.getEnvelope<ErrorEventView[]>('/errors', {
        source: filters.source,
        hours: filters.hours,
      });
      return { items: data, services: (meta.services as string[] | undefined) ?? [] };
    },
    refetchInterval,
  });
}

export interface ErrorLogParams {
  service: string;
  at: string;
  before_min: number;
  after_min: number;
  index_job_id?: string;
}

/** 선택한 오류 시각 전후의 파드 로그 — [조회] 를 눌렀을 때만(enabled) 가져온다. */
export function useErrorLogs(params: ErrorLogParams | null) {
  return useQuery({
    queryKey: qk.errorLogs(params ?? {}),
    queryFn: () =>
      api.get<ErrorLogsResult>('/errors/logs', {
        service: params!.service,
        at: params!.at,
        before_min: params!.before_min,
        after_min: params!.after_min,
        index_job_id: params!.index_job_id,
      }),
    enabled: !!params,
    retry: false,
    staleTime: 0,
  });
}
