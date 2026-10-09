#!/usr/bin/env bash
# 랩(RKE2 2노드) 재배포: 소스 변경 → 이미지 8종 빌드·push → helm upgrade → rollout 확인.
# 가이드 rke2_two_node_test_guide.md §4.6. P3(rke2-master-01)의 리포 루트에서 실행한다.
#
#   scripts/redeploy_lab.sh              # 커밋된 HEAD 를 빌드·배포
#   scripts/redeploy_lab.sh --dry-run    # 점검만 하고 실행할 명령을 출력
#   scripts/redeploy_lab.sh --skip-build # 이미 push 한 HEAD 태그로 helm upgrade 만
#
# 수작업에서 실제로 났던 사고를 막는다:
#   - REG/TAG 빈 값(잘린 이미지 경로)  → TAG 는 항상 git HEAD, REG 기본값 고정
#   - 커밋 안 한 변경이 섞인 이미지     → 작업 트리가 깨끗하지 않으면 중단 (TAG=sha 와 내용 불일치 방지)
#   - helm -n 누락(ownership 오류)      → release NS 고정
#   - vLLM 태그 불일치(ImagePullBackOff) → vLLM 은 values-lab 의 고정 태그(vllm.imageTag). 레지스트리에 없으면
#     현재 배포 중인 태그의 manifest 를 서버 측 복사(멀티아키 manifest list 그대로 — docker pull/push 하면 amd64 만 남는다)
set -euo pipefail

REG=${REG:-registry.local:5000}
RELEASE=rag-platform
RELEASE_NS=rag-platform
CHART=deploy/helm/rag-platform
VALUES=(-f "$CHART/values-poc.yaml" -f "$CHART/values-lab.yaml")
TIMEOUT=${TIMEOUT:-15m}
MANIFEST_ACCEPT='application/vnd.oci.image.index.v1+json,application/vnd.docker.distribution.manifest.list.v2+json,application/vnd.oci.image.manifest.v1+json,application/vnd.docker.distribution.manifest.v2+json'

DRY_RUN=0
SKIP_BUILD=0
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    --skip-build) SKIP_BUILD=1 ;;
    -h | --help) sed -n '2,8p' "$0"; exit 0 ;;
    *) echo "알 수 없는 옵션: $arg" >&2; exit 2 ;;
  esac
done

log() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
die() { printf '\033[31m[중단] %s\033[0m\n' "$*" >&2; exit 1; }
run() {
  if ((DRY_RUN)); then printf '  [dry-run] %s\n' "$*"; else "$@"; fi
}
manifest_exists() { # repo tag
  [[ $(curl -s -o /dev/null -w '%{http_code}' -I -H "Accept: $MANIFEST_ACCEPT" \
    "http://$REG/v2/$1/manifests/$2") == 200 ]]
}

cd "$(git rev-parse --show-toplevel)"

# ---- 1. 사전 점검 ----
log "사전 점검"
for bin in git make docker helm kubectl curl; do
  command -v "$bin" >/dev/null || die "$bin 명령이 없습니다."
done
git diff --quiet && git diff --cached --quiet ||
  die "커밋하지 않은 변경이 있습니다. 이미지 태그(git sha)와 내용이 달라지므로 먼저 커밋하세요. (git status)"
TAG=$(git rev-parse --short HEAD)
P3_IP=${P3_IP:-$(kubectl get nodes -l node-role.kubernetes.io/control-plane \
  -o jsonpath='{.items[0].status.addresses[?(@.type=="InternalIP")].address}')}
[[ -n $P3_IP ]] || die "P3_IP 를 알 수 없습니다. export P3_IP=<P3 IP> 후 재실행하세요."
curl -sf "http://$REG/v2/" >/dev/null ||
  die "레지스트리 http://$REG 에 접속할 수 없습니다 (가이드 §1.5)."
echo "  REG=$REG  TAG=$TAG ($(git log -1 --format=%s))  P3_IP=$P3_IP  release=$RELEASE_NS/$RELEASE"

# vLLM 은 앱과 분리된 고정 태그 — 렌더 결과에서 실제 이미지 참조를 읽는다.
VLLM_IMAGE=$(helm template "$RELEASE" "$CHART" "${VALUES[@]}" --set global.imageTag="$TAG" \
  --set "networkPolicy.apiServer.cidrs={$P3_IP/32}" -s templates/vllm.yaml |
  awk '/image:/{print $2; exit}')
