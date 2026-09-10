# 로컬 Laptop 테스트 가이드 — RAG Platform

> 문서 ID: GUIDE-LOCAL-TEST-001 (**v1.2 — 2026-09-10 코드 리뷰 반영**)
> 기준: TDD-RAG-CHATBOT-POC-001 v1.2 + **현행 구현 기준** — 전 서비스 Python 3.12 (uv workspace). admin-api 는 Python(FastAPI + SQLAlchemy + Alembic) — JDK/Gradle 불필요.
> v1.2 변경 요지 (상세: `docs/code-review-2026-09-10.md` §6): v1.1 이 "리포에 없다"고 표시했던 **mock-mattermost(`make mock-mattermost`) · `scripts/sign_feedback.py` · `samples/`** 가 추가됨 · 색인 절차를 "seed 된 가짜 Job 실행"에서 **admin-api 업로드 → `index_jobs` 생성 → CLI 실행**으로 정정 · `make test-integration` 대상 정정 · §7 chart 신규 키(Secret 마운트/PostgreSQL Secret/Ingress) 반영 · 업로드 시 `allowed_channel_ids` 필수(없으면 검색 불가).
> 대상 환경: **i7 13세대 / RAM 64GB / SSD 1.5TB / RTX 4060 8GB / Windows 11 / Docker Desktop**

---

## 0. 이 가이드가 검증하는 범위

| 검증 항목 | 로컬 가능 여부 | 방법 |
|---|---|---|
| Bridge 수신/검증/피드백 파이프라인 | ✅ 완전 | WSL2 + curl 모사 |
| RAG 파이프라인 (Embedding→검색→Rerank→생성) | ✅ 완전 | CPU 모델 + **소형 LLM(GPU)** |
| 문서 파싱/색인 (parser-indexer) | ✅ 완전 | CLI 실행 |
| Admin API (FastAPI) / Admin Web | ✅ 완전 | 로컬 기동 |
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
# uv + Python 3.12 — admin-api 포함 전 백엔드 서비스가 이걸로 돌아간다 (JDK/Gradle 불필요)
curl -LsSf https://astral.sh/uv/install.sh | sh
uv python install 3.12

# Node 20 — admin-web(React/Vite) 전용. WSL에서 실행 권장 (경로/줄바꿈 문제 회피)
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash - && sudo apt install -y nodejs

uv --version
node -v         # v20.x
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

GPU 없이 검증할 땐 vLLM 대신 `make mock-llm`(:8010, OpenAI 호환 고정응답)으로 대체 가능 — 파이프라인/격리 테스트에는 충분합니다.

---

## 3. 설정 / Secret / 시드

```bash
cp .env.example .env
# 로컬 조정 항목만 수정:
#   VLLM_API_URL=http://localhost:8010/v1
#   MAX_CONTEXT_TOKENS=6144
#   LLM_MODEL_PATH=/models/llm/local-4b
#   TOKENIZER_PATH=/models/llm/local-4b
#   DOCUMENT_STORAGE_PATH=./data/documents     (admin-api 업로드 저장 경로 — 미리 mkdir)
#   INDEX_JOB_TRIGGER=none                     (로컬은 K8s 가 없으므로 색인 Job 을 CLI 로 직접 실행 — §5.1)
#   EMBEDDING_MOCK=0 / RERANKER_MOCK=0         (실 모델을 쓰려면 `uv sync --extra models` 후. 미설치면 1 유지 → 결정론적 mock)
mkdir -p data/documents

mkdir -p secrets/mattermost secrets/rag
echo -n "local-dev-outgoing-token" > secrets/mattermost/outgoing-token
python3 -c "import secrets;print(secrets.token_hex(32),end='')" > secrets/rag/feedback-signing-key
echo -n "http://localhost:9099/hooks/cloud-ops" > secrets/mattermost/mattermost-incoming-rag-cloud-ops   # 파일명 = binding.secret_ref
echo -n "http://localhost:9099/hooks/hr"        > secrets/mattermost/mattermost-incoming-rag-hr
chmod 600 secrets/mattermost/* secrets/rag/*

# DB migration — 스키마 소유자는 admin-api의 Alembic
#   (apps/admin-api/src/admin/db/migrations, 리비전 0001_initial → 0002_feedback_enabled)
#   ※ 서비스 기동 시 자동 실행되지 않는다. 아래를 명시적으로 1회 실행할 것
uv run --package admin-api \
  alembic -c apps/admin-api/src/admin/db/migrations/alembic.ini upgrade head
uv run --package admin-api \
  alembic -c apps/admin-api/src/admin/db/migrations/alembic.ini current
# → 0002_feedback_enabled (head)

# 시드 + Qdrant 초기화
make seed && make qdrant-init
```

