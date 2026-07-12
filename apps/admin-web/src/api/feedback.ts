import { useQuery } from '@tanstack/react-query';
import { api } from './client';
import { qk } from './queryKeys';
import type {
  FeedbackByChannel,
  FeedbackMessage,
  FeedbackSummary,
  FeedbackValue,
  MessageFeedbackDetail,
} from '../types';

export function useFeedbackSummary() {
  return useQuery({
    queryKey: qk.feedbackSummary,
    queryFn: () => api.get<FeedbackSummary>('/feedback/summary'),
  });
}

export function useFeedbackByChannel() {
  return useQuery({
    queryKey: qk.feedbackByChannel,
    queryFn: () => api.get<FeedbackByChannel[]>('/feedback/by-channel'),
  });
}

export function useFeedbackMessages(value: FeedbackValue = 'DOWN') {
  return useQuery({
    queryKey: qk.feedbackMessages(value),
    queryFn: () => api.get<FeedbackMessage[]>('/feedback/messages', { value }),
  });
}

export function useMessageFeedback(messageId: string | undefined) {
  return useQuery({
    queryKey: ['feedback', 'message', messageId],
    queryFn: () => api.get<MessageFeedbackDetail>(`/messages/${messageId}/feedback`),
    enabled: !!messageId,
  });
}
