import { useQuery } from '@tanstack/react-query';
import { api } from './client';
import { qk } from './queryKeys';
import type { AuditLogView } from '../types';

export interface AuditFilters {
  actor?: string;
  action?: string;
  method?: string;
  from?: string;
  to?: string;
}

/**
 * NOTE (deviation): admin-api writes audit_logs via middleware but does not yet
 * expose a read endpoint. This targets the expected `/api/v1/audit-logs` contract
 * and degrades gracefully to an empty list.
 */
export function useAuditLogs(filters: AuditFilters) {
  return useQuery({
    queryKey: qk.audit(filters),
    queryFn: async () => {
      try {
        return await api.get<AuditLogView[]>('/audit-logs', {
          actor: filters.actor,
          action: filters.action,
          method: filters.method,
          from: filters.from,
          to: filters.to,
        });
      } catch {
        return [] as AuditLogView[];
      }
    },
  });
}
