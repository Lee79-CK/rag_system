/** Centralized React Query keys. */
export const qk = {
  whoami: ['whoami'] as const,
  documents: ['documents'] as const,
  document: (id: string) => ['documents', id] as const,
  documentVersions: (id: string) => ['documents', id, 'versions'] as const,
  indexJobs: (status?: string) => ['indexJobs', status ?? 'all'] as const,
  channels: ['channels'] as const,
  channel: (id: string) => ['channels', id] as const,
  chatJobs: (status?: string) => ['chatJobs', status ?? 'all'] as const,
  settings: ['settings'] as const,
  evaluationDatasets: ['evaluation', 'datasets'] as const,
  evaluationRuns: ['evaluation', 'runs'] as const,
  audit: (filters: object) => ['audit', filters] as const,
  feedbackSummary: ['feedback', 'summary'] as const,
  feedbackByChannel: ['feedback', 'by-channel'] as const,
  feedbackMessages: (value: string) => ['feedback', 'messages', value] as const,
};
