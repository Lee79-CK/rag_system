# Claude Design Script — RAG Platform Admin Console

> 용도: 이 문서 전체를 Claude(또는 Claude Code)에 입력하여 Admin 화면의 목업/프로토타입(HTML 또는 React)을 생성한다.
> 기준 문서: TDD-RAG-CHATBOT-POC-001 v1.2 §7.5(admin-api), §7.6(admin-web)
> 산출 대상: 관리자 전용 Web Console (일반 사용자 채팅 UI 아님 — 사용자 접점은 Mattermost)

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

- **사용자 접점은 Mattermost다.** 이 콘솔은 문서/Channel/품질/운영을 관리하는 내부 도구다. 화려함보다 **밀도, 스캔 속도, 오조작 방지**가 우선.
- **폐쇄망 환경**: 외부 폰트/CDN/이미지 사용 금지. 시스템 폰트 스택 또는 Pretendard(로컬 배포 가정)만 사용.
- **가장 위험한 오조작 2가지**를 UI가 구조적으로 방지해야 한다:
  1. Channel Binding을 잘못된 Incoming Webhook(Secret)과 연결 → 답변이 다른 Channel에 게시되는 사고
  2. 문서 ACL/지식 범위 오설정 → 다른 부서 Channel에서 문서 노출
  → 따라서 활성화·Secret·ACL 변경은 항상 **확인 다이얼로그 + 영향 요약** 패턴을 사용한다.
- 운영자는 하루에도 수십 번 "색인이 끝났나", "답변이 왜 안 갔나", "품질이 떨어졌나"를 확인한다. **상태(Status)가 모든 화면의 1급 시민**이다.

### 2.1 사용자 역할 (RBAC) — 화면 노출 제어

| 역할 | 접근 화면 | 특이사항 |
|---|---|---|
| SYS_ADMIN | 전체 | 설정 변경, Secret 교체, Binding 활성화 가능 |
| DOC_ADMIN | Dashboard, Documents, Index Jobs, (Channels 읽기) | 문서 업로드/재색인/ACL |
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
| ACTIVE / COMPLETED / SENT / 활성 | success | 문서, Job, 전송, Binding |
| INDEXING / RUNNING / QUEUED / PENDING | info (+스피너) | 진행 중 |
| PARSE_FAILED / INDEX_FAILED / FAILED / DEAD_LETTER | danger | 실패 — 클릭 시 오류 상세 |
| INACTIVE / DISABLED / IGNORED | neutral | 비활성 |
| RETRYING / DELIVERY_PENDING | warning | 재시도 중 |

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
│ 채널 연동     │                                              │
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
- 파괴적/위험 작업(활성화, Secret 교체, 삭제, 설정 저장)은 **영향 요약 확인 모달**: "이 작업으로 무엇이 바뀌는가"를 bullet 2~3개로 보여주고 확인 입력 또는 명시적 버튼.
- 빈 상태(Empty state)는 다음 행동 안내 포함 (예: "등록된 문서가 없습니다 → [문서 업로드]").
- 오류 상태는 표준 Error Schema의 `code`를 함께 표기 (예: `CHANNEL_NOT_BOUND`).

---

## 5. 화면별 상세 명세

### 5.1 대시보드 (Dashboard) — `/`

**목적**: 30초 안에 "시스템이 건강한가, 오늘 처리량과 품질은 어떤가"를 판단.

레이아웃 (위→아래):
1. **KPI 카드 6개** (1행): 오늘 질문 수 · 답변 성공률 · 답변 p95(초, 목표 30s 대비 게이지) · 활성 Channel 수 · 색인 대기/실패 · **만족률(👍 비율, 24h)**
2. **서비스 상태 스트립**: bridge / rag-worker / embedding / reranker / vLLM×2 / qdrant / postgres — 각각 ●(success/danger) + 지연시간. vLLM은 GPU 사용률 미니 게이지.
3. **2열 위젯**: 좌 — 최근 24h 질문/답변 추이 라인차트(성공·실패 적층). 우 — 최근 실패 이벤트 리스트(Dead Letter, Index 실패, 근거부족 급증) → 클릭 시 해당 화면 딥링크.
4. **주의 배너 (조건부)**: Dead Letter > 0 이면 상단 warning 배너 "미전송 답변 N건 — [대화 작업에서 재시도]".

