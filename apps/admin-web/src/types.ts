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
export type Role = 'SYS_ADMIN' | 'DOC_ADMIN' | 'QUALITY_EVALUATOR' | 'AUDITOR';

export interface Principal {
  id: string | null;
  login_id: string | null;
  display_name: string | null;
  roles: Role[];
}

// ----- Documents (§7.5 / §9.5) -----
export type SecurityLevel = 'PUBLIC' | 'INTERNAL' | 'CONFIDENTIAL' | 'SECRET';
export type DocumentStatus =
  | 'UPLOADED'
  | 'INDEXING'
  | 'ACTIVE'
  | 'INACTIVE'
  | 'DELETED'
  | 'FAILED';

export interface DocumentView {
  id: string;
  title: string;
  category: string | null;
  department: string | null;
  security_level: string;
  status: string;
  active_version_id: string | null;
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

export interface UploadDocumentResult {
  document: DocumentView;
  version: DocumentVersionView;
}

export interface ReindexResult {
  index_job_id: string;
  status: string;
}

// ----- Index Jobs (index_jobs; parser-indexer §7.7) -----
export type IndexStage =
  | 'PARSING'
  | 'CHUNKING'
  | 'EMBEDDING'
  | 'UPSERTING'
  | 'VALIDATING'
  | null;

export interface IndexJobView {
  id: string;
  document_version_id: string | null;
  status: string;
  stage: IndexStage | string | null;
  progress?: number | null;
  error?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

// ----- Channels + Bindings (§7.5 / §9.6; rag_schemas.binding) -----
export type ChannelMode = 'DEDICATED_CHANNEL' | 'TRIGGER_WORD';
export type ConversationMode = 'CHANNEL' | 'THREAD' | 'STATELESS';

/** rag_schemas.KnowledgeScope (libs/schemas/binding.py). */
export interface KnowledgeScope {
  categories: string[];
  departments: string[];
  security_levels: string[];
  document_ids: string[];
}

export interface ChannelView {
  id: string;
  team_id: string;
  team_domain: string | null;
  channel_id: string;
  channel_name: string;
  display_name: string | null;
  bindings?: BindingView[];
}

/** Mirrors admin.api.channels._binding_view. NEVER carries a secret value. */
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
  /** K8s Secret NAME only — never the URL/value (FR-OPS-010). */
  secret_ref: string;
  secret_updated_at: string | null;
}

export interface ChannelCreate {
  team_id: string;
  channel_id: string;
  channel_name: string;
  team_domain?: string | null;
  display_name?: string | null;
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
  secret_ref: string;
}

export type BindingUpdate = Partial<Omit<BindingCreate, 'secret_ref'>>;

export interface SecretUpdateResult {
  channel_id: string;
  binding_id: string;
  secret_ref: string;
  secret_updated_at: string;
}

export interface ConnectionTestResult {
  channel_id: string;
  secret_ref: string;
  ok: boolean;
  detail: string | null;
}

// ----- Chat Jobs (§7.5) -----
export interface ChatJobView {
  id: string;
  event_id: string | null;
  conversation_id: string | null;
  status: string;
  error: string | null;
  queued_at: string | null;
  started_at: string | null;
  completed_at: string | null;
}

export interface RetryDeliveryResult {
  chat_job_id: string;
  delivery_id: string;
  status: string;
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
export interface EvaluationDataset {
  id: string;
  name: string;
  item_count?: number;
  created_at?: string | null;
}

export interface EvaluationRun {
  id: string;
  dataset_id?: string;
  status?: string;
  recall_at_10?: number | null;
  faithfulness?: number | null;
  created_at?: string | null;
}

export interface PromoteCandidateResult {
  candidate_id: string;
  message_id: string;
  status: string;
}

// ----- Audit Logs (§7.5, FR-AUTH-005) -----
export interface AuditLogView {
  id: string;
  actor?: string | null;
  actor_login_id?: string | null;
  method?: string | null;
  path?: string | null;
  action?: string | null;
  target?: string | null;
  status_code?: number | null;
  created_at?: string | null;
}

// ----- Feedback (v1.1, §7.5 / §8.4) -----
export type FeedbackValue = 'UP' | 'DOWN';

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
  content: string;
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
