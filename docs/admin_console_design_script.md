# Claude Design Script — RAG Platform Admin Console

> 용도: 이 문서 전체를 Claude(또는 Claude Code)에 입력하여 Admin 화면의 목업/프로토타입(HTML 또는 React)을 생성한다.
> 기준 문서: TDD-RAG-CHATBOT-POC-001 v1.2 §7.5(admin-api), §7.6(admin-web)
> 산출 대상: 관리자 전용 Web Console (일반 사용자 채팅 UI 아님 — 사용자 접점은 별도 앱 **chat-web**(Web Chat))
> 변경(v2.0): 사용자 접점이 Mattermost → Web Chat(`apps/chat-web` + `apps/chat-gateway`)으로 바뀜에 따라 채널 관리(채널 생성·Binding·멤버), **채팅 사용자** 화면을 반영하고 Mattermost 전용 요소(team_id, Incoming Webhook Secret, 연결 테스트, 답변 재전송)를 제거했다. (Mattermost 는 v2.0 에서 제거)

---

## 1. 디자인 지시 (Role Instruction)

당신은 엔터프라이즈 B2B 관리 콘솔 전문 프로덕트 디자이너다. 아래 명세를 기반으로 **폐쇄망 사내 RAG 챗봇 플랫폼의 Admin Console** 화면을 디자인하라.

**산출물 형식 (요청 시 택1):**
- A. 단일 HTML 파일 프로토타입 — 좌측 네비게이션 + 화면 전환 동작 포함, 더미 데이터 렌더링
- B. React(JSX) 컴포넌트 — 페이지별 분리, 더미 데이터는 상수로 포함
- C. 화면별 정적 목업 (SVG/HTML) + 설계 근거 설명

**공통 요구:**
- 모든 UI 텍스트는 한국어. 날짜는 `2026-07-17 14:30` 형식, 시간대 KST.
- 반응형 최소 폭 1280px (데스크톱 전용 콘솔). 모바일 대응 불필요.
- 더미 데이터는 §6의 샘플 데이터를 사용하라 (실제 도메인 문맥 유지 목적).
- 접근성: 명도 대비 WCAG AA, 키보드 포커스 링, 상태를 색상+아이콘+텍스트 3중으로 표기.

---

## 2. 제품 컨텍스트 (디자인 판단의 근거)

- **사용자 접점은 Web Chat(chat-web)이다.** 이 콘솔은 문서/채널/채팅 사용자/품질/운영을 관리하는 내부 도구다 (채팅 기능 없음). 화려함보다 **밀도, 스캔 속도, 오조작 방지**가 우선.
- **폐쇄망 환경**: 외부 폰트/CDN/이미지 사용 금지. 시스템 폰트 스택 또는 Pretendard(로컬 배포 가정)만 사용.
- **가장 위험한 오조작 2가지**를 UI가 구조적으로 방지해야 한다:
  1. 채널 멤버십 오설정 → 권한 없는 사용자가 채널에 들어와 대화·답변(=해당 채널 지식 범위의 문서 근거)을 열람하는 사고. **멤버십이 곧 Channel 격리 경계**다
  2. 문서 ACL/지식 범위 오설정 → 다른 부서 채널에서 문서 노출
  → 따라서 RAG 응답 활성화·멤버 변경·ACL 변경은 항상 **확인 다이얼로그 + 영향 요약** 패턴을 사용한다.
- 운영자는 하루에도 수십 번 "색인이 끝났나", "답변이 왜 실패했나", "품질이 떨어졌나"를 확인한다. **상태(Status)가 모든 화면의 1급 시민**이다.

### 2.1 사용자 역할 (RBAC) — 화면 노출 제어

| 역할 | 접근 화면 | 특이사항 |
|---|---|---|
| SYS_ADMIN | 전체 | 설정 변경, 채널 생성·Binding 활성화·멤버 관리, 채팅 사용자 생성/비밀번호 재설정 |
| DOC_ADMIN | Dashboard, Documents, Index Jobs, (채널 관리 읽기) | 문서 업로드/재색인/ACL |
| QUALITY_EVALUATOR | Dashboard, Evaluation, Feedback, Chat Jobs(읽기) | 👎 답변 → 평가셋 승격 |
| AUDITOR | Audit Logs, Dashboard(읽기) | 읽기 전용 |