### 5.2 문서 관리 (Documents) — `/documents`  [DOC_ADMIN]

**목적**: 문서 생명주기(업로드→색인→활성→비활성/삭제) 관리. PRD 부록 C 상태 모델 기준.

- **필터바**: 검색(제목), 카테고리, 부서, 보안등급, 상태, 기간.
- **테이블 컬럼**: 제목 · 카테고리 · 부서 · 보안등급 · 활성 버전(v3) · 상태 Badge · Chunk 수 · 허용 Channel 수 · 최종 색인일 · 액션(⋯).
- **업로드 모달** (버튼: 우상단 Primary "문서 업로드"):
  - 드래그앤드롭 + 파일 선택 (pdf/docx/pptx/xlsx/txt/md/html, 100MB, 최대 10개)
  - 메타데이터 폼: 제목(파일명 기본), 카테고리(셀렉트), 부서, 보안등급(INTERNAL 기본), **허용 Channel 멀티셀렉트(기본 0개 — 명시 선택 강제)**
  - 동일 hash 감지 시: "동일 파일이 이미 존재합니다 — [기존 문서 새 버전으로 등록] / [취소]"
  - 업로드 후 행동: "색인 시작" 체크박스 (기본 on)
- **상세 Drawer 탭**: ① 개요(메타데이터 편집) ② 버전 이력(버전별 상태/hash/롤백 버튼) ③ Chunk 미리보기(청크 목록 + 본문 발췌, mono) ④ 허용 Channel(ACL 편집 — 변경 시 영향 요약 모달: "이 문서가 rag-hr 채널 검색에 노출됩니다")
- **행 액션**: 재색인 · 비활성화(즉시 검색 제외 안내) · 삭제(확인 모달: "색인된 128개 청크가 검색에서 제외됩니다") · 새 버전 업로드.

### 5.3 색인 작업 (Index Jobs) — `/index-jobs`  [DOC_ADMIN]

**목적**: 파싱→색인 파이프라인 진행/실패 모니터링.

- **테이블**: 문서 제목 · 버전 · 상태 Badge · **진행 스테퍼**(PARSING→CHUNKING→EMBEDDING→UPSERTING→VALIDATING, 현재 단계 하이라이트) · 진행률 bar · Chunk/Vector 수 · 소요시간 · 시작/완료 시각 · 액션(재시도).
- **실패 행 확장**: 오류 코드(`SCANNED_NO_OCR`, `ENCRYPTED_FILE` 등) + 원인 설명 + 권장 조치("OCR 옵션을 활성화하거나 텍스트 PDF로 재업로드하세요").
- 진행 중 Job은 자동갱신(5s). 완료 시 토스트 "장애대응매뉴얼 v2 색인 완료 — 128 chunks".

### 5.4 채널 연동 (Channels) — `/channels`  [SYS_ADMIN 쓰기]

**목적**: Mattermost Channel Binding의 안전한 등록·활성화. **이 화면이 오조작 위험 최고 지점.**

- **테이블**: Channel 이름(`rag-cloud-ops`) · Team · 모드 Badge(전용/트리거 `!rag`) · 지식 범위 요약(카테고리 chip) · 대화 모드(CHANNEL) · 피드백(on/off) · Secret 상태(등록일 + "90일 경과" warning) · 연결 테스트 결과(최근 ✓/✗ + 시각) · 활성 토글.
- **등록/편집 Drawer — 4단계 위저드**:
  1. Channel 정보: team_id, channel_id, channel_name (mono 입력, Mattermost에서 복사 안내 힌트)
  2. 동작 설정: 모드(전용 Channel/Trigger Word), trigger_word, 대화 모드, history_turns(슬라이더 0–20, 기본 8), 멘션/접수 메시지/피드백 토글
  3. 지식 범위: 기존 Scope 선택 또는 신규(카테고리/부서/보안등급/문서 지정 멀티셀렉트) + **우측 실시간 미리보기 "이 범위에 포함되는 문서 12건"** 목록
  4. Secret: Incoming Webhook URL 입력(마스킹, 붙여넣기 전용) → 저장 시 "K8s Secret으로 저장되며 이후 값 조회 불가" 고지. 기존 Secret은 `mattermost-incoming-rag-cloud-ops · 2026-05-02 등록` 형태로 참조명만 표시. [교체] 버튼만 제공.
