# RAG Platform — Web Chat 기반 폐쇄형 Private Cloud RAG LLM 챗봇

사내 사용자가 **RAG Web Chat**(`apps/chat-web`, aiops_chatbot UI 이식)의 채널에 질문하면, `chat-gateway` 가 이를 받아
Channel별로 격리된 지식 범위 내에서 RAG 파이프라인(Embedding → Qdrant 검색 → Re-rank → vLLM 생성)을 실행하고,
답변을 **토큰 단위로 스트리밍**(socket.io)하여 근거 문서 표와 👍/👎 피드백 버튼과 함께 보여주는 시스템입니다.

> **v2.0 (2026-09-28)** — 사용자 UI 를 Mattermost 에서 Web Chat 으로 전환했습니다. Mattermost 연동(bridge/adapter/Webhook)은 완전히 제거되었습니다.
> 이식 기록: `apps/chat-web/PORTING.md` (원본 `../aiops_chatbot` 은 수정하지 않음).

> - 요구사항: `docs/PRD.md` (PRD-RAG-CHATBOT-POC-001 v2.0)
> - 기술 설계: `docs/TDD.md` (TDD-RAG-CHATBOT-POC-001 v2.0) — **구현의 SSOT**
> - Claude Code 컨텍스트: `CLAUDE.md`
> - 보안 체크리스트: `docs/security-checklist.md`

## 0. 구현 현황

TDD §15 로드맵 **M1–M12 구현 완료** (M12 = Web Chat 전환). 로컬은 GPU/모델 미배치 전제로 **mock 엔진 + mock LLM** 기준.

| 지표 | 결과 |
|---|---|
| Python 테스트 | **183 passed** (`make test` = testpaths `libs`·`apps`·`tests`, Docker 가용 시 실 Qdrant 격리 테스트 포함 · Docker 없으면 182 passed, 1 skipped) · `tools/*` 7건은 `uv run pytest tools` 로 별도 실행 |
| Lint | `ruff check .` / `ruff format --check .` clean |
| Helm | `helm lint` clean (values / values-poc / values-lab) |
| admin-web | `npm run build` (tsc + vite) OK |
| chat-web | `npm run typecheck` + `next build` (standalone) OK |

| 구성요소 | 위치 | 테스트 |
|---|---|---|
| 공유 스키마/유틸 (M1) | `libs/schemas·common·observability·chat-adapter` | 37 |
| chat-gateway (M2 → v2.0) | `apps/chat-gateway` (REST + socket.io) | 44 |
| admin-api + Alembic (M3) | `apps/admin-api` | 33 |
| embedding/reranker (M4) | `apps/embedding-api`·`apps/reranker-api` | 21 |
| parser-indexer (M5) | `apps/parser-indexer` | 16 |
| rag domain/worker/streaming/feedback (M6) | `apps/rag-api` | 18 |
| p95 측정 (M7) | `scripts/measure_latency.py` | — |
| admin-web (M8) | `apps/admin-web` (React + Vite) | build |
| Channel 격리 Gate (M9) | `tests/channel-isolation` (CH-001~010) | 12 |
| Helm/NetworkPolicy/Ingress/모니터링 (M10) | `deploy/helm/rag-platform` | helm lint |
| 평가 runner + perf (M11) | `tools/evaluation`·`tools/mock-llm`, `tests/performance`, `tests/contract` | 9 (tools 7 + contract 2) |
| **Web Chat UI (M12)** | `apps/chat-web` (Next.js 15, aiops_chatbot 이식) | typecheck/build |

**로컬 실행 캐비엇**: 이 저장소는 Intel macOS(GPU 없음)에서 개발되어 실 모델 의존성(`torch`/`FlagEmbedding`)은
optional `models` extra로 분리했다. 기본 경로는 `EMBEDDING_MOCK=1`/`RERANKER_MOCK=1` + `make mock-llm`.
GPU 노드에서는 `uv sync --extra models` 로 실 엔진을 활성화한다. testcontainers 통합/격리 테스트는 Docker 필요.

