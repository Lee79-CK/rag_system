# 로컬 Laptop 테스트 가이드 — RAG Platform

> 문서 ID: GUIDE-LOCAL-TEST-001 (v2.0 — Web Chat 전환: Mattermost 제거)
> 기준: TDD-RAG-CHATBOT-POC-001 + **현행 구현 기준** — 전 백엔드 Python 3.12 (uv workspace), 사용자 UI `apps/chat-web`(Next.js 15, npm)
> 변경(v2.0): 사용자 접점이 Mattermost 에서 **Web Chat(`apps/chat-web` + `apps/chat-gateway`)** 으로 바뀌었습니다. Mattermost Outgoing/Incoming Webhook 을 curl 로 모사하던 절차는 전부 **브라우저 기반 E2E** 로 대체됩니다. (Mattermost 는 v2.0 에서 제거 — 관련 Secret/토큰/mock 서버 불필요)
> 이월(v1.2 → v2.0): **v1.2(2026-09-10 코드 리뷰) 반영분** — 앱별 Containerfile·`make build-images`, Alembic migration hook Job(`migration.enabled`), K8s 색인 트리거(`INDEX_JOB_TRIGGER=none|k8s`, 업로드 `start_indexing`), NS 라벨(`rag-platform=true`), `samples/` 샘플 문서, `make test-integration` 대상 정정 등 — 이 v2.0 에 이월되었습니다(상세: `docs/TDD.md` 변경 이력 v2.0.1). 리뷰 중 Mattermost 전용 항목(mock 서버·Webhook Secret·서명 스크립트)은 v2.0 에서 폐기되었습니다.
> 정정(v1.1, 유지): TDD 초기 문서는 admin-api를 Java 21 Spring Boot로 기술하지만, **구현된 `apps/admin-api` 는 Python(FastAPI + SQLAlchemy + Alembic)** 입니다. JDK/Gradle은 필요 없습니다.
> 대상 환경: **i7 13세대 / RAM 64GB / SSD 1.5TB / RTX 4060 8GB / Windows 11 / Docker Desktop**

---

## 0. 이 가이드가 검증하는 범위

| 검증 항목 | 로컬 가능 여부 | 방법 |
|---|---|---|
| Web Chat 로그인 (prehash → scrypt+pepper, JWT + refresh 쿠키) | ✅ 완전 | 브라우저 (chat-web :3000 → chat-gateway :8001) |
| Web Chat 질문 → 스트리밍 답변 → 근거 문서 표 → 피드백 👍/👎 | ✅ 완전 | 브라우저 + socket.io(`/ws`) |
| 채널 멤버십 격리 (비멤버 404 / WS room 미가입) | ✅ 완전 | 브라우저(사용자 2명) + 자동 테스트 |
| RAG 파이프라인 (Embedding→검색→Rerank→생성) | ✅ 완전 | CPU 모델 + **소형 LLM(GPU)** 또는 mock-llm |
| 문서 파싱/색인 (parser-indexer) | ✅ 완전 | CLI 실행 |
| Admin API (FastAPI) / Admin Web (채널·채팅 사용자·문서 ACL) | ✅ 완전 | 로컬 기동 |
| Channel 격리 (CH-001~010) | ✅ 완전 | `make test-isolation`(in-memory fake) + `make test-integration`(testcontainers 실 Qdrant) |
| **답변 품질 (32B 모델)** | ⚠️ 불가 | 4060 8GB로는 4B~7B 4bit까지만 — 품질 평가는 DGX/서버에서 |
| 성능 목표 (p95 30s @ 동시 10) | ⚠️ 참고치만 | 소형 모델 기준 경향 확인 용도 |
| K8s/Helm 배포 | 🔶 선택 | Docker Desktop 내장 K8s 또는 생략 |

**핵심 제약**: RTX 4060 8GB(VRAM)로 운영 대상 Qwen3-32B는 구동 불가합니다. 로컬은 **Qwen3-4B(AWQ/GPTQ 4bit)** 로 파이프라인 정합성·격리·계약을 검증하고, 품질/성능 수치는 GPU 서버 환경에서 측정합니다. RAM 64GB는 BGE-M3(CPU) + Reranker(CPU) + 전체 서비스 + testcontainers 동시 구동에 충분합니다.

---

## 1. 사전 준비 (Windows 11)

### 1.1 WSL2 + Ubuntu 24.04

Python 서비스와 vLLM은 Linux 전용 휠이 필요하므로 **모든 Python/GPU 작업은 WSL2 내부에서** 수행합니다. (Windows 네이티브 Python 사용 금지 — cp312 manylinux 휠 정책과 vLLM 미지원)

```powershell
# PowerShell (관리자)
wsl --install -d Ubuntu-24.04
wsl --update
```

`C:\Users\<you>\.wslconfig` 생성 — 64GB 중 WSL에 충분히 할당:

```ini
[wsl2]
memory=48GB
processors=12
swap=16GB
```

```powershell
wsl --shutdown   # 설정 반영
```

### 1.2 Docker Desktop

- Settings → General → **Use the WSL 2 based engine** 체크
- Settings → Resources → WSL Integration → **Ubuntu-24.04 활성화**
- GPU 확인 (WSL2 백엔드는 NVIDIA GPU 패스스루 기본 지원, 최신 Game Ready/Studio 드라이버 필요):

```bash
# WSL2 Ubuntu 터미널
nvidia-smi                                   # RTX 4060, 8188MiB 표시 확인
docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi
```

### 1.3 개발 도구 설치

**WSL2 Ubuntu 내부:**

```bash
# uv + Python 3.12 — admin-api·chat-gateway 포함 전 백엔드 서비스가 이걸로 돌아간다 (JDK/Gradle 불필요)
curl -LsSf https://astral.sh/uv/install.sh | sh
uv python install 3.12

# Node 22+ — chat-web(Next.js 15 / React 19) 과 admin-web(React/Vite) 공용.
# WSL에서 실행 권장 (경로/줄바꿈·파일감시 문제 회피). chat-web 운영 이미지가 Node 22 런타임 기준이므로 로컬도 22 로 통일
curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash - && sudo apt install -y nodejs

uv --version
node -v         # v22.x 이상
```

### 1.4 저장소 클론 — 반드시 WSL 파일시스템에

```bash
# ✅ WSL ext4 (빠름):  ~/work/rag-platform
# ❌ /mnt/c/... (NTFS 경유 — uv/npm 설치·파일감시 극도로 느림, CRLF 문제)
mkdir -p ~/work && cd ~/work
git clone https://git.internal.example/ai/rag-platform.git && cd rag-platform
git config core.autocrlf input   # CRLF 방지
```

