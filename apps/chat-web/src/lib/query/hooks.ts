'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { Block } from '@/shared';
import { del, get, post } from '../api';

// ---------------------------------------------------------------- types (API DTO)
// 서버 SSOT: libs/schemas/src/rag_schemas/webchat.py — 필드명(snake_case) 1:1 대응.
export interface UserBrief {
  id: string;
  display_name: string;
  avatar_url: string | null;
  is_bot: boolean;
  email?: string | null;
}
/** Bot Post props (rag-worker WebChatDelivery 가 채움) */
export interface BotProps {
  streaming?: boolean;
  /** placeholder 생성 시 binding.ack_message_enabled */
  ack?: boolean;
  kind?: 'error' | string;
  feedback_token?: string;
  feedback?: Record<string, number>;
  citations_count?: number;
  insufficient_evidence?: boolean;
  /** `/` 접두어 LLM 직접 대화 답변 (RAG 미경유) */
  direct?: boolean;
}
export interface PostDto {
  id: string;
  channel_id: string;
  root_id: string | null;
  type: 'user' | 'bot' | 'system';
  user: UserBrief | null;
  message: string;
  blocks: Block[] | null;
  props: BotProps & Record<string, unknown>;
  created_at: string;
  edit_at: string | null;
  delete_at: string | null;
  is_pinned: boolean;
  reply_count: number;
  last_reply_at: string | null;
  participants: UserBrief[];
  reactions: { emoji: string; count: number; me: boolean; users: string[] }[];
}
export interface SidebarChannel {
  id: string;
  name: string;
  display_name: string | null;
  type: 'public' | 'private';
  unread: number;
  mention_count: number;
  is_muted: boolean;
  is_favorite: boolean;
  role: string;
}
export interface Sidebar {
  workspace: { id: string; name: string; slug: string };
  favorites: SidebarChannel[];
  other: SidebarChannel[];
  all: SidebarChannel[];
}
export interface EffectivePermissions {
  role: string | null;
  is_member: boolean;
  /** post / reply / use_bot / moderate */
  permissions: Record<string, boolean>;
}
export interface ChannelBindingBrief {
  enabled: boolean;
  mode: 'DEDICATED_CHANNEL' | 'TRIGGER_WORD';
  trigger_word: string | null;
  conversation_mode: 'CHANNEL' | 'THREAD' | 'STATELESS';
  /** `/` 접두어 LLM 직접 대화 허용 */
  direct_llm_enabled?: boolean;
}
export interface ChannelDetail {
  id: string;
  name: string;
  display_name: string;
  type: string;
  purpose: string | null;
  member_count: number;
  binding: ChannelBindingBrief | null;
  me: EffectivePermissions;
}
export interface ThreadDto {
  root: PostDto;
  replies: PostDto[];
  thread: { reply_count: number; participant_count: number };
  me: EffectivePermissions;
}

// ---------------------------------------------------------------- keys
export const qk = {
  sidebar: ['sidebar'] as const,
  channel: (idOrName: string) => ['channel', idOrName] as const,
  posts: (channelId: string) => ['posts', channelId] as const,
  thread: (rootId: string) => ['thread', rootId] as const,
  me: ['me'] as const,
};

// ---------------------------------------------------------------- hooks
export const useSidebar = () => useQuery({ queryKey: qk.sidebar, queryFn: () => get<Sidebar>('/api/v1/channels/sidebar'), staleTime: 5_000 });
export const useChannel = (idOrName: string | null) => useQuery({ queryKey: qk.channel(idOrName ?? ''), queryFn: () => get<ChannelDetail>(`/api/v1/channels/${encodeURIComponent(idOrName!)}`), enabled: !!idOrName });
export const usePosts = (channelId: string | null) => useQuery({ queryKey: qk.posts(channelId ?? ''), queryFn: () => get<{ items: PostDto[]; has_more: boolean }>(`/api/v1/channels/${channelId}/posts?limit=80`), enabled: !!channelId });
export const useThread = (rootId: string | null) => useQuery({ queryKey: qk.thread(rootId ?? ''), queryFn: () => get<ThreadDto>(`/api/v1/posts/${rootId}/thread`), enabled: !!rootId });