**알려진 후속(admin-web가 graceful degrade 처리)**: admin-api에 아직 없는 조회/액션 엔드포인트 —
`GET /index-jobs`·`/index-jobs/{id}/retry`, `GET /audit-logs`(감사 로그는 기록만 하고 조회 API 미제공),
`POST /evaluation/candidates`(👎→평가셋 승격). 프론트는 빈 상태로 안전하게 동작한다.

> **명령 안내**: 아래 §2~§9의 일부 `make` 타깃/스크립트는 운영 절차를 설명하는 예시로, 현재 저장소에
> 실제 구현된 것은 다음이다 — `make install lint fmt test test-cov test-isolation test-integration
> evaluate perf-chat-burst mock-llm build-images push-images helm-lint helm-template qdrant-init seed
> seed-users openapi chat-gateway chat-web-dev chat-web-build infra-up infra-down clean`, 스크립트는
> `scripts/export_openapi.py`·`measure_latency.py`·`seed_dev.sql`·`create_chat_user.py`, 이미지 빌드는
> `apps/*/Containerfile`(8종), 업로드용 샘플 문서는 `samples/`. 그 외(`make dev`, `verify-wheels`, `test-e2e`,
> `seed-vectors`, `perf-peak/soak` 등)는 배포 파이프라인 확장 시 추가 예정인 계획 항목이다.

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
사용자(브라우저) ──HTTPS──> Ingress (chat host, 동일 출처)
                            ├─ /        ──> chat-web (Next.js standalone, aiops_chatbot UI 이식)
                            ├─ /api/v1  ──> chat-gateway  REST (로그인·채널·질문·피드백)
                            └─ /ws      ──> chat-gateway  socket.io (post.* / llm.stream.delta|end)
                                               │  질문 Post + placeholder Bot Post + chat_jobs
                                               ▼
                                         Redis Queue(RQ) ──> rag-worker
                                               ▲               ├─> embedding-api (BGE-M3, CPU)
       socket.io Redis manager (delta emit) ───┘               ├─> qdrant (build_filter: Channel/ACL)
                                                               ├─> reranker-api (BGE-reranker, CPU)
                                                               ├─> vLLM ×2 (stream=True)
                                                               └─> PostgreSQL (Bot Post 갱신/대화/피드백)

관리자 ──> admin-web ──> admin-api ──> PostgreSQL / K8s Job(parser-indexer)
                         (채널·Binding·멤버·채팅 사용자·문서 ACL)