권한 없는 메뉴는 숨김이 아니라 **비활성(disabled) + 툴팁 "권한 필요: SYS_ADMIN"** 으로 표기 (존재를 알되 접근 불가임을 학습시키는 목적).

---

## 3. 디자인 토큰

라이트 테마 기본 (관제형 대시보드가 아닌 업무형 콘솔이므로). 다크 모드는 선택 제공.

```css
:root {
  /* Color */
  --bg: #f7f8fa;            --surface: #ffffff;      --border: #e3e6ea;
  --text: #1a1f27;          --text-sub: #5b6472;     --text-disabled: #9aa3af;
  --primary: #2563eb;       --primary-hover: #1d4ed8;
  --success: #16a34a;       --warning: #d97706;      --danger: #dc2626;
  --info: #0891b2;          --neutral: #6b7280;
  /* Status 전용 (배경 tint) */
  --tint-success: #ecfdf3;  --tint-warning: #fffbeb;  --tint-danger: #fef2f2;
  --tint-info: #ecfeff;     --tint-neutral: #f3f4f6;
  /* Typography */
  --font: "Pretendard", -apple-system, "Noto Sans KR", sans-serif;
  --font-mono: "JetBrains Mono", "D2Coding", monospace;   /* ID, hash, 로그 */
  --fs-title: 20px; --fs-section: 16px; --fs-body: 14px; --fs-caption: 12px;
  /* Layout */
  --sidebar-w: 232px; --radius: 8px; --gap: 16px;
  --shadow: 0 1px 2px rgba(16,24,40,.06);
}
```

**상태 Badge 팔레트 (전 화면 공통, 반드시 동일 매핑 사용):**

| 상태 | 색 | 사용처 |
|---|---|---|
| ACTIVE / COMPLETED / active / 활성 | success | 문서, Job, Binding, 채팅 사용자 |
| INDEXING / RUNNING / QUEUED / PENDING | info (+스피너) | 진행 중 |
| PARSE_FAILED / INDEX_FAILED / FAILED | danger | 실패 — 클릭 시 오류 상세 |
| DELIVERY_FAILED / 임시 비밀번호 | warning | 답변 생성 후 Bot Post 갱신·실시간 전송 실패(채널 재조회 시 DB 기준 수렴) / 첫 로그인 전 비밀번호 변경 필요 |
| INACTIVE / DISABLED / inactive | neutral | 비활성 |

ID/hash/scope_key/chunk_id는 항상 `--font-mono` + 복사 버튼.

---

## 4. 정보 구조 (IA) 및 공통 레이아웃

```text
┌────────────┬──────────────────────────────────────────────┐
│  Sidebar    │  Topbar: 화면 제목 · 환경 배지(PoC) · 사용자/역할  │
│  ─────────  ├──────────────────────────────────────────────┤
│ 대시보드      │                                              │
│ 문서 관리     │              Content Area                    │
│ 색인 작업     │   (필터바 → 테이블/카드 → 상세 Drawer 패턴)       │
│ 채널 관리     │                                              │
│ 채팅 사용자    │                                              │
│ 대화 작업     │                                              │
│ 피드백       │                                              │
│ 품질 평가     │                                              │
│ 설정        │                                              │
│ 감사 로그     │                                              │
└────────────┴──────────────────────────────────────────────┘
```

