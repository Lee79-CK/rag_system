# 로컬 2-Node RKE2 클러스터 테스트 가이드 — RAG Platform

> 문서 ID: GUIDE-LOCAL-K8S-TEST-001 (v1.0)
> 기준: TDD-RAG-CHATBOT-POC-001 v1.3 (admin-api = Java 21 Spring Boot, 그 외 Python 3.12)
> 대상 환경:
> - **Master**: Lenovo ThinkStation P3 Tower Gen 2 — Core Ultra 7 265 (x86_64), RAM 128GB, RTX A400 4GB, NVMe 1TB + HDD 4TB/2TB, Ubuntu 24.04
> - **Worker**: Lenovo ThinkStation PGX (NVIDIA DGX Spark OEM) — GB10 Grace Blackwell (**ARM64/aarch64**), 통합 메모리 128GB, SSD 4TB
> - RKE2 설치 완료 (P3=server, PGX=agent), 노드 간 2.5GbE

---

## 0. 이 환경이 검증하는 범위 (노트북 가이드와의 차이)

| 검증 항목 | 가능 여부 | 비고 |
|---|---|---|
| Helm 배포 / NetworkPolicy / Probe 등 K8s 매니페스트 전체 | ✅ | **PoC 배포와 동일 방식** — 이 환경의 최대 가치 |
| RAG 파이프라인 전체 (E2E) | ✅ | Ingress 경유 |
| **답변 품질 평가 (Qwen3-32B)** | ✅ | PGX 통합 메모리 128GB — 32B FP8/4bit 여유 구동 |
| `make evaluate` 100문항 | ✅ | LLM-judge 포함 |
| Channel 격리 (CH-001~010) | ✅ | 클러스터 내 실행 |
| 성능 목표 수치 (p95 30s @ 동시 10~15) | ⚠️ 참고치 | GB10 메모리 대역폭(~273GB/s) 특성상 decode 속도는 운영 GPU(H100 등)와 다름. **동시 4~8 기준 경향 측정** |
| GPU 2장 이중화 (vLLM ×2) | ❌ | GPU 노드 1대 — replica 1로 축소 |

**아키텍처 핵심 제약** — 이 클러스터는 이기종(x86_64 + aarch64)입니다:

| 구분 | 배치 노드 | 이유 |
|---|---|---|
| vLLM (Qwen3-32B) | **PGX (arm64)** | GPU/통합 메모리. NVIDIA ARM64 컨테이너 사용 |
| 그 외 전부 (bridge, rag, admin, embedding, reranker, qdrant, pg, redis, indexer) | **P3 (amd64)** | x86 단일 아키텍처로 이미지 빌드 단순화. Core Ultra 7 + 128GB로 충분 |
| P3의 RTX A400 4GB | **미사용** | LLM 부적합(4GB). GPU Operator 설치 대상에서 제외 |

> 이 배치 전략 덕분에 **multi-arch 이미지 빌드가 불필요**합니다. 앱 이미지는 amd64만 빌드하고, vLLM은 NVIDIA 제공 arm64 이미지를 그대로 사용합니다. (추후 PGX의 Grace CPU 20코어를 embedding 등에 활용하려면 buildx multi-arch로 확장 — §9 참고)

---

## 1. 클러스터 준비

### 1.1 노드 상태 확인 (P3에서)

```bash
export KUBECONFIG=/etc/rancher/rke2/rke2.yaml   # 또는 ~/.kube/config 복사
kubectl get nodes -o wide
# NAME   STATUS  ROLES                       ARCH    INTERNAL-IP
# p3     Ready   control-plane,etcd,master   amd64   192.168.x.10
# pgx    Ready   <none>                      arm64   192.168.x.11

kubectl get nodes -o custom-columns='NAME:.metadata.name,ARCH:.status.nodeInfo.architecture,CPU:.status.capacity.cpu,MEM:.status.capacity.memory'
```

### 1.2 노드 라벨/테인트 — 배치 전략 고정

