# 로컬 2-Node RKE2 클러스터 테스트 가이드 — RAG Platform

> 문서 ID: GUIDE-LOCAL-K8S-TEST-001 (v2.0 — Web Chat 전환: Mattermost 제거 / v1.1 — P3 디스크 2개 구성 반영)
> 기준: TDD-RAG-CHATBOT-POC-001 + **현행 구현 기준** — 전 백엔드 Python 3.12 (uv workspace), 사용자 UI `apps/chat-web`(Next.js standalone), Helm chart `deploy/helm/rag-platform`
> 변경(v2.0): 사용자 접점이 Mattermost 에서 **Web Chat(chat-web + chat-gateway)** 으로 바뀌었습니다. Mattermost 서버/Outgoing Webhook 설정, mock-mattermost, `rag-bridge-secrets` 는 더 이상 필요 없고, 대신 **`rag-chat-secrets` + Ingress(TLS)** 를 준비합니다. (Mattermost 는 v2.0 에서 제거)
> 이월(v1.2 — 2026-09-10 코드 리뷰, `docs/code-review-2026-09-10.md`): **Containerfile(8종) · Alembic hook Job(`rag-db-migrate`) · admin-api RBAC/K8s 색인 트리거(`INDEX_JOB_TRIGGER=k8s`) · Namespace 라벨(`rag-platform=true`) · 배포 후 검증(§4.3)** 반영분이 v2.0 에 이월되었습니다. v1.2 의 Mattermost 전용 절차는 제외했습니다.
> 변경(v2.1): 한글 PDF(`docs/pdf/*` 공공 가이드라인 5종) 기준으로 **임베딩 모델을 KURE-v1 로, PDF 파서를 PyMuPDF + 페이지 단위 pdfplumber 대체 + 한글 정규화로** 갱신했습니다 — 선정 근거·재색인 절차는 §5.1.2. 임베딩 입력이 FlagEmbedding 기본 512 토큰에서 잘리던 문제도 수정(`EMBEDDING_MAX_LENGTH=2048`).
> 변경(v2.2): LLM 모델을 PGX 의 **`/home/cheolkyulee/models/<모델 디렉터리>`** 에서 로딩하도록 바꾸고(현재 `Qwen3.8-27B-FP8`), **모델 교체를 `vllm.modelDir` 값 하나로** 할 수 있게 했습니다(chart 가 `--model=/models/<modelDir>` 를 생성) — §2.1.1.
> 정정(v1.1): TDD v1.3 문서는 admin-api를 Java 21 Spring Boot로 기술하지만, **구현된 `apps/admin-api` 는 Python(FastAPI + SQLAlchemy + Alembic)** 입니다. 이 가이드는 구현을 따릅니다.
> 대상 환경:
> - **Master(P3)**: Lenovo ThinkStation P3 Tower Gen 2 — Core Ultra 7 265 (x86_64), RAM 128GB, RTX A400 4GB, **NVMe 1TB(OS+RKE2+fast PVC) + HDD 4TB(bulk)**, Ubuntu 24.04
> - **Worker(PGX)**: Lenovo ThinkStation PGX (NVIDIA DGX Spark OEM) — GB10 Grace Blackwell (**ARM64/aarch64**), 통합 메모리 128GB, SSD 4TB
> - RKE2 설치 완료 (P3=server, PGX=agent), 노드 간 2.5GbE, Docker(P3, 이미지 빌드용)

---

## 0. 이 환경이 검증하는 범위 (노트북 가이드와의 차이)

| 검증 항목 | 가능 여부 | 비고 |
|---|---|---|
| Helm 배포 / NetworkPolicy / Ingress / Probe / Secret 마운트 / hook Job / RBAC 등 K8s 매니페스트 전체 | ✅ | **PoC 배포와 동일 chart·동일 방식** — 이 환경의 최대 가치 |
| RAG 파이프라인 전체 (E2E) | ✅ | Ingress 경유 — 업로드 → K8s 색인 Job → 브라우저 Web Chat (로그인 → 스트리밍 답변 → 피드백) |
| Web Chat WebSocket(socket.io `/ws`) Ingress 경유 동작 | ✅ | ingress-nginx websocket + timeout annotation, TLS |
| **답변 품질 (Qwen3.8-27B 실물)** | ✅ | PGX 통합 메모리 128GB — 27B FP8(~29GB) 여유 구동, KV cache 공간 충분 |
| `make evaluate` 품질 평가 | ⚠️ 부분 | **현재 데이터셋 6문항**(`tests/evaluation/dataset/q001~q006`), 지표 4종(Recall@10 · Citation Precision · 무근거 안전응답 · 근거 응답률). **Faithfulness/LLM-judge 는 미구현** — 100문항·judge 는 작성 과제 |
| Channel 격리 (CH-001~010) | ✅ | `make test-isolation` 은 **클러스터와 무관한 로컬 pytest**(in-memory fake). 실 Qdrant 검증(`test_ch_qdrant.py`)은 Docker(testcontainers) 필요 — P3 에서 `make test-integration` |
| 성능 목표 수치 (p95 30s @ 동시 10~15) | ⚠️ 참고치 | GB10 메모리 대역폭(~273GB/s) 특성상 decode 속도는 운영 GPU(H100 등)와 다름. **동시 4~8 기준 경향 측정** |
| GPU 2장 이중화 (vLLM ×2) | ❌ | GPU 노드 1대 — replica 1로 축소 |

**아키텍처 핵심 제약** — 이 클러스터는 이기종(x86_64 + aarch64)입니다:

| 구분 | 배치 노드 | 이유 |
|---|---|---|
| vLLM (Qwen3.8-27B-FP8) | **PGX (arm64)** | GPU/통합 메모리. NVIDIA ARM64 컨테이너 사용 (vLLM ≥ 0.17.0) |
| 그 외 전부 (chat-gateway, chat-web, rag-api/worker, admin-api/web, embedding, reranker, qdrant, pg, redis, indexer Job) | **P3 (amd64)** | x86 단일 아키텍처로 이미지 빌드 단순화. Core Ultra 7 + 128GB로 충분 |
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
echo $P3_IP     # §4.2 의 networkPolicy.apiServer.cidrs 와 /etc/hosts 에 사용
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
| 모델 아티팩트 (LLM) | PGX SSD 4TB | `/home/cheolkyulee/models/<모델>` | hostPath 마운트 (§2.1) — 모델별 디렉터리, `vllm.modelDir` 로 선택 |

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

> DB류 PVC를 HDD에 두면 Qdrant 검색 p95 1초 목표가 로컬에서도 깨집니다. **fast(NVMe)/bulk(HDD) 분리를 반드시 유지**하세요. 문서 원본 PVC가 NVMe로 새면 1TB가 금방 찹니다 — §4.3 ③ 의 `storageClassName` 검증을 꼭 실행하세요.

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

echo "${P3_IP} registry.local" | sudo tee -a /etc/hosts   # 양쪽 노드 + 접속 PC

# P3 의 Docker 도 insecure registry 로 등록 (push 용). 빠뜨리면 make push-images 가
#   "http: server gave HTTP response to HTTPS client" 로 실패한다.
# daemon.json 이 이미 있으면 덮어쓰지 말고 "insecure-registries" 키만 병합할 것.
[ -s /etc/docker/daemon.json ] && cat /etc/docker/daemon.json
sudo tee /etc/docker/daemon.json <<'EOF'
{
  "insecure-registries": ["registry.local:5000"]
}
EOF
sudo systemctl restart docker            # registry 컨테이너는 --restart=always 라 자동 복구
docker info | grep -A3 "Insecure Registries"   # registry.local:5000 이 보여야 함
curl -s http://registry.local:5000/v2/_catalog # {"repositories":[...]} 응답 확인
```

---

## 2. 모델 아티팩트 배치

### 2.1 PGX — LLM (Qwen3.8-27B 실물 구동)

랩 LLM 은 **`Qwen/Qwen3.8-27B-FP8`** (Apache-2.0) 이며, PGX 의 **`/home/cheolkyulee/models/Qwen3.8-27B-FP8`** 에 받아 두었습니다(≈29GB). dense 27B · FP8 체크포인트로 통합 메모리 128GB 에 KV cache 포함 여유 있게 적재됩니다.

**모델 디렉터리 구조 — 모델별 하위 디렉터리를 나란히 둔다**

```text
/home/cheolkyulee/models/            ← values-lab  vllm.modelHostPath  (컨테이너 /models 로 마운트, readOnly)
├── Qwen3.8-27B-FP8/                 ← values-lab  vllm.modelDir (현재)  → --model=/models/Qwen3.8-27B-FP8
└── Qwen3.8-27B-NVFP4/               ← 교체 후보 (같은 qwen3_5 계열, compressed-tensors NVFP4 ≈22GB)
```

chart 는 `vllm.modelDir` 로 `--model=/models/<modelDir>` 를, `vllm.servedModelName`(`internal-rag-llm`)으로 `--served-model-name` 을 **직접 생성**합니다. `vllm.args` 에는 이 둘을 넣지 않습니다(넣으면 `helm template` 단계에서 실패하도록 막아 두었습니다). 서빙 이름이 고정이라 **모델을 바꿔도 rag-api/worker 설정은 그대로**입니다.

| 항목 | 값 | 랩 설정에 미치는 영향 |
|---|---|---|
| 아키텍처 | `Qwen3_5ForConditionalGeneration` (`qwen3_5`) — 64층 중 48층 linear attention 하이브리드 | **vLLM ≥ 0.17.0 필요** (§3 이미지 태그 확인). 구버전은 `architecture not supported` 로 기동 실패 |
| 양자화 | `config.json` 의 `quantization_config.quant_method=fp8` | vLLM 이 자동 인식 — `--quantization` 지정 불필요 |
| 모달리티 | vision-language (이미지/비디오 입력 가능) | 텍스트 RAG 이므로 `--language-model-only` 로 vision tower 미적재 → 메모리·KV cache 확보 |
| thinking | **기본 on** (`<think>…</think>` 후 답변) | 앱이 요청마다 `chat_template_kwargs.enable_thinking=false` 전송(`LLM_ENABLE_THINKING=false`, 기본값) + vLLM `--reasoning-parser=qwen3` 로 혹시 켜져도 추론이 `content` 에 섞이지 않게 분리 |
| 컨텍스트 | 네이티브 262,144 (YaRN 으로 1M) | 랩은 `--max-model-len=16384` — RAG 예산(MAX_CONTEXT_TOKENS 8192 + 출력 1024)에 충분 |
| MTP head | `mtp.safetensors` 포함 | (선택) `--speculative-config` 로 디코드 가속 — values-lab 주석 참고 |
| 서빙 이름 | `--served-model-name=internal-rag-llm` (`vllm.servedModelName`, 변경 없음) | rag-api/worker 설정 변경 불필요 |

```bash
# PGX에서 — 이미 받아 둔 상태 확인
ls /home/cheolkyulee/models/Qwen3.8-27B-FP8/{config.json,tokenizer.json,model.safetensors.index.json}
python3 -c "import json;c=json.load(open('/home/cheolkyulee/models/Qwen3.8-27B-FP8/config.json'));print(c['architectures'],c['quantization_config']['quant_method'])"
# → ['Qwen3_5ForConditionalGeneration'] fp8

# Pod 읽기 권한 — hostPath 에는 fsGroup 이 적용되지 않으므로 other 읽기(+디렉터리 실행)가 필요
chmod -R a+rX /home/cheolkyulee/models
```

> **권한 메모**: hostPath 는 `/home/cheolkyulee/models` 자체를 컨테이너 `/models` 로 bind mount 하므로 상위 홈 디렉터리(`drwxr-x---`)의 권한은 영향이 없습니다. 모델 디렉터리·파일만 `a+rX` 이면 비루트(uid 10001) vLLM 이 읽을 수 있습니다.
> **경로 바꾸기**: 다른 계정/디스크로 옮기면 `values-lab.yaml` 의 `vllm.modelHostPath` 만 바꾸면 됩니다. hostPath `type: Directory` 라 경로가 없으면 Pod 가 `ContainerCreating`(`hostPath type check failed`)에 머뭅니다.

> **샘플링**: 모델 권장값(non-thinking)은 `temperature=0.7, top_p=0.8, presence_penalty=1.5` 이지만, RAG 는 근거 충실도를 우선해 앱 기본 `LLM_TEMPERATURE=0.2` 를 유지합니다. 답변이 반복적이면 `LLM_TEMPERATURE` 를 0.5~0.7 로 올려 §7 평가로 비교하세요.
> **토크나이저**: rag-api/worker 는 P3 에서 돌고 모델 파일은 PGX 에만 있으므로 토큰 수는 근사 카운터로 계산됩니다(기존과 동일). 정확한 예산이 필요하면 현재 모델의 토크나이저 파일(`tokenizer.json`, `tokenizer_config.json`, `vocab.json`, `merges.txt`)만 P3 `/data/bulk/models/llm/main` 에 복사하세요(rag-api `TOKENIZER_PATH=/models/llm/main`). 모델을 바꾸면 이 복사본도 함께 교체합니다.

#### 2.1.1 LLM 모델 교체 (새 모델 다운로드 시)

모델 교체는 **새 디렉터리를 나란히 받고 → `vllm.modelDir` 만 바꿔 `helm upgrade`** 입니다. 기존 디렉터리를 덮어쓰지 않으므로 파일이 섞여 기동 실패하는 일이 없고, **되돌리기는 값만 원복**하면 됩니다.

```bash
# 1) PGX — 새 모델을 별도 디렉터리로 다운로드 (폐쇄망은 해시 검증된 반입 아티팩트 복사)
hf download <org>/<NewModel> --local-dir /home/cheolkyulee/models/<NewModel>
chmod -R a+rX /home/cheolkyulee/models/<NewModel>
python3 -c "import json;c=json.load(open('/home/cheolkyulee/models/<NewModel>/config.json'));print(c['architectures'],c.get('quantization_config',{}).get('quant_method'))"