- **활성화 토글 확인 모달 (필수)**: "다음을 확인했습니까?" ① 연결 테스트 성공(최근 결과 표시, 미실행 시 활성화 버튼 비활성) ② 지식 범위 문서 N건 ③ 대상 Channel명 재표기. 체크 후 활성화.
- **행 액션**: 연결 테스트(테스트 메시지 게시 → 결과 토스트+기록) · Secret 교체 · 비활성화("이후 질문에 무응답" 고지).

### 5.5 대화 작업 (Chat Jobs) — `/chat-jobs`

**목적**: 질문→답변 파이프라인 추적, Dead Letter 복구.

- **상단 탭**: 전체 / 진행 중 / 실패 / **미전송(Dead Letter) N** — Dead Letter 탭은 건수 Badge(danger).
- **테이블**: 시각 · Channel · 질문 요약(1줄 말줄임) · 상태 Badge · 단계별 소요(Σ 8.4s = emb 0.2 + search 0.3 + rerank 0.8 + llm 6.5 + delivery 0.6 — 미니 가로 적층바) · 피드백(👍/👎/−) · 액션.
- **상세 Drawer**: 타임라인(수신→큐→단계별→게시), 질문/답변 전문, Citation 목록(문서·페이지·score), 근거부족 여부, 오류/재시도 이력.
- **Dead Letter 액션**: [답변 재전송] — 확인 모달 "rag-cloud-ops 채널에 재게시합니다". 일괄 선택 재시도 지원.

### 5.6 피드백 (Feedback) — `/feedback`  [QUALITY_EVALUATOR, SYS_ADMIN] (v1.1)

**목적**: 👍/👎 수집 결과로 품질 저하 감지 → 개선 루프 연결.

- **상단 KPI**: 만족률(기간 셀렉트: 24h/7d/30d) · 총 피드백 수 · 👎 수(전 기간 대비 증감 화살표).
- **Channel별 막대 차트**: 만족률 내림차순, 표본 10건 미만 Channel은 회색 + "표본 부족" 라벨 (오독 방지).
- **👎 답변 테이블**: 시각 · Channel · 질문 · 답변 요약 · Citation 수 · 근거부족 여부 · 액션 **[평가셋 후보로 승격]** → 모달에서 YAML 초안(question/channel_id/ground_truth 골격) 미리보기 + "품질 평가자 검토 대기" 상태로 저장.
- 행 클릭 → 5.5의 Chat Job 상세 Drawer 재사용.

### 5.7 품질 평가 (Evaluation) — `/evaluation`  [QUALITY_EVALUATOR]

**목적**: 평가셋 실행 이력과 지표 추이 관리.

- **실행 이력 테이블**: 실행일 · 데이터셋 버전(문항 수) · Recall@10 · Citation Precision · Faithfulness · 무근거 안전응답률 · 격리 정확도 · 상태 · [리포트 보기].
- **지표별 목표선 표시**: 목표(85/90/85/90/100%) 대비 미달 셀은 danger tint.
- **비교 뷰**: 실행 2건 선택 → 지표 diff (▲2.3%p 형식) + 문항별 결과 변화 테이블(개선/악화/동일 필터).
- **평가셋 관리 탭**: 문항 목록(유형 비율 도넛: 단일30/종합20/표15/정의10/무근거15/모호10), 5.6에서 승격된 "검토 대기" 문항 편집·승인 흐름.

### 5.8 설정 (Settings) — `/settings`  [SYS_ADMIN]