```

| 서비스 | 역할 | 포트(로컬) |
|---|---|---|
| `chat-web` | 사용자 Web Chat UI (Next.js 15, aiops_chatbot 이식) | 3000 |
| `chat-gateway` | 로그인(prehash/JWT)·채널 멤버십·질문 수신/Job 등록·실시간(socket.io `/ws`)·피드백 | 8001 |
| `rag-api` / `rag-worker` | RAG 파이프라인 오케스트레이션 · 답변 스트리밍/Bot Post 갱신 | 8002 / - |
| `admin-api` | 문서(ACL)/채널·Binding·멤버/채팅 사용자/설정/피드백 관리 | 8003 |
| `admin-web` | 관리자 Portal (React + Vite) | 5173 |
| `embedding-api` | BGE-M3 임베딩 | 8004 |
| `reranker-api` | BGE-reranker-v2-m3 재정렬 | 8005 |
| `parser-indexer` | 문서 파싱/색인 배치 (CLI) | - |

**핵심 불변 규칙** (자세한 내용은 `CLAUDE.md`):
- Python **3.12 고정**, 의존성은 cp312 바이너리 휠만 (sdist 빌드 금지)
- 런타임 외부 네트워크 호출 금지 — 모델은 로컬 경로 로딩만
- Qdrant 검색은 `build_filter()` 없이 호출 금지 (Channel 격리 100%)
- Secret(JWT 키/pepper/피드백 서명키/토큰)은 로그·응답·repr에 절대 노출 금지
- Channel 격리: 채널 멤버십(REST 404 · WS room) + `build_filter()` + scope_key

---

## 2. 사전 준비 및 오픈소스 S/W 설치

### 2.1 요구 버전

| 구분 | 버전 | 비고 |
|---|---|---|
| Python | 3.12.x | `requires-python = ">=3.12,<3.13"` |
| uv | 최신 | Python 패키지/venv 관리 |
| Node.js | 22 LTS | admin-web (Vite) · chat-web (Next.js 15) |
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
uv sync --all-packages --frozen   # uv.lock 기반, sdist 빌드 발생 시 실패 처리

# 프론트엔드 (uv workspace 제외 — npm)
cd apps/admin-web && npm ci && cd -
cd apps/chat-web  && npm ci && cd -
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

# Web Chat — chat-gateway
CHAT_WORKSPACE_SLUG=rag                       # prehash salt — chat-web NEXT_PUBLIC_WORKSPACE_SLUG 와 동일
CHAT_DEFAULT_TRIGGER_WORD=!rag
CHAT_CORS_ORIGINS=http://localhost:3000       # dev 교차 출처 WS. 운영(Ingress 동일 출처)은 비움
JWT_SECRET_FILE=./secrets/rag/jwt-secret
PASSWORD_PEPPER_FILE=./secrets/rag/password-pepper   # chat-gateway · admin-api 공유
COOKIE_SECURE=false                           # 로컬 HTTP 전용. 운영 true

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
mkdir -p secrets/rag
for k in jwt-secret password-pepper feedback-signing-key; do
  python3 -c "import secrets; print(secrets.token_hex(32), end='')" > secrets/rag/$k
done
chmod 600 secrets/rag/*
```

| 파일 | 사용처 | 용도 |
|---|---|---|
| `jwt-secret` | chat-gateway | access token(HS256) 서명 |
| `password-pepper` | chat-gateway · admin-api | 비밀번호 해시 pepper (**교체 시 전 사용자 비밀번호 재설정 필요**) |
| `feedback-signing-key` | chat-gateway · rag-worker | 피드백 토큰 HMAC(`message_id:bot_post_id`) |

### 3.4 Kubernetes Secret (PoC/운영)

```bash
kubectl -n rag-app create secret generic rag-chat-secrets \
  --from-file=jwt-secret=secrets/rag/jwt-secret \
  --from-file=password-pepper=secrets/rag/password-pepper \
  --from-file=feedback-signing-key=secrets/rag/feedback-signing-key
```

```bash
# PostgreSQL 비밀번호 (key=password) — DB 를 쓰는 네임스페이스마다 동일 값으로 생성
for ns in rag-app rag-data rag-ingestion; do
  kubectl -n $ns create secret generic rag-postgresql-secret --from-literal=password='<pg-password>'
done
```

- Helm 은 `appServices.<svc>.secretMount.keys` 에 나열한 키만 `/var/run/secrets/rag` 에 파일로 투영(defaultMode `0440`)하고
  `*_FILE` env(`JWT_SECRET_FILE`/`PASSWORD_PEPPER_FILE`/`FEEDBACK_SIGNING_KEY_FILE`)를 자동 주입합니다 —
  chat-gateway=3키, rag-worker=`feedback-signing-key`, admin-api=`password-pepper`.
  values 에는 Secret **이름**(`global.chatSecretName: rag-chat-secrets`, `global.postgres.existingSecret: rag-postgresql-secret`)만 기입합니다.
- Secret 파일이 없거나 비면 **fail-closed**: chat-gateway 는 기동 시 `startup.*_missing` error 로그, 로그인/refresh 는 503 `AUTH_NOT_CONFIGURED`,
  피드백은 401. rag-worker 는 서명 키가 없으면 피드백 토큰을 붙이지 않습니다.
- JWT 키 교체: 모든 access token 무효화(최대 15분 후 refresh 로 재발급). 피드백 키 교체: 이전 답변의 피드백 버튼이 401(정상).