[[ $VLLM_IMAGE == "$REG/"* ]] || die "vLLM 이미지가 $REG 를 가리키지 않습니다: $VLLM_IMAGE"
VLLM_REPO=${VLLM_IMAGE#"$REG/"}
VLLM_REPO=${VLLM_REPO%:*}
VLLM_TAG=${VLLM_IMAGE##*:}
if manifest_exists "$VLLM_REPO" "$VLLM_TAG"; then
  echo "  vLLM $VLLM_IMAGE 레지스트리에 있음 (앱 재배포만으로는 vLLM 재시작 없음)"
else
  CUR=$(kubectl -n rag-ai get deploy vllm-llm-0 -o jsonpath='{.spec.template.spec.containers[0].image}' 2>/dev/null || true)
  CUR_TAG=${CUR##*:}
  [[ $CUR == "$REG/$VLLM_REPO:"* ]] && manifest_exists "$VLLM_REPO" "$CUR_TAG" ||
    die "vLLM $VLLM_IMAGE 가 레지스트리에 없고 복사할 원본도 없습니다. 가이드 §3 대로 미러링하세요."
  log "vLLM 고정 태그 생성: $VLLM_REPO:$CUR_TAG → :$VLLM_TAG (레지스트리 서버 측 manifest 복사)"
  if ((DRY_RUN)); then
    echo "  [dry-run] GET /v2/$VLLM_REPO/manifests/$CUR_TAG → PUT /v2/$VLLM_REPO/manifests/$VLLM_TAG"
  else
    tmp=$(mktemp)
    trap 'rm -f "$tmp"' EXIT
    ctype=$(curl -sf -H "Accept: $MANIFEST_ACCEPT" -D - -o "$tmp" \
      "http://$REG/v2/$VLLM_REPO/manifests/$CUR_TAG" |
      awk -F': ' 'tolower($1)=="content-type"{gsub("\r",""); print $2}')
    curl -sf -X PUT -H "Content-Type: $ctype" --data-binary @"$tmp" \
      "http://$REG/v2/$VLLM_REPO/manifests/$VLLM_TAG" >/dev/null
    manifest_exists "$VLLM_REPO" "$VLLM_TAG" || die "vLLM 태그 복사 실패"
    echo "  완료 — 이번 배포에서 vLLM 은 태그 변경으로 1회 재시작됩니다(모델 재로딩 최대 10분)."
  fi
fi

# ---- 2. 빌드·push ----
if ((SKIP_BUILD)); then
  log "빌드 생략 (--skip-build) — $TAG 이미지가 이미 push 되어 있어야 함"
else
  log "이미지 8종 빌드·push ($TAG)"
  run make build-images push-images REG="$REG" TAG="$TAG"
fi
if ! ((DRY_RUN)); then
  missing=()
  for img in $(sed -n 's/^\(PY\|WEB\)_IMAGES := //p' Makefile); do  # make build-images 와 같은 목록
    manifest_exists "rag/$img" "$TAG" || missing+=("rag/$img")
  done
  ((${#missing[@]} == 0)) || die "레지스트리에 $TAG 태그가 없는 이미지: ${missing[*]}"
  echo "  레지스트리 확인: rag/* 8종 :$TAG 존재"
fi

# ---- 3. helm upgrade ----
log "helm upgrade ($RELEASE_NS/$RELEASE)"
run helm upgrade --install "$RELEASE" "$CHART" -n "$RELEASE_NS" "${VALUES[@]}" \
  --set global.imageTag="$TAG" \
  --set "networkPolicy.apiServer.cidrs={$P3_IP/32}" \
  --timeout "$TIMEOUT"

# ---- 4. rollout 확인 ----
log "rollout 확인 (최대 $TIMEOUT — embedding/reranker 는 HDD 모델 로딩, vLLM 은 재시작 시 최대 10분)"
for ns in rag-app rag-ai; do
  for d in $(kubectl -n "$ns" get deploy -l app.kubernetes.io/part-of=rag-platform -o name); do
    run kubectl -n "$ns" rollout status "$d" --timeout="$TIMEOUT"
  done
done
((DRY_RUN)) || kubectl get pods -A -l app.kubernetes.io/part-of=rag-platform -o wide
log "완료: $TAG 배포. 브라우저는 새로고침(F5)만 하면 됩니다(socket.io 자동 재연결)."