**목적**: 검색/생성 파라미터 안전 변경 (60초 내 반영).

- **그룹 카드**: 검색(VECTOR_TOP_K, RERANK_TOP_N, SIMILARITY_THRESHOLD, RERANK_SCORE_THRESHOLD) / 생성(MAX_CONTEXT_TOKENS, MAX_OUTPUT_TOKENS, temperature) / 청크(CHUNK_SIZE, CHUNK_OVERLAP — "재색인 후 적용" 라벨) / 제한(Rate Limit 3종).
- 각 항목: 현재값 · 기본값 · 허용 범위 · 마지막 변경(누가/언제 — audit 연동) · 도움말 툴팁("Threshold를 올리면 무근거 안내가 늘고 오답이 줄어듭니다").
- 저장 버튼은 변경 항목 diff 요약 모달("VECTOR_TOP_K 30→40 외 1건") 후 적용. 버전 자동 증가.

### 5.9 감사 로그 (Audit Logs) — `/audit`  [AUDITOR]

- **필터**: 기간 · 행위자 · 액션 유형(로그인/문서/Binding/설정/Secret/재전송) · 결과.
- **테이블**: 시각 · 행위자 · 액션 · 대상 · 결과 Badge · detail(JSON 뷰어 토글, mono).
- 읽기 전용. 내보내기(CSV) 버튼 — AUDITOR 권한.

---

## 6. 목업용 샘플 데이터 (더미)

```yaml
channels:
  - { name: rag-cloud-ops, team: cloud-team, mode: 전용, scope: [운영매뉴얼, 장애대응], enabled: true,
      secret: mattermost-incoming-rag-cloud-ops (2026-05-02), last_test: 성공 2026-07-16 09:12, feedback: on }
  - { name: rag-hr, team: cloud-team, mode: "트리거 !rag", scope: [인사규정], enabled: true,
      secret: mattermost-incoming-rag-hr (2026-03-11 · 90일 경과), last_test: 성공 2026-07-10, feedback: on }
  - { name: rag-security, team: sec-team, mode: 전용, scope: [보안지침], enabled: false,
      secret: 미등록, last_test: 미실행, feedback: off }
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
      status: DEAD_LETTER, total: 9.1s, feedback: "-" }
kpi: { today_q: 142, success: 97.2%, p95: 18.4s, active_channels: 2, index_pending: 1, index_failed: 1,
       satisfaction_24h: 91% }
feedback_down_sample:
  - { time: "07-17 11:20", channel: rag-hr, q: "육아휴직 급여 상한이 얼마인가요?",
      reason_hint: 근거부족 아님·Citation 2건, action: 평가셋 후보로 승격 }
```

---

## 7. 생성 절차 지시 (Claude 실행 순서)

1. §3 토큰과 §4 공통 레이아웃으로 **셸(사이드바+톱바) 먼저** 구축.
2. 화면 우선순위 순서로 생성: **Channels(5.4) → Documents(5.2) → Chat Jobs(5.5) → Dashboard(5.1)** → 나머지. (위험도·사용빈도 기준)
3. 각 화면 완성 시 §5의 해당 명세와 대조하여 누락 요소 체크리스트를 출력할 것 (필터바/상태 Badge/빈 상태/확인 모달/권한 처리).
4. 모든 확인 모달에는 "영향 요약" bullet이 실제 문구로 들어가야 한다 — placeholder 금지.
5. 상태 Badge 색 매핑(§3)을 화면 간 불일치 없이 사용했는지 마지막에 자체 검증 결과를 보고할 것.

## 8. 금지 사항

- 외부 CDN/폰트/아이콘 로딩 (폐쇄망) — 아이콘은 inline SVG.
- Secret 값 노출 UI (URL/Token 표시, 조회 버튼) — 참조명과 등록일만.
- 일반 사용자용 채팅 인터페이스 추가 — 범위 외 (SYS_ADMIN Test Console은 P1, 이번 산출물 제외).
- localStorage/sessionStorage 사용 (프로토타입은 메모리 상태만).
- 영어 UI 라벨 (기술 식별자 제외).
