# RAG Platform — dev Makefile. docs/README.md, docs/TDD.md §17.
# uv workspace: 단일 lockfile/venv 로 전 멤버 관리.

UV ?= uv

.PHONY: help install lint fmt test test-cov test-isolation test-integration \
<<<<<<< HEAD
        evaluate perf-webhook-burst mock-llm mock-mattermost qdrant-init seed openapi \
        build-images push-images helm-lint helm-template infra-up infra-down clean

# 이미지 빌드/푸시 (Containerfile 은 앱별, 빌드 컨텍스트는 리포 루트 — admin-web 만 자체 디렉터리)
REG ?= registry.local:5000
TAG ?= $(shell git rev-parse --short HEAD)
PY_IMAGES := mattermost-bridge rag-api admin-api embedding-api reranker-api parser-indexer
=======
        evaluate perf-chat-burst mock-llm qdrant-init seed seed-users openapi \
        chat-gateway chat-web-dev chat-web-build infra-up infra-down clean
>>>>>>> bd76b61 (Mattermost 대신 chatbot UI 추가)

help:
	@grep -E '^[a-zA-Z_-]+:.*?# ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?# "}{printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

install: # 전 서비스 의존성 설치 (uv workspace sync)
	$(UV) sync --all-packages

lint: # ruff (lint+format check) + mypy
	$(UV) run ruff check .
	$(UV) run ruff format --check .
	$(UV) run mypy libs apps || true

fmt: # ruff 자동 포맷 + import 정렬
	$(UV) run ruff format .
	$(UV) run ruff check --fix .

test: # 전체 unit test
	$(UV) run pytest

test-cov: # coverage 리포트 (전체 ≥80%, rag/domain ≥90%)
	$(UV) run pytest --cov=libs --cov=apps --cov-report=term-missing

test-isolation: # ★ CH-001~010 Channel 격리 (배포 차단 Gate, §13.2)
	$(UV) run pytest tests/channel-isolation -v

<<<<<<< HEAD
test-integration: # Docker 가 필요한 통합 테스트 (testcontainers Qdrant + worker 통합). tests/integration 디렉터리는 없다
	$(UV) run pytest tests/channel-isolation/test_ch_qdrant.py apps/rag-api/tests/test_worker_integration.py -v
=======
test-integration: # 계약/통합 테스트 (mock-llm SSE ↔ LLMClient 등)
	$(UV) run pytest tests/contract -v
>>>>>>> bd76b61 (Mattermost 대신 chatbot UI 추가)

evaluate: # RAG 품질 평가 runner (§13.3) → reports/evaluation_report.md
	$(UV) run python -m evaluation.runner --dataset tests/evaluation/dataset

perf-chat-burst: # 질문 Burst 부하 (ACK p95 ≤ 2s, §8.5) — CHAT_EMAIL/CHAT_PASSWORD 필요
	$(UV) run locust -f tests/performance/locustfile.py --headless -u 50 -r 50 -t 10s \
		--host $${GATEWAY_URL:-http://localhost:8001}

mock-llm: # 로컬 OpenAI-compatible mock LLM (:8010) — §5.4
	$(UV) run python -m mock_llm.server

mock-mattermost: # Incoming Webhook 수신 mock (:9099) — 답변 게시 payload 확인 (tools/mock-mattermost)
	$(UV) run python -m mock_mattermost.server

build-images: # 컨테이너 이미지 8종 빌드 (REG=... TAG=...). embedding/reranker 는 --extra models 포함(UV_EXTRA=models 기본)
	for app in $(PY_IMAGES); do \
	  docker build -f apps/$$app/Containerfile -t $(REG)/rag/$$app:$(TAG) . || exit 1; \
	done
	docker build -f tools/mock-mattermost/Containerfile -t $(REG)/rag/mock-mattermost:$(TAG) .
	docker build -f apps/admin-web/Containerfile -t $(REG)/rag/admin-web:$(TAG) apps/admin-web

push-images: # build-images 로 만든 이미지 push
	for img in $(PY_IMAGES) mock-mattermost admin-web; do docker push $(REG)/rag/$$img:$(TAG) || exit 1; done

helm-lint: # chart lint
	helm lint deploy/helm/rag-platform

helm-template: # poc / poc+lab 두 프로파일 렌더 (stdout)
	helm template rag-platform deploy/helm/rag-platform -f deploy/helm/rag-platform/values-poc.yaml > /dev/null && echo "poc OK"
	helm template rag-platform deploy/helm/rag-platform -f deploy/helm/rag-platform/values-poc.yaml \
	  -f deploy/helm/rag-platform/values-lab.yaml > /dev/null && echo "poc+lab OK"

qdrant-init: # rag_chunks_v1 collection + payload index 생성 (§6.2)
	$(UV) run python -m ingestion.tools.qdrant_init

seed: # DB 샘플 데이터 (scripts/seed_dev.sql) — 채널/Binding/문서 ACL
	psql "$${DATABASE_URL:-postgresql://rag:rag-dev-only@localhost:5432/rag}" -f scripts/seed_dev.sql

seed-users: # Web Chat 데모 사용자 + 채널 멤버십 (PASSWORD_PEPPER_FILE 필요)
	$(UV) run python scripts/create_chat_user.py --email hong@example.com --name 홍길동 \
		--password '$(or $(CHAT_DEMO_PASSWORD),Rag!Assistant2026)' --channels rag-cloud-ops,rag-hr --role admin
	$(UV) run python scripts/create_chat_user.py --email kim@example.com --name 김민수 \
		--password '$(or $(CHAT_DEMO_PASSWORD),Rag!Assistant2026)' --channels rag-hr

chat-gateway: # Web Chat 백엔드 (REST + socket.io /ws, :8001)
	$(UV) run --package chat-gateway uvicorn gateway.main:app --port 8001 --reload

chat-web-dev: # Web Chat UI dev 서버 (:3000) — /api 는 CHAT_GATEWAY_URL 로 프록시
	cd apps/chat-web && CHAT_GATEWAY_URL=$${CHAT_GATEWAY_URL:-http://localhost:8001} \
		NEXT_PUBLIC_WS_URL=$${NEXT_PUBLIC_WS_URL:-http://localhost:8001} npm run dev

chat-web-build: # Web Chat UI 프로덕션 빌드 (standalone → .next/standalone/server.js)
	cd apps/chat-web && npm run typecheck && npm run build

openapi: # 각 FastAPI 앱 OpenAPI 스키마 export → docs/openapi/*.json
	$(UV) run python scripts/export_openapi.py

infra-up: # 로컬 인프라 기동 (postgres/redis/qdrant)
	docker compose -f docker-compose.dev.yml up -d

infra-down:
	docker compose -f docker-compose.dev.yml down

clean:
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	rm -rf .pytest_cache .ruff_cache .mypy_cache .coverage
