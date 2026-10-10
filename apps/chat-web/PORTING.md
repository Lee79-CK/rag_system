# chat-web 이식 기록 (aiops_chatbot → rag_system)

| 항목 | 값 |
|---|---|
| 원본 저장소 | `../aiops_chatbot` (원본은 **수정하지 않음**) |
| 원본 커밋 | `a39d05badcd3b64c35eb698eb0307f599f08e808` (2026-09-18) |
| 원본 경로 | `apps/web` (Next.js 15 App Router) + `packages/shared` 일부 |
| 이식 경로 | `apps/chat-web` (npm, uv workspace 제외) |
| 백엔드 | `apps/chat-gateway` (Python FastAPI + python-socketio) — NestJS/Prisma 미이식 |
| 계약 SSOT | `libs/schemas/src/rag_schemas/webchat.py` (TS 타입은 `src/lib/query/hooks.ts`, `src/shared/*`) |

## 유지한 것 (원본 거의 그대로)
- 디자인 토큰·레이아웃: `src/styles/globals.css`, `components/ui/{primitives,Toast}.tsx`, `app/providers.tsx`
- 채팅 골격: `components/chat/{ChatView,Markdown}.tsx`, 레이아웃 A/B 스레드 패널
- API 클라이언트: `lib/api.ts` (Bearer + 401 시 refresh 재시도), `lib/format.ts`
- 인증: `shared/crypto/prehash.ts` (PBKDF2 600k prehash — 원문 비밀번호 미전송), 로그인 화면 구조
- 실시간: `lib/ws.ts`·`lib/useRealtime.ts` — socket.io `post.*` / `llm.stream.delta|end` 캐시 반영

## 변경한 것
| 파일 | 변경 |
|---|---|
| `package.json` | `@aiops/shared` workspace 의존 제거, 이름 `@rag/chat-web` |
| `next.config.ts` | `output: 'standalone'`, dev 에서만 `/api` → `CHAT_GATEWAY_URL` rewrite, CSP 에서 외부 CDN 제거 |
| `app/layout.tsx` | CDN 폰트(Pretendard / IBM Plex Mono) `<link>` 제거 (폐쇄망) — 시스템 폰트 fallback |
| `app/health/live/route.ts` | 신규 — K8s probe |
| `src/shared/*` | `packages/shared` 중 blocks/ws/prehash 만 인라인. 블록은 RAG 서브셋 |
| `lib/api.ts` | 오류 본문 `{error:{code,message}}`(TDD §3.3) 파싱 |
| `lib/ws.ts` | same-origin 기본, `transports: ['websocket']` 전용 (다중 replica sticky 불필요) |
| `lib/stores/*` | AuthUser 를 gateway 계약(role `user|admin`)으로, localStorage 키 `aiops.*` → `rag.*` |
| `lib/query/hooks.ts` | DTO 를 gateway 계약에 맞춤, AIOps 전용 훅 제거 |
| `components/chat/PostItem.tsx` | 리액션/핀/이벤트·승인 카드 제거, Bot 상태(접수·스트리밍·오류), 피드백 value=`feedback_token`(HMAC) |
| `components/chat/Composer.tsx` | 슬래시 커맨드/멘션/메일/Action Tier 제거 → Binding(모드·trigger) 안내, THREAD 모드면 전송 후 스레드 자동 오픈 |
| `components/chat/ChannelHeader.tsx` | 고객사/환경/Skill/MCP → RAG Binding 상태 |
| `components/shell/{Rail,ChannelSidebar}.tsx` | Threads/Events/관리/알림/DM/채널 브라우저 제거, 채널 필터(⌘K) |
| `components/thread/ThreadPanel.tsx` | 인시던트 상태/담당/심각도/요약/메일 제거 |
| `components/blocks/BlockRenderer.tsx` | event_card / approval_card / tool_trace 제거. TableView: `maxWidth 640` 제거(메시지 폭 전체), 열 폭 규칙 — right 열 내용 폭·중간 열 14rem 상한+줄바꿈·마지막 열(발췌) 확장(최소 12rem, 그 이하 가로 스크롤) |
| `app/(app)/profile/page.tsx` | 비밀번호 변경만 (세션/외부계정/프로필 편집 제거) |
| `app/login/page.tsx` | RAG 브랜딩, 외부 IdP 버튼 제거, 임시 비밀번호면 `/profile` 로 이동 |

## 제거한 것
`app/(app)/{admin,events,threads}`, `app/reset/[token]`, `components/mail/*`,
`components/shell/{NotificationCenter,ChannelBrowser}.tsx`, `components/thread/AssigneePicker.tsx`,
e2e(Playwright) 설정 — RAG 관리 기능은 `apps/admin-web` 이 담당한다.

## 원본 갱신 반영 방법
원본 UI 개선을 가져올 때는 위 "유지한 것" 파일을 diff 로 비교해 수동 반영한다.
prehash 알고리즘을 바꾸면 `libs/common` 의 고정 벡터 테스트(`test_fr_web_001_prehash_matches_web_client_vector`)가 실패하므로 서버 구현을 함께 갱신해야 한다.
