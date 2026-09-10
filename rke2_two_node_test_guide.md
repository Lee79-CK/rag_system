# 로컬 2-Node RKE2 클러스터 테스트 가이드 — RAG Platform

> 문서 ID: GUIDE-LOCAL-K8S-TEST-001 (**v1.2 — 2026-09-10 코드 리뷰 반영**)
> 기준: TDD-RAG-CHATBOT-POC-001 v1.2 + **현행 구현 기준** — 전 서비스 Python 3.12 (uv workspace), Helm chart `deploy/helm/rag-platform`
> v1.2 변경 요지 (상세: `docs/code-review-2026-09-10.md` §6):
> - v1.1 이 전제하던 **Containerfile · mock-mattermost · `samples/` · `scripts/sign_feedback.py` 가 리포에 추가**되어 §3/§5 절차가 실제로 실행된다.
> - chart 가 **Secret 파일 마운트 · PostgreSQL 자격증명 · documents-pvc 마운트 · Ingress · Alembic hook · admin-api RBAC** 를 렌더한다 (v1.1 은 이 항목들이 없어 배포가 성립하지 않았다).
> - 업로드 API 필드(`meta` 파트 없음), 색인 트리거(`INDEX_JOB_TRIGGER=k8s`), 평가 runner 실체(6문항·judge 없음), `make test-integration` 대상 등 사실과 다른 기술을 정정했다.
> 대상 환경:
> - **Master(P3)**: Lenovo ThinkStation P3 Tower Gen 2 — Core Ultra 7 265 (x86_64), RAM 128GB, RTX A400 4GB, **NVMe 1TB(OS+RKE2+fast PVC) + HDD 4TB(bulk)**, Ubuntu 24.04
> - **Worker(PGX)**: Lenovo ThinkStation PGX (NVIDIA DGX Spark OEM) — GB10 Grace Blackwell (**ARM64/aarch64**), 통합 메모리 128GB, SSD 4TB
> - RKE2 설치 완료 (P3=server, PGX=agent), 노드 간 2.5GbE, Docker(P3, 이미지 빌드용)

---

## 0. 이 환경이 검증하는 범위 (노트북 가이드와의 차이)

| 검증 항목 | 가능 여부 | 비고 |
|---|---|---|
| Helm 배포 / NetworkPolicy / Ingress / Probe / Secret 마운트 등 K8s 매니페스트 전체 | ✅ | **PoC 배포와 동일 chart·동일 방식** — 이 환경의 최대 가치 |
| RAG 파이프라인 전체 (E2E, Ingress 경유) | ✅ | 업로드 → K8s 색인 Job → 질문 → mock-mattermost 게시 → 피드백 |
| **답변 품질 (Qwen3-32B 실물)** | ✅ | PGX 통합 메모리 128GB — 32B FP8/4bit 여유 구동 |
| `make evaluate` 품질 평가 | ⚠️ 부분 | **현재 데이터셋 6문항**(`tests/evaluation/dataset/q001~q006`), 지표 4종(Recall@10 · Citation Precision · 무근거 안전응답 · 근거 응답률). **Faithfulness/LLM-judge 는 미구현** — 100문항·judge 는 작성 과제 |
| Channel 격리 (CH-001~010) | ✅ | `make test-isolation` 은 **클러스터와 무관한 로컬 pytest**(in-memory fake). 실 Qdrant 검증(`test_ch_qdrant.py`)은 Docker(testcontainers) 필요 — P3 에서 실행 |
| 성능 목표 수치 (p95 30s @ 동시 10~15) | ⚠️ 참고치 | GB10 메모리 대역폭(~273GB/s) 특성상 decode 속도는 운영 GPU(H100 등)와 다름. **동시 4~8 기준 경향 측정** |
| GPU 2장 이중화 (vLLM ×2) | ❌ | GPU 노드 1대 — replica 1로 축소 |

**아키텍처 핵심 제약** — 이 클러스터는 이기종(x86_64 + aarch64)입니다:

| 구분 | 배치 노드 | 이유 |
|---|---|---|
| vLLM (Qwen3-32B) | **PGX (arm64)** | GPU/통합 메모리. NVIDIA ARM64 컨테이너 사용 |
| 그 외 전부 (bridge, rag-api/worker, admin-api/web, embedding, reranker, mock-mattermost, qdrant, pg, redis, indexer Job) | **P3 (amd64)** | x86 단일 아키텍처로 이미지 빌드 단순화. Core Ultra 7 + 128GB로 충분 |
| P3의 RTX A400 4GB | **미사용** | LLM 부적합(4GB). GPU Operator 설치 대상에서 제외 |

> 이 배치 전략 덕분에 **multi-arch 이미지 빌드가 불필요**합니다. 앱 이미지는 amd64만 빌드하고, vLLM은 NVIDIA 제공 arm64 이미지를 그대로 사용합니다. (추후 PGX의 Grace CPU를 embedding 등에 활용하려면 buildx multi-arch로 확장 — §9)

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
export P3_IP=$(kubectl get node -l node-role.kubernetes.io/control-plane -o jsonpath='{.items[0].status.addresses[?(@.type=="InternalIP")].address}')
echo $P3_IP     # §4 의 networkPolicy.apiServer.cidrs 와 /etc/hosts 에 사용
```

### 1.2 노드 라벨/테인트 — 배치 전략 고정

```bash
kubectl label node p3  ragplatform.io/tier=app   --overwrite
kubectl label node pgx ragplatform.io/tier=llm   --overwrite
kubectl taint node pgx dedicated=llm:NoSchedule --overwrite     # PGX 를 LLM 전용으로 보호
```

`values-lab.yaml` 은 전역 `nodeSelector: {kubernetes.io/arch: amd64}` 를, vLLM 에는 `nodeSelector: {ragplatform.io/tier: llm}` + toleration 을 지정합니다 (§4).

### 1.3 PGX GPU 활성화 (GPU Operator)

DGX Spark 계열은 드라이버가 DGX OS/베이스 이미지에 포함되므로 Operator는 **driver 설치 비활성** 모드로 배포합니다.

```bash
# PGX 로컬에서 드라이버/CUDA 확인
nvidia-smi     # GB10, 통합 메모리 표시

# P3(kubectl)에서 GPU Operator 설치 — arm64 지원 버전 (chart 는 개발망에서 미러링해 두었다고 가정)
helm repo add nvidia https://helm.ngc.nvidia.com/nvidia && helm repo update
helm upgrade --install gpu-operator nvidia/gpu-operator \
  -n gpu-operator --create-namespace \
  --set driver.enabled=false \
  --set toolkit.enabled=true

