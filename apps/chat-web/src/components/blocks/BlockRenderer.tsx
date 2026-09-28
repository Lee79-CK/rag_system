'use client';

import clsx from 'clsx';
import { Button } from '@/components/ui/primitives';
import type { EffectivePermissions } from '@/lib/query/hooks';
import { useWidgetAction } from '@/lib/query/hooks';
import type { Block, TableBlockT } from '@/shared';
import { Markdown } from '../chat/Markdown';

/**
 * 선언적 블록 렌더러 — aiops_chatbot 이식. RAG 답변은 `table`(근거 문서) · `context`(근거 부족 안내)를 주로 쓴다.
 * AIOps 전용 event_card / approval_card / tool_trace 렌더러는 제거했다.
 */

export interface BlockCtx {
  postId: string;
  me?: EffectivePermissions | null;
  compact?: boolean;
}

export function BlockRenderer({ blocks, ctx }: { blocks: Block[]; ctx: BlockCtx }) {
  return (
    <div className="flex flex-col gap-2 mt-2">
      {blocks.map((b, i) => (
        <BlockView key={(b as { block_id?: string }).block_id ?? i} block={b} ctx={ctx} />
      ))}
    </div>
  );
}

function BlockView({ block, ctx }: { block: Block; ctx: BlockCtx }) {
  switch (block.type) {
    case 'header':
      return <div className="font-bold text-[14px]">{block.text}</div>;
    case 'section':
    case 'markdown':
      return <Markdown text={block.text} className="!text-[13px]" />;
    case 'context':
      return <div className="mono text-[11px] text-muted">{block.text}</div>;
    case 'divider':
      return <hr className="border-line" />;
    case 'kv_list':
      return (
        <div className="grid gap-x-4 gap-y-1.5 mono text-[12px] leading-[1.5]" style={{ gridTemplateColumns: 'auto 1fr' }}>
          {block.items.map((i, idx) => (
            <KV key={idx} k={i.k} v={i.v} />
          ))}
        </div>
      );
    case 'code':
      return (
        <pre className="m-0 px-3 py-2.5 rounded-[10px] overflow-auto mono text-[12px] leading-[1.5] font-medium" style={{ background: '#1D1D1F', color: '#E5E5EA' }}>
          {block.text}
        </pre>
      );
    case 'table':
      return <TableView block={block} />;
    case 'actions':
      return <ActionsView block={block} ctx={ctx} />;
    default:
      return <div className="mono text-[11px] text-muted border border-dashed border-line rounded-lg p-2">위젯: {(block as { type: string }).type}</div>;
  }
}

function KV({ k, v }: { k: string; v: string }) {
  return (
    <>
      <span className="text-muted">{k}</span>
      <span className="break-words">{v}</span>
    </>
  );
}

// ---------------------------------------------------------------- table
function TableView({ block }: { block: TableBlockT }) {
  return (
    <div className="card overflow-hidden" style={{ maxWidth: 640 }}>
      <div className="overflow-auto">
        <table className="w-full border-collapse mono text-[12px]">
          <thead>
            <tr className="bg-surface2">
              {block.columns.map((c) => (
                <th key={c.key} className={clsx('px-3 py-2 font-semibold', c.align === 'right' ? 'text-right' : 'text-left')}>
                  {c.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {block.rows.map((r, i) => (
              <tr key={i} className="border-t border-line">
                {block.columns.map((c) => {
                  const v = r[c.key];
                  const hot = c.emphasis && typeof v === 'number' && v >= 5;
                  return (
                    <td key={c.key} className={clsx('px-3 py-2', c.align === 'right' && 'text-right', c.emphasis && 'font-semibold')} style={hot ? { color: 'var(--coral)' } : undefined}>
                      {v == null ? '' : String(v)}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {(block.footer?.length || block.source) && (
        <div className="flex gap-2.5 px-3 py-2 border-t border-line mono text-[11px] text-muted">
          {block.footer?.map((f) => <span key={f}>{f}</span>)}
          {block.source && <span className="ml-auto">출처: {block.source}</span>}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- actions
function ActionsView({ block, ctx }: { block: Extract<Block, { type: 'actions' }>; ctx: BlockCtx }) {
  const act = useWidgetAction();
  return (
    <div className="flex gap-1.5 flex-wrap">
      {block.elements.map((el) =>
        el.url ? (
          <a key={el.action_id} href={el.url} target="_blank" rel="noreferrer" className="btn !h-7 !text-[11px]">
            {el.text}
          </a>
        ) : (
          <Button key={el.action_id} size="sm" variant={el.style === 'primary' ? 'primary' : el.style === 'danger' ? 'danger' : 'default'} disabled={el.disabled || act.isPending} onClick={() => act.mutate({ post_id: ctx.postId, block_id: block.block_id, action_id: el.action_id, value: el.value })}>
            {el.text}
          </Button>
        ),
      )}
    </div>
  );
}
