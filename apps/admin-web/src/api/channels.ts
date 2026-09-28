import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from './client';
import { qk } from './queryKeys';
import type {
  BindingCreate,
  BindingUpdate,
  BindingView,
  ChannelCreate,
  ChannelMemberView,
  ChannelView,
} from '../types';

/** Web Chat 채널/Binding/멤버 — admin-api `/api/v1/chat/*` (TDD §7.5). */
export function useChannels() {
  return useQuery({
    queryKey: qk.channels,
    queryFn: () => api.get<ChannelView[]>('/chat/channels'),
  });
}

export function useChannel(id: string | undefined) {
  return useQuery({
    queryKey: qk.channel(id ?? ''),
    queryFn: () => api.get<ChannelView>(`/chat/channels/${id}`),
    enabled: !!id,
  });
}

export function useCreateChannel() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: ChannelCreate) => api.post<ChannelView>('/chat/channels', body),
    onSuccess: () => qc.invalidateQueries({ queryKey: qk.channels }),
  });
}

export function useUpdateChannel() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ channelId, body }: { channelId: string; body: Partial<ChannelCreate> }) =>
      api.put<ChannelView>(`/chat/channels/${channelId}`, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['channels'] }),
  });
}

export function useCreateBinding() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ channelId, body }: { channelId: string; body: BindingCreate }) =>
      api.post<BindingView>(`/chat/channels/${channelId}/bindings`, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['channels'] }),
  });
}

export function useUpdateBinding() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ bindingId, body }: { bindingId: string; body: BindingUpdate }) =>
      api.put<BindingView>(`/chat/bindings/${bindingId}`, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['channels'] }),
  });
}

export function useSetBindingEnabled() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ bindingId, enabled }: { bindingId: string; enabled: boolean }) =>
      api.post<BindingView>(`/chat/bindings/${bindingId}/${enabled ? 'enable' : 'disable'}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['channels'] }),
  });
}

export function useChannelMembers(channelId: string | undefined) {
  return useQuery({
    queryKey: qk.channelMembers(channelId ?? ''),
    queryFn: () => api.get<ChannelMemberView[]>(`/chat/channels/${channelId}/members`),
    enabled: !!channelId,
  });
}

export function useAddMembers() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ channelId, userIds, role }: { channelId: string; userIds: string[]; role?: string }) =>
      api.post<{ added: number }>(`/chat/channels/${channelId}/members`, { user_ids: userIds, role: role ?? 'member' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['channels'] }),
  });
}

export function useRemoveMember() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ channelId, userId }: { channelId: string; userId: string }) =>
      api.del<{ removed: boolean }>(`/chat/channels/${channelId}/members/${userId}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['channels'] }),
  });
}