kubectl describe node pgx | grep -A3 'Allocatable' | grep nvidia
# nvidia.com/gpu: 1
```

RKE2는 containerd 사용 — GPU Operator의 toolkit이 containerd config를 자동 패치합니다. 수동 설정이 필요하면 `/var/lib/rancher/rke2/agent/etc/containerd/config.toml.tmpl`에 nvidia runtime을 추가 후 `systemctl restart rke2-agent`.

### 1.4 스토리지 전략 (P3 디스크 2개 — NVMe 1TB + HDD 4TB)

P3의 물리 디스크는 **NVMe 1TB, HDD 4TB 2개뿐**입니다. **OS·RKE2·etcd·fast PVC가 같은 NVMe를 공유**하며, 이것이 이 구성의 유일한 진짜 제약입니다. 티어 분리는 유지하되 NVMe는 "여유 공간 관리" 대상으로 다룹니다.

| 용도 | 디스크 | 경로 | 방식 |
|---|---|---|---|
| OS / RKE2 / etcd / containerd 이미지 | NVMe 1TB | `/`, `/var/lib/rancher` | 기본 (건드리지 않음) |
| PostgreSQL / Qdrant / Redis PVC | **NVMe 1TB** | `/data/fast` | StorageClass `local-fast` (성능 필수) |
| 문서 원본 PVC(`documents-pvc`) / 이미지 레지스트리 / 백업 | **HDD 4TB** | `/data/bulk` | StorageClass `local-bulk` |
| 모델 아티팩트 (embedding/reranker) | **HDD 4TB** | `/data/bulk/models` | hostPath 마운트 (§2.2) |
| 모델 아티팩트 (LLM) | PGX SSD 4TB | `/models/llm` | hostPath 마운트 (§2.1) |

> 레지스트리·문서 원본·모델·백업이 HDD 4TB 한 스핀들을 공유합니다. 용량은 충분하지만 **IO 경합**이 생깁니다 — 대량 색인 Job과 이미지 push/pull을 동시에 돌리지 마세요 (§8).

#### 1.4.1 NVMe 용량 배분 (1TB 단일 디스크)

| 항목 | 배분 | 근거 |
|---|---|---|
| OS(Ubuntu 24.04) + `/var/lib/rancher` (containerd 이미지 + etcd) | ~250GB | amd64 앱 이미지 8종 + 베이스 이미지 누적 |
| `/data/fast` (DB PVC 전용) | **400GB** | 아래 실사용 합계의 4배 여유 |
| 미할당 여유 | ~280GB | DiskPressure 방어선 |

`/data/fast` 명목 합계 (values-lab 기준): PostgreSQL 20Gi + Qdrant 50Gi + Redis 10Gi = **80Gi**. 6문항 평가/샘플 문서 기준 실사용은 10GB 미만입니다.

#### 1.4.2 디스크 준비 (P3 로컬)

**HDD 4TB — `/data/bulk` 로 마운트** (디바이스명은 `lsblk` 로 반드시 확인):

```bash
lsblk -o NAME,SIZE,TYPE,MOUNTPOINT,MODEL        # 4TB HDD의 실제 이름 확인 (예: /dev/sda)

sudo parted -s /dev/sda mklabel gpt mkpart primary ext4 0% 100%
sudo mkfs.ext4 -L bulk /dev/sda1
sudo mkdir -p /data/bulk
echo "UUID=$(sudo blkid -s UUID -o value /dev/sda1) /data/bulk ext4 defaults,noatime 0 2" | sudo tee -a /etc/fstab
sudo mount -a
findmnt /data/bulk                               # ★ HDD 디바이스가 나오는지 확인 후 다음 단계
sudo mkdir -p /data/bulk/pvc /data/bulk/models /data/bulk/registry
```

**NVMe — `/data/fast`.** 별도 디스크가 없으므로 두 가지 선택지가 있습니다.

*(A) 전용 파티션 — 권장.* NVMe에 미할당 공간이 있으면 400GB 파티션을 잘라 루트 파일시스템과 격리합니다. PVC가 폭주해도 **kubelet의 nodefs eviction(루트 FS 기준)이 발동하지 않습니다.**

```bash
sudo parted -s /dev/nvme0n1 mkpart primary ext4 <시작>GB <시작+400>GB   # 미할당 영역 확인 후
sudo mkfs.ext4 -L fast /dev/nvme0n1pN && sudo mkdir -p /data/fast
echo "UUID=$(sudo blkid -s UUID -o value /dev/nvme0n1pN) /data/fast ext4 defaults,noatime 0 2" | sudo tee -a /etc/fstab
sudo mount -a && findmnt /data/fast
```

*(B) 루트 파일시스템 위 디렉터리 — 미할당 공간이 없을 때.* **DB PVC 사용량이 루트 FS 사용량에 그대로 합산**됩니다. 루트 FS 85% 초과 시 kubelet이 `DiskPressure` 로 P3의 Pod들을 evict — 앱 전체가 P3에 있으므로 사실상 클러스터 정지입니다.

```bash
sudo mkdir -p /data/fast && df -h /data/fast     # Avail 500GB 이상이어야 안전
```

> local-path는 hostPath 기반이라 **PVC의 `requests.storage` 를 강제하지 않습니다.** (B)를 택했다면 `df -h /` 를 평가 전후로 확인하세요.

#### 1.4.3 StorageClass 배포

`deploy/k8s/` 의 두 매니페스트가 local-path-provisioner 인스턴스를 **각각 하나씩** 띄웁니다 (provisioner 이름 `rancher.io/local-path-fast` / `-bulk`).

```bash
# ★ 노드 이름 치환 — 매니페스트의 "p3" 는 예시
NODE=$(kubectl get node -l ragplatform.io/tier=app -o jsonpath='{.items[0].metadata.name}')
sed -i "s/\"node\": \"p3\"/\"node\": \"$NODE\"/" deploy/k8s/local-path-*.yaml

# 폐쇄망: helper 이미지(busybox:1.36.1)를 미러 레지스트리로 교체 (§1.5 이후 실행) — 아니면 helper Pod ImagePullBackOff
# sed -i "s#busybox:1.36.1#registry.local:5000/library/busybox:1.36.1#g" deploy/k8s/local-path-*.yaml

kubectl apply -f deploy/k8s/local-path-fast.yaml
kubectl apply -f deploy/k8s/local-path-bulk.yaml

kubectl -n local-path-storage get pods
kubectl get sc
# NAME                 PROVISIONER                  RECLAIMPOLICY   VOLUMEBINDINGMODE
# local-fast (default) rancher.io/local-path-fast   Delete          WaitForFirstConsumer
# local-bulk           rancher.io/local-path-bulk   Retain          WaitForFirstConsumer
```

동작 확인 — PVC를 하나 만들어 **경로가 맞는 디스크에 생겼는지** 봅니다 (`WaitForFirstConsumer` 이므로 Pod가 있어야 바인딩됩니다):

```bash
kubectl apply -f - <<'EOF'
apiVersion: v1
kind: PersistentVolumeClaim
metadata: { name: sc-check, namespace: default }
spec:
  accessModes: ["ReadWriteOnce"]
  storageClassName: local-bulk
  resources: { requests: { storage: 1Gi } }
---
apiVersion: v1
kind: Pod
metadata: { name: sc-check, namespace: default }
spec:
  nodeSelector: { kubernetes.io/arch: amd64 }
  containers:
    - name: c
      image: busybox:1.36.1
      command: ["sh","-c","echo ok > /d/probe && sleep 30"]
      volumeMounts: [{ name: d, mountPath: /d }]
  volumes: [{ name: d, persistentVolumeClaim: { claimName: sc-check } }]
EOF

kubectl get pvc sc-check                       # Bound 확인
sudo find /data/bulk/pvc -name probe           # ★ HDD 경로에 파일이 있어야 정상
kubectl delete pod/sc-check pvc/sc-check
sudo rm -rf /data/bulk/pvc/pvc-*               # Retain 정책이라 수동 정리
```

> DB류 PVC를 HDD에 두면 Qdrant 검색 p95 1초 목표가 로컬에서도 깨집니다. **fast(NVMe)/bulk(HDD) 분리를 반드시 유지**하세요. 문서 원본 PVC가 NVMe로 새면 1TB가 금방 찹니다 — §4.3 의 `storageClassName` 검증을 꼭 실행하세요.

### 1.5 프라이빗 레지스트리 (P3, HDD)

폐쇄망 Harbor를 모사하고 PGX가 이미지를 당겨갈 수 있도록 P3에 registry를 둡니다.

```bash
findmnt /data/bulk || { echo "HDD 미마운트 — §1.4.2 먼저"; exit 1; }   # 미마운트 상태로 띄우면 NVMe에 이미지가 쌓인다
docker run -d --restart=always --name registry -p 5000:5000 \
  -v /data/bulk/registry:/var/lib/registry registry:2