**공통 패턴 규칙:**
- 목록 → 상세는 페이지 이동이 아닌 **우측 Drawer(560px)** 로 연다 (목록 컨텍스트 유지).
- 모든 테이블: 컬럼 정렬, 상단 필터바(상태/기간/검색), 우상단 새로고침 + 자동갱신 토글(10s), 페이지네이션(20행).
- 파괴적/위험 작업(활성화, 멤버 제거, 비밀번호 재설정, 삭제, 설정 저장)은 **영향 요약 확인 모달**: "이 작업으로 무엇이 바뀌는가"를 bullet 2~3개로 보여주고 확인 입력 또는 명시적 버튼.
- 빈 상태(Empty state)는 다음 행동 안내 포함 (예: "등록된 문서가 없습니다 → [문서 업로드]").
- 오류 상태는 표준 Error Schema의 `code`를 함께 표기 (예: `CHANNEL_NOT_BOUND`).

---

## 5. 화면별 상세 명세

### 5.1 대시보드 (Dashboard) — `/`

**목적**: 30초 안에 "시스템이 건강한가, 오늘 처리량과 품질은 어떤가"를 판단.

레이아웃 (위→아래):
1. **KPI 카드 6개** (1행): 오늘 질문 수 · 답변 성공률 · 답변 p95(초, 목표 30s 대비 게이지) · 활성 Channel 수 · 색인 대기/실패 · **만족률(👍 비율, 24h)**
2. **서비스 상태 스트립**: chat-gateway / chat-web / rag-worker / embedding / reranker / vLLM×2 / qdrant / postgres / redis — 각각 ●(success/danger) + 지연시간. vLLM은 GPU 사용률 미니 게이지.
3. **2열 위젯**: 좌 — 최근 24h 질문/답변 추이 라인차트(성공·실패 적층). 우 — 최근 실패 이벤트 리스트(실패 Chat Job, Index 실패, 근거부족 급증) → 클릭 시 해당 화면 딥링크.
4. **주의 배너 (조건부)**: FAILED/DELIVERY_FAILED Job > 0 이면 상단 warning 배너 "실패한 답변 N건 — [대화 작업에서 확인]". (재전송 기능 없음 — 답변 본문은 Bot Post 가 SSOT)

### 5.2 문서 관리 (Documents) — `/documents`  [DOC_ADMIN]

**목적**: 문서 생명주기(업로드→색인→활성→비활성/삭제) 관리. PRD 부록 C 상태 모델 기준.

- **필터바**: 검색(제목), 카테고리, 부서, 보안등급, 상태, 기간.
- **테이블 컬럼**: 제목 · 카테고리 · 부서 · 보안등급 · 활성 버전(v3) · 상태 Badge · Chunk 수 · 허용 Channel 수 · 최종 색인일 · 액션(⋯).
- **업로드 모달** (버튼: 우상단 Primary "문서 업로드"):
  - 드래그앤드롭 + 파일 선택 (pdf/docx/pptx/xlsx/txt/md/html, 100MB, 최대 10개)
  - 메타데이터 폼: 제목(파일명 기본), 카테고리(셀렉트), 부서, 보안등급(INTERNAL 기본), **허용 Channel(ACL) 멀티셀렉트 — Web Chat 채널 목록(`#rag-cloud-ops · Cloud 운영 Q&A` 형식), 값은 채널 UUID(`chat_channels.id` = Qdrant `allowed_channel_ids`), 기본 0개 — 명시 선택 강제**
  - 동일 hash 감지 시: "동일 파일이 이미 존재합니다 — [기존 문서 새 버전으로 등록] / [취소]"
  - 업로드 후 행동: "색인 시작" 체크박스 (기본 on)
- **상세 Drawer 탭**: ① 개요(메타데이터 편집) ② 버전 이력(버전별 상태/hash/롤백 버튼) ③ Chunk 미리보기(청크 목록 + 본문 발췌, mono) ④ 허용 Channel(ACL 편집 — 변경 시 영향 요약 모달: "이 문서가 rag-hr 채널 검색에 노출됩니다")
- **행 액션**: 재색인 · 비활성화(즉시 검색 제외 안내) · 삭제(확인 모달: "색인된 128개 청크가 검색에서 제외됩니다") · 새 버전 업로드.

### 5.3 색인 작업 (Index Jobs) — `/index-jobs`  [DOC_ADMIN]

