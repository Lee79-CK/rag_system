# 로컬 2-Node RKE2 클러스터 테스트 가이드 — RAG Platform

> 문서 ID: GUIDE-LOCAL-K8S-TEST-001 (v1.1 — P3 디스크 2개 구성 반영)
> 기준: TDD-RAG-CHATBOT-POC-001 v1.3 + **현행 구현 기준** — 전 서비스 Python 3.12 (uv workspace)
> 정정(v1.1): TDD v1.3 문서는 admin-api를 Java 21 Spring Boot로 기술하지만, **구현된 `apps/admin-api` 는 Python(FastAPI + SQLAlchemy + Alembic)** 입니다. 이 가이드는 구현을 따릅니다.
> 대상 환경:
> - **Master**: Lenovo ThinkStation P3 Tower Gen 2 — Core Ultra 7 265 (x86_64), RAM 128GB, RTX A400 4GB, **NVMe 1TB(OS+RKE2+fast PVC) + HDD 4TB(bulk)** 2-디스크, Ubuntu 24.04
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

### 1.4 스토리지 전략 (P3 디스크 2개 — NVMe 1TB + HDD 4TB)

P3의 물리 디스크는 **NVMe 1TB, HDD 4TB 2개뿐**입니다. 즉 **OS·RKE2·etcd·fast PVC가 모두 같은 NVMe를 공유**하며, 이것이 이 구성의 유일한 진짜 제약입니다. 티어 분리 자체는 유지하되, NVMe는 "용량"이 아니라 "여유 공간 관리"의 대상으로 다룹니다.
l
| 용도 | 디스크 | 경로 | 방식 |
|---|---|---|---|
| OS / RKE2 / etcd / containerd 이미지 | NVMe 1TB | `/`, `/var/lib/rancher` | 기본 (건드리지 않음) |
| PostgreSQL / Qdrant / Redis PVC | **NVMe 1TB** | `/data/fast` | StorageClass `local-fast` (성능 필수) |
| 문서 원본 PVC / 이미지 레지스트리 / 백업 | **HDD 4TB** | `/data/bulk` | StorageClass `local-bulk` |
| 모델 아티팩트 (embedding/reranker) | **HDD 4TB** | `/data/bulk/models` | hostPath 마운트 (§2.2) |
| 모델 아티팩트 (LLM) | PGX SSD 4TB | `/models/llm` | hostPath 마운트 (§2.1) |

> **HDD 2TB(3번째 디스크)가 없는 구성이므로** 레지스트리·문서 원본·모델·백업이 모두 HDD 4TB 한 스핀들을 공유합니다. 용량은 충분하지만 **IO 경합**이 생깁니다 — 대량 색인 Job과 이미지 push/pull을 동시에 돌리지 마세요 (§8 참고).

#### 1.4.1 NVMe 용량 배분 (1TB 단일 디스크)

| 항목 | 배분 | 근거 |
|---|---|---|
| OS(Ubuntu 24.04) + `/var/lib/rancher` (containerd 이미지 + etcd) | ~250GB | amd64 앱 이미지 7종 + 베이스 이미지 누적 |
| `/data/fast` (DB PVC 전용) | **400GB** | 아래 실사용 합계의 4배 여유 |
| 미할당 여유 | ~280GB | DiskPressure 방어선 |

`/data/fast` 실사용 합계 (§4 values-lab 기준): PostgreSQL 20Gi + Qdrant 50Gi + Redis 10Gi = **80Gi 명목**. 로컬 100문항 평가 데이터셋 기준 실사용은 10GB 미만입니다.

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

*(A) 전용 파티션 — 권장.* NVMe에 미할당 공간이 있으면 400GB 파티션을 잘라 루트 파일시스템과 격리합니다. 이러면 PVC가 폭주해도 **kubelet의 nodefs eviction(루트 FS 기준)이 발동하지 않아** 클러스터 전체가 흔들리지 않습니다.