접속 정보는 `env.py` 가 `admin.core.config.get_settings()` 에서 가져오므로, `.env` 의 `POSTGRES_*` (또는 `DATABASE_URL`)만 맞으면 별도 인자가 필요 없습니다.

> **mock-mattermost** (`tools/mock-mattermost`, `make mock-mattermost`, :9099) 가 Mattermost Incoming Webhook 수신을 흉내냅니다 — `POST /hooks/{id}` 를 받아 `ok` 를 돌려주고 payload 를 로그(JSON 한 줄)와 메모리에 보관하며 `GET /posts?hook_id=cloud-ops` 로 조회할 수 있습니다. 위 secret 파일의 URL 이 이 서버를 가리키므로 rag-worker 의 실제 `deliver()` 경로(재시도·분할 게시 포함)가 그대로 실행됩니다.
> 여기서 만든 `secrets/rag/feedback-signing-key` 는 §5.2 의 `scripts/sign_feedback.py` 가 그대로 읽습니다.

---

## 4. 서비스 기동

uv workspace이므로 **리포 루트에서 `--package` 로 선택 실행**합니다. 서비스마다 `cd` 하면 다음 `cd` 가 상대경로로 깨지므로 아래 형태를 쓰세요. (`make dev` 같은 일괄 타깃은 아직 없습니다 — Makefile 참조.)

```bash
cd ~/work/rag-platform
make install     # uv sync (workspace 전체) — 최초 1회

# [T1] CPU 모델 서빙 — 최초 로딩 1~2분, /health/startup 200 확인
uv run --package embedding-api uvicorn embedding.main:app --port 8004 &
uv run --package reranker-api  uvicorn reranker.main:app  --port 8005 &

# [T2] Bridge + RAG API + Worker
uv run --package mattermost-bridge uvicorn bridge.main:app --port 8001 &
uv run --package rag-api uvicorn rag.main:app --port 8002 &
uv run --package rag-api rq worker rag-chat --url redis://localhost:6379/0 &

# [T3] Admin API (FastAPI — 다른 Python 서비스와 동일한 기동 방식)
uv run --package admin-api uvicorn admin.main:app --port 8003 &
# 확인: curl -s localhost:8003/health/ready | jq .
# OpenAPI: http://localhost:8003/docs   (FastAPI 기본 경로)

# [T3b] mock-mattermost — 답변 게시 수신 (:9099)
make mock-mattermost &

# [T4] Admin Web (uv workspace 제외 — npm)
cd apps/admin-web && npm ci && npm run dev && cd ../..   # http://localhost:5173
```

**기동 상태 일괄 점검** — 전 서비스가 FastAPI라 health 경로가 동일합니다:

```bash
for p in 8001 8002 8003 8004 8005; do
  curl -sf localhost:$p/health/ready >/dev/null && echo "$p OK" || echo "$p FAIL"
done
curl -sf localhost:8010/v1/models >/dev/null && echo "vLLM OK"
curl -sf localhost:9099/health/ready >/dev/null && echo "mock-mattermost OK"
```

예상 리소스(참고): RAM 사용 총 ~13GB (embedding 2.5 + reranker 2 + 나머지 Python 서비스 + 기타), VRAM 6.5GB. 64GB 노트북에서 브라우저/IDE 병행 여유 충분.

