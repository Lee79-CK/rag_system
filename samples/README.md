# samples — 로컬/랩 E2E 용 샘플 문서

바이너리 PDF 는 리포에 넣지 않는다. parser-indexer 가 지원하는 `.md`(텍스트) 샘플로 업로드 → 색인 → 질의를 검증한다.

| 파일 | 대상 Channel(seed) | 카테고리 | 평가셋 연관 |
|---|---|---|---|
| `장애대응매뉴얼.md` | `channel-001` (rag-cloud-ops) | 장애대응 | `tests/evaluation/dataset/q001~q003` |
| `인사규정집.md` | `channel-002` (rag-hr, `!rag` 트리거) | 인사규정 | 격리(CH-001) 대조용 |

업로드 예 (admin-api, `X-Auth-User` 는 seed 계정):

```bash
curl -s -X POST http://localhost:8003/api/v1/documents -H 'X-Auth-User: cklee' \
  -F 'file=@samples/장애대응매뉴얼.md' -F 'title=장애대응매뉴얼' -F 'category=장애대응' \
  -F 'department=Cloud운영팀' -F 'security_level=INTERNAL' \
  -F 'allowed_channel_ids=channel-001' -F 'start_indexing=true'
```

`allowed_channel_ids` 를 비우면 색인은 되어도 어느 채널에서도 검색되지 않는다 (검색 전 Channel Filter — CH-001).
