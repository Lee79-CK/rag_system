# RAG Chatbot Platform — Claude Code Context

## What this is
폐쇄망 K8s 위 **Web Chat** RAG 챗봇 (v2.0: 사용자 UI = `apps/chat-web`, aiops_chatbot UI 이식 · Mattermost 제거).
설계 SSOT: `docs/TDD.md`, 요구사항: `docs/PRD.md`. 이식 기록: `apps/chat-web/PORTING.md`.
Monorepo (uv workspace). **구현 현황: M1–M12 구현 완료** (M12 = Web Chat 전환, 로컬 mock LLM/mock 엔진 기준).
2026-09-10 코드 리뷰(`docs/code-review-2026-09-10.md` — v1.x Mattermost 기준, 역사 기록)의 수정은 v2.0 에 이월됨
(Containerfile·Alembic hook Job·K8s 색인 트리거/RBAC·claim_job 멱등·RQ timeout·SecretStr·마스킹·fail-closed).
검증: `270 passed` (Docker 없으면 실 Qdrant CH-001 1 skipped) · ruff clean · `helm lint`(values / +poc / +poc+lab) clean · admin-web / chat-web build OK.
알려진 미구현(리뷰 §7 중 v2.0 에 유효한 것): Settings 테이블→rag-api 연동(60s 캐시), 문서 삭제 시 원본 파일·Vector 물리 삭제(검색 제외 is_active=false 는 구현됨),
mock 엔진 silent fallback 차단, async 핸들러 내 동기 I/O(chat-gateway SqlChatStore·admin 업로드), rate limit 비원자(INCR→EXPIRE),
CHAT_MAX_CONCURRENCY 미강제, 평가셋 100문항·LLM-judge, Circuit Breaker(reranker 장애는 벡터 순서 대체로 완화됨).

## Hard rules
- 외부 네트워크 호출 금지 (HF Hub, PyPI, CDN 폰트 등). 모델은 로컬 경로 로딩만. chat-web 에 외부 CDN 리소스 추가 금지.
- Python 3.12 고정 (`requires-python ">=3.12,<3.13"`). 의존성은 cp312 바이너리 휠(또는 pure-python wheel)만, sdist 빌드 금지.
- Secret(JWT 키/pepper/피드백 서명키/토큰/쿠키)을 로그·응답·repr에 절대 노출 금지. Pydantic `SecretStr`, 파일 mount(`*_FILE`).
- Secret 파일(JWT 키 / password pepper / 피드백 서명키)이 없거나 비면 **fail-closed**(빈 키로 서명·해시 금지 → 로그인 503, 피드백 401). "테스트 편의로 빈 값 허용" 금지.
- Qdrant 검색은 `build_filter()` 없이 호출 금지 (Channel 격리 100%). 격리 키 = `chat_channels.id`. 예외: parser-indexer 내부 검증(`count`/`query_points`, `document_version_id` 필터)·admin-api 문서 청크 조회(`list_chunks`, `document_version_id` scroll)는 서빙 경로가 아님.
- Channel 격리는 멤버십으로도 강제: chat-gateway 의 채널 리소스는 멤버만(비멤버 = 404), socket.io 는 **멤버 채널 room 만 join**.
- `apps/*` 간 직접 import 금지. 공유는 `libs/*` 로만 (gateway ↔ worker 공유 코드는 `libs/chat-adapter`).
- `rag/domain/*` 은 FastAPI/LangChain/socket.io 타입 import 금지 (순수 Python + rag_schemas).
- 스키마 변경은 `libs/schemas` 에서만. 서비스 로컬 재정의 금지. Web Chat DTO(`rag_schemas.webchat`)를 바꾸면 chat-web TS 타입(`src/lib/query/hooks.ts`, `src/shared/*`)도 함께.
- 피드백(`POST /api/v1/actions`) 경로는 JWT + 채널 멤버십 + HMAC 피드백 토큰(`message_id:bot_post_id`) 검증 필수, LLM/Queue 호출 금지.
- Worker 는 `claim_job`(QUEUED→RUNNING 원자 전이)을 선점한 경우에만 처리 — RQ 재실행/중복 enqueue 로 Bot Post 가 중복 갱신되지 않게.
- 비밀번호 원문은 서버로 오지 않는다 (PBKDF2 prehash). prehash 알고리즘은 `rag_common.passwords` ↔ `chat-web/src/shared/crypto/prehash.ts` 바이트 동일 유지 (고정 벡터 테스트).
- `../aiops_chatbot` 원본은 수정하지 않는다. 이식한 코드는 `apps/chat-web` 안에서만 변경하고 PORTING.md 에 기록.