```bash
# 역할 라벨
kubectl label node p3  ragplatform.io/tier=app   --overwrite
kubectl label node pgx ragplatform.io/tier=llm   --overwrite

# PGX를 LLM 전용으로 보호 (일반 워크로드 유입 차단)
kubectl taint node pgx dedicated=llm:NoSchedule --overwrite
```

이후 모든 앱 chart의 values에 `nodeSelector: {kubernetes.io/arch: amd64}` 를, vLLM에는 `nodeSelector: {ragplatform.io/tier: llm}` + toleration을 지정합니다 (§5).

### 1.3 PGX GPU 활성화 (GPU Operator)

DGX Spark 계열은 드라이버가 DGX OS/베이스 이미지에 포함되므로 Operator는 **driver 설치 비활성** 모드로 배포합니다.

```bash
# PGX 로컬에서 드라이버/CUDA 확인
nvidia-smi     # GB10, 통합 메모리 표시

# P3(kubectl)에서 GPU Operator 설치 — arm64 지원 버전
helm repo add nvidia https://helm.ngc.nvidia.com/nvidia && helm repo update
helm upgrade --install gpu-operator nvidia/gpu-operator \
  -n gpu-operator --create-namespace \
  --set driver.enabled=false \
  --set toolkit.enabled=true

# 확인: PGX에 nvidia.com/gpu allocatable 등장
kubectl describe node pgx | grep -A3 'Allocatable' | grep nvidia
# nvidia.com/gpu: 1
```

RKE2는 containerd 사용 — GPU Operator의 toolkit이 containerd config를 자동 패치합니다. 수동 설정이 필요하면 `/var/lib/rancher/rke2/agent/etc/containerd/config.toml.tmpl`에 nvidia runtime을 추가 후 `systemctl restart rke2-agent`.

### 1.4 스토리지 전략 (P3 디스크 3개 활용)

| 용도 | 위치 | 방식 |
|---|---|---|
| etcd / RKE2 | NVMe 1TB (기본) | 그대로 |
| PostgreSQL / Qdrant / Redis PVC | **NVMe 1TB** `/data/fast` | local-path (성능 필수) |
| 문서 원본(NFS 대체) / 이미지 레지스트리 | **HDD 4TB** `/data/bulk` | local-path 별도 클래스 |
| 모델 아티팩트 | PGX SSD 4TB `/models` (vLLM용) + P3 `/data/bulk/models` (embedding/reranker용) | hostPath 마운트 |

```bash
# P3에서 디스크 마운트 (예: HDD 4TB = /dev/sda)
sudo mkfs.ext4 /dev/sda1 && sudo mkdir -p /data/bulk && \
  echo '/dev/sda1 /data/bulk ext4 defaults 0 2' | sudo tee -a /etc/fstab && sudo mount -a
sudo mkdir -p /data/fast   # NVMe 여유 공간 사용

# local-path-provisioner 2개 StorageClass 구성 (fast=/data/fast, bulk=/data/bulk)
kubectl apply -f deploy/k8s/local-path-fast.yaml
kubectl apply -f deploy/k8s/local-path-bulk.yaml
kubectl get sc
# local-fast (default), local-bulk
```

> DB류 PVC를 HDD에 두면 Qdrant 검색 p95 1초 목표가 로컬에서도 깨집니다. **fast(NVMe)/bulk(HDD) 분리를 반드시 유지**하세요.

### 1.5 프라이빗 레지스트리 (P3, HDD)

폐쇄망 Harbor를 모사하고 PGX가 이미지를 당겨갈 수 있도록 P3에 registry를 둡니다.

```bash
docker run -d --restart=always --name registry -p 5000:5000 \
  -v /data/bulk/registry:/var/lib/registry registry:2

# 양쪽 노드 모두: /etc/rancher/rke2/registries.yaml
sudo tee /etc/rancher/rke2/registries.yaml << 'EOF'
mirrors:
  "registry.local:5000":
    endpoint: ["http://192.168.x.10:5000"]
configs:
  "registry.local:5000":
    tls: { insecure_skip_verify: true }
EOF
sudo systemctl restart rke2-server   # P3
sudo systemctl restart rke2-agent    # PGX
```