---

## 4. DB 초기화 및 샘플 데이터

### 4.1 Migration

```bash
cd apps/admin-api
uv run alembic -c src/admin/db/migrations/alembic.ini upgrade head
# rev.1: TDD §5 DDL · rev.2: feedback_enabled · rev.3(0003_webchat): Mattermost 제거 → chat_* 테이블
# ⚠ v1.x DB 를 rev.3 으로 올린 경우 Channel id 가 UUID 로 재매핑되므로 전 문서 재색인이 필요합니다.
```

K8s 에서는 `migration.enabled=true` 시 Helm hook Job `rag-db-migrate` 가 install/upgrade 마다 같은 명령을 실행합니다 (§7.3).

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

-- Web Chat 채널 / 지식 범위 / Binding  (chat_channels.id = Qdrant allowed_channel_ids)
INSERT INTO chat_channels (id, name, display_name, type, purpose) VALUES
  ('c0000000-0000-0000-0000-000000000001', 'rag-cloud-ops', 'Cloud 운영 Q&A', 'public', 'Cloud 운영 문서 질의'),
  ('c0000000-0000-0000-0000-000000000002', 'rag-hr', '인사 규정 Q&A', 'public', '"!rag 질문" 형식');

INSERT INTO knowledge_scopes (id, name, filter_json, conversation_mode) VALUES
  ('d0000000-0000-0000-0000-000000000001', 'Cloud 운영 문서',
   '{"categories": ["운영매뉴얼", "장애대응"], "departments": ["Cloud운영팀"], "security_levels": ["INTERNAL"]}', 'THREAD'),
  ('d0000000-0000-0000-0000-000000000002', '인사 규정',
   '{"categories": ["인사규정"], "security_levels": ["INTERNAL"]}', 'CHANNEL');

INSERT INTO channel_bindings
  (id, channel_ref, mode, trigger_word, enabled, knowledge_scope_id, history_turns,
   mention_user, ack_message_enabled, feedback_enabled) VALUES
  ('e0000000-0000-0000-0000-000000000001', 'c0000000-0000-0000-0000-000000000001',
   'DEDICATED_CHANNEL', NULL, true, 'd0000000-0000-0000-0000-000000000001', 8, false, true, true),
  ('e0000000-0000-0000-0000-000000000002', 'c0000000-0000-0000-0000-000000000002',
   'TRIGGER_WORD', '!rag', true, 'd0000000-0000-0000-0000-000000000002', 8, true, true, true);

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
  ('f0000000-0000-0000-0000-000000000001', 'c0000000-0000-0000-0000-000000000001', 'ALLOW');

-- 색인 Job (완료 상태 예시)
INSERT INTO index_jobs (id, document_version_id, status, progress, stage, chunk_count, vector_count,
                        started_at, completed_at) VALUES
  ('01000000-0000-0000-0000-000000000001', 'f1000000-0000-0000-0000-000000000001',
   'COMPLETED', 100, 'VALIDATING', 128, 128, now() - interval '1 hour', now() - interval '50 min');

-- 설정 / 감사 로그
INSERT INTO settings (key, value, updated_by) VALUES
  ('retrieval.vector_top_k', '30', 'b0000000-0000-0000-0000-000000000001'),
  ('retrieval.similarity_threshold', '0.0', 'b0000000-0000-0000-0000-000000000001');

```

채팅 사용자와 채널 멤버십은 비밀번호 해시가 필요하므로 SQL 이 아닌 스크립트로 생성합니다
(대화·Post·피드백 데이터는 실제 사용으로 쌓이므로 seed 하지 않습니다):

```bash
export PASSWORD_PEPPER_FILE=./secrets/rag/password-pepper
make seed-users
# hong@example.com (admin, rag-cloud-ops + rag-hr) / kim@example.com (rag-hr) — 비밀번호 Rag!Assistant2026 (로컬 전용)
# 개별: uv run python scripts/create_chat_user.py --email a@b.co --name 이름 --password '…' --channels rag-hr
```

### 4.3 Qdrant 초기화 + 샘플 벡터

```bash
make qdrant-init    # rag_chunks_v1 collection + payload index 7종 생성 (TDD §6.2)
# 샘플 문서 색인: admin-api 업로드(allowed_channel_ids=채널 UUID) → reindex → parser-indexer CLI (§5.3)
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