# 2) P3 — 렌더 확인 후 교체. 영구 반영은 values-lab.yaml 의 vllm.modelDir 를 수정(SSOT), 일시 A/B 는 --set
helm template rag-platform deploy/helm/rag-platform -f deploy/helm/rag-platform/values-poc.yaml \
  -f deploy/helm/rag-platform/values-lab.yaml --set vllm.modelDir=<NewModel> -s templates/vllm.yaml | grep -- --model=
helm upgrade --install rag-platform deploy/helm/rag-platform \
  -f deploy/helm/rag-platform/values-poc.yaml -f deploy/helm/rag-platform/values-lab.yaml \
  --set global.imageTag=$TAG --set "networkPolicy.apiServer.cidrs={${P3_IP}/32}" \
  --set vllm.modelDir=<NewModel>          # values-lab 을 수정했다면 이 줄은 생략

# 3) 확인 — args 가 바뀌어 vLLM Pod 가 재생성된다 (maxSurge 0 → 기존 Pod 종료 후 새 모델 로딩, 그동안 질문은 오류 안내)
kubectl -n rag-ai get deploy vllm-llm-0 -o jsonpath='{.spec.template.metadata.annotations.ragplatform\.io/llm-model}'; echo
kubectl -n rag-ai logs -f deploy/vllm-llm-0 | grep -iE "loading|ready|error"
kubectl -n rag-app exec deploy/rag-api -- python -c "import httpx;print(httpx.get('http://vllm-service.rag-ai:8000/v1/models',timeout=10).json()['data'][0]['root'])"
# → /models/<NewModel>   (id 는 여전히 internal-rag-llm)