---

## 5. 기능 테스트 시나리오 (E2E, Mattermost 없이)

### 5.1 문서 업로드 → 색인 → 질문 → 답변 게시

> seed 의 문서 1건(`장애대응매뉴얼`)은 **파일 실체가 없는 메타데이터**라 색인할 수 없습니다. `samples/` 의 `.md` 를 admin-api 로 업로드해 `index_jobs` 를 만들고, 로컬(`INDEX_JOB_TRIGGER=none`)에서는 그 id 로 parser-indexer CLI 를 직접 실행합니다. (K8s 에서는 `k8s` 모드가 Job 을 자동 생성 — RKE2 가이드 §5.)

```bash
# 1) 업로드 — 필드는 평면 multipart. ★ allowed_channel_ids 를 비우면 색인되어도 어느 채널에서도 검색되지 않는다 (검색 전 Channel Filter)
curl -s -X POST localhost:8003/api/v1/documents -H 'X-Auth-User: cklee' \
  -F 'file=@samples/장애대응매뉴얼.md' -F 'title=장애대응매뉴얼' -F 'category=장애대응' \
  -F 'department=Cloud운영팀' -F 'security_level=INTERNAL' \
  -F 'allowed_channel_ids=channel-001' -F 'start_indexing=true' | tee /tmp/upload.json
JOB_ID=$(jq -r .data.index_job_id /tmp/upload.json)     # index_job_status=PENDING

# 2) 색인 Job 실행 (로컬은 CLI — .env 의 QDRANT_URL/EMBEDDING_API_URL/POSTGRES_* 사용)
uv run --package parser-indexer python -m ingestion.main --index-job-id $JOB_ID
# → PARSING→CHUNKING→EMBEDDING→UPSERTING→VALIDATING, index_job COMPLETED, document ACTIVE
curl -s localhost:8003/api/v1/documents -H 'X-Auth-User: cklee' | jq '.data[] | {title,status}'

# 3) 질문 발송 (Outgoing Webhook 모사)
curl -s -X POST localhost:8001/integrations/mattermost/v1/outgoing \
  -H 'Content-Type: application/json' -d '{
  "token":"local-dev-outgoing-token",
  "team_id":"team-001","team_domain":"cloud-team",
  "channel_id":"channel-001","channel_name":"rag-cloud-ops",
  "user_id":"mmuser-001","user_name":"tester",
  "post_id":"post-'"$(date +%s)"'","root_id":"",
  "text":"장애 등급별 대응 절차를 알려주세요."}'
```

**확인 포인트:**
1. 즉시 응답 `{"text":"질문을 접수했습니다..."}` — 2초 이내
2. `mock-mattermost` 콘솔(또는 `curl -s localhost:9099/posts?hook_id=cloud-ops | jq .`)에 답변 payload — `text`에 `[1]` 인용 + `근거 문서` 목록, `attachments[0].actions`에 👍/👎 버튼 2개
3. DB 검증 — 컨테이너 이름은 compose 프로젝트명(디렉터리명)에 따라 달라지므로 `compose exec` 를 씁니다:
```bash
docker compose -f docker-compose.dev.yml exec postgres psql -U rag -c \
 "SELECT status, completed_at - started_at AS dur FROM chat_jobs ORDER BY queued_at DESC LIMIT 1;"
-- COMPLETED, 로컬 4B 기준 5~15초
```

### 5.2 피드백 버튼 클릭

> `scripts/sign_feedback.py` 는 `mattermost_adapter.feedback_signature`(서명 규약 SSOT)로 sig 를 산출합니다. 키 파일은 `--key-file`(기본 `FEEDBACK_SIGNING_KEY_FILE` → `./secrets/rag/feedback-signing-key`).