### 1.5 모델 다운로드 및 배치

개발망(인터넷 가능) 전제. 폐쇄망 노트북이면 반입 아티팩트를 동일 경로에 복사합니다.

```bash
sudo mkdir -p /models && sudo chown $USER /models
uv tool install "huggingface_hub[cli]"

# CPU 모델 (RAM 사용: BGE-M3 약 2.5GB, reranker 약 2GB)
hf download BAAI/bge-m3               --local-dir /models/embedding/bge-m3
hf download BAAI/bge-reranker-v2-m3   --local-dir /models/reranker/bge-reranker-v2-m3

# ★ 로컬용 소형 LLM — 8GB VRAM 기준 권장: Qwen3-4B AWQ (4bit, ~3.3GB + KV cache)
hf download Qwen/Qwen3-4B-AWQ         --local-dir /models/llm/local-4b

# 다운로드 후에는 TDD 오프라인 규칙 그대로 검증
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
```

> 대안: VRAM 여유를 더 확보하려면 `Qwen3-1.7B`(비양자화)도 가능. 7B급 4bit는 KV cache를 줄이면(context 4K) 아슬아슬하게 구동되나 데스크톱 화면 출력이 같은 GPU를 쓰는 노트북 특성상 OOM이 잦아 **4B AWQ를 표준**으로 합니다.

---

## 2. 인프라 및 vLLM 기동

### 2.1 PostgreSQL / Redis / Qdrant

```bash
cd ~/work/rag-platform
docker compose -f docker-compose.dev.yml up -d
docker compose -f docker-compose.dev.yml ps    # postgres:16, redis:7, qdrant 모두 Up
```

### 2.2 vLLM (GPU) — 로컬 프로파일

`docker-compose.gpu.yml` (레포 미포함 시 아래로 생성):

```yaml
services:
  vllm:
    image: vllm/vllm-openai:latest        # 폐쇄망: harbor.internal/ai/vllm-openai@sha256:...
    ports: ["8010:8000"]
    volumes: ["/models:/models:ro"]
    environment: [HF_HUB_OFFLINE=1, TRANSFORMERS_OFFLINE=1]
    deploy:
      resources:
        reservations:
          devices: [{ driver: nvidia, count: 1, capabilities: [gpu] }]
    command: >
      --model /models/llm/local-4b
      --served-model-name internal-rag-llm
      --max-model-len 8192
      --gpu-memory-utilization 0.85
      --max-num-seqs 4
      --dtype auto
```

```bash
docker compose -f docker-compose.gpu.yml up -d
# 기동 확인 (모델 로딩 1~3분)
curl -s localhost:8010/v1/models | jq .
curl -s localhost:8010/v1/chat/completions -H 'Content-Type: application/json' -d '{
  "model":"internal-rag-llm",
  "messages":[{"role":"user","content":"한 문장으로 자기소개"}],"max_tokens":64}' | jq -r '.choices[0].message.content'
nvidia-smi   # VRAM 사용 ~6.5GB 내외 확인
```

**운영과의 의도적 차이 (기록해 둘 것):**

| 항목 | 운영(TDD §8.2) | 로컬 | 이유 |
|---|---|---|---|
| 모델 | Qwen3-32B | Qwen3-4B-AWQ | VRAM 8GB |
| max-model-len | 16384 | 8192 | KV cache 절약 |
| max-num-seqs | 16 | 4 | 동시성 축소 |
| MAX_CONTEXT_TOKENS(.env) | 8192 | **6144로 하향** | 8192 model-len 내 output 1024 + margin 확보 |

GPU 없이 검증할 땐 vLLM 대신 `make mock-llm`(:8010, OpenAI 호환 고정응답 + `stream:true` SSE 스트리밍)으로 대체 가능 — 파이프라인/격리/Web Chat 스트리밍 테스트에는 충분합니다.

---

## 3. 설정 / Secret / 시드

```bash
cp .env.example .env
# 로컬 조정 항목만 수정:
#   VLLM_API_URL=http://localhost:8010/v1
#   MAX_CONTEXT_TOKENS=6144
#   LLM_MODEL_PATH=/models/llm/local-4b
#   TOKENIZER_PATH=/models/llm/local-4b
# 아래 항목은 .env.example 기본값 그대로 로컬에 맞다:
#   DOCUMENT_STORAGE_PATH=./data/documents   (admin-api 업로드 저장 경로 — 리포 루트 기준 상대경로, parser-indexer 공용. 미리 mkdir)
#   INDEX_JOB_TRIGGER=none                   (로컬은 K8s 가 없으므로 index_jobs 행만 생성 → 색인은 CLI 로 직접 실행 — §5.1)
#   EMBEDDING_MOCK=1 / RERANKER_MOCK=1       (§1.5 의 실 모델을 쓰려면 embedding-api/reranker-api 의 `models` extra(FlagEmbedding·torch) 설치 후 0 으로)
mkdir -p data/documents

# Web Chat 항목도 .env.example 기본값 그대로 로컬에 맞다:
#   CHAT_CORS_ORIGINS=http://localhost:3000   (dev: chat-web :3000 → gateway :8001 WS 교차 출처 허용)
#   COOKIE_SECURE=false                       (로컬 HTTP 전용. 운영은 true)
#   JWT_SECRET_FILE / PASSWORD_PEPPER_FILE / FEEDBACK_SIGNING_KEY_FILE = ./secrets/rag/*

# Secret 파일 3종 — chat-gateway·rag-worker·admin-api 가 파일로 읽는다 (값은 로그/응답에 노출되지 않음)
mkdir -p secrets/rag
openssl rand -hex 32 > secrets/rag/jwt-secret             # access JWT(HS256) 서명 키
openssl rand -hex 32 > secrets/rag/password-pepper        # scrypt 해시 pepper (gateway·admin-api 공유)
openssl rand -hex 32 > secrets/rag/feedback-signing-key   # 피드백 토큰 HMAC 키 (gateway·worker 공유)
chmod 600 secrets/rag/*
```

> ⚠️ **`password-pepper` 를 바꾸면 기존 채팅 사용자 비밀번호가 전부 무효**가 됩니다 (`make seed-users` 재실행 또는 admin-web 에서 비밀번호 재설정 필요). `jwt-secret` 교체는 로그인 세션만 끊기고, `feedback-signing-key` 교체는 이전 답변의 피드백 버튼만 401 이 됩니다.

