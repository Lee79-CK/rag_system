# RAG Platform — dev Makefile. docs/README.md, docs/TDD.md §17.
# uv workspace: 단일 lockfile/venv 로 전 멤버 관리.

UV ?= uv

.PHONY: help install lint fmt test test-cov test-isolation test-integration \
        evaluate perf-webhook-burst mock-llm qdrant-init seed openapi \
        infra-up infra-down clean

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

test-integration: # testcontainers 통합 테스트 (Docker 필요)
	$(UV) run pytest tests/integration -v

evaluate: # RAG 품질 평가 runner (§13.3) → reports/evaluation_report.md
	$(UV) run python -m evaluation.runner --dataset tests/evaluation/dataset

perf-webhook-burst: # Webhook Burst 부하 (ACK p95 ≤ 2s, §8.5)
	$(UV) run locust -f tests/performance/locustfile.py --headless -u 50 -r 50 -t 10s \
		--host $${BRIDGE_URL:-http://localhost:8001}

mock-llm: # 로컬 OpenAI-compatible mock LLM (:8010) — §5.4
	$(UV) run python -m mock_llm.server

qdrant-init: # rag_chunks_v1 collection + payload index 생성 (§6.2)
	$(UV) run python -m ingestion.tools.qdrant_init

seed: # DB 샘플 데이터 (scripts/seed_dev.sql)
	psql "$${DATABASE_URL:-postgresql://rag:rag-dev-only@localhost:5432/rag}" -f scripts/seed_dev.sql

openapi: # 각 FastAPI 앱 OpenAPI 스키마 export → docs/openapi/*.json
	$(UV) run python scripts/export_openapi.py

infra-up: # 로컬 인프라 기동 (postgres/redis/qdrant)
	docker compose -f docker-compose.dev.yml up -d

infra-down:
	docker compose -f docker-compose.dev.yml down

clean:
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	rm -rf .pytest_cache .ruff_cache .mypy_cache .coverage