---

## 2. 모델 아티팩트 배치

### 2.1 PGX — LLM (Qwen3-32B 실물 구동)

통합 메모리 128GB이므로 32B FP8(~34GB) 또는 AWQ 4bit(~20GB)가 KV cache 포함 여유 있게 적재됩니다. **TDD §8.2 운영 인자를 그대로 사용할 수 있는 것이 이 환경의 최대 장점입니다.**

```bash
# PGX에서
sudo mkdir -p /models/llm && sudo chown $USER /models
hf download Qwen/Qwen3-32B-FP8 --local-dir /models/llm/main   # 또는 반입 아티팩트 복사
sha256sum -c /models/llm/main/SHA256SUMS 2>/dev/null || true
```

### 2.2 P3 — Embedding / Reranker (CPU, amd64)

```bash
# P3에서
sudo mkdir -p /data/bulk/models && sudo chown $USER /data/bulk/models
hf download BAAI/bge-m3             --local-dir /data/bulk/models/embedding/bge-m3
hf download BAAI/bge-reranker-v2-m3 --local-dir /data/bulk/models/reranker/bge-reranker-v2-m3
```

---

## 3. 이미지 빌드 및 푸시 (P3, amd64 전용)

```bash
cd ~/work/rag-platform
export TAG=$(git rev-parse --short HEAD)
export REG=registry.local:5000

# Python 서비스 5종 + parser-indexer (amd64 — P3 로컬 빌드이므로 자동)
for app in mattermost-bridge rag-api embedding-api reranker-api parser-indexer; do
  docker build -f apps/$app/Containerfile -t $REG/rag/$app:$TAG . && docker push $REG/rag/$app:$TAG
done

# admin-api (Spring Boot / Java 21) — bootBuildImage 또는 Containerfile
cd apps/admin-api && ./gradlew bootJar && \
  docker build -t $REG/rag/admin-api:$TAG . && docker push $REG/rag/admin-api:$TAG && cd ../..

# admin-web
docker build -f apps/admin-web/Containerfile -t $REG/rag/admin-web:$TAG apps/admin-web && \
  docker push $REG/rag/admin-web:$TAG
```

vLLM은 빌드하지 않고 **NVIDIA 제공 arm64 이미지**를 미러링합니다:

```bash
# DGX Spark 지원 vLLM 이미지 (NGC) — arm64 태그 확인 후 미러
docker pull --platform linux/arm64 nvcr.io/nvidia/vllm:latest
docker tag nvcr.io/nvidia/vllm:latest $REG/ai/vllm-arm64:latest
docker push $REG/ai/vllm-arm64:latest
```

> **검증 습관**: 배포 전 `docker manifest inspect $REG/rag/rag-api:$TAG | grep architecture` — 이기종 클러스터에서 `exec format error`의 90%는 아키텍처 불일치입니다.

---

## 4. 배포 (Helm, values-lab.yaml)

`deploy/helm/rag-platform/values-lab.yaml` 핵심 오버라이드:

```yaml
global:
  imageRegistry: registry.local:5000
  imageTag: <git-sha>

# 모든 앱 공통 — P3(amd64) 고정
appNodeSelector: &appNode
  kubernetes.io/arch: amd64

mattermost-bridge: { replicaCount: 1, nodeSelector: *appNode }
rag-api:           { replicaCount: 1, workerReplicaCount: 2, nodeSelector: *appNode }
admin-api:         { replicaCount: 1, nodeSelector: *appNode }   # Spring Boot :8003, JVM -Xmx1g
admin-web:         { replicaCount: 1, nodeSelector: *appNode }
embedding-api:
  nodeSelector: *appNode
  modelHostPath: /data/bulk/models/embedding/bge-m3
reranker-api:
  nodeSelector: *appNode
  modelHostPath: /data/bulk/models/reranker/bge-reranker-v2-m3

vllm:
  replicas: 1                      # GPU 노드 1대 — 운영(2)과 다름을 기록
  image: registry.local:5000/ai/vllm-arm64:latest
  nodeSelector: { ragplatform.io/tier: llm }
  tolerations: [{ key: dedicated, value: llm, effect: NoSchedule }]
  resources: { limits: { nvidia.com/gpu: 1 } }
  modelHostPath: /models/llm/main
  args:                            # TDD §8.2 운영값 유지 가능!
    maxModelLen: 16384
    gpuMemoryUtilization: 0.90
    maxNumSeqs: 8                  # 운영 16 → Spark 대역폭 고려 8

postgresql: { primary: { nodeSelector: *appNode, persistence: { storageClass: local-fast, size: 50Gi } } }
redis:      { master:  { nodeSelector: *appNode, persistence: { storageClass: local-fast } } }
qdrant:     { nodeSelector: *appNode, persistence: { storageClass: local-fast, size: 100Gi } }

documentStorage: { storageClass: local-bulk, size: 500Gi }   # 문서 원본 PVC
```

### 4.1 Secret 생성 및 설치

```bash
kubectl create ns rag-app rag-ai rag-data rag-ingestion

kubectl -n rag-app create secret generic rag-bridge-secrets \
  --from-literal=outgoing-token='lab-outgoing-token' \
  --from-literal=feedback-signing-key="$(python3 -c 'import secrets;print(secrets.token_hex(32),end="")')"
kubectl -n rag-app create secret generic mattermost-incoming-rag-cloud-ops \
  --from-literal=url='http://mock-mattermost.rag-app.svc:9099/hooks/local'

helm dependency update deploy/helm/rag-platform
helm upgrade --install rag-platform deploy/helm/rag-platform \
  -f deploy/helm/rag-platform/values-lab.yaml --set global.imageTag=$TAG

# 상태 확인 — vLLM은 32B 로딩에 최대 10분 (startupProbe 설계 범위)
kubectl get pods -A -l app.kubernetes.io/part-of=rag-platform -o wide
kubectl -n rag-ai logs -f deploy/vllm-llm-0 | grep -i "loading\|ready"
```

`-o wide`로 **배치 검증**: vLLM만 pgx, 나머지 전부 p3에 스케줄되었는지 확인합니다.

### 4.2 DB Migration / Seed / Qdrant 초기화

```bash
# Flyway는 admin-api 기동 시 자동 실행 (spring.flyway.enabled=true) — 로그 확인
kubectl -n rag-app logs deploy/admin-api | grep -i flyway

# Seed + Qdrant collection (Job 또는 port-forward)
kubectl -n rag-data port-forward svc/postgresql 5432:5432 &
kubectl -n rag-data port-forward svc/qdrant 6333:6333 &
make seed && make qdrant-init
```

### 4.3 Ingress (RKE2 내장 ingress-nginx)

```bash
kubectl -n rag-app get ingress
# rag.lab.local     → bridge(/integrations), admin-api(/api), admin-web(/)
echo "192.168.x.10 rag.lab.local" | sudo tee -a /etc/hosts   # 접속 PC에도 등록
```

---

## 5. E2E 기능 테스트 (Ingress 경유)

노트북 가이드 §5와 동일 시나리오를 **클러스터 외부에서** 수행합니다 — 이 환경에서는 NetworkPolicy·Ingress 경로까지 함께 검증됩니다.