**목적**: 파싱→색인 파이프라인 진행/실패 모니터링.

- **테이블**: 문서 제목 · 버전 · 상태 Badge · **진행 스테퍼**(PARSING→CHUNKING→EMBEDDING→UPSERTING→VALIDATING, 현재 단계 하이라이트) · 진행률 bar · Chunk/Vector 수 · 소요시간 · 시작/완료 시각 · 액션(재시도).
- **실패 행 확장**: 오류 코드(`SCANNED_NO_OCR`, `ENCRYPTED_FILE` 등) + 원인 설명 + 권장 조치("OCR 옵션을 활성화하거나 텍스트 PDF로 재업로드하세요").
- 진행 중 Job은 자동갱신(5s). 완료 시 토스트 "장애대응매뉴얼 v2 색인 완료 — 128 chunks".

### 5.4 채널 관리 (Channels) — `/channels`  [SYS_ADMIN 쓰기]

**목적**: Web Chat 채널의 생성, RAG 응답 설정(Binding), 멤버십을 안전하게 관리. 채널 = chat-web 사용자 대화 공간 · Binding = 채널의 RAG 응답 설정 · **멤버십 = Channel 격리 경계**. **이 화면이 오조작 위험 최고 지점.**

- **읽기 전용 배너**: SYS_ADMIN 이 아니면 상단에 "읽기 전용 모드 — 채널 생성·Binding·멤버 관리에는 SYS_ADMIN 권한이 필요합니다."
- **필터바**: 채널 검색(name/표시 이름) · RAG 응답(전체/활성/비활성) · 새로고침 · 우상단 Primary **[채널 만들기]**.
- **테이블** (채널 × Binding 1행): 채널(`#rag-cloud-ops` + 표시 이름 + UUID mono) · 공개(public/private Badge) · 모드 Badge(전용 / 트리거 `!rag`) · 지식 범위(Scope 지정 / 전체 ACL) · 이력(턴) · 피드백(on/off) · **RAG 응답 토글** (Binding 없으면 [+ Binding] 버튼) · 액션([편집] [멤버]).
- **채널 만들기 / Binding 편집 Drawer — 3단계 위저드** (Mattermost 시절의 team_id·Secret 단계는 없음):
  1. 채널 정보: 채널 이름(URL slug, 소문자·숫자·`-`·`_` 2~80자, 생성 후 변경 불가, mono) · 표시 이름 · 공개 범위(public/private — "어느 경우든 채널을 볼 수 있는 사람은 멤버뿐입니다" 툴팁) · 설명
  2. 동작 설정: 모드(전용 채널 DEDICATED_CHANNEL / 트리거 단어 TRIGGER_WORD — 트리거 단어 필수, 예 `!rag`), 대화 이력 turns(슬라이더 0–20, 기본 8), 질문자 멘션 · 접수 안내 표시 · 피드백 수집 토글
  3. 지식 범위: 기존 Scope 선택 또는 비우면 전체 ACL + **우측 실시간 미리보기 "이 범위에 포함되는 문서 12건"** 목록
  - 생성 완료 토스트: "채널/Binding이 생성되었습니다. (RAG 응답 비활성 — 멤버 추가 후 활성화하세요)" — **신규 Binding 은 항상 비활성으로 시작**.
- **멤버 Drawer (560px)**: 제목 `멤버 — #rag-cloud-ops`. 상단에 사용자 멀티셀렉트("추가할 사용자 선택 (채팅 사용자 메뉴에서 생성)") + [추가] (역할 기본 member — channel_admin 지정은 API `POST /api/v1/chat/channels/{id}/members {user_ids, role}` 지원). 하단 테이블: 이름 · 이메일(mono) · 역할 Badge · [제거](확인 모달: "제거하면 이 사용자는 즉시 채널 목록·대화·답변을 볼 수 없습니다"). Bot 계정은 선택지에 없음.
- **RAG 응답 활성화 확인 모달 (필수)** — 활성화 체크리스트:
  - 현재 멤버 수 표시 (0명이면 warning tint: "멤버가 없으면 아무도 이 채널을 사용할 수 없습니다. [멤버]에서 추가하세요.")
  - ☐ 지식 범위(Scope 지정 범위 / 전체 ACL 범위)가 이 채널 멤버에게 공개되어도 됩니다.
  - ☐ 대상 채널이 `#rag-cloud-ops` (`c0000000…`) 임을 확인했습니다.
  - 두 항목 모두 체크해야 [활성화] 버튼 활성.