# 4) 품질 비교 — §7.1 평가를 모델별 리포트로 남긴다 (예: reports/eval_ko_pdf_<NewModel>.md)
# 되돌리기: --set vllm.modelDir=Qwen3.8-27B-FP8 (또는 values-lab 원복) 후 helm upgrade
```

새 모델이 **다른 계열**이면 `values-lab.yaml` 의 `vllm.args` 중 모델 의존 항목을 함께 점검하세요:

| 점검 항목 | Qwen3.8 기준 | 다른 모델일 때 |
|---|---|---|
| vLLM 버전 | ≥ 0.17.0 (`qwen3_5`) | 새 아키텍처 지원 버전인지 §3 명령으로 확인 |
| `--language-model-only` | vision-language 이라 필요 | 텍스트 전용 모델이면 인자 제거(미지원 경고/오류 가능) |
| `--reasoning-parser=qwen3` | thinking 모델 | 비-thinking 모델이면 제거, 다른 계열은 해당 parser(예: `deepseek_r1`) |
| `LLM_ENABLE_THINKING=false` (rag-api/worker) | chat template 이 `enable_thinking` 지원 | 지원하지 않는 템플릿이면 무시되므로 그대로 둬도 무방 |
| `--max-model-len` / `--gpu-memory-utilization` | 16384 / 0.90 | 모델 크기·네이티브 컨텍스트에 맞춰 조정(OOM 시 §8) |
| 토크나이저 복사본 | `/data/bulk/models/llm/main` (선택) | 새 모델 토크나이저로 교체 |

> 예: 같은 계열인 **`Qwen3.8-27B-NVFP4`**(이미 `/home/cheolkyulee/models` 에 있음, ≈22GB)는 args 변경 없이 `vllm.modelDir=Qwen3.8-27B-NVFP4` 만으로 교체됩니다. NVFP4(`compressed-tensors`)는 Blackwell(GB10) FP4 경로를 쓰므로 vLLM 이미지가 해당 커널을 포함하는지 로딩 로그로 확인하고, FP8 대비 품질은 §7 평가로 비교하세요.
> 사용하지 않는 모델 디렉터리는 롤백 대상이 없을 때 `rm -rf /home/cheolkyulee/models/<OldModel>` 로 정리합니다(PGX SSD 4TB — 여유는 충분).

### 2.2 P3 — Embedding / Reranker (CPU, amd64)

```bash
# P3에서 — HDD(/data/bulk)에 배치. 세 모델 합쳐 ~7GB로 NVMe를 쓸 이유가 없다.
sudo mkdir -p /data/bulk/models && sudo chown $USER /data/bulk/models
# 임베딩 — 랩 기본 KURE-v1 (한글 파인튜닝 bge-m3, MIT, §5.1.2). values-lab EMBEDDING_MODEL_PATH=/models/embedding/kure-v1
hf download nlpai-lab/KURE-v1       --local-dir /data/bulk/models/embedding/kure-v1
# 비교 기준선(A/B, §5.1.2) — 경로만 바꿔 helm upgrade + 재색인하면 전환된다
hf download BAAI/bge-m3             --local-dir /data/bulk/models/embedding/bge-m3
hf download BAAI/bge-reranker-v2-m3 --local-dir /data/bulk/models/reranker/bge-reranker-v2-m3
sudo chmod -R a+rX /data/bulk/models
```

> KURE-v1 디렉터리에는 bge-m3 의 `colbert_linear.pt`/`sparse_linear.pt` 가 없어 embedding-api 기동 로그에 FlagEmbedding 경고 `The parameters of colbert_linear and sparse linear is new initialize` 가 한 번 찍힙니다. **dense 벡터(CLS)만 쓰므로 정상**입니다.

> HDD에서 로드하므로 Pod 최초 기동 시 모델 적재가 NVMe 대비 수십 초 느립니다. values-lab 은 embedding/reranker 의 `startupFailureThreshold: 90`(×10s = 15분) 을 두었습니다. 추론 중에는 모델이 페이지 캐시(RAM 128GB)에 상주하므로 **정상 상태 성능에는 영향이 없습니다.**
>
> ⚠️ embedding/reranker 는 모델 디렉터리가 없으면 **조용히 mock 엔진(결정론적 난수 벡터)으로 기동**합니다(`engine.py build_engine`). 배포 후 로그의 `engine_ready` 이벤트에 `-mock` 접미가 없는지 반드시 확인하세요 (§4.3 ⑤).

---

## 3. 이미지 빌드 및 푸시 (P3, amd64 전용)

**Containerfile 은 앱별로 리포에 포함되어 있습니다.** Python 서비스 6종은 **빌드 컨텍스트가 리포 루트**(uv workspace 해석), Web 앱 2종(chat-web, admin-web)은 자체 디렉터리 컨텍스트입니다. `make build-images` 가 8종을 한 번에 빌드합니다.

| 이미지 | Containerfile | 비고 |
|---|---|---|
| `rag/chat-gateway` `rag/rag-api` `rag/admin-api` | `apps/<svc>/Containerfile` | uv 2-stage, `uv sync --frozen --no-dev --package <svc>`, `UV_ONLY_BINARY=:all:`, 비루트 uid 10001, WORKDIR `/app`. rag-worker 는 rag-api 이미지 공유(DEC-017 — command 만 `rq worker rag-chat`) |
| `rag/embedding-api` `rag/reranker-api` | `apps/<svc>/Containerfile` | **`UV_EXTRA=models` 기본** → torch/FlagEmbedding(cp312 amd64 휠) 포함. mock 전용 이미지는 `--build-arg UV_EXTRA=` |
| `rag/parser-indexer` | `apps/parser-indexer/Containerfile` | ENTRYPOINT `python -m ingestion.main` (K8s Job). `ingestion.tools.qdrant_init` 도 포함(§4.4) |
| `rag/chat-web` | `apps/chat-web/Containerfile` (컨텍스트 `apps/chat-web`) | `node:22-alpine` 에서 `npm ci` → `npm run typecheck && npm run build` → Next standalone 산출물로 **`node server.js` :3000**, uid 10001. **`NEXT_PUBLIC_WS_URL` 은 비운 채 빌드**(기본값 = same-origin, Ingress `/ws`). `NEXT_PUBLIC_WORKSPACE_SLUG` 기본 `rag` |
| `rag/admin-web` | `apps/admin-web/Containerfile` + `nginx.conf` (컨텍스트 `apps/admin-web`) | node 빌드 → **nginx :8080 비루트**, `/health/*` 200 |

```bash
cd ~/work/rag-platform
export TAG=$(git rev-parse --short HEAD)
export REG=registry.local:5000

# 8종 빌드 + push (Makefile 변수 REG/TAG — 기본값도 registry.local:5000 / git short sha)
make build-images REG=$REG TAG=$TAG
make push-images  REG=$REG TAG=$TAG
```

> **베이스 이미지 / 패키지 인덱스 (폐쇄망)**: 기본 베이스는 `python:3.12-slim`, `ghcr.io/astral-sh/uv:0.5`, `node:22-alpine`(chat-web), `node:20-alpine` + `nginx:1.27-alpine`(admin-web) 이며 개발망에서 pull 됩니다. 완전 폐쇄망이면 내부 미러를 build-arg 로 지정합니다 — Python: `--build-arg PYTHON_IMAGE=... --build-arg UV_IMAGE=... --build-arg UV_INDEX_URL=https://pypi.internal/simple`(cp312 바이너리 휠만, sdist 빌드 금지), Web: `--build-arg NODE_IMAGE=... --build-arg NPM_REGISTRY=...`(admin-web 은 `NGINX_IMAGE` 도). `make build-images` 는 build-arg 를 넘기지 않으므로 이 경우 Makefile 의 `docker build` 명령을 직접 실행하세요 (예: `docker build -f apps/rag-api/Containerfile --build-arg UV_INDEX_URL=... -t $REG/rag/rag-api:$TAG .`).
>
> **torch 휠 크기**: embedding/reranker 이미지는 torch(CPU) 포함 시 2~3GB 입니다. 두 이미지가 HDD 레지스트리와 P3 containerd 캐시(NVMe) 양쪽에 올라간다는 점을 §1.4.1 용량 계산에 반영하세요.

vLLM 은 빌드하지 않고 **NVIDIA 제공 arm64 이미지**를 미러링합니다:

```bash
# DGX Spark 지원 vLLM 이미지 (NGC) — arm64 태그 확인 후 미러. chart 의 rag.image 헬퍼가 global.imageTag 를 붙이므로 앱과 동일 $TAG 로 태깅
# ★ Qwen3.8-27B(qwen3_5) 는 vLLM ≥ 0.17.0 필요 — 태그의 vLLM 버전을 먼저 확인:
#   docker run --rm --entrypoint python nvcr.io/nvidia/vllm:<tag> -c "import vllm; print(vllm.__version__)"
docker pull --platform linux/arm64 nvcr.io/nvidia/vllm:<tag>
docker tag nvcr.io/nvidia/vllm:<tag> $REG/ai/vllm-arm64:$TAG
docker push $REG/ai/vllm-arm64:$TAG

# 데이터 계층 + helper 이미지 미러 (values-lab.yaml 의 data.*.image 가 이 경로를 가리킴, busybox 는 §1.4.3/§6 용)
for img in qdrant/qdrant:v1.12.1 postgres:16 redis:7 busybox:1.36.1; do
  name=$(basename $img); docker pull $img && docker tag $img $REG/library/$name && docker push $REG/library/$name
done
```

> **검증 습관**: 배포 전 `docker manifest inspect $REG/rag/rag-api:$TAG | grep architecture` — 이기종 클러스터에서 `exec format error`의 90%는 아키텍처 불일치입니다.

---

## 4. 배포 (Helm, values-lab.yaml)

`deploy/helm/rag-platform/values-lab.yaml` 은 `values.yaml`(기본) → `values-poc.yaml`(운영 override) 위에 겹쳐 쓰는 **랩 override** 이며 단독으로는 사용하지 않습니다. 운영과 달라지는 지점은 파일 주석에 근거를 남겼습니다.

| 항목 | 운영(values-poc) | 랩(values-lab) | 이유 |
|---|---|---|---|
| 레지스트리 | `harbor.internal` | `registry.local:5000` | §1.5 |
| 앱 replica / PDB | 2 / `minAvailable: 1` | 1 / 해제(`null` → PDB 미생성) | P3 20코어. replica 1에 PDB를 두면 rollout이 막힘 |
| rag-worker | 2 | 2 (유지) | 큐 재처리 시나리오(§6) 검증 |
| vLLM replica / 배치 | `[llm-0, llm-1]` | `[llm-0]` + `nodeSelector tier=llm` + `dedicated=llm` toleration | GPU 노드 1대, 이기종 배치 |
| `--max-num-seqs` | 16 | 8 | GB10 대역폭 |
| LLM 모델 | 운영 모델(TDD §8), `modelDir: llm/main` | **`vllm.modelDir: Qwen3.8-27B-FP8`** (교체 = 이 값만, §2.1.1) + `--language-model-only` `--reasoning-parser=qwen3`, rag-api/worker `LLM_ENABLE_THINKING=false` | §2.1 — thinking 기본 on 모델, 텍스트 전용 RAG |
| 모델 볼륨 | `models-pvc` | **hostPath** (앱: `/data/bulk/models`, vLLM: `/home/cheolkyulee/models`) — 컨테이너에는 둘 다 `/models` | GPU 노드와 앱 노드가 달라 단일 PVC 공유 불가 |
| 데이터 계층 | qdrant 500Gi / pg 200Gi / redis 20Gi | 50 / 20 / 10Gi + `local-fast` | NVMe 1TB 공유 (§1.4.1) |
| `documents-pvc` | 1Ti (default SC=NFS) | 500Gi + `local-bulk` | HDD |
| Namespace | 사전 생성(`namespaces.create: false`) | 동일 — §4.1 에서 kubectl 로 생성 + 라벨 | Secret 을 helm 전에 만들어야 함 |
| Ingress Controller | `networkPolicy.ingressController.namespace: ingress-nginx` | `kube-system` + podSelector `app.kubernetes.io/name: rke2-ingress-nginx` | RKE2 내장 컨트롤러 위치 |
| Ingress host | chat `chat.rag.internal` / admin `rag.internal` | chat `chat.rag.lab.local` / admin `rag.lab.local` (TLS `rag-chat-tls`) | — |
| chat-gateway `COOKIE_SECURE` | `true` | `true` (자체서명 TLS 로 HTTPS 접속) | HTTP 로만 쓸 경우에만 `"false"` |
| 색인 트리거 | `INDEX_JOB_TRIGGER=none` | `k8s` + ServiceAccount/RBAC(`serviceAccounts.adminApi.create=true`) + apiserver egress | 업로드 → Job 자동 생성 검증 |
| 마이그레이션 hook | `migration.enabled: true` | `true` | §4.2 |
| Grafana 대시보드 ConfigMap | on (`monitoring` NS) | **off** | kube-prometheus-stack 미설치 전제 (§9) |
| admin-web | appServices 미정의 | appServices 로 추가(:8080) | admin host `/` |

chart 가 **코드가 기대하는 경로/키를 책임지고 채우는** 항목 — 사용자는 §4.1 의 Namespace·Secret 만 만들면 됩니다:

| 코드가 읽는 것 | chart 가 렌더하는 것 |
|---|---|
| `JWT_SECRET_FILE`, `PASSWORD_PEPPER_FILE`, `FEEDBACK_SIGNING_KEY_FILE` (파일) | Secret `rag-chat-secrets`(`global.chatSecretName`) 중 **`appServices.<svc>.secretMount.keys` 에 나열한 키만** items 로 투영해 `/var/run/secrets/rag`(`secretMounts.chatSecretsPath`) 에 마운트(`defaultMode 0440`) + 해당 `*_FILE` env 자동 주입. chat-gateway = `jwt-secret`·`password-pepper`·`feedback-signing-key` 3키 / rag-worker = `feedback-signing-key` / admin-api = `password-pepper` (rag-api 는 없음) |
| `POSTGRES_HOST/PORT/USER/DB/PASSWORD` | `global.postgres.*`(host `postgresql.rag-data`) + `secretKeyRef` Secret `rag-postgresql-secret`(key `password`) — 앱(`dbEnv`)·색인 Job·마이그레이션 Job·PostgreSQL StatefulSet(initdb) 공통 |
| `REDIS_URL`, `RQ_REDIS_URL` | `global.redisUrl` (`redisEnv` — chat-gateway / rag-api / rag-worker) |
| `DOCUMENT_STORAGE_PATH=/data/documents` (admin-api 쓰기, indexer 읽기) | `documents-pvc` 를 admin-api(rag-app)·indexer Job(rag-ingestion)에 마운트 (PVC 는 두 NS 에 각각 생성) |
| Alembic `upgrade head` | `migration.enabled=true` → post-install/upgrade hook Job **`rag-db-migrate`**(admin-api 이미지, 10s 간격 30회 재시도) |
| K8s 색인 Job 생성 권한 | `serviceAccounts.adminApi.create=true` → SA `admin-api`(rag-app) + Role/RoleBinding `rag-index-job-creator`(rag-ingestion: configmaps `parser-indexer-job-template` get, jobs create/get/list) + (apiServer.enabled 시) NetworkPolicy `allow-admin-api-to-apiserver` |

### 4.1 선행 조건 — Namespace · 라벨 · Secret

**순서가 중요합니다.** Secret 은 Namespace-scoped 이므로 NS 를 먼저 만들고, Secret 을 만든 뒤 helm 을 실행해야 Pod 가 첫 기동에서 바로 뜹니다.

```bash
# 1) Namespace 4종 + ★ NetworkPolicy 가 요구하는 라벨. 라벨이 없으면 rag-api→qdrant/pg/redis/embedding/vllm 등 NS 간 통신이 전부 차단된다
for ns in rag-app rag-ai rag-data rag-ingestion; do
  kubectl create ns $ns --dry-run=client -o yaml | kubectl apply -f -
  kubectl label ns $ns rag-platform=true --overwrite
done

# 2) 로컬 secret 파일 — §4.4 seed-users 가 같은 pepper 파일을 다시 쓴다
mkdir -p secrets/rag
openssl rand -hex 32 > secrets/rag/jwt-secret
openssl rand -hex 32 > secrets/rag/password-pepper
openssl rand -hex 32 > secrets/rag/feedback-signing-key
echo -n "rag-lab-pg-$(openssl rand -hex 8)" > secrets/rag/postgres-password
chmod 600 secrets/rag/*

# 3) Web Chat Secret (rag-app) — 키 이름은 정확히 jwt-secret / password-pepper / feedback-signing-key
kubectl create secret generic rag-chat-secrets -n rag-app \
  --from-file=jwt-secret=secrets/rag/jwt-secret \
  --from-file=password-pepper=secrets/rag/password-pepper \
  --from-file=feedback-signing-key=secrets/rag/feedback-signing-key

# 4) TLS (rag-app) — chat host 와 admin host 가 같은 Secret 을 쓰므로(adminTlsSecretName 비움) SAN 에 두 호스트 모두 포함
#    사내 CA 발급본이 있으면 그것을, 없으면 랩용 자체 서명
openssl req -x509 -newkey rsa:2048 -nodes -days 365 \
  -keyout secrets/chat.key -out secrets/chat.crt \
  -subj "/CN=chat.rag.lab.local" \
  -addext "subjectAltName=DNS:chat.rag.lab.local,DNS:rag.lab.local"
kubectl -n rag-app create secret tls rag-chat-tls --cert=secrets/chat.crt --key=secrets/chat.key

# 5) PostgreSQL 비밀번호 — StatefulSet(rag-data) · 앱/마이그레이션 Job(rag-app) · 색인 Job(rag-ingestion) 세 NS 에 동일하게
for ns in rag-data rag-app rag-ingestion; do
  kubectl -n $ns create secret generic rag-postgresql-secret --from-file=password=secrets/rag/postgres-password
done

kubectl get secret -A | grep -E "rag-chat-secrets|rag-chat-tls|rag-postgresql"   # 5개 (chat-secrets 1 + tls 1 + postgresql 3)
```

> Secret 값은 Helm values 에 절대 넣지 않습니다(TDD §14.2 existingSecret 패턴). `rag-chat-secrets` 가 없으면 chat-gateway·rag-worker·admin-api Pod 가 `ContainerCreating`(Secret volume mount 실패)에 머뭅니다.

### 4.2 설치 및 DB 마이그레이션

```bash
cd ~/work/rag-platform
export TAG=$(git rev-parse --short HEAD)   # §3 에서 push 한 태그

make helm-lint helm-template                # 렌더 사전 검증 (poc / poc+lab)

# Ingress(chat.rag.lab.local / rag.lab.local, TLS rag-chat-tls)·migration·RBAC 는 values-lab 에 이미 켜져 있다
helm upgrade --install rag-platform deploy/helm/rag-platform \
  -f deploy/helm/rag-platform/values-poc.yaml \
  -f deploy/helm/rag-platform/values-lab.yaml \
  --set global.imageTag=$TAG \
  --set "networkPolicy.apiServer.cidrs={${P3_IP}/32}"   # admin-api → kube-apiserver(6443) egress. values-lab 의 예시 IP 를 실제 값으로
# `helm dependency update` 는 필요 없다 — Chart.yaml 에 dependencies 가 없다(데이터 계층도 이 chart 의 StatefulSet)

# 상태 확인 — vLLM 은 27B 로딩에 최대 10분(startupProbe 60×10s), embedding/reranker 는 HDD 로딩 최대 15분(90×10s)
kubectl get pods -A -l app.kubernetes.io/part-of=rag-platform -o wide
kubectl -n rag-ai logs -f deploy/vllm-llm-0 | grep -i "loading\|ready\|error"
```

`-o wide` 로 **배치 검증**: vLLM 만 pgx, 나머지 전부(chat-gateway·chat-web 포함) p3 에 스케줄되었는지 확인합니다.

**DB 마이그레이션** — 스키마 소유자는 **admin-api 의 Alembic** 입니다 (`apps/admin-api/src/admin/db/migrations`, 리비전 `0001_initial` → `0002_feedback_enabled` → `0003_webchat`). admin-api 는 기동 시 마이그레이션을 하지 않으며, 대신 `migration.enabled=true`(poc·lab 기본) 이면 Helm **post-install/post-upgrade hook Job `rag-db-migrate`** 가 `alembic upgrade head` 를 실행합니다.

- hook Job 은 `helm upgrade --install` 이 끝나기 전에 **완료되어야 하며**, 실패하면 helm 명령 자체가 실패합니다(§8). 성공하면 `hook-delete-policy: hook-succeeded` 로 삭제되므로 Job 이 남아 있지 않은 것이 정상입니다.
- 적용 결과 확인 (Containerfile WORKDIR=`/app` 기준 절대 경로 = `migration.alembicIni`):

```bash
kubectl -n rag-app exec deploy/admin-api -- \
  alembic -c /app/apps/admin-api/src/admin/db/migrations/alembic.ini current
# → 0003_webchat (head)
```

- **fallback — `migration.enabled=false` 로 설치한 경우에만** 수동 실행합니다:

```bash
kubectl -n rag-app exec deploy/admin-api -- \
  alembic -c /app/apps/admin-api/src/admin/db/migrations/alembic.ini upgrade head
```

> **v1.x(Mattermost) 데이터가 있던 DB 를 `0003_webchat` 으로 올린 경우**: 문서 ACL 의 채널 참조가 `chat_channels.id` 로 재매핑되므로 **전 문서 재색인이 필요**합니다 (Qdrant `allowed_channel_ids` 갱신). 새로 구축한 랩이면 해당 없음.

### 4.3 배포 후 검증 (필수 8종)

```bash
# ① 마이그레이션 — hook Job 이 지웠으므로 admin-api Pod 에서 리비전 확인
kubectl -n rag-app exec deploy/admin-api -- \
  alembic -c /app/apps/admin-api/src/admin/db/migrations/alembic.ini current
# → 0003_webchat (head)

# ② Secret 파일이 실제로 마운트되었는지 (secretMount.keys 에 나열한 키만 보여야 정상)
kubectl -n rag-app exec deploy/chat-gateway -- ls -l /var/run/secrets/rag   # jwt-secret, password-pepper, feedback-signing-key (3)
kubectl -n rag-app exec deploy/rag-worker   -- ls -l /var/run/secrets/rag   # feedback-signing-key (1)
kubectl -n rag-app exec deploy/admin-api    -- ls -l /var/run/secrets/rag   # password-pepper (1)
kubectl -n rag-app logs deploy/chat-gateway | grep -c "startup.*_missing"    # 0 이어야 정상 (1 이상이면 로그인 503 AUTH_NOT_CONFIGURED — §8)

# ③ PVC 가 맞는 티어에 생성되었는지
kubectl get pvc -A -o custom-columns='NS:.metadata.namespace,NAME:.metadata.name,SC:.spec.storageClassName,SIZE:.spec.resources.requests.storage,STATUS:.status.phase'
# data-qdrant-0 / data-postgresql-0 / data-redis-0 → local-fast ; documents-pvc(rag-app, rag-ingestion) → local-bulk
# models-pvc 는 modelStorage.create=false 이므로 없는 것이 정상

# ④ admin-api 가 문서 볼륨에 쓸 수 있는지
kubectl -n rag-app exec deploy/admin-api -- sh -c 'touch /data/documents/.probe && rm /data/documents/.probe && echo writable'

# ⑤ 임베딩/리랭커가 mock 이 아닌 실엔진으로 떴는지 (모델 경로 미마운트 시 조용히 mock 으로 기동한다)
kubectl -n rag-ai logs deploy/embedding-api | grep engine_ready     # model="kure-v1" (모델 디렉터리 이름). "-mock" 접미가 없어야 함
kubectl -n rag-ai logs deploy/reranker-api  | grep engine_ready

# ⑥ vLLM 모델 서빙 (rag-api 는 rag-app NS)
kubectl -n rag-app exec deploy/rag-api -- python -c "import httpx;print(httpx.get('http://vllm-service.rag-ai:8000/v1/models',timeout=10).json()['data'][0]['id'])"
# → internal-rag-llm
kubectl -n rag-ai get deploy vllm-llm-0 -o jsonpath='{.spec.template.metadata.annotations.ragplatform\.io/llm-model}'; echo
# → /models/Qwen3.8-27B-FP8   (vllm.modelDir — 의도한 모델인지 확인)

# ⑦ Ingress / NetworkPolicy
kubectl -n rag-app get ingress
# rag-chat    chat.rag.lab.local   (TLS rag-chat-tls)
# rag-admin   rag.lab.local        (TLS rag-chat-tls)
kubectl get netpol -A | grep allow-ingress-to
# rag-app  allow-ingress-to-chat-gateway / allow-ingress-to-chat-web / allow-ingress-to-admin-api / allow-ingress-to-admin-web (4)
kubectl -n rag-app get netpol allow-admin-api-to-apiserver        # INDEX_JOB_TRIGGER=k8s 용 apiserver egress

# ⑧ 디스크
df -h / /data/fast /data/bulk    # NVMe 사용률 70% 미만
```

### 4.4 Seed / 채팅 사용자 / Qdrant 초기화

seed(`scripts/seed_dev.sql`) 는 관리자 2명(`cklee`=SYS_ADMIN, `docadmin`=DOC_ADMIN), 채널 2개(`rag-cloud-ops` = `c0000000-0000-0000-0000-000000000001` 전용 / `rag-hr` = `c0000000-0000-0000-0000-000000000002` `!rag` 트리거), 지식범위, binding, 문서 메타 1건을 넣습니다.

```bash
# 1) Seed — PostgreSQL Pod 안에서 psql 로 적용 (호스트에 psql 불필요, NetworkPolicy 무관)
kubectl -n rag-data exec -i sts/postgresql -- psql -U rag -d rag -v ON_ERROR_STOP=1 -f - < scripts/seed_dev.sql

# 2) Qdrant collection(rag_chunks_v1) + payload index — parser-indexer 이미지 안의 도구를 클러스터 안에서 실행
kubectl -n rag-ingestion run qdrant-init --rm -i --restart=Never \
  --image=$REG/rag/parser-indexer:$TAG \
  --labels=app.kubernetes.io/part-of=rag-platform \
  --overrides='{"spec":{"nodeSelector":{"kubernetes.io/arch":"amd64"}}}' \
  --env=QDRANT_URL=http://qdrant.rag-data:6333 \
  --command -- python -m ingestion.tools.qdrant_init

# 3) Web Chat 데모 사용자 — hong(두 채널, admin) / kim(rag-hr). 비밀번호 해시는 SQL 로 만들 수 없어 스크립트를 쓴다
#    ★ 클러스터 Secret 과 "같은" pepper 파일로 해시해야 gateway 로그인이 된다 (§4.1 의 secrets/rag/password-pepper)
kubectl -n rag-data port-forward svc/postgresql 5432:5432 &
POSTGRES_PASSWORD="$(cat secrets/rag/postgres-password)" \
PASSWORD_PEPPER_FILE=./secrets/rag/password-pepper make seed-users
```

> - default-deny NetworkPolicy 환경에서 port-forward 트래픽은 CNI 구현에 따라 차단될 수 있습니다. 그래서 seed/qdrant-init 은 위처럼 클러스터 안에서 실행하는 쪽이 확실합니다. seed-users 의 port-forward 가 막히면, admin-api 이미지에 `scripts/` 가 포함되고 POSTGRES_* env 와 `password-pepper` 파일도 마운트되어 있으므로 Pod 안에서 실행할 수 있습니다: `kubectl -n rag-app exec deploy/admin-api -- python /app/scripts/create_chat_user.py --email hong@example.com --name 홍길동 --password 'Rag!Assistant2026' --channels rag-cloud-ops,rag-hr --role admin` (kim 도 같은 방식으로 `--channels rag-hr`).
> - 데모 비밀번호 `Rag!Assistant2026` 은 로컬/랩 전용입니다. 랩을 여러 사람이 쓰면 `CHAT_DEMO_PASSWORD=... make seed-users` 로 바꾸거나, admin-web **채팅 사용자** 메뉴의 임시 비밀번호 발급을 사용하세요.
> - seed 의 문서 1건(`장애대응매뉴얼`)은 **파일 실체가 없는 메타데이터**이므로 색인 대상이 아닙니다 — 실제 문서는 §5.1 에서 업로드합니다.

### 4.5 Ingress (RKE2 내장 ingress-nginx) + TLS

chart 의 `templates/ingress.yaml` 은 `ingress.enabled=true` 일 때만 렌더되며(values-lab 에서 켜짐), `appServices` 에 정의된 서비스만 라우팅합니다.

| Ingress | host | 경로 → 백엔드 |
|---|---|---|
| `rag-chat` | `ingress.chatHost` = `chat.rag.lab.local` | `/api/v1`, `/ws` → `chat-gateway:8001` · `/` → `chat-web:3000` |
| `rag-admin` (`ingress.adminHost` 지정 시) | `ingress.adminHost` = `rag.lab.local` | `/api` → `admin-api:8003` · `/` → `admin-web:8080` |

```bash
echo "${P3_IP} chat.rag.lab.local rag.lab.local" | sudo tee -a /etc/hosts   # 접속 PC 에도 등록
```

- **same-origin 필수**: chat-web 과 chat-gateway 가 같은 host 로 묶여야 refresh 쿠키(`rag_rt`, SameSite=Strict)와 WS Origin 검사(same-origin 자동 허용, `CHAT_CORS_ORIGINS` 는 비움)가 동작합니다. chat-web 이미지를 `NEXT_PUBLIC_WS_URL` 없이 빌드하는 이유입니다.
- **HTTPS 필수(실질)**: 로그인 prehash 는 브라우저 WebCrypto 를 쓰며 **HTTPS 또는 localhost 에서만** 동작합니다. `http://chat.rag.lab.local` 로는 로그인할 수 없으므로 `ingress.tlsSecretName`(values-lab: `rag-chat-tls`) 이 필요하고, 자체 서명 인증서라면 **접속 PC 에 `secrets/chat.crt` 를 신뢰 인증서로 등록**하세요. values-lab 의 chat-gateway `COOKIE_SECURE` 는 `"true"` 입니다.
- **WebSocket 타임아웃**: 템플릿이 `rag-chat` 에 `nginx.ingress.kubernetes.io/proxy-read-timeout`/`proxy-send-timeout: "3600"` 을 넣습니다(nginx 기본 60s 면 유휴 WS 가 1분마다 끊김). Upgrade 헤더는 ingress-nginx 가 자동 처리합니다. 추가 annotation 은 `ingress.annotations` 로.
- **NetworkPolicy**: `allow-ingress-to-<svc>`(chat-gateway / chat-web / admin-api / admin-web — `networkPolicy.exposedServices` 중 appServices 에 있는 것만) 는 **`networkPolicy.ingressController.{namespace,podSelector}`** 에 해당하는 Ingress Controller Pod 에서 오는 트래픽만 각 서비스 포트로 허용합니다. RKE2 번들 ingress-nginx 는 `kube-system` 에서 돌므로 values-lab 은 `namespace: kube-system`, `podSelector: {app.kubernetes.io/name: rke2-ingress-nginx}` 입니다(기본 values 는 `ingress-nginx` / `{}`). 불일치하면 502/504 — `kubectl -n kube-system get pods -l app.kubernetes.io/name=rke2-ingress-nginx` 로 확인 후 values 를 맞추세요.
- ⚠️ **X-Auth-User 신뢰(DEC-003)**: admin-api 는 `X-Auth-User` 헤더를 그대로 신뢰합니다. 랩은 인증 프록시가 없어 클라이언트(admin-web / curl)가 직접 보냅니다. 운영에서는 admin host 앞에 인증 프록시(oauth2-proxy 등)가 헤더를 주입·덮어쓰고 클라이언트 헤더를 제거해야 하며, **이 상태로 외부에 노출하면 안 됩니다.**

스모크:

```bash
curl -s --cacert secrets/chat.crt https://chat.rag.lab.local/health/live      # chat-web (/ → chat-web)
curl -s --cacert secrets/chat.crt https://chat.rag.lab.local/api/v1/auth/me    # chat-gateway 경유 — 토큰 없으면 401 이 정상
curl -s --cacert secrets/chat.crt https://rag.lab.local/api/v1/auth/whoami -H 'X-Auth-User: cklee'
curl -s --cacert secrets/chat.crt https://rag.lab.local/api/v1/chat/channels -H 'X-Auth-User: cklee' | jq '.data[].name'
curl -s --cacert secrets/chat.crt -o /dev/null -w "%{http_code}\n" https://rag.lab.local/   # admin-web 200
```

> Ingress 경로는 chat host 기준 `/api/v1`·`/ws`·`/` 뿐이므로 chat-gateway 의 `/health/*` 는 Ingress 로 노출되지 않습니다 (K8s probe 전용). gateway 자체 상태는 `kubectl -n rag-app port-forward svc/chat-gateway 8001:8001` 후 `curl localhost:8001/health/ready`.

---

## 5. E2E 기능 테스트 (Ingress 경유)

노트북 가이드 §5 와 동일 시나리오를 **클러스터 외부(접속 PC 브라우저)에서** 수행합니다 — Ingress·TLS·WebSocket·NetworkPolicy·Secret 마운트·K8s 색인 Job 트리거까지 함께 검증됩니다. Mattermost 서버나 Outgoing Webhook 설정은 필요 없습니다.

### 5.1 문서 업로드 → K8s 색인 Job

```bash
export ADMIN=https://rag.lab.local
export CURL_CA_BUNDLE=$PWD/secrets/chat.crt      # 자체 서명 TLS 신뢰

# 1) 샘플 문서 업로드 (samples/*.md). 평면 multipart: file/title/category/department/security_level/allowed_channel_ids/start_indexing
#    allowed_channel_ids = 채널 UUID (반복 필드 또는 콤마 구분). ★ 비우면 어느 채널에서도 검색되지 않는다. 비UUID → 422 INVALID_CHANNEL_ID
curl -s -X POST $ADMIN/api/v1/documents -H 'X-Auth-User: cklee' \
  -F 'file=@samples/장애대응매뉴얼.md' -F 'title=장애대응매뉴얼' -F 'category=장애대응' \
  -F 'department=Cloud운영팀' -F 'security_level=INTERNAL' \
  -F 'allowed_channel_ids=c0000000-0000-0000-0000-000000000001' \
  -F 'start_indexing=true' | tee /tmp/upload.json
# → data.index_job_id, data.index_job_status=PENDING
#   values-lab 은 INDEX_JOB_TRIGGER=k8s → admin-api 가 ConfigMap parser-indexer-job-template 으로 Job 생성

# 2) admin-api 가 만든 parser-indexer Job 확인 (rag-ingestion, generateName index-job-)
kubectl -n rag-ingestion get jobs -w            # index-job-xxxxx  COMPLETIONS 1/1
kubectl -n rag-ingestion logs job/$(kubectl -n rag-ingestion get jobs -o jsonpath='{.items[-1].metadata.name}') | tail -20
# → 단계 PARSING→CHUNKING→EMBEDDING→UPSERTING→VALIDATING, index_job COMPLETED
curl -s $ADMIN/api/v1/documents -H 'X-Auth-User: cklee' | jq '.data[] | {title,status}'     # ACTIVE

# 트리거가 실패하면 업로드 자체는 성공하고 index_jobs.error 에 "TRIGGER_FAILED[k8s]: ..." 가 남는다 (§8)
kubectl -n rag-data exec sts/postgresql -- psql -U rag -d rag -c \
  "SELECT status, stage, error FROM index_jobs ORDER BY created_at DESC LIMIT 3;"
```

`#rag-hr` 트리거 시나리오용으로 `samples/인사규정집.md` 를 `allowed_channel_ids=c0000000-0000-0000-0000-000000000002` 로 같은 방식으로 업로드해 두세요. 재색인은 `POST $ADMIN/api/v1/documents/<id>/reindex` (응답 `index_job_id`, `status`, `trigger`, `error`).

> **fallback — `INDEX_JOB_TRIGGER=none` 인 경우에만**(예: values-poc 기본값으로 배포) admin-api 는 index_jobs 행만 만듭니다. 이때는 chart 가 배포한 Job 템플릿 ConfigMap 을 직접 인스턴스화합니다:
>
> ```bash
> JOB_ID=$(jq -r .data.index_job_id /tmp/upload.json)
> kubectl -n rag-ingestion get cm parser-indexer-job-template -o jsonpath='{.data.job\.yaml}' \
>   | sed "s/__INDEX_JOB_ID__/$JOB_ID/" | kubectl create -f -
> ```

### 5.1.1 실제 PDF 문서 — 권장 용량·페이지 기준 (한글)

샘플(`.md`) 대신 실제 PDF 를 색인할 때의 기준입니다. **P3 와 동일 사양(Core Ultra 7 265 / 128GB)에서 실측**한 값이며, embedding-api 는 values-lab 의 CPU limit 과 같은 6 스레드로 측정했습니다.

**실측 (한글 텍스트 PDF, A4 10pt ≈ 1,800자/쪽)**

| 단계 | 실측 | 비고 |
|---|---|---|
| 파싱 (PyMuPDF + pdfplumber 표 추출) | **22ms/쪽** (200쪽 4.4초) · 실문서(§5.1.2, 개발 PC) 24~76ms/쪽 · **Print-To-PDF 문서 ≈ 0.36초/쪽**(pdfplumber 대체) | 병목 아님 |
| 청크 | **≈ 1.06개/쪽** (최대 800tok × 3.3자 = 2,640자, 문단 경계 분할로 평균 ≈ 1,600자) | 200쪽 → 212청크. values-lab(`CHARS_PER_TOKEN=1.9`)은 최대 1,520자 → 실문서 ≈ 1.4~2.8개/쪽(§5.1.2, 표가 많을수록 증가) |
| 청크 실제 토큰 (bge-m3 토크나이저) | 최대 길이(2,640자) 청크: 순수 한글 **≈ 1,413 tok** · 한글+영문 기술문서 ≈ 906 tok | 한글은 1.87자/토큰 — 청커 근사치(3.3자/토큰)보다 청크가 실제로 약 1.8배 길다 → **values-lab 은 `CHARS_PER_TOKEN=1.9`** 로 실제 ≈800 tok 에 맞춘다 |
| **임베딩 (bge-m3, CPU 6코어) — 병목** | 최대 길이 청크: 순수 한글 **1.63초** · 혼합 1.20초 / 1,300자 청크: 0.71초 | **색인 시간 ≈ 1~1.7초/쪽** (1.7초 = 보수적 상한). ⚠ 아래 주의 참고 — **재측정 필요** |
| Qdrant 저장 | ≈ 13KB/청크 (1024-dim float32 4KB + payload 원문) | 1,000쪽 ≈ 14MB — 랩 50Gi 기준 제약 아님 |

> ⚠ **임베딩 실측치 재확인**: embedding-api 는 v2.1 이전까지 FlagEmbedding 1.4 `encode()` 를 `max_length` 없이 호출해 **입력이 512 토큰에서 잘렸습니다**. 위 임베딩 시간을 서비스 코드 경로로 쟀다면 1,413 tok 청크도 512 tok 만 계산된 값입니다. v2.1 은 `EMBEDDING_MAX_LENGTH=2048` 로 전 길이를 임베딩하되 values-lab 의 `CHARS_PER_TOKEN=1.9` 로 청크 자체를 ≈800 tok 로 줄였으므로, 청크당 시간은 비슷하거나 늘고 청크 수는 늘어납니다. §5.1.2 의 5종 업로드 때 Job 로그의 EMBEDDING 단계 소요 시간으로 **쪽당 색인 시간을 다시 기록**하세요.

**chart 에 반영된 설정 2가지 — 실제 PDF 용 (기본 적용됨, 배포 후 확인만)**

1. **admin host 업로드 상한 100MB** — ingress-nginx 기본 업로드 제한은 **1MB** 라서, 글꼴이 임베드된 한글 PDF 는 10~50쪽만 돼도 **413 Request Entity Too Large** 로 거부됩니다. chart 는 `rag-admin` Ingress 에 `nginx.ingress.kubernetes.io/proxy-body-size: 100m`(values `ingress.adminProxyBodySize`, admin-api `MAX_UPLOAD_BYTES` 100MB 와 일치)을 붙이고, `rag-chat` 은 `1m` 을 유지합니다. `ingress.annotations` 에 같은 키를 넣으면 두 Ingress 모두 그 값으로 덮어씁니다.
   ```bash
   kubectl -n rag-app get ingress rag-admin -o jsonpath='{.metadata.annotations}'; echo   # proxy-body-size=100m
   ```
2. **임베딩 배치 8 · timeout 120초** — parser-indexer 코드 기본값(청크 **64개**/요청, **30초** timeout)으로는 한글 64청크가 ≈ 60~104초 걸려 **약 20~30쪽 초과 문서**가 `ReadTimeout` → 3회 재시도 → `index_jobs.stage=EMBEDDING, status=FAILED` 가 됩니다(끊긴 요청도 embedding-api 에서는 끝까지 계산되어 재시도마다 CPU 부하가 쌓임). chart 는 `ingestion.extraEnv` 에 `EMBEDDING_MAX_BATCH=8`(한글 8청크 ≈ 13초/요청), `EMBEDDING_TIMEOUT=120`(채팅 질의와 CPU 경합 여유)을 넣습니다. `ingestion.extraEnv` 를 override 할 때는 리스트가 통째로 교체되므로 이 두 항목을 함께 유지하세요.
   ```bash
   kubectl -n rag-ingestion get cm parser-indexer-job-template -o jsonpath='{.data.job\.yaml}' | grep -A1 EMBEDDING_   # MAX_BATCH 8 · TIMEOUT 120
   ```