```bash
sudo parted -s /dev/nvme0n1 mkpart primary ext4 <시작>GB <시작+400>GB   # 미할당 영역 확인 후
sudo mkfs.ext4 -L fast /dev/nvme0n1pN && sudo mkdir -p /data/fast
echo "UUID=$(sudo blkid -s UUID -o value /dev/nvme0n1pN) /data/fast ext4 defaults,noatime 0 2" | sudo tee -a /etc/fstab
sudo mount -a && findmnt /data/fast
```

*(B) 루트 파일시스템 위 디렉터리 — 미할당 공간이 없을 때.* 파티션 작업 없이 진행하되, **DB PVC 사용량이 루트 FS 사용량에 그대로 합산**된다는 점을 인지해야 합니다. 루트 FS가 85%를 넘으면 kubelet이 `DiskPressure` 를 걸고 P3의 Pod들을 evict합니다 — 앱 전체가 P3에 있으므로 사실상 클러스터 정지입니다.

```bash
sudo mkdir -p /data/fast && df -h /data/fast     # Avail 500GB 이상이어야 안전
```

> local-path는 hostPath 기반이라 **PVC의 `requests.storage` 를 강제하지 않습니다.** 50Gi를 요청한 Qdrant PVC가 디스크를 400GB까지 쓸 수 있습니다. (B)를 택했다면 `df -h /` 를 평가 실행 전후로 확인하세요.

#### 1.4.3 StorageClass 배포

`deploy/k8s/` 의 두 매니페스트가 local-path-provisioner 인스턴스를 **각각 하나씩** 띄웁니다 (provisioner 이름이 달라 서로 간섭하지 않음).

```bash
# ★ 노드 이름 치환 — 매니페스트의 "p3" 는 예시. 실제 노드 이름으로 바꾼다.
kubectl get nodes -o name
NODE=$(kubectl get node -l ragplatform.io/tier=app -o jsonpath='{.items[0].metadata.name}')
sed -i "s/\"node\": \"p3\"/\"node\": \"$NODE\"/" deploy/k8s/local-path-*.yaml

kubectl apply -f deploy/k8s/local-path-fast.yaml
kubectl apply -f deploy/k8s/local-path-bulk.yaml

kubectl -n local-path-storage get pods
kubectl get sc
# NAME                 PROVISIONER                  RECLAIMPOLICY   VOLUMEBINDINGMODE
# local-fast (default) rancher.io/local-path-fast   Delete          WaitForFirstConsumer
# local-bulk           rancher.io/local-path-bulk   Retain          WaitForFirstConsumer
```

동작 확인 — 실제로 PVC를 하나 만들어 **경로가 맞는 디스크에 생겼는지** 봅니다 (`WaitForFirstConsumer` 이므로 Pod가 있어야 바인딩됩니다):

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

> DB류 PVC를 HDD에 두면 Qdrant 검색 p95 1초 목표가 로컬에서도 깨집니다. **fast(NVMe)/bulk(HDD) 분리를 반드시 유지**하세요. 반대로 문서 원본·모델 PVC가 NVMe로 새면 1TB가 금방 찹니다 — §4의 `storageClassName` 명시 경고를 꼭 확인하세요.

### 1.5 프라이빗 레지스트리 (P3, HDD)

폐쇄망 Harbor를 모사하고 PGX가 이미지를 당겨갈 수 있도록 P3에 registry를 둡니다.

```bash
findmnt /data/bulk || { echo "HDD 미마운트 — §1.4.2 먼저"; exit 1; }   # 미마운트 상태로 띄우면 NVMe에 이미지가 쌓인다
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
# P3에서 — HDD(/data/bulk)에 배치. 두 모델 합쳐 ~5GB로 NVMe를 쓸 이유가 없다.
sudo mkdir -p /data/bulk/models && sudo chown $USER /data/bulk/models
hf download BAAI/bge-m3             --local-dir /data/bulk/models/embedding/bge-m3
hf download BAAI/bge-reranker-v2-m3 --local-dir /data/bulk/models/reranker/bge-reranker-v2-m3
```

