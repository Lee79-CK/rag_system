/**
 * Shared TypeScript types mirroring rag_schemas + admin-api view shapes.
 * SSOT: libs/schemas (rag_schemas) and apps/admin-api/src/admin/api/*.py.
 * These are hand-mirrored (closed network — no codegen against a live server).
 */

// ----- Response envelope (admin.api.responses.envelope) -----
export interface Meta {
  count?: number;
  [key: string]: unknown;
}

export interface Envelope<T> {
  data: T;
  meta: Meta;
}

export interface ErrorDetail {
  code: string;
  message: string;
  request_id?: string;
  detail?: Record<string, unknown> | null;
}

export interface ErrorResponse {
  error: ErrorDetail;
}

// ----- Auth / RBAC (docs/TDD.md §7.5) -----
export type Role = "SYS_ADMIN" | "DOC_ADMIN" | "QUALITY_EVALUATOR" | "AUDITOR";

export interface Principal {
  id: string | null;
  login_id: string | null;
  display_name: string | null;
  roles: Role[];
}

// ----- Documents (§7.5 / §9.5) -----
export type SecurityLevel = "PUBLIC" | "INTERNAL" | "CONFIDENTIAL" | "SECRET";
export type DocumentStatus =
  "UPLOADED" | "INDEXING" | "ACTIVE" | "INACTIVE" | "DELETED" | "FAILED";

export interface DocumentView {
  id: string;
  title: string;
  category: string | null;
  department: string | null;
  security_level: string;
  status: string;
  active_version_id: string | null;
  /** 허용 채널(chat_channels.id) — Qdrant payload allowed_channel_ids 의 원천 (FR-DOC-004). */
  allowed_channel_ids: string[];
  created_at: string | null;
}

export interface DocumentVersionView {
  id: string;
  document_id: string;
  version: number;
  hash: string;
  file_path: string;
  file_size: number;
  status: string;
  created_at: string | null;
}

/** GET /documents/{id}/chunks 행 — Qdrant 에 색인된 텍스트(AI 가 검색·답변에 쓰는 내용). */
export interface DocumentChunkView {
  chunk_index: number;
  page_start: number | null;
  page_end: number | null;
  section: string | null;
  text: string;
  is_active: boolean;
}

export interface UploadDocumentResult {
  document: DocumentView;
  version: DocumentVersionView;
  allowed_channel_ids: string[];
  index_job_id?: string;
  index_job_status?: string;
}

export interface ReindexResult {
  index_job_id: string;
  status: string;
  trigger: string | null;
  error: string | null;
}

/** 409 DUPLICATE_DOCUMENT 의 error.detail — 기존 문서에 채널 연결을 제안할 때 사용. */
export interface DuplicateDocumentDetail {
  existing_document_id: string;
  existing_document_title: string | null;
  existing_document_status: string | null;
}

/** POST /documents/batch 의 파일별 결과 — 실패해도 나머지 파일은 등록된다. */
export interface BatchUploadItem {
  file_name: string | null;
  ok: boolean;
  document?: DocumentView;
  version?: DocumentVersionView;
  allowed_channel_ids?: string[];
  index_job_id?: string;
  index_job_status?: string;
  error?: {
    code: string;
    message: string;
    /** DUPLICATE_DOCUMENT 이면 DuplicateDocumentDetail */
    detail: Record<string, unknown> | null;
  };
}

/** PATCH /documents/{id} 결과 — ACL 교체 + 자동 재색인 (FR-DOC-004). */
export interface UpdateDocumentChannelsResult {
  document: DocumentView;
  changed: boolean;
  added: string[];
  removed: string[];
  index_job: ReindexResult | null;
  /** NO_ACTIVE_VERSION | STATUS_<status> | PENDING_JOB_REUSED */
  reindex_skipped_reason: string | null;
}

// ----- Index Jobs (index_jobs; parser-indexer §7.7) -----
export type IndexStage =
  | "WAITING"
  | "PARSING"
  | "CHUNKING"
  | "EMBEDDING"
  | "UPSERTING"
  | "VALIDATING"
  | "DONE"
  | null;

export type IndexJobStatus =
  "PENDING" | "RUNNING" | "COMPLETED" | "FAILED" | "CANCELLED";