**권장 기준 (위 설정 기준)**

| 항목 | 권장 | 근거 |
|---|---|---|
| **페이지 수 (1차 기준)** | **파일당 300쪽 이하** 권장 (색인 ≈ 5~9분), 최대 500쪽 (≈ 8~15분) | 색인 시간 ≈ 1~1.7초/쪽. 실패 시 전체 재시도, 색인 중 채팅 질의 임베딩도 같은 CPU 를 공유해 응답이 느려짐 |
| 파일 용량 | 텍스트 위주 한글 PDF: 쪽당 ≈ 50~100KB → **300쪽 ≈ 15~30MB 이하** | 용량은 보조 지표 — 이미지 비중이 크면 용량만 크고 색인 시간은 페이지 수(텍스트 양)에 비례 |
| 절대 상한 | **100MB** (admin-api `MAX_UPLOAD_BYTES`, 초과 시 413 `FILE_TOO_LARGE`) | 업로드는 admin-api 메모리에 전체 적재(limit 2Gi) — 상향 비권장 |
| 1,000쪽 이상 | 장/부 단위로 **분할 업로드** | 색인 ≈ 17~30분, 실패 시 재처리 비용 큼 |
| 스캔본(이미지) PDF | **불가** | OCR 비활성(`OCR_ENABLED=0`, DEC-005) → `SCANNED_NO_OCR` 로 실패. 텍스트 레이어가 있는 PDF 만 |
| 일부 쪽만 이미지(흐름도·표지) | 색인은 성공, **그 쪽 내용만 누락** | Job 로그 `pdf_image_only_pages` 경고 + `parsed` 의 `stats.image_only_pages` 로 확인 (§5.1.2) |
| 여러 문서 | **순차 색인** (한 번에 1개) | embedding-api replica 1 / CPU 6코어 공유. 대량 적재는 업무 시간 외 |

