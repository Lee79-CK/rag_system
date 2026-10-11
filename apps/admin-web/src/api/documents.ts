import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./client";
import { qk } from "./queryKeys";
import type {
  BatchUploadItem,
  DocumentChunkView,
  DocumentVersionView,
  DocumentView,
  ReindexResult,
  UpdateDocumentChannelsResult,
  UploadDocumentResult,
} from "../types";

export function useDocuments() {
  return useQuery({
    queryKey: qk.documents,
    queryFn: () => api.get<DocumentView[]>("/documents"),
  });
}

export function useDocument(id: string | undefined) {
  return useQuery({
    queryKey: qk.document(id ?? ""),
    queryFn: () => api.get<DocumentView>(`/documents/${id}`),
    enabled: !!id,
  });
}

export function useDocumentVersions(id: string | undefined) {
  return useQuery({
    queryKey: qk.documentVersions(id ?? ""),
    queryFn: () => api.get<DocumentVersionView[]>(`/documents/${id}/versions`),
    enabled: !!id,
  });
}

/** 일괄 업로드 상한 — 서버(MAX_UPLOAD_FILES · MAX_UPLOAD_BYTES)가 최종 판정, 화면은 미리 막는다. */
export const MAX_UPLOAD_FILES = 10;
export const MAX_UPLOAD_TOTAL_BYTES = 100 * 1024 * 1024;
export const UPLOAD_EXTENSIONS = [
  "pdf",
  "docx",
  "pptx",
  "xlsx",
  "txt",
  "md",
  "html",
];

export interface BatchUploadArgs extends Omit<UploadArgs, "file"> {
  files: File[];
}

/** POST /documents/batch — 여러 파일을 공통 메타·허용 채널로 등록. 결과는 파일별(일부 실패 가능). */
export function useUploadDocuments() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (args: BatchUploadArgs) => {
      const fd = new FormData();
      for (const f of args.files) fd.append("files", f);
      // 제목은 파일 1개일 때만 (서버도 여러 파일 + 제목은 422)
      if (args.title && args.files.length === 1) fd.append("title", args.title);
      if (args.category) fd.append("category", args.category);
      if (args.department) fd.append("department", args.department);
      if (args.security_level) fd.append("security_level", args.security_level);
      for (const ch of args.allowed_channel_ids ?? []) {
        fd.append("allowed_channel_ids", ch);
      }
      if (args.start_indexing) fd.append("start_indexing", "true");
      return api.upload<BatchUploadItem[]>("/documents/batch", fd);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: qk.documents });
      qc.invalidateQueries({ queryKey: ["indexJobs"] });
    },
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
  /** true 면 업로드 직후 색인 Job 생성 (FR-IDX-010). */
  start_indexing?: boolean;
}

export function useUploadDocument() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (args: UploadArgs) => {
      const fd = new FormData();
      fd.append("file", args.file);
      if (args.title) fd.append("title", args.title);
      if (args.category) fd.append("category", args.category);
      if (args.department) fd.append("department", args.department);
      if (args.security_level) fd.append("security_level", args.security_level);
      for (const ch of args.allowed_channel_ids ?? []) {
        fd.append("allowed_channel_ids", ch);
      }
      if (args.start_indexing) fd.append("start_indexing", "true");
      return api.upload<UploadDocumentResult>("/documents", fd);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: qk.documents });
      qc.invalidateQueries({ queryKey: ["indexJobs"] });
    },
  });
}

export function useReindexDocument() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) =>
      api.post<ReindexResult>(`/documents/${id}/reindex`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: qk.documents });
      qc.invalidateQueries({ queryKey: ["indexJobs"] });
    },
  });
}

/** 허용 채널 전체 교체. 변경 시 서버가 재색인 Job 을 만든다(Qdrant payload 반영). */
export function useUpdateDocumentChannels() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, channelIds }: { id: string; channelIds: string[] }) =>
      api.patch<UpdateDocumentChannelsResult>(`/documents/${id}`, {
        allowed_channel_ids: channelIds,
      }),
    onSuccess: (_res, { id }) => {
      qc.invalidateQueries({ queryKey: qk.documents });
      qc.invalidateQueries({ queryKey: qk.document(id) });
      qc.invalidateQueries({ queryKey: ["indexJobs"] });
    },
  });
}

