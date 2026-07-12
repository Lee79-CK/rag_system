import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from './client';
import { qk } from './queryKeys';
import type {
  DocumentVersionView,
  DocumentView,
  ReindexResult,
  UploadDocumentResult,
} from '../types';

export function useDocuments() {
  return useQuery({
    queryKey: qk.documents,
    queryFn: () => api.get<DocumentView[]>('/documents'),
  });
}

export function useDocument(id: string | undefined) {
  return useQuery({
    queryKey: qk.document(id ?? ''),
    queryFn: () => api.get<DocumentView>(`/documents/${id}`),
    enabled: !!id,
  });
}

export function useDocumentVersions(id: string | undefined) {
  return useQuery({
    queryKey: qk.documentVersions(id ?? ''),
    queryFn: () => api.get<DocumentVersionView[]>(`/documents/${id}/versions`),
    enabled: !!id,
  });
}

export interface UploadArgs {
  file: File;
  title?: string;
  category?: string;
  department?: string;
  security_level?: string;
  /** Allowed channel ids for ACL (FR-DOC / KnowledgeScope). */
  allowed_channel_ids?: string[];
}

export function useUploadDocument() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (args: UploadArgs) => {
      const fd = new FormData();
      fd.append('file', args.file);
      if (args.title) fd.append('title', args.title);
      if (args.category) fd.append('category', args.category);
      if (args.department) fd.append('department', args.department);
      if (args.security_level) fd.append('security_level', args.security_level);
      for (const ch of args.allowed_channel_ids ?? []) {
        fd.append('allowed_channel_ids', ch);
      }
      return api.upload<UploadDocumentResult>('/documents', fd);
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: qk.documents }),
  });
}

export function useReindexDocument() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.post<ReindexResult>(`/documents/${id}/reindex`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: qk.documents });
      qc.invalidateQueries({ queryKey: ['indexJobs'] });
    },
  });
}

export function useDeactivateDocument() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.post<DocumentView>(`/documents/${id}/deactivate`),
    onSuccess: () => qc.invalidateQueries({ queryKey: qk.documents }),
  });
}

export function useDeleteDocument() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.del<{ id: string; status: string }>(`/documents/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: qk.documents }),
  });
}
