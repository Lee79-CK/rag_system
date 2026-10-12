# Lab 부가 스택 도입 계획 — Harbor · Prometheus/Grafana · Langfuse · Ragas

> 문서 ID: PLAN-LAB-ADDONS-001 (v0.1, 2026-10-12) · 상태: **계획 (미구현)**
> 대상: RKE2 2노드 랩(P3 `rke2-master-01` amd64 + PGX `pgx` arm64 GB10). 랩은 **온라인** 환경 기준이며 오프라인(폐쇄망) 반입 절차는 다루지 않는다.
> 원칙: **모든 구성요소를 현재 K8s 클러스터에 Helm 으로 설치**한다 — 기존 플랫폼 설치 방식(`rke2_two_node_test_guide.md` §1.4·§4)을 그대로 따른다.
> 관련: 구축 가이드 `rke2_two_node_test_guide.md`(이하 **가이드**) · 설계 `docs/TDD.md` · 아키텍처 `docs/manual/system-architecture.html`

---

## 1. 목표와 범위

| 구성요소 | 목적 | 대체·보강 대상 |
|---|---|---|
| **Harbor** | 컨테이너 레지스트리 + 태그 보존·GC + Trivy 취약점 스캔 + 프로젝트 권한 | P3 Docker 의 `registry:2`(K8s 밖, 수동 운영) |
| **Prometheus · Alertmanager · Grafana** (kube-prometheus-stack) | 노드·Pod·GPU·vLLM·앱 metric 수집, 대시보드, 디스크·장애 알람 | chart 의 `rag-grafana-dashboards` ConfigMap(현재 수집기 없음) |
| **Langfuse** (v3) | 질문 1건 단위 LLM 트레이스(검색·재정렬·생성 단계, 토큰, 지연), 평가 점수 보관 | 로그(`structlog`) 기반 추적 |
| **Ragas** | LLM-judge 기반 RAG 품질 지표(Faithfulness 등) | `tools/evaluation` 의 규칙 기반 지표(Recall@10 등) — 알려진 미구현 "LLM-judge" 해소 |

범위 밖: 오프라인 반입, HA(복제본 2 이상), 외부 알림 채널(메일·메신저), 운영(PoC) 환경 적용.

---

## 2. 현재 상태 (2026-10-11~12 클러스터·리포 실측)

| 항목 | 현황 | 계획 반영 |
|---|---|---|
| P3 리소스 | 실사용 CPU 1% · MEM 13%, **요청(request) 합계 CPU 71%(14.0/19.6) · MEM 23%** | 신규 요청을 그대로 더하면 CPU 요청 ≈ 92% → Pending 위험. §4 예산대로 요청 조정 |
| 디스크 | OS NVMe 1TB 10% · fast NVMe 512GB(`/data/fast`) ≈ 0% · HDD 4TB(`/data/bulk`) 2% | 용량 충분. DB류 → `local-fast`, 대용량 blob → `local-bulk` |
| 레지스트리 | `registry:2`(snap Docker, `$HOME/registry-data` → HDD bind). **`library/postgres·qdrant·redis·busybox` 가 레지스트리에 없음**(노드 캐시로만 동작) | Harbor 이관 시 함께 적재 |
| 대시보드 | `rag-grafana-dashboards` 패널 10개 중 **6개가 존재하지 않는 metric** 조회 (`chat_job_duration_seconds`, `chat_queue_depth`, `rag_insufficient_evidence_total`, `feedback_satisfaction_ratio`, `embedding_latency_seconds`, `rerank_latency_seconds`) | P2 에서 metric 구현 또는 패널 수정 |
| rag-worker metric | 포트 없음. RQ 는 작업마다 fork → 자식 프로세스의 metric 이 사라짐 | `prometheus_client` multiprocess 모드 + metric 포트 |
| embedding/reranker metric | `/metrics` 에 python·process 기본 metric 뿐 | 지연 히스토그램 추가 |
| NetworkPolicy | rag-* NS 전부 default-deny(ingress+egress), NS 간 허용은 라벨 `rag-platform=true` | 신규 NS 에는 이 라벨을 **붙이지 않고**(허용 범위 과다) 용도별 정책을 추가 |
| `monitoring` NS | 없음 (chart 의 대시보드 ConfigMap 이 전제) | P2 에서 생성 |
| Ragas 입력 | rag-api `citations[].excerpt` 최대 200자 — 청크 원문 없음 | 평가 전용 contexts 옵션 추가 |