```bash
MSG_ID=$(docker compose -f docker-compose.dev.yml exec -T postgres psql -U rag -tA -c \
  "SELECT id FROM messages WHERE role='assistant' ORDER BY created_at DESC LIMIT 1;")
SIG=$(uv run python scripts/sign_feedback.py --message-id $MSG_ID --value UP --key-file secrets/rag/feedback-signing-key)

curl -s -X POST localhost:8001/integrations/mattermost/v1/actions \
  -H 'Content-Type: application/json' -d '{
  "user_id":"mmuser-001","post_id":"p1","channel_id":"channel-001",
  "context":{"action":"feedback","message_id":"'$MSG_ID'","chat_job_id":"x","value":"UP","sig":"'$SIG'"}}'
# → {"ephemeral_text":"피드백이 반영되었습니다. 감사합니다 🙏"}

# 위조 서명 → 401 확인
curl -s -o /dev/null -w "%{http_code}\n" -X POST localhost:8001/integrations/mattermost/v1/actions \
  -H 'Content-Type: application/json' -d '{
  "user_id":"u","post_id":"p","channel_id":"channel-001",
  "context":{"action":"feedback","message_id":"'$MSG_ID'","chat_job_id":"x","value":"UP","sig":"deadbeef"}}'
# → 401
```

### 5.3 부정 케이스 스모크

| 케이스 | 명령 요지 | 기대 |
|---|---|---|
| 잘못된 token | token=wrong | HTTP 401 `INVALID_TOKEN` |
| **빈 token** | token="" | HTTP 401 (fail-closed — Secret 파일이 비어 있어도 통과하지 않음) |
| 미등록 Channel | channel_id=channel-999 | HTTP 403 `CHANNEL_NOT_BOUND` |
| 중복 post_id | 동일 post_id 2회 | 2회째 200 + chat_jobs 1건만 |
| Bot 메시지 루프 | user_name="RAG Assistant" | 200 + job 미생성 |
| 트리거 채널 | channel_id=channel-002, text="!rag 연차는 며칠인가요?" | 접수 후 `!rag` 제거된 질문으로 처리. 트리거 없는 text 는 200 무시. (`samples/인사규정집.md` 를 `allowed_channel_ids=channel-002` 로 업로드해 두면 답변) |
| 격리 (CH-001) | channel-002 에서 "장애 등급별 대응 절차" | 장애대응매뉴얼은 channel-001 전용 → 근거 부족 안내 |
| 근거 없는 질문 | "오늘 점심 메뉴 추천" | "근거를 찾지 못했습니다" 안내 게시 (`SIMILARITY_THRESHOLD` 기본 0.0 이라 검색 0건일 때만 발동) |

### 5.4 Admin Web 수동 확인 (http://localhost:5173)

- 우상단 사용자 버튼에서 `X-Auth-User`=`cklee` 설정(localStorage). vite dev 서버가 `/api` → :8003 프록시
- 문서 업로드(허용 Channel 지정) → 재색인 → CLI 실행(§5.1 2단계) → ACTIVE 전환. Index Jobs 화면은 admin-api 조회 API 가 없어 비어 있음(`apps/admin-web/README.md`)
- Channels: **연결 테스트는 stub(항상 성공)** — 실제 게시 확인은 §5.1 의 mock-mattermost 로
- Chat Jobs: 방금 질문의 단계별 latency 바 표시
- Feedback: 5.2에서 남긴 👍 반영 확인

---

## 6. 자동화 테스트 실행

전 서비스가 Python 단일 스택이므로 admin-api 테스트도 루트 `make test` 에 포함됩니다 — 별도 빌드 도구 호출이 없습니다.

```bash
make lint && make test                 # ruff + mypy, 전체 unit (admin-api 포함)

# Channel 격리 (in-memory fake — Docker 불필요) + Docker 가 필요한 통합 테스트
make test-isolation                    # ★ CH-001~010 — 로컬에서도 반드시 green
make test-integration                  # testcontainers 실 Qdrant(test_ch_qdrant.py) + worker 통합. Docker Desktop 필요
```