/** GET /api/v1/index-jobs 행 — 문서 제목·버전이 조인된 index_jobs. */
export interface IndexJobView {
  id: string;
  document_id: string;
  document_title: string;
  version: number;
  document_version_id: string;
  status: IndexJobStatus | string;
  stage: IndexStage | string | null;
  progress: number | null;
  chunk_count: number | null;
  vector_count: number | null;
  error: string | null;
  created_at: string | null;
  started_at: string | null;
  completed_at: string | null;
  /** RUNNING 인데 INDEX_JOB_STALE_MINUTES 이상 진행이 없는 Job (비정상 종료 의심) */
  stale: boolean;
}

// ----- Channels + Bindings (§7.5 / §9.6; rag_schemas.binding) -----
export type ChannelMode = "DEDICATED_CHANNEL" | "TRIGGER_WORD";
export type ConversationMode = "CHANNEL" | "THREAD" | "STATELESS";

/** rag_schemas.KnowledgeScope (libs/schemas/binding.py). */
export interface KnowledgeScope {
  categories: string[];
  departments: string[];
  security_levels: string[];
  document_ids: string[];
}

/** Web Chat 채널 (admin.api.channels._channel_view). id = Qdrant allowed_channel_ids 값. */
export interface ChannelView {
  id: string;
  name: string;
  display_name: string;
  type: "public" | "private";
  purpose: string | null;
  archived: boolean;
  created_at: string | null;
  member_count?: number;
  bindings?: BindingView[];
}

/** Mirrors admin.api.channels._binding_view. */
export interface BindingView {
  id: string;
  channel_ref: string;
  mode: string;
  trigger_word: string | null;
  enabled: boolean;
  knowledge_scope_id: string | null;
  history_turns: number;
  mention_user: boolean;
  ack_message_enabled: boolean;
  feedback_enabled: boolean;
  direct_llm_enabled: boolean;
}

export interface ChannelCreate {
  name: string;
  display_name: string;
  type?: "public" | "private";
  purpose?: string | null;
}

export interface BindingCreate {
  mode: string;
  trigger_word?: string | null;
  enabled: boolean;
  knowledge_scope_id?: string | null;
  history_turns: number;
  mention_user: boolean;
  ack_message_enabled: boolean;
  feedback_enabled: boolean;
  direct_llm_enabled: boolean;
}

export type BindingUpdate = Partial<BindingCreate>;

export interface ChannelMemberView {
  user_id: string;
  email: string;
  display_name: string;
  role: "member" | "channel_admin";
  joined_at: string | null;
}

// ----- Web Chat 사용자 (admin.api.chat_users) -----
export interface ChatUserView {
  id: string;
  email: string;
  display_name: string;
  role: "user" | "admin";
  is_bot: boolean;
  is_active: boolean;
  must_change_password: boolean;
  created_at: string | null;
}

/** 생성/재설정 응답에만 1회 포함 — 화면을 닫으면 다시 볼 수 없다. */
export interface ChatUserWithTempPassword extends ChatUserView {
  temporary_password: string;
}

// ----- Chat Jobs (§7.5) -----
export interface ChatJobView {
  id: string;
  post_id: string | null;
  bot_post_id: string | null;
  conversation_id: string | null;
  status: string;
  error: string | null;
  queued_at: string | null;
  started_at: string | null;
  completed_at: string | null;
}

// ----- Settings (§7.5 / §5.1) -----
export interface SettingView {
  key: string;
  value: unknown;
  version: number;
  updated_by: string | null;
  updated_at: string | null;
}

// ----- Evaluation (§13) -----
// ----- Evaluation candidates (§7.5, §13.3) -----
export type CandidateStatus = 'PENDING' | 'ACCEPTED' | 'REJECTED';
/** tools/evaluation CaseType 과 동일 */
export type EvalCaseType = 'single_doc' | 'multi_doc' | 'table' | 'definition' | 'no_answer' | 'ambiguous';

export interface PromoteCandidateResult {
  candidate_id: string;
  message_id: string;
  status: CandidateStatus;
  /** false = 이미 승격된 답변 (기존 후보 반환) */
  created: boolean;
}

export interface EvaluationCandidate {
  id: string;
  message_id: string | null;
  channel_id: string;
  question: string;
  answer: string;
  cited_documents: string[];
  case_type: EvalCaseType;
  answer_gist: string;
  expected_documents: string[];
  expected_pages: number[];
  answerable: boolean;
  status: CandidateStatus;
  note: string | null;
  promoted_by: string;
  created_at: string | null;
  updated_at: string | null;
}

export type EvaluationRunStatus = 'RUNNING' | 'COMPLETED' | 'FAILED';

