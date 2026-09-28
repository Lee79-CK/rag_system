'use client';

import { Badge, Segmented } from '@/components/ui/primitives';
import type { ChannelDetail } from '@/lib/query/hooks';
import { useUiStore } from '@/lib/stores/ui';

const MODE_LABEL: Record<string, string> = { CHANNEL: '채널 컨텍스트', THREAD: '스레드 컨텍스트', STATELESS: '단발 질의' };

/** 채널 헤더 — aiops_chatbot 이식. 고객사/환경 태그·Skill/MCP 카운트 → RAG Binding 상태로 대체 */
export function ChannelHeader({ channel, name, threadOpen, onOpenThread }: { channel: ChannelDetail | null; name: string; threadOpen: boolean; onOpenThread: () => void }) {
  const { layout, setLayout } = useUiStore();
  const b = channel?.binding;
  return (
    <header className="flex-none h-14 flex items-center gap-2.5 px-5 border-b border-line bg-surface">
      <div className="font-bold text-[16px] whitespace-nowrap">
        <span className="text-muted">{channel?.type === 'private' ? '⌂' : '#'}</span> {name}
      </div>
      {channel && channel.type !== 'public' && <Badge tone="outline" className="!rounded-none">{channel.type}</Badge>}
      {b && (
        <Badge tone={b.enabled ? 'mint' : 'muted'} className="!rounded-none" title={b.enabled ? 'RAG 응답 활성' : 'RAG 응답 비활성'}>
          RAG {b.enabled ? (b.mode === 'TRIGGER_WORD' ? `· ${b.trigger_word ?? 'trigger'}` : 'ON') : 'OFF'}
        </Badge>
      )}
      {channel && (
        <span className="text-[12px] text-muted truncate min-w-0" title={channel.purpose ?? ''}>
          {channel.display_name} · 멤버 {channel.member_count}
          {b ? ` · ${MODE_LABEL[b.conversation_mode] ?? b.conversation_mode}` : ''}
          {channel.purpose ? ` · ${channel.purpose}` : ''}
        </span>
      )}
      <div className="ml-auto flex items-center gap-2 flex-none">
        <Segmented size="sm" value={layout} onChange={setLayout} options={[{ value: 'A', label: 'A · 패널', title: '3열 · 사이드 패널' }, { value: 'B', label: 'B · 오버레이', title: '2열 · 스레드 오버레이' }]} />
        {!threadOpen && (
          <button type="button" onClick={onOpenThread} className="btn">
            스레드 열기
          </button>
        )}
      </div>
    </header>
  );
}