---

## 3. 설치 방식 — 기존 클러스터 관례 준수

기존 플랫폼(`rag-platform` release)과 같은 규칙으로 각 구성요소를 **독립 Helm release** 로 설치한다.

| 관례 | 기존 플랫폼 | 부가 스택 적용 |
|---|---|---|
| 설치 도구 | Helm (`deploy/helm/rag-platform`) | 공식 chart(Helm repo) + 리포에 values 파일. chart 버전은 `--version` 으로 고정하고 values 파일 머리 주석에 기록 |
| values 위치 | `values.yaml` → `values-poc.yaml` → `values-lab.yaml` | `deploy/lab/<harbor\|monitoring\|langfuse>/values.yaml` (랩 전용) |
| Namespace | kubectl 로 사전 생성 + 라벨 (가이드 §4.1) | `harbor` · `monitoring` · `langfuse` 를 kubectl 로 사전 생성. release NS = 구성요소 NS (서드파티 chart 는 release NS 에 리소스를 만든다) |
| Secret | `secrets/rag/*` 파일 → `kubectl create secret --from-file` (gitignore) | `secrets/lab/<구성요소>/*` 동일 방식. values 에는 Secret **이름**만 |
| 노드 배치 | 전역 `nodeSelector: kubernetes.io/arch: amd64`, PGX 는 `dedicated=llm` taint 로 vLLM 전용 | 전부 P3(`kubernetes.io/arch: amd64`). 예외: node-exporter·DCGM exporter 는 양쪽 노드(taint 허용) |
| 저장소 | `local-fast`(NVMe 512GB, DB) / `local-bulk`(HDD, 대용량) / hostPath | DB·TSDB·ClickHouse → `local-fast`, 이미지 blob·MinIO → `local-bulk` |
| 외부 노출 | RKE2 내장 ingress-nginx(kube-system) + TLS Secret, `*.rag.lab.local` | `harbor` · `grafana` · `langfuse` `.rag.lab.local` Ingress (className `nginx`) |
| 설치 자동화 | `scripts/redeploy_lab.sh` (사전 점검·`--dry-run`) | 신규 `scripts/install_lab_addons.sh <component> [--dry-run]` 같은 형식 |
| 검증 | 가이드 §4.3 체크 | 구성요소별 완료 기준(§6) |

### 3.1 TLS — 랩 CA 도입

현재는 chat/admin 호스트용 자체 서명 인증서(`secrets/chat.crt`, Secret `rag-chat-tls`) 하나다. 호스트가 늘어나므로 **랩 CA 1개**로 정리한다.

1. `secrets/lab/ca/{ca.key,ca.crt}` 생성 → `*.rag.lab.local` + `rag.lab.local` 와일드카드 인증서 발급.
2. 각 NS 에 TLS Secret 생성(`lab-wildcard-tls`). 기존 `rag-chat-tls` 도 같은 인증서로 교체 가능(선택).
3. CA 신뢰 등록: 접속 PC 브라우저 · 양쪽 노드 containerd(`registries.yaml` 의 `tls.ca_file`) · P3 snap Docker(인증서 디렉터리 경로는 설치 시 확인 — snap 은 `/etc/docker/certs.d` 대신 snap 데이터 경로를 쓸 수 있음).

(대안: cert-manager + 자체 서명 ClusterIssuer. 인증서 자동 갱신이 필요해지면 도입. 랩에서는 정적 Secret 로 충분)

### 3.2 이름 해석

`harbor.rag.lab.local` 등은 DNS 가 없으므로 기존처럼 `/etc/hosts` 에 등록한다. **이미지 pull 은 노드의 containerd 가 하므로 P3·PGX 양쪽 노드의 `/etc/hosts` 에도 등록**해야 한다(접속 PC 외). Ingress 는 양쪽 노드에서 응답하므로 P3 IP(192.168.168.109) 하나로 통일.

---

## 4. 리소스·저장소 예산

