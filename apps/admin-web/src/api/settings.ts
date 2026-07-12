import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from './client';
import { qk } from './queryKeys';
import type { SettingView } from '../types';

export function useSettings() {
  return useQuery({
    queryKey: qk.settings,
    queryFn: () => api.get<SettingView[]>('/settings'),
  });
}

export function useUpdateSetting() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ key, value }: { key: string; value: unknown }) =>
      api.put<SettingView>(`/settings/${encodeURIComponent(key)}`, { value }),
    onSuccess: () => qc.invalidateQueries({ queryKey: qk.settings }),
  });
}