# 양쪽 노드 모두: /etc/rancher/rke2/registries.yaml  (P3_IP 는 §1.1)
sudo tee /etc/rancher/rke2/registries.yaml <<EOF
mirrors:
  "registry.local:5000":
    endpoint: ["http://${P3_IP}:5000"]
configs:
  "registry.local:5000":
    tls: { insecure_skip_verify: true }
EOF
sudo systemctl restart rke2-server   # P3
sudo systemctl restart rke2-agent    # PGX (동일 파일 배치 후)

# P3 의 Docker 도 insecure registry 로 등록 (push 용): /etc/docker/daemon.json → {"insecure-registries":["registry.local:5000"]}
echo "${P3_IP} registry.local" | sudo tee -a /etc/hosts   # 양쪽 노드 + 접속 PC
```

---

## 2. 모델 아티팩트 배치

### 2.1 PGX — LLM (Qwen3-32B 실물 구동)

통합 메모리 128GB이므로 32B FP8(~34GB) 또는 AWQ 4bit(~20GB)가 KV cache 포함 여유 있게 적재됩니다. **TDD §8.2 운영 인자를 그대로 사용할 수 있는 것이 이 환경의 최대 장점입니다.**

```bash
# PGX에서
sudo mkdir -p /models/llm && sudo chown $USER /models
hf download Qwen/Qwen3-32B-FP8 --local-dir /models/llm/main   # 또는 반입 아티팩트 복사
sudo chmod -R a+rX /models      # Pod(runAsUser 10001) 읽기 권한 — hostPath 에는 fsGroup 이 적용되지 않는다
```

### 2.2 P3 — Embedding / Reranker (CPU, amd64)

```bash
# P3에서 — HDD(/data/bulk)에 배치. 두 모델 합쳐 ~5GB로 NVMe를 쓸 이유가 없다.
sudo mkdir -p /data/bulk/models && sudo chown $USER /data/bulk/models
hf download BAAI/bge-m3             --local-dir /data/bulk/models/embedding/bge-m3
hf download BAAI/bge-reranker-v2-m3 --local-dir /data/bulk/models/reranker/bge-reranker-v2-m3
sudo chmod -R a+rX /data/bulk/models
```

> HDD에서 로드하므로 Pod 최초 기동 시 모델 적재가 NVMe 대비 수십 초 느립니다. values-lab 은 embedding/reranker 의 `startupFailureThreshold: 90`(×10s = 15분) 을 두었습니다. 추론 중에는 모델이 페이지 캐시(RAM 128GB)에 상주하므로 **정상 상태 성능에는 영향이 없습니다.**
>
> ⚠️ embedding/reranker 는 모델 디렉터리가 없으면 **조용히 mock 엔진(결정론적 난수 벡터)으로 기동**합니다(`engine.py build_engine`). 배포 후 로그의 `engine_ready` 이벤트에 `-mock` 접미가 없는지 반드시 확인하세요 (§4.3).

---

## 3. 이미지 빌드 및 푸시 (P3, amd64 전용)

**Containerfile 은 앱별로 존재하며 빌드 컨텍스트는 리포 루트**(uv workspace 해석)입니다 — admin-web 만 자체 디렉터리. `make build-images` 가 8종을 한 번에 빌드합니다.

| 이미지 | Containerfile | 비고 |
|---|---|---|
| `rag/mattermost-bridge` `rag/rag-api` `rag/admin-api` | `apps/<svc>/Containerfile` | `uv sync --frozen --no-dev --package <svc>`. rag-worker 는 rag-api 이미지 공유(DEC-017) |
| `rag/embedding-api` `rag/reranker-api` | `apps/<svc>/Containerfile` | **`UV_EXTRA=models` 기본** → torch/FlagEmbedding(cp312 amd64 휠) 포함. mock 전용 이미지는 `--build-arg UV_EXTRA=` |
| `rag/parser-indexer` | `apps/parser-indexer/Containerfile` | ENTRYPOINT `python -m ingestion.main` (K8s Job) |
| `rag/admin-web` | `apps/admin-web/Containerfile` + `nginx.conf` | node 빌드 → nginx :8080 비루트 |
| `rag/mock-mattermost` | `tools/mock-mattermost/Containerfile` | 랩 전용 Incoming Webhook 수신 mock :9099 |

```bash
cd ~/work/rag-platform
export TAG=$(git rev-parse --short HEAD)
export REG=registry.local:5000

# 8종 빌드 + push (Makefile 변수 REG/TAG). 베이스 이미지(python:3.12-slim, ghcr.io/astral-sh/uv, node:20-alpine, nginx:1.27-alpine)
# 는 개발망에서 pull 된다. 완전 폐쇄망이면 --build-arg PYTHON_IMAGE/UV_IMAGE/NODE_IMAGE/NGINX_IMAGE/UV_INDEX_URL 로 내부 미러를 지정한다.
make build-images REG=$REG TAG=$TAG
make push-images  REG=$REG TAG=$TAG
```

> **torch 휠 크기**: embedding/reranker 이미지는 torch(CPU) 포함 시 2~3GB 입니다. 두 이미지가 HDD 레지스트리와 P3 containerd 캐시(NVMe) 양쪽에 올라간다는 점을 §1.4.1 용량 계산에 반영하세요.

vLLM 은 빌드하지 않고 **NVIDIA 제공 arm64 이미지**를 미러링합니다:

```bash
# DGX Spark 지원 vLLM 이미지 (NGC) — arm64 태그 확인 후 미러. chart 의 rag.image 헬퍼가 global.imageTag 를 붙이므로 앱과 동일 $TAG 로 태깅
docker pull --platform linux/arm64 nvcr.io/nvidia/vllm:<tag>
docker tag nvcr.io/nvidia/vllm:<tag> $REG/ai/vllm-arm64:$TAG
docker push $REG/ai/vllm-arm64:$TAG

# 데이터 계층 + helper 이미지 미러 (values-lab.yaml 의 data.*.image 가 이 경로를 가리킴)
for img in qdrant/qdrant:v1.12.1 postgres:16 redis:7 busybox:1.36.1; do
  name=$(basename $img); docker pull $img && docker tag $img $REG/library/$name && docker push $REG/library/$name