# Chat Gateway / RAG API / Admin API
make chat-gateway                                # = uv run --package chat-gateway uvicorn gateway.main:app --port 8001
cd apps/rag-api   && uv run uvicorn rag.main:app   --port 8002 --reload
cd apps/admin-api && uv run uvicorn admin.main:app --port 8003 --reload

# RAG Worker (RQ)
cd apps/rag-api && uv run rq worker rag-chat --url redis://localhost:6379/0

# Web Chat (사용자) — /api 는 chat-gateway 로 dev 프록시, WS 는 gateway 직접
make chat-web-dev                                # http://localhost:3000  (localhost 로 접속: WebCrypto 요건)

# Admin Web
cd apps/admin-web && npm ci && npm run dev      # http://localhost:5173
```

### 5.3 문서 색인 (parser-indexer CLI)

```bash
# 1) 업로드 + Channel ACL (admin-web 문서 관리 화면과 동일)
curl -s -X POST localhost:8003/api/v1/documents -H 'X-Auth-User: cklee' \
  -F file=@manual.pdf -F category=장애대응 -F department=Cloud운영팀 \
  -F allowed_channel_ids=c0000000-0000-0000-0000-000000000001
# 2) 색인 Job 생성 → CLI 실행
curl -s -X POST localhost:8003/api/v1/documents/<document_id>/reindex -H 'X-Auth-User: cklee'
uv run --package parser-indexer python -m ingestion.main --index-job-id <index_job_id>

# (대안) 업로드와 색인 Job 생성을 한 번에 — 응답의 index_job_id 로 바로 CLI 실행
curl -s -X POST localhost:8003/api/v1/documents -H 'X-Auth-User: cklee' \
  -F file=@samples/<파일> -F allowed_channel_ids=c0000000-0000-0000-0000-000000000001 \
  -F start_indexing=true
```

- `allowed_channel_ids` 는 채널 UUID(`chat_channels.id`) — 반복 필드 또는 콤마 구분. 비UUID 는 422 `INVALID_CHANNEL_ID`, 미존재 채널은 404.
- 색인 트리거는 `INDEX_JOB_TRIGGER` 로 선택합니다: `none`(기본 — `index_jobs` 행만 생성, 위 CLI 로 수동 실행) /
  `k8s`(클러스터 내 admin-api 가 ConfigMap `parser-indexer-job-template` 으로 parser-indexer Job 생성). 트리거 실패는
  `index_jobs.error = "TRIGGER_FAILED[...]"` 로 기록되고 요청 자체는 성공합니다.
- 샘플 문서와 업로드 예시는 `samples/README.md` 참고.

### 5.4 Mock LLM (GPU 없는 로컬)

```bash
make mock-llm   # :8010 OpenAI-compatible /v1/chat/completions (stream=true 시 SSE, MOCK_LLM_STREAM_DELAY_MS)
```

실 GPU 환경(vLLM)은 §7.3 배포 후 `VLLM_API_URL`만 교체하면 됩니다.

### 5.5 로컬 E2E 흐름 확인 (브라우저)

1. http://localhost:3000 → `hong@example.com` / `Rag!Assistant2026` 로그인 (prehash 만 전송)
2. `#rag-cloud-ops`(DEDICATED · THREAD 컨텍스트)에서 질문 → 스레드가 열리고 "질문을 접수했습니다…" → **토큰 스트리밍** → 근거 문서 표 + 👍/👎
3. 같은 스레드에 후속 질문 → 이전 대화가 컨텍스트로 사용됨 (scope_key = `{channel_id}:{root_id}`)
4. `#rag-hr`(TRIGGER_WORD): 일반 메시지는 답변 없음, `!rag 연차 규정` 만 답변
5. 👍 클릭 → admin-web 피드백 대시보드 반영 · 위조 토큰은 401
6. `kim@example.com` 으로 로그인 → `#rag-cloud-ops` 미노출, URL 직접 접근 시 "채널을 찾을 수 없거나 접근 권한이 없습니다"

