# RAG Platform — Mattermost 기반 폐쇄형 Private Cloud RAG LLM 챗봇

사내 Mattermost Channel에 게시된 질문을 Outgoing Webhook으로 수신하여, Channel별로 격리된 지식 범위 내에서 RAG 파이프라인(Embedding → Qdrant 검색 → Re-rank → vLLM 생성)을 수행하고, 출처와 👍/👎 피드백 버튼이 포함된 한국어 답변을 Incoming Webhook으로 동일 Channel에 게시하는 시스템입니다.

> - 요구사항: `docs/PRD.md` (PRD-RAG-CHATBOT-POC-001 v1.1)
> - 기술 설계: `docs/TDD.md` (TDD-RAG-CHATBOT-POC-001 v1.2) — **구현의 SSOT**
> - Claude Code 컨텍스트: `CLAUDE.md`
> - 보안 체크리스트: `docs/security-checklist.md`

## 0. 구현 현황

TDD §15 로드맵 **M1–M11 전 마일스톤 구현 완료**. 로컬은 GPU/모델 미배치 전제로 **mock 엔진 + mock LLM** 기준.

| 지표 | 결과 |
|---|---|
| Python 테스트 | **112 passed, 1 skipped** (Docker-gated Qdrant 격리 테스트) |
| Lint | `ruff check .` clean (전 패키지) |
| Helm | `helm lint` clean · `helm template` 45개 리소스 렌더 |
| admin-web | `npm run typecheck` + `vite build` → `dist/` OK |

| 구성요소 | 위치 | 테스트 |
|---|---|---|
| 공유 스키마/유틸 (M1) | `libs/schemas·common·observability·mattermost-adapter` | 28 |
| mattermost-bridge (M2) | `apps/mattermost-bridge` | 14 |
| admin-api + Alembic (M3) | `apps/admin-api` | 16 |
| embedding/reranker (M4) | `apps/embedding-api`·`apps/reranker-api` | 20 |
| parser-indexer (M5) | `apps/parser-indexer` | 13 |
| rag domain/worker/feedback (M6) | `apps/rag-api` | 10 |
| p95 측정 (M7) | `scripts/measure_latency.py` | — |
| admin-web (M8) | `apps/admin-web` (React) | build |
| Channel 격리 Gate (M9) | `tests/channel-isolation` (CH-001~010) | 11 |
| Helm/NetworkPolicy/모니터링 (M10) | `deploy/helm/rag-platform` | helm lint |
| 평가 runner + perf (M11) | `tools/evaluation`, `tests/performance` | 6 |

**로컬 실행 캐비엇**: 이 저장소는 Intel macOS(GPU 없음)에서 개발되어 실 모델 의존성(`torch`/`FlagEmbedding`)은
optional `models` extra로 분리했다. 기본 경로는 `EMBEDDING_MOCK=1`/`RERANKER_MOCK=1` + `make mock-llm`.
GPU 노드에서는 `uv sync --extra models` 로 실 엔진을 활성화한다. testcontainers 통합/격리 테스트는 Docker 필요.

**알려진 후속(admin-web가 graceful degrade 처리)**: admin-api에 아직 없는 조회/액션 엔드포인트 —
`GET /index-jobs`·`/index-jobs/{id}/retry`, `GET /audit-logs`(감사 로그는 기록만 하고 조회 API 미제공),
`POST /evaluation/candidates`(👎→평가셋 승격). 프론트는 빈 상태로 안전하게 동작한다.

> **명령 안내**: 아래 §2~§9의 일부 `make` 타깃/스크립트는 운영 절차를 설명하는 예시로, 현재 저장소에
> 실제 구현된 것은 다음이다 — `make install lint fmt test test-cov test-isolation test-integration
> evaluate perf-webhook-burst mock-llm qdrant-init seed openapi infra-up infra-down clean`,
> 스크립트는 `scripts/export_openapi.py`·`measure_latency.py`·`seed_dev.sql`. 그 외(`make dev`,
> `verify-wheels`, `build-images`, `test-contract/e2e`, `seed-vectors`, `sign_feedback.py` 등)는
> 배포 파이프라인 확장 시 추가 예정인 계획 항목이다.

## 목차

