'use client';

import { useParams } from 'next/navigation';
import { ChatView } from '@/components/chat/ChatView';

/** THR-03 독립 URL: /ch/{channel}/thread/{root_id} */
export default function ThreadPage() {
  const { channel, rootId } = useParams<{ channel: string; rootId: string }>();
  return <ChatView channelName={decodeURIComponent(channel)} rootId={rootId} />;
}