> `make test` 는 133 passed, 1 skipped 이 정상입니다 — skip 1건은 Docker 미기동 시 `test_ch_qdrant.py`. `tests/integration`·`tests/mattermost`(contract fixture) 디렉터리는 없으며 `make test-contract` 타깃도 없습니다. Mattermost payload 계약 검증은 `make test` 안의 adapter 단위 테스트가 담당합니다.

Windows/Docker Desktop 주의: testcontainers가 느리면 Docker Desktop → Resources에서 CPU/RAM 상향, WSL 파일시스템(§1.4) 사용 여부 재확인.

### 6.1 미니 성능 체크 (참고치)

```bash
# 기본값은 -u 50 -r 50 -t 10s / --host http://localhost:8001 (Makefile 참조).
# BRIDGE_URL 로만 대상 변경이 가능하며 LOCAL 같은 변수는 없다
make perf-webhook-burst            # ACK p95 ≤ 2s는 로컬에서도 만족해야 정상

# 부하 수준을 바꾸려면 locust를 직접 호출
uv run locust -f tests/performance/locustfile.py --headless -u 20 -r 20 -t 10s \
  --host http://localhost:8001
# 생성 p95는 4B 모델 기준 경향만 기록 (운영 수치 아님)
```

---

## 7. (선택) Docker Desktop K8s로 Helm 검증

Settings → Kubernetes → Enable 후. **NS 라벨과 Secret 4종이 선행**되어야 Pod 가 뜹니다(chart 가 Secret 을 파일로 마운트하고 PostgreSQL 비밀번호도 Secret 에서 읽음).

```bash
for ns in rag-app rag-ai rag-data rag-ingestion; do kubectl create ns $ns; kubectl label ns $ns rag-platform=true; done
kubectl -n rag-app create secret generic rag-bridge-secrets \
  --from-file=outgoing-token=secrets/mattermost/outgoing-token \
  --from-file=feedback-signing-key=secrets/rag/feedback-signing-key
for ns in rag-data rag-app rag-ingestion; do
  kubectl -n $ns create secret generic rag-postgresql-secret --from-literal=password=rag-dev-only
done
kubectl -n rag-app create secret generic mattermost-incoming-rag-cloud-ops --from-literal=url=http://mock-mattermost.rag-app:9099/hooks/cloud-ops
kubectl -n rag-app create secret generic mattermost-incoming-rag-hr        --from-literal=url=http://mock-mattermost.rag-app:9099/hooks/hr

make helm-lint helm-template     # 렌더 사전 검증
helm upgrade --install rag-platform deploy/helm/rag-platform \
  -f deploy/helm/rag-platform/values-poc.yaml \
  -f deploy/helm/rag-platform/values-local.yaml --set global.imageTag=$(git rev-parse --short HEAD)
```

