# RAG Chatbot Platform — Claude Code Context

## What this is
폐쇄망 K8s 위 Mattermost RAG 챗봇. 설계 SSOT: `docs/TDD.md`, 요구사항: `docs/PRD.md`.
Monorepo (uv workspace). **구현 현황: M1–M11 전 마일스톤 구현 완료** (로컬 mock LLM/mock 엔진 기준).
검증: `112 passed, 1 skipped`(Docker-gated) · ruff clean · `helm lint` clean · admin-web `vite build` OK.

## Hard rules
- 외부 네트워크 호출 금지 (HF Hub, PyPI 등). 모델은 로컬 경로 로딩만.
- Python 3.12 고정 (`requires-python ">=3.12,<3.13"`). 의존성은 cp312 바이너리 휠만, sdist 빌드 금지.
- Secret(토큰/Webhook URL)을 로그·응답·repr에 절대 노출 금지. Pydantic `SecretStr`.
- Qdrant 검색은 `build_filter()` 없이 호출 금지 (Channel 격리 100%).
- `apps/*` 간 직접 import 금지. 공유는 `libs/*` 로만.
- `rag/domain/*` 은 FastAPI/LangChain/Mattermost 타입 import 금지 (순수 Python + rag_schemas).
- 스키마 변경은 `libs/schemas` 에서만. 서비스 로컬 재정의 금지.
- 피드백(`/actions`) 경로는 HMAC 서명 검증 필수, LLM/Queue 호출 금지.

## Layout
- `libs/schemas` (rag_schemas) — 공유 Pydantic 스키마 (SSOT, §4)
- `libs/common` (rag_common) — ids/json/retry/cache/hashing
- `libs/observability` (rag_observability) — structlog + prometheus + secret masking
- `libs/mattermost-adapter` (mattermost_adapter) — payload 정규화 + 렌더 + deliver()
- `apps/mattermost-bridge` (bridge) — Webhook 수신/응답 Adapter
- `apps/rag-api` (rag) — RAG orchestration + worker
- `apps/admin-api` (admin) — 문서/Channel/설정/피드백 관리
- `apps/embedding-api` (embedding) / `apps/reranker-api` (reranker) — CPU serving (로컬 mock 엔진)
- `apps/parser-indexer` (ingestion) — 문서 파싱/색인 CLI Job
- `apps/admin-web` — 관리자 Portal (React 18 + Vite + TS + React Query + antd). uv workspace 제외.
- `tools/mock-llm` (mock_llm) — 로컬 OpenAI-compatible mock LLM (`make mock-llm`)
- `tools/evaluation` (evaluation) — RAG 품질 평가 runner (`make evaluate`)
- `tests/channel-isolation` — CH-001~010 격리 Gate / `tests/evaluation` 데이터셋 / `tests/performance` locust
- `deploy/helm/rag-platform` — Umbrella Helm chart (Deployment/Service/PDB/NetworkPolicy/Grafana)
- `scripts/` — `export_openapi.py`, `measure_latency.py`(p95), `seed_dev.sql`

## Commands
- `make install`        # uv sync (workspace)
- `make lint`           # ruff + mypy
- `make test`           # 전체 pytest
- `make test-isolation` # CH-001~010 Channel 격리 (배포 차단 Gate)
- `make evaluate`       # RAG 품질 평가 runner → reports/
- `make mock-llm`       # 로컬 OpenAI-compatible mock LLM (:8010)
- `make qdrant-init`    # rag_chunks_v1 collection + payload index
- `make openapi`        # docs/openapi/*.json export
- admin-web: `cd apps/admin-web && npm install && npm run build`

## Local dev caveat (this machine)
Intel macOS + no GPU → 실 모델 dep(torch/FlagEmbedding)은 미설치(optional `models` extra).
`EMBEDDING_MOCK=1`/`RERANKER_MOCK=1` + `make mock-llm` 로 결정론적 mock 경로가 기본.
GPU 노드: `uv sync --extra models` 로 실 엔진 활성화.

## Local dev notes
- 모델 미배치 로컬에서는 `EMBEDDING_MOCK=1`/`RERANKER_MOCK=1` 로 결정론적 mock 엔진 사용.
- LLM은 `make mock-llm` 후 `VLLM_API_URL=http://localhost:8010/v1`.

## Test naming
PRD 요구사항 ID를 테스트 이름에 포함: `test_fr_mm_006_...`, `test_ch_002_...`, `test_fb_...`.