export function useCreatePost() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { channel_id: string; root_id?: string | null; message: string; client_id?: string }) => post<PostDto>('/api/v1/posts', body),
    onSuccess: (p) => {
      // WS 로도 오지만 낙관적으로 즉시 반영
      upsertPost(qc, p);
    },
  });
}

/** 답변 피드백 — value 에 Bot Post 의 feedback_token(HMAC) 을 싣는다 (TDD §7.1.4) */
export function useWidgetAction() {
  return useMutation({
    mutationFn: (body: { post_id: string; block_id: string; action_id: string; value?: string }) => post<{ ok: boolean; feedback: Record<string, number> }>('/api/v1/actions', body),
  });
}

export const useMarkViewed = () => {
  const qc = useQueryClient();
  return useMutation({ mutationFn: (channelId: string) => post(`/api/v1/channels/${channelId}/view`), onSuccess: () => qc.invalidateQueries({ queryKey: qk.sidebar }) });
};
export const useDeletePost = () => {
  const qc = useQueryClient();
  return useMutation({ mutationFn: (id: string) => del(`/api/v1/posts/${id}`), onSuccess: () => { qc.invalidateQueries({ queryKey: ['posts'] }); qc.invalidateQueries({ queryKey: ['thread'] }); } });
};

// ---------------------------------------------------------------- cache helpers (WS)
export function upsertPost(qc: ReturnType<typeof useQueryClient>, p: PostDto) {
  if (p.root_id) {
    qc.setQueryData<ThreadDto>(qk.thread(p.root_id), (old) => {
      if (!old) return old;
      const idx = old.replies.findIndex((r) => r.id === p.id);
      const replies = idx >= 0 ? old.replies.map((r) => (r.id === p.id ? p : r)) : [...old.replies, p];
      return { ...old, replies };
    });
    // 채널 목록의 root "답글 N개" 요약 갱신
    qc.invalidateQueries({ queryKey: qk.posts(p.channel_id) });
  } else {
    qc.setQueryData<{ items: PostDto[]; has_more: boolean }>(qk.posts(p.channel_id), (old) => {
      if (!old) return old;
      const idx = old.items.findIndex((r) => r.id === p.id);
      return { ...old, items: idx >= 0 ? old.items.map((r) => (r.id === p.id ? p : r)) : [...old.items, p] };
    });
    qc.setQueryData<ThreadDto>(qk.thread(p.id), (old) => (old ? { ...old, root: { ...old.root, ...p } } : old));
  }
}
export function applyDelta(qc: ReturnType<typeof useQueryClient>, d: { post_id: string; channel_id: string; root_id: string | null; delta: string }) {
  const mut = (p: PostDto) => (p.id === d.post_id ? { ...p, message: (p.message ?? '') + d.delta, props: { ...p.props, streaming: true } } : p);
  if (d.root_id) qc.setQueryData<ThreadDto>(qk.thread(d.root_id), (old) => (old ? { ...old, replies: old.replies.map(mut) } : old));
  qc.setQueryData<{ items: PostDto[]; has_more: boolean }>(qk.posts(d.channel_id), (old) => (old ? { ...old, items: old.items.map(mut) } : old));
}
export function removePost(qc: ReturnType<typeof useQueryClient>, d: { id: string; channel_id: string; root_id: string | null }) {
  if (d.root_id) qc.setQueryData<ThreadDto>(qk.thread(d.root_id), (old) => (old ? { ...old, replies: old.replies.filter((r) => r.id !== d.id) } : old));
  else qc.setQueryData<{ items: PostDto[]; has_more: boolean }>(qk.posts(d.channel_id), (old) => (old ? { ...old, items: old.items.filter((r) => r.id !== d.id) } : old));
}