### 4.1 CPU·메모리 요청 (P3, allocatable CPU 19.6 · MEM ≈ 122Gi)

| 구분 | CPU 요청 | MEM 요청 | 비고 |
|---|---|---|---|
| 현재 합계 | 14.0 | 29.6Gi | 71% / 23% |
| **조정**: reranker-api 4 → 2, embedding-api 2 → 1 | −3.0 | — | 실사용 기준. limit(8·6)는 유지해 색인 시 burst 허용 |
| Harbor (core·portal·registry·jobservice·DB·Redis·Trivy) | +1.0 | +2.5Gi | 구성요소별 100~250m |
| kube-prometheus-stack (Prometheus·Grafana·Alertmanager·KSM·operator·node-exporter) | +1.0 | +3.0Gi | Prometheus 500m/2Gi |
| Langfuse (web·worker·PG·ClickHouse·Redis·MinIO) | +2.0 | +6.0Gi | ClickHouse 1/4Gi |
| **조정 후 합계** | **≈ 15.0 (77%)** | **≈ 41Gi (34%)** | 여유 ≈ 4.6 코어 |

- 대안: PGX 의 `dedicated=llm` taint 를 완화해 Langfuse·모니터링을 PGX 에 배치. **권장하지 않음** — "PGX = LLM 전용" 설계 원칙과 GPU 노드 메모리(통합 128GB, vLLM `gpu-memory-utilization 0.90`)를 지키기 위해.
- 요청값은 설치 후 1주 실사용(`kubectl top`, Prometheus)을 보고 재조정한다.

### 4.2 저장소

| 볼륨 | StorageClass | 크기 | 비고 |
|---|---|---|---|
| Harbor registry(이미지 blob) | `local-bulk` (HDD) | 500Gi | 태그 보존 정책 + 주간 GC 로 상한 관리 |
| Harbor DB · Redis · Trivy DB · jobservice | `local-fast` | 5 + 2 + 5 + 1Gi | |
| Prometheus TSDB | `local-fast` | 50Gi | 보존 15일 |
| Grafana · Alertmanager | `local-fast` | 5 + 2Gi | |
| Langfuse PostgreSQL | `local-fast` | 10Gi | 플랫폼 PostgreSQL 과 **분리** (장애·업그레이드 영향 격리) |
| Langfuse ClickHouse | `local-fast` | 50Gi | trace·observation 저장 |
| Langfuse Redis | `local-fast` | 2Gi | |
| Langfuse MinIO(S3) | `local-bulk` | 50Gi | 이벤트·미디어 blob |
| **fast NVMe 합계** | | ≈ 215Gi | 기존 80Gi 포함, 512GB 의 ≈ 45% |

- local-path 는 PVC 크기를 강제하지 않는다 — `/data/fast` 사용률은 P2 알람(80%)으로 감시.
- `Retain`(local-bulk)/`Delete`(local-fast) 정책 차이를 uninstall 절차에 반영.

---

## 5. 네트워크 정책

기존 rag-* NS 의 default-deny 는 유지하고, chart(`templates/networkpolicy.yaml`)에 **용도별 허용 정책**을 추가한다. 신규 NS 에는 `rag-platform=true` 라벨을 붙이지 않는다.

| 정책 (신규) | 위치 | 허용 | 단계 |
|---|---|---|---|
| `allow-from-monitoring` | rag-app · rag-ai · rag-data | `monitoring` NS 의 Prometheus Pod → 각 서비스 metric 포트 (8001~8005, worker metric 포트, vLLM 8000, Qdrant 6333, exporter 포트) | P2 |
| `allow-egress-to-langfuse` | rag-app | rag-worker · rag-api → `langfuse` NS `langfuse-web:3000` | P3 |
| (외부 egress) | harbor · monitoring · langfuse | 제한 없음 (서드파티 chart, 온라인 랩) — default-deny 미적용 | — |

ingress-nginx → Harbor/Grafana/Langfuse 는 해당 NS 에 default-deny 가 없으므로 추가 정책 불필요.

---

## 6. 단계별 계획

진행 순서: **P0 → P1 → P2 → P3 → P4**. P2 의 앱 metric 보강(코드)은 P1 과 독립이라 병행 가능.