> HDD에서 로드하므로 Pod 최초 기동 시 모델 적재가 NVMe 대비 수십 초 느립니다. embedding/reranker의 `startupProbe.failureThreshold` 가 부족해 CrashLoop 하면 §8 표를 참고하세요. 추론 중에는 모델이 페이지 캐시(RAM 128GB)에 상주하므로 **정상 상태 성능에는 영향이 없습니다.**

---

## 3. 이미지 빌드 및 푸시 (P3, amd64 전용)

```bash
cd ~/work/rag-platform
export TAG=$(git rev-parse --short HEAD)
export REG=registry.local:5000

# Python 서비스 6종 (amd64 — P3 로컬 빌드이므로 자동)
# admin-api 도 Python(FastAPI)이라 다른 서비스와 완전히 동일한 절차다 — 별도 JVM 빌드 단계 없음
for app in mattermost-bridge rag-api admin-api embedding-api reranker-api parser-indexer; do
  docker build -f apps/$app/Containerfile -t $REG/rag/$app:$TAG . && docker push $REG/rag/$app:$TAG
done

# admin-web (React/Vite — uv workspace 제외)
docker build -f apps/admin-web/Containerfile -t $REG/rag/admin-web:$TAG apps/admin-web && \
  docker push $REG/rag/admin-web:$TAG
```

> **선행 조건 — Containerfile이 아직 리포에 없습니다.** `apps/*/Containerfile` 은 현재 미작성 상태라 위 루프는 그대로는 실패합니다. 빌드 컨텍스트는 monorepo 루트(uv workspace 해석 때문)이며, 각 서비스는 `uv sync --frozen --package <pkg>` 후 해당 entrypoint(§4 values의 `command`)를 실행하는 형태가 됩니다. `rag-api` 이미지는 rag-worker와 공유합니다(DEC-017 — entrypoint만 다름).

vLLM은 빌드하지 않고 **NVIDIA 제공 arm64 이미지**를 미러링합니다:

```bash
# DGX Spark 지원 vLLM 이미지 (NGC) — arm64 태그 확인 후 미러
# ※ chart의 rag.image 헬퍼가 global.imageTag를 붙이므로 앱과 동일한 $TAG로 태깅한다
docker pull --platform linux/arm64 nvcr.io/nvidia/vllm:latest
docker tag nvcr.io/nvidia/vllm:latest $REG/ai/vllm-arm64:$TAG
docker push $REG/ai/vllm-arm64:$TAG

# 데이터 계층 이미지도 미러 (values-lab.yaml의 data.*.image가 이 경로를 가리킴)
for img in qdrant/qdrant:v1.12.1 postgres:16 redis:7; do
  name=$(basename $img); docker pull $img && docker tag $img $REG/library/$name && docker push $REG/library/$name
done
```

> **검증 습관**: 배포 전 `docker manifest inspect $REG/rag/rag-api:$TAG | grep architecture` — 이기종 클러스터에서 `exec format error`의 90%는 아키텍처 불일치입니다.

---

## 4. 배포 (Helm, values-lab.yaml)

**`deploy/helm/rag-platform/values-lab.yaml` 가 리포지토리에 포함되어 있습니다.** `values-poc.yaml` 위에 겹쳐 쓰는 override 전용 파일이며, 단독으로는 사용하지 않습니다.

```bash
helm upgrade --install rag-platform deploy/helm/rag-platform \
  -f deploy/helm/rag-platform/values-poc.yaml \
  -f deploy/helm/rag-platform/values-lab.yaml \
  --set global.imageTag=$TAG
```

담고 있는 내용 — 운영(PoC)과 달라지는 지점은 전부 파일 주석에 근거를 남겼습니다.

