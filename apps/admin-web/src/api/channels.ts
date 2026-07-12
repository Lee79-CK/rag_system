import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from './client';
import { qk } from './queryKeys';
import type {
  BindingCreate,
  BindingUpdate,
  BindingView,
  ChannelCreate,
  ChannelView,
  ConnectionTestResult,
  SecretUpdateResult,
} from '../types';

export function useChannels() {
  return useQuery({
    queryKey: qk.channels,
    queryFn: () => api.get<ChannelView[]>('/mattermost/channels'),
  });
}

export function useChannel(id: string | undefined) {
  return useQuery({
    queryKey: qk.channel(id ?? ''),
    queryFn: () => api.get<ChannelView>(`/mattermost/channels/${id}`),
    enabled: !!id,
  });
}

export function useCreateChannel() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: ChannelCreate) => api.post<ChannelView>('/mattermost/channels', body),
    onSuccess: () => qc.invalidateQueries({ queryKey: qk.channels }),
  });
}

export function useCreateBinding() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ channelId, body }: { channelId: string; body: BindingCreate }) =>
      api.post<BindingView>(`/mattermost/channels/${channelId}/bindings`, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['channels'] }),
  });
}

export function useUpdateBinding() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ bindingId, body }: { bindingId: string; body: BindingUpdate }) =>
      api.put<BindingView>(`/mattermost/bindings/${bindingId}`, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['channels'] }),
  });
}

export function useSetBindingEnabled() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ bindingId, enabled }: { bindingId: string; enabled: boolean }) =>
      api.post<BindingView>(`/mattermost/bindings/${bindingId}/${enabled ? 'enable' : 'disable'}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['channels'] }),
  });
}

/** Posts a secret_ref (K8s Secret NAME only). Never carries a URL/value (FR-OPS-010). */
export function useUpdateSecret() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ channelId, secretRef }: { channelId: string; secretRef: string }) =>
      api.post<SecretUpdateResult>(`/mattermost/channels/${channelId}/secret`, {
        secret_ref: secretRef,
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['channels'] }),
  });
}

export function useTestChannel() {
  return useMutation({
    mutationFn: (channelId: string) =>
      api.post<ConnectionTestResult>(`/mattermost/channels/${channelId}/test`),
  });
}