```bash
# DB migration — 스키마 소유자는 admin-api의 Alembic
#   (apps/admin-api/src/admin/db/migrations, 리비전 0001_initial → 0002_feedback_enabled → 0003_webchat)
#   ※ 로컬에서는 서비스 기동 시 자동 실행되지 않는다. 아래를 명시적으로 1회 실행할 것
#     (K8s 는 migration.enabled=true 이면 Helm hook Job `rag-db-migrate` 가 install/upgrade 후 upgrade head 실행)
uv run --package admin-api \
  alembic -c apps/admin-api/src/admin/db/migrations/alembic.ini upgrade head
uv run --package admin-api \
  alembic -c apps/admin-api/src/admin/db/migrations/alembic.ini current
# → 0006_eval_runs (head)

# 시드 — 채널 2개(rag-cloud-ops / rag-hr) + Binding + 지식 범위 + 관리자(cklee/docadmin)
make seed

# 채팅 사용자 + 채널 멤버십 — 비밀번호 해시(prehash→scrypt+pepper)는 SQL로 만들 수 없어 스크립트 사용.
# Makefile 은 .env 를 읽지 않으므로 PASSWORD_PEPPER_FILE 을 export 해야 한다 (chat-gateway 와 같은 파일)
export PASSWORD_PEPPER_FILE=./secrets/rag/password-pepper
make seed-users
# ok: hong@example.com (...) channels=[rag-cloud-ops,rag-hr]   ← admin, 두 채널 멤버
# ok: kim@example.com  (...) channels=[rag-hr]                 ← user, rag-hr 만

# Qdrant collection + payload index
make qdrant-init
```

시드 결과 요약 (`scripts/seed_dev.sql` + `make seed-users`):

| 채널 (name) | chat_channels.id (= Qdrant `allowed_channel_ids`) | Binding | 지식 범위 / 대화 모드 | 멤버 |
|---|---|---|---|---|
| `rag-cloud-ops` | `c0000000-0000-0000-0000-000000000001` | DEDICATED_CHANNEL (모든 메시지 응답) | 운영매뉴얼·장애대응 / Cloud운영팀 / INTERNAL · **THREAD** | hong |
| `rag-hr` | `c0000000-0000-0000-0000-000000000002` | TRIGGER_WORD `!rag` (mention_user on) | 인사규정 / INTERNAL · CHANNEL | hong, kim |

- 데모 계정 비밀번호: `Rag!Assistant2026` (**로컬 전용**. `CHAT_DEMO_PASSWORD=... make seed-users` 로 변경 가능)
- 접속 정보는 `env.py` 가 `admin.core.config.get_settings()` 에서 가져오므로, `.env` 의 `POSTGRES_*` (또는 `DATABASE_URL`)만 맞으면 Alembic 에 별도 인자가 필요 없습니다. `make seed`/`make seed-users` 는 `DATABASE_URL`(없으면 `postgresql://rag:rag-dev-only@localhost:5432/rag`)·`POSTGRES_*` 환경변수를 씁니다.
- 시드의 `장애대응매뉴얼` 문서 행은 **실제 파일/색인이 없는 메타데이터 샘플**입니다(색인 불가). 답변 근거는 §5.1 에서 `samples/` 의 `.md` 를 업로드·색인해 만듭니다.
- `make` 가 없으면 먼저 설치하세요 (`sudo apt install -y make`). `make seed` 는 호스트의 `psql` 도 필요합니다 (`sudo apt install -y postgresql-client`).

---

## 4. 서비스 기동

uv workspace이므로 **리포 루트에서 `--package` 로 선택 실행**합니다. 서비스마다 `cd` 하면 다음 `cd` 가 상대경로로 깨지므로 아래 형태를 쓰세요. (`make dev` 같은 일괄 타깃은 없습니다 — Makefile 참조.) 모든 Python 서비스는 리포 루트의 `.env` 를 읽으므로 **반드시 루트에서** 기동합니다.

```bash
cd ~/work/rag-platform
make install     # uv sync (workspace 전체) — 최초 1회

# [T0] (GPU 없이 검증 시) mock LLM — 스트리밍(stream:true SSE) 지원
make mock-llm &                                      # :8010, MOCK_LLM_STREAM_DELAY_MS 기본 30

# [T1] CPU 모델 서빙 — 최초 로딩 1~2분, /health/startup 200 확인
#      모델 미배치 시: EMBEDDING_MOCK=1 / RERANKER_MOCK=1 (.env.example 기본값)
uv run --package embedding-api uvicorn embedding.main:app --port 8004 &
uv run --package reranker-api  uvicorn reranker.main:app  --port 8005 &

# [T2] RAG API + Worker
uv run --package rag-api uvicorn rag.main:app --port 8002 &
uv run --package rag-api rq worker rag-chat --url redis://localhost:6379/0 &

# [T3] Admin API (FastAPI — 다른 Python 서비스와 동일한 기동 방식)
uv run --package admin-api uvicorn admin.main:app --port 8003 &
# 확인: curl -s localhost:8003/health/ready | jq .
# OpenAPI: http://localhost:8003/docs   (FastAPI 기본 경로)

# [T4] chat-gateway — Web Chat 백엔드 (REST /api/v1 + socket.io /ws, :8001)
make chat-gateway &
#   = uv run --package chat-gateway uvicorn gateway.main:app --port 8001 --reload

# [T5] chat-web — Web Chat UI (uv workspace 제외 — npm, :3000)
(cd apps/chat-web && npm install) && make chat-web-dev
#   = cd apps/chat-web && CHAT_GATEWAY_URL=http://localhost:8001 NEXT_PUBLIC_WS_URL=http://localhost:8001 npm run dev
#   → http://localhost:3000

# [T6] Admin Web (uv workspace 제외 — npm, :5173 → /api 는 :8003 프록시)
#      admin-api RBAC 는 X-Auth-User 헤더 = admin_users.login_id. 시드 SYS_ADMIN 은 cklee
cd apps/admin-web && npm ci && VITE_DEV_AUTH_USER=cklee npm run dev && cd ../..   # http://localhost:5173
```