API 만으로 확인하려면 `tests/performance/locustfile.py` 의 로그인/질문 흐름 또는 `docs/openapi/chat-gateway.json` 참고.

---

## 6. 테스트

### 6.1 계층별 실행

```bash
make lint              # ruff + mypy (py312 타깃)
make test              # 전체 테스트 (183 passed; Docker 없으면 182 passed, 1 skipped)
make test-integration  # tests/contract(mock-llm SSE ↔ openai SDK LLMClient.stream 계약) + test_ch_qdrant.py(실 Qdrant)
make test-isolation    # ★ CH-001~010 Channel 격리 — 배포 차단 Gate
make chat-web-build    # chat-web typecheck + next build (standalone)
```

### 6.2 통합 테스트

- `tests/channel-isolation/test_ch_qdrant.py` 는 **testcontainers** 로 실 Qdrant 를 띄워 CH-001 을 검증합니다 (Docker 없으면 skip).
- chat-gateway 테스트는 fakeredis + in-memory store + spy emitter 로 REST/WS/피드백 계약을 검증합니다.
- rag-api worker 테스트는 fake stream LLM 으로 delta 순서·Bot Post 갱신·피드백 토큰·오류 경로를 검증합니다.

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

테스트 이름 규약: PRD 요구사항 ID 포함 — `test_fr_web_006_...`, `test_ch_002_...`, `test_fb_...`

---

## 7. 빌드 및 배포

### 7.1 이미지 빌드

```bash
# 개별 — Python 서비스는 리포 루트 컨텍스트 (apps/{chat-gateway,rag-api,admin-api,embedding-api,reranker-api,parser-indexer}/Containerfile)
docker build -f apps/chat-gateway/Containerfile \
  -t harbor.internal/rag/chat-gateway:$(git rev-parse --short HEAD) .
# chat-web — 컨텍스트 = apps/chat-web (Next standalone, node server.js :3000, uid 10001)
#            NEXT_PUBLIC_* 는 build 시 고정 — 운영은 NEXT_PUBLIC_WS_URL 비움 = same-origin
docker build -f apps/chat-web/Containerfile \
  -t harbor.internal/rag/chat-web:$(git rev-parse --short HEAD) apps/chat-web
# admin-web — 컨텍스트 = apps/admin-web (nginx :8080 비루트)

# 전체 8종 (Makefile) — REG 기본 registry.local:5000, TAG 기본 git short sha
make build-images REG=harbor.internal TAG=$(git rev-parse --short HEAD)
make push-images  REG=harbor.internal TAG=$(git rev-parse --short HEAD)
```

- Base image: 승인된 `harbor.internal/library/python:3.12-slim@sha256:...` (digest 고정, `latest` 금지) — `--build-arg PYTHON_IMAGE=... UV_IMAGE=...` (web 은 `NODE_IMAGE`)
- 빌드 시 내부 PyPI만 참조: `--build-arg UV_INDEX_URL=https://nexus.internal.example/...` (`UV_ONLY_BINARY` 로 sdist 빌드 차단). web 이미지는 `--build-arg NPM_REGISTRY=...`
- embedding-api / reranker-api 는 `UV_EXTRA=models` 가 기본 (실 모델 엔진 포함)

### 7.2 CI/CD 파이프라인 (PRD §26.2)