업로드 전 사전 점검 — **parser-indexer 의 실제 파서·청커**로 돌려 쪽수·pdfplumber 대체 쪽·이미지 전용 쪽·청크 수/최대 토큰을 봅니다 (네트워크·DB 불필요, P3 또는 개발 PC):

```bash
uv run --package parser-indexer python scripts/inspect_pdf.py manual.pdf            # values-lab 기준(CHARS_PER_TOKEN 1.9)
uv run --package parser-indexer python scripts/inspect_pdf.py docs/pdf/*.pdf --show 2   # 청크 본문 미리보기
# ✗ [SCANNED_NO_OCR] → 스캔본(OCR 필요) · ⚠ 이미지 전용 N쪽 → 그 쪽은 색인되지 않음
# 예상 색인 시간 ≈ 청크 수 × (Job 로그로 잰 청크당 임베딩 시간)
```

> **답변 쪽 여유**: rag-api 는 토크나이저 없이 3자/토큰으로 근사하지만 Qwen3.8 실측은 한글 1.74자/토큰입니다. 컨텍스트 예산 `MAX_CONTEXT_TOKENS=8192` 가 실제 ≈ 14,100 토큰이 되어 출력 1,024 를 더해도 vLLM `--max-model-len=16384` 안에 들어갑니다. **청크 크기(`CHUNK_SIZE`)나 `RERANK_TOP_N` 을 키우면 초과할 수 있으니** 함께 조정하세요.

### 5.1.2 한글 PDF — 파서·임베딩 모델 선정 (`docs/pdf` 실문서 5종 기준)

`docs/pdf/` 의 AI 기본법 가이드라인 5종(총 470쪽)을 실제로 파싱해 결함을 찾고, 그에 맞춰 파서와 임베딩 모델을 정했습니다. **5종 모두 텍스트 레이어가 있는 디지털 PDF**(스캔본 아님)라 OCR 없이 색인됩니다.

**① 문서별 진단 (PyMuPDF 기존 파서 기준)**

| 문서 | 생성기 | 쪽 | 발견된 결함 | v2.1 조치 |
|---|---|---|---|---|
| 1. 투명성 확보 | Hancom PDF (HWP 2022) | 33 | Wingdings 글머리표가 `l`·`è` 로 추출 | span 폰트명 기반 복원 → `●` `➔` |
| 2. 안전성 확보 | macOS Quartz | 71 | 가운뎃점이 **`䞻`(U+47BB)로 858회** 추출(KoPubWorldDotum ToUnicode 결함 — "개발䞻운영"), PUA 글머리표 141 | `䞻`→`·`, PUA → `●` `•` |
| 3. 고영향 판단 | Hancom PDF (HWP 2020) | 216 | Wingdings `Ÿ` 714, **이미지 전용 28쪽**(표지·장 표지·분야별 판단 흐름도) | 복원 / 이미지 쪽은 `image_only_pages` 로 보고 |
| 4. 사업자 책무 | **Microsoft Print To PDF** | 111 | **읽기 순서 붕괴** — 쉼표·마침표가 독립 줄로 떨어지고 문장 조각이 뒤섞임(구두점-only 줄 2,512개, 99/111쪽) | 해당 쪽만 **pdfplumber 글자 좌표 정렬 텍스트로 대체** |
| 5. 영향평가 | Hancom PDF | 39 | Wingdings `§`, 쪽 번호 `- 4 -` | 복원 / 쪽 번호 제거 |
| 공통 | — | — | 반복 머리말("인공지능 안정성 확보 가이드라인" 66쪽), `ㆍ` `･` `∙` `｢｣` 혼용 | 머리말/꼬리말·쪽 번호 제거, `·` `「」` 로 통일(NFC. NFKC 는 `①②` 항 번호를 뭉개므로 미사용) |

**② 파서 선정**

| 후보 | 판정 | 근거 |
|---|---|---|
| **PyMuPDF** (기존) | ✅ 기본 유지 | HWP 산출물 읽기 순서 정상, 216쪽 0.2초. 단 span 단위로 조립해 폰트명(Wingdings)을 보고 글머리표 복원 |
| **pdfplumber `extract_text`** | ✅ **깨진 쪽만** 대체 (`PDF_TEXT_ENGINE=auto`) | 문서 4 를 완벽 복원(구두점-only 줄 2,512 → 0). 대신 ~90배 느려(111쪽 37.7초) 전 쪽 적용은 하지 않음. 판정: 쪽의 구두점-only 줄 ≥3 이고 ≥5% (정상 문서 최대 2줄/3%, 문서 4 최대 77줄/52%) |
| PyMuPDF `sort=True` | ❌ | 줄 순서는 좋아지나 줄 안 조각 순서는 여전히 깨짐("반영하였다특히한국정보통신기술협회. ,") |
| Docling / Marker / Unstructured hi_res | ❌ (이 랩) | 레이아웃·OCR 모델(torch) 반입이 추가로 필요. 텍스트 레이어가 온전한 이 문서군에서는 위 조합으로 결함이 해소되어 이득이 작음 |
| OCR (PaddleOCR PP-OCRv5 korean 등) | ⏸ 보류 | 필요한 곳은 문서 3 의 흐름도 ~10쪽뿐. `OCR_ENABLED=0` 유지, §9 확장 과제 |

**파서 결과 (개발 PC 실측, `scripts/inspect_pdf.py`, values-lab 청킹)**

| 문서 | 파싱 | pdfplumber 대체 | 글리프 보정 | 머리말/쪽번호 제거 | 이미지 전용 쪽 | 청크(표) | 최대 청크 |
|---|---|---|---|---|---|---|---|
| 1 | 0.8s | 0 | 126 | 59줄 | 3 (표지 등) | 48 (19) | 1,487자 ≈ 795 tok |
| 2 | 3.6s | 0 | 1,018 | 140줄 | 1 | 101 (30) | 1,661자 ≈ 888 tok |
| 3 | 16.4s | 0 | 1,381 | 191줄 | **28** | 318 (116) | 2,035자 ≈ 1,088 tok (표) |
| 4 | 39.9s | **99쪽** | 1,130 | 110줄 | 1 | 311 (193) | 1,518자 ≈ 812 tok |
| 5 | 1.6s | 0 | 241 | 37줄 | 1 | 105 (61) | 1,519자 ≈ 812 tok |

> 남은 한계: 문서 2 의 위첨자 `10²⁶` 이 `10²乀`, 일부 화살표 글머리표가 `丼` 로 추출됩니다(폰트 결함, 소수라 미보정). 문서 3 의 흐름도(예: p.30 "에너지 분야 고영향 판단") 안 글자는 이미지라 검색되지 않습니다.

**③ 임베딩 모델 선정**