```bash
# 1) 샘플 문서 색인 — admin-api가 K8s Job 생성 (rag-ingestion NS)
curl -s -X POST http://rag.lab.local/api/v1/documents \
  -H 'X-Auth-User: cklee' -F 'file=@samples/장애대응매뉴얼.pdf' \
  -F 'meta={"title":"장애대응매뉴얼","category":"장애대응","security_level":"INTERNAL","allowed_channel_ids":["channel-001"]};type=application/json'
kubectl -n rag-ingestion get jobs -w    # parser-indexer Job COMPLETED 확인

# 2) 질문 발송
curl -s -X POST http://rag.lab.local/integrations/mattermost/v1/outgoing \
  -H 'Content-Type: application/json' -d '{
  "token":"lab-outgoing-token","team_id":"team-001","team_domain":"cloud-team",
  "channel_id":"channel-001","channel_name":"rag-cloud-ops",
  "user_id":"mmuser-001","user_name":"tester",
  "post_id":"post-'"$(date +%s)"'","root_id":"","text":"장애 등급별 대응 절차를 알려주세요."}'

# 3) mock-mattermost 수신 확인 (답변 본문 + 👍/👎 attachment)
kubectl -n rag-app logs deploy/mock-mattermost --tail=50

# 4) 피드백 클릭 + 위조 서명 401 — 노트북 가이드 §5.2와 동일 (URL만 rag.lab.local)
# 5) 부정 케이스 5종 — 노트북 가이드 §5.3과 동일
```

**32B 실물이므로 답변 품질을 직접 확인**: 근거 citation 정합성, 한국어 자연스러움, 무근거 질문의 안전 응답을 수동 채점해 두면 §7 자동 평가와 대조할 수 있습니다.

---

## 6. 자동화 테스트

```bash
make lint && make test && make test-contract
cd apps/admin-api && ./gradlew test && cd ../..

# 통합/격리 — 클러스터 인프라를 직접 사용 (port-forward 상태에서)
make test-integration
make test-isolation        # ★ CH-001~010 — 배포 Gate. 실 Qdrant+PG 대상
```

이 환경 특화 검증 항목:

| 항목 | 방법 | 기대 |
|---|---|---|
| NetworkPolicy default-deny | `kubectl -n rag-app exec deploy/admin-api -- curl -m3 qdrant.rag-data:6333` | **차단** (admin-api→qdrant는 비허용 경로) |
| vLLM 재기동 복원력 | `kubectl -n rag-ai rollout restart deploy/vllm-llm-0` 후 질문 | 로딩 중 FAILED 답변 오류 게시 → 복구 후 정상 |
| Worker 장애 | worker pod 삭제 → 처리 중 Job | RQ 재큐잉으로 재처리, 중복 게시 없음 |
| 노드 격리 | PGX cordon 후 앱 재배포 | 앱은 전부 P3에서 정상 (vLLM만 Pending) |

---

## 7. RAG 품질 평가 및 성능 참고치

### 7.1 품질 평가 — 이 환경의 본론

```bash
make evaluate    # 100문항, 실 32B + 실 파이프라인. LLM-judge도 내부 vLLM 사용
# reports/eval_YYYYMMDD.md — Recall@10 ≥85%, Citation Precision ≥90%,
# Faithfulness ≥85%, 무근거 안전응답 ≥90%, 격리 100% 목표 대비 판정
```

파라미터 튜닝 루프(README §8.3)를 이 클러스터에서 그대로 수행합니다. Admin Web(`http://rag.lab.local`) Settings 변경 → 재평가 → diff. **`SIMILARITY_THRESHOLD` 확정을 이 환경에서 완료**하는 것을 권장합니다 (TDD §7.2.3의 숙제).

### 7.2 성능 — 해석 주의

```bash
make perf-webhook-burst   # ACK p95 ≤ 2s — 이 환경에서도 그대로 유효한 목표
make perf-peak CONCURRENCY=6
```

| 지표 | 목표(운영) | 이 환경 해석 |
|---|---|---|
| ACK p95 | ≤ 2s | **그대로 판정** (LLM 무관 경로) |
| 검색 p95 | ≤ 1s | NVMe Qdrant면 그대로 판정 |
| 답변 p95 | ≤ 30s @ 동시 10 | GB10 대역폭 특성상 **동시 4~8에서 경향만** 기록. 절대치로 합불 판정 금지 |
| 동시 15 | NFR-PERF-004 | 미검증 — 운영 GPU 환경 몫 |