```text
Lint/Format → Unit Test → Contract Test → admin-web Build/Test → SAST
→ Dependency/License Scan → Image Build → SBOM 생성(syft) → Image Scan(trivy)
→ Harbor Push → Dev 배포 → Integration Test → test-isolation(Gate)
→ Web Chat E2E(스테이징) → 승인 → PoC Namespace 배포
```

### 7.3 Kubernetes 배포 (Helm)

```bash
# 사전: §3.4의 K8s Secret 생성 완료 상태

make helm-lint helm-template   # values / +poc / +poc+lab 렌더 확인 (chart 는 외부 dependency 없음)

helm upgrade --install rag-platform deploy/helm/rag-platform \
  -f deploy/helm/rag-platform/values-poc.yaml \
  --set global.imageTag=<git-sha> \
  --set ingress.enabled=true --set ingress.chatHost=chat.rag.internal \
  --set ingress.tlsSecretName=rag-chat-tls \
  --namespace rag-app --create-namespace

# 배포 확인
kubectl get pods -n rag-app -n rag-ai -n rag-data -n rag-ingestion
kubectl -n rag-ai rollout status deploy/vllm-llm-0   # startupProbe 최대 10분
```

- Namespace 배치: `rag-app`(chat-web/chat-gateway/admin/rag), `rag-ai`(vllm/embedding/reranker), `rag-data`(qdrant/pg/redis), `rag-ingestion`(parser-indexer Job).
  NetworkPolicy 의 cross-NS 허용은 NS 라벨 `rag-platform=true` 에 의존합니다(`namespaces.create=true` 또는 `kubectl label ns ... rag-platform=true`).
- DB 마이그레이션: `migration.enabled=true`(values-poc/lab 기본) 면 post-install/post-upgrade hook Job `rag-db-migrate` 가
  admin-api 이미지로 `alembic upgrade head` 를 실행합니다(admin-api 는 기동 시 마이그레이션하지 않음).
- 색인 트리거: `INDEX_JOB_TRIGGER=k8s` 로 쓰려면 `serviceAccounts.adminApi.create=true` + `networkPolicy.apiServer.{enabled,cidrs}` 필요(values-lab 참고)
- Ingress: chat host 의 `/api/v1`·`/ws` → chat-gateway, `/` → chat-web (동일 출처 필수 — refresh 쿠키 SameSite=Strict, WS Origin 검사). **TLS 필수** (브라우저 WebCrypto prehash)
- chat-gateway 다중 replica: socket.io Redis manager 로 브로드캐스트, 클라이언트는 websocket 전용이라 sticky session 불필요
- vLLM Rolling: `maxSurge=0, maxUnavailable=1` (GPU 2장 한도 내 순차 교체)
- GitOps(선택): `deploy/argocd/` Application 등록 시 Harbor digest 갱신으로 자동 sync

### 7.4 배포 후 스모크 체크리스트

```bash
curl -sf https://chat.rag.internal/health/live            # chat-web
curl -sf https://chat.rag.internal/api/v1/auth/me -o /dev/null -w '%{http_code}\n'   # 401 = gateway 도달
# admin-web → 채팅 사용자 생성(임시 비밀번호) → 채널 관리 › 멤버 추가 → Binding 활성화
# 브라우저 로그인 → 테스트 채널 질문 1건 → 스트리밍 답변 + 근거 문서 표 + 👍/👎 확인
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
CHAT_EMAIL=hong@example.com CHAT_PASSWORD='Rag!Assistant2026' make perf-chat-burst
                          # 50명, 10초 내 질문 — 질문 ACK(POST /api/v1/posts) p95 ≤ 2s 검증
                          # ※ 부하 시험 중 RATE_LIMIT_PER_USER_PER_MIN 을 충분히 올릴 것
make perf-peak            # 동시 10 생성 — 답변 게시 p95 ≤ 30s
make perf-soak            # 5~10 동시, 2시간 — 메모리 누수 확인
```

---

## 9. 트러블슈팅

