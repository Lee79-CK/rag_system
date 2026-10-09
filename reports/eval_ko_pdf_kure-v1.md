# RAG 평가 리포트

- 총 문항: **8**
- 유형 분포: {'single_doc': 4, 'definition': 2, 'multi_doc': 1, 'no_answer': 1}

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
| kp001 | single_doc | True | False | 0 | [Errno 111] Connection refused |
| kp002 | single_doc | True | False | 0 | [Errno 111] Connection refused |
| kp003 | single_doc | True | False | 0 | [Errno 111] Connection refused |
| kp004 | definition | True | False | 0 | [Errno 111] Connection refused |
| kp005 | single_doc | True | False | 0 | [Errno 111] Connection refused |
| kp006 | definition | True | False | 0 | [Errno 111] Connection refused |
| kp007 | multi_doc | True | False | 0 | [Errno 111] Connection refused |
| kp008 | no_answer | False | False | 0 | [Errno 111] Connection refused |