| 항목 | 운영(values-poc) | 랩(values-lab) | 이유 |
|---|---|---|---|
| 레지스트리 | `harbor.internal` | `registry.local:5000` | §1.5 |
| 앱 replica / PDB | 2 / `minAvailable: 1` | 1 / 해제(`null`) | P3 20코어. replica 1에 PDB를 두면 rollout이 막힘 |
| rag-worker | 2 | 2 (유지) | 큐 재처리 시나리오(§6) 검증에 필요 |
| vLLM replica | `[llm-0, llm-1]` | `[llm-0]` | GPU 노드 1대 |
| vLLM 배치 | — | `nodeSelector: tier=llm` + `dedicated=llm` toleration | 이기종 배치의 핵심 |
| `--max-num-seqs` | 16 | 8 | GB10 대역폭 |
| 모델 볼륨 | `models-pvc` | **hostPath** (`/data/bulk/models`, vLLM은 `/models`) | GPU 노드와 앱 노드가 달라 단일 PVC 공유 불가 |
| 데이터 계층 | qdrant 500Gi / pg 200Gi | 50 / 20 / 10Gi + `local-fast` | NVMe 1TB 공유 (§1.4.1) |
| 서비스 URL | (미지정 = localhost) | `extraEnv` 로 in-cluster DNS 주입 | chart 기본값이 localhost |

핵심 오버라이드 발췌:

```yaml
# ---- 스케줄링 ----
nodeSelector: { kubernetes.io/arch: amd64 }     # 전역 기본 = P3

vllm:
  replicas: [llm-0]
  image: ai/vllm-arm64                          # $REG/ai/vllm-arm64:$TAG 로 미러 (§3)
  nodeSelector: { ragplatform.io/tier: llm }
  tolerations: [{ key: dedicated, value: llm, operator: Equal, effect: NoSchedule }]
  modelHostPath: /models                        # PGX 로컬 (모델 실체 /models/llm/main)
  resources: { requests: { cpu: "8", memory: 32Gi }, limits: { nvidia.com/gpu: 1 } }

modelStorage:
  create: false                                 # PVC 대신 hostPath → 빈 models-pvc 생성 안 함
  hostPath: /data/bulk/models                   # embedding/reranker/indexer 공용 (P3)

# ---- 스토리지 티어 (★ 2-디스크 구성의 핵심 — 생략 금지) ----
# 데이터 계층 → NVMe. 운영값(qdrant 500Gi / pg 200Gi)은 1TB NVMe에 과대하므로 축소
data:
  storageClass: local-fast         # qdrant/postgresql/redis 공통
  qdrant:     { storage: 50Gi }
  postgresql: { storage: 20Gi }
  redis:      { storage: 10Gi }

# 문서 원본·모델 PVC → HDD. 지정하지 않으면 default SC(local-fast=NVMe)로 새어 들어간다
documentStorage: { storageClass: local-bulk, size: 500Gi }
```

> **chart 지원 여부 (v1.1에서 반영 완료).** `documentStorage` / `modelStorage` / `data.storageClass` 키는 chart에 구현되어 있습니다 — `templates/pvcs.yaml`(models-pvc, documents-pvc)과 `templates/data.yaml`(volumeClaimTemplates)이 값을 받아 `storageClassName` 을 렌더합니다. 서비스별로 다르게 두려면 `data.<svc>.storageClass` 로 개별 override 합니다 (서비스별 값이 `data.storageClass` 보다 우선).
>
> 기본값은 모두 `""` 이며 이때는 필드 자체가 렌더되지 않아 **클러스터 default SC를 따릅니다** — 즉 `values-poc.yaml`(운영, NFS 전제) 동작은 이전과 동일합니다.
>
> **이 랩에서 위 세 줄을 빠뜨리면**, 1Ti짜리 `documents-pvc` 가 default인 `local-fast`(NVMe)로 갑니다. local-path는 용량을 강제하지 않으므로 **바인딩은 성공하고 NVMe만 조용히 차오릅니다.** 배포 직후 반드시 확인하세요:
>
> ```bash
> kubectl get pvc -A -o custom-columns='NS:.metadata.namespace,NAME:.metadata.name,SC:.spec.storageClassName,SIZE:.spec.resources.requests.storage'
> # qdrant/postgresql/redis(data-*) → local-fast, documents-pvc → local-bulk
> # models-pvc 는 values-lab 에서 modelStorage.create=false 이므로 생성되지 않는 것이 정상
> ```
>
> 참고로 `documents-pvc` 는 `ReadWriteMany` 입니다. local-path는 본래 RWX를 보장하지 않지만, **이 랩에서는 앱 Pod가 전부 P3 한 노드에 고정되므로 동일 hostPath를 공유해 동작합니다.** 노드가 늘어나는 순간 깨지는 구성이라는 점만 기록해 두세요 (운영은 NFS — DEC-004).

