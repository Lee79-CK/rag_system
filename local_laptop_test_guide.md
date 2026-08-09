# 로컬 Laptop 테스트 가이드 — RAG Platform

> 문서 ID: GUIDE-LOCAL-TEST-001 (v1.1 — admin-api Python 정정)
> 기준: TDD-RAG-CHATBOT-POC-001 v1.3 + **현행 구현 기준** — 전 서비스 Python 3.12 (uv workspace)
> 정정(v1.1): TDD v1.3 문서는 admin-api를 Java 21 Spring Boot로 기술하지만, **구현된 `apps/admin-api` 는 Python(FastAPI + SQLAlchemy + Alembic)** 입니다. 이 가이드는 구현을 따릅니다. JDK/Gradle은 필요 없습니다.
> 대상 환경: **i7 13세대 / RAM 64GB / SSD 1.5TB / RTX 4060 8GB / Windows 11 / Docker Desktop**

---

## 0. 이 가이드가 검증하는 범위

| 검증 항목 | 로컬 가능 여부 | 방법 |
|---|---|---|
| Bridge 수신/검증/피드백 파이프라인 | ✅ 완전 | WSL2 + curl 모사 |
| RAG 파이프라인 (Embedding→검색→Rerank→생성) | ✅ 완전 | CPU 모델 + **소형 LLM(GPU)** |
| 문서 파싱/색인 (parser-indexer) | ✅ 완전 | CLI 실행 |
| Admin API (FastAPI) / Admin Web | ✅ 완전 | 로컬 기동 |
| Channel 격리 (CH-001~010) | ✅ 완전 | testcontainers |
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

mkdir -p secrets/mattermost secrets/rag
echo -n "local-dev-outgoing-token" > secrets/mattermost/outgoing-token
python3 -c "import secrets;print(secrets.token_hex(32),end='')" > secrets/rag/feedback-signing-key
echo -n "http://localhost:9099/hooks/local" > secrets/mattermost/mattermost-incoming-rag-cloud-ops
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

> **mock-mattermost는 아직 리포에 없습니다.** `tools/` 에는 `mock-llm`, `evaluation` 만 있고 `make mock-mattermost` 타깃도 없습니다. §5의 "게시 결과 확인"은 현재 두 가지로 대체합니다.
> - `secrets/mattermost/mattermost-incoming-rag-cloud-ops` 를 임시 수신 엔드포인트로 지정하고 직접 확인 (예: `uv run python -m http.server 9099` 로는 POST 본문을 볼 수 없으므로 간단한 echo 서버 필요)
> - 또는 DB에서 직접 확인 — `messages` 테이블의 assistant 메시지 본문과 `chat_jobs.status` (§5.1의 SQL)

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

# [T4] Admin Web (uv workspace 제외 — npm)
cd apps/admin-web && npm ci && npm run dev && cd ../..   # http://localhost:5173
```

**기동 상태 일괄 점검** — 전 서비스가 FastAPI라 health 경로가 동일합니다:

```bash
for p in 8001 8002 8003 8004 8005; do
  curl -sf localhost:$p/health/ready >/dev/null && echo "$p OK" || echo "$p FAIL"
done
curl -sf localhost:8010/v1/models >/dev/null && echo "vLLM OK"
```

예상 리소스(참고): RAM 사용 총 ~13GB (embedding 2.5 + reranker 2 + 나머지 Python 서비스 + 기타), VRAM 6.5GB. 64GB 노트북에서 브라우저/IDE 병행 여유 충분.

---

## 5. 기능 테스트 시나리오 (E2E, Mattermost 없이)

### 5.1 질문 → 답변 게시

```bash
# 사전: 샘플 문서 색인 (루트에서 --package 로 실행)
uv run --package parser-indexer python -m ingestion.main \
  --index-job-id 01000000-0000-0000-0000-000000000001

# 질문 발송 (Outgoing Webhook 모사)
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
2. `mock-mattermost` 콘솔에 답변 payload 출력 — `text`에 근거 문서 목록, `attachments[0].actions`에 👍/👎ボ튼 2개
3. DB 검증 — 컨테이너 이름은 compose 프로젝트명(디렉터리명)에 따라 달라지므로 `compose exec` 를 씁니다:
```bash
docker compose -f docker-compose.dev.yml exec postgres psql -U rag -c \
 "SELECT status, completed_at - started_at AS dur FROM chat_jobs ORDER BY queued_at DESC LIMIT 1;"
-- COMPLETED, 로컬 4B 기준 5~15초
```

### 5.2 피드백 버튼 클릭

> **`scripts/sign_feedback.py` 는 아직 리포에 없습니다** (`scripts/` 에는 `export_openapi.py`, `measure_latency.py`, `seed_dev.sql` 만 존재). 아래 `SIG` 계산은 서명 규약(HMAC)에 맞춰 직접 산출하거나 해당 스크립트를 먼저 추가해야 합니다. 서명 로직은 bridge의 피드백 검증 코드가 SSOT입니다.

