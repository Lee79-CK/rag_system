import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from './client';
import { qk } from './queryKeys';
import type { ChatUserView, ChatUserWithTempPassword } from '../types';

/** Web Chat 사용자 — admin-api `/api/v1/chat/users` (TDD §7.5). */
export function useChatUsers() {
  return useQuery({ queryKey: qk.chatUsers, queryFn: () => api.get<ChatUserView[]>('/chat/users') });
}

export function useCreateChatUser() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { email: string; display_name: string; role: 'user' | 'admin' }) =>
      api.post<ChatUserWithTempPassword>('/chat/users', body),
    onSuccess: () => qc.invalidateQueries({ queryKey: qk.chatUsers }),
  });
}

export function useUpdateChatUser() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: Partial<Pick<ChatUserView, 'display_name' | 'role' | 'is_active'>> }) =>
      api.put<ChatUserView>(`/chat/users/${id}`, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: qk.chatUsers }),
  });
}

export function useResetChatUserPassword() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.post<ChatUserWithTempPassword>(`/chat/users/${id}/reset-password`),
    onSuccess: () => qc.invalidateQueries({ queryKey: qk.chatUsers }),
  });
}