| 증상 | 원인/조치 |
|---|---|
| `uv sync` 중 `Building wheel...` 후 실패 | cp312 휠 부재 패키지가 sdist 빌드 시도 (3.12는 distutils 제거). 내부 PyPI에 cp312 휠 반입 요청. `make verify-wheels`로 대상 식별 |
| embedding/reranker 기동 시 Hub 접속 오류 | 모델 경로 미배치 또는 Hub ID 로딩 코드 혼입. `HF_HUB_OFFLINE=1` 유지 상태에서 `*_MODEL_PATH` 확인 |
| 로그인 버튼이 반응 없음 / `crypto.subtle` 오류 | HTTP + LAN IP 로 접속함. WebCrypto 는 HTTPS 또는 localhost 에서만 동작 — TLS 적용 또는 localhost 사용 |
| 로그인 401 (비밀번호 맞음) | chat-gateway `CHAT_WORKSPACE_SLUG` ≠ chat-web `NEXT_PUBLIC_WORKSPACE_SLUG`, 또는 admin-api 와 gateway 의 `PASSWORD_PEPPER_FILE` 불일치 |
| 답변이 스트리밍되지 않음(완료 후 한 번에 표시) | WS 미연결. 브라우저 콘솔의 `/ws` 403 → Origin 불일치(dev 는 `CHAT_CORS_ORIGINS`), Ingress 는 `/ws` 라우팅·websocket timeout 확인 |
| "생각 중…" 에서 멈춤 | rag-worker 미기동/실패. `chat_jobs.status`·worker 로그 확인 (실패 시 Bot Post 가 오류 안내로 갱신됨) |
| 답변에 다른 채널 문서 인용 | 발생 시 Critical. 문서 ACL(`document_channel_acl`)·Qdrant `allowed_channel_ids` 가 채널 UUID 인지 확인, `make test-isolation` |
| 피드백 클릭이 401 | `FEEDBACK_SIGNING_KEY_FILE` 이 gateway 와 worker 간 불일치(또는 키 교체 후 이전 답변). 키는 Secret 으로 고정 운용 |
| 질문이 무응답(Bot 답변 없음) | Binding 비활성/미설정 또는 Trigger Word 미일치 — 메시지는 일반 대화로만 게시됨. admin-web 채널 관리에서 확인 |
| 채널이 사이드바에 없음 | 채널 멤버가 아님. admin-web 채널 관리 › 멤버 추가 (연결 중이면 재접속 시 반영) |
| vLLM Pod CrashLoop | startupProbe 시간 부족 또는 VRAM 초과. `--max-model-len`/quantization 확인 |

---

## 라이선스 / 반입 고지

본 저장소의 소스 코드와 문서는 [MIT License](LICENSE)로 배포됩니다.

의존 오픈소스와 모델에는 각자의 라이선스가 적용되며, 이 저장소의 MIT 라이선스가 그것을 바꾸지 않습니다.
- **PyMuPDF(AGPL-3.0)**: parser-indexer 가 PDF 파싱에 사용합니다. parser-indexer 이미지를 외부에 배포하거나 네트워크 서비스로 제공하면 AGPL-3.0 의무가 적용될 수 있으니, 그런 경우 Artifex 상용 라이선스를 받거나 PyMuPDF 의존을 걷어내고 pdfplumber(MIT)로 대체하는 것을 검토하세요(현재 `pdf_parser.py` 는 `PDF_TEXT_ENGINE` 값과 무관하게 PyMuPDF 를 import 합니다). 이 저장소의 소스 코드 자체를 공개·재사용하는 데는 영향이 없습니다.
- 그 밖의 오픈소스(vLLM, Qdrant, FastAPI, FlagEmbedding 등)와 모델(Qwen/EXAONE/BGE·KURE 계열)도 폐쇄망 반입 시 라이선스 검토·해시 검증·SBOM 등록을 완료해야 합니다 (PRD §21, NFR-SEC-012).
- `docs/pdf/` 의 한글 공공 PDF 는 재배포 권리가 불명확해 저장소에 포함하지 않습니다 (rke2 가이드 §5.1.2).