> **`values-local.yaml` 은 리포에 없습니다.** `values-lab.yaml`(2-Node RKE2 랩)을 복사해 시작하세요 — replica 1, PDB 해제, 리소스 축소, `INDEX_JOB_TRIGGER=k8s`, Ingress, mock-mattermost/admin-web 까지 이미 되어 있습니다. 로컬에서 바꿀 부분:
> - `global.imageRegistry` — Docker Desktop 은 로컬 데몬 이미지를 그대로 쓰므로 `make build-images REG=local TAG=...` 후 `imageRegistry: local`, `imagePullPolicy: Never`
> - `nodeSelector: {}` — 단일 노드이므로 arch 고정 불필요
> - `vllm.replicas: []` — GPU vLLM 은 chart 밖(§2.2 compose :8010)에서 돌리고, rag-api/worker `extraEnv` 의 `VLLM_API_URL` 을 `http://host.docker.internal:8010/v1` 로
> - `modelStorage.hostPath` / `data.storageClass` / `documentStorage.storageClass` — Docker Desktop 기본 `hostpath` SC 사용 시 storageClass 키를 비워 둔다
> - `networkPolicy.ingressController` — ingress-nginx 를 설치했다면 그 NS, 없으면 `ingress.enabled: false` 로 port-forward 사용
> - `networkPolicy.apiServer.cidrs` — Docker Desktop apiserver 주소(`kubectl get endpoints kubernetes`) 로, 또는 `INDEX_JOB_TRIGGER=none` + `serviceAccounts.adminApi.create=false`
>
> 렌더 결과는 적용 전에 확인하세요: `helm template ... | kubectl apply --dry-run=client -f -`. 배포 후 검증 8종은 RKE2 가이드 §4.3 을 그대로 씁니다.

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
| admin-api 500 (`relation ... does not exist`) | Alembic이 **자동 실행되지 않는다** — §3의 `alembic upgrade head` 를 돌렸는지 확인. `alembic current` 가 비어 있으면 미적용 |
| 질문이 전부 401 (토큰이 맞는데도) | `MATTERMOST_OUTGOING_TOKEN_SECRET_FILE` 경로의 파일이 없거나 비어 있음 → fail-closed 거부. bridge 기동 로그 `startup.outgoing_token_missing` 확인 |
| 색인은 COMPLETED 인데 "근거를 찾지 못했습니다" | 업로드 시 `allowed_channel_ids` 누락 → `document_channel_acl` 없음 → 검색 필터에 매칭 안 됨. 재업로드(동일 내용은 409 → 파일 한 글자 수정) |
| 색인 Job `FAILED@EMBEDDING` | embedding-api(:8004) 미기동 또는 v1.2 이전 코드(요청 키 `input`/`texts` 불일치). `curl -s localhost:8004/health/ready` |
| 업로드 500 (`No such file or directory: ./data/documents`) | `DOCUMENT_STORAGE_PATH` 디렉터리 미생성 — §3 `mkdir -p data/documents` |
| mock-mattermost 에 아무것도 안 옴, `mattermost_deliveries.status=DEAD_LETTER` | `secrets/mattermost/<secret_ref>` 파일명이 binding 의 `secret_ref`(`mattermost-incoming-rag-cloud-ops`)와 다름, 또는 :9099 미기동 |
| `uv run --package <name>` 이 패키지를 못 찾음 | 패키지명은 디렉터리명이 아니라 `pyproject.toml` 의 `[project] name` — `admin-api`, `rag-api`, `mattermost-bridge`, `parser-indexer`, `embedding-api`, `reranker-api` |
| embedding-api RAM 과다(>6GB) | fp32 로딩 정상 범위는 ~2.5GB. `EMBEDDING_MAX_BATCH` 축소 및 중복 프로세스 확인 |

---

## 9. 로컬 검증 완료 체크리스트

- [ ] `nvidia-smi` (WSL) — RTX 4060 인식
- [ ] 인프라 3종 + vLLM(4B) 기동, `/v1/models` 응답
- [ ] **Alembic `upgrade head` 수동 실행** + `alembic current` = `0002_feedback_enabled` 확인, seed + qdrant-init 완료
- [ ] 전 서비스 health OK (8001/8002/8003/8004/8005/8010)
- [ ] mock-mattermost(:9099) 기동
- [ ] `samples/장애대응매뉴얼.md` 업로드(`allowed_channel_ids=channel-001`) → `index_jobs` 생성 → CLI 색인 COMPLETED → 문서 ACTIVE
- [ ] 질문 → 접수 ACK 2초 내 → mock-mattermost에 답변+버튼 게시
- [ ] 피드백 UP 반영 / 위조 서명 401 (`scripts/sign_feedback.py`)
- [ ] 부정 케이스 8종 통과 (§5.3 — 빈 토큰, 트리거 채널, 격리 포함)
- [ ] `make lint`, `make test`(133 passed, 1 skipped), `make test-integration`(Docker) green
- [ ] **`make test-isolation` (CH-001~010) green**
- [ ] Admin Web 4개 흐름 수동 확인 (§5.4)

> 로컬 green 이후 단계: 동일 코드로 DGX/GPU 서버 환경에서 32B 모델 + `make evaluate`(품질) + `make perf-*`(성능 p95) 측정.