/** INACTIVE → 재색인으로 재활성화 (현재 허용 채널로 검색 색인을 다시 쓴다). */
export function useActivateDocument() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) =>
      api.post<ReindexResult>(`/documents/${id}/activate`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: qk.documents });
      qc.invalidateQueries({ queryKey: ["indexJobs"] });
    },
  });
}

export function useDeactivateDocument() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) =>
      api.post<DocumentView>(`/documents/${id}/deactivate`),
    onSuccess: () => qc.invalidateQueries({ queryKey: qk.documents }),
  });
}

export function useDeleteDocument() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) =>
      api.del<{ id: string; status: string }>(`/documents/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: qk.documents }),
  });
}

// ----- 원본 파일 · 색인 텍스트 (FR-DOC-010) -----

/** 확장자 → 브라우저 미리보기 방식. 서버도 pdf·txt·md 만 inline 으로 내려준다. */
export type PreviewKind = "pdf" | "text" | "none";

export function previewKind(fileName: string | null | undefined): PreviewKind {
  const ext = (fileName ?? "").split(".").pop()?.toLowerCase() ?? "";
  if (ext === "pdf") return "pdf";
  if (ext === "txt" || ext === "md") return "text";
  return "none";
}

/** 원본을 내려받아 원래 파일명으로 저장한다(X-Auth-User 를 보내야 하므로 fetch → Blob → 임시 링크). */
export async function downloadDocument(
  id: string,
  version?: number,
): Promise<void> {
  const { blob, filename } = await api.blob(`/documents/${id}/file`, {
    version,
    disposition: "attachment",
  });
  const url = URL.createObjectURL(blob);
  try {
    const a = document.createElement("a");
    a.href = url;
    a.download = filename ?? "document";
    document.body.appendChild(a);
    a.click();
    a.remove();
  } finally {
    // 클릭 직후 revoke 하면 일부 브라우저가 저장을 취소한다 — 다음 tick 에 해제
    setTimeout(() => URL.revokeObjectURL(url), 0);
  }
}

export interface DocumentPreview {
  /** pdf → iframe 용 object URL */
  url: string | null;
  /** txt/md → 본문 */
  text: string | null;
}

/** 원본 미리보기(inline). enabled 일 때만 내려받고, object URL 은 바뀌거나 언마운트될 때 해제한다. */
export function useDocumentPreview(
  id: string | undefined,
  kind: PreviewKind,
  enabled: boolean,
) {
  const query = useQuery({
    queryKey: [...qk.document(id ?? ""), "preview"],
    queryFn: async () => {
      const { blob } = await api.blob(`/documents/${id}/file`, {
        disposition: "inline",
      });
      return blob;
    },
    enabled: !!id && enabled && kind !== "none",
    staleTime: 5 * 60 * 1000,
  });
  const [preview, setPreview] = useState<DocumentPreview>({
    url: null,
    text: null,
  });
  useEffect(() => {
    const blob = query.data;
    if (!blob) {
      setPreview({ url: null, text: null });
      return;
    }
    if (kind === "text") {
      let alive = true;
      blob.text().then((text) => alive && setPreview({ url: null, text }));
      return () => {
        alive = false;
      };
    }
    // PDF 뷰어가 형식을 알도록 type 을 명시한 Blob 으로 URL 생성
    const url = URL.createObjectURL(
      new Blob([blob], { type: "application/pdf" }),
    );
    setPreview({ url, text: null });
    return () => URL.revokeObjectURL(url);
  }, [query.data, kind]);
  return { ...query, preview };
}

/** 색인 텍스트(청크) — 탭이 열릴 때만 조회. meta: version · count · document_status. */
export function useDocumentChunks(id: string | undefined, enabled: boolean) {
  return useQuery({
    queryKey: [...qk.document(id ?? ""), "chunks"],
    queryFn: () =>
      api.getEnvelope<DocumentChunkView[]>(`/documents/${id}/chunks`),
    enabled: !!id && enabled,
  });
}
