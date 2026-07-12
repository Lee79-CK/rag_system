# admin-web

폐쇄망 RAG 챗봇 **관리 포털** 프론트엔드 (M8, `docs/TDD.md` §7.6).
일반 사용자 채팅 UI는 없다 (NOGOAL-009) — 운영/관리 전용.

## Stack
React 18 + Vite + TypeScript + React Query(@tanstack/react-query) + Ant Design(antd) + react-router-dom.
빌드 산출물은 정적(`dist/`)이며 nginx가 서빙한다. API는 ingress에서 `/api` → admin-api 로 프록시된다.

## 폐쇄망 원칙
- 런타임 외부 호출 없음. 모든 API 호출은 상대경로 `/api/v1/...` 로만 나간다.
- 차트/폰트/아이콘 등 외부 CDN 미사용 (antd 아이콘 + 자체 SVG-free 막대그래프).
- Secret 값(Webhook URL/토큰)은 화면에 절대 표시하지 않는다. Channels 페이지는
  `secret_ref`(K8s Secret 이름)와 `secret_updated_at`만 노출한다 (FR-OPS-010).

## 인증 (dev)
DEC-003 Reverse-Proxy 헤더 신뢰 방식. 개발 시 상단 우측 사용자 버튼에서 `X-Auth-User`
값을 바꿀 수 있고, `VITE_DEV_AUTH_USER` 로 기본값을 설정한다. 운영에서는 oauth2-proxy/ingress가
헤더를 주입하므로 이 값은 무시된다.

## Commands
```bash
npm install
npm run dev        # vite dev server (:5173), /api → http://localhost:8003 프록시
npm run build      # tsc --noEmit + vite build → dist/
npm run preview    # 빌드 산출물 미리보기
npm run typecheck  # tsc --noEmit
npm run lint       # eslint
```

## Pages (§7.6)
Dashboard · Documents · Index Jobs · Channels · Chat Jobs · Settings · Evaluation ·
Feedback Dashboard(v1.1) · Audit Logs.

## admin-api 계약과의 차이 (deviations)
아래 화면은 admin-api에 아직 read/write 엔드포인트가 없어 기대 계약을 대상으로 구현했고,
응답이 없으면 빈 상태로 우아하게 표시된다.
- **Index Jobs**: `GET /api/v1/index-jobs`, `POST /api/v1/index-jobs/{id}/retry` (현재 admin-api는 `documents/{id}/reindex` 만 존재).
- **Audit Logs**: `GET /api/v1/audit-logs` (현재 미들웨어가 기록만 하고 조회 엔드포인트 없음).
- **Evaluation 승격**: `POST /api/v1/evaluation/candidates` (evaluation 라우터는 현재 read-only stub).
- **Knowledge Scope 편집기**: binding은 `knowledge_scope_id`(FK)만 저장한다. scope 객체 생성 API가 없어
  편집기는 scope 구성/미리보기 용도이며, 실제 저장은 `knowledge_scope_id` 입력으로 수행한다.