### P0. 사전 준비 (≈ 0.5일)

1. `values-lab.yaml` 요청 조정(§4.1) → `redeploy_lab.sh` 로 반영, Pending 없는지 확인.
2. 랩 CA·와일드카드 인증서 생성, 접속 PC·양쪽 노드 `/etc/hosts` 와 CA 신뢰 등록(§3.1~3.2).
3. Namespace 생성: `harbor` · `monitoring` · `langfuse` (`kubectl create ns ... --dry-run=client -o yaml | kubectl apply -f -`).
4. Helm repo 등록: goharbor · prometheus-community · langfuse.
5. `scripts/install_lab_addons.sh` 골격(사전 점검·`--dry-run`·구성요소별 서브커맨드).

**완료 기준**: P3 CPU 요청 ≤ 60%, `curl --cacert ca.crt https://chat.rag.lab.local/health/live` 성공.

### P1. Harbor (≈ 1일)

1. **설치** (`deploy/lab/harbor/values.yaml`)
   - expose = Ingress(`harbor.rag.lab.local`, className `nginx`, TLS = `lab-wildcard-tls`), `externalURL` 동일.
   - Ingress annotation: `proxy-body-size: "0"`, `proxy-read/send-timeout: "900"` — embedding 이미지 ≈ 2.4GB 레이어 push 대비.
   - persistence: registry → `local-bulk` 500Gi, 나머지 → `local-fast`. Trivy 활성.
   - 관리자 비밀번호·DB 비밀번호는 `secrets/lab/harbor/` → Secret.
2. **프로젝트·계정**: 프로젝트 `rag` · `ai` · `library`(모두 private). robot 계정 2개 — push(P3 빌드용), pull(노드용).
3. **노드 연동**: 양쪽 노드 `/etc/rancher/rke2/registries.yaml` 에 `harbor.rag.lab.local`(CA·pull robot 인증) 추가 → `rke2-server`/`rke2-agent` 재시작(실행 중 컨테이너는 유지되나 노드별로 순차 진행). P3 Docker 에 `docker login`.
4. **이관**: `crane copy`(또는 `skopeo copy --all`)로 `registry.local:5000` → Harbor. vLLM arm64 는 **멀티아키 manifest 유지 복사 필수**. 레지스트리에 없는 `library/postgres:16`·`qdrant:v1.12.1`·`redis:7`·`busybox:1.36.1` 은 docker.io 에서 바로 복사.
5. **정책**: 태그 보존 — 저장소별 최근 10개 + `26.09`·현재 배포 태그 보호. GC 주 1회. push 시 Trivy 스캔(랩은 차단 없이 보고만).
6. **리포 변경**: `values-lab.yaml` `global.imageRegistry`·데이터 계층·vLLM 이미지 경로, Makefile·`redeploy_lab.sh` 의 `REG` 기본값, `redeploy_lab.sh` 의 vLLM manifest 서버 측 복사(현재 인증 없는 Registry v2 API 호출) → `crane copy`/`crane tag` 로 교체, local-path 매니페스트의 helper 이미지 경로, 가이드 §1.5·§3.
7. **전환**: `registry:2` 는 2주 병행 후 중지. 기간 중 문제가 생기면 `values-lab.yaml` 의 레지스트리만 되돌린다.

**완료 기준**: `redeploy_lab.sh` 1회 성공(Harbor 기준), 양쪽 노드에서 pull 확인(vLLM 포함), Harbor UI 에 스캔 결과·보존 정책 표시.

**위험**: Harbor 가 내려가면 **새 이미지 pull** 이 실패한다(이미 받은 이미지로 도는 Pod 는 영향 없음). Harbor 자체 이미지는 docker.io 에서 받으므로 순환 의존은 없다. 노드 재부팅 전 Harbor 상태를 확인하는 점검 항목을 가이드에 추가.

### P2. Prometheus · Alertmanager · Grafana (≈ 2일, 앱 metric 포함)