- **비활성화**: 확인 모달 "비활성화하면 이후 이 채널의 질문에 RAG 가 응답하지 않습니다 (일반 대화는 계속 가능)."

### 5.5 채팅 사용자 (Chat Users) — `/chat-users`  [SYS_ADMIN]

**목적**: chat-web 로그인 계정 관리. 외부 IdP 없음 — 관리자가 계정을 만들고 임시 비밀번호를 전달한다.

- **테이블**: 이름(+Bot 이면 `BOT` Badge) · 이메일(로그인 ID, mono) · 역할 Badge(user / admin — admin 은 모든 채널에서 메시지 삭제 가능) · 상태(active/inactive + "임시 비밀번호" warning Badge) · 생성일 · 활성 토글 · 액션([비밀번호 재설정]).
- **사용자 추가 모달**: 이메일(로그인 ID) · 표시 이름 · 역할. 저장 시 서버가 임시 비밀번호를 생성해 **응답에 1회만** 반환 → 결과 모달에 mono + 복사 버튼으로 표시, "이 창을 닫으면 **다시 확인할 수 없습니다**." / "첫 로그인 시 chat-web [내 정보]에서 비밀번호 변경이 요구됩니다." 고지.
- **비밀번호 재설정**: 확인 모달 "새 임시 비밀번호를 발급합니다. 기존 비밀번호로는 더 이상 로그인할 수 없습니다." → 동일한 1회 표시 결과 모달.
- 비밀번호 해시·기존 비밀번호를 보여주는 UI 는 없다 (API 응답에도 없음). Bot 계정(`RAG Assistant`)은 편집·재설정 불가.
- 채널 배정은 이 화면이 아니라 **채널 관리 → 멤버 Drawer** 에서 한다 (빈 상태 안내: "사용자를 만든 뒤 채널 관리에서 멤버로 추가하세요").

### 5.6 대화 작업 (Chat Jobs) — `/chat-jobs`

**목적**: 질문→답변 파이프라인 추적, 실패 원인 확인. (재전송/재시도 없음 — 답변 본문은 채널의 Bot Post 가 SSOT)

- **상단 탭**: 전체 / 진행 중 / **실패 N** (FAILED + DELIVERY_FAILED, 건수 Badge danger). 실패 행에는 "확인 필요" 태그.
- **테이블**: 시각 · Channel · 질문 요약(1줄 말줄임) · 질문/답변 Post id(mono) · 상태 Badge · 단계별 소요(Σ 8.4s = emb 0.2 + search 0.3 + rerank 0.8 + llm 6.5(첫 토큰 0.9) + 게시 0.1 — 미니 가로 적층바) · 오류 코드 · 피드백(👍/👎/−).
- **상세 Drawer**: 타임라인(질문 게시→큐→단계별→스트리밍→Bot Post 확정), 질문/답변 전문, Citation 목록(문서·페이지·score), 근거부족 여부, 오류 상세(`error`).
- DELIVERY_FAILED 는 "답변은 생성됐으나 Bot Post 갱신/실시간 전송 실패" 로 설명 — 사용자는 채널 재조회로 DB 기준 결과를 본다. 별도 복구 버튼은 두지 않는다.

### 5.7 피드백 (Feedback) — `/feedback`  [QUALITY_EVALUATOR, SYS_ADMIN] (v1.1)

**목적**: 👍/👎 수집 결과로 품질 저하 감지 → 개선 루프 연결.