**chat-web dev 구성 요점:**
- REST(`/api/*`)는 Next dev 서버가 `CHAT_GATEWAY_URL` 로 rewrite 프록시 → 브라우저 입장에서 same-origin 이라 refresh 쿠키(`rag_rt`, HttpOnly·SameSite=Strict, Path=/api/v1/auth)가 그대로 동작합니다.
- socket.io 는 `NEXT_PUBLIC_WS_URL`(dev: `http://localhost:8001`)로 **gateway 에 직접** 연결하므로 교차 출처입니다 → gateway 의 `CHAT_CORS_ORIGINS=http://localhost:3000` 이 필요합니다(.env.example 기본값). 비우면 WS 연결이 Origin 검사에서 거부됩니다.
- **반드시 `http://localhost:3000` 으로 접속**하세요. 로그인 prehash 는 브라우저 WebCrypto(PBKDF2)를 쓰는데, WebCrypto 는 HTTPS 또는 localhost 에서만 동작합니다 — `http://192.168.x.x:3000` 같은 LAN IP·HTTP 로 접속하면 로그인 자체가 불가합니다. (Windows 브라우저에서도 WSL2 localhost 포워딩으로 `localhost:3000` 사용)
- `NEXT_PUBLIC_*` 는 build 시 고정값입니다. dev 에서는 위 환경변수(또는 `apps/chat-web/.env.local`)로 충분하고, `NEXT_PUBLIC_WORKSPACE_SLUG` 는 기본 `rag` = gateway `CHAT_WORKSPACE_SLUG` 와 같아야 로그인됩니다(prehash salt).

**기동 상태 일괄 점검** — 전 Python 서비스가 FastAPI라 health 경로가 동일합니다:

```bash
for p in 8001 8002 8003 8004 8005; do
  curl -sf localhost:$p/health/ready >/dev/null && echo "$p OK" || echo "$p FAIL"
done
curl -sf localhost:8010/v1/models >/dev/null && echo "LLM OK"
curl -sf localhost:3000/health/live >/dev/null && echo "chat-web OK"
```

예상 리소스(참고): RAM 사용 총 ~14GB (embedding 2.5 + reranker 2 + 나머지 Python 서비스 + Next dev 서버 + 기타), VRAM 6.5GB. 64GB 노트북에서 브라우저/IDE 병행 여유 충분.

---

## 5. 기능 테스트 시나리오 (E2E, 브라우저 Web Chat)

### 5.1 문서 업로드 → ACL → 색인

답변 근거로 쓸 문서를 `rag-cloud-ops` 채널 전용(ACL)으로 올립니다. **ACL 값은 채널 name 이 아니라 `chat_channels.id`(UUID)** 이며, 이 값이 Qdrant payload `allowed_channel_ids` 로 복사되어 `build_filter()` 격리의 근거가 됩니다. 지식 범위 필터(카테고리 `장애대응`·부서 `Cloud운영팀`·`INTERNAL`)에 맞춰야 검색됩니다.

로컬(`INDEX_JOB_TRIGGER=none`)에서는 업로드/재색인이 `index_jobs` 행만 만들고 끝나므로, 그 id 로 **parser-indexer CLI 를 직접 실행**합니다. (K8s 에서 `INDEX_JOB_TRIGGER=k8s` 이면 admin-api 가 ConfigMap `parser-indexer-job-template` 으로 Job 을 자동 생성 — RKE2 가이드 참고.)

**(A) curl — 권장** (`samples/장애대응매뉴얼.md`, `samples/README.md` 참고):

```bash
# 1) 업로드 + 색인 Job 생성 — 필드는 평면 multipart.
#    ★ allowed_channel_ids 를 비우면 색인되어도 어느 채널에서도 검색되지 않는다 (검색 전 Channel Filter)
JOB_ID=$(curl -s -X POST localhost:8003/api/v1/documents -H 'X-Auth-User: cklee' \
  -F 'file=@samples/장애대응매뉴얼.md' -F 'title=장애대응매뉴얼' -F 'category=장애대응' \
  -F 'department=Cloud운영팀' -F 'security_level=INTERNAL' \
  -F 'allowed_channel_ids=c0000000-0000-0000-0000-000000000001' -F 'start_indexing=true' \
  | jq -r .data.index_job_id)                         # 응답 index_job_status=PENDING
#   allowed_channel_ids 는 여러 채널이면 -F 반복 또는 콤마 구분 모두 가능.
#   UUID 형식이 아니면 422 INVALID_CHANNEL_ID, 없는 채널 UUID 면 404 CHANNEL_NOT_FOUND. 동일 내용 재업로드는 409 DUPLICATE_DOCUMENT

# 2) 색인 Job 실행 — 로컬은 CLI (루트에서 --package, .env 의 QDRANT_URL/EMBEDDING_API_URL/POSTGRES_* 사용)
uv run --package parser-indexer python -m ingestion.main --index-job-id $JOB_ID
# → PARSING→CHUNKING→EMBEDDING→UPSERTING→VALIDATING→ACTIVATING, index_job COMPLETED(stage=DONE), 문서 ACTIVE
curl -s localhost:8003/api/v1/documents -H 'X-Auth-User: cklee' | jq '.data[] | {title,status}'
```

대안 — 이미 올린 문서를 다시 색인할 때는 재색인 API 로 새 Job 을 만든 뒤 같은 CLI 를 실행합니다 (`start_indexing` 없이 업로드한 경우도 동일):

```bash
DOC_ID=<documents.id>
JOB_ID=$(curl -s -X POST localhost:8003/api/v1/documents/$DOC_ID/reindex -H 'X-Auth-User: cklee' \
  | jq -r '.data.index_job_id')                       # 응답 trigger=none, error=null
uv run --package parser-indexer python -m ingestion.main --index-job-id $JOB_ID
```

**(B) admin-web** — 문서 관리 → [문서 업로드] → 카테고리 `장애대응`, 부서 `Cloud운영팀`, 보안등급 `INTERNAL`, **허용 Channel (ACL)** 에서 `#rag-cloud-ops · Cloud 운영 Q&A` 선택 → 업로드 → 행 액션 [재색인] → 생성된 Job id 로 위 CLI 실행. (Job id 는 재색인 응답/DB `index_jobs` 로 확인 — admin-web 색인 작업 화면은 조회 API 가 없어 비어 있음, §5.6)

**확인 포인트:** 문서 상태 ACTIVE, `index_jobs.status=COMPLETED`. Qdrant 의 청크 payload `allowed_channel_ids` 에 `c0000000-0000-0000-0000-000000000001` 이 들어가 있어야 합니다.

```bash
docker compose -f docker-compose.dev.yml exec postgres psql -U rag -c \
 "SELECT status, stage, error FROM index_jobs ORDER BY created_at DESC LIMIT 3;"
```

### 5.2 로그인 → 질문 → 스트리밍 답변 (#rag-cloud-ops, THREAD 모드)

1. `http://localhost:3000` → **hong@example.com / `Rag!Assistant2026`** 로그인. 사이드바에 `rag-cloud-ops`, `rag-hr` 두 채널이 보입니다.
2. `#rag-cloud-ops` 에서 `장애 등급별 대응 절차를 알려주세요.` 전송.