1. **설치** (`deploy/lab/monitoring/values.yaml`, release `kube-prometheus-stack`, NS `monitoring`)
   - Prometheus: 보존 15일, TSDB 50Gi `local-fast`, `serviceMonitorSelectorNilUsesHelmValues=false`(다른 release 의 ServiceMonitor 수집).
   - RKE2 특이점: etcd·scheduler·controller-manager·kube-proxy metric 은 localhost 바인드 → **초기에는 해당 scrape 비활성**(필요 시 RKE2 config 의 bind-address 변경을 별도 과제로).
   - node-exporter: 모든 taint 허용 → P3·PGX 양쪽.
   - Grafana: Ingress `grafana.rag.lab.local`, 관리자 비밀번호 Secret, sidecar 가 `monitoring` NS 의 `grafana_dashboard: "1"` ConfigMap 로드(현재 chart 대시보드가 이 규약을 따름).
2. **수집 대상**
   - 플랫폼 서비스: chart 에 `templates/servicemonitors.yaml` 추가(`monitoring.serviceMonitors.enabled`) — chat-gateway·rag-api·admin-api·embedding-api·reranker-api·rag-worker·Qdrant.
   - vLLM `/metrics`(TTFT·throughput·KV cache): ServiceMonitor.
   - GPU: GPU Operator 의 DCGM exporter ServiceMonitor 활성(`dcgmExporter.serviceMonitor.enabled`).
   - ingress-nginx: RKE2 `HelmChartConfig`(kube-system `rke2-ingress-nginx`)로 metrics·ServiceMonitor 활성.
   - (선택) postgres-exporter · redis-exporter.
3. **NetworkPolicy**: `allow-from-monitoring`(§5).
4. **앱 metric 보강 (코드)** — 대시보드가 이미 쓰는 이름에 맞춘다(TDD §12.1 갱신).
   - rag-worker: `PROMETHEUS_MULTIPROC_DIR`(emptyDir) + metric HTTP 서버(전용 포트, Deployment port 추가). `chat_job_duration_seconds{stage}`(embed·search·rerank·llm·total), `rag_insufficient_evidence_total`.
   - 큐 깊이 `chat_queue_depth`: chat-gateway 가 scrape 시 RQ 큐 길이를 gauge 로 노출(또는 redis-exporter 로 대체하고 패널 수정).
   - embedding-api / reranker-api: `embedding_latency_seconds` / `rerank_latency_seconds` 히스토그램.
   - `feedback_satisfaction_ratio`: chat-gateway feedback 카운터(👍/👎)를 두고 **패널에서 비율 계산**으로 변경.
5. **대시보드**: RAG 대시보드 수정 + 공식 대시보드 import(Node Exporter Full, NVIDIA DCGM, vLLM, ingress-nginx). 대시보드 JSON 은 리포에 ConfigMap 으로 관리.
6. **알람 (PrometheusRule)**: `/`·`/data/fast` 사용률 ≥ 80% · 노드 DiskPressure · Pod 재시작 급증 · vLLM/embedding/reranker down · 색인 Job 실패 · ACK p95 > 2s · GPU 메모리 ≥ 95%. 랩은 Alertmanager 수신자 없이 Grafana 알람 화면에서 확인.

**완료 기준**: 모든 대시보드 패널에 값 표시(빈 패널 0), `/data/fast` 알람을 테스트로 발생·해소, PGX GPU 패널 표시.

### P3. Langfuse (≈ 2일, 앱 트레이싱 포함)

1. **설치** (`deploy/lab/langfuse/values.yaml`, release `langfuse`, NS `langfuse`)
   - langfuse-web·worker 각 1개. 번들 PostgreSQL·ClickHouse·Redis·MinIO 사용, **ClickHouse 단일 노드**(chart 기본의 다중 replica·keeper 축소).
   - Ingress `langfuse.rag.lab.local`.
   - `TELEMETRY_ENABLED=false`, `AUTH_DISABLE_SIGNUP=true`, `LANGFUSE_INIT_*` 로 조직·프로젝트·API 키 자동 생성.
   - salt·암호화 키(32바이트 hex)·NextAuth 키·DB 비밀번호 → `secrets/lab/langfuse/` → Secret.
   - chart values 키 이름은 설치 시점 chart README 기준으로 확정해 values 파일에 기록.
