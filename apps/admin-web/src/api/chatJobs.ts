import { useQuery } from '@tanstack/react-query';
import { api } from './client';
import { qk } from './queryKeys';
import type { ChatJobView } from '../types';

/** enabled=false 면 호출하지 않는다 — 권한 없는 역할의 사이드바 배지/대시보드가 403 을 내지 않게. */
export function useChatJobs(status?: string, enabled = true, sinceHours?: number) {
  return useQuery({
    queryKey: [...qk.chatJobs(status), sinceHours ?? 'all'] as const,
    queryFn: () =>
      api.get<ChatJobView[]>('/chat-jobs', { job_status: status, since_hours: sinceHours }),
    enabled,
  });
}

/** 사이드바 "대화 작업" 배지 — 이 시간 안의 실패만 센다(전체 이력이 아니라). */
export const RECENT_FAILED_HOURS = 24;

/**
 * 최근 RECENT_FAILED_HOURS 시간의 FAILED 대화 작업. 사이드바는 화면 전환에도 계속 마운트되어 있고
 * 전역 refetchOnWindowFocus 가 꺼져 있으므로 1분마다 직접 다시 조회한다.
 */
export function useRecentFailedChatJobs(enabled = true) {
  return useQuery({
    queryKey: ['chatJobs', 'failed-recent', RECENT_FAILED_HOURS] as const,
    queryFn: () =>
      api.get<ChatJobView[]>('/chat-jobs', {
        job_status: 'FAILED',
        since_hours: RECENT_FAILED_HOURS,
      }),
    enabled,
    refetchInterval: 60_000,
  });
}
