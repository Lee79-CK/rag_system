# RAG Assistant 운영자 매뉴얼

> 대상: 시스템 관리자(SYS_ADMIN) · 문서 관리자(DOC_ADMIN) · 품질 평가자 · 인프라 운영자
> 버전: v2.0 (2026-10) · 기준 환경: RKE2 2노드 랩(P3 `rke2-master-01` + PGX `pgx`). PoC/운영은 주소·values 만 다릅니다.
> 사용자용 문서: [사용자 매뉴얼](user-manual.md) · 설치/배포 상세: [`rke2_two_node_test_guide.md`](../../rke2_two_node_test_guide.md)(이하 **가이드**) · 설계: [`docs/TDD.md`](../TDD.md)

---

## 목차

1. [시스템 개요](#1-시스템-개요)
2. [관리자 포털 접속과 권한](#2-관리자-포털-접속과-권한)
3. [채팅 사용자 관리](#3-채팅-사용자-관리)
4. [채널 관리](#4-채널-관리)
5. [문서 관리와 색인](#5-문서-관리와-색인)
6. [품질 관리](#6-품질-관리)
7. [배포·변경 작업](#7-배포변경-작업)
8. [모니터링과 로그](#8-모니터링과-로그)
9. [백업과 복구](#9-백업과-복구)
10. [장애 대응](#10-장애-대응)
11. [보안 운영 수칙](#11-보안-운영-수칙)
12. [알려진 제약과 우회 방법](#12-알려진-제약과-우회-방법)
13. [부록 — 자주 쓰는 명령·상태값](#13-부록--자주-쓰는-명령상태값)

---

## 1. 시스템 개요

### 1.1 구성

| Namespace | 구성 요소 (포트) | 역할 |
|---|---|---|
| `rag-app` | chat-web(3000), chat-gateway(8001, REST + socket.io `/ws`), rag-api(8002), rag-worker(포트 없음), admin-api(8003), admin-web(8080) | 사용자/관리자 UI·API, 답변 생성 워커 |
| `rag-ai` | vLLM `vllm-llm-0`(8000, PGX GPU), embedding-api(8004), reranker-api(8005) | LLM · 임베딩 · 재순위 |
| `rag-data` | postgresql(5432), qdrant(6333), redis(6379) — 각 StatefulSet 1개 | 메타데이터·대화 / 벡터 / 큐·실시간 |
| `rag-ingestion` | parser-indexer Job (문서별 1회 실행) | 문서 파싱·색인 |
| `rag-platform` | (Pod 없음) Helm release 기록만 | **모든 helm 명령은 `-n rag-platform`** |

접속 주소(랩): 사용자 **`https://chat.rag.lab.local`**, 관리자 **`https://rag.lab.local`**

### 1.2 질문 처리 흐름

```
chat-web ─POST /posts─▶ chat-gateway ─(멤버십·트리거 판단, Bot Post 생성)─▶ Redis 큐(rag-chat)
                            ▲ socket.io 스트리밍                              │
                            └──────── rag-worker ◀───────────────────────────┘
                                         │ embedding-api → Qdrant(채널 필터 강제) → reranker-api → vLLM
```

- 질문 접수(ACK)는 2초 안에 응답하고, 답변은 워커가 비동기로 생성해 실시간 전송합니다.
- 검색은 항상 **채널 필터**(`allowed_channel_ids`)를 적용합니다. 문서가 어느 채널에서 검색될지는 문서의 **허용 채널**로 결정됩니다.

### 1.3 색인 흐름

```
admin-web 업로드 → admin-api(index_jobs 생성) → K8s Job(rag-ingestion) → 파싱→청크→임베딩→Qdrant 저장→검증 → 문서 ACTIVE
```

- 문서의 허용 채널은 **색인 시점**에 Qdrant 로 복사됩니다. 채널을 바꾸면 **재색인이 끝나야** 검색에 반영됩니다.

---

## 2. 관리자 포털 접속과 권한

### 2.1 인증 방식

관리자 포털에는 로그인 화면이 없습니다. admin-api 는 요청 헤더 **`X-Auth-User`** 값(= `admin_users.login_id`)을 신뢰합니다.

- **운영(PoC)**: 앞단 인증 프록시(oauth2-proxy 등)가 헤더를 주입하고 **클라이언트가 보낸 헤더는 제거**해야 합니다.
- **랩**: 프록시가 없으므로 포털 우상단 사용자 버튼 → **"접속 사용자 (dev)"** 에 `cklee` 입력 → [적용]. (브라우저 localStorage 에 저장)

> ⚠️ 랩 구성은 누구나 헤더를 위조할 수 있습니다. **인증 프록시 없이 관리자 주소를 외부에 노출하지 마세요.**

### 2.2 역할과 메뉴

| 메뉴 | 경로 | 사용 가능한 역할 |
|---|---|---|
| 모니터링 › 대시보드 | `/` | 전체 (역할에 따라 일부 지표만 표시) |
| 지식 관리 › 문서 관리 | `/documents` | SYS_ADMIN, DOC_ADMIN |
| 지식 관리 › 색인 작업 | `/index-jobs` | SYS_ADMIN, DOC_ADMIN (§5.2) |
| 서비스 운영 › 채널 관리 | `/channels` | SYS_ADMIN (DOC_ADMIN 은 **읽기 전용**) |
| 서비스 운영 › 채팅 사용자 | `/chat-users` | SYS_ADMIN |
| 서비스 운영 › 대화 작업 | `/chat-jobs` | SYS_ADMIN, QUALITY_EVALUATOR |
| 품질 › 피드백 | `/feedback` | SYS_ADMIN, QUALITY_EVALUATOR |
| 품질 › 품질 평가 | `/evaluation` | SYS_ADMIN, QUALITY_EVALUATOR (API 스텁 — CLI 사용, §6.2) |
| 시스템 › 설정 | `/settings` | SYS_ADMIN (※ 변경해도 답변에 반영 안 됨, §6.3) |
| 시스템 › 감사 로그 | `/audit` | SYS_ADMIN, AUDITOR (§8.4) |
| 시스템 › 오류 로그 | `/errors` | SYS_ADMIN — 대화·색인·관리 API 오류와 관련 파드 로그 (§10.2) |

- 메뉴 권한은 admin-api 권한과 일치합니다. 권한이 없는 메뉴는 사이드바에서 비활성화되고, 주소를 직접 입력해도 **"이 화면에 접근할 권한이 없습니다"** 가 표시됩니다.
- 접속 사용자를 확인할 수 없으면(`X-Auth-User` 미설정·미등록) 모든 화면 대신 **"관리자 신원을 확인할 수 없습니다"** 가 표시됩니다 — 랩에서는 우상단 접속 사용자를 확인하세요.
- DOC_ADMIN 은 문서의 **허용 채널 선택**에 필요한 채널 목록을 조회할 수 있지만, 채널·Binding·멤버 변경은 SYS_ADMIN 만 가능합니다.

### 2.3 관리자 계정 추가 (SQL)

관리자 계정 관리 화면은 없습니다. PostgreSQL 에 직접 등록합니다.

```bash
kubectl -n rag-data exec -i sts/postgresql -- psql -U rag -d rag <<'SQL'
INSERT INTO admin_users (id, login_id, display_name, department, status)
VALUES (gen_random_uuid(), 'newadmin', '홍길동', '운영팀', 'ACTIVE');
INSERT INTO user_roles (user_id, role_id)
SELECT u.id, r.id FROM admin_users u, roles r
WHERE u.login_id = 'newadmin' AND r.name = 'SYS_ADMIN';   -- DOC_ADMIN / QUALITY_EVALUATOR / AUDITOR
SQL
```

- 비활성화: `UPDATE admin_users SET status='INACTIVE' WHERE login_id='newadmin';` (즉시 401)
- 초기 seed(`scripts/seed_dev.sql`)는 `cklee`(SYS_ADMIN), `docadmin`(DOC_ADMIN) 을 만듭니다(가이드 §4.4).

---

## 3. 채팅 사용자 관리

메뉴: **서비스 운영 › 채팅 사용자** (SYS_ADMIN)

### 3.1 사용자 추가

1. [사용자 추가] → **이메일(로그인 ID)**, **표시 이름**, **역할**(user / admin) 입력.
2. **임시 비밀번호** 창이 뜹니다. [복사] 후 사용자에게 안전한 경로로 전달하세요. **창을 닫으면 다시 볼 수 없습니다.**
3. 사용자는 첫 로그인 후 [내 정보]에서 비밀번호를 바꿉니다(브라우저가 안내만 하고 강제하지는 않으므로 변경 여부를 확인하세요 — 상태 열의 "임시 비밀번호" 태그).
4. **채널 멤버로 추가해야** 사용자가 채널을 볼 수 있습니다(§4.3).

- 역할 `admin`: 자신이 멤버인 채널에서 다른 사람 메시지를 삭제(moderation)할 수 있습니다.
- 같은 이메일은 중복 등록할 수 없습니다(409 `DUPLICATE_USER`).

### 3.2 비밀번호 재설정 · 비활성화

| 작업 | 방법 | 효과 |
|---|---|---|
| 비밀번호 재설정 | 행의 [비밀번호 재설정] → 새 임시 비밀번호 1회 표시 | 기존 비밀번호 즉시 무효 |
| 계정 비활성화 | **활성** 스위치 끄기 | 로그인·토큰 갱신·API·실시간 연결 즉시 차단 (삭제 기능은 없음) |

### 3.3 비밀번호 정책과 보안

- 12자 이상, 영문 대/소문자·숫자·특수문자 중 3종 이상, 이메일 ID·표시 이름 포함 금지.
- 비밀번호 원문은 서버로 오지 않습니다(브라우저 PBKDF2 prehash → 서버 scrypt + pepper).
- **계정 잠금 기능은 없습니다.** 대신 로그인 속도 제한(이메일당 1분 10회, IP당 1분 50회).
- 대량 등록/랩 초기화는 스크립트 사용(`make seed-users`, `scripts/create_chat_user.py` — 가이드 §4.4). 스크립트는 비밀번호 정책을 검사하지 않으므로 운영에서는 포털의 임시 비밀번호 방식을 쓰세요.

---

## 4. 채널 관리

메뉴: **서비스 운영 › 채널 관리** (SYS_ADMIN)

채널 = 사용자가 대화하는 공간이자 **문서 격리 단위**. **Binding** = 그 채널의 챗봇 응답 설정입니다.

### 4.1 채널 만들기 (3단계 마법사)

[채널 만들기] →

| 단계 | 항목 | 설명 |
|---|---|---|
| ① 채널 정보 | 채널 이름 | URL slug (`^[a-z0-9][a-z0-9_-]{1,79}$`), **변경 불가**. 사용자 주소 `/ch/<이름>` |
| | 표시 이름 / 공개 범위 / 설명 | public·private 모두 **멤버만** 볼 수 있습니다(아이콘 차이) |
| ② 동작 설정 | 모드 | **전용 채널**(모든 메시지에 응답) / **트리거 단어**(접두어 메시지만, 예 `!rag`) |
| | 대화 이력 turns | 이전 질문·답변을 몇 회 참고할지 (기본 8, UI 0~20) |
| | 질문자 멘션 / 접수 안내 / 피드백 수집 | 답변 앞 `@이름`, "질문을 접수했습니다…" 표시, 👍👎 버튼 |
| ③ 지식 범위 | Knowledge Scope ID | 선택. 채널 안에서 카테고리·부서·보안등급으로 범위를 더 좁힐 때. 비우면 **허용 채널 ACL 전체** |

- 생성 직후 Binding 은 **비활성**입니다("RAG 응답 비활성 — 멤버 추가 후 활성화하세요").
- 지식 범위(Scope)를 쓰면 문서 ACL 이 허용돼도 Scope 조건(예: 보안등급 `INTERNAL`)에 맞지 않는 문서는 검색되지 않습니다. 원인 불명의 "근거 없음"이 나오면 Scope 를 먼저 확인하세요.

### 4.2 RAG 응답 활성화

목록의 **RAG 응답** 스위치 → "RAG 응답 활성화 확인" 창의 두 체크박스(멤버 수 확인 등) 확인 → 활성화. 끄면 챗봇만 멈추고 일반 대화는 계속됩니다. 목록의 [편집] 으로 모드·트리거 단어·이력·멘션·피드백 설정을 바꿉니다.

API 로 할 때(일괄 작업·자동화):

```bash
export ADMIN=https://rag.lab.local CURL_CA_BUNDLE=$PWD/secrets/chat.crt; H='X-Auth-User: cklee'
curl -s $ADMIN/api/v1/chat/channels -H "$H" | jq '.data[] | {name, member_count, bindings: [.bindings[] | {id, mode, enabled}]}'
curl -s -X POST $ADMIN/api/v1/chat/bindings/<binding_id>/enable  -H "$H" | jq .data.enabled
curl -s -X POST $ADMIN/api/v1/chat/bindings/<binding_id>/disable -H "$H" | jq .data.enabled
```

> 한 채널에는 Binding 을 하나만 두세요. 예전 버전에서 [+ Binding] 을 여러 번 눌러 중복이 생겼다면, 위 조회로 확인 후 쓰지 않는 Binding 을 `disable` 하세요(활성 Binding 이 여럿이면 가장 최근에 수정된 것이 쓰입니다).

### 4.3 멤버 관리

[멤버] → "추가할 사용자 선택" → [추가] / 행의 [제거]

- **멤버만** 채널을 보고 질문할 수 있습니다(비멤버는 채널 존재 자체를 모름 — 격리).
- UI 는 항상 `member` 로 추가합니다. 채널 관리자(`channel_admin`, 메시지 삭제 권한)는 API 로:
  `curl -X POST $ADMIN/api/v1/chat/channels/$CH/members -H "$H" -H 'Content-Type: application/json' -d '{"user_ids":["<uuid>"],"role":"channel_admin"}'`
- 제거된 사용자의 실시간 연결은 다음 재연결 시 끊깁니다.
- 채널 삭제·보관 기능은 없습니다. 쓰지 않는 채널은 Binding 비활성화 + 멤버 제거로 정리합니다.

### 4.4 새 채널 운영 체크리스트

1. 채널 생성(Binding 포함) → 2. 멤버 추가 → 3. 문서의 허용 채널에 새 채널 추가(§5.3) → 4. 재색인 완료 확인 → 5. Binding 활성화 → 6. 멤버 계정으로 시험 질문(출처 표 확인) → 7. 다른 채널에서 같은 질문 시 "근거 없음" 확인(격리)

---

## 5. 문서 관리와 색인

메뉴: **지식 관리 › 문서 관리**

### 5.1 업로드

[문서 업로드] →

| 항목 | 설명 |
|---|---|
| 파일 | `pdf, docx, pptx, xlsx, txt, md, html`, **최대 100MB**. 같은 내용(해시)의 파일은 다시 올릴 수 없음 |
| 제목 | 미입력 시 파일명 (평가셋은 제목 기준이므로 일관된 이름 권장) |
| 카테고리 / 부서 / 보안등급 | 지식 범위(Scope) 필터에 쓰입니다. 보안등급 PUBLIC·INTERNAL·CONFIDENTIAL·SECRET |
| 허용 Channel (ACL) | **이 문서가 검색될 채널.** 비우면 어느 채널에서도 검색되지 않습니다 |

- **업로드 후 바로 색인**(기본 체크): 업로드와 동시에 색인 Job 이 생성되고, 완료되면 상태가 `ACTIVE` 가 됩니다. 체크를 해제하면 `UPLOADED` 로 남으며 나중에 **[재색인]** 으로 색인합니다(허용 채널을 먼저 정리할 때 등). API 는 `start_indexing=true`(가이드 §5.1).

**여러 문서를 한꺼번에 올려도 됩니다.** 색인은 시스템이 **한 번에 1개씩(`INDEX_MAX_PARALLEL`) 순서대로** 처리합니다. 나머지 문서는 `INDEXING` 상태에서 차례를 기다리며(색인 Job `stage=WAITING`), 앞 문서가 끝나면 자동으로 시작됩니다. 임베딩 서버를 채팅 질의와 함께 쓰므로 동시에 여러 개를 돌리면 오히려 느려지고 실패하기 때문입니다. 대량 적재(수십 개·수천 쪽)는 채팅이 적은 업무 시간 외에 하세요.

**권장 문서 기준**(가이드 §5.1.1): 파일당 300쪽 이하(최대 500쪽), 텍스트 PDF(**스캔 PDF 미지원** — OCR 없음). 색인 시간 ≈ 쪽당 1~1.7초(300쪽 ≈ 5~9분). 업로드 전 점검: `uv run --package parser-indexer python scripts/inspect_pdf.py <파일>`.

### 5.2 색인 상태 확인

| 문서 상태 | 의미 |
|---|---|
| `UPLOADED` | 업로드됨, 색인 전 |
| `INDEXING` | 색인 Job 생성됨 / 진행 중 / **실패**(실패해도 이 상태로 남음 — 아래 확인) |
| `ACTIVE` | 색인 완료, 검색 가능 |
| `INACTIVE` | 비활성화 — 검색에서 제외, [활성화] 로 복구 (§5.5) |
| `DELETED` | 삭제(논리) — 검색에서 제외, 복구 불가 (§5.5) |

**포털 › 지식 관리 › 색인 작업**에서 문서별 색인 Job 의 상태·단계·진행률·청크 수·소요 시간·오류를 봅니다. 진행 중인 Job 이 있으면 5초마다 자동 갱신됩니다.

- `대기(순서)` = 다른 문서 색인이 끝나기를 기다리는 중(동시 색인 1건 제한). `중단 의심` = RUNNING 인데 오래 진행이 없음 → 문서 화면에서 [재색인] 하면 FAILED 로 정리되고 새 Job 이 뜹니다.
- **[재시도]** 는 실패·취소·트리거 실패 작업에만 활성화됩니다. 새 Job 이 생기고 원래 행은 이력으로 남습니다. 이전 버전의 작업은 재시도할 수 없습니다(문서 화면에서 현재 버전을 재색인).

화면에서 원인이 부족하면(파드 로그 등) 아래로 확인합니다.

```bash
kubectl -n rag-ingestion get jobs                                   # index-job-xxxxx 1/1 이면 성공 (완료 1시간 뒤 자동 삭제)
J=$(kubectl -n rag-ingestion get jobs --sort-by=.metadata.creationTimestamp -o name | tail -1)
[ -n "$J" ] && kubectl -n rag-ingestion logs $J | tail -20           # parsed → index_completed
kubectl -n rag-data exec sts/postgresql -- psql -U rag -d rag -c \
  "SELECT d.title, j.status, j.stage, left(j.error,80) error, j.created_at
     FROM index_jobs j JOIN document_versions v ON v.id=j.document_version_id JOIN documents d ON d.id=v.document_id
    ORDER BY j.created_at DESC LIMIT 10;"
```

| index_jobs.status | 조치 |
|---|---|
| `PENDING` + stage `WAITING` | **정상** — 앞 문서 색인이 끝나기를 기다리는 중(동시 색인 슬롯) |
| `PENDING` + error `TRIGGER_FAILED[k8s]` | K8s Job 생성 실패(RBAC/NetworkPolicy) — 가이드 §8, 원인 해결 후 [재색인] |
| `FAILED` + stage | 해당 단계 오류. EMBEDDING `ReadTimeout` 은 큰 문서 — 가이드 §5.1.1, §8 |
| `COMPLETED` | 성공 |
| `CANCELLED` | 정상 취소 — 문서 비활성화/삭제, 또는 새 [재색인] 요청으로 교체(error `SUPERSEDED`) |
| `FAILED` + error `STALE_RUNNING` | 2시간 넘게 RUNNING 에 남은 Job(Pod 강제 종료 등)을 자동 정리 — [재색인] |
| `FAILED` + error `SLOT_WAIT_TIMEOUT` | 6시간 넘게 차례를 못 받음 — 앞 Job 상태 확인 후 [재색인] |

### 5.3 허용 채널 변경 (기존 문서를 다른 채널에 연결)

행의 **[채널]** → 허용 채널 선택(현재 값이 미리 선택됨) → [저장]

- 저장 시 **재색인 Job 이 자동 생성**되고, 재색인이 끝나야 새 채널에서 검색됩니다. **제거한 채널에서도 재색인 완료 전까지는 검색됩니다.**
- 결과 메시지:

| 메시지 | 의미 |
|---|---|
| 재색인 시작 (완료 후 검색에 반영) | 정상 |
| 아직 색인 전 문서라 재색인하지 않았습니다 | `UPLOADED` — [재색인] 시 새 채널 적용 |
| 비활성 문서라 채널만 저장했습니다 | `INACTIVE` — [활성화] 시 새 채널로 다시 색인 |
| 대기 중인 색인 Job 이 실행될 때 새 채널이 반영됩니다 | 기존 대기 Job 재사용 |
| `[INDEX_JOB_RUNNING]` | 색인 진행 중 — 완료 후 다시 저장 |

- **같은 파일을 다시 업로드**하면 "이미 등록된 문서입니다" 창이 뜨고 [채널 연결] 로 기존 문서에 선택 채널을 추가할 수 있습니다.
- 여러 문서를 한 번에 바꿀 때는 API(`PATCH /api/v1/documents/{id}`) — 가이드 §5.1 의 일괄 스크립트 참고. 변경 이력은 감사 로그 `DOCUMENT_ACL_UPDATE`(before/after)에 남습니다.

### 5.4 재색인

[재색인] 은 문서를 처음부터 다시 파싱·임베딩합니다. 같은 문서가 이미 **대기 중**이면 새 요청으로 교체되고(이전 대기는 취소), **실행 중**이면 `INDEX_JOB_RUNNING` 으로 거부됩니다. 필요한 경우: 업로드 시 바로 색인하지 않은 문서, 색인 실패 후 재시도, 파서·임베딩 설정 변경 후. 큰 PDF 는 수 분~수십 분 걸립니다. 여러 문서를 연달아 눌러도 시스템이 하나씩 순서대로 처리합니다. 비활성·삭제 문서에는 [재색인] 이 비활성화됩니다(비활성 문서는 [활성화]).

### 5.5 비활성화 · 활성화 · 삭제

| 작업 | 효과 | 되돌리기 |
|---|---|---|
| **[비활성화]** | 검색에서 **즉시** 제외 (검색 색인 `is_active=false` 반영 후 상태 `INACTIVE`) | **[활성화]** |
| **[활성화]** (INACTIVE 문서) | 현재 허용 채널로 **재색인** → 완료되면 `ACTIVE` 로 검색 복귀 (수 분 소요) | — |
| **[삭제]** | 검색에서 **즉시** 제외, 상태 `DELETED` (논리 삭제 — 원본 파일·이력은 감사용으로 보존) | **불가**. 같은 파일 재업로드도 불가(해시 중복) |

- 색인이 **진행 중(RUNNING)** 이면 비활성화·삭제가 거부됩니다(`INDEX_JOB_RUNNING`) — 완료 후 다시 시도하세요. 대기 중인 색인 Job 은 자동 취소(`CANCELLED`)됩니다.
- 검색 색인(Qdrant)에 연결할 수 없으면 `SEARCH_INDEX_UNAVAILABLE`(503)로 실패하고 **문서 상태는 바뀌지 않습니다**. 화면과 실제 검색 상태가 어긋나지 않도록 한 동작이니 qdrant 파드 상태를 확인 후 재시도하세요.
- 비활성 중에 허용 채널을 바꾸면 채널만 저장되고, [활성화] 할 때 새 채널로 색인됩니다.
- 특정 채널에서만 빼려면 비활성화가 아니라 **허용 채널 변경**(§5.3)을 쓰세요.

---

## 6. 품질 관리

### 6.1 피드백

메뉴: **품질 › 피드백** — 👍/👎 합계, 만족률(UP/(UP+DOWN)), 채널별 통계, **👎 답변 목록**(질문·답변·인용).

👎 답변 점검 순서:
1. 인용 문서가 엉뚱함 → 문서 ACL·Scope, 동일 주제 문서 중복 여부 확인
2. 근거는 맞는데 답이 틀림 → 해당 문서 쪽의 파싱 품질 확인(`inspect_pdf.py`), 표·이미지 위주 페이지 여부
3. "근거 없음"인데 문서가 있음 → 허용 채널, 색인 상태(§5.2), 재색인 완료 여부
4. 반복되는 질문 유형은 평가셋에 추가(§6.2)

> 집계는 전체 기간 누적입니다(기간 필터 없음). [평가셋 승격] 버튼은 미구현입니다.

### 6.2 품질 평가 (CLI)

포털의 품질 평가 화면은 비어 있습니다. 평가는 P3 에서 실행합니다(가이드 §7.1).

```bash
kubectl -n rag-app port-forward svc/rag-api 8002:8002 &
RAG_API_URL=http://localhost:8002 make evaluate                       # → reports/evaluation_report.md
RAG_API_URL=http://localhost:8002 uv run python -m evaluation.runner \
  --dataset tests/evaluation/dataset-ko-pdf --out reports/eval_ko_pdf.md
```

지표: Recall@10, Citation Precision, 근거 없음 시 안전 응답률, 근거 기반 답변률. 목표(PRD): Recall@10 ≥ 85%, Citation Precision ≥ 90%, 안전 응답 ≥ 90%. 설정·모델 변경 전후로 같은 데이터셋을 돌려 비교하세요.

### 6.3 설정 화면에 대해

**시스템 › 설정** 의 값(VECTOR_TOP_K, RERANK_TOP_N, SIMILARITY_THRESHOLD 등)은 저장되지만 **답변 파이프라인에 반영되지 않습니다**(미연동). 튜닝은 Helm values 의 환경변수로 합니다.

```yaml
# deploy/helm/rag-platform/values-lab.yaml — appServices.rag-api.extraEnv (rag-worker 가 공유)
- { name: SIMILARITY_THRESHOLD, value: "0.3" }
```
→ 커밋 후 재배포(§7.1), 평가로 효과 확인. 현재 값: 검색 후보 `VECTOR_TOP_K`(기본 30, **랩 12**) → 재순위 상위 8건, 임계값 0.0, 출력 최대 1,024 토큰. 재순위 제한 시간 `RERANKER_TIMEOUT`(45초), reranker 입력 길이 `RERANKER_MAX_LENGTH`(랩 512). CPU reranker 는 후보 수·청크 길이에 비례해 느려지므로(30개×긴 한글 청크 ≈ 40~90초) 후보 수를 늘릴 때는 응답 시간을 함께 확인하세요.

### 6.4 대화 작업

메뉴: **서비스 운영 › 대화 작업** — 질문별 처리 상태(QUEUED·RUNNING·COMPLETED·DELIVERY_FAILED·FAILED)와 오류. **실패만 보기** 로 점검합니다. 재시도 기능은 없으며 사용자가 다시 질문하면 됩니다. `DELIVERY_FAILED` 는 답변은 생성됐으나 실시간 전송 실패 — 사용자가 채널을 다시 열면 보입니다.

---

## 7. 배포·변경 작업

### 7.1 소스 변경 재배포 (표준)

```bash
cd ~/workspace/rag_system
git add -A && git commit -m "변경 내용"
scripts/redeploy_lab.sh --dry-run    # 점검 + 실행 명령 출력
scripts/redeploy_lab.sh              # 빌드·push → helm upgrade(-n rag-platform) → rollout 확인
```

- 커밋하지 않은 변경이 있으면 중단합니다(이미지 태그 = 커밋 sha).
- vLLM(고정 태그 `vllm.imageTag`)과 데이터 계층은 재시작되지 않습니다. DB 스키마 변경은 migrate hook Job 이 자동 적용합니다.
- 사용자는 새로고침(F5)만 하면 됩니다(재로그인 불필요).
- 롤백: `helm rollback rag-platform -n rag-platform` 또는 이전 커밋 checkout 후 `scripts/redeploy_lab.sh --skip-build`.
- 상세: 가이드 §4.6.

### 7.2 배포 후 점검 (가이드 §4.3 ①~⑧ 요약)

```bash
kubectl get pods -A -l app.kubernetes.io/part-of=rag-platform -o wide          # 전부 Running/Ready
kubectl -n rag-app logs deploy/chat-gateway | grep -c "startup.*_missing"       # 0
kubectl -n rag-ai logs deploy/embedding-api | grep engine_ready                  # model 에 "-mock" 없어야 함
kubectl -n rag-ai logs deploy/reranker-api  | grep engine_ready
kubectl -n rag-app exec deploy/rag-api -- python -c "import httpx;print(httpx.get('http://vllm-service.rag-ai:8000/v1/models',timeout=10).json()['data'][0]['id'])"   # internal-rag-llm
df -h / /data/fast /data/bulk                                                    # NVMe 70% 미만
```
그리고 사용자 계정으로 시험 질문 1건(출처 표 확인).

### 7.3 LLM 모델 교체

1. PGX 에 새 모델을 **새 디렉터리**로 다운로드(기존 디렉터리 덮어쓰기 금지), `chmod -R a+rX`.
2. `values-lab.yaml` 의 `vllm.modelDir` 변경 → 커밋 → 재배포.
3. vLLM 파드가 재생성되며 로딩(최대 10분) 동안 질문은 오류 응답 — **사용자 공지 후 작업**.
4. 확인: `kubectl -n rag-ai get deploy vllm-llm-0 -o jsonpath='{.spec.template.metadata.annotations.ragplatform\.io/llm-model}'`
5. 롤백: `modelDir` 원복 후 재배포. 모델 계열이 바뀌면 `--reasoning-parser` 등 인자도 점검(가이드 §2.1.1).

vLLM **이미지** 교체는 새 태그로 미러링 후 `vllm.imageTag` 변경(가이드 §3).

### 7.4 임베딩 모델 교체 — 전체 재색인 필수

차원이 같아도 벡터가 섞이면 **오류 없이 검색 품질만 무너집니다.** 경로 변경 → 재배포 → `engine_ready` 확인 → Qdrant collection 삭제·재생성 → **전 문서 순차 재색인** → 평가 비교(가이드 §5.1.2 ⑤).

### 7.5 Secret 교체

| Secret 키 | 교체 영향 | 절차 |
|---|---|---|
| `jwt-secret` | 접속 중 사용자는 자동 재발급(재로그인 거의 없음) | `rag-chat-secrets` 갱신 → chat-gateway 재시작 |
| `feedback-signing-key` | **기존 답변의 피드백 버튼 무효(401)** | 갱신 → chat-gateway·rag-worker 재시작 |
| `password-pepper` | **모든 사용자 비밀번호 무효 → 전원 재설정 필요** | 사실상 고정값. 교체 시 전 사용자 임시 비밀번호 재발급 계획 수립 |
| TLS `rag-chat-tls` | 인증서 교체 | SAN 에 chat·admin 두 호스트 포함 |

재시작: `kubectl -n rag-app rollout restart deploy/chat-gateway deploy/rag-worker deploy/admin-api`. Secret 값은 Helm values·Git·로그에 절대 넣지 않습니다(§11).

### 7.6 확장

- 동시 답변 수 ≈ **rag-worker replica 수**(랩 2). `appServices.rag-worker.replicas` 조정 후 재배포. GPU 처리량을 넘기면 응답이 느려지므로 부하 시험으로 결정(가이드 §7.2).
- vLLM 은 GPU 1장당 1개(`vllm.replicas`). 데이터 계층은 replica 1 고정, HPA 없음.
- 동시 색인 수: `ingestion.extraEnv` 의 `INDEX_MAX_PARALLEL`(기본 1). embedding-api replica·CPU 를 늘린 경우에만 올리세요. 색인 Job Pod 메모리 상한은 `ingestion.resources`(8Gi).

---

## 8. 모니터링과 로그

### 8.1 헬스 체크

| 서비스 | 점검 |
|---|---|
| chat-gateway | `/health/ready` = Redis 연결 |
| admin-api | `/health/ready` = DB 연결 |
| rag-api · embedding · reranker | `/health/ready` = 모델/엔진 로딩 완료 |
| vLLM | `/health` (startupProbe, 로딩 최대 10분) |
| rag-worker | 프로브 없음 — 파드 Running 과 로그로 확인 |

외부 Ingress 로는 `/health` 가 노출되지 않습니다. `kubectl -n rag-app port-forward svc/chat-gateway 8001:8001` 후 `curl localhost:8001/health/ready`.

### 8.2 지표 (Prometheus)

현재 코드가 제공하는 지표는 **chat-gateway** 것뿐입니다: `gateway_post_received_total{result}`(accepted / rate_limited / not_member / enqueue_failed …), `gateway_ack_latency_seconds`, `gateway_login_total{result}`, `gateway_ws_connections`, `feedback_received_total`, `gateway_invalid_feedback_token_total`.

- 차트에 ServiceMonitor/스크랩 설정이 없으므로 Prometheus 수집은 별도 구성이 필요합니다.
- Grafana 대시보드(`monitoring.grafanaDashboards: true`, `monitoring` NS 선행 필요)의 10개 패널 중 **4개만 데이터**가 있습니다(나머지 지표 미구현).
- 주의 신호: `not_member` 급증(격리 위반 시도), `gateway_login_total{result="invalid"|"replay"}` 급증, `gateway_invalid_feedback_token_total` 증가, `enqueue_failed` > 0.
- 랩 최우선 경보: 디스크(`node_filesystem_avail_bytes{mountpoint=~"/|/data/.*"}`).

**목표치(SLO)**: 질문 접수 p95 ≤ 2초, 최종 답변 p95 ≤ 30초(동시 10), 검색 p95 ≤ 1초, 오류율 ≤ 1%, 가용성 ≥ 95%.

### 8.3 주요 로그 이벤트

로그는 JSON(structlog)이며 Secret·토큰·비밀번호 값은 자동 마스킹됩니다.

| 이벤트 | 서비스 | 의미 |
|---|---|---|
| `engine_ready` | embedding / reranker | `model` 값에 `-mock` 이면 **모델 미로딩(가짜 엔진)** — 즉시 조치 |
| `startup.*_missing`, `auth.secret_missing` | chat-gateway | Secret 누락 → 로그인 503 |
| `enqueue_failed`, `bot_post_update_failed`, `stream_emit_failed` | gateway / worker | 답변 전달 문제 |
| `documents.index_trigger_failed` | admin-api | 색인 Job 생성 실패 |
| `documents.acl_updated` | admin-api | 문서 허용 채널 변경 |
| `index_completed` / `index_failed` | parser-indexer | 색인 결과 (Job 로그는 1시간 후 삭제) |
| `worker.pipeline_failed` | rag-worker | 답변 실패 — `error` 에 예외 종류·대상 URL (예: `ReadTimeout: … [http://reranker-api…]`) |
| `worker.rerank_fallback` | rag-worker | 재순위 실패/시간 초과 → **벡터 순서로 답변**(오류 아님, 품질 다소 저하). 잦으면 §6.3 튜닝 |

```bash
kubectl -n rag-app logs deploy/rag-worker --since=1h | grep -i error
kubectl -n rag-ai  logs deploy/vllm-llm-0 --since=1h | tail -50
```
중앙 로그 수집(Loki 등)은 차트에 포함되어 있지 않습니다. 장기 보관이 필요하면 별도 구성하세요(목표 30일).

### 8.4 감사 로그

admin-api 의 모든 변경 요청(POST/PUT/PATCH/DELETE)은 `audit_logs` 에 기록됩니다. **포털 › 시스템 › 감사 로그**에서 행위자, Action/Path(부분 일치), Method, 결과(성공·권한 거부·오류), 기간으로 검색합니다.

- 문서 채널 변경은 작업 칸에 `DOCUMENT_ACL_UPDATE` 로 표시되고, [상세 › 보기]에 변경 전·후 채널 목록이 나옵니다. 오류 로그 열람은 `ERROR_LOG_VIEW` 입니다.
- 한 번에 최근 500건까지 표시합니다. 더 오래된 기록은 기간을 좁혀 검색하세요(잘린 경우 화면에 안내).
- 조회 권한: SYS_ADMIN, AUDITOR.

화면 대신 SQL 로 볼 때:

```bash
kubectl -n rag-data exec sts/postgresql -- psql -U rag -d rag -c \
  "SELECT ts, actor, action, result, detail FROM audit_logs ORDER BY ts DESC LIMIT 30;"
# 문서 채널 변경 이력만
kubectl -n rag-data exec sts/postgresql -- psql -U rag -d rag -c \
  "SELECT ts, actor, target, detail->'added' added, detail->'removed' removed FROM audit_logs WHERE action='DOCUMENT_ACL_UPDATE' ORDER BY ts DESC;"
```

---

## 9. 백업과 복구

> 현재 저장소에는 **백업 자동화(CronJob·스크립트)가 없습니다.** 아래는 PRD §24 정책에 따른 **권장 수동 절차**이며 랩에서 검증되지 않았습니다. 운영 전환 전 반드시 복구 시험을 1회 이상 수행하세요(목표 RPO 24시간 / RTO 4시간).

| 대상 | 방법 | 주기 / 보관 |
|---|---|---|
| PostgreSQL (사용자·채널·문서 메타·대화·피드백·감사) | `pg_dump` | 매일 / 14일 |
| 문서 원본 (`/data/bulk/documents`, 운영은 NFS PVC) | 파일 복사·스냅샷 | 매일 |
| Qdrant (벡터) | 스냅샷 또는 **재색인으로 재생성** | 매일 또는 문서 변경 후 / 7~14일 |
| 모델 파일 | 원본 아티팩트 보관 | 승인 버전 |
| 차트·설정 | Git | — |

```bash
# PostgreSQL 백업 / 복원
kubectl -n rag-data exec sts/postgresql -- pg_dump -U rag -d rag -Fc > /data/bulk/backup/rag-$(date +%F).dump
kubectl -n rag-data exec -i sts/postgresql -- pg_restore -U rag -d rag --clean --if-exists < /data/bulk/backup/rag-<날짜>.dump

# 문서 원본
sudo tar -C /data/bulk -czf /data/bulk/backup/documents-$(date +%F).tgz documents
```

- Qdrant 는 PostgreSQL(문서 메타·ACL) + 문서 원본만 있으면 **전 문서 재색인으로 복원**할 수 있습니다(시간은 문서량에 비례).
- 백업 파일에도 원본과 같은 접근 통제를 적용하세요. 백업 디렉터리는 HDD(`/data/bulk`)에 두고 NVMe 를 채우지 마세요.
- 보관 기간 정책(대화 90일, 감사 180일)에 따른 자동 삭제 Job 도 아직 없습니다.

---

## 10. 장애 대응

### 10.1 1차 점검 순서

1. `kubectl get pods -A -l app.kubernetes.io/part-of=rag-platform -o wide` — Running 아닌 파드. **vLLM 파드는 이 라벨이 없어 목록에 안 나오므로** `kubectl -n rag-ai get pods -o wide` 로 따로 확인
2. `kubectl -n <ns> describe pod <pod>` 의 Events / `kubectl -n <ns> logs <pod> --previous`
3. 노드 상태와 디스크: `kubectl get nodes`, `df -h`
4. 오류 원인은 포털 **오류 로그**(§10.2)에서 먼저 확인, 그 밖의 증상은 §10.3 표 → 상세는 가이드 §8 트러블슈팅

### 10.2 오류 추적 — 포털 "오류 로그" 화면 (우선)

**시스템 › 오류 로그** (SYS_ADMIN)

1. 출처(전체·대화·색인·관리 API)와 기간(1시간·24시간·7일)을 고르고, 채널명·문서명·오류 문구로 검색합니다.
2. 목록은 **대화 답변 실패**(채널·질문 앞부분), **색인 실패**(문서·단계), **관리 API 오류/권한 거부**를 최신순으로 보여 줍니다. 정상 취소(재색인 교체 등)는 제외됩니다.
3. 행을 누르면 오류 전문과 함께 **관련 로그**를 볼 수 있습니다. 관련 서비스는 오류 메시지의 대상 주소로 자동 선택되며(예: `reranker-api`), 다른 서비스로 바꿀 수 있습니다. 기본 시간 범위는 오류 시각 **5분 전 ~ 2분 후**입니다.
4. 로그는 파드별로 표시되고 Traceback·ERROR 줄은 빨간색입니다. 재시작된 파드는 이전 컨테이너 로그도 함께 보입니다. 비밀번호·토큰 등은 **마스킹**되어 표시됩니다.

알아둘 점:
- 로그 열람은 감사 로그에 `ERROR_LOG_VIEW` 로 기록됩니다(로그에 질문 원문이 포함될 수 있음).
- **색인 Job 로그는 완료·실패 1시간 후 Pod 와 함께 삭제**됩니다. 직전 재시작보다 앞선 컨테이너 로그, 노드의 로그 회전으로 지워진 로그는 볼 수 없습니다(중앙 로그 수집 없음, §8.3).
- [로그 조회] 가 `POD_LOGS_DISABLED`(503)면 파드 로그 조회가 꺼진 배포입니다(`POD_LOG_ACCESS=k8s`, chart `podLogs.enabled`). 아래 kubectl 절차를 쓰세요.

### 10.2.1 kubectl 로 추적 (대안)

```bash
# ① 실패한 대화 작업과 오류 — 어느 채널·시각·원인(예외 종류와 대상 URL)
kubectl -n rag-data exec sts/postgresql -- psql -U rag -d rag -c "
SELECT j.status, left(j.error,200) error, j.queued_at, c.name channel
  FROM chat_jobs j
  LEFT JOIN channel_conversations cc ON cc.id = j.conversation_id
  LEFT JOIN chat_channels c ON c.id::text = cc.channel_id::text
 ORDER BY j.queued_at DESC LIMIT 10;"

# ② rag-worker 로그 (replica 2개 모두) — Traceback 의 마지막 호출이 실패 지점
for p in $(kubectl -n rag-app get pods -o name | grep rag-worker); do
  echo "== $p"; kubectl -n rag-app logs $p --since=1h | grep -E "pipeline_failed|rerank_fallback|Traceback" -A3 | tail -40
done

# ③ 실패 지점 서비스 로그
kubectl -n rag-ai logs deploy/reranker-api  --since=1h | grep -v health    # .../internal/v1/rerank
kubectl -n rag-ai logs deploy/embedding-api --since=1h | grep -v health    # .../embeddings
kubectl -n rag-ai logs deploy/vllm-llm-0    --since=1h | tail -50           # .../v1/chat/completions
```

포털 **시스템 › 오류 로그** 또는 **서비스 운영 › 대화 작업**의 "실패만 보기"에서도 ①을 볼 수 있습니다. 오류 유형별 판단:

| `error` 패턴 | 원인 | 조치 |
|---|---|---|
| `ReadTimeout … [http://embedding-api…]` | 임베딩 지연 — 대개 대량 색인과 겹침 | 색인 완료 후 재질문, `INDEX_MAX_PARALLEL` 1 유지 |
| `HTTPStatusError: Server error '500' … reranker` | reranker 내부 오류 | reranker 로그 Traceback (가이드 §8 transformers 항목 등) |
| `ConnectError … vllm-service` / `ReadTimeout … /v1/chat/completions` | vLLM 미기동·재시작·과부하 | vLLM 파드 상태·로그, 로딩 완료 대기 |
| `CHANNEL_NOT_BOUND_OR_DISABLED` | 질문 직후 Binding 비활성화 | 채널 RAG 응답 확인 |

> reranker 시간 초과는 이제 답변 실패가 아니라 **벡터 순서로 대체 답변**하고 `worker.rerank_fallback` 경고만 남깁니다. 경고가 잦으면 §6.3 의 `VECTOR_TOP_K`·`RERANKER_MAX_LENGTH` 를 조정하세요.

### 10.3 증상별 조치

| 증상 | 원인 | 조치 |
|---|---|---|
| 모든 사용자 로그인 503 "인증 설정이 완료되지 않았습니다" | JWT 키/pepper Secret 누락(fail-closed) | `rag-chat-secrets` 키 확인, `startup.*_missing` 로그 |
| 맞는 비밀번호인데 로그인 401 | 계정 생성 시 다른 pepper 파일 사용 | 같은 pepper 로 재설정(포털 [비밀번호 재설정]) |
| 로그인 버튼 무반응 | HTTP 접속 | HTTPS 로 접속 |
| 모든 답변 "⚠️ 답변 생성 중 오류" | vLLM·embedding 장애 등 | §10.2 절차로 실패 URL 특정 → 해당 파드 로그 |
| 긴 PDF 채널 답변이 유독 느림 / `worker.rerank_fallback` 경고 반복 | CPU reranker 가 후보 수 × 긴 청크를 시간 내 처리 못함 | `VECTOR_TOP_K` 축소, `RERANKER_MAX_LENGTH=512`, 평가로 품질 확인(§6.2) |
| 답변이 엉뚱함 | embedding/reranker 가 mock 엔진 | `engine_ready` 의 `-mock` 확인, 모델 경로·권한 |
| 업로드는 됐는데 "근거 없음" | 허용 채널 없음 / 색인 미완료 / Scope 조건 | §5.2·§5.3·§4.1 확인 |
| 피드백 모두 401 | `feedback-signing-key` 누락/불일치 | Secret 확인 후 gateway·worker 재시작 |
| 답변이 실시간으로 안 나옴, 60초마다 끊김 | Ingress WebSocket 설정 | 가이드 §4.5 주석·`/ws` 경로 |
| 업로드 413 | Ingress 본문 크기 제한 / 100MB 초과 | `proxy-body-size 100m` 확인 |
| 색인 `TRIGGER_FAILED[k8s]` | Job 생성 RBAC/NetworkPolicy | 가이드 §8 |
| 큰 PDF 색인 EMBEDDING 실패 | 배치·타임아웃 설정 누락 | `EMBEDDING_MAX_BATCH=8`, `EMBEDDING_TIMEOUT=120` |
| 문서가 오래 `INDEXING` 에 머묾 | 앞 문서 색인 대기(정상) 또는 실패 | `index_jobs` 의 stage(`WAITING`=대기)·error 확인(§5.2) |
| 색인 Job Pod `OOMKilled` | 초대형·특수 형식 PDF 메모리 초과 | 분할 업로드 또는 `ingestion.resources.limits.memory` 상향 |
| 파드 `ImagePullBackOff` (HTTP/HTTPS 오류) | 노드 `registries.yaml` | 가이드 §1.5 |
| vLLM 기동 실패/CrashLoop | 모델 경로·권한·버전·인자 | `kubectl -n rag-ai logs deploy/vllm-llm-0` → 가이드 §8 vLLM 항목 |
| vLLM OOM / 급격한 지연 | GPU 통합 메모리 경합 | `--gpu-memory-utilization` 0.85 로 하향 |
| Qdrant 검색 1초 초과 | PVC 가 HDD 에 생성 | `kubectl get pvc -n rag-data` SC 확인 |
| 노드 DiskPressure, 파드 대량 Evicted | NVMe 고갈 | 미사용 이미지 정리 `sudo crictl rmi --prune`, PVC 위치 확인 |
| helm `ownership` 오류 | `-n rag-platform` 누락 | `scripts/redeploy_lab.sh` 사용 |
| 문서 채널 변경·비활성화·삭제 409 `INDEX_JOB_RUNNING` | 색인 진행 중 | 완료 후 재시도 |
| 오류 로그 [로그 조회] 503 `POD_LOGS_DISABLED` / 502 | 파드 로그 조회 미설정·권한·apiserver 접근 | 가이드 §8 오류 로그 항목, 임시로 §10.2.1 kubectl |
| 문서 비활성화·삭제 503 `SEARCH_INDEX_UNAVAILABLE` | admin-api → Qdrant 연결 실패 (상태 불변) | qdrant 파드, admin-api `QDRANT_URL` 확인 후 재시도 |
| [재색인] 409 `DOCUMENT_INACTIVE` | 비활성 문서 | [활성화] 사용 |

### 10.4 장애 공지

vLLM 재시작·모델 교체·노드 작업은 최대 10~15분 답변 불가가 생깁니다. 사용자에게는 "답변 생성 중 오류"가 보이므로 사전 공지하고, 작업 후 시험 질문으로 복구를 확인하세요.

---

## 11. 보안 운영 수칙

- **채널 격리 3중 장치**: 멤버십(비멤버 404), 검색 필터 강제, 실시간 room 제한. 배포 전 격리 게이트 `make test-isolation`(CH-001~010).
- **문서 ACL 은 최소 권한**: 문서는 필요한 채널에만 허용. 기밀 문서는 별도 채널 + Scope 로 분리.
- **Secret**: 파일 마운트만 사용, Helm values·Git·ConfigMap·이미지·로그에 넣지 않음. 임시 비밀번호는 1회만 표시되며 저장되지 않음. 최소 6개월 주기 교체 검토(pepper 제외 — §7.5).
- **관리자 포털**: 인증 프록시 필수, 클라이언트 `X-Auth-User` 헤더 제거. 퇴직·이동자는 `admin_users.status='INACTIVE'`.
- **채팅 사용자**: 퇴직·이동 시 즉시 [활성] 끄기 + 채널 멤버 제거.
- **네트워크**: NetworkPolicy default-deny, 외부 egress 없음. 앱 NS 는 `rag-platform=true` 라벨 필수.
- **컨테이너**: 비루트(uid 10001), 읽기 전용 루트 FS, 권한 상승 금지(vLLM 은 캐시 쓰기 예외).
- **폐쇄망**: 모델·패키지는 사내 반입 절차(해시·악성코드·라이선스 점검) 후 로컬 경로로만 로딩.
- **감사**: 관리자 변경은 `audit_logs` 에 자동 기록 — 포털 감사 로그 화면에서 주기적으로 점검(§8.4).

---

## 12. 알려진 제약과 우회 방법

| 제약 | 영향 | 우회 |
|---|---|---|
| 색인 실패 시 문서가 INDEXING 에 남음 | 상태로 실패 구분 불가 | `index_jobs` SQL(§5.2) |
| 품질 평가 화면 비어 있음 | 화면으로 조회 불가 | `make evaluate` |
| 설정 화면 값 미반영 | 튜닝 효과 없음 | Helm env(§6.3) |
| 대시보드 수치 일부 예시값/라벨 부정확 ("오늘", "24h", p95, 서비스 상태) | 오판 위험 | 피드백·대화 작업 화면, SQL 로 확인 |
| 관리자 계정 관리 화면 없음 | — | SQL(§2.3) |
| `channel_admin` 지정·이력 20턴 초과는 UI 불가 | — | API |
| 계정 잠금 없음, 임시 비밀번호 변경 강제 안 됨 | 보안 정책 보완 필요 | 속도 제한으로 대체, "임시 비밀번호" 태그 점검 |
| 지표 대부분 미구현, ServiceMonitor 없음 | 모니터링 공백 | 로그·SQL·gateway 지표로 보완 |
| 백업·보관기간 자동화 없음 | 데이터 손실·과다 보관 위험 | §9 수동 절차 |
| 동시 처리 상한(`CHAT_MAX_CONCURRENCY`) 미적용, 속도 제한 비원자 | 부하 시 지연 | rag-worker replica 로 조절 |
| 임베딩/리랭커 모델 미로딩 시 조용히 mock 동작 | 엉뚱한 답변 | 배포 후 `engine_ready` 필수 확인 |
| 채널 삭제/보관 기능 없음 | — | Binding 비활성화 + 멤버 제거 |
| 문서 삭제 시 원본 파일·벡터 물리 삭제 안 함 | 저장 공간 점유 (검색에서는 제외됨) | 필요 시 수동 정리 |

---

## 13. 부록 — 자주 쓰는 명령·상태값

### 13.1 명령 모음

```bash
# 전체 상태
kubectl get pods -A -l app.kubernetes.io/part-of=rag-platform -o wide
helm list -n rag-platform

# 재배포 / 롤백
scripts/redeploy_lab.sh [--dry-run|--skip-build]
helm rollback rag-platform -n rag-platform

# 관리자 API (랩)
export ADMIN=https://rag.lab.local CURL_CA_BUNDLE=$PWD/secrets/chat.crt; H='X-Auth-User: cklee'
curl -s $ADMIN/api/v1/documents -H "$H" | jq '.data[] | {title,status,allowed_channel_ids}'
curl -s $ADMIN/api/v1/chat/channels -H "$H" | jq '.data[] | {name,id}'
curl -s -X POST $ADMIN/api/v1/documents/<id>/reindex -H "$H" | jq .data

# DB 접속
kubectl -n rag-data exec -it sts/postgresql -- psql -U rag -d rag

# Qdrant 채널별 청크 수 (색인 반영 확인)
kubectl -n rag-ingestion run qdrant-count --rm -i --restart=Never \
  --image=registry.local:5000/rag/parser-indexer:$(git rev-parse --short HEAD) \
  --labels=app.kubernetes.io/part-of=rag-platform \
  --overrides='{"spec":{"nodeSelector":{"kubernetes.io/arch":"amd64"}}}' \
  --command -- python -c "from qdrant_client import QdrantClient, models as m; print(QdrantClient('http://qdrant.rag-data:6333').count('rag_chunks_v1', count_filter=m.Filter(must=[m.FieldCondition(key='allowed_channel_ids', match=m.MatchValue(value='<channel_id>'))])).count)"
```

### 13.2 상태값

| 대상 | 값 |
|---|---|
| 문서 | UPLOADED → INDEXING → ACTIVE ⇄ INACTIVE([비활성화] / [활성화]=재색인), → DELETED(종료) |
| 색인 Job (`index_jobs`) | PENDING(stage=WAITING: 슬롯 대기) → RUNNING → COMPLETED / FAILED, PENDING → CANCELLED(문서 비활성/삭제·재색인 교체) |
| 대화 작업 (`chat_jobs`) | QUEUED → RUNNING → COMPLETED / DELIVERY_FAILED / FAILED |
| Binding 모드 | DEDICATED_CHANNEL(전용) / TRIGGER_WORD(트리거 단어) |
| 대화 맥락 | CHANNEL(채널 컨텍스트) / THREAD(스레드 컨텍스트) / STATELESS(단발 질의) |
| 관리자 역할 | SYS_ADMIN / DOC_ADMIN / QUALITY_EVALUATOR / AUDITOR |
| 채팅 사용자 역할 | user / admin, 채널 역할 member / channel_admin |

### 13.3 관련 문서

| 문서 | 내용 |
|---|---|
| [`rke2_two_node_test_guide.md`](../../rke2_two_node_test_guide.md) | 설치(§1~4), 재배포(§4.6), E2E(§5), 성능·평가(§7), **트러블슈팅(§8)** |
| [`docs/TDD.md`](../TDD.md) | 설계(SSOT) |
| [`docs/PRD.md`](../PRD.md) | 요구사항·SLO·보존/백업 정책(§24) |
| [`docs/security-checklist.md`](../security-checklist.md) | 보안 점검 항목 |
| [사용자 매뉴얼](user-manual.md) | 최종 사용자 안내 |