```bash
MSG_ID=$(docker compose -f docker-compose.dev.yml exec -T postgres psql -U rag -tA -c \
  "SELECT id FROM messages WHERE role='assistant' ORDER BY created_at DESC LIMIT 1;")
SIG=$(uv run python scripts/sign_feedback.py --message-id $MSG_ID --value UP)

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
| 잘못된 token | token=wrong | HTTP 401 |
| 미등록 Channel | channel_id=channel-999 | HTTP 403 |
| 중복 post_id | 동일 post_id 2회 | 2회째 200 + chat_jobs 1건만 |
| Bot 메시지 루프 | user_name="RAG Assistant" | 200 + job 미생성 |
| 근거 없는 질문 | "오늘 점심 메뉴 추천" | "근거를 찾지 못했습니다" 안내 게시 |

### 5.4 Admin Web 수동 확인 (http://localhost:5173)

- 문서 업로드 → 색인 Job 진행 스테퍼 → ACTIVE 전환
- Channels: 연결 테스트(mock-mattermost 수신 확인) → 활성화 확인 모달
- Chat Jobs: 방금 질문의 단계별 latency 바 표시
- Feedback: 5.2에서 남긴 👍 반영 확인

---

## 6. 자동화 테스트 실행

전 서비스가 Python 단일 스택이므로 admin-api 테스트도 루트 `make test` 에 포함됩니다 — 별도 빌드 도구 호출이 없습니다.

```bash
make lint && make test                 # ruff + mypy, 전체 unit (admin-api 포함)

# 통합 + Channel 격리 (Docker Desktop 위 testcontainers)
make test-integration
make test-isolation                    # ★ CH-001~010 — 로컬에서도 반드시 green
```

> `make test-contract` 는 Makefile에 없는 타깃입니다 (`tests/` 에도 contract 디렉터리 없음). Mattermost payload 계약 검증은 현재 `make test` 안의 adapter 단위 테스트가 담당합니다.

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

Settings → Kubernetes → Enable 후:

```bash
kubectl create ns rag-app
kubectl -n rag-app create secret generic rag-bridge-secrets \
  --from-file=outgoing-token=secrets/mattermost/outgoing-token \
  --from-file=feedback-signing-key=secrets/rag/feedback-signing-key

helm upgrade --install rag-platform deploy/helm/rag-platform \
  -f deploy/helm/rag-platform/values-poc.yaml \
  -f deploy/helm/rag-platform/values-local.yaml --namespace rag-app
```

> **`values-local.yaml` 은 아직 없습니다.** 리포에는 `values.yaml`(기본) / `values-poc.yaml`(운영) / **`values-lab.yaml`(2-Node RKE2 랩)** 이 있습니다. 로컬용을 만들 때는 `values-lab.yaml` 을 복사해 시작하는 것이 가장 빠릅니다 — replica 1, PDB 해제(`pdbMinAvailable: null`), 리소스 축소, `extraEnv` 로 서비스 URL 주입까지 이미 되어 있습니다. 로컬에서 바꿀 부분은 대체로 셋뿐입니다.
> - `nodeSelector: {}` — 단일 노드이므로 arch 고정 불필요
> - `vllm.replicas: []` — GPU vLLM은 chart 밖(§2.2 compose :8010)에서 돌리고, `VLLM_API_URL` 을 `http://host.docker.internal:8010/v1` 로
> - `modelStorage.hostPath` / `data.storageClass` — Docker Desktop의 기본 `hostpath` SC 사용 시 storageClass 키를 비워 둔다
>
> 렌더 결과는 적용 전에 확인하세요: `helm template ... | kubectl apply --dry-run=client -f -`

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
| `uv run --package <name>` 이 패키지를 못 찾음 | 패키지명은 디렉터리명이 아니라 `pyproject.toml` 의 `[project] name` — `admin-api`, `rag-api`, `mattermost-bridge`, `parser-indexer`, `embedding-api`, `reranker-api` |
| embedding-api RAM 과다(>6GB) | fp32 로딩 정상 범위는 ~2.5GB. `EMBEDDING_MAX_BATCH` 축소 및 중복 프로세스 확인 |

---

## 9. 로컬 검증 완료 체크리스트

- [ ] `nvidia-smi` (WSL) — RTX 4060 인식
- [ ] 인프라 3종 + vLLM(4B) 기동, `/v1/models` 응답
- [ ] **Alembic `upgrade head` 수동 실행** + `alembic current` = `0002_feedback_enabled` 확인, seed + qdrant-init 완료
- [ ] 전 서비스 health OK (8001/8002/8003/8004/8005/8010)
- [ ] 질문 → 접수 ACK 2초 내 → mock-mattermost에 답변+버튼 게시
- [ ] 피드백 UP 반영 / 위조 서명 401
- [ ] 부정 케이스 5종 통과 (§5.3)
- [ ] `make lint`, `make test`(admin-api 포함), `make test-integration` green
- [ ] **`make test-isolation` (CH-001~010) green**
- [ ] Admin Web 4개 흐름 수동 확인 (§5.4)

> 로컬 green 이후 단계: 동일 코드로 DGX/GPU 서버 환경에서 32B 모델 + `make evaluate`(품질) + `make perf-*`(성능 p95) 측정.