| 모델 | 크기 / 차원 / 최대 길이 | 라이선스 | 한글 검색 (공개 벤치마크) | 교체 비용 | 판정 |
|---|---|---|---|---|---|
| `BAAI/bge-m3` (기존) | 568M / 1024 / 8192 | MIT | MTEB-ko-retrieval Recall@1 0.518 · NDCG@1 0.598 ¹ / ko-leaderboard 검색 평균 79.30 ² | — | 비교 기준선 |
| **`nlpai-lab/KURE-v1`** | 568M / 1024 / 8192 (bge-m3 한글 파인튜닝) | MIT | **0.526 · 0.606** ¹ / **80.76** ² | **경로만 교체** — 차원·토크나이저·CLS pooling 동일, 접두어 없음, collection 스키마 그대로 | ✅ **랩 기본** |
| `dragonkue/snowflake-arctic-embed-l-v2.0-ko` | 568M / 1024 / 8192 | Apache-2.0 | 82.14 ² | 질의에 `query: ` 접두어 필요 → `EMBEDDING_QUERY_PREFIX="query: "` 로 지원 | A/B 후보 |
| `dragonkue/BGE-m3-ko` | 568M / 1024 / 8192 | Apache-2.0 | 0.524 · 0.604 ¹ | 경로만 교체 | 대안 |
| `Qwen/Qwen3-Embedding-0.6B` | 0.6B / 1024 / 32K | Apache-2.0 | 75.88 ² | last-token pooling·지시문 — 엔진 코드 변경 필요 | ❌ (한글 점수 낮음) |
| `Qwen/Qwen3-Embedding-4B` | 4B | Apache-2.0 | 81.37 ² | P3 CPU 로는 bge-m3 대비 ~7배 연산, PGX GPU 는 vLLM 점유 | ❌ (이 랩) |

¹ KURE-v1 모델 카드의 MTEB-ko-retrieval 표(Top-1 평균) · ² [ko-embedding-leaderboard](https://github.com/OnAnd0n/ko-embedding-leaderboard) 검색 평균. **공개 벤치마크는 일반 도메인**이라 이 법령·가이드라인 문서군에서의 우열은 아래 ⑤ A/B 로 확정합니다. KURE-v1 을 기본으로 둔 이유는 점수 차보다 **"경로 교체만으로 되고 실패 시 되돌리기 쉽다"** 는 점입니다.

리랭커는 `bge-reranker-v2-m3`(다국어, `RERANKER_MAX_LENGTH=1024`) 유지 — values-lab 은 `CHARS_PER_TOKEN=1.9` 로 청크를 ≈800 tok 로 줄였으므로 질의 + 청크가 1024 안에 들어갑니다(표 청크 일부만 초과·절단).

**④ 적용된 설정 (values-lab, 코드 기본값)**

| 키 | 값 | 이유 |
|---|---|---|
| `EMBEDDING_MODEL_PATH` (embedding-api) | `/models/embedding/kure-v1` | ③ |
| `EMBEDDING_MAX_LENGTH` (embedding-api) | `2048` (코드 기본도 2048) | **버그 수정** — FlagEmbedding 1.4 `encode()` 기본 512 tok 절단. 표 청크(최대 ≈1,100 tok)까지 포함 |
| `EMBEDDING_QUERY_PREFIX` | `""` | arctic-ko A/B 때만 `"query: "` (rag-api 가 `input_type=query` 로 보냄) |
| `CHARS_PER_TOKEN` (ingestion) | `1.9` | 한글 실측 1.87자/토큰 → `CHUNK_SIZE=800` 이 실제 ≈800 tok |
| `PDF_TEXT_ENGINE` (ingestion) | `auto` | ② (`pymupdf` = 대체 끔, `pdfplumber` = 전 쪽 — 느림) |

**⑤ 5종 업로드 · 모델 전환 · A/B**

```bash
# (a) 5종 업로드 — title 을 파일명 stem 으로 둬야 평가셋(tests/evaluation/dataset-ko-pdf) 문서 매칭이 된다. 순차 색인(§5.1.1)
for f in docs/pdf/*.pdf; do
  curl -s -X POST $ADMIN/api/v1/documents -H 'X-Auth-User: cklee' \
    -F "file=@$f" -F "title=$(basename "$f" .pdf)" -F 'category=AI기본법' -F 'department=AI정책' \
    -F 'security_level=INTERNAL' -F 'allowed_channel_ids=c0000000-0000-0000-0000-000000000001' \
    -F 'start_indexing=true' | jq -c '.data | {index_job_id, index_job_status}'
  sleep 5
  kubectl -n rag-ingestion wait --for=condition=complete --timeout=30m \
    job/$(kubectl -n rag-ingestion get jobs --sort-by=.metadata.creationTimestamp -o jsonpath='{.items[-1].metadata.name}')
done
# 파싱 통계 확인 — pdfplumber_text_pages(문서 4 → 99쪽), image_only_pages(문서 3 → 28쪽), repaired_glyphs
kubectl -n rag-ingestion logs job/<index-job-...> | grep -E '"parsed"|pdf_image_only_pages'

# (b) 평가 (§7.1 port-forward 상태) — 모델별로 리포트를 남긴다
RAG_API_URL=http://localhost:8002 uv run python -m evaluation.runner \
  --dataset tests/evaluation/dataset-ko-pdf --out reports/eval_ko_pdf_kure-v1.md

# (c) 모델 전환 (예: KURE-v1 → bge-m3 기준선). ★ 차원이 같아 섞여도 오류가 나지 않고 검색 품질만 무너진다 → 반드시 전량 재색인
#   1) values-lab 의 EMBEDDING_MODEL_PATH 변경 → helm upgrade → engine_ready 의 model 값 확인(§4.3 ⑤)
#   2) 기존 벡터 삭제 + collection 재생성 (색인 Job 과 같은 NS/이미지 — NetworkPolicy 통과)
kubectl -n rag-ingestion run qdrant-drop --rm -i --restart=Never \
  --image=$REG/rag/parser-indexer:$TAG --labels=app.kubernetes.io/part-of=rag-platform \
  --overrides='{"spec":{"nodeSelector":{"kubernetes.io/arch":"amd64"}}}' \
  --command -- python -c "from qdrant_client import QdrantClient; print(QdrantClient('http://qdrant.rag-data:6333').delete_collection('rag_chunks_v1'))"
#      → True 확인 후 §4.4 (2) qdrant-init 재실행
#   3) 전 문서 재색인 (순차)
for id in $(curl -s $ADMIN/api/v1/documents -H 'X-Auth-User: cklee' | jq -r '.data[].id'); do
  curl -s -X POST $ADMIN/api/v1/documents/$id/reindex -H 'X-Auth-User: cklee' | jq -c .
  sleep 5
  kubectl -n rag-ingestion wait --for=condition=complete --timeout=30m \
    job/$(kubectl -n rag-ingestion get jobs --sort-by=.metadata.creationTimestamp -o jsonpath='{.items[-1].metadata.name}')
done
#   4) (b) 를 --out reports/eval_ko_pdf_bge-m3.md 로 반복 → 두 리포트 diff. Recall@10 이 높은 쪽을 PoC(values-poc) 에 반영
```

> A/B 는 **8문항**(`dataset-ko-pdf`, 정의·단일/다중 문서·근거 없음 포함)이라 방향성 확인용입니다. 차이가 1문항 수준이면 KURE-v1 유지(교체 비용 0), arctic-ko 가 뚜렷이 앞서면 `EMBEDDING_QUERY_PREFIX="query: "` 와 함께 채택하세요.

### 5.2 브라우저 Web Chat E2E

1) **브라우저**: `https://chat.rag.lab.local` → hong@example.com / `Rag!Assistant2026` 로그인 → `#rag-cloud-ops` 에 `장애 등급별 대응 절차를 알려주세요.`
   - 접수 안내 2초 내 → THREAD 모드라 **스레드 자동 오픈** → 토큰 **스트리밍** → 근거 문서 표 + 👍/👎
   - 브라우저 개발자도구 Network → WS 탭에서 `wss://chat.rag.lab.local/ws/...` 가 101 Switching Protocols 로 유지되는지 확인 (60초 이상 유휴 후에도 끊기지 않아야 annotation 정상)
2) 후속 질문(같은 스레드) / `#rag-hr` 의 `!rag` 트리거 · 일반 메시지 무응답 — 노트북 가이드 §5.2·§5.3 과 동일
3) 피드백 👍/👎 + admin 피드백 대시보드 반영, 위조 토큰 401 — 노트북 가이드 §5.4·§5.5 (스크립트의 `BASE` 를 `https://chat.rag.lab.local` 로. 자체 서명이면 `SSL_CERT_FILE=secrets/chat.crt` 지정. `BOT_POST` 조회는 `kubectl -n rag-data exec sts/postgresql -- psql -U rag -d rag -tA -c "SELECT post_id FROM messages WHERE role='assistant' ORDER BY created_at DESC LIMIT 1;"`)
4) 부정 케이스 — kim@example.com 로그인 시 `rag-cloud-ops` 비노출, `/ch/rag-cloud-ops` 직접 접근 시 "채널을 찾을 수 없거나 접근 권한이 없습니다." (노트북 가이드 §5.5)
5) DB 상태 확인:

```bash
kubectl -n rag-data exec sts/postgresql -- psql -U rag -d rag -c \
  "SELECT status, completed_at - started_at AS dur FROM chat_jobs ORDER BY queued_at DESC LIMIT 3;"
# → COMPLETED, 27B(thinking off) 기준 수 초~수십 초
```

**27B 실물이므로 답변 품질을 직접 확인**: 근거 citation 정합성, 한국어 자연스러움, 무근거 질문의 안전 응답을 수동 채점해 두면 §7 자동 평가와 대조할 수 있습니다. 답변 본문에 `<think>` 나 추론 문장이 보이면 §8 참고.

### 5.3 Admin Web (`https://rag.lab.local/`)

- 우상단 사용자 버튼에서 `X-Auth-User` 를 `cklee` 로 설정(localStorage) — 랩은 인증 프록시가 없어 **클라이언트가 보낸 헤더를 그대로 신뢰**합니다(DEC-003, §4.5 경고).
- 문서 관리(업로드/재색인) · 채널 · 채팅 사용자 · 대화 작업 · 피드백(§5.2 반영) 확인.
- **Index Jobs / Audit Logs 화면은 빈 상태**로 표시됩니다 — admin-api 에 조회 API(`/api/v1/index-jobs`, `/api/v1/audit-logs`)가 없습니다(`apps/admin-web/README.md`). 색인 진행은 §5.1 의 `kubectl get jobs` / `index_jobs` 조회로 확인하세요.

---

## 6. 자동화 테스트

전 서비스가 Python 단일 스택이므로 admin-api 테스트도 루트 `make test` 에 포함됩니다 — 별도 빌드 도구 호출이 없습니다.

```bash
make lint && make test         # ruff + mypy(경고성) + 전체 pytest (183 passed — Docker 없으면 182 passed, 1 skipped: test_ch_qdrant)
make test-isolation            # ★ CH-001~010 — 배포 Gate. 로컬 fake 기반이라 클러스터 불필요
make test-integration          # Docker 필요(P3): tests/contract(mock-llm SSE ↔ LLMClient) + 실 Qdrant 격리(test_ch_qdrant.py, testcontainers)
```

이 환경 특화 검증 항목:

| 항목 | 방법 | 기대 |
|---|---|---|
| NetworkPolicy default-deny | `kubectl -n default run np-probe --rm -it --restart=Never --image=$REG/library/busybox:1.36.1 --overrides='{"spec":{"nodeSelector":{"kubernetes.io/arch":"amd64"}}}' -- wget -qO- -T3 http://qdrant.rag-data:6333/collections` | **타임아웃** — 라벨 없는 NS(`default`)의 Pod 는 rag-data 로 못 들어감. 같은 명령을 `-n rag-app --labels=app.kubernetes.io/part-of=rag-platform` 로 실행하면 **성공** (`allow-intra-platform` 은 `part-of=rag-platform` Pod 또는 `rag-platform=true` NS 간 통신을 허용) |
| NS 라벨 의존성 | `kubectl label ns rag-data rag-platform-` 후 질문 → 복구 `kubectl label ns rag-data rag-platform=true` | 라벨 제거 중 qdrant/pg/redis 불통 → Bot Post 가 오류 안내로 갱신(Job FAILED) → 복구 후 정상. (admin-api→qdrant 도 `allow-intra-platform` 상 **허용** 경로 — 서비스별 세분화는 후속 과제) |
| vLLM 재기동 복원력 | `kubectl -n rag-ai rollout restart deploy/vllm-llm-0` 후 질문 | 로딩 중 Bot Post 가 오류 안내로 갱신(Job FAILED) → 복구 후 정상 |
| Worker 장애 | 처리 중 `kubectl -n rag-app delete pod -l app.kubernetes.io/name=rag-worker` | RQ 가 job 을 재큐잉해도 `claim_job`(QUEUED→RUNNING 원자 전이) 멱등 가드로 이미 선점된 job 은 건너뜀 — **Bot Post 중복 갱신·중복 게시 없음** |
| 노드 격리 | PGX cordon 후 앱 재배포 | 앱은 전부 P3 에서 정상 (vLLM 만 Pending) |
| 색인 Job 격리 | 대용량 문서 색인 중 질문 | 질문 지연 없음 (rag-ingestion NS 별도, NFR-PERF-007) |
| chat-gateway 재기동 중 WS | `kubectl -n rag-app rollout restart deploy/chat-gateway` 중 브라우저 유지 | socket.io 자동 재연결 후 `ready` 재수신, 누락 답변은 채널 재조회로 수렴 (Bot Post 가 SSOT) |
| gateway 내부 경로 비노출 | 클러스터 밖에서 `https://chat.rag.lab.local/metrics` | Ingress 상 `/` → chat-web 로 라우팅되어 404 — gateway `/metrics`·`/health/*` 는 외부 비노출 (probe/Prometheus 내부 전용) |

