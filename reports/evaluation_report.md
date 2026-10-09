# RAG 평가 리포트

- 총 문항: **6**
- 유형 분포: {'single_doc': 1, 'multi_doc': 1, 'table': 1, 'definition': 1, 'no_answer': 1, 'ambiguous': 1}

## 지표 (PRD §8.1 목표 대비)

| 지표 | 결과 | 목표 | 판정 |
|---|---:|---:|:--:|
| 검색 Recall@10 | 0.0% | 85% | ❌ |
| Citation Precision | 0.0% | 90% | ❌ |
| 무근거 안전응답률 | 0.0% | 90% | ❌ |
| 근거 응답률(answerable) | 100.0% | — | — |

## 문항별 결과

| id | type | answerable | 근거부족 | citations | error |
|---|---|:--:|:--:|---:|---|
| q001 | single_doc | True | False | 0 | Server error '500 Internal Server Error' for url 'http://localhost:8002/internal/v1/rag/completions'
For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/500 |
| q002 | multi_doc | True | False | 0 | Server disconnected without sending a response. |
| q003 | table | True | False | 0 | Server error '500 Internal Server Error' for url 'http://localhost:8002/internal/v1/rag/completions'
For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/500 |
| q004 | definition | True | False | 0 | Server disconnected without sending a response. |
| q005 | no_answer | False | False | 0 | Server error '500 Internal Server Error' for url 'http://localhost:8002/internal/v1/rag/completions'
For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/500 |
| q006 | ambiguous | False | False | 0 | Server disconnected without sending a response. |