## Layout
- `libs/schemas` (rag_schemas) — 공유 Pydantic 스키마 (SSOT, §4). `webchat.py` = chat-web ↔ gateway 계약
- `libs/common` (rag_common) — ids/json/retry/cache/hashing + `passwords`(prehash/scrypt+pepper) + `jwt`(HS256)
- `libs/observability` (rag_observability) — structlog + prometheus + secret masking
- `libs/chat-adapter` (chat_adapter) — 답변 렌더(markdown+blocks) · 피드백 토큰 · socket.io StreamEmitter · PostDto 매핑
- `apps/chat-gateway` (gateway) — Web Chat 백엔드: 로그인/채널/질문/피드백 REST + socket.io `/ws` (:8001)
- `apps/chat-web` — 사용자 Web Chat UI (Next.js 15 + React 19 + TanStack Query + zustand + socket.io-client, aiops_chatbot 이식). uv workspace 제외 (npm)
- `apps/rag-api` (rag) — RAG orchestration + worker (LLM 스트리밍 → WebChatDelivery)
- `apps/admin-api` (admin) — 문서(ACL)/채널·Binding·멤버/채팅 사용자/설정/피드백 관리 + Alembic(head `0003_webchat`)
- `apps/embedding-api` (embedding) / `apps/reranker-api` (reranker) — CPU serving (로컬 mock 엔진)
- `apps/parser-indexer` (ingestion) — 문서 파싱/색인 CLI Job
- `apps/admin-web` — 관리자 Portal (React 18 + Vite + TS + React Query + antd). uv workspace 제외.
- `tools/mock-llm` (mock_llm) — 로컬 OpenAI-compatible mock LLM, `stream:true` SSE 지원 (`make mock-llm`)
- `tools/evaluation` (evaluation) — RAG 품질 평가 runner (`make evaluate`)
- `samples/` — E2E 용 샘플 문서(.md), 업로드 예시는 `samples/README.md` (ACL = 채널 UUID)
- `docs/pdf/` — 한글 공공 PDF 5종(RKE2 한글 색인 테스트용, git 미추적). 파서/임베딩 선정 근거 = rke2 가이드 §5.1.2, A/B 평가셋 `tests/evaluation/dataset-ko-pdf`
- `tests/channel-isolation` — CH-001~010 격리 Gate / `tests/contract` mock-llm SSE 계약 / `tests/evaluation` 데이터셋 / `tests/performance` locust
- `deploy/helm/rag-platform` — 단일 Helm chart (Deployment/Service/PDB/NetworkPolicy/Ingress/Namespace/RBAC/Alembic hook Job/Grafana). `values.yaml` 기본 → `values-poc.yaml`(운영 override) → `values-lab.yaml`(RKE2 랩 override). Secret 은 `appServices.<svc>.secretMount.keys` 로 필요한 키만 마운트
- `apps/*/Containerfile` — Python 서비스는 빌드 컨텍스트 = 리포 루트, `chat-web`·`admin-web` 은 자체 디렉터리. `make build-images REG= TAG=`
- `scripts/` — `redeploy_lab.sh`(랩 재배포: 커밋 → 빌드·push → helm upgrade, 가이드 §4.6), `export_openapi.py`, `measure_latency.py`(p95), `seed_dev.sql`, `create_chat_user.py`, `inspect_pdf.py`(업로드 전 PDF 파싱/청크 점검)

## Commands
- `make install`        # uv sync (workspace)
- `make lint`           # ruff + mypy
- `make test`           # 전체 pytest
- `make test-isolation` # CH-001~010 Channel 격리 (배포 차단 Gate)
- `make test-integration` # tests/contract (mock-llm SSE ↔ LLMClient) + 실 Qdrant 격리(Docker)
- `make evaluate`       # RAG 품질 평가 runner → reports/
- `make mock-llm`       # 로컬 OpenAI-compatible mock LLM (:8010)
- `make qdrant-init`    # rag_chunks_v1 collection + payload index
- `make seed` / `make seed-users`  # 채널·Binding·ACL / 채팅 데모 사용자+멤버십 (PASSWORD_PEPPER_FILE 필요)
- `make chat-gateway`   # :8001 (REST + /ws)
- `make chat-web-dev` / `make chat-web-build`  # :3000 dev / standalone build
- `make perf-chat-burst` # locust 질문 burst (CHAT_EMAIL/CHAT_PASSWORD)
- `make openapi`        # docs/openapi/*.json export (API 변경 시 재실행 후 커밋)
- `make build-images` / `make push-images` REG=registry.local:5000 TAG=$(git rev-parse --short HEAD)   # 8종 (Python 6 + chat-web + admin-web)
- `make helm-lint` / `make helm-template`   # chart lint + poc / poc+lab 렌더
- admin-web: `cd apps/admin-web && npm ci && npm run build`

## Local dev caveat (this machine)
실 모델 dep(torch/FlagEmbedding)은 미설치(optional `models` extra).
`EMBEDDING_MOCK=1`/`RERANKER_MOCK=1` + `make mock-llm` 로 결정론적 mock 경로가 기본.
GPU 노드: `uv sync --extra models` 로 실 엔진 활성화.

## Local dev notes
- 모델 미배치 로컬에서는 `EMBEDDING_MOCK=1`/`RERANKER_MOCK=1` 로 결정론적 mock 엔진 사용.
- LLM은 `make mock-llm` 후 `VLLM_API_URL=http://localhost:8010/v1`.
- Secret 파일: `secrets/rag/{jwt-secret,password-pepper,feedback-signing-key}` (gitignore). gateway·worker·admin-api 가 공유.
- chat-web 은 `http://localhost:3000` 으로 접속 (prehash 가 WebCrypto 사용 → HTTPS 또는 localhost 에서만 동작).
  dev WS 는 gateway 직접 연결(`NEXT_PUBLIC_WS_URL=http://localhost:8001`, gateway `CHAT_CORS_ORIGINS=http://localhost:3000`).
- 데모 계정(`make seed-users`): hong@example.com(admin, 두 채널) / kim@example.com(rag-hr) — `Rag!Assistant2026` (로컬 전용).

## Test naming
PRD 요구사항 ID를 테스트 이름에 포함: `test_fr_web_006_...`, `test_ch_002_...`, `test_fb_...`.