**확인 포인트:**
1. 전송 직후(ACK ≤ 2초) 질문 Post + Bot 접수 안내 "질문을 접수했습니다. 근거 문서를 찾는 중…" 표시 (`ack_message_enabled`)
2. 채널이 THREAD 모드이므로 **질문을 root 로 스레드 패널이 자동으로 열리고**, Bot 답변이 스레드 안에서 **토큰 단위로 스트리밍**(streaming 점)
3. 완료 시 답변 본문 아래 **근거 문서 표**(#, 근거 문서, 위치, 발췌 — "사내 문서 RAG 검색") + 👍 도움됨 / 👎 아쉬움 버튼
4. 같은 스레드에서 후속 질문(예: `P1 보고 주기는?`) → 이전 대화를 이어 답변 (동일 scope_key)
5. DB 검증 — 컨테이너 이름은 compose 프로젝트명(디렉터리명)에 따라 달라지므로 `compose exec` 를 씁니다:
```bash
docker compose -f docker-compose.dev.yml exec postgres psql -U rag -c \
 "SELECT status, completed_at - started_at AS dur FROM chat_jobs ORDER BY queued_at DESC LIMIT 2;"
# COMPLETED, 로컬 4B 기준 5~15초 (mock-llm 이면 수 초)
docker compose -f docker-compose.dev.yml exec postgres psql -U rag -c \
 "SELECT scope_key, mode FROM channel_conversations ORDER BY created_at DESC LIMIT 3;"
# 첫 질문과 후속 질문이 같은 c0000000-...-000000000001:<root post id> 1행
```

> 스트리밍 중 WS 가 끊겨도 답변은 유실되지 않습니다 — 최종 본문은 `chat_posts` 의 Bot Post 가 SSOT 이고, 새로고침/재접속 시 DB 기준으로 수렴합니다.

### 5.3 트리거 단어 채널 (#rag-hr, `!rag`)

| 입력 | 기대 |
|---|---|
| `연차 이월 규정 알려줘` (접두어 없음) | 일반 메시지로만 게시, **Bot 응답 없음** (chat_jobs 미생성) |
| `!rag 연차 이월 규정이 어떻게 되나요?` | `!rag` 제거 후 질의, 채널 본문에 `@홍길동 ` 멘션 + 답변 (CHANNEL 모드 · mention_user on) |
| Bot 답변이 달린 스레드에서 `!rag` 없이 후속 질문 | trigger 없이도 후속 질문으로 처리 |

> 인사규정 문서를 올리지 않았다면 `!rag` 질문의 답변은 **근거 부족 안내**가 됩니다(LLM 미호출·스트리밍 없음). 이것도 정상 동작 확인 항목입니다. 근거 있는 답변까지 보려면 §5.1 과 같은 방법으로 `samples/인사규정집.md` 를 카테고리 `인사규정`, 보안등급 `INTERNAL`, ACL `c0000000-0000-0000-0000-000000000002` 로 업로드·색인하세요. (이 문서는 `rag-cloud-ops` 에서는 검색되지 않아야 합니다 — CH-001 격리 대조)

### 5.4 피드백 👍/👎

1. §5.2 답변의 👍 도움됨 클릭 → 카운트 1 반영 (다른 탭/사용자 화면에도 `post.updated` 로 실시간 반영)
2. 같은 답변에 👎 아쉬움 클릭 → **의견 변경**(👍 0 / 👎 1, 재클릭 = upsert)
3. admin-web 피드백 대시보드에서 채널별 집계·👎 답변 목록에 반영 확인

피드백 경로(`POST /api/v1/actions`)는 동기 처리이며 LLM/Queue 를 호출하지 않습니다.

### 5.5 부정 케이스 스모크

| 케이스 | 방법 | 기대 |
|---|---|---|
| 비멤버 채널 비노출 | **kim@example.com** 으로 로그인 (다른 브라우저/시크릿 창) | 사이드바에 `rag-hr` 만 보임 (`rag-cloud-ops` 없음) |
| 비멤버 채널 직접 접근 | kim 으로 `http://localhost:3000/ch/rag-cloud-ops` 입력 | "채널을 찾을 수 없거나 접근 권한이 없습니다." (API 404 — 존재 여부 비노출) |
| 잘못된 비밀번호 | 로그인 시 틀린 비밀번호 | 동일 오류 메시지(사용자 열거 방지), 반복 시 429 (`RATE_LIMIT_LOGIN_PER_MIN`) |
| 위조 피드백 토큰 | 아래 스크립트 | HTTP 401 `INVALID_SIGNATURE` |
| 세션 유지(refresh) | 로그인 상태에서 새로고침 | 로그인 화면 없이 복귀 (access 토큰은 메모리 보관 → refresh 쿠키로 재발급·rotation) |
| 로그아웃 | 로그아웃 후 새로고침 | 로그인 화면 (refresh 세션 폐기) |
| 근거 없는 질문 | `#rag-cloud-ops` 에 "오늘 점심 메뉴 추천" | 근거 부족 안내 (LLM 미호출) |

위조 피드백 토큰 → 401 확인 (브라우저 대신 스크립트로 로그인해 `/api/v1/actions` 직접 호출):

```bash
BOT_POST=$(docker compose -f docker-compose.dev.yml exec -T postgres psql -U rag -tA -c \
  "SELECT post_id FROM messages WHERE role='assistant' ORDER BY created_at DESC LIMIT 1;")

BOT_POST=$BOT_POST uv run python - <<'PY'
import json, os, time, uuid, urllib.error, urllib.request
from rag_common.passwords import compute_prehash

BASE, EMAIL, PW = "http://localhost:8001", "hong@example.com", "Rag!Assistant2026"

def post(path, body, token=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(BASE + path, json.dumps(body).encode(), headers, method="POST")
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")

_, login = post("/api/v1/auth/login", {"email": EMAIL, "prehash": compute_prehash("rag", EMAIL, PW),
                "client_nonce": uuid.uuid4().hex, "timestamp": int(time.time() * 1000)})
status, body = post("/api/v1/actions", {"post_id": os.environ["BOT_POST"], "block_id": "fb",
                    "action_id": "feedback:up", "value": "deadbeef"}, login["access_token"])
print(status, body.get("error", {}).get("code"))   # → 401 INVALID_SIGNATURE
PY
```

### 5.6 Admin Web 수동 확인 (http://localhost:5173)

- `X-Auth-User` = `cklee` — §4 의 `VITE_DEV_AUTH_USER` 기본값이며, 헤더의 사용자 전환(AuthUserSwitcher)으로 바꾸면 localStorage 값이 우선합니다. vite dev 서버가 `/api` → :8003 프록시
- **문서 관리**: 업로드 모달의 **허용 Channel (ACL)** 셀렉터가 Web Chat 채널(`#rag-cloud-ops`, `#rag-hr`) 목록을 보여줌 → 업로드 → 재색인 → CLI 실행(§5.1 2단계) → ACTIVE 전환
- **색인 작업**: admin-api 에 `/index-jobs` 조회 API 가 없어 **화면은 빈 상태가 정상**입니다(`apps/admin-web/README.md` deviations). Job 진행은 DB `index_jobs` 또는 문서 상태로 확인
- **채널 관리**: [채널 만들기] 3단계 위저드(채널 정보 → 동작 설정 → 지식 범위)로 테스트 채널 생성 → 생성 직후 RAG 응답 비활성 상태 → **[멤버] Drawer** 에서 사용자 추가/제거 → RAG 응답 토글 on 시 **활성화 확인 모달**(현재 멤버 수 + 체크 2개) 확인
- **채팅 사용자**: 사용자 생성 → **임시 비밀번호가 1회만 표시**됨(창을 닫으면 재확인 불가) → 그 계정으로 chat-web 로그인 시 비밀번호 변경(`/profile`)으로 유도됨. [비밀번호 재설정] 도 동일
- **대화 작업**: 방금 질문의 Job 상태(COMPLETED)·질문/답변 Post id 표시, "실패만 보기" 필터 (재전송 버튼은 없음 — Bot Post 가 SSOT)
- **피드백**: §5.4 의 👍/👎 반영 확인

---

## 6. 자동화 테스트 실행

전 백엔드가 Python 단일 스택이므로 admin-api·chat-gateway 테스트도 루트 `make test` 에 포함됩니다 — 별도 빌드 도구 호출이 없습니다.

`make` 가 없으면 먼저 설치하세요 (`sudo apt install -y make`).

```bash
make lint && make test                 # ruff + mypy, 전체 pytest
# 기대: 183 passed (Docker 가용 시 실 Qdrant CH-001 포함). Docker 미기동이면 182 passed, 1 skipped (test_ch_qdrant.py)

make test-isolation                    # ★ CH-001~010 — tests/channel-isolation (in-memory fake + 실 Qdrant 1건). 로컬에서도 반드시 green
make test-integration                  # tests/contract(mock-llm SSE ↔ LLMClient.stream 계약) + tests/channel-isolation/test_ch_qdrant.py
                                       #   (testcontainers 실 Qdrant — Docker Desktop 필요, 없으면 skip)

# chat-web 타입체크 + 프로덕션 빌드 (standalone)
make chat-web-build
```

Web Chat 관련 테스트는 PRD ID `FR-WEB-*`/`test_fb_*`/`test_ws_*` 이름을 씁니다 (예: `test_fr_web_004_non_member_post_404`, `test_fb_invalid_token_401`, `test_ws_joins_only_member_channel_rooms`).

Windows/Docker Desktop 주의: testcontainers가 느리면 Docker Desktop → Resources에서 CPU/RAM 상향, WSL 파일시스템(§1.4) 사용 여부 재확인.

### 6.1 미니 성능 체크 (참고치)

locust 가 데모 계정으로 로그인한 뒤 `POST /api/v1/posts` 의 ACK(질문 Post + placeholder 생성) p95 ≤ 2s 를 판정합니다. 기본값은 `-u 50 -r 50 -t 10s` / `--host ${GATEWAY_URL:-http://localhost:8001}` (Makefile 참조).

```bash
# ⚠️ 부하 시험 동안 gateway rate limit 을 충분히 올린 뒤 chat-gateway 를 재기동할 것
#    (.env: RATE_LIMIT_PER_USER_PER_MIN / RATE_LIMIT_PER_CHANNEL_PER_MIN, 50명 동시 로그인이면 RATE_LIMIT_LOGIN_PER_MIN 도)
#    그대로 두면 429 가 실패로 집계된다. 시험 후 원복.
CHAT_EMAIL=hong@example.com CHAT_PASSWORD='Rag!Assistant2026' make perf-chat-burst
#   대상 변경: GATEWAY_URL=http://... make perf-chat-burst  (채널: CHAT_CHANNEL, 기본 rag-cloud-ops)

# 부하 수준을 바꾸려면 locust를 직접 호출
CHAT_EMAIL=hong@example.com CHAT_PASSWORD='Rag!Assistant2026' \
uv run locust -f tests/performance/locustfile.py --headless -u 20 -r 20 -t 10s \
  --host http://localhost:8001
# 생성 p95는 4B 모델 기준 경향만 기록 (운영 수치 아님)
```

---

## 7. (선택) Docker Desktop K8s로 Helm 검증

Settings → Kubernetes → Enable 후. **Namespace 라벨(`rag-platform=true`)과 사전 Secret 이 선행**되어야 Pod 가 뜹니다 — NetworkPolicy 가 라벨로 NS 간 통신을 허용하고, chart 는 Secret 값을 values 에 넣지 않고 파일 마운트(`rag-chat-secrets`)·`secretKeyRef`(`rag-postgresql-secret`)로만 읽습니다.

```bash
# 1) Namespace 4종 + NetworkPolicy 전제 라벨 (라벨이 없으면 NS 간 통신이 전부 차단된다)
for ns in rag-app rag-ai rag-data rag-ingestion; do kubectl create ns $ns; kubectl label ns $ns rag-platform=true; done

# 2) Secret — §3 에서 만든 파일 그대로 (seed-users 가 같은 pepper 파일을 써야 로그인된다)
kubectl -n rag-app create secret generic rag-chat-secrets \
  --from-file=jwt-secret=secrets/rag/jwt-secret \
  --from-file=password-pepper=secrets/rag/password-pepper \
  --from-file=feedback-signing-key=secrets/rag/feedback-signing-key
for ns in rag-app rag-data rag-ingestion; do        # key = password (global.postgres.existingSecret)
  kubectl -n $ns create secret generic rag-postgresql-secret --from-literal=password=rag-dev-only
done
# (선택) Ingress 를 HTTPS 로 켤 때만 — chat/admin 두 호스트 SAN 인증서 (RKE2 가이드 §4.1 참고)
# kubectl -n rag-app create secret tls rag-chat-tls --cert=<crt> --key=<key>

# 3) 이미지 8종 빌드 — Docker Desktop K8s 는 로컬 데몬 이미지를 그대로 쓰므로 push 불필요
#    (apps/*/Containerfile: Python 6종은 리포 루트 컨텍스트, chat-web/admin-web 은 자체 디렉터리 컨텍스트.
#     embedding-api/reranker-api 는 UV_EXTRA=models 기본이라 torch 포함 — 빌드가 오래 걸린다)
TAG=$(git rev-parse --short HEAD)
make build-images REG=local TAG=$TAG                # → local/rag/<app>:$TAG

# 4) 렌더 사전 검증 → 설치
make helm-lint helm-template                        # lint + poc / poc+lab 렌더
helm upgrade --install rag-platform deploy/helm/rag-platform \
  -f deploy/helm/rag-platform/values-poc.yaml \
  -f deploy/helm/rag-platform/values-local.yaml --set global.imageTag=$TAG
```

> **`values-local.yaml` 은 리포에 없습니다.** 리포에는 `values.yaml`(기본) / `values-poc.yaml`(운영) / **`values-lab.yaml`(2-Node RKE2 랩)** 이 있으며, 로컬용은 `values-lab.yaml` 을 복사해 시작하는 것이 가장 빠릅니다 — replica 1, PDB 해제(`pdbMinAvailable: null`), 리소스 축소, `namespaces.create: false`(위 1단계에서 kubectl 로 생성), `migration.enabled: true`(hook Job `rag-db-migrate` 가 install/upgrade 후 `alembic upgrade head`), admin-api `INDEX_JOB_TRIGGER=k8s` + `serviceAccounts.adminApi.create: true`, Ingress(chat/admin host), admin-web appService 까지 이미 되어 있습니다. Secret 은 `appServices.<svc>.secretMount.keys` 로 필요한 키만 `/var/run/secrets/rag` 에 마운트되고 `*_FILE` env 가 자동으로 채워지므로 따로 넣을 것이 없습니다. 로컬에서 바꿀 부분:
> - `global.imageRegistry: local`, `global.imagePullPolicy: Never` — 3단계에서 로컬 데몬에 빌드한 이미지를 그대로 사용
> - `data.qdrant/postgresql/redis.image` — lab 값은 `registry.local:5000/library/*` 이므로 원본(`qdrant/qdrant:v1.12.1`, `postgres:16`, `redis:7`) 또는 로컬 미러로
> - `nodeSelector: {}` — 단일 노드이므로 arch 고정 불필요
> - `vllm.replicas: []` — GPU vLLM 은 chart 밖(§2.2 compose :8010)에서 돌리고, rag-api/worker `extraEnv` 의 `VLLM_API_URL` 을 `http://host.docker.internal:8010/v1` 로
> - `modelStorage.hostPath` / `data.storageClass` / `documentStorage.storageClass` — Docker Desktop 기본 `hostpath` SC 사용 시 storageClass 키를 비워 둔다. 모델을 두지 않으면 embedding/reranker `extraEnv` 의 `EMBEDDING_MOCK`/`RERANKER_MOCK` 을 `"1"` 로
> - `networkPolicy.ingressController` — ingress-nginx 를 설치했다면 그 NS(`namespace`, `podSelector`), 없으면 `ingress.enabled: false` 로 port-forward 사용
> - `networkPolicy.apiServer.cidrs` — Docker Desktop apiserver 주소(`kubectl get endpoints kubernetes`) 로, 또는 `INDEX_JOB_TRIGGER=none` + `serviceAccounts.adminApi.create: false` (그 경우 색인은 §5.1 처럼 수동 실행)
> - chat-gateway `COOKIE_SECURE` — lab 은 자체서명 TLS 전제로 `"true"`. HTTP(port-forward)로만 쓸 경우에만 `"false"`
>
> Web Chat 까지 브라우저로 보려면 `ingress.enabled=true`, `ingress.chatHost=chat.localhost` 등으로 Ingress 를 켜고(ingress-nginx 필요), **WebCrypto 제약상 HTTPS 또는 localhost 호스트**로 접속해야 로그인됩니다.
>
> 렌더 결과는 적용 전에 확인하세요: `helm template ... | kubectl apply --dry-run=client -f -`. 배포 후 검증 8종은 RKE2 가이드 §4.3 을 그대로 씁니다. Seed/채팅 사용자/Qdrant 초기화도 RKE2 가이드(§4.2, port-forward 경유)와 같습니다.

로컬 K8s는 chart 문법/NetworkPolicy 렌더링 검증 용도이며, GPU 스케줄링·성능 검증은 대상이 아닙니다.

---

## 8. 트러블슈팅 (Windows/노트북 특화)

| 증상 | 조치 |
|---|---|
| vLLM `CUDA out of memory` | 화면 출력이 4060 VRAM 점유 중 — `--gpu-memory-utilization 0.80`, `--max-model-len 6144`로 하향. 외장 모니터를 iGPU 출력으로 전환하면 ~0.5GB 확보 |
| vLLM 기동 후 첫 요청 매우 느림 | CUDA graph 워밍업 정상 동작. 2번째 요청부터 판단 |
| `uv sync`가 수 분 소요 | 레포가 `/mnt/c` NTFS에 있음 — §1.4대로 WSL ext4로 이동 |
| 스크립트 실행 시 `\r` 오류 | CRLF 혼입 — `git config core.autocrlf input` 후 재클론 또는 `dos2unix` |
| WSL 메모리 급증으로 Windows 버벅임 | `.wslconfig`의 memory 상한 확인, `wsl --shutdown` 후 재시작 |
| testcontainers 이미지 pull 실패(폐쇄망) | `TESTCONTAINERS_HUB_IMAGE_NAME_PREFIX=harbor.internal/library/` |
| localhost 포트를 Windows 브라우저에서 접근 불가 | WSL2 localhost 포워딩 이상 — `wsl --shutdown` 재시작, 또는 `netsh interface portproxy` 확인 |
| admin-api/chat-gateway 500 (`relation ... does not exist`) | 로컬에서는 Alembic 이 **자동 실행되지 않는다** — §3의 `alembic upgrade head` 를 돌렸는지 확인. `alembic current` 가 `0003_webchat` 이 아니면 미적용 |
| chat-gateway 기동 로그 `startup.jwt_secret_missing` / `startup.password_pepper_missing` / `startup.feedback_signing_key_missing`, 로그인 **503 `AUTH_NOT_CONFIGURED`** | `secrets/rag/*` 파일이 없거나 비어 있음 → fail-closed (빈 키로 서명·해시하지 않음). §3 의 `openssl rand` 3줄 재실행 후 gateway 재기동. 피드백 키가 비면 `/api/v1/actions` 가 전부 401 `INVALID_SIGNATURE`, rag-worker 는 `worker.feedback_signing_key_missing` 로그 + 피드백 버튼 토큰 미부착 |
| 업로드 500 (`No such file or directory` / `Permission denied`) | `DOCUMENT_STORAGE_PATH` 경로 문제 — `.env` 미적용으로 기본값 `/data/documents` 가 쓰였거나 루트가 아닌 곳에서 기동. `.env` 의 `./data/documents` 확인 + §3 `mkdir -p data/documents`, admin-api·parser-indexer 를 리포 루트에서 실행 |
| 색인은 COMPLETED 인데 답변이 항상 근거 부족 | 업로드 시 `allowed_channel_ids`(채널 UUID) 누락 → `document_channel_acl` 없음 → 검색 전 Channel Filter 에 매칭 안 됨. 재업로드 필요(동일 내용은 409 `DUPLICATE_DOCUMENT` → 파일 내용을 한 글자라도 수정). 카테고리/부서/보안등급이 채널 지식 범위와 다른 경우도 동일 증상 |
| 색인 Job `FAILED` (`index_jobs.stage=EMBEDDING`) | embedding-api(:8004) 미기동 — `curl -s localhost:8004/health/ready` 확인 후 §5.1 재색인 → CLI 재실행 |
| 재색인 응답 `error` 가 `TRIGGER_FAILED[k8s]: ...` | 로컬인데 `INDEX_JOB_TRIGGER=k8s` 로 설정됨 — `.env` 를 `none` 으로 되돌리고, 이미 만들어진 Job 은 그 id 로 CLI 실행 (요청 자체는 성공 처리됨) |
| `uv run --package <name>` 이 패키지를 못 찾음 | 패키지명은 디렉터리명이 아니라 `pyproject.toml` 의 `[project] name` — `admin-api`, `rag-api`, `chat-gateway`, `parser-indexer`, `embedding-api`, `reranker-api` |
| `make seed-users` 가 "PASSWORD_PEPPER_FILE 이 필요합니다" | Makefile 은 `.env` 를 읽지 않는다 — `export PASSWORD_PEPPER_FILE=./secrets/rag/password-pepper` 후 재실행 |
| `make seed-users` 가 "채널 없음: rag-cloud-ops" | `make seed` 를 먼저 실행 |
| 로그인 버튼을 눌러도 진행 안 됨 / crypto 오류 | LAN IP·HTTP 로 접속함 — WebCrypto 는 HTTPS/localhost 전용. `http://localhost:3000` 사용 |
| 올바른 비밀번호인데 로그인 401 | gateway 와 `make seed-users` 가 **다른 pepper 파일**을 씀, 또는 `CHAT_WORKSPACE_SLUG` ≠ `NEXT_PUBLIC_WORKSPACE_SLUG` — 같은 값으로 맞추고 `make seed-users` 재실행 |
| 로그인 400 "요청이 만료되었습니다" | 브라우저 PC 와 서버 시계 차이 > `LOGIN_MAX_CLOCK_SKEW_SECONDS`(300s) — WSL 시계 동기화 확인(`date` 로 Windows 시각과 비교, 어긋나면 `wsl --shutdown` 후 재시작) |
| 질문은 게시되는데 답변이 실시간으로 안 뜸(새로고침하면 보임) | WS 연결 실패 — `CHAT_CORS_ORIGINS=http://localhost:3000` 확인, chat-web 을 `NEXT_PUBLIC_WS_URL=http://localhost:8001` 로 기동했는지 확인 (`make chat-web-dev` 는 기본 설정) |
| 질문 후 접수 안내만 남고 답변 없음 | rq worker(`rag-chat`) 미기동 또는 LLM(:8010) 미기동 — worker 로그와 `chat_jobs.status`/`error` 확인 |
| 로그인이 새로고침마다 풀림 | 브라우저가 `localhost:3000` 이 아닌 다른 출처로 REST 호출 중 (refresh 쿠키 SameSite=Strict) — chat-web dev rewrite 경유(`/api`)인지 확인 |
| embedding-api RAM 과다(>6GB) | fp32 로딩 정상 범위는 ~2.5GB. `EMBEDDING_MAX_BATCH` 축소 및 중복 프로세스 확인 |
| 답변이 항상 근거 부족 (색인 전) | §5.1 의 `ingestion.main` 미실행 — 로컬(`INDEX_JOB_TRIGGER=none`)은 업로드만으로 색인되지 않는다. 문서 상태가 `INDEXING` 에 머물러 있으면 해당 Job id 로 CLI 실행 |

---

## 9. 로컬 검증 완료 체크리스트

- [ ] `nvidia-smi` (WSL) — RTX 4060 인식 (또는 GPU 없이 `make mock-llm`)
- [ ] 인프라 3종 + vLLM(4B)/mock-llm 기동, `/v1/models` 응답
- [ ] **Alembic `upgrade head` 수동 실행** (로컬 — K8s 는 hook Job) + `alembic current` = `0003_webchat` 확인
- [ ] Secret 파일 3종(`jwt-secret`, `password-pepper`, `feedback-signing-key`) 생성, `make seed` + `make seed-users` + `make qdrant-init` 완료
- [ ] 전 서비스 health OK (8001/8002/8003/8004/8005/8010) + chat-web :3000
- [ ] `mkdir -p data/documents` + `samples/장애대응매뉴얼.md` 업로드(ACL=채널 UUID, `start_indexing=true`) → `index_jobs` 생성 → `ingestion.main` COMPLETED, 문서 ACTIVE
- [ ] hong 로그인 → `#rag-cloud-ops` 질문 → 접수 안내 2초 내 → 스레드 자동 오픈 + 스트리밍 → 근거 문서 표 → 후속 질문 동일 scope_key
- [ ] `#rag-hr` `!rag` 트리거 / 일반 메시지 무응답
- [ ] 피드백 👍/👎(의견 변경) 반영 + admin-web 피드백 대시보드 반영 / 위조 토큰 401
- [ ] 부정 케이스 통과 (§5.5 — kim 비멤버 채널 비노출·직접 접근 차단, refresh 세션 유지)
- [ ] `make lint`, `make test`(183 passed / Docker 없으면 182 passed, 1 skipped), `make test-integration`(Docker), `make chat-web-build` green
- [ ] **`make test-isolation` (CH-001~010) green**
- [ ] Admin Web 수동 확인 (§5.6 — 채널 위저드·멤버 Drawer·채팅 사용자 임시 비밀번호·문서 ACL)

> 로컬 green 이후 단계: 동일 코드로 DGX/GPU 서버 환경에서 32B 모델 + `make evaluate`(품질) + `make perf-*`(성능 p95) 측정.
