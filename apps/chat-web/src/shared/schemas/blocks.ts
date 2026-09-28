import { z } from 'zod';

/**
 * 선언적 블록 — aiops_chatbot `packages/shared/src/schemas/blocks.ts` 이식 (RAG 서브셋).
 * 서버 SSOT: `libs/schemas/src/rag_schemas/webchat.py` (Block union). 필드를 바꾸면 양쪽을 함께 바꾼다.
 * 제거: event_card / approval_card / tool_trace (AIOps 인시던트·MCP 전용).
 */
const Text = z.string().max(4000);

export const HeaderBlock = z.object({ type: z.literal('header'), text: Text, block_id: z.string().optional() });
export const SectionBlock = z.object({ type: z.literal('section'), text: Text, block_id: z.string().optional() });
export const MarkdownBlock = z.object({ type: z.literal('markdown'), text: z.string().max(20000), block_id: z.string().optional() });
export const ContextBlock = z.object({ type: z.literal('context'), text: Text, block_id: z.string().optional() });
export const DividerBlock = z.object({ type: z.literal('divider'), block_id: z.string().optional() });

export const KvListBlock = z.object({
  type: z.literal('kv_list'),
  items: z.array(z.object({ k: z.string().max(200), v: z.string().max(2000) })).max(50),
  block_id: z.string().optional(),
});

export const CodeBlock = z.object({
  type: z.literal('code'),
  lang: z.string().max(40).optional(),
  text: z.string().max(20000),
  block_id: z.string().optional(),
});

export const TableBlock = z.object({
  type: z.literal('table'),
  columns: z
    .array(z.object({ key: z.string(), label: z.string(), align: z.enum(['left', 'right']).optional(), emphasis: z.boolean().optional() }))
    .max(12),
  rows: z.array(z.record(z.string(), z.union([z.string(), z.number(), z.null()]))).max(200),
  footer: z.array(z.string()).optional(),
  source: z.string().optional(),
  block_id: z.string().optional(),
});

export const ButtonElement = z.object({
  type: z.literal('button'),
  action_id: z.string().max(80),
  text: z.string().max(80),
  value: z.string().max(2000).optional(),
  style: z.enum(['primary', 'danger', 'default']).optional(),
  url: z.string().url().optional(),
  disabled: z.boolean().optional(),
});
export const ActionsBlock = z.object({
  type: z.literal('actions'),
  block_id: z.string().max(80),
  elements: z.array(ButtonElement).max(8),
});

export const BlockSchema = z.discriminatedUnion('type', [
  HeaderBlock,
  SectionBlock,
  MarkdownBlock,
  ContextBlock,
  DividerBlock,
  KvListBlock,
  CodeBlock,
  TableBlock,
  ActionsBlock,
]);
export type Block = z.infer<typeof BlockSchema>;
export const BlocksSchema = z.array(BlockSchema).max(50);
export type Blocks = z.infer<typeof BlocksSchema>;
export type TableBlockT = z.infer<typeof TableBlock>;

/** 위젯 액션 요청 — POST /api/v1/actions (피드백: action_id=feedback:up|down, value=feedback_token) */
export const WidgetActionRequestSchema = z.object({
  post_id: z.string().uuid(),
  block_id: z.string().max(80),
  action_id: z.string().max(80),
  value: z.string().max(2000).optional(),
});
export type WidgetActionRequest = z.infer<typeof WidgetActionRequestSchema>;