- **상단 KPI**: 만족률(기간 셀렉트: 24h/7d/30d) · 총 피드백 수 · 👎 수(전 기간 대비 증감 화살표).
- **Channel별 막대 차트**: 만족률 내림차순, 표본 10건 미만 Channel은 회색 + "표본 부족" 라벨 (오독 방지).
- **👎 답변 테이블**: 시각 · Channel · 질문 · 답변 요약 · Citation 수 · 근거부족 여부 · 액션 **[평가셋 후보로 승격]** → 모달에서 YAML 초안(question/channel_id/ground_truth 골격) 미리보기 + "품질 평가자 검토 대기" 상태로 저장.
- 행 클릭 → 5.6의 Chat Job 상세 Drawer 재사용.

### 5.8 품질 평가 (Evaluation) — `/evaluation`  [QUALITY_EVALUATOR]

**목적**: 평가셋 실행 이력과 지표 추이 관리.

- **실행 이력 테이블**: 실행일 · 데이터셋 버전(문항 수) · Recall@10 · Citation Precision · Faithfulness · 무근거 안전응답률 · 격리 정확도 · 상태 · [리포트 보기].
- **지표별 목표선 표시**: 목표(85/90/85/90/100%) 대비 미달 셀은 danger tint.
- **비교 뷰**: 실행 2건 선택 → 지표 diff (▲2.3%p 형식) + 문항별 결과 변화 테이블(개선/악화/동일 필터).
- **평가셋 관리 탭**: 문항 목록(유형 비율 도넛: 단일30/종합20/표15/정의10/무근거15/모호10), 5.7에서 승격된 "검토 대기" 문항 편집·승인 흐름.

### 5.9 설정 (Settings) — `/settings`  [SYS_ADMIN]

**목적**: 검색/생성 파라미터 안전 변경 (60초 내 반영).

- **그룹 카드**: 검색(VECTOR_TOP_K, RERANK_TOP_N, SIMILARITY_THRESHOLD, RERANK_SCORE_THRESHOLD) / 생성(MAX_CONTEXT_TOKENS, MAX_OUTPUT_TOKENS, temperature) / 청크(CHUNK_SIZE, CHUNK_OVERLAP — "재색인 후 적용" 라벨) / 제한(Rate Limit 3종).
- 각 항목: 현재값 · 기본값 · 허용 범위 · 마지막 변경(누가/언제 — audit 연동) · 도움말 툴팁("Threshold를 올리면 무근거 안내가 늘고 오답이 줄어듭니다").
- 저장 버튼은 변경 항목 diff 요약 모달("VECTOR_TOP_K 30→40 외 1건") 후 적용. 버전 자동 증가.

### 5.10 감사 로그 (Audit Logs) — `/audit`  [AUDITOR]

- **필터**: 기간 · 행위자 · 액션 유형(로그인/문서/채널·Binding/멤버/채팅 사용자/설정) · 결과.
- **테이블**: 시각 · 행위자 · 액션 · 대상 · 결과 Badge · detail(JSON 뷰어 토글, mono).
- 읽기 전용. 내보내기(CSV) 버튼 — AUDITOR 권한.

---

## 6. 목업용 샘플 데이터 (더미)