2. **앱 Secret**: Langfuse 프로젝트 secret key 를 `rag-chat-secrets` 에 `langfuse-secret-key` 로 추가 → 기존 규칙대로 `secretMount.keys` + `*_FILE` + `SecretStr`.
3. **앱 트레이싱 (코드, rag-api·rag-worker)**
   - 설정: `LANGFUSE_ENABLED`, `LANGFUSE_HOST`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY_FILE`, `LANGFUSE_CAPTURE_CONTENT`.
   - 구조: `rag/domain` 은 순수 Python 규칙 → domain 에 `Tracer` Protocol(기본 no-op)만 두고, Langfuse SDK 구현은 `rag/adapters` 에 둔다. 의존성은 rag-api 에만 추가.
   - trace 1개 = 채팅 Job 1개, **trace id = `message_id`**(Ragas 점수·피드백 연결 키).
   - span: `embed` → `search`(top_k, hit 문서 id·점수, 채널 필터 요약) → `rerank`(fallback 여부) → `generation`(모델, messages, 출력, usage, 첫 토큰 시간).
   - **fail-open**: 트레이싱 오류는 답변에 영향 없음, 키 없으면 비활성, 비동기 배치 전송. CLAUDE.md 의 fail-closed 규칙(인증 Secret 대상)과 다른 예외임을 문서에 명시.
   - `LANGFUSE_CAPTURE_CONTENT=true` 일 때 질문·문서 원문이 Langfuse 에 저장된다 → `rag_observability` 마스킹 적용, Langfuse 접근 계정 최소화, 보존 기간 설정.
4. **NetworkPolicy**: `allow-egress-to-langfuse`(§5).
5. **(선택) 피드백 → Langfuse score**: 피드백 경로는 LLM·Queue 호출 금지 + p95 500ms 이므로 실시간 전송하지 않는다. admin-api CronJob 이 주기적으로 feedback 을 읽어 trace(`message_id`)에 score 로 동기화.

**완료 기준**: 질문 1건 = trace 1개(4 span), 단계 지연이 Grafana `chat_job_duration_seconds` 와 일치, Langfuse 를 내려도 채팅 정상.

### P4. Ragas (≈ 1.5일)

1. **의존성**: `tools/evaluation` 에 선택 extra `ragas` 추가(기본 runner 는 경량 유지). LangChain 의존은 tools 에만 — `rag/domain` 규칙과 무관.
2. **평가 입력**: rag-api 내부 `POST /internal/v1/rag/completions` 에 `include_contexts` 옵션 → 응답에 청크 원문 목록(선택 필드). 스키마 변경은 `libs/schemas`(`RagCompletion`)에서만.
3. **지표**: Faithfulness · ResponseRelevancy · LLMContextPrecisionWithReference · LLMContextRecall. reference = 데이터셋 `ground_truth.answer_gist`. 기존 규칙 지표(Recall@10·Citation Precision·무근거 안전응답률)와 한 리포트에 병기.
4. **모델**: judge LLM = 랩 vLLM(`internal-rag-llm`, OpenAI 호환, thinking off). 임베딩 = embedding-api(KURE-v1)를 감싼 Ragas 커스텀 임베딩 클래스(OpenAI 호환 API 아님). 한국어 프롬프트 적응 여부는 `dataset-ko-pdf` 8문항으로 비교 후 결정.
5. **실행**: `tools/evaluation` Containerfile 신설 → `rag-app` NS 에서 K8s Job(`rag-eval`, part-of 라벨로 기존 NetworkPolicy 내 통신). Makefile `evaluate-lab` 타깃. 리포트는 Job 로그 + Langfuse.
6. **Langfuse 연계**: 평가셋을 Langfuse Dataset 으로 등록, 실행마다 dataset run 생성 + Ragas 점수를 trace score 로 기록 → 실행 간 비교를 Langfuse 화면에서.

**완료 기준**: `dataset-ko-pdf` 8문항 Ragas 4지표 리포트 생성, 같은 점수가 Langfuse dataset run 에 표시.

---

## 7. 리포 변경 목록 (예상)

| 구분 | 파일 |
|---|---|
| 신규 | `deploy/lab/{harbor,monitoring,langfuse}/values.yaml` · `scripts/install_lab_addons.sh` · `scripts/lab_ca.sh`(CA·인증서) · `deploy/helm/rag-platform/templates/servicemonitors.yaml` · PrometheusRule·대시보드 ConfigMap · `tools/evaluation/Containerfile` |
| chart 수정 | `networkpolicy.yaml`(2종) · `app-services.yaml`(worker metric 포트·emptyDir) · `monitoring.yaml`(대시보드 수정) · `values.yaml`/`values-lab.yaml`(레지스트리, 요청값, Langfuse env·secret, serviceMonitors) |
| 코드 | rag-api/worker(metric, `Tracer` Port + Langfuse adapter, `include_contexts`) · chat-gateway(큐 깊이·피드백 카운터) · embedding/reranker(지연 히스토그램) · `libs/schemas`(`RagCompletion.contexts`) · `tools/evaluation`(Ragas) — 각 테스트 포함 |
| 스크립트 | `redeploy_lab.sh`(REG, vLLM 태그 복사 방식) · Makefile(`REG`, `evaluate-lab`) |
| 문서 | 가이드(§1.5 Harbor, 신규 "부가 스택" 절, 트러블슈팅) · 운영자 매뉴얼 §8(모니터링·트레이스) · TDD §12(metric·트레이싱) · `docs/manual/architecture/build_diagrams.py`(그림 갱신) · CLAUDE.md(Layout·검증·알려진 미구현) |

---

## 8. 결정 사항

| # | 항목 | 결정 / 권장 |
|---|---|---|
| D1 | 설치 위치 | **결정**: 모두 현재 K8s 클러스터에 Helm 으로 설치 (Harbor 포함) |
| D2 | 오프라인 고려 | **결정**: 랩은 온라인 기준, 오프라인 절차 제외 |
| D3 | CPU 여유 확보 | 권장: 요청값 조정(§4.1), PGX 는 LLM 전용 유지 |
| D4 | Langfuse 원문 저장 | 권장: 랩은 저장(`CAPTURE_CONTENT=true`) + 마스킹, PoC 전 재검토 |
| D5 | Ragas judge LLM | 권장: 랩 vLLM(Qwen3.8-27B) 사용, 자기 평가 편향을 리포트에 명시 |
| D6 | Langfuse 저장소 | 권장: 번들 PostgreSQL 사용(플랫폼 PG 와 분리) |
| D7 | 진행 순서 | 권장: P0 → P1 → P2 → P3 → P4 (P2 앱 metric 은 병행 가능) |

## 9. 위험과 대응

| 위험 | 영향 | 대응 |
|---|---|---|
| Harbor 장애 | 새 이미지 pull 실패(재배포·Pod 재스케줄) | `imagePullPolicy: IfNotPresent` 유지, `registry:2` 2주 병행, 노드 재부팅 전 Harbor 점검 |
| `registries.yaml` 변경 시 RKE2 재시작 | 노드 컴포넌트 재기동 | 노드별 순차, 실행 중 컨테이너는 유지됨을 확인 후 진행 |
| CPU 요청 초과로 Pending | 신규·기존 Pod 기동 실패 | P0 요청 조정 선행, 설치 후 `kubectl describe node` 로 확인 |
| fast NVMe 사용 증가 | DB 쓰기 오류 | §4.2 예산, `/data/fast` 80% 알람 |
| Langfuse 에 사내 문서 원문 축적 | 정보 노출 범위 확대 | 마스킹, 계정 최소화, 보존 기간, D4 재검토 |
| Ragas judge 품질(한국어·JSON 출력) | 지표 신뢰도 저하 | 8문항 수동 검토로 보정, 프롬프트 적응 비교 |
| 서드파티 chart 업그레이드 | values 키 변경 | chart `--version` 고정, 업그레이드는 별도 작업으로 |

## 10. 일정 (예상)

| 단계 | 기간 |
|---|---|
| P0 사전 준비 | 0.5일 |
| P1 Harbor | 1일 |
| P2 모니터링 + 앱 metric | 2일 |
| P3 Langfuse + 트레이싱 | 2일 |
| P4 Ragas | 1.5일 |
| 문서·그림 갱신 | 0.5일 (각 단계에 분산) |
| **합계** | **≈ 7.5일** |