### 4.1 Secret 생성 및 설치

```bash
kubectl create ns rag-app rag-ai rag-data rag-ingestion

kubectl -n rag-app create secret generic rag-bridge-secrets \
  --from-literal=outgoing-token='lab-outgoing-token' \
  --from-literal=feedback-signing-key="$(python3 -c 'import secrets;print(secrets.token_hex(32),end="")')"
kubectl -n rag-app create secret generic mattermost-incoming-rag-cloud-ops \
  --from-literal=url='http://mock-mattermost.rag-app.svc:9099/hooks/local'

# 모델 hostPath 는 fsGroup 이 적용되지 않는다 — Pod(runAsUser 10001) 가 읽도록 권한 부여
sudo chmod -R a+rX /data/bulk/models          # P3
ssh pgx 'sudo chmod -R a+rX /models'          # PGX

helm dependency update deploy/helm/rag-platform
helm upgrade --install rag-platform deploy/helm/rag-platform \
  -f deploy/helm/rag-platform/values-poc.yaml \
  -f deploy/helm/rag-platform/values-lab.yaml \
  --set global.imageTag=$TAG

# 상태 확인 — vLLM은 32B 로딩에 최대 10분 (startupProbe 설계 범위)
kubectl get pods -A -l app.kubernetes.io/part-of=rag-platform -o wide
kubectl -n rag-ai logs -f deploy/vllm-llm-0 | grep -i "loading\|ready"
```

`-o wide`로 **배치 검증**: vLLM만 pgx, 나머지 전부 p3에 스케줄되었는지 확인합니다.

### 4.2 DB Migration / Seed / Qdrant 초기화

스키마 소유자는 **admin-api의 Alembic** 입니다 (`apps/admin-api/src/admin/db/migrations`, 리비전 `0001_initial` → `0002_feedback_enabled`).

> ⚠️ **자동 실행되지 않습니다.** `admin/main.py` 에는 기동 시 마이그레이션 훅이 없습니다 — Pod가 Running이어도 테이블은 비어 있을 수 있습니다. 아래를 **명시적으로 1회** 실행하세요. (반복 배포를 자동화하려면 Helm `pre-install/pre-upgrade` hook Job으로 감싸는 것이 다음 과제입니다.)

```bash
# 1) migration — admin-api Pod 안에서 실행 (이미지에 alembic 포함, DB 접근 경로도 동일)
kubectl -n rag-app exec deploy/admin-api -- \
  alembic -c src/admin/db/migrations/alembic.ini upgrade head

# 적용 결과 확인
kubectl -n rag-app exec deploy/admin-api -- \
  alembic -c src/admin/db/migrations/alembic.ini current
# 0002_feedback_enabled (head) 가 나와야 정상

# 2) Seed + Qdrant collection (port-forward 경유, 로컬 make 사용)
kubectl -n rag-data port-forward svc/postgresql 5432:5432 &
kubectl -n rag-data port-forward svc/qdrant 6333:6333 &
make seed && make qdrant-init
```

`alembic.ini` 경로는 이미지의 WORKDIR 기준 상대 경로입니다 — Containerfile 작성 시 확정되므로, 컨테이너에서 한 번 `find / -name alembic.ini` 로 확인해 두면 이후가 편합니다. Pod 내 실행이 막히면(readOnlyRootFilesystem 등) port-forward 상태에서 로컬로 대체할 수 있습니다:

```bash
DATABASE_URL=postgresql+psycopg://rag:rag-dev-only@localhost:5432/rag \
  uv run --package admin-api alembic -c apps/admin-api/src/admin/db/migrations/alembic.ini upgrade head
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

전 서비스가 Python 단일 스택이므로 admin-api 테스트도 루트 `make test` 에 포함됩니다 — 별도 빌드 도구 호출이 없습니다.

```bash
make lint && make test     # ruff + mypy, 전체 pytest (admin-api 포함)

# 통합/격리 — 클러스터 인프라를 직접 사용 (port-forward 상태에서)
make test-integration      # testcontainers (Docker 필요)
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
# ACK p95 ≤ 2s — 이 환경에서도 그대로 유효한 목표. BRIDGE_URL 로 Ingress를 가리킨다
BRIDGE_URL=http://rag.lab.local make perf-webhook-burst

# 동시 6 부하는 별도 make 타깃이 없다 — locust 인자를 직접 지정 (Makefile의 perf-webhook-burst와 동일 파일)
uv run locust -f tests/performance/locustfile.py --headless -u 6 -r 6 -t 5m \
  --host http://rag.lab.local
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
| PVC가 계속 `Pending` | ① `deploy/k8s/local-path-*.yaml` 의 nodePathMap 노드 이름 불일치(§1.4.3 sed 누락) — provisioner 로그 확인: `kubectl -n local-path-storage logs deploy/local-path-provisioner-fast` ② `WaitForFirstConsumer` 라 소비 Pod가 스케줄되기 전엔 정상적으로 Pending ③ Pod가 pgx로 갔다면 nodePathMap에 없어 실패 — nodeSelector 확인 |
| PVC Pending + helper-pod `ImagePullBackOff` | 폐쇄망에서 `busybox:1.36.1` pull 실패 — ConfigMap `helperPod.yaml` 과 Deployment `--helper-image` 를 `registry.local:5000/library/busybox:1.36.1` 로 교체 후 provisioner 재시작 |
| **NVMe 용량 부족 / 노드 `DiskPressure`, Pod 무더기 Evicted** | 2-디스크 구성의 핵심 리스크. `df -h / /data/fast` → NVMe 소진. 원인 1순위는 **PVC가 default SC(local-fast)로 새어 문서/모델이 NVMe에 적재**된 것 — §4 경고의 `storageClassName` 검증 명령 실행. 즉시 조치: 해당 PVC 삭제 후 local-bulk로 재생성, `sudo crictl rmi --prune` 로 미사용 이미지 정리 |
| `/data/bulk` 가 비어 있는데 NVMe만 참 | HDD 마운트 전에 디렉터리/registry/PVC를 만든 케이스 — `findmnt /data/bulk` 로 확인. 마운트가 나중에 되면 기존 데이터가 가려짐. 마운트 해제 → 루트 FS의 `/data/bulk` 잔여물 삭제 → 재마운트 |
| 색인 Job이 평소보다 훨씬 느림 | HDD 4TB 한 대에 문서 원본 + registry + 모델이 공존 — 이미지 push/pull, 다중 색인 Job 동시 실행을 피하고 순차 실행. `iostat -x 2 /dev/sda` 로 `%util` 확인 |
| PVC 삭제 후에도 HDD 용량 미반환 | `local-bulk` 는 `reclaimPolicy: Retain` — `kubectl get pv \| grep Released` 확인 후 `sudo rm -rf /data/bulk/pvc/pvc-<uid>` 수동 정리 |
| embedding/reranker 최초 기동 CrashLoop | HDD에서 모델 로드가 느려 startupProbe 초과 — `failureThreshold` 상향 또는 모델을 `/data/fast/models` 로 이동(NVMe 여유 확인 후) |
| PGX가 이미지 pull 실패 | PGX의 `/etc/rancher/rke2/registries.yaml` 누락 또는 rke2-agent 미재시작 |
| 노드 간 호출 간헐 지연 | 2.5GbE 협상 확인 `ethtool enpXs0 \| grep Speed`, MTU 불일치 확인 |
| 테이블 없음 / admin-api 500 (`relation ... does not exist`) | Alembic이 **자동 실행되지 않는다** — §4.2의 `alembic upgrade head` 를 돌렸는지 확인. `alembic current` 가 비어 있으면 미적용 |
| `alembic upgrade` 가 DB 연결 실패 | Pod env의 `POSTGRES_HOST` 확인(`kubectl -n rag-app exec deploy/admin-api -- env \| grep POSTGRES`). values-lab의 `extraEnv` 누락이면 기본값 localhost로 붙는다 |
| RKE2 재부팅 후 워크로드 미복귀 | `systemctl status rke2-server`(P3)/`rke2-agent`(PGX), PGX 절전 설정 비활성 |