```yaml
channels:
  - { name: rag-cloud-ops, display: "Cloud 운영 Q&A", id: c0000000-0000-0000-0000-000000000001, type: public,
      mode: 전용, scope: [운영매뉴얼, 장애대응], conversation: THREAD, turns: 8, enabled: true, members: 12, feedback: on }
  - { name: rag-hr, display: "인사 규정 Q&A", id: c0000000-0000-0000-0000-000000000002, type: public,
      mode: "트리거 !rag", scope: [인사규정], conversation: CHANNEL, turns: 8, enabled: true, members: 48, feedback: on }
  - { name: rag-security, display: "보안지침 Q&A", id: c0000000-0000-0000-0000-000000000003, type: private,
      mode: 전용, scope: [보안지침], conversation: CHANNEL, turns: 8, enabled: false, members: 0, feedback: off }
chat_users:
  - { name: 홍길동, email: hong@example.com, role: admin, status: active, channels: [rag-cloud-ops, rag-hr] }
  - { name: 김민수, email: kim@example.com, role: user, status: active, channels: [rag-hr] }
  - { name: 박신입, email: park@example.com, role: user, status: "active · 임시 비밀번호", channels: [] }
  - { name: RAG Assistant, email: rag-assistant@bot.local, role: user, bot: true, status: active }
documents:
  - { title: 장애대응매뉴얼, category: 장애대응, dept: Cloud운영팀, level: INTERNAL, ver: v3,
      status: ACTIVE, chunks: 128, channels: 1, indexed: 2026-07-15 }
  - { title: 2026 인사규정집, category: 인사규정, dept: 인사팀, level: INTERNAL, ver: v1,
      status: INDEXING(EMBEDDING 62%), chunks: "-", channels: 1, indexed: "-" }
  - { title: 스캔_구매지침.pdf, category: 구매, dept: 재무팀, level: INTERNAL, ver: v1,
      status: PARSE_FAILED(SCANNED_NO_OCR), chunks: 0, channels: 0, indexed: "-" }
chat_jobs:
  - { time: "07-17 14:02", channel: rag-cloud-ops, q: "장애 등급별 대응 절차를 알려주세요.",
      status: COMPLETED, total: 8.4s, feedback: 👍 }
  - { time: "07-17 13:55", channel: rag-hr, q: "!rag 연차 이월 규정이 어떻게 되나요?",
      status: COMPLETED, total: 11.2s, feedback: "-" }
  - { time: "07-17 13:41", channel: rag-cloud-ops, q: "DR 절체 승인권자는 누구인가요?",
      status: FAILED, total: 9.1s, feedback: "-" }
kpi: { today_q: 142, success: 97.2%, p95: 18.4s, active_channels: 2, index_pending: 1, index_failed: 1,
       satisfaction_24h: 91% }
feedback_down_sample:
  - { time: "07-17 11:20", channel: rag-hr, q: "육아휴직 급여 상한이 얼마인가요?",
      reason_hint: 근거부족 아님·Citation 2건, action: 평가셋 후보로 승격 }
```

---

## 7. 생성 절차 지시 (Claude 실행 순서)

1. §3 토큰과 §4 공통 레이아웃으로 **셸(사이드바+톱바) 먼저** 구축.
2. 화면 우선순위 순서로 생성: **Channels(5.4) → Chat Users(5.5) → Documents(5.2) → Chat Jobs(5.6) → Dashboard(5.1)** → 나머지. (위험도·사용빈도 기준)
3. 각 화면 완성 시 §5의 해당 명세와 대조하여 누락 요소 체크리스트를 출력할 것 (필터바/상태 Badge/빈 상태/확인 모달/권한 처리).
4. 모든 확인 모달에는 "영향 요약" bullet이 실제 문구로 들어가야 한다 — placeholder 금지.
5. 상태 Badge 색 매핑(§3)을 화면 간 불일치 없이 사용했는지 마지막에 자체 검증 결과를 보고할 것.

## 8. 금지 사항

- 외부 CDN/폰트/아이콘 로딩 (폐쇄망) — 아이콘은 inline SVG.
- 비밀번호/토큰 노출 UI — 임시 비밀번호는 발급 직후 결과 모달에 **1회만** 표시, 재조회 버튼·목록 표시 금지. 비밀번호 해시·서명 키 등 Secret 은 어떤 화면에도 없음.
- 일반 사용자용 채팅 인터페이스 추가 — 범위 외. 사용자 채팅은 **별도 앱 chat-web(`apps/chat-web`, 별도 host/Ingress)** 이 제공하며 admin-web 에는 채팅 기능을 두지 않는다 (SYS_ADMIN Test Console은 P1, 이번 산출물 제외).
- localStorage/sessionStorage 사용 (프로토타입은 메모리 상태만).
- 영어 UI 라벨 (기술 식별자 제외).