0. [구현 현황](#0-구현-현황)
1. [아키텍처 개요](#1-아키텍처-개요)
2. [사전 준비 및 오픈소스 S/W 설치](#2-사전-준비-및-오픈소스-sw-설치)
3. [Config / Secret 설정](#3-config--secret-설정)
4. [DB 초기화 및 샘플 데이터](#4-db-초기화-및-샘플-데이터)
5. [로컬 실행](#5-로컬-실행)
6. [테스트](#6-테스트)
7. [빌드 및 배포](#7-빌드-및-배포)
8. [RAG 성능 평가](#8-rag-성능-평가)
9. [트러블슈팅](#9-트러블슈팅)

---

## 1. 아키텍처 개요

```text
사용자 ──> Mattermost Channel
              │  Outgoing Webhook (질문)
              ▼
        mattermost-bridge ──> Redis Queue(RQ) ──> rag-worker
              ▲                                     │
              │  Incoming Webhook (답변+👍/👎 버튼)    ├─> embedding-api (BGE-M3, CPU)
              │  Interactive Action (피드백 클릭)      ├─> qdrant (Channel/ACL Filter 검색)
              └─────────────────────────────────────┤─> reranker-api (BGE-reranker, CPU)
                                                    ├─> vLLM ×2 (GPU 1장/Replica)
                                                    └─> PostgreSQL (대화/Job/피드백)

관리자 ──> admin-web ──> admin-api ──> PostgreSQL / K8s Job(parser-indexer)
```

| 서비스 | 역할 | 포트(로컬) |
|---|---|---|
| `mattermost-bridge` | Webhook 수신/검증/Job 등록, 답변 게시, 피드백 수신 | 8001 |
| `rag-api` / `rag-worker` | RAG 파이프라인 오케스트레이션 | 8002 / - |
| `admin-api` | 문서/Channel Binding/설정/피드백 관리 | 8003 |
| `admin-web` | 관리자 Portal (React) | 5173 |
| `embedding-api` | BGE-M3 임베딩 | 8004 |
| `reranker-api` | BGE-reranker-v2-m3 재정렬 | 8005 |
| `parser-indexer` | 문서 파싱/색인 배치 (CLI) | - |

**핵심 불변 규칙** (자세한 내용은 `CLAUDE.md`):
- Python **3.12 고정**, 의존성은 cp312 바이너리 휠만 (sdist 빌드 금지)
- 런타임 외부 네트워크 호출 금지 — 모델은 로컬 경로 로딩만
- Qdrant 검색은 `build_filter()` 없이 호출 금지 (Channel 격리 100%)
- Secret(Token/Webhook URL)은 로그·응답·repr에 절대 노출 금지

---

## 2. 사전 준비 및 오픈소스 S/W 설치

### 2.1 요구 버전

| 구분 | 버전 | 비고 |
|---|---|---|
| Python | 3.12.x | `requires-python = ">=3.12,<3.13"` |
| uv | 최신 | Python 패키지/venv 관리 |
| Node.js | 20 LTS | admin-web |
| Docker / Podman | 최신 | 로컬 인프라 및 이미지 빌드 |
| PostgreSQL | 16 | 컨테이너 |
| Redis | 7 | 컨테이너 |
| Qdrant | 1.x | 컨테이너 |
| vLLM | 최신 stable | GPU 노드 전용 (로컬은 Mock 대체 가능) |

### 2.2 개발 도구 설치

```bash
# uv (Python 패키지 관리자)
curl -LsSf https://astral.sh/uv/install.sh | sh
# 폐쇄망: 내부 Nexus에서 uv 바이너리 다운로드 후 PATH 등록

# Python 3.12 (uv로 관리)
uv python install 3.12

# 내부 PyPI 지정 (폐쇄망 필수) — 프로젝트 루트 uv.toml 또는 ~/.config/uv/uv.toml
cat > uv.toml << 'UVEOF'
[[index]]
name = "internal"
url = "https://nexus.internal.example/repository/pypi-proxy/simple"
default = true
UVEOF
```

### 2.3 로컬 인프라 (PostgreSQL / Redis / Qdrant)

레포에 포함된 `docker-compose.dev.yml` 사용:

```yaml
# docker-compose.dev.yml (요약)
services:
  postgres:
    image: harbor.internal/library/postgres:16   # 개발망: postgres:16
    environment:
      POSTGRES_USER: rag
      POSTGRES_PASSWORD: rag-dev-only
      POSTGRES_DB: rag
    ports: ["5432:5432"]
    volumes: ["pgdata:/var/lib/postgresql/data"]
  redis:
    image: harbor.internal/library/redis:7
    ports: ["6379:6379"]
  qdrant:
    image: harbor.internal/library/qdrant:v1.12
    ports: ["6333:6333", "6334:6334"]
    volumes: ["qdrantdata:/qdrant/storage"]
volumes: { pgdata: {}, qdrantdata: {} }
```

```bash
docker compose -f docker-compose.dev.yml up -d
docker compose -f docker-compose.dev.yml ps   # 3개 서비스 healthy 확인
```

### 2.4 모델 아티팩트 배치

폐쇄망 반입 절차(해시 검증·라이선스 검토 완료)를 거친 모델을 로컬 경로에 배치합니다.

```text
/models/
├── llm/main/                    # Qwen3-32B 계열 (로컬 개발은 소형 모델 또는 Mock 권장)
├── embedding/bge-m3/            # BAAI/bge-m3
└── reranker/bge-reranker-v2-m3/ # BAAI/bge-reranker-v2-m3
```

```bash
# 반입 아티팩트 해시 검증 예시
sha256sum -c /models/embedding/bge-m3/SHA256SUMS
```

> 개발 편의: GPU가 없는 로컬 환경에서는 vLLM 대신 Mock LLM 서버(`make mock-llm`)를 사용합니다. §5.4 참고.

### 2.5 서비스 의존성 설치

```bash
git clone https://git.internal.example/ai/rag-platform.git && cd rag-platform

# 전 서비스 일괄 (Makefile이 apps/*, libs/* 순회)
make install

# 개별 서비스 예시
cd apps/mattermost-bridge && uv sync --frozen   # uv.lock 기반, sdist 빌드 발생 시 실패 처리
```

**검증**: `make verify-wheels` — 설치 로그에 `Building wheel`(sdist 빌드)이 0건인지 확인합니다 (TDD §3.4).

---

## 3. Config / Secret 설정

### 3.1 원칙

- 일반 설정: 환경변수(로컬 `.env`) / K8s ConfigMap. 키 이름은 **TDD §10 + PRD 부록 B가 SSOT**이며 임의 변경 금지.
- Secret: 파일 mount 방식 (`*_FILE`, `*_KEY_FILE` 접미사). K8s에서는 Secret volume, 로컬에서는 `secrets/` 디렉토리(gitignore 대상).
- **금지**: Secret을 Git, ConfigMap, 로그, Admin 응답에 저장/노출 (NFR-SEC-006).

### 3.2 로컬 `.env` 생성

```bash
cp .env.example .env
```

`.env.example` 핵심 항목:

```bash
# Common
APP_ENV=local
LOG_LEVEL=DEBUG
TZ=Asia/Seoul

# Offline (로컬 개발도 동일 유지 — 외부 다운로드 경로 조기 검출 목적)
HF_HUB_OFFLINE=1
TRANSFORMERS_OFFLINE=1
HF_HOME=/models/huggingface

# Infra
REDIS_URL=redis://localhost:6379/0
POSTGRES_HOST=localhost
POSTGRES_USER=rag
POSTGRES_PASSWORD=rag-dev-only
POSTGRES_DB=rag
QDRANT_URL=http://localhost:6333

# 내부 서비스 URL (로컬)
EMBEDDING_API_URL=http://localhost:8004
RERANKER_API_URL=http://localhost:8005
VLLM_API_URL=http://localhost:8010/v1        # mock-llm 포트
BRIDGE_INTERNAL_URL=http://localhost:8001

# Mattermost Bridge
MATTERMOST_BASE_URL=https://mattermost.internal.example
MATTERMOST_OUTGOING_TOKEN_SECRET_FILE=./secrets/mattermost/outgoing-token
BRIDGE_ALLOWED_SOURCE_CIDRS=127.0.0.1/32,10.0.0.0/8
BRIDGE_BOT_USERNAME=RAG Assistant
MATTERMOST_DEFAULT_TRIGGER_WORD=!rag

# Feedback (v1.1)
FEEDBACK_ENABLED=true
FEEDBACK_SIGNING_KEY_FILE=./secrets/rag/feedback-signing-key

# Retrieval / Model
VECTOR_TOP_K=30
RERANK_TOP_N=8
CHUNK_SIZE=800
CHUNK_OVERLAP=120
MAX_CONTEXT_TOKENS=8192
MAX_OUTPUT_TOKENS=1024
SIMILARITY_THRESHOLD=0.0
LLM_MODEL_PATH=/models/llm/main
EMBEDDING_MODEL_PATH=/models/embedding/bge-m3
RERANKER_MODEL_PATH=/models/reranker/bge-reranker-v2-m3
TOKENIZER_PATH=/models/llm/main
```

### 3.3 로컬 Secret 파일 생성

```bash
mkdir -p secrets/mattermost secrets/rag

# Outgoing Webhook Token (Mattermost 관리콘솔에서 발급받은 값)
echo -n "<outgoing-webhook-token>" > secrets/mattermost/outgoing-token

# 피드백 버튼 HMAC 서명키 (신규 생성)
python3 -c "import secrets; print(secrets.token_hex(32), end='')" > secrets/rag/feedback-signing-key

# Channel별 Incoming Webhook URL — secret_ref 이름과 파일명 일치 필수
echo -n "https://mattermost.internal.example/hooks/xxxxxxxx" \
  > secrets/mattermost/mattermost-incoming-rag-cloud-ops

chmod 600 secrets/mattermost/* secrets/rag/*
```

### 3.4 Kubernetes Secret (PoC/운영)

```bash
# Outgoing Token + 피드백 서명키
kubectl -n rag-app create secret generic rag-bridge-secrets \
  --from-literal=outgoing-token='<token>' \
  --from-literal=feedback-signing-key="$(python3 -c 'import secrets;print(secrets.token_hex(32),end="")')"

# Channel별 Incoming Webhook URL (이름 = Binding의 secret_ref)
kubectl -n rag-app create secret generic mattermost-incoming-rag-cloud-ops \
  --from-literal=url='https://mattermost.internal.example/hooks/xxxxxxxx'
```

- Helm values에는 `existingSecret: rag-bridge-secrets` 형태로 이름만 기입합니다.
- Secret 교체(Rotation): Admin Web `Channels > Secret 교체` 또는 `POST /api/v1/mattermost/channels/{id}/secret` → K8s Secret 갱신 + `secret_updated_at` 기록. **값 재조회 API는 존재하지 않습니다** (FR-OPS-010).

---

## 4. DB 초기화 및 샘플 데이터

### 4.1 Migration

```bash
cd apps/admin-api
uv run alembic upgrade head     # rev.1: TDD §5 전체 DDL, rev.2: feedback_enabled 컬럼
```

### 4.2 샘플 데이터 주입

`scripts/seed_dev.sql`을 제공하며 `make seed`로 실행합니다. 테이블별 대표 샘플:

```sql
-- 관리자 / 역할
INSERT INTO roles (id, name) VALUES
  ('a0000000-0000-0000-0000-000000000001', 'SYS_ADMIN'),
  ('a0000000-0000-0000-0000-000000000002', 'DOC_ADMIN'),
  ('a0000000-0000-0000-0000-000000000003', 'QUALITY_EVALUATOR'),
  ('a0000000-0000-0000-0000-000000000004', 'AUDITOR');

INSERT INTO admin_users (id, login_id, display_name, department, status) VALUES
  ('b0000000-0000-0000-0000-000000000001', 'cklee', '이철규', 'Cloud운영팀', 'ACTIVE'),
  ('b0000000-0000-0000-0000-000000000002', 'docadmin', '문서관리자', '기술기획팀', 'ACTIVE');

INSERT INTO user_roles VALUES
  ('b0000000-0000-0000-0000-000000000001', 'a0000000-0000-0000-0000-000000000001'),
  ('b0000000-0000-0000-0000-000000000002', 'a0000000-0000-0000-0000-000000000002');

-- Mattermost Channel / 지식 범위 / Binding
INSERT INTO mattermost_channels (id, team_id, team_domain, channel_id, channel_name, display_name) VALUES
  ('c0000000-0000-0000-0000-000000000001', 'team-001', 'cloud-team', 'channel-001', 'rag-cloud-ops', 'Cloud 운영 Q&A'),
  ('c0000000-0000-0000-0000-000000000002', 'team-001', 'cloud-team', 'channel-002', 'rag-hr', '인사 규정 Q&A');

INSERT INTO knowledge_scopes (id, name, filter_json, conversation_mode) VALUES
  ('d0000000-0000-0000-0000-000000000001', 'Cloud 운영 문서',
   '{"categories": ["운영매뉴얼", "장애대응"], "departments": ["Cloud운영팀"], "security_levels": ["INTERNAL"]}', 'CHANNEL'),
  ('d0000000-0000-0000-0000-000000000002', '인사 규정',
   '{"categories": ["인사규정"], "security_levels": ["INTERNAL"]}', 'CHANNEL');

INSERT INTO mattermost_channel_bindings
  (id, channel_ref, mode, trigger_word, enabled, knowledge_scope_id, history_turns,
   mention_user, ack_message_enabled, feedback_enabled, secret_ref) VALUES
  ('e0000000-0000-0000-0000-000000000001', 'c0000000-0000-0000-0000-000000000001',
   'DEDICATED_CHANNEL', NULL, true, 'd0000000-0000-0000-0000-000000000001', 8,
   true, true, true, 'mattermost-incoming-rag-cloud-ops'),
  ('e0000000-0000-0000-0000-000000000002', 'c0000000-0000-0000-0000-000000000002',
   'TRIGGER_WORD', '!rag', true, 'd0000000-0000-0000-0000-000000000002', 8,
   true, true, true, 'mattermost-incoming-rag-hr');

-- 문서 / 버전 / Channel ACL
INSERT INTO documents (id, title, category, department, security_level, status, created_by) VALUES
  ('f0000000-0000-0000-0000-000000000001', '장애대응매뉴얼', '장애대응', 'Cloud운영팀', 'INTERNAL', 'ACTIVE',
   'b0000000-0000-0000-0000-000000000002');

INSERT INTO document_versions (id, document_id, version, hash, file_path, file_size, status) VALUES
  ('f1000000-0000-0000-0000-000000000001', 'f0000000-0000-0000-0000-000000000001', 1,
   'sha256:1f2e3d...', '/data/documents/f0000000.../1/장애대응매뉴얼.pdf', 2457600, 'ACTIVE');

UPDATE documents SET active_version_id = 'f1000000-0000-0000-0000-000000000001'
 WHERE id = 'f0000000-0000-0000-0000-000000000001';

INSERT INTO document_channel_acl VALUES
  ('f0000000-0000-0000-0000-000000000001', 'channel-001', 'ALLOW');

-- 색인 Job (완료 상태 예시)
INSERT INTO index_jobs (id, document_version_id, status, progress, stage, chunk_count, vector_count,
                        started_at, completed_at) VALUES
  ('01000000-0000-0000-0000-000000000001', 'f1000000-0000-0000-0000-000000000001',
   'COMPLETED', 100, 'VALIDATING', 128, 128, now() - interval '1 hour', now() - interval '50 min');

-- Webhook Event / Chat Job / 대화 / 메시지
INSERT INTO mattermost_events (id, post_id, root_id, team_id, channel_id, user_id, payload_hash, status) VALUES
  ('02000000-0000-0000-0000-000000000001', 'post-001', NULL, 'team-001', 'channel-001',
   'mmuser-001', 'sha256:ab12...', 'ACCEPTED');

INSERT INTO channel_conversations (id, scope_key, team_id, channel_id, mode) VALUES
  ('03000000-0000-0000-0000-000000000001', 'team-001:channel-001', 'team-001', 'channel-001', 'CHANNEL');

INSERT INTO chat_jobs (id, event_id, conversation_id, status, queued_at, started_at, completed_at) VALUES
  ('04000000-0000-0000-0000-000000000001', '02000000-0000-0000-0000-000000000001',
   '03000000-0000-0000-0000-000000000001', 'COMPLETED', now() - interval '10 min',
   now() - interval '10 min', now() - interval '9 min');

INSERT INTO messages (id, conversation_id, mattermost_post_id, role, content, latency_ms) VALUES
  ('05000000-0000-0000-0000-000000000001', '03000000-0000-0000-0000-000000000001', 'post-001',
   'user', '장애 등급별 대응 절차를 알려주세요.', NULL),
  ('05000000-0000-0000-0000-000000000002', '03000000-0000-0000-0000-000000000001', NULL,
   'assistant', '장애 등급은 심각도에 따라 1~4등급으로 구분되며... [1]', 8420);

INSERT INTO citations (message_id, chunk_id, document_id, score, rank) VALUES
  ('05000000-0000-0000-0000-000000000002', 'f1000000...-00012',
   'f0000000-0000-0000-0000-000000000001', 0.91, 1);

-- 피드백 (v1.1)
INSERT INTO message_feedback (message_id, mattermost_user_id, value, channel_id) VALUES
  ('05000000-0000-0000-0000-000000000002', 'mmuser-001', 'UP', 'channel-001');

-- 전송 이력 / 설정 / 감사 로그
INSERT INTO mattermost_deliveries (chat_job_id, channel_id, attempt, status, http_status) VALUES
  ('04000000-0000-0000-0000-000000000001', 'channel-001', 1, 'SENT', 200);

INSERT INTO settings (key, value, updated_by) VALUES
  ('retrieval.vector_top_k', '30', 'b0000000-0000-0000-0000-000000000001'),
  ('retrieval.similarity_threshold', '0.0', 'b0000000-0000-0000-0000-000000000001');

INSERT INTO audit_logs (actor, action, target, result, detail) VALUES
  ('cklee', 'CHANNEL_BINDING_ENABLE', 'channel-001', 'SUCCESS', '{"binding_id": "e0000000-..."}');
```

### 4.3 Qdrant 초기화 + 샘플 벡터

```bash
make qdrant-init    # rag_chunks_v1 collection + payload index 7종 생성 (TDD §6.2)
make seed-vectors   # 샘플 문서 chunk 5개를 실제 embedding-api로 색인 (allowed_channel_ids=[channel-001])
```

---

## 5. 로컬 실행

### 5.1 전체 기동 (권장)

```bash
docker compose -f docker-compose.dev.yml up -d   # 인프라
make seed && make qdrant-init                    # 최초 1회
make dev                                         # 전 서비스 + mock-llm 병렬 기동 (honcho/Procfile)
```

### 5.2 서비스 개별 기동

```bash
# Embedding / Reranker (모델 로딩 1~2분 소요, /health/startup 200 확인 후 진행)
cd apps/embedding-api && uv run uvicorn embedding.main:app --port 8004
cd apps/reranker-api  && uv run uvicorn reranker.main:app  --port 8005

# Bridge / RAG API / Admin API
cd apps/mattermost-bridge && uv run uvicorn bridge.main:app --port 8001 --reload
cd apps/rag-api           && uv run uvicorn rag.main:app    --port 8002 --reload
cd apps/admin-api         && uv run uvicorn admin.main:app  --port 8003 --reload

# RAG Worker (RQ)
cd apps/rag-api && uv run rq worker rag-chat --url redis://localhost:6379/0

# Admin Web
cd apps/admin-web && npm ci && npm run dev      # http://localhost:5173
```

### 5.3 문서 색인 (parser-indexer CLI)

```bash
# Admin Web 업로드 대신 CLI로 직접 실행 가능
cd apps/parser-indexer
uv run python -m ingestion.main --index-job-id 01000000-0000-0000-0000-000000000001
```

### 5.4 Mock LLM (GPU 없는 로컬)

```bash
make mock-llm   # :8010 에서 OpenAI-compatible /v1/chat/completions 제공 (고정/에코 응답)
```

실 GPU 환경(vLLM)은 §7.3 배포 후 `VLLM_API_URL`만 교체하면 됩니다.

### 5.5 로컬 E2E 흐름 확인 (Mattermost 없이)

```bash
# 1) Outgoing Webhook 모사 — 질문 발송
curl -s -X POST http://localhost:8001/integrations/mattermost/v1/outgoing \
  -H 'Content-Type: application/json' \
  -d '{
    "token": "'$(cat secrets/mattermost/outgoing-token)'",
    "team_id": "team-001", "team_domain": "cloud-team",
    "channel_id": "channel-001", "channel_name": "rag-cloud-ops",
    "user_id": "mmuser-001", "user_name": "honggildong",
    "post_id": "post-'$(date +%s)'", "root_id": "",
    "text": "장애 등급별 대응 절차를 알려주세요."
  }'
# → {"text": "질문을 접수했습니다..."} (p95 2초 이내)

# 2) Worker 로그에서 파이프라인 단계별 latency 확인, Incoming Webhook 게시는
#    로컬에서 make mock-mattermost (수신 payload를 콘솔에 출력) 로 확인

# 3) 피드백 버튼 클릭 모사
SIG=$(uv run python scripts/sign_feedback.py --message-id <message_id> --value UP)
curl -s -X POST http://localhost:8001/integrations/mattermost/v1/actions \
  -H 'Content-Type: application/json' \
  -d '{"user_id":"mmuser-001","post_id":"p1","channel_id":"channel-001",
       "context":{"action":"feedback","message_id":"<message_id>",
                  "chat_job_id":"<job_id>","value":"UP","sig":"'$SIG'"}}'
# → {"ephemeral_text": "피드백이 반영되었습니다. 감사합니다 🙏"}
```

---

## 6. 테스트

### 6.1 계층별 실행

```bash
make lint            # ruff + mypy (py312 타깃)
make test            # 전체 unit test (coverage: 전체 ≥80%, rag/domain ≥90%)
make test-contract   # tests/mattermost — 실제 payload fixture(JSON/form) 계약 테스트
make test-integration
make test-isolation  # ★ CH-001~010 Channel 격리 — 배포 차단 Gate
make test-e2e        # Mattermost Sandbox Channel 필요 (PoC 환경)
```

### 6.2 통합 테스트 (testcontainers)

`tests/integration`은 **testcontainers**로 postgres/redis/qdrant를 자동 기동합니다. Docker daemon만 있으면 별도 준비가 필요 없습니다.

```bash
uv run pytest tests/integration -v
# 주요 시나리오:
#  - Outgoing 수신 → Redis Job → Worker → (mock LLM) → 게시 payload(attachment 포함) 검증
#  - 문서 색인 → Qdrant 검증 → 재실행 멱등성
#  - 문서 삭제 → is_active=false → 검색 제외
#  - 피드백 UPSERT / 서명 위조 401
```

폐쇄망에서 testcontainers 이미지 pull이 안 되는 경우:

```bash
export TESTCONTAINERS_HUB_IMAGE_NAME_PREFIX=harbor.internal/library/
```

### 6.3 Channel 격리 테스트 (필수 Gate)

```bash
make test-isolation
# CH-002/003: Channel A 대화 후 B 질문 시 LLM payload에 A 문자열 부재 assert
# CH-001: A 전용 문서가 B 검색에서 0건 assert
# 실패 시 CI가 배포 파이프라인을 차단합니다.
```

테스트 이름 규약: PRD 요구사항 ID 포함 — `test_fr_mm_006_...`, `test_ch_002_...`, `test_fb_...`

---

## 7. 빌드 및 배포

### 7.1 이미지 빌드

```bash
# 개별
docker build -f apps/mattermost-bridge/Containerfile \
  -t harbor.internal/rag/mattermost-bridge:$(git rev-parse --short HEAD) .

# 전체 (Makefile)
make build-images TAG=$(git rev-parse --short HEAD)
```

- Base image: 승인된 `harbor.internal/library/python:3.12-slim@sha256:...` (digest 고정, `latest` 금지)
- 빌드 시 내부 PyPI만 참조: `--build-arg PIP_INDEX_URL=https://nexus.internal.example/...`

### 7.2 CI/CD 파이프라인 (PRD §26.2)

```text
Lint/Format → Unit Test → Contract Test → admin-web Build/Test → SAST
→ Dependency/License Scan → Image Build → SBOM 생성(syft) → Image Scan(trivy)
→ Harbor Push → Dev 배포 → Integration Test → test-isolation(Gate)
→ Sandbox Channel E2E → 승인 → PoC Namespace 배포
```

### 7.3 Kubernetes 배포 (Helm)

```bash
# 사전: §3.4의 K8s Secret 생성 완료 상태

helm dependency update deploy/helm/rag-platform

helm upgrade --install rag-platform deploy/helm/rag-platform \
  -f deploy/helm/rag-platform/values-poc.yaml \
  --set global.imageTag=<git-sha> \
  --namespace rag-app --create-namespace

# 배포 확인
kubectl get pods -n rag-app -n rag-ai -n rag-data -n rag-ingestion
kubectl -n rag-ai rollout status deploy/vllm-llm-0   # startupProbe 최대 10분
```

- Namespace 배치: `rag-app`(bridge/admin/rag), `rag-ai`(vllm/embedding/reranker), `rag-data`(qdrant/pg/redis), `rag-ingestion`(parser-indexer Job)
- vLLM Rolling: `maxSurge=0, maxUnavailable=1` (GPU 2장 한도 내 순차 교체)
- GitOps(선택): `deploy/argocd/` Application 등록 시 Harbor digest 갱신으로 자동 sync

### 7.4 배포 후 스모크 체크리스트

```bash
for svc in bridge rag-api admin-api embedding reranker; do
  kubectl -n rag-app exec deploy/debug -- curl -sf http://$svc:8000/health/ready && echo "$svc OK"
done
# Admin Web → Channels → 연결 테스트 (Incoming Webhook 테스트 메시지 게시)
# 테스트 Channel에서 질문 1건 → 답변 + 👍/👎 버튼 표시 확인
```

---

## 8. RAG 성능 평가

### 8.1 평가 데이터셋

`tests/evaluation/dataset/*.yaml` — 최소 100문항, 유형 비율은 PRD §25.6 (단일문서 30% / 종합 20% / 표 15% / 정의 10% / 무근거 15% / 모호 10%).

```yaml
# tests/evaluation/dataset/q001.yaml
id: q001
type: single_doc
question: "장애 등급별 대응 절차를 알려주세요."
channel_id: channel-001
ground_truth:
  answer_gist: "1~4등급 구분, 등급별 보고/복구 절차"
  documents: ["장애대응매뉴얼.pdf"]
  pages: [12]
  answerable: true
```

### 8.2 평가 실행

```bash
# 전체 평가 (실 embedding/qdrant/reranker + vLLM 또는 mock)
make evaluate                        # = uv run python -m evaluation.runner --dataset tests/evaluation/dataset

# 특정 유형만 / 리포트 경로 지정
uv run python -m evaluation.runner --type no_answer --out reports/eval_$(date +%Y%m%d).md
```

Runner 산출 지표와 PoC 목표(PRD §8.1):

| 지표 | 목표 | 측정 방식 |
|---|---|---|
| 검색 Recall@10 | ≥ 85% | 정답 chunk가 Top10 포함 비율 |
| Citation Precision | ≥ 90% | 표시 출처가 실제 근거 포함 비율 |
| Faithfulness | ≥ 85% | LLM-judge(내부 vLLM 사용) 채점 |
| 무근거 안전응답률 | ≥ 90% | `no_answer` 유형에서 추측 없이 부족 안내 비율 |
| Channel 격리 정확도 | 100% | 비허용 문서/타 Channel 대화 미포함 |

### 8.3 파라미터 튜닝 루프

1. `make evaluate` → `reports/eval_*.md` 기준선 확보
2. Admin Web `Settings`에서 `VECTOR_TOP_K`, `RERANK_TOP_N`, `SIMILARITY_THRESHOLD`, `CHUNK_SIZE` 등 변경 (settings 테이블, 60초 내 반영)
3. 재평가 → 리포트 diff 비교 (`scripts/eval_diff.py before.md after.md`)
4. Threshold 확정: `no_answer` 유형의 오탐/미탐 균형점에서 `SIMILARITY_THRESHOLD` 설정 (TDD §7.2.3)

### 8.4 운영 피드백 기반 평가 (v1.1)

- Admin Web `Feedback` 대시보드: 만족률(UP/(UP+DOWN)), Channel별 추이, 👎 답변 목록
- 👎 답변은 **평가셋 승격 버튼**으로 `tests/evaluation/dataset/` 후보 YAML 초안 생성 → 품질 평가자가 ground truth 보완 후 커밋
- Grafana: `feedback_satisfaction_ratio`, `rag_insufficient_evidence_total` 패널로 품질 저하 조기 감지

### 8.5 성능(부하) 테스트

```bash
make perf-webhook-burst   # 50명, 10초 내 질문 — ACK p95 ≤ 2s 검증
make perf-peak            # 동시 10 생성 — 답변 게시 p95 ≤ 30s
make perf-soak            # 5~10 동시, 2시간 — 메모리 누수 확인
```

---

## 9. 트러블슈팅

| 증상 | 원인/조치 |
|---|---|
| `uv sync` 중 `Building wheel...` 후 실패 | cp312 휠 부재 패키지가 sdist 빌드 시도 (3.12는 distutils 제거). 내부 PyPI에 cp312 휠 반입 요청. `make verify-wheels`로 대상 식별 |
| embedding/reranker 기동 시 Hub 접속 오류 | 모델 경로 미배치 또는 Hub ID 로딩 코드 혼입. `HF_HUB_OFFLINE=1` 유지 상태에서 `*_MODEL_PATH` 확인 |
| Outgoing 요청이 401 | `secrets/mattermost/outgoing-token` 값과 Mattermost 발급 token 불일치 |
| 답변이 다른 Channel에 게시 | 발생 시 Critical. Binding의 `secret_ref` ↔ 실제 Incoming URL 대상 Channel 재확인, `make test-isolation` 실행 |
| 피드백 클릭이 401 | Bridge 재기동으로 서명키 변경됨 — 이전 게시 버튼의 sig 불일치(정상 동작). 키는 Secret으로 고정 운용 |
| 질문이 무응답 | 비활성 Binding(무응답 정책) 또는 Trigger Word 미일치. `mattermost_events.status=IGNORED_*` 확인 |
| vLLM Pod CrashLoop | startupProbe 시간 부족 또는 VRAM 초과. `--max-model-len`/quantization 확인 |

---

## 라이선스 / 반입 고지

본 저장소가 사용하는 오픈소스(vLLM, Qdrant, FastAPI, FlagEmbedding, PyMuPDF 등)와 모델(Qwen/EXAONE/BGE 계열)은 폐쇄망 반입 시 라이선스 검토·해시 검증·SBOM 등록을 완료해야 합니다 (PRD §21, NFR-SEC-012). 반입 절차는 `docs/supply-chain.md` 참조.