---

## 7. RAG 품질 평가 및 성능 참고치

### 7.1 품질 평가

runner(`tools/evaluation`)는 **rag-api 의 `POST /internal/v1/rag/completions` 를 직접 호출**합니다 — `RAG_API_URL` 로 접근 경로를 지정해야 하며, 클러스터 밖에서는 port-forward 가 필요합니다.

```bash
kubectl -n rag-app port-forward svc/rag-api 8002:8002 &
RAG_API_URL=http://localhost:8002 make evaluate
# → reports/evaluation_report.md  (Recall@10 ≥85%, Citation Precision ≥90%, 무근거 안전응답 ≥90%, 근거 응답률)
```

> - 데이터셋은 **6문항**(`channel_id` = 채널 UUID `c0000000-...-001` 등)이며 `q001` 은 `장애대응매뉴얼.pdf` 를 기대 문서로 둡니다 — §5.1 에서 `.md` 로 업로드했어도 문서명 매칭은 확장자 차이를 허용(기대 문서 stem 포함 여부)하므로 통과합니다. PRD §25.6 의 100문항/유형 비율은 작성 과제입니다.
> - **Faithfulness/LLM-judge 와 격리 정확도는 리포트에 없습니다.** 격리는 §6 의 `make test-isolation` 이 담당합니다.
> - port-forward 가 default-deny 에 막히면 임시 정책: `kubectl -n rag-app apply -f - <<< '{"apiVersion":"networking.k8s.io/v1","kind":"NetworkPolicy","metadata":{"name":"tmp-allow-rag-api"},"spec":{"podSelector":{"matchLabels":{"app.kubernetes.io/name":"rag-api"}},"ingress":[{}]}}'` 후 평가, 끝나면 삭제.
> - **`SIMILARITY_THRESHOLD` 튜닝**(TDD §7.2.3 숙제, 기본 0.0): 현재 값은 rag-api/rag-worker 의 **env** 로만 반영됩니다(`values-lab.yaml` 의 `appServices.rag-api.extraEnv`(rag-worker 가 anchor 로 공유)에 추가 → `helm upgrade`). Admin Web Settings 화면의 값은 `settings` 테이블에만 저장되고 파이프라인에는 연동되지 않습니다(리뷰 잔여 과제). README §8.3 의 `scripts/eval_diff.py` 도 아직 없습니다 — 리포트 파일을 날짜별로 복사해 두고 `diff` 로 비교하세요. 이 환경에서 SIMILARITY_THRESHOLD 확정을 완료하는 것을 권장합니다.

### 7.2 성능 — 해석 주의

```bash
# ACK p95 ≤ 2s — 이 환경에서도 그대로 유효한 목표. GATEWAY_URL 로 Ingress(chat host)를 가리킨다
# locust 는 데모 계정으로 로그인 → POST /api/v1/posts ACK 를 측정한다 (-u 50 -r 50 -t 10s)
# 자체 서명 인증서면 REQUESTS_CA_BUNDLE 로 신뢰 지정
REQUESTS_CA_BUNDLE=secrets/chat.crt \
CHAT_EMAIL=hong@example.com CHAT_PASSWORD='Rag!Assistant2026' \
GATEWAY_URL=https://chat.rag.lab.local make perf-chat-burst

# 동시 6 부하는 별도 make 타깃이 없다 — locust 인자를 직접 지정 (Makefile의 perf-chat-burst와 동일 파일)
REQUESTS_CA_BUNDLE=secrets/chat.crt \
CHAT_EMAIL=hong@example.com CHAT_PASSWORD='Rag!Assistant2026' \
uv run locust -f tests/performance/locustfile.py --headless -u 6 -r 6 -t 5m \
  --host https://chat.rag.lab.local

# 최종 답변 지연 p50/p95 — rag-api 동기 completions 경로 직접 호출 (§7.1 port-forward 상태에서)
uv run python scripts/measure_latency.py --n 30 --concurrency 4 --rag-url http://localhost:8002
```

> ⚠️ **rate limit 조정 필수**: 단일 계정으로 부하를 주므로 gateway 의 `RATE_LIMIT_PER_USER_PER_MIN`(기본 10)·`RATE_LIMIT_PER_CHANNEL_PER_MIN`(30)에 곧바로 걸려 429 가 실패로 집계됩니다. 50명 동시 로그인이면 `RATE_LIMIT_LOGIN_PER_MIN`(10)도 걸립니다. 시험 동안 values-lab 의 `appServices.chat-gateway.extraEnv` 에 해당 값을 올려 `helm upgrade` 하고(리스트는 통째로 교체되므로 기존 항목 유지), 시험 후 원복하세요.

| 지표 | 목표(운영) | 이 환경 해석 |
|---|---|---|
| ACK p95 | ≤ 2s | **그대로 판정** (LLM 무관 경로). 단 chat-gateway 의 DB 조회(`SqlChatStore`)가 async 핸들러 내 동기 I/O 라 50-user burst 에서 흔들릴 수 있음(리뷰 H-8) |
| 검색 p95 | ≤ 1s | NVMe Qdrant 면 그대로 판정 (completions 응답 `usage.search_ms` 로 확인) |
| 답변 p95 | ≤ 30s @ 동시 10 | GB10 대역폭 특성상 **동시 4~8 에서 경향만** 기록. 절대치로 합불 판정 금지 |
| 동시 15 | NFR-PERF-004 | 미검증 — 운영 GPU 환경 몫. (`CHAT_MAX_CONCURRENCY` 는 아직 코드가 강제하지 않음 — 실효 동시성은 rag-worker replica 수) |

---

## 8. 트러블슈팅 (이기종 클러스터 특화)

| 증상 | 조치 |
|---|---|
| 한글 PDF 답변이 엉뚱한 문장 조각을 근거로 든다 / 근거에 `, .` 가 줄마다 끼어 있다 | 읽기 순서가 깨진 PDF(MS Print-To-PDF 등). Job 로그 `parsed` 의 `pdfplumber_text_pages` 가 비어 있으면 `PDF_TEXT_ENGINE` 이 `pymupdf` 로 덮였는지 확인(`auto` 권장), 재색인 (§5.1.2 ②) |
| 임베딩 모델 교체 후 검색 품질이 급락(오류 없음) | 이전 모델 벡터가 collection 에 남아 섞임 — 차원이 같아 오류가 나지 않는다. §5.1.2 ⑤(c) 로 collection 삭제·재생성 후 전량 재색인 |
| embedding-api 로그 `colbert_linear and sparse linear is new initialize` | KURE-v1 등 bge-m3 파인튜닝 모델은 colbert/sparse 가중치가 없음 — dense 만 쓰므로 무시 (§2.2) |
| `helm install` 이 `namespaces "monitoring" not found` | `monitoring.grafanaDashboards=true` 인데 NS 가 없음 — values-lab 기본은 false. kube-prometheus-stack 설치 후 켤 것 |
| `helm install` 이 hook Job `rag-db-migrate` 실패로 종료 | PostgreSQL 이 5분(30×10s) 내 준비되지 않음(이미지 pull/PVC Pending) 또는 `rag-postgresql-secret` 누락. `kubectl -n rag-app logs job/rag-db-migrate`, `kubectl -n rag-data describe pod postgresql-0`. 원인 해결 후 `helm upgrade` 재실행 |
| 테이블 없음 / admin-api 500 (`relation ... does not exist`) | `migration.enabled=false` 로 설치했거나 hook 이 돌지 않음 — §4.2 `alembic current` 확인, 비어 있으면 fallback `upgrade head` |
| PostgreSQL `CrashLoopBackOff`, 로그 `Database is uninitialized and superuser password is not specified` | `rag-postgresql-secret`(rag-data) 누락 — §4.1 ⑤ |
| `alembic`/앱이 DB 연결 실패 | `kubectl -n rag-app exec deploy/admin-api -- env \| grep POSTGRES` 로 `POSTGRES_HOST=postgresql.rag-data` 확인. `rag-postgresql-secret` 이 해당 NS(rag-app / rag-ingestion)에 있는지 확인 |
| rag-api/worker 가 qdrant/pg/redis 에 연결 실패, 전 NS 간 통신 불통 | **NS 라벨 `rag-platform=true` 누락** — `kubectl get ns -L rag-platform`. §4.1 ① |
| 외부에서 `chat.rag.lab.local`/`rag.lab.local` 502/504 또는 접근 불가 (Ingress 는 ADDRESS 있음) | ① `networkPolicy.ingressController.{namespace,podSelector}` 가 실제 컨트롤러와 불일치(`kubectl -n kube-system get pods -l app.kubernetes.io/name=rke2-ingress-nginx`) ② 접속 PC `/etc/hosts` 미등록 ③ ingressClassName |
| chat-gateway/rag-worker/admin-api `ContainerCreating` 에서 멈춤 | `rag-chat-secrets` 미생성 또는 키 이름 불일치 — `kubectl -n rag-app describe pod <pod>` 의 `MountVolume.SetUp failed`. 키는 정확히 `jwt-secret`, `password-pepper`, `feedback-signing-key` |
| 로그인이 항상 **503 `AUTH_NOT_CONFIGURED`** | chat-gateway 가 JWT 키 또는 pepper 파일을 읽지 못함(fail-closed — 빈 키로 서명·해시하지 않음). `kubectl -n rag-app logs deploy/chat-gateway \| grep startup.` 의 `startup.jwt_secret_missing`/`startup.password_pepper_missing`, §4.3 ② |
| 피드백이 전부 401 `INVALID_SIGNATURE` | `feedback-signing-key` 미마운트 — gateway 는 키가 없으면 `/api/v1/actions` 를 전면 거부(로그 `startup.feedback_signing_key_missing`), rag-worker 는 feedback_token 을 붙이지 않음(로그 `worker.feedback_signing_key_missing`). §4.3 ② |
| 브라우저 로그인 버튼이 동작하지 않음 / crypto 오류 | HTTP 로 접속함 — WebCrypto 는 HTTPS/localhost 전용. `https://` 접속, 자체 서명이면 접속 PC 에 인증서 신뢰 등록 |
| admin host(`rag.lab.local`) 에서만 인증서 오류 | TLS 인증서 SAN 에 `rag.lab.local` 누락 — §4.1 ④ 처럼 두 호스트를 SAN 에 넣어 재발급 후 `rag-chat-tls` 교체 |
| 올바른 비밀번호인데 로그인 401 | `make seed-users` 가 클러스터 Secret 과 다른 pepper 파일로 해시함 — §4.1 에서 Secret 으로 등록한 `secrets/rag/password-pepper` 로 재실행 |
| 질문은 게시되는데 답변이 실시간으로 안 뜸(새로고침하면 보임) / WS 핸드셰이크 403, gateway 로그 `... is not an accepted origin` | WS Origin 거부 또는 경로 문제 — ① chat-web 을 `NEXT_PUBLIC_WS_URL` 을 채운 채 빌드(교차 출처로 연결 → Origin 거부. 비운 채 재빌드) ② Ingress 에 `/ws` 경로 누락 ③ `networkPolicy.ingressController.namespace/podSelector` 와 실제 ingress-nginx 불일치(§4.5) |
| WS 가 약 60초마다 끊겼다 재연결 | `proxy-read-timeout`/`proxy-send-timeout` annotation 미적용 — `kubectl -n rag-app get ingress rag-chat -o yaml` 확인 |
| 로그인이 새로고침마다 풀림 | refresh 쿠키 미전송 — chat-web 과 chat-gateway 가 서로 다른 host 로 노출됨(SameSite=Strict), 또는 `COOKIE_SECURE=true` 인데 HTTP 접속 |
| 업로드 500, admin-api 로그 `Read-only file system` | `documents-pvc` 미마운트 — `kubectl -n rag-app get deploy admin-api -o jsonpath='{.spec.template.spec.volumes[*].name}'` 에 documents 가 있는지, §4.3 ④ |
| `index_jobs.error` 에 `TRIGGER_FAILED[k8s]: ... status=403` | admin-api ServiceAccount RBAC 누락(`serviceAccounts.adminApi.create`) 또는 `appServices.admin-api.serviceAccountName` 미지정 — `kubectl -n rag-ingestion get role,rolebinding rag-index-job-creator` |
| `index_jobs.error` 에 `TRIGGER_FAILED[k8s]: ... ConnectError` | admin-api → apiserver egress 차단 — `networkPolicy.apiServer.cidrs` 가 P3 IP 가 아님 (`--set` 확인, `kubectl -n rag-app get netpol allow-admin-api-to-apiserver -o yaml`) |
| PDF 업로드가 `413 Request Entity Too Large` (HTML 응답) | `rag-admin` Ingress 에 `proxy-body-size: 100m` annotation 이 없음(구 chart 로 배포 / 다른 IngressClass) → 최신 chart 로 `helm upgrade` 또는 `ingress.adminProxyBodySize` 확인 (§5.1.1). JSON `FILE_TOO_LARGE` 면 admin-api 100MB 상한 초과 → 파일 분할 |
| 긴 PDF 색인이 `stage=EMBEDDING`, `FAILED` (Job 로그 `ReadTimeout`) | `ingestion.extraEnv` override 로 `EMBEDDING_MAX_BATCH=8`·`EMBEDDING_TIMEOUT=120` 이 빠져 코드 기본값(64청크/30초)으로 동작 → 두 항목 복원 후 재배포 (§5.1.1) |
| 색인 Job 은 성공했는데 질문에 "근거를 찾지 못했습니다" | 업로드 시 `allowed_channel_ids` 를 비웠거나 다른 채널 UUID 지정 → `document_channel_acl` 없음 → 검색 필터에 절대 매칭 안 됨. `psql -c "select * from document_channel_acl"` 확인 후 재업로드(같은 내용은 409 → 파일 한 글자 수정) |
| embedding/reranker 가 뜨긴 했는데 답변이 엉뚱함 | 모델 경로 미마운트로 **mock 엔진**으로 기동 — `engine_ready` 로그에 `-mock`. hostPath `/data/bulk/models/{embedding,reranker}/...` 와 `chmod a+rX` 확인 (§4.3 ⑤) |
| embedding/reranker 최초 기동 CrashLoop | HDD 로딩이 15분(90×10s) 초과 — `appServices.<svc>.startupFailureThreshold` 상향 또는 모델을 `/data/fast/models` 로 이동(NVMe 여유 확인 후) |
| vLLM Pod `CreateContainerConfigError`/권한 오류 | NGC 이미지가 root 전제 — `vllm.podSecurityContext: {runAsNonRoot: false, runAsUser: 0}` (values-lab 주석) 로 예외를 명시하고 리포트에 기록(§22.4) |
| Pod `exec format error` CrashLoop / vLLM Pod가 P3로 스케줄 시도 | amd64 이미지가 PGX 에, 또는 반대로 스케줄됨 — nodeSelector/toleration 확인, `kubectl get pod -o wide`. P3 에는 nvidia.com/gpu 리소스가 없어 vLLM Pending 이 정상 |
| PGX에서 `nvidia.com/gpu: 0` | GPU Operator toolkit Pod(pgx) 로그 확인, containerd 재시작. `driver.enabled=false` 유지 |
| vLLM OOM/성능 급락 | 통합 메모리를 OS·타 프로세스와 공유 — PGX 에 다른 워크로드 금지(taint 유지), `--gpu-memory-utilization` 0.85 로 하향 |
| vLLM 기동 실패 `Qwen3_5ForConditionalGeneration ... not supported` / `qwen3_5` 인식 불가 | vLLM 이미지가 0.17.0 미만 — NGC 최신 arm64 태그로 교체(§3 버전 확인 명령). 다운로드가 덜 끝났거나 한 디렉터리에 두 모델을 섞어 받았어도 발생 → 새 디렉터리로 재다운로드 후 `vllm.modelDir` 지정(§2.1.1) |
| vLLM Pod `ContainerCreating`, 이벤트 `hostPath type check failed: /home/cheolkyulee/models is not a directory` | PGX 에 `vllm.modelHostPath` 경로가 없음 — 경로 확인(`ls -ld /home/cheolkyulee/models`) 또는 values-lab 의 `modelHostPath` 수정 |
| vLLM 로그 `... /models/<이름> ... does not appear to have a file named config.json` / `Repo id must be ...` | `vllm.modelDir` 가 실제 디렉터리 이름과 다름(대소문자 포함) — `ls /home/cheolkyulee/models` 와 비교 후 helm upgrade |
| vLLM 로그 `PermissionError` / `Permission denied` (모델 파일) | 새로 받은 모델의 other 읽기 권한 없음 — `chmod -R a+rX /home/cheolkyulee/models/<모델>` |
| `helm template` 이 `vllm.args 에 "--model=..." 를 넣지 마세요` 로 실패 | 구 values 의 `--model`/`--served-model-name` 인자가 남아 있음 — 삭제하고 `vllm.modelDir`/`vllm.servedModelName` 사용 |
| 답변 본문에 `<think>` / 추론 과정이 섞임, 첫 토큰이 매우 늦음 | thinking 이 켜진 상태 — rag-api/worker env `LLM_ENABLE_THINKING=false` 확인, vLLM args 에 `--reasoning-parser=qwen3` 확인(`kubectl -n rag-ai get deploy vllm-llm-0 -o jsonpath='{.spec.template.spec.containers[0].args}'`) |
| Qdrant 검색 1s 초과 | PVC 가 local-bulk(HDD)에 생성됨 — `kubectl get pvc -n rag-data` 로 SC 확인 후 local-fast 로 재생성 |
| PVC가 계속 `Pending` | ① `deploy/k8s/local-path-*.yaml` 의 nodePathMap 노드 이름 불일치(§1.4.3 sed 누락) — `kubectl -n local-path-storage logs deploy/local-path-provisioner-fast` ② `WaitForFirstConsumer` 라 소비 Pod 스케줄 전엔 정상 ③ Pod 가 pgx 로 갔다면 nodePathMap 에 없어 실패 — nodeSelector 확인 |
| PVC Pending + helper-pod `ImagePullBackOff` | 폐쇄망에서 `busybox:1.36.1` pull 실패 — §1.4.3 의 sed 로 미러 경로(`registry.local:5000/library/busybox:1.36.1`) 교체 후 provisioner 재시작 |
| **NVMe 용량 부족 / `DiskPressure`, Pod 무더기 Evicted** | 2-디스크 구성의 핵심 리스크. `df -h / /data/fast` → NVMe 소진. 원인 1순위는 PVC 가 default SC(local-fast)로 새어 문서가 NVMe 에 적재 — §4.3 ③. 즉시 조치: PVC 삭제 후 local-bulk 로 재생성, `sudo crictl rmi --prune` 로 미사용 이미지 정리 |
| `/data/bulk` 가 비어 있는데 NVMe 만 참 | HDD 마운트 전에 디렉터리/registry/PVC 를 만든 케이스 — `findmnt /data/bulk`. 마운트 해제 → 루트 FS 의 `/data/bulk` 잔여물 삭제 → 재마운트 |
| 색인 Job 이 평소보다 훨씬 느림 | HDD 한 대에 문서 원본 + registry + 모델 공존 — 이미지 push/pull, 다중 색인 Job 동시 실행을 피하고 순차 실행. `iostat -x 2 /dev/sda` 로 `%util` 확인 |
| PVC 삭제 후에도 HDD 용량 미반환 | `local-bulk` 는 `reclaimPolicy: Retain` — `kubectl get pv \| grep Released` 후 `sudo rm -rf /data/bulk/pvc/pvc-<uid>` 수동 정리 |
| PGX 가 이미지 pull 실패 | PGX 의 `/etc/rancher/rke2/registries.yaml` 누락 또는 rke2-agent 미재시작, PGX `/etc/hosts` 의 `registry.local` 누락(§1.5) |
| `make push-images` 가 `server gave HTTP response to HTTPS client` | P3 Docker 에 insecure registry 미등록 — §1.5 의 `/etc/docker/daemon.json`(`"insecure-registries":["registry.local:5000"]`) 작성 후 `sudo systemctl restart docker` |
| 노드 간 호출 간헐 지연 | 2.5GbE 협상 확인 `ethtool enpXs0 \| grep Speed`, MTU 불일치 확인 |
| RKE2 재부팅 후 워크로드 미복귀 | `systemctl status rke2-server`(P3)/`rke2-agent`(PGX), PGX 절전 설정 비활성 |

