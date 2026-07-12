import { useQuery } from '@tanstack/react-query';
import { api } from './client';
import { qk } from './queryKeys';
import type { Principal } from '../types';

export function useWhoami() {
  return useQuery({
    queryKey: qk.whoami,
    queryFn: () => api.get<Principal>('/auth/whoami'),
    retry: false,
    staleTime: 5 * 60 * 1000,
  });
}
