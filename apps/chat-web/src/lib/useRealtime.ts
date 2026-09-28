'use client';

import { useQueryClient } from '@tanstack/react-query';
import { useEffect } from 'react';
import { WS_SERVER_EVENTS } from '@/shared';
import { applyDelta, qk, removePost, upsertPost, type PostDto } from './query/hooks';
import { useAuthStore } from './stores/auth';
import { connectSocket, disconnectSocket } from './ws';

/** (app) 레이아웃에서 1회 연결. 서버 이벤트를 TanStack 캐시에 반영한다. */
export function useRealtime() {
  const qc = useQueryClient();
  const token = useAuthStore((s) => s.accessToken);

  useEffect(() => {
    if (!token) return;
    const s = connectSocket(undefined, () => {
      // 재연결 후 누락 → 전체 재조회
      qc.invalidateQueries({ queryKey: ['posts'] });
      qc.invalidateQueries({ queryKey: ['thread'] });
      qc.invalidateQueries({ queryKey: qk.sidebar });
    });
    const onPost = (p: PostDto) => {
      upsertPost(qc, p);
      qc.invalidateQueries({ queryKey: qk.sidebar });
    };
    const onUpdated = (p: PostDto) => upsertPost(qc, p);
    const onThread = (p: PostDto) => {
      upsertPost(qc, p);
      qc.invalidateQueries({ queryKey: ['thread', p.id] });
    };
    const onDeleted = (d: { id: string; channel_id: string; root_id: string | null }) => removePost(qc, d);
    const onDelta = (d: { post_id: string; channel_id: string; root_id: string | null; delta: string }) => applyDelta(qc, d);
    const onEnd = (d: { post_id: string; root_id: string | null; channel_id: string }) => {
      // 스트리밍 종료 → DB(SSOT) 기준 재조회로 delta 유실/순서 차이 수렴
      if (d.root_id) qc.invalidateQueries({ queryKey: qk.thread(d.root_id) });
      qc.invalidateQueries({ queryKey: qk.posts(d.channel_id) });
    };
    const onChannel = () => {
      qc.invalidateQueries({ queryKey: qk.sidebar });
      qc.invalidateQueries({ queryKey: ['channel'] });
    };
    s.on(WS_SERVER_EVENTS.postCreated, onPost);
    s.on(WS_SERVER_EVENTS.postUpdated, onUpdated);
    s.on(WS_SERVER_EVENTS.threadUpdated, onThread);
    s.on(WS_SERVER_EVENTS.postDeleted, onDeleted);
    s.on(WS_SERVER_EVENTS.llmStreamDelta, onDelta);
    s.on(WS_SERVER_EVENTS.llmStreamEnd, onEnd);
    s.on(WS_SERVER_EVENTS.channelUpdated, onChannel);
    return () => {
      s.off(WS_SERVER_EVENTS.postCreated, onPost);
      s.off(WS_SERVER_EVENTS.postUpdated, onUpdated);
      s.off(WS_SERVER_EVENTS.threadUpdated, onThread);
      s.off(WS_SERVER_EVENTS.postDeleted, onDeleted);
      s.off(WS_SERVER_EVENTS.llmStreamDelta, onDelta);
      s.off(WS_SERVER_EVENTS.llmStreamEnd, onEnd);
      s.off(WS_SERVER_EVENTS.channelUpdated, onChannel);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [!!token]);

  useEffect(() => () => disconnectSocket(), []);
}