/** rag_eval.MetricSummary (0~1) */
export interface EvaluationMetrics {
  total: number;
  recall_at_10: number;
  citation_precision: number;
  no_answer_safety: number;
  answerable_answered: number;
  by_type: Record<string, number>;
  /** 지표별 적용 문항 수 (0 이면 해당 지표 없음 — 값 0.0 은 의미 없음) */
  applicable?: Partial<Record<'recall_at_10' | 'citation_precision' | 'no_answer_safety' | 'answerable_answered', number>>;
}

export interface EvaluationRun {
  id: string;
  status: EvaluationRunStatus;
  dataset: string;
  total: number;
  done: number;
  metrics: EvaluationMetrics | null;
  error: string | null;
  started_by: string;
  created_at: string | null;
  updated_at: string | null;
  completed_at: string | null;
}

export interface EvaluationRunResult {
  seq: number;
  candidate_id: string | null;
  case_id: string;
  question: string;
  case_type: EvalCaseType;
  answerable: boolean;
  answer: string;
  insufficient_evidence: boolean;
  expected_documents: string[];
  citations: string[];
  retrieved: string[];
  /** 1.0 / 0.0, 해당 없음 null */
  recall_at_10: number | null;
  citation_precision: number | null;
  no_answer_safe: number | null;
  answerable_answered: number | null;
  latency_ms: number | null;
  error: string | null;
}

export interface EvaluationRunDetail extends EvaluationRun {
  results: EvaluationRunResult[];
}

export type CandidateUpdate = Partial<
  Pick<EvaluationCandidate, 'case_type' | 'answer_gist' | 'expected_documents' | 'expected_pages' | 'answerable' | 'status' | 'note'>
>;

// ----- Audit Logs (§7.5, FR-AUTH-005) -----
/** GET /api/v1/audit-logs 행. method/path 는 미들웨어 기록("METHOD /path")일 때만, 핸들러 기록은 action 이름. */
export interface AuditLogView {
  id: string;
  actor: string;
  method: string | null;
  path: string | null;
  action: string;
  target: string | null;
  /** OK | DENIED | ERROR */
  result: string;
  status_code: number | null;
  detail: Record<string, unknown> | null;
  created_at: string | null;
}

// ----- Feedback (v1.1, §7.5 / §8.4) -----
export type FeedbackValue = "UP" | "DOWN";

export interface FeedbackSummary {
  up: number;
  down: number;
  total: number;
  satisfaction_ratio: number | null;
}

export interface FeedbackByChannel {
  channel_id: string;
  up: number;
  down: number;
  total: number;
  satisfaction_ratio: number | null;
}

export interface FeedbackCitation {
  chunk_id: string | null;
  document_id: string | null;
  score: number | null;
  rank: number | null;
}

export interface FeedbackMessage {
  message_id: string;
  conversation_id: string;
  /** 질문 원문 (chat_jobs 로 연결, 없으면 null) */
  question: string | null;
  content: string;
  /** 평가셋 후보로 승격됐으면 그 상태 */
  candidate_status: CandidateStatus | null;
  channel_id: string;
  value: FeedbackValue;
  created_at: string | null;
  citations: FeedbackCitation[];
}

export interface MessageFeedbackDetail {
  message_id: string;
  up: number;
  down: number;
  satisfaction_ratio: number | null;
  entries: {
    user_id: string;
    value: FeedbackValue;
    channel_id: string;
    created_at: string | null;
    updated_at: string | null;
  }[];
}

// ----- Dashboard aggregate (client-composed) -----
export interface DashboardStatus {
  documents: number;
  channels: number;
  enabledBindings: number;
  chatJobs: number;
  deadLetterJobs: number;
  feedback: FeedbackSummary | null;
}

// ----- 오류 로그 (admin.api.errors, FR-OPS-011) -----
export type ErrorSource = "chat" | "index" | "admin";

/** DB 에 기록된 오류 1건 — 대화 작업(chat_jobs) · 색인 작업(index_jobs) · 관리 API(audit_logs). */
export interface ErrorEventView {
  id: string;
  source: ErrorSource;
  ref_id: string;
  occurred_at: string | null;
  status: string;
  error: string | null;
  summary: string;
  context: Record<string, string | number | null>;
  /** 관련 로그를 볼 서비스(추정) — 서버 allowlist 중 하나 */
  service: string;
}

export interface PodLogLine {
  ts: string | null;
  text: string;
}

export interface PodLogView {
  pod: string;
  previous: boolean;
  truncated: boolean;
  lines: PodLogLine[];
}

export interface ErrorLogsResult {
  service: string;
  namespace: string;
  since: string;
  until: string;
  reason: string | null;
  pods: PodLogView[];
}
