'use client';

import { io, type Socket } from 'socket.io-client';
import { useAuthStore } from './stores/auth';

// 비우면 same-origin (K8s Ingress: /ws → chat-gateway). dev 는 http://localhost:8001 지정.
const WS_URL = process.env.NEXT_PUBLIC_WS_URL || undefined;
let socket: Socket | null = null;
let lastSeen: string | null = null;

export function getSocket(): Socket | null {
  return socket;
}

/** 연결(토큰은 handshake.auth) — 재연결 시 ack(since) 로 누락 동기화 트리거 */
export function connectSocket(onReady?: (info: { channels: string[] }) => void, onMissed?: (missed: unknown[]) => void): Socket {
  if (socket?.connected) return socket;
  const token = useAuthStore.getState().accessToken;
  if (socket) socket.disconnect();
  // websocket 전용: gateway 다중 replica 에서 sticky session 없이 동작 (polling 미허용, TDD §7.1.2)
  const opts = { path: '/ws', transports: ['websocket'], auth: { token }, reconnection: true, reconnectionDelay: 1000, reconnectionDelayMax: 8000 };
  socket = WS_URL ? io(WS_URL, opts) : io(opts);
  socket.on('ready', (info: { channels: string[]; server_time: string }) => {
    onReady?.(info);
    if (lastSeen) socket?.emit('ack', { since: lastSeen }, (res: { missed?: unknown[] }) => res?.missed?.length && onMissed?.(res.missed));
    lastSeen = info.server_time;
  });
  socket.onAny(() => {
    lastSeen = new Date().toISOString();
  });
  // 토큰 갱신 시 재인증
  useAuthStore.subscribe((s, prev) => {
    if (s.accessToken && s.accessToken !== prev.accessToken && socket) {
      (socket.auth as { token?: string | null }).token = s.accessToken;
      if (!socket.connected) socket.connect();
    }
    if (!s.accessToken && socket) socket.disconnect();
  });
  return socket;
}

export function disconnectSocket() {
  socket?.disconnect();
  socket = null;
}