---

## 9. 확장 과제 (선택)

- **PGX Grace CPU 활용**: embedding/reranker를 arm64로도 빌드(`docker buildx build --platform linux/amd64,linux/arm64`)해 PGX에 배치하면 색인 처리량 향상. 단 taint 정책 재설계 필요.
- **vLLM 2-replica 모사**: PGX 단일 GPU에서 MPS/시간분할은 비권장 — HA 시나리오(NFR-HA-002)는 순차 재기동 테스트로 대체.
- **모니터링**: kube-prometheus-stack + TDD §12 metric 대시보드를 이 클러스터에 먼저 구축해 두면 PoC 환경 이관이 빠릅니다. 2-디스크 구성에서는 **node-exporter의 `node_filesystem_avail_bytes{mountpoint=~"/|/data/.*"}` 알람을 최우선**으로 걸어두세요 — NVMe 소진이 이 랩의 단일 최대 장애 요인입니다.
- **디스크 1개 추가 시**: SATA HDD/SSD를 한 장 더 꽂으면 `/data/bulk` 에서 **레지스트리를 분리**(`/data/registry`)하는 것이 가장 효과가 큽니다. 색인 Job의 문서 읽기와 이미지 push/pull IO 경합이 사라집니다. `deploy/k8s/local-path-bulk.yaml` 을 복사해 세 번째 클래스를 만들거나, registry 볼륨만 새 마운트로 옮기면 됩니다.

---

## 10. 검증 완료 체크리스트

- [ ] 노드 2대 Ready, 라벨/테인트 적용 (`tier=app`/`tier=llm`)
- [ ] PGX `nvidia.com/gpu: 1` allocatable
- [ ] HDD 4TB `/data/bulk` 마운트 확인 (`findmnt /data/bulk`), NVMe `/data/fast` 준비
- [ ] StorageClass `local-fast`/`local-bulk` Bound 테스트 통과 (§1.4.3), nodePathMap 노드 이름 치환 완료
- [ ] **전 PVC의 StorageClass 검증** — DB류=local-fast, documents/models=local-bulk (§4 경고)
- [ ] 배포 후 `df -h / /data/fast /data/bulk` — NVMe 사용률 70% 미만
- [ ] amd64 앱 이미지 + arm64 vLLM 이미지 레지스트리 push, manifest arch 확인
- [ ] Helm 배포 — vLLM만 pgx, 나머지 p3 배치 확인 (`-o wide`)
- [ ] **Qwen3-32B 로딩 완료** (startupProbe 내), `/v1/models` 응답
- [ ] **Alembic `upgrade head` 수동 실행** + `alembic current` = `0002_feedback_enabled` 확인, seed + qdrant-init
- [ ] Ingress 경유 E2E: 질문→답변(+피드백 버튼)→피드백 UP/위조 401
- [ ] NetworkPolicy 차단 경로 확인, vLLM 재기동 복원 확인
- [ ] `make test-isolation` green
- [ ] **`make evaluate` 리포트 생성 — 품질 5지표 목표 대비 판정, SIMILARITY_THRESHOLD 확정**
- [ ] ACK p95 ≤ 2s / 검색 p95 ≤ 1s 판정, 생성 성능은 참고치 기록

> 이 클러스터에서 green이면 PoC 환경 이관 시 남는 변수는 사실상 "운영 GPU 성능"과 "실 Mattermost 연동" 둘뿐입니다.
