import { useQuery } from '@tanstack/react-query';
import { requestEnvelope } from './client';
import { qk } from './queryKeys';
import type { AuditLogView } from '../types';

export interface AuditFilters {
  actor?: string;
  action?: string;
  method?: string;
  result?: string;
  from?: string;
  to?: string;
}

export interface AuditLogPage {
  items: AuditLogView[];
  /** 서버 limit(기본 500)에 걸려 오래된 기록이 잘렸는지 — 기간을 좁히라는 안내용 */
  truncated: boolean;
  limit: number;
}

/** GET /api/v1/audit-logs (SYS_ADMIN · AUDITOR) — 최신순. */
export function useAuditLogs(filters: AuditFilters) {
  return useQuery({
    queryKey: qk.audit(filters),
    queryFn: async (): Promise<AuditLogPage> => {
      const { data, meta } = await requestEnvelope<AuditLogView[]>('/audit-logs', {
        query: {
          actor: filters.actor,
          action: filters.action,
          method: filters.method,
          result: filters.result,
          from: filters.from,
          to: filters.to,
        },
      });
      return {
        items: data ?? [],
        truncated: Boolean(meta.truncated),
        limit: Number(meta.limit ?? 0),
      };
    },
  });
}