---

## 9. 확장 과제 (선택)

- **모니터링**: kube-prometheus-stack 설치 후 `monitoring.grafanaDashboards=true` 로 `helm upgrade` — chart 가 `rag-grafana-dashboards` ConfigMap(sidecar 라벨 `grafana_dashboard: "1"`, 질문 ACK p95 · 답변 지연 p95 · 큐 깊이 · WebSocket 연결 · 근거부족 · 만족률 · 위조 피드백 토큰 · embedding/rerank 지연 패널)을 `monitoring` NS 에 생성합니다. 2-디스크 구성에서는 `node_filesystem_avail_bytes{mountpoint=~"/|/data/.*"}` 알람을 최우선으로 — NVMe 소진이 이 랩의 단일 최대 장애 요인입니다.
- **PGX Grace CPU 활용**: embedding/reranker 를 arm64 로도 빌드(`docker buildx build --platform linux/amd64,linux/arm64`)해 PGX 에 배치하면 색인 처리량 향상. taint 정책 재설계 필요.
- **vLLM 2-replica 모사**: 단일 GPU 에서 MPS/시간분할은 비권장 — HA(NFR-HA-002)는 순차 재기동 테스트로 대체.
- **이미지 전용 쪽 OCR**(§5.1.2): 흐름도·도표 안 한글(문서 3 의 분야별 판단 흐름도 등)을 검색하려면 `stats.image_only_pages` 쪽만 골라 OCR 하는 경로가 필요합니다. 후보는 PaddleOCR PP-OCRv5 한국어 인식 모델(또는 그 ONNX 변환을 쓰는 RapidOCR) — 모델 파일 반입·로컬 경로 로딩, TDD §7.7 의 격리 `ocr-worker` 설계를 따릅니다.
- **디스크 1개 추가 시**: `/data/bulk` 에서 **레지스트리를 분리**(`/data/registry`)하는 것이 효과가 가장 큼. 색인 Job 의 문서 읽기와 이미지 push/pull IO 경합이 사라집니다.
- **PoC 이관 전 코드 과제**(`docs/code-review-2026-09-10.md` 잔여): Settings→파이프라인 연동, async 핸들러 내 동기 I/O 제거(chat-gateway `SqlChatStore`, admin 업로드), rate limit 원자화, 문서 삭제 시 Qdrant 비활성화, mock 엔진 silent fallback 차단, 100문항 평가셋·LLM-judge, `CHAT_MAX_CONCURRENCY` 강제, admin-api `/index-jobs` 조회 API.

---

## 10. 검증 완료 체크리스트

- [ ] 노드 2대 Ready, 라벨/테인트 적용 (`tier=app`/`tier=llm`), PGX `nvidia.com/gpu: 1` allocatable
- [ ] HDD `/data/bulk` 마운트(`findmnt`), NVMe `/data/fast` 준비, StorageClass `local-fast`/`local-bulk` Bound 테스트 통과(§1.4.3), nodePathMap 치환
- [ ] **이미지 8종**(chat-gateway · rag-api · admin-api · embedding-api · reranker-api · parser-indexer · chat-web · admin-web) + vLLM arm64 + data 3종 + busybox 레지스트리 push, manifest arch 확인
- [ ] **NS 4종 + `rag-platform=true` 라벨**, Secret 5개(`rag-chat-secrets`, `rag-chat-tls`(SAN 두 호스트), `rag-postgresql-secret`×3)
- [ ] `helm upgrade --install` 성공(hook `rag-db-migrate` 포함), `alembic current` = `0003_webchat (head)`
- [ ] 배치 검증 — vLLM 만 pgx, 나머지(chat-gateway·chat-web 포함) p3 (`-o wide`), **Qwen3.8-27B 로딩 완료**(startupProbe 내, `/v1/models` → `internal-rag-llm`, annotation `ragplatform.io/llm-model=/models/Qwen3.8-27B-FP8`)
- [ ] §4.3 ①~⑧: alembic head, Secret 파일 마운트(gateway 3 / worker 1 / admin-api 1, `startup.*_missing` 0), PVC 티어(DB=local-fast, documents=local-bulk), 문서 볼륨 쓰기, **실엔진 기동(`-mock` 없음)**, `/v1/models`, Ingress(rag-chat/rag-admin)·NetPol(`allow-ingress-to-*` 4 + `allow-admin-api-to-apiserver`), NVMe 70% 미만
- [ ] seed + qdrant-init + seed-users(동일 pepper) 완료
- [ ] 업로드(`start_indexing=true`) → **K8s 색인 Job COMPLETED**, 문서 ACTIVE
- [ ] 한글 PDF 5종(§5.1.2) 색인 COMPLETED — 문서 4 `pdfplumber_text_pages` 99쪽·문서 3 `image_only_pages` 28쪽 확인, `engine_ready model=kure-v1`, `dataset-ko-pdf` 평가 리포트(모델별) 기록, 쪽당 색인 시간 재측정(§5.1.1 ⚠)
- [ ] Ingress(HTTPS) 경유 브라우저 E2E: 로그인→질문→스트리밍 답변(+근거 표·피드백 버튼)→피드백 👍/👎/위조 401, 비멤버 채널 차단
- [ ] WebSocket 60초 이상 유휴 유지(timeout annotation), `curl https://chat.rag.lab.local/health/live` 200
- [ ] NetworkPolicy 차단/허용 확인(np-probe), NS 라벨 제거 실험, vLLM 재기동 복원, worker 삭제 시 중복 게시 없음
- [ ] `make lint && make test` green(200, Docker 없으면 199+1 skipped), `make test-isolation` green, `make test-integration`(Docker) green
- [ ] `make evaluate` → `reports/evaluation_report.md` 생성, **4지표** 목표 대비 판정 기록 (6문항 한계 명시), SIMILARITY_THRESHOLD 확정
- [ ] ACK p95 ≤ 2s / 검색 p95 ≤ 1s 판정, 생성 성능은 참고치 기록
- [ ] 운영과의 의도적 차이(replica, PDB, hostPath, vLLM podSecurityContext 예외, X-Auth-User 클라이언트 신뢰, 자체서명 TLS) 리포트 기록

> 이 클러스터에서 green 이면 PoC 환경 이관 시 남는 변수는 사실상 "운영 GPU 성능"과 "사내 TLS 인증서·DNS·인증 프록시(admin X-Auth-User 주입) 연동" 둘뿐입니다.