---

## 8. 트러블슈팅 (이기종 클러스터 특화)

| 증상 | 조치 |
|---|---|
| Pod `exec format error` CrashLoop | amd64 이미지가 PGX에, 또는 반대로 스케줄됨 — nodeSelector 누락 확인, `kubectl get pod -o wide`로 노드 확인 |
| vLLM Pod가 P3로 스케줄 시도 | taint/toleration·nodeSelector 확인. P3에는 nvidia.com/gpu 리소스가 없어 Pending이 정상 |
| PGX에서 `nvidia.com/gpu: 0` | GPU Operator toolkit Pod(pgx) 로그 확인, containerd 재시작. driver.enabled=false 유지 |
| vLLM OOM/성능 급락 | 통합 메모리를 OS·타 프로세스와 공유 — PGX에 다른 워크로드 금지(taint 유지), `gpu-memory-utilization` 0.85로 하향 |
| Qdrant 검색 1s 초과 | PVC가 local-bulk(HDD)에 생성됨 — `kubectl get pvc -n rag-data`로 StorageClass 확인 후 local-fast로 재생성 |
| PGX가 이미지 pull 실패 | PGX의 `/etc/rancher/rke2/registries.yaml` 누락 또는 rke2-agent 미재시작 |
| 노드 간 호출 간헐 지연 | 2.5GbE 협상 확인 `ethtool enpXs0 \| grep Speed`, MTU 불일치 확인 |
| admin-api Flyway 실패 | PG 기동 순서 — admin-api에 initContainer(pg wait) 확인, `kubectl -n rag-app logs deploy/admin-api` |
| RKE2 재부팅 후 워크로드 미복귀 | `systemctl status rke2-server`(P3)/`rke2-agent`(PGX), PGX 절전 설정 비활성 |

---

## 9. 확장 과제 (선택)

- **PGX Grace CPU 활용**: embedding/reranker를 arm64로도 빌드(`docker buildx build --platform linux/amd64,linux/arm64`)해 PGX에 배치하면 색인 처리량 향상. 단 taint 정책 재설계 필요.
- **vLLM 2-replica 모사**: PGX 단일 GPU에서 MPS/시간분할은 비권장 — HA 시나리오(NFR-HA-002)는 순차 재기동 테스트로 대체.
- **모니터링**: kube-prometheus-stack + TDD §12 metric 대시보드를 이 클러스터에 먼저 구축해 두면 PoC 환경 이관이 빠릅니다.

---

## 10. 검증 완료 체크리스트

- [ ] 노드 2대 Ready, 라벨/테인트 적용 (`tier=app`/`tier=llm`)
- [ ] PGX `nvidia.com/gpu: 1` allocatable
- [ ] StorageClass fast(NVMe)/bulk(HDD) 분리, DB류 PVC=fast 확인
- [ ] amd64 앱 이미지 + arm64 vLLM 이미지 레지스트리 push, manifest arch 확인
- [ ] Helm 배포 — vLLM만 pgx, 나머지 p3 배치 확인 (`-o wide`)
- [ ] **Qwen3-32B 로딩 완료** (startupProbe 내), `/v1/models` 응답
- [ ] Flyway migration + seed + qdrant-init
- [ ] Ingress 경유 E2E: 질문→답변(+피드백 버튼)→피드백 UP/위조 401
- [ ] NetworkPolicy 차단 경로 확인, vLLM 재기동 복원 확인
- [ ] `make test-isolation` green
- [ ] **`make evaluate` 리포트 생성 — 품질 5지표 목표 대비 판정, SIMILARITY_THRESHOLD 확정**
- [ ] ACK p95 ≤ 2s / 검색 p95 ≤ 1s 판정, 생성 성능은 참고치 기록

> 이 클러스터에서 green이면 PoC 환경 이관 시 남는 변수는 사실상 "운영 GPU 성능"과 "실 Mattermost 연동" 둘뿐입니다.
