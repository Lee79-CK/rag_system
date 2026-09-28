/**
 * WebSocket(socket.io) 이벤트 — aiops_chatbot `schemas/ws.ts` 이식 (RAG 서브셋).
 * 서버 SSOT: `libs/schemas/src/rag_schemas/webchat.py` (WS_* 상수). chat-gateway 는 path `/ws`.
 */
export const WS_SERVER_EVENTS = {
  postCreated: 'post.created',
  postUpdated: 'post.updated',
  postDeleted: 'post.deleted',
  threadUpdated: 'thread.updated',
  llmStreamDelta: 'llm.stream.delta',
  llmStreamEnd: 'llm.stream.end',
  channelUpdated: 'channel.updated',
} as const;

export const WS_CLIENT_EVENTS = {
  subscribe: 'subscribe',
  ack: 'ack',
} as const;

export interface LlmStreamDelta {
  post_id: string;
  channel_id: string;
  root_id: string | null;
  delta: string;
  seq: number;
}
export interface LlmStreamEnd {
  post_id: string;
  channel_id: string;
  root_id: string | null;
  usage?: { prompt_tokens?: number; completion_tokens?: number } | null;
}