done
```

> **검증 습관**: 배포 전 `docker manifest inspect $REG/rag/rag-api:$TAG | grep architecture` — 이기종 클러스터에서 `exec format error`의 90%는 아키텍처 불일치입니다.

---

## 4. 배포 (Helm, values-lab.yaml)

`deploy/helm/rag-platform/values-lab.yaml` 은 `values.yaml`(기본) → `values-poc.yaml`(운영 override) 위에 겹쳐 쓰는 **랩 override** 입니다. 운영과 달라지는 지점은 파일 주석에 근거를 남겼습니다.

| 항목 | 운영(values-poc) | 랩(values-lab) | 이유 |
|---|---|---|---|
| 레지스트리 | `harbor.internal` | `registry.local:5000` | §1.5 |
| 앱 replica / PDB | 2 / `minAvailable: 1` | 1 / 해제(`null` → PDB 미생성) | P3 20코어. replica 1에 PDB를 두면 rollout이 막힘 |
| rag-worker | 2 | 2 (유지) | 큐 재처리 시나리오(§6) 검증 |
| vLLM replica / 배치 | `[llm-0, llm-1]` | `[llm-0]` + `nodeSelector tier=llm` + `dedicated=llm` toleration | GPU 노드 1대, 이기종 배치 |
| `--max-num-seqs` | 16 | 8 | GB10 대역폭 |
| 모델 볼륨 | `models-pvc` | **hostPath** (`/data/bulk/models`, vLLM은 `/models`) | GPU 노드와 앱 노드가 달라 단일 PVC 공유 불가 |
| 데이터 계층 | qdrant 500Gi / pg 200Gi / redis 20Gi | 50 / 20 / 10Gi + `local-fast` | NVMe 1TB 공유 (§1.4.1) |
| `documents-pvc` | 1Ti (default SC=NFS) | 500Gi + `local-bulk` | HDD |
| Ingress Controller NS | `ingress-nginx` | `kube-system` + podSelector `rke2-ingress-nginx` | RKE2 내장 컨트롤러 위치 |
| Ingress host | `rag.internal` | `rag.lab.local` | — |
| 색인 트리거 | `INDEX_JOB_TRIGGER=none` | `k8s` + ServiceAccount/RBAC + apiserver egress | 업로드 → Job 자동 생성 검증 |
| Grafana 대시보드 ConfigMap | on (`monitoring` NS) | **off** | kube-prometheus-stack 미설치 전제 (§9) |
| admin-web / mock-mattermost | 미포함 | appServices 로 추가 | Ingress `/`, E2E 게시 확인 |

chart 가 **코드가 기대하는 경로/키를 책임지고 채우는** 항목(v1.2 에서 추가됨 — 사용자는 Secret 만 만들면 됩니다):

| 코드가 읽는 것 | chart 가 렌더하는 것 |
|---|---|
| `MATTERMOST_OUTGOING_TOKEN_SECRET_FILE`, `FEEDBACK_SIGNING_KEY_FILE` (파일) | Secret `rag-bridge-secrets` → `/var/run/secrets/rag/{outgoing-token,feedback-signing-key}` (bridge/rag-api/rag-worker) |
| `MATTERMOST_SECRET_DIR/<secret_ref>` (파일명 = binding.secret_ref) | `incomingWebhookSecrets` 목록을 **projected volume** 으로 `/var/run/secrets/mattermost/<secretName>` 에 투영 (rag-api/rag-worker) |
| `POSTGRES_HOST/PORT/USER/DB/PASSWORD` | `global.postgres.*` + Secret `rag-postgresql-secret`(key `password`) — 앱·Job·PostgreSQL StatefulSet(initdb) 공통 |
| `REDIS_URL`, `RQ_REDIS_URL` | `global.redisUrl` |
| `DOCUMENT_STORAGE_PATH=/data/documents` (admin-api 쓰기, indexer 읽기) | `documents-pvc` 를 admin-api(rag-app)·indexer Job(rag-ingestion)에 마운트 |
| Alembic `upgrade head` | `migration.enabled=true` → post-install/upgrade hook Job(admin-api 이미지, 30회 재시도) |

### 4.1 선행 조건 — Namespace · 라벨 · Secret

**순서가 중요합니다.** Secret 은 Namespace-scoped 이므로 NS 를 먼저 만들고, Secret 을 만든 뒤 helm 을 실행해야 Pod 가 첫 기동에서 바로 뜹니다.

```bash
# 1) Namespace 4종 + ★ NetworkPolicy 가 요구하는 라벨. 라벨이 없으면 rag-api→qdrant/pg/redis/embedding/vllm 등 NS 간 통신이 전부 차단된다
for ns in rag-app rag-ai rag-data rag-ingestion; do
  kubectl create ns $ns --dry-run=client -o yaml | kubectl apply -f -
  kubectl label ns $ns rag-platform=true --overwrite
done

