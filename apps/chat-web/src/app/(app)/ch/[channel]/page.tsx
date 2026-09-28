'use client';

import { useParams } from 'next/navigation';
import { ChatView } from '@/components/chat/ChatView';

export default function ChannelPage() {
  const { channel } = useParams<{ channel: string }>();
  return <ChatView channelName={decodeURIComponent(channel)} rootId={null} />;
}