# 2) 로컬 secret 파일 (노트북 가이드 §3 와 동일 규약 — sign_feedback.py 가 같은 파일을 읽는다)
mkdir -p secrets/mattermost secrets/rag
echo -n "lab-outgoing-token" > secrets/mattermost/outgoing-token
python3 -c "import secrets;print(secrets.token_hex(32),end='')" > secrets/rag/feedback-signing-key
echo -n "rag-lab-pg-$(openssl rand -hex 8)" > secrets/rag/postgres-password
chmod 600 secrets/mattermost/* secrets/rag/*

# 3) bridge / rag-api / rag-worker 가 파일로 읽는 Secret (rag-app)
kubectl -n rag-app create secret generic rag-bridge-secrets \
  --from-file=outgoing-token=secrets/mattermost/outgoing-token \
  --from-file=feedback-signing-key=secrets/rag/feedback-signing-key

# 4) PostgreSQL 비밀번호 — StatefulSet(rag-data) · 앱/마이그레이션 Job(rag-app) · 색인 Job(rag-ingestion) 세 NS 에 동일하게
for ns in rag-data rag-app rag-ingestion; do
  kubectl -n $ns create secret generic rag-postgresql-secret --from-file=password=secrets/rag/postgres-password
done

# 5) Channel 별 Incoming Webhook URL (seed 의 두 채널: secret_ref = Secret 이름). 랩은 mock-mattermost 를 가리킨다
kubectl -n rag-app create secret generic mattermost-incoming-rag-cloud-ops \
  --from-literal=url='http://mock-mattermost.rag-app:9099/hooks/cloud-ops'
kubectl -n rag-app create secret generic mattermost-incoming-rag-hr \
  --from-literal=url='http://mock-mattermost.rag-app:9099/hooks/hr'

kubectl get secret -A | grep -E "rag-bridge|rag-postgresql|mattermost-incoming"   # 6개
```

> Secret 값은 Helm values 에 절대 넣지 않습니다(TDD §14.2 existingSecret 패턴). 채널을 추가하면 ① admin-api 로 binding 생성(`secret_ref` = Secret 이름) ② 같은 이름의 Secret 생성 ③ `values-lab.yaml` 의 `incomingWebhookSecrets` 에 항목 추가 후 `helm upgrade` — 세 단계가 필요합니다.

### 4.2 설치

```bash
cd ~/work/rag-platform
export TAG=$(git rev-parse --short HEAD)   # §3 에서 push 한 태그

make helm-lint helm-template                # 렌더 사전 검증 (poc / poc+lab)

helm upgrade --install rag-platform deploy/helm/rag-platform \
  -f deploy/helm/rag-platform/values-poc.yaml \
  -f deploy/helm/rag-platform/values-lab.yaml \
  --set global.imageTag=$TAG \
  --set "networkPolicy.apiServer.cidrs={${P3_IP}/32}"   # admin-api → kube-apiserver(6443) egress. values-lab 의 예시 IP 를 실제 값으로
# `helm dependency update` 는 필요 없다 — Chart.yaml 에 dependencies 가 없다(데이터 계층도 이 chart 의 StatefulSet)

# 상태 확인 — vLLM 은 32B 로딩에 최대 10분(startupProbe 60×10s), embedding/reranker 는 HDD 로딩 최대 15분(90×10s)
kubectl get pods -A -l app.kubernetes.io/part-of=rag-platform -o wide
kubectl -n rag-ai logs -f deploy/vllm-llm-0 | grep -i "loading\|ready\|error"
```

`-o wide` 로 **배치 검증**: vLLM 만 pgx, 나머지 전부 p3 에 스케줄되었는지 확인합니다. 마이그레이션 hook Job 은 `helm upgrade` 가 끝날 때 완료되어 있어야 하며(실패 시 helm 자체가 실패), 성공하면 `hook-delete-policy` 로 삭제됩니다.

### 4.3 배포 후 검증 (필수 8종)

```bash
# ① 마이그레이션 — hook Job 이 지웠으므로 admin-api Pod 에서 리비전 확인 (Containerfile WORKDIR=/app)
kubectl -n rag-app exec deploy/admin-api -- \
  alembic -c /app/apps/admin-api/src/admin/db/migrations/alembic.ini current
# → 0002_feedback_enabled (head)

# ② Secret 파일이 실제로 마운트되었는지 (v1.1 배포의 최대 함정 — 없으면 모든 질문이 401)
kubectl -n rag-app exec deploy/mattermost-bridge -- ls -l /var/run/secrets/rag
kubectl -n rag-app exec deploy/rag-worker -- ls -l /var/run/secrets/mattermost
# → mattermost-incoming-rag-cloud-ops, mattermost-incoming-rag-hr (파일명 = secret_ref)
kubectl -n rag-app logs deploy/mattermost-bridge | grep -c "startup.*_missing"    # 0 이어야 정상

# ③ PVC 가 맞는 티어에 생성되었는지
kubectl get pvc -A -o custom-columns='NS:.metadata.namespace,NAME:.metadata.name,SC:.spec.storageClassName,SIZE:.spec.resources.requests.storage,STATUS:.status.phase'
# data-qdrant-0 / data-postgresql-0 / data-redis-0 → local-fast ; documents-pvc(rag-app, rag-ingestion) → local-bulk
# models-pvc 는 modelStorage.create=false 이므로 없는 것이 정상

# ④ admin-api 가 문서 볼륨에 쓸 수 있는지
kubectl -n rag-app exec deploy/admin-api -- sh -c 'touch /data/documents/.probe && rm /data/documents/.probe && echo writable'

# ⑤ 임베딩/리랭커가 mock 이 아닌 실엔진으로 떴는지 (모델 경로 미마운트 시 조용히 mock 으로 기동한다)
kubectl -n rag-ai logs deploy/embedding-api | grep engine_ready     # "-mock" 접미가 없어야 함
kubectl -n rag-ai logs deploy/reranker-api  | grep engine_ready

# ⑥ vLLM 모델 서빙
kubectl -n rag-ai exec deploy/rag-api -- python -c "import httpx;print(httpx.get('http://vllm-service.rag-ai:8000/v1/models',timeout=10).json()['data'][0]['id'])"
# → internal-rag-llm

# ⑦ Ingress / NetworkPolicy
kubectl -n rag-app get ingress rag-platform        # HOSTS rag.lab.local, ADDRESS = P3_IP
kubectl get netpol -A | grep -c allow-ingress-to    # 3 (mattermost-bridge, admin-api, admin-web)
echo "${P3_IP} rag.lab.local" | sudo tee -a /etc/hosts    # 접속 PC
curl -s http://rag.lab.local/api/v1/auth/whoami -H 'X-Auth-User: cklee' | head -c 200   # seed 전이면 401/404 — §4.4 후 재확인

# ⑧ 디스크
df -h / /data/fast /data/bulk    # NVMe 사용률 70% 미만
```

### 4.4 Seed / Qdrant 초기화

seed(`scripts/seed_dev.sql`) 는 관리자 2명(`cklee`=SYS_ADMIN, `docadmin`=DOC_ADMIN), 채널 2개(`channel-001` rag-cloud-ops 전용 / `channel-002` rag-hr `!rag` 트리거), 지식범위, binding, 문서 메타 1건을 넣습니다.

```bash
# PostgreSQL Pod 안에서 psql 로 적용 (호스트에 psql 불필요, NetworkPolicy 무관)
kubectl -n rag-data exec -i sts/postgresql -- psql -U rag -d rag -v ON_ERROR_STOP=1 -f - < scripts/seed_dev.sql

# Qdrant collection(rag_chunks_v1) + payload index — parser-indexer 이미지 안의 도구를 클러스터 안에서 실행
kubectl -n rag-ingestion run qdrant-init --rm -i --restart=Never \
  --image=$REG/rag/parser-indexer:$TAG \
  --labels=app.kubernetes.io/part-of=rag-platform \
  --overrides='{"spec":{"nodeSelector":{"kubernetes.io/arch":"amd64"}}}' \
  --env=QDRANT_URL=http://qdrant.rag-data:6333 \
  --command -- python -m ingestion.tools.qdrant_init
```

> `make seed`/`make qdrant-init` 을 **port-forward 로 로컬에서** 실행하는 방법도 있지만, default-deny NetworkPolicy 환경에서 port-forward 트래픽은 CNI 구현에 따라 차단될 수 있어 위처럼 클러스터 안에서 실행하는 쪽이 확실합니다. seed 의 문서 1건(`장애대응매뉴얼`)은 **파일 실체가 없는 메타데이터**이므로 색인 대상이 아닙니다 — 실제 문서는 §5 에서 업로드합니다.

---

## 5. E2E 기능 테스트 (Ingress 경유)

노트북 가이드 §5 와 동일 시나리오를 **클러스터 외부(접속 PC)에서** 수행합니다 — NetworkPolicy·Ingress·Secret 마운트·K8s Job 트리거까지 함께 검증됩니다.

### 5.1 문서 업로드 → 색인 Job → 질문 → 게시 확인

```bash
export RAG=http://rag.lab.local

# 1) 샘플 문서 업로드 (samples/*.md — parser 가 .md 지원). 필드는 평면 multipart: file/title/category/department/security_level/
#    allowed_channel_ids(콤마 구분 — ★ 비우면 어느 채널에서도 검색되지 않는다)/start_indexing
curl -s -X POST $RAG/api/v1/documents -H 'X-Auth-User: cklee' \
  -F 'file=@samples/장애대응매뉴얼.md' -F 'title=장애대응매뉴얼' -F 'category=장애대응' \
  -F 'department=Cloud운영팀' -F 'security_level=INTERNAL' \
  -F 'allowed_channel_ids=channel-001' -F 'start_indexing=true' | tee /tmp/upload.json
# → data.index_job_id, data.index_job_status=PENDING (INDEX_JOB_TRIGGER=k8s → Job 생성). error 가 있으면 §8 "TRIGGER_FAILED"

# 2) admin-api 가 만든 parser-indexer Job 확인 (rag-ingestion)
kubectl -n rag-ingestion get jobs -w            # index-job-xxxxx  COMPLETIONS 1/1
kubectl -n rag-ingestion logs job/$(kubectl -n rag-ingestion get jobs -o jsonpath='{.items[-1].metadata.name}') | tail -20
# → 단계 PARSING→CHUNKING→EMBEDDING→UPSERTING→VALIDATING, index_job COMPLETED
JOB_ID=$(jq -r .data.index_job_id /tmp/upload.json)
curl -s $RAG/api/v1/documents -H 'X-Auth-User: cklee' | jq '.data[] | {title,status}'     # ACTIVE

# 3) 질문 발송 (Outgoing Webhook 모사 — 토큰은 §4.1 의 outgoing-token)
curl -s -X POST $RAG/integrations/mattermost/v1/outgoing \
  -H 'Content-Type: application/json' -d '{
  "token":"lab-outgoing-token","team_id":"team-001","team_domain":"cloud-team",
  "channel_id":"channel-001","channel_name":"rag-cloud-ops",
  "user_id":"mmuser-001","user_name":"tester",
  "post_id":"post-'"$(date +%s)"'","root_id":"","text":"장애 등급별 대응 절차를 알려주세요."}'
# → {"text":"질문을 접수했습니다. 답변을 준비 중입니다."}  (2초 이내)

# 4) mock-mattermost 수신 확인 — 답변 본문 + 근거 문서 + 👍/👎 attachment
kubectl -n rag-app logs deploy/mock-mattermost --tail=5 | jq -r 'select(.event=="mock_mattermost.post_received") | .text, (.attachments[0].actions | map(.name))'
#    또는 조회 API: kubectl -n rag-app port-forward svc/mock-mattermost 9099:9099 & curl -s localhost:9099/posts?hook_id=cloud-ops | jq .

# 5) DB 상태
kubectl -n rag-data exec sts/postgresql -- psql -U rag -d rag -c \
  "SELECT status, completed_at - started_at AS dur FROM chat_jobs ORDER BY queued_at DESC LIMIT 3;"
# → COMPLETED, 32B 기준 수 초~수십 초
```

**32B 실물이므로 답변 품질을 직접 확인**: 근거 citation 정합성(`[1]` 과 `근거 문서` 목록), 한국어 자연스러움, 무근거 질문의 안전 응답을 수동 채점해 두면 §7 자동 평가와 대조할 수 있습니다.

### 5.2 피드백 버튼 클릭 + 위조 서명

```bash
MSG_ID=$(kubectl -n rag-data exec sts/postgresql -- psql -U rag -d rag -tA -c \
  "SELECT id FROM messages WHERE role='assistant' ORDER BY created_at DESC LIMIT 1;")
SIG=$(uv run python scripts/sign_feedback.py --message-id $MSG_ID --value UP --key-file secrets/rag/feedback-signing-key)

curl -s -X POST $RAG/integrations/mattermost/v1/actions -H 'Content-Type: application/json' -d '{
  "user_id":"mmuser-001","post_id":"p1","channel_id":"channel-001",
  "context":{"action":"feedback","message_id":"'$MSG_ID'","chat_job_id":"x","value":"UP","sig":"'$SIG'"}}'
# → {"ephemeral_text":"피드백이 반영되었습니다. 감사합니다 🙏"}

# 위조 서명 → 401 INVALID_SIGNATURE / 타 채널 → 403 FEEDBACK_CHANNEL_MISMATCH
curl -s -o /dev/null -w "%{http_code}\n" -X POST $RAG/integrations/mattermost/v1/actions -H 'Content-Type: application/json' -d '{
  "user_id":"u","post_id":"p","channel_id":"channel-001",
  "context":{"action":"feedback","message_id":"'$MSG_ID'","chat_job_id":"x","value":"UP","sig":"deadbeef"}}'
curl -s $RAG/api/v1/feedback/summary -H 'X-Auth-User: cklee' | jq .
```

### 5.3 부정 케이스 스모크

| 케이스 | 명령 요지 | 기대 |
|---|---|---|
| 잘못된 token | `"token":"wrong"` | HTTP 401 `INVALID_TOKEN` |
| **빈 token** | `"token":""` | HTTP 401 (v1.2 fail-closed — 이전엔 Secret 미마운트 시 통과) |
| 미등록 Channel | `channel_id=channel-999` | HTTP 403 `CHANNEL_NOT_BOUND` + bridge warning 로그 |
| 중복 post_id | 동일 post_id 2회 | 2회째 200 + `chat_jobs` 1건 |
| Bot 메시지 루프 | `user_name="RAG Assistant"` | 200 + job 미생성 |
| 트리거 채널 | `channel_id=channel-002`, `text="!rag 연차는 며칠인가요?"` | 접수. `text="연차는?"`(트리거 없음) 은 200 무시. 인사규정집을 `allowed_channel_ids=channel-002` 로 업로드해 두면 답변 |
| **격리(CH-001)** | channel-002 에서 "장애 등급별 대응 절차" 질문 | 장애대응매뉴얼은 channel-001 전용 → 근거 부족 안내 |
| 근거 없는 질문 | "오늘 점심 메뉴 추천" | "근거를 찾지 못했습니다" 안내 게시 (※ `SIMILARITY_THRESHOLD` 기본 0.0 이라 검색 0건일 때만 발동 — §7.1) |

### 5.4 Admin Web (`http://rag.lab.local/`)

- 우상단 사용자 버튼에서 `X-Auth-User` 를 `cklee` 로 설정(localStorage) — 랩은 인증 프록시가 없어 **클라이언트가 보낸 헤더를 그대로 신뢰**합니다(DEC-003). 운영 이관 시 oauth2-proxy 등이 헤더를 주입·덮어써야 하며, 이 상태로 외부에 노출하면 안 됩니다.
- 문서 관리(업로드/재색인) · 채널 · 대화 작업(단계별 latency) · 피드백(5.2 반영) 확인. Index Jobs/Audit Logs 화면은 admin-api 에 조회 API 가 없어 빈 상태로 표시됩니다(`apps/admin-web/README.md` 참조).
- 채널 "연결 테스트"는 **stub**(항상 성공) — 실제 게시 검증은 5.1 의 mock-mattermost 로 대신합니다.

---

## 6. 자동화 테스트

```bash
make lint && make test         # ruff + mypy(경고성) + 전체 pytest (133 passed, 1 skipped — Docker 없으면 test_ch_qdrant skip)
make test-isolation            # ★ CH-001~010 — 배포 Gate. 로컬 fake 기반이라 클러스터 불필요
make test-integration          # Docker 필요(P3): testcontainers 실 Qdrant 격리 테스트 + worker 통합
```

이 환경 특화 검증 항목:

| 항목 | 방법 | 기대 |
|---|---|---|
| NetworkPolicy default-deny | `kubectl -n rag-app run np-probe --rm -it --restart=Never --image=$REG/library/busybox:1.36.1 --overrides='{"spec":{"nodeSelector":{"kubernetes.io/arch":"amd64"}}}' -- wget -qO- -T3 http://qdrant.rag-data:6333/collections` | **타임아웃**(part-of 라벨 없는 Pod). 같은 명령에 `--labels=app.kubernetes.io/part-of=rag-platform` 를 주면 **성공** |
| NS 라벨 의존성 | `kubectl label ns rag-data rag-platform-` 후 질문 → 복구 `kubectl label ns rag-data rag-platform=true` | 라벨 제거 중 FAILED 오류 게시(⚠️ 답변 생성 중 오류) → 복구 후 정상. (admin-api→qdrant 는 설계상 **허용** 경로 — 서비스별 세분화는 후속 과제) |
| vLLM 재기동 복원력 | `kubectl -n rag-ai rollout restart deploy/vllm-llm-0` 후 질문 | 로딩 중 FAILED 오류 게시 → 복구 후 정상 |
| Worker 장애 | 처리 중 `kubectl -n rag-app delete pod -l app.kubernetes.io/name=rag-worker` | RQ 가 job 을 재큐잉하되 `claim_job` 멱등 가드로 **중복 게시 없음**(mock-mattermost 수신 1건) |
| 노드 격리 | PGX cordon 후 앱 재배포 | 앱은 전부 P3 에서 정상 (vLLM 만 Pending) |
| 색인 Job 격리 | 대용량 문서 색인 중 질문 | 질문 지연 없음 (rag-ingestion NS 별도, NFR-PERF-007) |

---

## 7. RAG 품질 평가 및 성능 참고치

### 7.1 품질 평가

runner(`tools/evaluation`)는 **rag-api 의 `POST /internal/v1/rag/completions` 를 직접 호출**합니다 — `RAG_API_URL` 로 접근 경로를 지정해야 하며, 클러스터 밖에서는 port-forward 가 필요합니다.

```bash
kubectl -n rag-app port-forward svc/rag-api 8002:8002 &
RAG_API_URL=http://localhost:8002 make evaluate
# → reports/evaluation_report.md  (Recall@10 ≥85%, Citation Precision ≥90%, 무근거 안전응답 ≥90%, 근거 응답률)
```

> - 데이터셋은 6문항이며 `q001` 은 `장애대응매뉴얼.pdf` 를 기대 문서로 둡니다 — §5 에서 `.md` 로 업로드했다면 문서명 매칭(`removesuffix(".pdf")` 부분 일치)은 통과합니다. PRD §25.6 의 100문항/유형 비율은 작성 과제입니다.
> - **Faithfulness/LLM-judge 와 격리 정확도는 리포트에 없습니다.** 격리는 §6 의 `make test-isolation` 이 담당합니다.
> - port-forward 가 default-deny 에 막히면 임시 정책: `kubectl -n rag-app apply -f - <<< '{"apiVersion":"networking.k8s.io/v1","kind":"NetworkPolicy","metadata":{"name":"tmp-allow-rag-api"},"spec":{"podSelector":{"matchLabels":{"app.kubernetes.io/name":"rag-api"}},"ingress":[{}]}}'` 후 평가, 끝나면 삭제.
> - **`SIMILARITY_THRESHOLD` 튜닝**(TDD §7.2.3 숙제): 현재 값은 rag-api/rag-worker 의 **env** 로만 반영됩니다(`values-lab.yaml` `extraEnv` 에 추가 → `helm upgrade`). Admin Web Settings 화면의 값은 `settings` 테이블에만 저장되고 파이프라인에는 연동되지 않습니다(리뷰 리포트 §3-4, P0 후속). README §8.3 의 `scripts/eval_diff.py` 도 아직 없습니다 — 리포트 파일을 날짜별로 복사해 두고 `diff` 로 비교하세요.

### 7.2 성능 — 해석 주의

```bash
# ACK p95 ≤ 2s — 이 환경에서도 그대로 유효한 목표. ★ MM_OUTGOING_TOKEN 이 없으면 locust 가 "dev-token" 을 보내 전부 401 이 된다
MM_OUTGOING_TOKEN=lab-outgoing-token BRIDGE_URL=http://rag.lab.local make perf-webhook-burst   # -u 50 -r 50 -t 10s

# 동시 6 부하 — locust 인자를 직접 지정
MM_OUTGOING_TOKEN=lab-outgoing-token uv run locust -f tests/performance/locustfile.py --headless -u 6 -r 6 -t 5m --host http://rag.lab.local
```

| 지표 | 목표(운영) | 이 환경 해석 |
|---|---|---|
| ACK p95 | ≤ 2s | **그대로 판정** (LLM 무관 경로). 단 bridge 의 DB 조회가 동기 I/O 라 50-user burst 에서 흔들릴 수 있음(리뷰 H-8) |
| 검색 p95 | ≤ 1s | NVMe Qdrant 면 그대로 판정 (`chat_job_duration_seconds{stage="search"}`) |
| 답변 p95 | ≤ 30s @ 동시 10 | GB10 대역폭 특성상 **동시 4~8 에서 경향만** 기록. 절대치로 합불 판정 금지 |
| 동시 15 | NFR-PERF-004 | 미검증 — 운영 GPU 환경 몫. (`CHAT_MAX_CONCURRENCY` 는 아직 코드가 강제하지 않음) |

---

## 8. 트러블슈팅 (이기종 클러스터 특화)

| 증상 | 조치 |
|---|---|
| `helm install` 이 `namespaces "monitoring" not found` | `monitoring.grafanaDashboards=true` 인데 NS 가 없음 — values-lab 기본은 false. kube-prometheus-stack 설치 후 켤 것 |
| `helm install` 이 hook Job `rag-db-migrate` 실패로 종료 | PostgreSQL 이 5분 내 준비되지 않음(이미지 pull/PVC Pending) 또는 `rag-postgresql-secret` 누락. `kubectl -n rag-app logs job/rag-db-migrate`, `kubectl -n rag-data describe pod postgresql-0`. 원인 해결 후 `helm upgrade` 재실행 |
| PostgreSQL `CrashLoopBackOff`, 로그 `Database is uninitialized and superuser password is not specified` | `rag-postgresql-secret`(rag-data) 누락 — §4.1 ④ |
| 모든 질문이 401 `INVALID_TOKEN` (토큰이 맞는데도) | Secret 파일 미마운트 → 기대 토큰 `""` → **fail-closed 거부**. `kubectl -n rag-app logs deploy/mattermost-bridge | grep startup.outgoing_token_missing`, §4.3 ② |
| 답변이 게시되지 않고 `mattermost_deliveries.status=DEAD_LETTER` | rag-worker 의 `/var/run/secrets/mattermost/<secret_ref>` 파일 없음(Secret 이름 ≠ binding.secret_ref, 또는 `incomingWebhookSecrets` 미등록) / mock-mattermost 미기동. `kubectl -n rag-app logs deploy/rag-worker` |
| rag-api/worker 가 qdrant/pg/redis 에 연결 실패, 전 NS 간 통신 불통 | **NS 라벨 `rag-platform=true` 누락** — `kubectl get ns -L rag-platform`. §4.1 ① |
| 외부에서 `rag.lab.local` 접근 불가 (Ingress 는 ADDRESS 있음) | ① `networkPolicy.ingressController.{namespace,podSelector}` 가 실제 컨트롤러와 불일치(`kubectl -n kube-system get pods -l app.kubernetes.io/name=rke2-ingress-nginx`) ② `/etc/hosts` 미등록 ③ ingressClassName |
| 업로드 500, admin-api 로그 `Read-only file system` | `documents-pvc` 미마운트(chart v1.1) — v1.2 chart 인지 확인 `kubectl -n rag-app get deploy admin-api -o jsonpath='{.spec.template.spec.volumes[*].name}'` |
| 업로드 응답에 `error: "TRIGGER_FAILED[k8s]: ... status=403"` | admin-api ServiceAccount RBAC 누락(`serviceAccounts.adminApi.create`) 또는 `serviceAccountName` 미지정 |
| 업로드 응답 `TRIGGER_FAILED[k8s]: ConnectError` | admin-api → apiserver egress 차단 — `networkPolicy.apiServer.cidrs` 가 P3 IP 가 아님 (`--set` 확인) |
| 색인 Job 은 성공했는데 질문에 "근거를 찾지 못했습니다" | 업로드 시 `allowed_channel_ids` 를 비웠거나 다른 채널 지정 → `document_channel_acl` 없음 → 검색 필터에 절대 매칭 안 됨. `psql -c "select * from document_channel_acl"` 확인 후 재업로드(같은 내용은 409 → 파일 한 글자 수정) |
| 색인 Job `FAILED@EMBEDDING` | embedding-api 응답 확인. v1.2 이전 코드는 요청 키 불일치(`input`/`texts`)로 항상 실패했다 — 이미지 태그가 최신인지 확인 |
| embedding/reranker 가 뜨긴 했는데 답변이 엉뚱함 | 모델 경로 미마운트로 **mock 엔진**으로 기동 — `engine_ready` 로그에 `-mock`. hostPath `/data/bulk/models/{embedding,reranker}/...` 와 `chmod a+rX` 확인 |
| embedding/reranker 최초 기동 CrashLoop | HDD 로딩이 15분(90×10s) 초과 — `appServices.<svc>.startupFailureThreshold` 상향 또는 모델을 `/data/fast/models` 로 이동 |
| vLLM Pod `CreateContainerConfigError`/권한 오류 | NGC 이미지가 root 전제 — `vllm.podSecurityContext: {runAsNonRoot: false, runAsUser: 0}` (values-lab 주석) 로 예외를 명시하고 리포트에 기록(§22.4) |
| vLLM Pod가 P3로 스케줄 시도 / `exec format error` | nodeSelector/toleration 확인. amd64 이미지가 PGX 에, 또는 반대로 스케줄됨 — `kubectl get pod -o wide` |
| PGX에서 `nvidia.com/gpu: 0` | GPU Operator toolkit Pod(pgx) 로그 확인, containerd 재시작. `driver.enabled=false` 유지 |
| vLLM OOM/성능 급락 | 통합 메모리를 OS·타 프로세스와 공유 — PGX 에 다른 워크로드 금지(taint 유지), `--gpu-memory-utilization` 0.85 로 하향 |
| Qdrant 검색 1s 초과 | PVC 가 local-bulk(HDD)에 생성됨 — `kubectl get pvc -n rag-data` 로 SC 확인 후 재생성 |
| PVC가 계속 `Pending` | ① `deploy/k8s/local-path-*.yaml` 의 nodePathMap 노드 이름 불일치(§1.4.3 sed 누락) — `kubectl -n local-path-storage logs deploy/local-path-provisioner-fast` ② `WaitForFirstConsumer` 라 소비 Pod 스케줄 전엔 정상 ③ Pod 가 pgx 로 갔다면 nodePathMap 에 없어 실패 |
| PVC Pending + helper-pod `ImagePullBackOff` | 폐쇄망에서 `busybox:1.36.1` pull 실패 — §1.4.3 의 sed 로 미러 경로 교체 후 provisioner 재시작 |
| **NVMe 용량 부족 / `DiskPressure`, Pod 무더기 Evicted** | `df -h / /data/fast` → NVMe 소진. 원인 1순위는 PVC 가 default SC(local-fast)로 새어 문서가 NVMe 에 적재 — §4.3 ③. 즉시 조치: PVC 삭제 후 local-bulk 로 재생성, `sudo crictl rmi --prune` |
| `/data/bulk` 가 비어 있는데 NVMe 만 참 | HDD 마운트 전에 디렉터리/registry/PVC 를 만든 케이스 — `findmnt /data/bulk`. 마운트 해제 → 루트 FS 잔여물 삭제 → 재마운트 |
| 색인 Job 이 평소보다 훨씬 느림 | HDD 한 대에 문서 원본 + registry + 모델 공존 — 이미지 push/pull, 다중 색인 Job 동시 실행을 피함. `iostat -x 2 /dev/sda` |
| PVC 삭제 후에도 HDD 용량 미반환 | `local-bulk` 는 `Retain` — `kubectl get pv | grep Released` 후 `sudo rm -rf /data/bulk/pvc/pvc-<uid>` |
| PGX 가 이미지 pull 실패 | PGX 의 `/etc/rancher/rke2/registries.yaml` 누락 또는 rke2-agent 미재시작, `/etc/hosts` 의 `registry.local` |
| 노드 간 호출 간헐 지연 | 2.5GbE 협상 확인 `ethtool enpXs0 | grep Speed`, MTU 불일치 |
| `make perf-webhook-burst` 가 전부 401 | `MM_OUTGOING_TOKEN` 미설정(기본 `dev-token`) — §7.2 |
| RKE2 재부팅 후 워크로드 미복귀 | `systemctl status rke2-server`(P3)/`rke2-agent`(PGX), PGX 절전 설정 비활성 |

---

## 9. 확장 과제 (선택)

- **모니터링**: kube-prometheus-stack 설치 후 `monitoring.grafanaDashboards=true` 로 `helm upgrade` — chart 가 `rag-grafana-dashboards` ConfigMap(sidecar 라벨 `grafana_dashboard: "1"`, ACK/단계 latency/큐 깊이/DLQ/근거부족/만족률 패널)을 `monitoring` NS 에 생성합니다. 2-디스크 구성에서는 `node_filesystem_avail_bytes{mountpoint=~"/|/data/.*"}` 알람을 최우선으로 — NVMe 소진이 이 랩의 단일 최대 장애 요인입니다.
- **PGX Grace CPU 활용**: embedding/reranker 를 arm64 로도 빌드(`docker buildx build --platform linux/amd64,linux/arm64`)해 PGX 에 배치하면 색인 처리량 향상. taint 정책 재설계 필요.
- **vLLM 2-replica 모사**: 단일 GPU 에서 MPS/시간분할은 비권장 — HA(NFR-HA-002)는 순차 재기동 테스트로 대체.
- **디스크 1개 추가 시**: `/data/bulk` 에서 **레지스트리를 분리**(`/data/registry`)하는 것이 효과가 가장 큼.
- **PoC 이관 전 코드 과제**(`docs/code-review-2026-09-10.md` §7): Settings→파이프라인 연동, 동기 I/O 제거, 문서 삭제 시 Qdrant 비활성화, mock 엔진 fallback 차단, 100문항 평가셋.

---

## 10. 검증 완료 체크리스트

- [ ] 노드 2대 Ready, 라벨/테인트 적용 (`tier=app`/`tier=llm`), PGX `nvidia.com/gpu: 1`
- [ ] HDD `/data/bulk` 마운트(`findmnt`), NVMe `/data/fast` 준비, StorageClass Bound 테스트 통과(§1.4.3), nodePathMap 치환
- [ ] 이미지 8종 + vLLM arm64 + data 3종 + busybox 레지스트리 push, manifest arch 확인
- [ ] **NS 4종 + `rag-platform=true` 라벨**, Secret 6개(`rag-bridge-secrets`, `rag-postgresql-secret`×3, `mattermost-incoming-*`×2)
- [ ] `helm upgrade --install` 성공(hook `rag-db-migrate` 포함), `alembic current` = `0002_feedback_enabled`
- [ ] 배치 검증 — vLLM 만 pgx, 나머지 p3 (`-o wide`)
- [ ] §4.3 ①~⑧: Secret 파일 마운트, PVC 티어(DB=local-fast, documents=local-bulk), 문서 볼륨 쓰기, **실엔진 기동(`-mock` 없음)**, `/v1/models`, Ingress/NetPol, NVMe 70% 미만
- [ ] seed + qdrant-init 완료
- [ ] E2E: 업로드 → **K8s 색인 Job COMPLETED** → 질문 → mock-mattermost 에 답변+버튼 게시 → 피드백 UP / 위조 401 / 타채널 403
- [ ] 부정 케이스 8종(§5.3) — 빈 토큰 401, 트리거 채널, 격리(CH-001) 포함
- [ ] NetworkPolicy 차단/허용 확인(np-probe), NS 라벨 제거 실험, vLLM 재기동 복원, worker 삭제 시 중복 게시 없음
- [ ] `make lint && make test` green(133), `make test-isolation` green, `make test-integration`(Docker) green
- [ ] `make evaluate` → `reports/evaluation_report.md` 생성, 4지표 목표 대비 판정 기록 (6문항 한계 명시)
- [ ] ACK p95 ≤ 2s / 검색 p95 ≤ 1s 판정, 생성 성능은 참고치 기록
- [ ] 운영과의 의도적 차이(replica, PDB, hostPath, vLLM podSecurityContext 예외, X-Auth-User 클라이언트 신뢰) 리포트 기록

> 이 클러스터에서 green 이면 PoC 환경 이관 시 남는 변수는 사실상 "운영 GPU 성능", "실 Mattermost 연동(Incoming URL·Source CIDR)", "인증 프록시(X-Auth-User 주입)" 셋입니다.
